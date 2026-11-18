# CONTRACT-003: Load parsed reports into SQLite bronze

Status: Approved
Approved by: Patrick
Approved date: 2026-11-11
Related tasks: TASK-001
Related ADRs: ADR-001

## Purpose

Store every successfully parsed archived report in the bronze SQLite
database exactly once, so that every row can be traced to the file it came
from and a failed load never leaves partial data behind.

## Scope

### Included

- Selecting which archived files to load.
- Writing parsed records (CONTRACT-002) to the bronze tables.
- Recording load outcomes, both successes and failures.
- The bronze schema, at the level of tables, columns and constraints.

### Excluded

- Deduplicating across files. Production ToDate rows repeat in every daily
  file and are stored each time; a later layer handles that.
- Views, aggregates and silver/gold layers.
- Database backup.

## Actors

- `raptor-etl run`, after collect (CONTRACT-001).

## Bronze schema

All timestamps, durations and value types follow CONTRACT-002. "FK" means a
foreign key, which the database enforces.

### Lineage tables

**`archived_file`**: written by CONTRACT-001.

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | primary key |
| `original_name` | TEXT | not null, e.g. `Production Todate.xls` |
| `archive_name` | TEXT | not null, unique, e.g. `2026-11-10_Production Todate.xls` |
| `copy_date` | TEXT | not null, `YYYY-MM-DD` |
| `sha256` | TEXT | not null, 64 lowercase hex characters |
| `size_bytes` | INTEGER | not null |
| `archived_at` | TEXT | not null, plant-local timestamp |
| | | unique (`original_name`, `sha256`) |

**`file_load`**: one row per **successful** load.

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | primary key |
| `archived_file_id` | INTEGER | not null, unique, FK → `archived_file` |
| `report_type` | TEXT | not null, `downtime_summary`, `production_summary` or `production_todate` |
| `loaded_at` | TEXT | not null, plant-local timestamp |
| `printed_at` | TEXT | not null |
| `report_start` | TEXT | null for ToDate |
| `report_end` | TEXT | null for ToDate |
| `recipe` | TEXT | null for ToDate |
| `page_count` | INTEGER | not null |
| `record_count` | INTEGER | not null, number of data rows written for this load |

**`load_failure`**: one row per **failed** load attempt.

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | primary key |
| `archived_file_id` | INTEGER | not null, FK → `archived_file` |
| `attempted_at` | TEXT | not null |
| `error_type` | TEXT | not null, e.g. `LayoutError`, `ReconciliationError` |
| `error_message` | TEXT | not null |

### Report tables

Every report table declares `id INTEGER PRIMARY KEY` as its first column.
Every report row has `file_load_id` (INTEGER, not null, FK → `file_load`)
and `row_order` (INTEGER, not null), and (`file_load_id`, `row_order`) is
unique. Through `file_load_id`, each row traces to its file, hash, copy date
and load time.

**`downtime_alarm`**: `alarm_id` INTEGER not null, `description` TEXT not
null, `occurrences` INTEGER, `total_duration` TEXT, `min_duration` TEXT,
`max_duration` TEXT.

**`downtime_total`**: one per load, with `file_load_id` unique.
`occurrences` INTEGER, `total_duration` TEXT. (No `row_order`.)

**`production_summary_kpi`**: one per load, with `file_load_id` unique.
`avg_bf_per_piece` REAL, `lug_fill` REAL, `trimloss` REAL,
`trimmer_speed_slow_pct` REAL, `trimmer_speed_medium_pct` REAL,
`trimmer_speed_fast_pct` REAL. (No `row_order`.)

**`production_summary_breakdown`**: `section` TEXT not null (`product`,
`length`, `grade`, `width`), `label` TEXT not null, `is_total` INTEGER not
null (0 or 1), `pieces` INTEGER, `volume` REAL, `pct_volume` REAL.

**`production_todate_day`**: `run_start` TEXT not null, `fast_pct` REAL,
`medium_pct` REAL, `slow_pct` REAL, `lug_fill` REAL, `bf_per_piece` REAL,
`trimloss` REAL, `total_stops` INTEGER, `downtime` TEXT, `volume` REAL.
(`file_load_id`, `run_start`) is unique.

Value columns not marked not-null are nullable, because a blank source cell
becomes NULL (CONTRACT-002).

### Schema versioning

The database records its schema version (`PRAGMA user_version`). On startup:

- a new database gets the current schema;
- an older version is upgraded by ordered, recorded migrations;
- a version newer than the code knows → exit code 2, nothing written.

TASK-011 replaces schema version 1 in place. `MIGRATIONS` has one entry
and there is no migration from the old version 1. Delete the old database
before deployment.

Foreign keys are enabled on every connection.

## Preconditions

- Configuration is valid and the database is usable, meaning it opens and
  its schema version is known or upgradable. Otherwise: exit code 2.
- The run holds the run lock and the CONTRACT-001 precheck passed. If the
  source is unreachable, the run stops before loading (exit code 4).

## Required behavior

