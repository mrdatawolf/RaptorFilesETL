# TASK-002: Project foundation (package, config, database, run lock)

Owner role: implementer
Assigned agent: Codex (openai-coder)
Proposed by: Claude (main session)
Proposed date: 2026-11-11
Approved by: Patrick
Approved date: 2026-11-11
Related contracts: CONTRACT-001, CONTRACT-003
Related ADRs: ADR-001
Dependencies: None

## Desired outcome

An installable `raptor_etl` package with the shared pieces every stage needs:
configuration, logging, the bronze schema, the run lock and the `raptor-etl`
CLI. Later tasks add stages without changing these foundations.

## Context

See ADR-001 (stack, configuration, exit codes), `docs/DEVELOPMENT.md`
(layout, conventions) and CONTRACT-003 (bronze schema).

## Scope

### Included

- `pyproject.toml`: Python 3.12+, src layout, runtime deps from ADR-001
  (xlrd, smbprotocol, python-dotenv, tzdata, icontract), `dev` extra with
  pytest, console script `raptor-etl`.
- `.env.example` with placeholders for every ADR-001 variable.
- Config module: load `.env` without overriding existing variables, validate
  all ADR-001 variables, collect **all** problems, raise `ConfigError`. Secret
  values never appear in messages. Includes the archive-folder-writable and
  DB-parent-exists checks.
- Typed errors module: `ConfigError`, `LayoutError`, `ReconciliationError`
  (subclass of `LayoutError`), `ArchiveIntegrityError`.
- Logging to stdout at `RAPTOR_LOG_LEVEL`.
- Clock abstraction: plant-local "now" from `RAPTOR_TIMEZONE`, injectable in
  tests.
- Database module: open with foreign keys on; full CONTRACT-003 schema
  (lineage and report tables, all constraints); `PRAGMA user_version`
  versioning with an ordered migration list; newer-than-known version raises
  an error mapped to exit code 2.
- Run lock: a single-run lock (for example a lock file next to the database)
  that works on Linux and Windows. A second holder fails at once.
- CLI: `raptor-etl run` validates config, opens the DB, takes the lock and
  calls stage hooks (empty for now), mapping errors to exit codes 0/1/2/3.
  `raptor-etl schedule` may be a stub that exits with a clear "not
  implemented" message until TASK-006.

### Excluded

- Collect, parse and load logic (TASK-003 to TASK-005).
- Scheduler loop and Docker (TASK-006).

## Plan

1. Package skeleton and `pyproject.toml`.
2. Errors, config, logging, clock.
3. Database schema and versioning.
4. Run lock and CLI wiring.
5. Tests.

## Acceptance criteria

- [ ] `pip install -e ".[dev]"` and `pytest` work on a clean venv.
- [ ] Missing or invalid variables → every problem logged, no secret values, exit code 2.
- [ ] Existing environment variables override `.env`.
- [ ] A new database is created at the current schema version with every CONTRACT-003 table and constraint; foreign keys are enforced; unique constraints reject duplicates.
- [ ] A database with a newer `user_version` → exit code 2, nothing written.
- [ ] A second concurrent `run` → exit code 3.
- [ ] Python files and `.env.example` are the only new tracked files besides tests; no secrets, no `Samples/` content committed.

## Validation requirements

pytest covering each acceptance criterion. Handoff lists the commands run
and their output summary.

## Risks and assumptions

- The lock must release when the process dies (prefer an OS file lock over
  a "file exists" check).

## Blocker

None.

## Implementation handoff

# Implementation Report

Task: TASK-002 — Project foundation
Implementer: Codex (openai-coder)
Date: 2026-11-11

## Changes made

- Added `pyproject.toml`: Python 3.12+, setuptools src layout, only ADR-001
  runtime dependencies, pytest dev extra, and `raptor-etl` console script.
- Added placeholder-only `.env.example` for all ten ADR-001 variables.
- Added configuration with non-overriding, non-interpolating dotenv loading,
  aggregated diagnostics, conditional SMB credentials, archive writability probe,
  database-parent validation, timezone/schedule/log-level validation, and secret-safe
  errors and configuration representation.
