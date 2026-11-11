# TASK-005: Load parsed reports into SQLite bronze

Owner role: implementer
Assigned agent: Codex (openai-coder)
Proposed by: Claude (main session)
Proposed date: 2026-11-11
Approved by:
Approved date:
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

Not started.

## Review

Not reviewed.

## Human acceptance

Pending.
