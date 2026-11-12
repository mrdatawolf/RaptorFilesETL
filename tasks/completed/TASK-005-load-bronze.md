# TASK-005: Load parsed reports into SQLite bronze

Owner role: implementer
Assigned agent: Codex (openai-coder)
Proposed by: Claude (main session)
Proposed date: 2026-11-11
Approved by: Patrick
Approved date: 2026-11-11
Related contracts: CONTRACT-003, CONTRACT-001 (exit codes)
Related ADRs: ADR-001
Dependencies: TASK-002, TASK-003, TASK-004

## Desired outcome

The load stage of `raptor-etl run`, implementing CONTRACT-003, so a full
`run` collects, parses and loads end to end.

## Context

The schema is created in TASK-002. CONTRACT-003 defines selection, the
per-file transaction, failure recording, invariants and tests.

## Scope

### Included

- Selection of unloaded `.xls` archive files (oldest first, retries
  included).
- Archive integrity re-check, parse, one-transaction insert, rollback and
  `load_failure` recording.
- Per-file outcome logging and exit-code contribution.
- An end-to-end test: local source of `Samples/` → `run` → expected bronze
  contents, then a second `run` that changes nothing.
- Tests from CONTRACT-003 "Validation requirements".

### Excluded

- Schema changes beyond TASK-002 (raise them instead). Scheduler and Docker.

## Plan

1. Selection query.
2. Per-file load with transaction.
3. CLI wiring.
4. Tests, including fault injection mid-transaction.

## Acceptance criteria

- [ ] Every CONTRACT-003 validation test is implemented and passes.
- [ ] End-to-end `run` on `Samples/` gives 3 `file_load`, 20 `downtime_alarm`, 1 `downtime_total`, 1 `production_summary_kpi`, 81 `production_todate_day` rows (plus the breakdown rows), exit code 0.
- [ ] A second `run` adds no rows.
- [ ] Load code never updates or deletes rows (append-only).

## Validation requirements

pytest; handoff summarizes results.

## Risks and assumptions

None beyond the contract.

## Blocker

None.

## Implementation handoff

Phase 2 of 2 complete

Task: TASK-005. Implementer: Codex. Date: 2026-11-11.

### Phase 1 changes and validation (historical)

- Added `src/raptor_etl/load.py` exposing `load_stage(config, database, clock)`.
  Selects only the three supported original `.xls` names without a successful
  load, ordered by archived_at then id, including earlier failures for retry.
- Rechecks archive SHA-256 before parsing. Missing/unreadable or changed files
  record ArchiveIntegrityError. Each success inserts file_load, header rows
  and ordered data in one transaction. Errors roll back and record failure
  history separately if possible. Every file outcome is logged.
- Reuses the schema and parser models, preserving NULLs, precision and order.
  An enabled icontract postcondition checks the inserted main-table count.
  Load SQL contains no UPDATE, DELETE or REPLACE.
- Added 14 tests in `tests/test_load.py`: complete sample field comparisons,
  counts, spot values, lineage, idempotency, parser/fixture repair retries,
  rollback fault injection in all three main tables, archive integrity,
  selection/exclusions/order, failure-history write failure, schema versions,
  foreign keys and unique constraints.

### Validation performed

- `.venv/bin/pytest tests/test_load.py -q`: **14 passed**.
- `.venv/bin/pytest`: **176 passed**, including concurrent TASK-007 tests
  present at execution time; no failures.
- `git diff --check`: passed before and after the handoff update.
- Reference counts: 3 file_load, 20 downtime_alarm, 1 downtime_total,
  1 production_summary_kpi and 81 production_todate_day. Breakdown rows and
  every record_count checked against parser output.
- Verified NULL slow_pct on 2026-09-23, exact avg_bf_per_piece of
  2.8713249629155975, and both 2026-09-16 timestamps.
- Initial documentation-edit command using `python` failed because that alias
  is unavailable; reran successfully with `.venv/bin/python`.

### Assumptions and deviations

- Human-directed phase 1 scope: no CLI wiring or end-to-end run test. Task
  stays in-progress; acceptance criteria remain pending.
- Caller must hold the run lock, validate configuration/database and pass the
  CONTRACT-001 precheck before invoking the loader. These are documented
  caller preconditions; phase 2 must preserve them when wiring the CLI.
  An enabled icontract precondition requires no active caller transaction.
- Equal archived_at timestamps use id as a deterministic secondary order.
- The fixture repair test corrupts a temporary archive after hash verification
  to provoke a real parser failure, then restores the original bytes before
  retrying. This avoids modifying append-only archived_file hashes. Separate
  tests simulate parser fixes with unchanged archives and check tampering.
- No deviations from CONTRACT-003 behavior within phase 1 scope.

### Unresolved risks and remaining work

