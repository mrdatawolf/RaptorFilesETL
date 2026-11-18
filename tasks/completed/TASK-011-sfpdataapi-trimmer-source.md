# TASK-011: Make the bronze database SFPDataAPI's `trimmer` source

Owner role: implementer
Assigned agent: Codex
Proposed by: Claude (main session)
Proposed date: 2026-11-17
Approved by: Patrick
Approved date: 2026-11-18
Related contracts: CONTRACT-003 (amended by this task), CONTRACT-001, CONTRACT-004
Related ADRs: ADR-001 (partly superseded), ADR-003 (proposed)
Dependencies: ADR-003 approved

## Desired outcome

Every weekday night, this project builds its bronze database and pushes it to
the bronze server as `trimmer.db`. SFPDataAPI then ingests it as the
`trimmer` source, and each row lands in SFPDataAPI exactly once, including
after a `VACUUM`. Deployment matches SFP_Tally_ETL on both platforms. On
Linux: a systemd oneshot service, a systemd timer and an rsync push from
`start.sh`. On Windows: a `start.bat` that runs the job only, with no push.
Docker is removed.

## Context

- SFPDataAPI (`../SFPDataAPI`) is the reference design. Sources that an ETL
  builds as SQLite files (`tally`, `mw` and the PLC placeholders) are
  configured with a single `<SOURCE>_DB` variable. SFPDataAPI finds their
  tables on its own and lands each row with `row_hash` = SHA-256 of the row,
  **including its `rowid`** (`server/sources/sqliteSource.ts`).
- Five report tables (`downtime_alarm`, `downtime_total`,
  `production_summary_kpi`, `production_summary_breakdown`,
  `production_todate_day`) have no `INTEGER PRIMARY KEY`. SQLite may renumber
  the hidden `rowid` of such tables on `VACUUM`. Every row's hash would then
  change, and SFPDataAPI would land the whole table a second time.
  SFP_Tally_ETL's tables all declare `id INTEGER PRIMARY KEY`, which makes
  `rowid` stable.
- The data is report-level (Crystal Reports exports), not the live Raptor
  system database that SFPDataAPI's `raptor` source expects. It therefore
  gets its own source. Patrick chose `trimmer`, which **fills the existing
  PLC `trimmer` placeholder** (2026-11-17).
- The job isn't doing real work yet, and the existing database does not need
  to be kept (Patrick, 2026-11-17).

## Scope

### Included

**This repository**

1. **Schema reset (CONTRACT-003 amendment).** Every report table gains
   `id INTEGER PRIMARY KEY` as its first column. All other columns,
   constraints and FKs are unchanged. Because the old database is discarded,
   the schema is replaced in place as version 1 (`MIGRATIONS` stays a single
   entry). No migration is written.
2. **Stability invariant (CONTRACT-003 amendment).** Every table has a
   declared `INTEGER PRIMARY KEY`. Rows are never updated or deleted by `run`
   or `import-pdf`, so a written row keeps the same content and `rowid`
   forever. `load_failure` stays append-only history. This is what SFPDataAPI's
   hash dedupe depends on.
3. **Deployment (ADR-003).** Add `start.sh`, `push_db.sh`,
   `raptorbronze.service` and `raptorbronze.timer`, modelled on
   SFP_Tally_ETL's `start.sh`, `push_tally_db.sh` and `tallybronze.service`.
   Add `start.bat` (runs `raptor-etl run` from the venv and returns its exit
   code; no push), modelled on SFP_Tally_ETL's `start.bat`. Add `PUSH_PULL`
   and `RAPTOR_PUSH_DEST` to `.env.example`. They are read by `start.sh`,
   not by the Python config.
4. **Remove Docker**: `Dockerfile`, `.dockerignore`, and the Docker and
   TrueNAS sections of `docs/DEVELOPMENT.md`, `docs/PROJECT.md` and
   CONTRACT-004 (its `docker exec` note).
5. **Remove the scheduler** (if ADR-003 open question 1 is decided that way):
   `scheduler.py`, the `schedule` CLI command, `tests/test_scheduler.py`,
   `RAPTOR_RUN_TIME` and `RAPTOR_RUN_DAYS`.
6. **Docs.** `PROJECT.md`: consumer = SFPDataAPI `trimmer` source, and the
   Docker constraints replaced. `DEVELOPMENT.md`: host install (venv), the
   systemd units and the push. `ARCHITECTURE.md`: fill in the data flow
   (share → archive → bronze → push → SFPDataAPI).

**Coordinated changes in sibling repos** (no task process there; done in the
same change set, listed here so the plan is in one place)