1. **Choose what to load.** Every `archived_file` that:
   - has an `original_name` of `Downtime Summary.xls`,
     `Production Summary.xls` or `Production Todate.xls`;
   - and has no `file_load` row.

   This includes files archived in earlier runs whose load failed, so
   failures are retried automatically on every run that passes the
   CONTRACT-001 precheck. PDFs and Thickness
   Breakdown are never selected (PDFs are loaded only by the manual
   backfill, CONTRACT-004). They are processed in `archived_at` order,
   oldest first.
2. **For each file:**
   1. Recalculate the archive file's SHA-256. If it doesn't match
      `archived_file.sha256`, or the file is gone → record a `load_failure`
      (`error_type` `ArchiveIntegrityError`) and move on.
   2. Parse it (CONTRACT-002) using the report type from `original_name`.
   3. On a parse error → record a `load_failure` and move on.
   4. On success, in **one transaction**: insert `file_load`, then the
      header-level rows (`downtime_total`, `production_summary_kpi`), then all
      data rows. Commit.
   5. If the transaction fails → roll back and record a `load_failure`.
3. Log each file's outcome: `loaded` with its record count, or `failed`
   with the error type and message.

## Postconditions and invariants

- **Loaded exactly once:** each `archived_file` has at most one `file_load`.
  Running again never duplicates data.
- **All or nothing:** for any `archived_file`, either a `file_load` exists
  along with **all** of its report rows, or **no** report rows exist for it.
- **Count matches:** `file_load.record_count` equals the number of rows in
  that load's main data table (`downtime_alarm`,
  `production_summary_breakdown` or `production_todate_day`).
- **Bronze matches the parse:** stored values equal the `ParsedReport`
  values (CONTRACT-002) with nothing rounded, defaulted or reordered.
- **Lineage:** every report row traces back through `file_load` and
  `archived_file` to a file in the archive.
- **Append-only:** `run` and `import-pdf` never update or delete written rows.
  `load_failure` stays append-only history. Every table declares
  `id INTEGER PRIMARY KEY`, which aliases SQLite's `rowid` and preserves it
  through `VACUUM`. SFPDataAPI deduplicates the `trimmer` source by hashing
  row content including `rowid`.

### Empty reports

A report with no production (CONTRACT-002, "Empty reports") loads like any
other report:

- Downtime Summary: `file_load` with `record_count` 0, one `downtime_total`
  row (`occurrences` 0, `total_duration` as parsed), no `downtime_alarm`
  rows.
- Production Summary: `file_load` with `record_count` 4, one
  `production_summary_kpi` row, and the four Total rows.
- Production ToDate with zero rows: `file_load` with `record_count` 0.

## Failure behavior

| Situation | Behavior |
|---|---|
| Parse error (`LayoutError`, `ReconciliationError`) | `load_failure` recorded, no report rows, other files continue, exit code 1. Retried next run. If the report layout changed, a code change is needed, and the retry succeeds after it ships. |
| Archive file missing or hash differs | `load_failure` (`ArchiveIntegrityError`), exit code 1. Needs a person to investigate. Retried each run. |
| Database write error mid-file | Rolled back, `load_failure` recorded if possible, exit code 1. |
| Database unopenable or schema too new | Exit code 2 before any load. |

## Interfaces

- Part of `raptor-etl run`. Exit codes as in CONTRACT-001.
- Reads `RAPTOR_ARCHIVE_DIR`. Reads and writes `RAPTOR_DB_PATH`.

## Validation requirements

Automated, against a temporary database and archive built from `Samples/`:

- After loading the three sample `.xls` files: 3 `file_load` rows; 20
  `downtime_alarm`, 1 `downtime_total`, 1 `production_summary_kpi` and 81
  `production_todate_day` rows; `record_count` correct for each.
- Spot values match the source: the 2026-09-23 `slow_pct` is NULL,
  `avg_bf_per_piece` = 2.8713249629155975, both 2026-09-16 rows are present.
- A second run loads nothing new.
- Load the sample `.xls` set, run `VACUUM`, and run the load again. Every
  report row retains its original `rowid` and content.
- A file that fails to parse: `load_failure` recorded and no report rows.
  After replacing the fixture with a valid file, the next run loads it.
- A fault injected after some rows are inserted → no rows remain for that
  file.
- A tampered archive file → `ArchiveIntegrityError`.
- The 2026-11-13 sample `.xls` set (all three types) loads with exit
  code 0 and the rows listed under "Empty reports".
- PDFs and Thickness Breakdown are never loaded by `run`. PDF loads by the
  manual backfill are defined in CONTRACT-004.
- Foreign keys are enforced, and the unique constraints reject duplicates.
- Schema version: a new database is created at version 1 with a declared `id INTEGER PRIMARY KEY` in every table, and a
  database with a newer version fails with exit code 2.

## Amendments

- 2026-11-16 (Approved): added "Empty reports".
  A no-production day loads with `record_count` 0 (Downtime, ToDate) or 4
  (Production Summary Totals) instead of failing.

- 2026-11-18 (TASK-011): replaced version 1 and specified stable row IDs
  for the SFPDataAPI hand-off.

## Open questions

None.