- Added typed errors, stdout logging, and injectable plant-local clock.
- Added all eight CONTRACT-003 tables, foreign keys, NOT NULL/unique/check
  constraints, and ordered atomic migrations recorded in `PRAGMA user_version`.
  Newer versions are rejected before database writes. icontract's foreign-key
  postcondition is explicitly enabled even under optimized Python.
- Added nonblocking Linux flock / Windows msvcrt run lock beside the database.
  The OS releases it on process death; the lock file persists to avoid inode races.
- Added run command and empty collect/load hooks with exit codes 0/1/2/3;
  schedule reports not implemented and exits 2. No ETL stages or scheduler loop
  were implemented.

## Validation performed

- `python3 -m venv .venv` — passed (Python 3.13.5).
- `.venv/bin/pip install -e '.[dev]'` — passed; editable package and dependencies
  installed. pip reported an unwritable user cache and automatically disabled
  caching; installation was not blocked and no permissions were changed.
- `.venv/bin/pytest tests/test_config.py -q` — 12 passed, 0 failed.
- `.venv/bin/pytest tests/test_database.py -q` — initially 16 passed; after adding
  lineage NOT NULL and isolated report-type checks, 20 passed, 0 failed.
- `.venv/bin/pytest tests/test_cli_lock.py -q` — 8 passed, 0 failed.
- `.venv/bin/pytest` — 40 passed, 0 failed (Linux, Python 3.13.5).
- `git diff --check` — passed.
- `git check-ignore .venv/ .env src/raptor_etl.egg-info/ src/raptor_etl/__pycache__/ .pytest_cache/`
  — all five paths ignored; `.gitignore` required no change.
- `git status --short` — staged task rename preserved; new files limited to
  package metadata, `.env.example`, Python package, and tests. No git writes,
  secrets, or Samples content were used.

## Acceptance criteria evidence

- Editable installation in newly created venv succeeds; installed console script
  is exercised by subprocess tests.
- Configuration tests check aggregate variable diagnostics, missing required
  variables, secret exclusion, exit 2, archive writability, malformed settings,
  environment precedence over dotenv, and default settings.
- Database tests check all eight tables, current schema version, foreign keys,
  report and lineage unique constraints, all declared NOT NULL columns,
  allowed-value checks, reopen behavior, and atomic rollback of a failed migration.
- Newer-schema CLI test compares the entire database bytes before and after exit 2.
- Concurrent subprocess run returns 3 before database creation; killing the holder
  releases the lock and a subsequent run succeeds.
- Only scoped source/tests/configuration metadata were added. Required generated
  artifacts remain ignored; the existing staged rename was not touched.

## Assumptions and deviations

- Direct task instructions override the lifecycle default: task remains here;
  Review and acceptance are unchanged. Acceptance checkboxes remain for review.
- The explicit request for `pyproject.toml` takes precedence over the task's
  acceptance wording limiting new tracked files to Python and `.env.example`.
- The lock is acquired before opening/migrating SQLite so a concurrent run does
  nothing to the database; this implements CONTRACT-001's stronger guarantee.
- Weekday ranges are ascending within MON..SUN; comma lists support arbitrary
  ordering. Local source availability is left to the future collect stage, since
  an unavailable source is a file/stage failure rather than a startup precondition.
- The scheduler stub exits 2; success from empty hooks means foundation startup
  succeeded, not that report files were processed.

## Unresolved risks

- Windows msvcrt locking is implemented but could not be executed on this Linux
  host. Windows and minimum Python 3.12 validation remain for independent review.
- No SMB access, real reports, ETL processing, or scheduler behavior is validated
  in this foundation task; those remain TASK-003 through TASK-006.

## Documentation updated

- This implementation handoff, in place. Existing development documentation
  already describes the approved foundation; no architecture change was made.

## Review

Not reviewed.

