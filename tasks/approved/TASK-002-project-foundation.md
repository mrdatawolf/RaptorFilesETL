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

Not started.

## Review

Not reviewed.