7. **SFPDataAPI**
   - `server/config.ts`: remove `'trimmer'` from `PLC_SOURCES` and add
     `readDbSource('trimmer')` with a comment saying it is built by
     RaptorFilesETL.
   - `.env.example`: move `TRIMMER_DB` out of the PLC block into its own
     commented entry. Set the local `.env` to `../RaptorFilesETL/<db>` for
     development.
   - `README.md`: in the Sources table, `trimmer` becomes "Raptor
     sorter/trimmer daily reports, pre-built by RaptorFilesETL" and is
     removed from the PLC row.
   - No ingest changes. Volumes are small (tens of rows per day), so a full
     rescan is fine and nothing is added to `INCREMENTAL_TABLES`.
8. **SFP_Tally_ETL**: remove the `RAPTOR_DB_PATH` snapshot-and-push block
   from `start.sh`, and `RAPTOR_DB_PATH` from `.env`, `.env.example` and
   `README.md`.
9. **`../SFP_Mill_Data_Pipeline.md`**: the Raptor reports are now the
   `trimmer` feed, so update the status table.

### Excluded

- Any change to parsing (CONTRACT-002) or to collect (CONTRACT-001) behavior.
- SFPDataAPI silver and gold layers, and any SFPDataAPI ingest changes.
- The live Raptor and Raptor2 system databases (SFPDataAPI `raptor` and
  `raptor2` stay as they are).
- Rebuilding bronze from previously archived files. The old archive and
  database are discarded (see Risks).

## Plan

1. Get ADR-003 approved, including its two open questions.
2. Amend CONTRACT-003: add the `id` columns, the stability invariant, the
   reset to version 1 and the validation below. Then update `database.py`
   and the tests.
3. Remove Docker, and the scheduler if decided.
4. Add `start.sh`, the push script and the systemd units, plus the config
   variables.
5. Make the SFPDataAPI, SFP_Tally_ETL and pipeline-doc changes.
6. Validate end to end locally: run, then point SFPDataAPI's `TRIMMER_DB` at
   the result and scan twice.
7. Deploy: delete the old database and archive on the host, install, and
   enable the timer. On the bronze server, delete the stale `raptor.db`.

## Acceptance criteria

- [ ] Every table in a newly created database declares `id INTEGER PRIMARY KEY`, and the schema version is 1.
- [ ] After loading the sample `.xls` set, `VACUUM`, and loading again, every report row's `rowid` and content are unchanged.
- [ ] All existing CONTRACT-003 and CONTRACT-004 validation still passes (row counts, spot values, idempotency, rollback, integrity).
- [ ] `start.sh` pushes a backup-API snapshot named `trimmer.db` to `RAPTOR_PUSH_DEST` when `PUSH_PULL=push` and `run` exits 0 or 1, pushes nothing on 2, 3 or 4, and exits with `run`'s code.
- [ ] With `PUSH_PULL=push` but no `RAPTOR_PUSH_DEST`, `start.sh` exits with an error before running anything.
- [ ] `raptorbronze.timer` is `Mon..Fri 23:00 America/Los_Angeles`, and `raptorbronze.service` is a oneshot that runs `start.sh`.
- [ ] `start.bat` runs `raptor-etl run` from the venv, passes through arguments, returns its exit code, and does not push.
- [ ] No `Dockerfile`, `.dockerignore` or Docker/TrueNAS instructions remain. No `schedule` command remains if the scheduler is removed.
- [ ] SFPDataAPI lists `trimmer` as its own `_DB` source (not under PLC). A scan of the pushed database lands `bronze.trimmer__*` tables, and a second scan inserts 0 rows.
- [ ] SFP_Tally_ETL no longer references `RAPTOR_DB_PATH` or pushes `raptor.db`.
- [ ] `docs/` and `../SFP_Mill_Data_Pipeline.md` describe the new flow.

## Validation requirements

- `pytest`, with a new test for `VACUUM` stability.
- A `start.sh` dry run against a local rsync destination folder, covering
  exit 0 (push), a forced exit 2 (no push) and a missing
  `RAPTOR_PUSH_DEST`.
- `start.bat`: run it on Windows if a Windows machine is available.
  Otherwise, say in the handoff that it was not run.
- SFPDataAPI: `npm test`, then two `POST /api/ingest/scan?source=trimmer`
  runs against the local database, with the results summarized in the
  handoff.
- `systemd-analyze verify` on both units, if available.

## Risks and assumptions

- **The archive and database are discarded.** Report files archived before
  deployment are not loaded again. `import-pdf` can still backfill from
  saved PDFs if that's ever needed.
- **The schema is replaced in place as version 1.** A leftover old
  version-1 database would open without error and not have the new `id`
  columns. Deployment must delete it first, and the deploy docs must say so.
