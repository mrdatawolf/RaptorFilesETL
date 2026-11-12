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

None. (Previously blocked on the CONTRACT-002 Production Summary header
precondition. Resolved 2026-11-11: the contract was amended with Patrick's
approval. See the CONTRACT-002 Amendments section.)

## Implementation handoff

Task: TASK-003 — Parse Raptor `.xls` reports
Implementer: Codex (openai-coder)
Date: 2026-11-11

### Changes made

- Added `src/raptor_etl/parse/` with public
  `parse_report(path, report_type) -> ParsedReport` and `parse_grid` test seam.
- `grid.py` reads BIFF using existing xlrd, retaining values, cell types and
  workbook date mode in an immutable cell grid. Workbook resources are released.
- `models.py` defines frozen typed header, alarm, grand-total, KPI, breakdown,
  day and report objects; nullable values remain nullable.
- `__init__.py` implements label-based layout/header checks, one extractor per
  report type, plant-local timestamp rendering with nearest-second conversion,
  exact duration/label handling, page-furniture skipping and all reconciliation
  checks. Reuses existing LayoutError and ReconciliationError. Internal grid and
  record-order guarantees use icontract, explicitly enabled in production.
- Added `tests/test_parse_reports.py`: sample assertions, hand-built/altered
  grids, each precondition and invariant, shifted columns, repeated headers,
  continuation, precision/nulls, read-only behavior and unsupported input.
- No existing shared modules, dependencies, collect tests or CLI were changed.

### Validation performed

- Read-only sample parse smoke command (`.venv/bin/python` importing
  `parse_report` and parsing the three sample workbooks): all 3 succeeded and
  printed expected headers/counts and first/last records; no failures.
- `.venv/bin/pytest tests/test_parse_reports.py -q` (first run):
  **76 passed, 1 failed, 0 skipped**. A deliberately invalid inline occurrences
  value was ignored in favor of a later cell. Fixed validation of that value.
- `.venv/bin/pytest tests/test_parse_reports.py -q` (second run):
  **86 passed, 0 failed, 0 skipped**, including new rounding/realignment cases.
- `.venv/bin/pytest tests/test_parse_reports.py -q` (third run):
  **91 passed, 0 failed, 0 skipped**, including missing parallel-section values
  and null reconciliation inputs.
- `.venv/bin/pytest`: **148 passed, 0 failed, 0 skipped**. Includes all 57
  pre-existing tests and 91 new parser cases. Samples were present.
- Read-only scope inspection confirmed parser source contains no database,
  network or file-writing operations, and no production `assert` statements.

### Acceptance criteria evidence

- All three sample reports parse. Tests check all header timestamps, recipe,
  page counts, first/last records and 1-based order. Downtime: 20 alarms,
  380 occurrences and 01:49:49. Production Summary: 34 breakdown records,
  four totals of 58,004, and exact KPI precision (2.8713249629155975).
  ToDate: 81 rows, null 2026-09-23 slow_pct and both 2026-09-16 timestamps.
- Extraction uses discovered labels/columns, never sample coordinates. Tests
  shift entire grids and individual pages. Repeated ToDate and downtime
  headers realign; Production Summary follows the unfinished product section
  onto page 2 and the later Width Summary title is accepted per the amendment.
- Parameterized tests remove every required label, reject late headers/section
  titles and KPI labels, wrong page-1 title/type, absent/unreadable/non-BIFF files
  and non-.xls input. Layout failures identify the file/check.
- Each invariant has a deliberately altered-grid failure: no records for each
  type; downtime occurrence sum, duration sum and both duration-bound
  comparisons; section Total count (zero and two), pieces sum, cross-section
  total equality and relative volume tolerance; null/duplicate ToDate run_start.
  Reconciliation failures identify the check and expected/actual values.
- Read-only tests forbid database connections, network sockets and file writes,
  compare sample SHA-256/mtime before/after and require no output. Sample tests
  skip with an explicit missing-Samples message when unavailable.

### Assumptions and deviations

- Public report-type identifiers match existing bronze schema terminology:
  `downtime_summary`, `production_summary`, `production_todate`.
- Column matching follows labels and their nearest value columns; summary
  continuation retains the unfinished labeled section across page furniture.
- Empty values remain null. Null inputs needed to prove a required numerical
  reconciliation cannot satisfy that invariant and raise ReconciliationError.
- No deviations from CONTRACT-002, including its human-approved amendment.
- Per direct instruction, the task remains in place and only this handoff was
  edited. Review and human acceptance are not changed or claimed.

### Unresolved risks

No known sample/contract conflicts or open questions. Future report-layout
changes remain subject to the contract's LayoutError/reconciliation rejection.
Loading/integration with TASK-005 is outside this task's scope.

### Documentation updated

This Implementation handoff only; contracts, ADRs and shared documentation
were not changed by this implementation.

## Review

Not reviewed.

