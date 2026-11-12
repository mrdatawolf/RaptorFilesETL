import sqlite3

import pytest

from raptor_etl import cli
from raptor_etl.database import CURRENT_VERSION, MIGRATIONS, open_database

TABLES = {'archived_file', 'file_load', 'load_failure', 'downtime_alarm',
          'downtime_total', 'production_summary_kpi', 'production_summary_breakdown',
          'production_todate_day'}


def seed(db):
    db.execute("INSERT INTO archived_file VALUES (1,'a','archive','2026-01-01',?,1,'now')", ('a' * 64,))
    db.execute("INSERT INTO file_load VALUES (1,1,'downtime_summary','now','now',NULL,NULL,NULL,1,0)")


def test_schema(tmp_path):
    db = open_database(tmp_path / 'db')
    assert db.execute('PRAGMA user_version').fetchone()[0] == CURRENT_VERSION == len(MIGRATIONS)
    assert {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} == TABLES
    assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    for table in TABLES - {'archived_file'}:
        assert len(db.execute(f'PRAGMA foreign_key_list({table})').fetchall()) == 1
    seed(db)
    db.commit()
    db.close()
    db = open_database(tmp_path / 'db')
    assert db.execute('SELECT count(*) FROM file_load').fetchone()[0] == 1
    db.close()


@pytest.mark.parametrize('statement', [
    "INSERT INTO archived_file VALUES (2,'b','archive','date',printf('%064d',0),1,'now')",
    "INSERT INTO archived_file VALUES (2,'a','other','date',replace(printf('%064d',0),'0','a'),1,'now')",
    "INSERT INTO file_load SELECT 2,archived_file_id,report_type,loaded_at,printed_at,report_start,report_end,recipe,page_count,record_count FROM file_load",
    "INSERT INTO load_failure VALUES (1,999,'now','LayoutError','bad')",
    "INSERT INTO archived_file VALUES (2,'b','b','date','BAD',1,'now')",
    "INSERT INTO file_load VALUES (2,999,'bad','now','now',NULL,NULL,NULL,1,0)",
    "INSERT INTO production_summary_breakdown VALUES (1,0,'invalid','x',0,NULL,NULL,NULL)",
    "INSERT INTO production_summary_breakdown VALUES (1,0,'grade','x',2,NULL,NULL,NULL)",
])
def test_lineage_and_checks(tmp_path, statement):
    db = open_database(tmp_path / 'db')
    seed(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(statement)
    db.close()


@pytest.mark.parametrize('table,values', [
    ('downtime_alarm', "1,0,1,'alarm',NULL,NULL,NULL,NULL"),
    ('downtime_total', '1,NULL,NULL'),
    ('production_summary_kpi', '1,NULL,NULL,NULL,NULL,NULL,NULL'),
    ('production_summary_breakdown', "1,0,'grade','label',0,NULL,NULL,NULL"),
    ('production_todate_day', "1,0,'start',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL"),
])
def test_report_uniques_foreign_keys_and_not_null(tmp_path, table, values):
    db = open_database(tmp_path / 'db')
    seed(db)
    db.execute(f'INSERT INTO {table} VALUES ({values})')
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(f'INSERT INTO {table} VALUES ({values})')
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(f'INSERT INTO {table} VALUES (999,{values.split(",", 1)[1]})')
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(f'INSERT INTO {table} VALUES (NULL,{values.split(",", 1)[1]})')
    if table == 'production_todate_day':
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f'INSERT INTO {table} VALUES ({values.replace("1,0,", "1,1,", 1)})')
    # Every declared NOT NULL column rejects NULL independently.
    db.execute(f'DELETE FROM {table}')
    for column in db.execute(f'PRAGMA table_info({table})').fetchall():
        if column[3]:
            parts = values.split(',')
            parts[column[0]] = 'NULL'
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(f'INSERT INTO {table} VALUES ({",".join(parts)})')
    db.close()


def test_newer_no_writes(configured):
    (configured / "source").mkdir()
    path = configured / 'bronze.db'
    db = sqlite3.connect(path)
    db.execute(f'PRAGMA user_version={CURRENT_VERSION + 1}')
    db.execute('CREATE TABLE sentinel(value TEXT)')
    db.execute("INSERT INTO sentinel VALUES ('keep')")
    db.commit()
    db.close()
    before = path.read_bytes()
    assert cli.main(['run']) == 2
    assert path.read_bytes() == before


def test_migration_rollback(tmp_path, monkeypatch):
    import raptor_etl.database as module
    monkeypatch.setattr(module, 'MIGRATIONS', (("CREATE TABLE partial(id INTEGER)", 'INVALID SQL'),))
    from raptor_etl.errors import ConfigError
    with pytest.raises(ConfigError):
        open_database(tmp_path / 'db')
    db = sqlite3.connect(tmp_path / 'db')
    assert db.execute('PRAGMA user_version').fetchone()[0] == 0
    assert db.execute('SELECT name FROM sqlite_master').fetchall() == []
    db.close()


@pytest.mark.parametrize('table,values', [
    ('archived_file', "2,'b','b','date','" + 'b' * 64 + "',0,'now'"),
    ('file_load', "2,2,'production_todate','now','now',NULL,NULL,NULL,1,0"),
    ('load_failure', "1,1,'now','LayoutError','message'"),
])
def test_lineage_not_null(tmp_path, table, values):
    db = open_database(tmp_path / 'db')
    seed(db)
    db.execute("INSERT INTO archived_file VALUES (3,'c','c','date',?,0,'now')", ('c' * 64,))
    # Use the available parent for file_load while independently testing each column.
    if table == 'file_load':
        values = values.replace('2,2,', '2,3,', 1)
    for column in db.execute(f'PRAGMA table_info({table})').fetchall():
        if column[3]:
            parts = values.split(',')
            parts[column[0]] = 'NULL'
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(f'INSERT INTO {table} VALUES ({",".join(parts)})')
    db.close()


def test_report_type_check(tmp_path):
    db = open_database(tmp_path / 'db')
    db.execute("INSERT INTO archived_file VALUES (1,'a','a','date',?,0,'now')", ('a' * 64,))
    with pytest.raises(sqlite3.IntegrityError, match='CHECK'):
        db.execute("INSERT INTO file_load VALUES (1,1,'invalid','now','now',NULL,NULL,NULL,1,0)")
    db.close()
