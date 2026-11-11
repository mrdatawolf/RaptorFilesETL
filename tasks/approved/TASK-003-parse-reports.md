# TASK-003: Parse Raptor `.xls` reports

Owner role: implementer
Assigned agent: Codex (openai-coder)
Proposed by: Claude (main session)
Proposed date: 2026-11-11
Approved by: Patrick
Approved date: 2026-11-11
Related contracts: CONTRACT-002
Related ADRs: ADR-001
Dependencies: TASK-002

## Desired outcome

`parse_report(path, report_type) -> ParsedReport` implementing CONTRACT-002
for Downtime Summary, Production Summary and Production ToDate.

## Context

CONTRACT-002 defines every field, precondition, invariant and test. The
TASK-001 handoff records sample findings: columns shift between pages, ToDate
has a blank Slow % on 2026-09-23 and two runs on 2026-09-16, dates are Excel
serials and durations are text.

## Scope

### Included

- Typed result objects for `ParsedReport`, header and each record type.
- Label-based extraction that realigns at repeated headers; page furniture
  skipped.
- All CONTRACT-002 preconditions (`LayoutError`) and invariants
  (`ReconciliationError`), with icontract on internal guarantees.
- Tests from CONTRACT-002 "Validation requirements".

### Excluded

- Database writes, file selection (TASK-005). PDFs and Thickness Breakdown.

## Plan

1. Read the sheet into a small cell-grid abstraction (value + type per cell)
   so tests can feed altered grids without writing `.xls` files.
2. Header and layout checks.
3. One extractor per report type.
4. Invariant checks.
5. Tests against `Samples/` plus altered grids for each failure path.

## Acceptance criteria

- [ ] The three `Samples/` `.xls` files parse and match CONTRACT-002 hand-checked values (20 alarms, 380 / 01:49:49; 58,004 pieces in all four sections; 81 ToDate rows, null 2026-09-23 `slow_pct`, both 2026-09-16 rows; header timestamps).
- [ ] No fixed cell coordinates in extraction code.
- [ ] Each invariant has a test that triggers its `ReconciliationError`.
- [ ] Wrong declared type and non-`.xls` input raise `LayoutError`.
- [ ] `parse_report` has no side effects (no DB, network or file writes).

## Validation requirements

pytest. Tests needing `Samples/` skip with a clear message when it is absent.

## Risks and assumptions

- No new dependencies. If writing altered `.xls` fixtures seems necessary
  (e.g. xlwt), stop and ask instead.

## Blocker

None.

## Implementation handoff

Not started.

## Review

Not reviewed.

