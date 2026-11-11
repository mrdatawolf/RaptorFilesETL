"""Bronze schema and atomic, ordered schema migrations."""
import sqlite3
from pathlib import Path

from icontract import ensure

from .errors import ConfigError

SCHEMA = (
    """CREATE TABLE archived_file (
    id INTEGER PRIMARY KEY, original_name TEXT NOT NULL,
    archive_name TEXT NOT NULL UNIQUE, copy_date TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    size_bytes INTEGER NOT NULL, archived_at TEXT NOT NULL,
    UNIQUE(original_name, sha256))""",
    """CREATE TABLE file_load (
    id INTEGER PRIMARY KEY,
    archived_file_id INTEGER NOT NULL UNIQUE REFERENCES archived_file(id),
    report_type TEXT NOT NULL CHECK(report_type IN
      ('downtime_summary','production_summary','production_todate')),
    loaded_at TEXT NOT NULL, printed_at TEXT NOT NULL,
    report_start TEXT, report_end TEXT, recipe TEXT,
    page_count INTEGER NOT NULL, record_count INTEGER NOT NULL)""",
    """CREATE TABLE load_failure (
    id INTEGER PRIMARY KEY, archived_file_id INTEGER NOT NULL REFERENCES archived_file(id),
    attempted_at TEXT NOT NULL, error_type TEXT NOT NULL, error_message TEXT NOT NULL)""",
    """CREATE TABLE downtime_alarm (
    file_load_id INTEGER NOT NULL REFERENCES file_load(id), row_order INTEGER NOT NULL,
    alarm_id INTEGER NOT NULL, description TEXT NOT NULL, occurrences INTEGER,
    total_duration TEXT, min_duration TEXT, max_duration TEXT,
    UNIQUE(file_load_id,row_order))""",
    """CREATE TABLE downtime_total (
    file_load_id INTEGER NOT NULL UNIQUE REFERENCES file_load(id),
    occurrences INTEGER, total_duration TEXT)""",
    """CREATE TABLE production_summary_kpi (
    file_load_id INTEGER NOT NULL UNIQUE REFERENCES file_load(id),
    avg_bf_per_piece REAL, lug_fill REAL, trimloss REAL,
    trimmer_speed_slow_pct REAL, trimmer_speed_medium_pct REAL, trimmer_speed_fast_pct REAL)""",
    """CREATE TABLE production_summary_breakdown (
    file_load_id INTEGER NOT NULL REFERENCES file_load(id), row_order INTEGER NOT NULL,
    section TEXT NOT NULL CHECK(section IN ('product','length','grade','width')),
    label TEXT NOT NULL, is_total INTEGER NOT NULL CHECK(is_total IN (0,1)),
    pieces INTEGER, volume REAL, pct_volume REAL, UNIQUE(file_load_id,row_order))""",
    """CREATE TABLE production_todate_day (
    file_load_id INTEGER NOT NULL REFERENCES file_load(id), row_order INTEGER NOT NULL,
    run_start TEXT NOT NULL, fast_pct REAL, medium_pct REAL, slow_pct REAL,
    lug_fill REAL, bf_per_piece REAL, trimloss REAL, total_stops INTEGER,
    downtime TEXT, volume REAL, UNIQUE(file_load_id,row_order), UNIQUE(file_load_id,run_start))""",
)
# Position + 1 is the recorded target version. Never reorder existing migrations.
MIGRATIONS = (SCHEMA,)
CURRENT_VERSION = len(MIGRATIONS)


@ensure(lambda result: result.execute("PRAGMA foreign_keys").fetchone()[0] == 1, enabled=True)
def open_database(path: Path | str) -> sqlite3.Connection:
    connection = None
    try:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > CURRENT_VERSION:
            raise ConfigError("RAPTOR_DB_PATH: schema version is newer than supported")
        if version < CURRENT_VERSION:
            connection.execute("BEGIN IMMEDIATE")
            for index in range(version, CURRENT_VERSION):
                for statement in MIGRATIONS[index]:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {index + 1}")
            connection.commit()
        return connection
    except (sqlite3.Error, OSError, ConfigError) as error:
        if connection is not None:
            connection.close()
        if isinstance(error, ConfigError):
            raise
        raise ConfigError("RAPTOR_DB_PATH: database cannot be opened or migrated") from None
