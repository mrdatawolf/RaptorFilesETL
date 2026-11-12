"""CONTRACT-001: verified, dated copies with independent per-file outcomes."""
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path

from icontract import ensure

from .errors import ArchiveIntegrityError
from .precheck import precheck
from .source import scrub_password, source_error

EXPECTED_FILES = tuple(f'{report}.{extension}' for report in (
    'Downtime Summary', 'Production Summary', 'Production Todate', 'Thickness Breakdown'
) for extension in ('pdf', 'xls'))
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class CollectOutcome:
    original_name: str
    outcome: str
    archive_name: str | None = None
    sha256: str | None = None
    reason: str = ''


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _copy(source, name, partial):
    digest = hashlib.sha256()
    size = 0
    with source.open(name) as incoming, partial.open('wb') as outgoing:
        for chunk in iter(lambda: incoming.read(CHUNK_SIZE), b''):
            digest.update(chunk)
            outgoing.write(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


@ensure(lambda result: len(result) == len(EXPECTED_FILES), enabled=True)
@ensure(lambda result: tuple(item.original_name for item in result) == EXPECTED_FILES, enabled=True)
def collect(config, database, clock) -> list[CollectOutcome]:
    """Called under the run lock, after configuration/database validation."""
    source, names = precheck(config)
    started = clock.now()
    copy_date = started.strftime('%Y-%m-%d')
    logger = logging.getLogger('raptor_etl')
    outcomes = []
    cleanup_failed = set()
    for name in EXPECTED_FILES:
        try:
            for partial in config.archive_dir.glob(f'.????-??-??_{name}.partial'):
                partial.unlink()
        except OSError:
            cleanup_failed.add(name)
    for name in EXPECTED_FILES:
        archive_name = f'{copy_date}_{name}'
        final = config.archive_dir / archive_name
        partial = config.archive_dir / f'.{archive_name}.partial'
        digest = None
        status, reason, recorded_name = 'failed', '', None
        try:
            if name in cleanup_failed:
                raise OSError('stale partial cleanup failed')
            if name not in names:
                status, reason = 'missing', 'expected source file absent'
            else:
                digest, size = _copy(source, name, partial)
                previous = database.execute(
                    'SELECT archive_name FROM archived_file WHERE original_name=? AND sha256=?',
                    (name, digest)).fetchone()
                if previous:
                    status, recorded_name = 'unchanged', previous[0]
                else:
                    if final.exists():
                        if file_hash(final) != digest:
                            raise ArchiveIntegrityError('archive name has different content')
                    else:
                        if file_hash(partial) != digest:
                            raise ArchiveIntegrityError('copy verification failed')
                        # The run lock serializes archive writers. Never replace an existing file.
                        partial.rename(final)
                    with database:
                        database.execute(
                            'INSERT INTO archived_file (original_name, archive_name, copy_date, '
                            'sha256, size_bytes, archived_at) VALUES (?, ?, ?, ?, ?, ?)',
                            (name, archive_name, copy_date, digest, size,
                             started.strftime('%Y-%m-%d %H:%M:%S')))
                    status, recorded_name = 'archived', archive_name
        except ArchiveIntegrityError as error:
            reason = str(error)
        except Exception as error:
            reason = source_error(error, config.smb_password,
                                  local=not config.source_path.startswith(('//', '\\\\')),
                                  path=config.source_path, username=config.smb_username).reason
        finally:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                status, reason = 'failed', 'partial cleanup failed'
        reason = scrub_password(reason, config.smb_password)
        outcome = CollectOutcome(name, status, recorded_name, digest, reason)
        outcomes.append(outcome)
        logger.log(logging.ERROR if status in ('missing', 'failed') else logging.INFO,
                   '%s', scrub_password(
                       '%s: %s archive=%s sha256=%s %s' % (
                           name, status, recorded_name or '-',
                           digest[:12] if digest else '-', reason),
                       config.smb_password))
    return outcomes