- Phase 2 must wire the CLI, verify precheck integration and add the
  end-to-end run test. No implementation acceptance is claimed.
- If the database also rejects load_failure, history cannot be persisted;
  the stage logs this and returns false (contract: record if possible).
- Concurrent TASK-007 changes were preserved. No shared files were edited
  by this implementation. Samples-dependent tests skip clearly when absent.
- No open questions or blockers for phase 1.

### Documentation updated

This handoff only; Review and Human acceptance unchanged.


### Phase 2 changes made

- Replaced only the CLI load_stage placeholder with delegation to
  raptor_etl.load.load_stage. Preserved the existing precheck before database
  opening, collect and load, check command, sanitized failures and exit codes.
- Added tests/test_load_e2e.py: complete CLI run and unchanged second run;
  missing and inaccessible source short-circuit both stages with exit 4;
  archive corruption after successful collect yields exit 1 while the other
  two reports load successfully. Tests copy Samples/ into temporary source
  paths, use scratch archive/database paths and an injected clock, and skip
  clearly when Samples/ is absent.
- Verified 34 breakdown rows, including one Total for each of the four
  sections, and record_count values 20, 34 and 81.

### Phase 2 validation performed

- `.venv/bin/pytest tests/test_load_e2e.py -q`: initial run **3 passed,
  1 failed** because the new spy targeted nonexistent LocalSource.list_names;
  corrected the test spy to LocalSource.names.
- `.venv/bin/pytest tests/test_load_e2e.py -q`: **4 passed** after correction.
- `.venv/bin/pytest`: **297 passed**, zero failures or skips (293 existing
  tests plus 4 new cases).
- Real `.venv/bin/raptor-etl run`: fresh directory created by
  `mktemp -d /tmp/raptor-task005-XXXXXX`, Samples/ copied to its source folder,
  with RAPTOR_SOURCE_PATH, RAPTOR_ARCHIVE_DIR and RAPTOR_DB_PATH pointing
  exclusively there. Explicit timezone America/Los_Angeles and INFO logging.
  Scratch directory: `/tmp/raptor-task005-C6Ii8i`. Exit code: **0**.

Captured run output (trailing log whitespace omitted):

```text
INFO Downtime Summary.pdf: archived archive=2026-11-11_Downtime Summary.pdf sha256=848ff4dbbd95
INFO Downtime Summary.xls: archived archive=2026-11-11_Downtime Summary.xls sha256=5c41c6796047
INFO Production Summary.pdf: archived archive=2026-11-11_Production Summary.pdf sha256=c4e616214545
INFO Production Summary.xls: archived archive=2026-11-11_Production Summary.xls sha256=685958242628
INFO Production Todate.pdf: archived archive=2026-11-11_Production Todate.pdf sha256=b03a1b5868a8
INFO Production Todate.xls: archived archive=2026-11-11_Production Todate.xls sha256=030afd04881b
INFO Thickness Breakdown.pdf: archived archive=2026-11-11_Thickness Breakdown.pdf sha256=86ecfcf132e4
INFO Thickness Breakdown.xls: archived archive=2026-11-11_Thickness Breakdown.xls sha256=1aa7b05d7520
INFO 2026-11-11_Downtime Summary.xls: loaded record_count=20
INFO 2026-11-11_Production Summary.xls: loaded record_count=34
INFO 2026-11-11_Production Todate.xls: loaded record_count=81
```

Post-run query using `.venv/bin/python` and standard-library sqlite3:

```text
archived_file: 8
file_load: 3
load_failure: 0
downtime_alarm: 20
downtime_total: 1
production_summary_kpi: 1
production_summary_breakdown: 34
production_todate_day: 81
record_count downtime_summary: 20
record_count production_summary: 34
record_count production_todate: 81
```

- `git diff --check`: initially flagged trailing spaces copied from CLI logs;
  removed trailing spaces from the handoff transcript and reran successfully.

### Phase 2 assumptions and deviations

- Phase 1 notes above describe the earlier handoff; their pending CLI and
  end-to-end work is now complete. No schema or dependency changes.
- Inaccessible source is simulated by a PermissionError from the local
  directory-listing method; no live SMB share is accessed.
- Corruption is injected into a scratch archive after successful collect,
  before the real loader runs, to exercise ArchiveIntegrityError without
  altering source reports or database lineage.
- Per direct human instruction, the task remains in tasks/in-progress/;
  Review and Human acceptance remain unchanged. No acceptance is claimed.
- Existing unrelated uncommitted work, including TASK-007, was preserved.

### Phase 2 unresolved risks

- No blockers or unresolved implementation issues found. Real SMB validation
  before deployment remains outside this local-source task.
- Phase 1's documented limitation still applies: if the database rejects
  failure-history writes, history can only be logged (record if possible).

## Review

Not reviewed.

## Human acceptance

Pending.
