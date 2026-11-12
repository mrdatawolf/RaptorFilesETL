"""Offline CONTRACT-003 validation without CLI wiring."""
from dataclasses import astuple
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
import shutil
import sqlite3
from zoneinfo import ZoneInfo

import pytest

from raptor_etl import load
from raptor_etl.clock import Clock
from raptor_etl.config import Config
from raptor_etl.database import CURRENT_VERSION, open_database
from raptor_etl.errors import ConfigError, LayoutError, ReconciliationError
from raptor_etl.parse import parse_report

SAMPLES = Path(__file__).resolve().parents[1] / 'Samples'
REPORT_TABLES = ('downtime_alarm', 'downtime_total', 'production_summary_kpi',
                 'production_summary_breakdown', 'production_todate_day')
ALL_TABLES = ('archived_file', 'file_load', 'load_failure', *REPORT_TABLES)


@pytest.fixture
def environment(tmp_path):
    archive = tmp_path / 'archive'
    archive.mkdir()
    config = Config(str(tmp_path), archive, tmp_path / 'bronze.db',
                    ZoneInfo('America/Los_Angeles'), '23:00', (0,), 'INFO', None, None, None)
    clock = Clock(config.timezone, lambda: datetime(2026, 11, 11, 7, 30, tzinfo=timezone.utc))
    db = open_database(config.db_path)
    yield config, db, clock
    db.close()


def archive_file(environment, name, content, archived_at='2026-11-10 23:00:00'):
    config, db, _ = environment
    archived = f'{db.execute("SELECT COUNT(*) FROM archived_file").fetchone()[0]}_{name}'
    (config.archive_dir / archived).write_bytes(content)
    with db:
        cursor = db.execute(
            'INSERT INTO archived_file (original_name, archive_name, copy_date, sha256, '
            'size_bytes, archived_at) VALUES (?, ?, ?, ?, ?, ?)',
            (name, archived, '2026-11-10', hashlib.sha256(content).hexdigest(), len(content), archived_at))
    return cursor.lastrowid, config.archive_dir / archived


@pytest.fixture
def samples(environment, tmp_path):
    if not SAMPLES.is_dir():
        pytest.skip('Samples/ is absent; load tests require a temporary copy of Samples/')
    source = tmp_path / 'source'
    shutil.copytree(SAMPLES, source)
    for path in sorted(source.iterdir()):
        if path.is_file():
            archive_file(environment, path.name, path.read_bytes())
    return environment


def counts(db):
    return {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            for table in ALL_TABLES}


