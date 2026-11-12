"""CONTRACT-003: append-only, atomic loads of verified archived reports."""
from dataclasses import astuple, fields
import logging
import sqlite3

from icontract import ensure, require

from .clock import Clock
from .collect import file_hash
from .config import Config
from .errors import ArchiveIntegrityError
from .parse import parse_report
from .parse.models import ParsedReport

REPORT_TYPES = {
    'Downtime Summary.xls': 'downtime_summary',
    'Production Summary.xls': 'production_summary',
    'Production Todate.xls': 'production_todate',
}
MAIN_TABLES = {
    'downtime_summary': ('downtime_alarm', 'alarms'),
    'production_summary': ('production_summary_breakdown', 'breakdown'),
    'production_todate': ('production_todate_day', 'days'),
}


def _insert_record(database, table, load_id, record):
    # Table and field names come exclusively from code-owned report models.
    columns = ', '.join(field.name for field in fields(record))
    values = (load_id, *astuple(record))
    placeholders = ', '.join('?' for _ in values)
    database.execute(f'INSERT INTO {table} (file_load_id, {columns}) '
                     f'VALUES ({placeholders})', values)


@ensure(lambda database, report, result: database.execute(
    f'SELECT COUNT(*) FROM {MAIN_TABLES[report.report_type][0]} WHERE file_load_id=?',
    (result,)).fetchone()[0] == len(getattr(report, MAIN_TABLES[report.report_type][1])),
    enabled=True)
def _insert_report(database, archived_id, timestamp, report: ParsedReport):
    table, attribute = MAIN_TABLES[report.report_type]
    records = getattr(report, attribute)
    cursor = database.execute(
        'INSERT INTO file_load (archived_file_id, report_type, loaded_at, printed_at, '
        'report_start, report_end, recipe, page_count, record_count) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (archived_id, report.report_type, timestamp, *astuple(report.header),
         report.page_count, len(records)))
    load_id = cursor.lastrowid
    if report.report_type == 'downtime_summary':
        _insert_record(database, 'downtime_total', load_id, report.grand_total)
    elif report.report_type == 'production_summary':
        _insert_record(database, 'production_summary_kpi', load_id, report.kpis)
    for record in records:
        _insert_record(database, table, load_id, record)
    return load_id


@require(lambda database: not database.in_transaction, enabled=True)
def load_stage(config: Config, database: sqlite3.Connection, clock: Clock) -> bool:
    """Load every pending report; caller holds the run lock and passed precheck.

    Configuration and database schema must already be validated. A failed
    failure-history write is logged and contributes False, like any file failure.
    """
    logger = logging.getLogger('raptor_etl')
    pending = database.execute(
        'SELECT a.id, a.original_name, a.archive_name, a.sha256 FROM archived_file a '
        'WHERE a.original_name IN (?, ?, ?) AND NOT EXISTS '
        '(SELECT 1 FROM file_load f WHERE f.archived_file_id=a.id) '
        'ORDER BY a.archived_at, a.id', tuple(REPORT_TYPES)).fetchall()
    succeeded = True
    for archived_id, original_name, archive_name, expected_hash in pending:
        timestamp = clock.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            path = config.archive_dir / archive_name
            try:
                actual_hash = file_hash(path)
            except OSError:
                raise ArchiveIntegrityError('archive file is missing or unreadable') from None
            if actual_hash != expected_hash:
                raise ArchiveIntegrityError('archive SHA-256 does not match recorded hash')
            report = parse_report(path, REPORT_TYPES[original_name])
            with database:
                _insert_report(database, archived_id, timestamp, report)
            count = len(getattr(report, MAIN_TABLES[report.report_type][1]))
            logger.info('%s: loaded record_count=%s', archive_name, count)
        except Exception as error:
            succeeded = False
            logger.error('%s: failed %s: %s', archive_name, type(error).__name__, error)
            try:
                with database:
                    database.execute(
                        'INSERT INTO load_failure (archived_file_id, attempted_at, '
                        'error_type, error_message) VALUES (?, ?, ?, ?)',
                        (archived_id, timestamp, type(error).__name__, str(error)))
            except sqlite3.Error:
                logger.error('%s: could not record load_failure', archive_name)
    return succeeded