- The host has Python 3.12+ and the service user has SSH access to the
  bronze server (the same access SFP_Tally_ETL's `biztech` user already has).
- Windows support is at SFP_Tally_ETL's level (Patrick, 2026-11-18): a
  Windows run builds the local database but never delivers it to
  SFPDataAPI.
- `start.sh` and `start.bat` have no automated tests, the same as in
  SFP_Tally_ETL. They're checked by the dry run under Validation.
- Assumes SFPDataAPI reads `/srv/data/bronze/trimmer.db`. Its deployed `.env`
  needs `TRIMMER_DB` set to that path.

## Blocker

Resolved: ADR-003 was approved by Patrick on 2026-11-18. Remove the
scheduler and install at `/srv/RaptorFilesETL` as `biztech`.

## Implementation handoff

### Changes made

- RaptorFilesETL: added integer primary keys to the five report tables in
  schema version 1, preserving the existing columns, constraints and load
  behavior. Added the sample VACUUM test and updated affected fixtures.
  Added the Linux launch and snapshot scripts, systemd units, and Windows
  launcher. Removed Docker packaging, the built-in scheduler and its
  settings. Removed obsolete scheduler assignments from the gitignored
  local `.env`. Updated the project, deployment, architecture and contract
  docs. ADR-003 already says Approved.
- SFPDataAPI: prepared changes to `server/config.ts`, `.env.example`
  and `README.md` to register `trimmer` as a RaptorFilesETL-built SQLite
  source. The temporary checkout's local `.env` used
  `TRIMMER_DB=../RaptorFilesETL/trimmer.db`. Ingest code was unchanged.
- SFP_Tally_ETL: prepared removal of Raptor delivery from `start.sh`,
  `.env.example` and `README.md`.
- SFP_Mill_Data_Pipeline.md: prepared the flow and status update for the
  `trimmer` feed.

### Validation performed

- `.venv/bin/python -m pytest -q tests/test_load_e2e.py::test_report_rows_stable_after_vacuum_and_rerun tests/test_database.py`
  → 21 passed. The initial full run caught stale Config fixtures and
  extra local PDF sample days. Adjusted the fixtures to exercise the
  approved four-day PDF set and retain all assertions.
- `.venv/bin/python -m pytest -q tests/test_load.py tests/test_load_e2e.py tests/test_import_pdf.py tests/test_collect.py tests/test_config.py tests/test_database.py`
  → 87 passed.
- `.venv/bin/python -m pytest -q` → 327 passed.
- `bash /tmp/task-011.SdkRmG/verify-launcher.sh` → exit 0 delivered
  `trimmer.db` with three report loads and SQLite integrity check `ok`.
  Exit 1 delivered a snapshot and preserved status 1. Invalid archive
  configuration forced exit 2, a stub forced exit 3, and a missing source
  forced exit 4. Each left its destination empty. The missing-destination
  case exited 2 with the expected diagnostic before calling the ETL stub.
- In the temporary SFPDataAPI checkout,
  `PATH="$HOME/.nvm/versions/node/v24.16.0/bin:$PATH" npm test`
  → 10 passed. Started the API with
  `HOST=127.0.0.1 APIPORT=17304 SCAN_ON_START=false SCAN_INTERVAL_HOURS=0 DB_PATH="$PWD/test-bronze" ./node_modules/.bin/tsx server/index.ts`
  using the same Node 24 PATH. The readiness probe at `/` logged a missing
  UI build in the temporary copy. Both ingest requests returned HTTP 200.
- Ran `curl -fsS -X POST 'http://127.0.0.1:17304/api/ingest/scan?source=trimmer'`
  twice → eight tables scanned each time. First scan inserted 148 rows.
  Second scan inserted 0 and skipped 148. A PGlite query verified eight
  physical `bronze.trimmer__*` tables.
- `systemd-analyze verify ./raptorbronze.service ./raptorbronze.timer`
  → exit 1, with the sole diagnostic that the install path
  `/srv/RaptorFilesETL/start.sh` does not exist locally.
  `systemd-analyze calendar 'Mon..Fri 23:00 America/Los_Angeles'`
  accepted and normalized the expression.
- `bash -n start.sh`, `bash -n push_db.sh`, `bash -n SFP_Tally_ETL/start.sh`
  (temporary copy), `.venv/bin/raptor-etl --help` and `git diff --check`
  passed. CLI help lists `run`, `check` and `import-pdf`.
- `git -C /home/patrick/Documents/Github/SFP apply --check /tmp/TASK-011-sibling-changes.patch`
  passed. The patch was also applied to a temporary copy of the original
  files and compared with the tested files.

### Deviations and unresolved issues

- The filesystem sandbox allows writes only in RaptorFilesETL and
  `/tmp`. The patch at `/tmp/TASK-011-sibling-changes.patch` contains
  all seven tracked sibling changes, relative to the parent `SFP`
  directory. Applying the patch to the live checkouts and editing their
  local `.env` files remain pending. SFP_Tally_ETL's live local `.env`
  still has the `RAPTOR_DB_PATH` entry. Local environment changes are
  excluded from the patch.
- Windows was unavailable, so `start.bat` was checked by inspection only.
  Production deployment was outside implementation scope. No SSH,
  deployment, commit or push was performed.
- Deployment requires deleting the old database and archive before the
  first run, since the replaced schema also reports version 1. The
  office-side `TRIMMER_DB` is assumed to be
  `/srv/data/bronze/trimmer.db`.

## Review

Not reviewed.