def test_sample_values_lineage_idempotency_and_append_only(samples, caplog):
    config, db, clock = samples
    statements = []
    db.set_trace_callback(statements.append)
    caplog.set_level(logging.INFO, logger='raptor_etl')
    assert load.load_stage(config, db, clock)
    result = counts(db)
    assert [result[t] for t in ('file_load', 'downtime_alarm', 'downtime_total',
                                'production_summary_kpi', 'production_todate_day')] == [3, 20, 1, 1, 81]
    assert result['load_failure'] == 0
    assert db.execute("SELECT slow_pct FROM production_todate_day WHERE run_start LIKE '2026-09-23%'").fetchall() == [(None,)]
    assert db.execute('SELECT avg_bf_per_piece FROM production_summary_kpi').fetchone()[0] == 2.8713249629155975
    assert db.execute("SELECT run_start FROM production_todate_day WHERE run_start LIKE '2026-09-16%' ORDER BY run_start").fetchall() == [
        ('2026-09-16 05:00:02',), ('2026-09-16 15:40:02',)]
    # Compare every stored field, including NULLs, precision, metadata and order.
    for row in db.execute('SELECT f.id, a.archive_name, f.report_type, f.printed_at, '
                          'f.report_start, f.report_end, f.recipe, f.page_count, '
                          'f.record_count, f.loaded_at FROM file_load f '
                          'JOIN archived_file a ON a.id=f.archived_file_id'):
        load_id, name, kind, *metadata = row
        parsed = parse_report(config.archive_dir / name, kind)
        table, attr = load.MAIN_TABLES[kind]
        records = getattr(parsed, attr)
        assert metadata == [*astuple(parsed.header), parsed.page_count, len(records), '2026-11-10 23:30:00']
        assert db.execute(f'SELECT * FROM {table} WHERE file_load_id=? ORDER BY row_order',
                          (load_id,)).fetchall() == [(load_id, *astuple(record)) for record in records]
        for header_table, record in (('downtime_total', parsed.grand_total),
                                     ('production_summary_kpi', parsed.kpis)):
            if record is not None:
                assert db.execute(f'SELECT * FROM {header_table} WHERE file_load_id=?',
                                  (load_id,)).fetchall() == [(load_id, *astuple(record))]
    assert load.load_stage(config, db, clock)
    assert counts(db) == result
    assert caplog.text.count(': loaded record_count=') == 3
    assert not any(sql.lstrip().upper().startswith(('UPDATE', 'DELETE', 'REPLACE')) for sql in statements)
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('error_type', [LayoutError, ReconciliationError])
def test_parse_failure_retry_after_parser_fix(samples, monkeypatch, error_type):
    config, db, clock = samples
    original = load.parse_report
    def broken(path, kind):
        if kind == 'downtime_summary':
            raise error_type('fixture layout rejected')
        return original(path, kind)
    monkeypatch.setattr(load, 'parse_report', broken)
    assert not load.load_stage(config, db, clock)
    assert counts(db)['file_load'] == 2
    assert counts(db)['downtime_alarm'] == counts(db)['downtime_total'] == 0
    assert db.execute('SELECT error_type, error_message, attempted_at FROM load_failure').fetchall() == [
        (error_type.__name__, 'fixture layout rejected', '2026-11-10 23:30:00')]
    monkeypatch.setattr(load, 'parse_report', original)
    assert load.load_stage(config, db, clock)
    assert counts(db)['file_load'] == 3
    assert counts(db)['load_failure'] == 1


def test_parse_failure_retry_after_fixture_restored(samples, monkeypatch):
    config, db, clock = samples
    original = load.parse_report
    target = next(config.archive_dir.glob('*Downtime Summary.xls'))
    valid = target.read_bytes()
    # Corrupt only after verification, then restore the exact archived bytes.
    def broken(path, kind):
        if kind == 'downtime_summary':
            path.write_bytes(b'invalid workbook')
        return original(path, kind)
    monkeypatch.setattr(load, 'parse_report', broken)
    assert not load.load_stage(config, db, clock)
    assert counts(db)['downtime_alarm'] == counts(db)['downtime_total'] == 0
    assert db.execute('SELECT error_type FROM load_failure').fetchall() == [('LayoutError',)]
    target.write_bytes(valid)
    monkeypatch.setattr(load, 'parse_report', original)
    assert load.load_stage(config, db, clock)
    assert counts(db)['file_load'] == 3
    assert counts(db)['load_failure'] == 1


@pytest.mark.parametrize('table,condition', [('downtime_alarm', 'NEW.row_order=3'),
                                           ('production_summary_breakdown', 'NEW.row_order=3'),
                                           ('production_todate_day', 'NEW.row_order=3')])
def test_mid_transaction_rollback_and_retry(samples, table, condition):
    config, db, clock = samples
    db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} WHEN {condition} "
               "BEGIN SELECT RAISE(FAIL, 'injected write failure'); END")
    assert not load.load_stage(config, db, clock)
    assert counts(db)['file_load'] == 2
    assert counts(db)[table] == 0
    if table == 'downtime_alarm':
        assert counts(db)['downtime_total'] == 0
    if table == 'production_summary_breakdown':
        assert counts(db)['production_summary_kpi'] == 0
    assert db.execute('SELECT error_type, error_message FROM load_failure').fetchall() == [
        ('IntegrityError', 'injected write failure')]
    db.execute('DROP TRIGGER injected')
    assert load.load_stage(config, db, clock)
    assert counts(db)['file_load'] == 3
    assert counts(db)['load_failure'] == 1


