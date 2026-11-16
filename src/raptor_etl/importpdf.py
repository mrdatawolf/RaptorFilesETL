"""CONTRACT-004: manual, last-resort backfill of reports from PDF exports."""
import hashlib
import logging
from pathlib import Path
import sqlite3

from icontract import require

from .collect import CHUNK_SIZE, file_hash
from .errors import ArchiveIntegrityError
from .load import _insert_report
from .parse.pdf import parse_pdf_report, pdf_printed_at

# Lowercase file name -> (canonical name as spelled on the share, report type).
CANDIDATES = {
    'production summary.pdf': ('Production Summary.pdf', 'production_summary'),
    'production todate.pdf': ('Production Todate.pdf', 'production_todate'),
}


def _archive(config, path, canonical, copy_date, digest):
    """Copy into the archive via a verified partial file; never replace a file."""
    archive_name = f'{copy_date}_{canonical}'
    final = config.archive_dir / archive_name
    partial = config.archive_dir / f'.{archive_name}.partial'
    try:
        if final.exists():
            if file_hash(final) != digest:
                raise ArchiveIntegrityError('archive name has different content')
            return archive_name, final.stat().st_size
        copied = hashlib.sha256()
        size = 0
        with path.open('rb') as incoming, partial.open('wb') as outgoing:
            for chunk in iter(lambda: incoming.read(CHUNK_SIZE), b''):
                copied.update(chunk)
                outgoing.write(chunk)
                size += len(chunk)
        if copied.hexdigest() != digest or file_hash(partial) != digest:
            raise ArchiveIntegrityError('copy verification failed')
        partial.rename(final)
        return archive_name, size
    finally:
        partial.unlink(missing_ok=True)


def _import_one(config, database, clock, path, canonical, report_type):
    """Return the log text for one candidate; raise for a failure without a database row."""
    digest = file_hash(path)
    existing = database.execute(
        'SELECT a.id, a.archive_name, EXISTS(SELECT 1 FROM file_load f WHERE f.archived_file_id=a.id) '
        'FROM archived_file a WHERE a.original_name=? AND a.sha256=?',
        (canonical, digest)).fetchone()
    if existing and existing[2]:
        return True, 'skipped: already loaded'
    try:
        report, error = parse_pdf_report(path, report_type), None
    except Exception as failure:
        report, error = None, failure
    printed_at = report.header.printed_at if report else pdf_printed_at(path, report_type)
    if report and printed_at:
        day = printed_at[:10]
        xls_loaded = database.execute(
            "SELECT 1 FROM file_load f JOIN archived_file a ON a.id=f.archived_file_id "
            "WHERE f.report_type=? AND lower(a.original_name) LIKE '%.xls' "
            "AND substr(f.printed_at, 1, 10)=?", (report_type, day)).fetchone()
        if xls_loaded:
            return True, f'skipped: xls already loaded for {day}'
    now = clock.now()
    timestamp = now.strftime('%Y-%m-%d %H:%M:%S')
    if existing:
        archived_id, archive_name = existing[0], existing[1]
    else:
        copy_date = printed_at[:10] if printed_at else now.strftime('%Y-%m-%d')
        archive_name, size = _archive(config, path, canonical, copy_date, digest)
        with database:
            archived_id = database.execute(
                'INSERT INTO archived_file (original_name, archive_name, copy_date, sha256, '
                'size_bytes, archived_at) VALUES (?, ?, ?, ?, ?, ?)',
                (canonical, archive_name, copy_date, digest, size, timestamp)).lastrowid
    if report is not None:
        try:
            with database:
                _insert_report(database, archived_id, timestamp, report)
            count = len(report.breakdown or report.days)
            return True, f'loaded record_count={count} archive={archive_name}'
        except Exception as failure:
            error = failure
    try:
        with database:
            database.execute(
                'INSERT INTO load_failure (archived_file_id, attempted_at, error_type, '
                'error_message) VALUES (?, ?, ?, ?)',
                (archived_id, timestamp, type(error).__name__, str(error)))
    except sqlite3.Error:
        return False, f'failed {type(error).__name__}: {error} (could not record load_failure)'
    return False, f'failed {type(error).__name__}: {error}'


@require(lambda database: not database.in_transaction, enabled=True)
def import_pdfs(config, database, clock, folder: Path) -> bool:
    """Import every candidate PDF under folder; caller holds the run lock.

    Returns False when at least one candidate failed (exit code 1).
    """
    logger = logging.getLogger('raptor_etl')
    succeeded = True
    for path in sorted((p for p in folder.rglob('*') if p.is_file()),
                       key=lambda p: p.relative_to(folder).as_posix()):
        relative = path.relative_to(folder).as_posix()
        candidate = CANDIDATES.get(path.name.lower())
        if candidate is None:
            if path.suffix.lower() == '.pdf':
                logger.info('%s: ignored: not supported', relative)
            continue
        try:
            ok, message = _import_one(config, database, clock, path, *candidate)
        except Exception as error:
            ok, message = False, f'failed {type(error).__name__}: {error}'
        succeeded = succeeded and ok
        logger.log(logging.INFO if ok else logging.ERROR, '%s: %s', relative, message)
    return succeeded
