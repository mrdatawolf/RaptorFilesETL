"""CLI collect-to-bronze validation using scratch copies of Samples/."""
from datetime import datetime, timezone
import shutil
import sqlite3

import pytest

from raptor_etl import cli
from raptor_etl.clock import Clock

TABLES = ('archived_file', 'file_load', 'load_failure', 'downtime_alarm',
          'downtime_total', 'production_summary_kpi',
          'production_summary_breakdown', 'production_todate_day')


@pytest.fixture
def sample_run(configured, monkeypatch, make_share):
    make_share(configured / 'source')
    archive = configured / 'archive'
    archive.mkdir()
    monkeypatch.setenv('RAPTOR_ARCHIVE_DIR', str(archive))
    monkeypatch.setattr(cli, 'Clock', lambda zone: Clock(
        zone, lambda: datetime(2026, 11, 11, 7, 30, tzinfo=timezone.utc)))
    return configured


def counts(db):
    return {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            for table in TABLES}


def test_first_and_second_run(sample_run):
    assert cli.main(['run']) == 0
    with sqlite3.connect(sample_run / 'bronze.db') as db:
        first = counts(db)
        assert first == dict(zip(TABLES, (3, 3, 0, 20, 1, 1, 34, 81)))
        assert dict(db.execute('SELECT report_type, record_count FROM file_load')) == {
            'downtime_summary': 20, 'production_summary': 34, 'production_todate': 81}
        assert dict(db.execute('SELECT section, COUNT(*) FROM production_summary_breakdown '
                               'WHERE is_total=1 GROUP BY section')) == dict.fromkeys(
                                   ('product', 'length', 'grade', 'width'), 1)
        before = {table: db.execute(f'SELECT * FROM {table}').fetchall() for table in TABLES}
    assert cli.main(['run']) == 0
    with sqlite3.connect(sample_run / 'bronze.db') as db:
        assert counts(db) == first
        assert {table: db.execute(f'SELECT * FROM {table}').fetchall()
                for table in TABLES} == before


@pytest.mark.parametrize('source_state', ['missing', 'unreachable'])
def test_source_precheck_never_calls_stages(sample_run, monkeypatch, source_state):
    if source_state == 'missing':
        shutil.rmtree(sample_run / 'source')
    else:
        from raptor_etl.source import LocalSource

        def denied(self):
            raise PermissionError('injected directory listing failure')

        monkeypatch.setattr(LocalSource, 'names', denied)
    calls = []
    monkeypatch.setattr(cli, 'load_stage', lambda *args: calls.append('load') or True)
    monkeypatch.setattr(cli, 'collect_stage', lambda *args: calls.append('collect') or True)
    assert cli.main(['run']) == 4
    assert calls == []
    assert not (sample_run / 'bronze.db').exists()
    assert list((sample_run / 'archive').iterdir()) == []


def test_corrupt_archive_load_fails_after_successful_collect(sample_run, monkeypatch):
    collect = cli.collect_stage
    collected = []

    def collect_then_corrupt(config, database, clock):
        result = collect(config, database, clock)
        collected.append(result)
        target, = config.archive_dir.glob('*_Downtime Summary.xls')
        target.write_bytes(b'corrupted archived workbook')
        return result

    monkeypatch.setattr(cli, 'collect_stage', collect_then_corrupt)
    assert cli.main(['run']) == 1
    assert collected == [True]
    with sqlite3.connect(sample_run / 'bronze.db') as db:
        assert counts(db) == dict(zip(TABLES, (3, 2, 1, 0, 0, 1, 34, 81)))
        assert db.execute('SELECT error_type FROM load_failure').fetchall() == [
            ('ArchiveIntegrityError',)]
        assert set(dict(db.execute('SELECT report_type, record_count FROM file_load'))) == {
            'production_summary', 'production_todate'}


def test_empty_day_run_loads_empty_reports(configured, monkeypatch, make_share):
    """CONTRACT-003 "Empty reports": the 2026-11-13 no-production day (XLS/11_11_2026)."""
    make_share(configured / 'source', xls_day='11_11_2026')
    archive = configured / 'archive'
    archive.mkdir()
    monkeypatch.setenv('RAPTOR_ARCHIVE_DIR', str(archive))
    monkeypatch.setattr(cli, 'Clock', lambda zone: Clock(
        zone, lambda: datetime(2026, 11, 14, 7, 0, tzinfo=timezone.utc)))
    assert cli.main(['run']) == 0
    with sqlite3.connect(configured / 'bronze.db') as db:
        assert dict(db.execute('SELECT report_type, record_count FROM file_load')) == {
            'downtime_summary': 0, 'production_summary': 4, 'production_todate': 80}
        assert counts(db) == dict(zip(TABLES, (3, 3, 0, 0, 1, 1, 4, 80)))
        assert db.execute('SELECT occurrences, total_duration FROM downtime_total').fetchall() == [(0, None)]
        assert db.execute('SELECT section, label, is_total, pieces FROM production_summary_breakdown '
                          'ORDER BY row_order').fetchall() == [
            ('product', 'Total', 1, 0), ('length', 'Total', 1, 0),
            ('grade', 'Total', 1, 0), ('width', 'Total', 1, 0)]


def test_report_rows_stable_after_vacuum_and_rerun(sample_run):
    from contextlib import closing

    def report_rows(db):
        return {table: db.execute(f'SELECT rowid, * FROM {table} ORDER BY rowid').fetchall()
                for table in TABLES[3:]}

    assert cli.main(['run']) == 0
    with closing(sqlite3.connect(sample_run / 'bronze.db')) as db:
        before = report_rows(db)
        assert all(before.values())
        db.execute('VACUUM')
        assert report_rows(db) == before
    assert cli.main(['run']) == 0
    with closing(sqlite3.connect(sample_run / 'bronze.db')) as db:
        assert report_rows(db) == before