@pytest.mark.parametrize('missing', [False, True])
def test_archive_integrity_before_parse(environment, monkeypatch, missing, caplog):
    config, db, clock = environment
    _, path = archive_file(environment, 'Downtime Summary.xls', b'original')
    if missing:
        path.unlink()
    else:
        path.write_bytes(b'tampered')
    def unexpected(*args):
        pytest.fail('integrity failure must not call parser')
    monkeypatch.setattr(load, 'parse_report', unexpected)
    for _ in range(2):
        assert not load.load_stage(config, db, clock)
    assert counts(db)['file_load'] == 0
    assert db.execute('SELECT error_type FROM load_failure').fetchall() == [('ArchiveIntegrityError',)] * 2
    assert caplog.text.count(': failed ArchiveIntegrityError:') == 2


def test_selection_oldest_first_and_retry(environment, monkeypatch):
    config, db, clock = environment
    for index, name in enumerate((*load.REPORT_TYPES, 'Thickness Breakdown.xls',
                                  'Downtime Summary.pdf', 'Production Summary.pdf',
                                  'Production Todate.pdf', 'Thickness Breakdown.pdf', 'downtime summary.xls')):
        archive_file(environment, name, str(index).encode(), f'2026-11-{10-index:02} 00:00:00')
    called = []
    def rejected(path, kind):
        called.append(kind)
        raise LayoutError('retry me')
    monkeypatch.setattr(load, 'parse_report', rejected)
    assert not load.load_stage(config, db, clock)
    assert not load.load_stage(config, db, clock)
    assert called == ['production_todate', 'production_summary', 'downtime_summary'] * 2
    assert counts(db)['load_failure'] == 6


def test_no_pending_files(environment):
    assert load.load_stage(*environment)
    assert counts(environment[1]) == dict.fromkeys(ALL_TABLES, 0)


def test_failure_history_write_unavailable(environment, caplog):
    config, db, clock = environment
    archive_file(environment, 'Downtime Summary.xls', b'not a workbook')
    db.execute("CREATE TRIGGER injected BEFORE INSERT ON load_failure BEGIN SELECT RAISE(FAIL, 'unavailable'); END")
    assert not load.load_stage(config, db, clock)
    assert counts(db)['file_load'] == counts(db)['load_failure'] == 0
    assert 'could not record load_failure' in caplog.text


def test_schema_version_and_constraints(samples):
    config, db, clock = samples
    assert db.execute('PRAGMA user_version').fetchone()[0] == CURRENT_VERSION
    assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert load.load_stage(config, db, clock)
    for table in ('file_load', *REPORT_TABLES):
        with pytest.raises(sqlite3.IntegrityError), db:
            db.execute(f'INSERT INTO {table} SELECT * FROM {table} LIMIT 1')
    with pytest.raises(sqlite3.IntegrityError), db:
        db.execute("INSERT INTO downtime_total VALUES (999999, 1, '00:00:01')")
    with pytest.raises(sqlite3.IntegrityError), db:
        db.execute('INSERT INTO production_todate_day SELECT file_load_id, row_order+1000, '
                   'run_start, fast_pct, medium_pct, slow_pct, lug_fill, bf_per_piece, '
                   'trimloss, total_stops, downtime, volume FROM production_todate_day LIMIT 1')


def test_newer_schema_rejected_without_writes(tmp_path):
    path = tmp_path / 'newer.db'
    with sqlite3.connect(path) as db:
        db.execute(f'PRAGMA user_version={CURRENT_VERSION+1}')
    before = path.read_bytes()
    with pytest.raises(ConfigError, match='newer'):
        open_database(path)
    assert path.read_bytes() == before
