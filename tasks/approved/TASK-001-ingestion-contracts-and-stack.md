# TASK-001: Define ingestion contracts and technology stack

Owner role: contract-architect (contracts), jarvis (ADR)
Assigned agent: Claude
Proposed by: Claude (main session)
Proposed date: 2026-11-10
Approved by: Patrick
Approved date: 2026-11-10
Related contracts: CONTRACT-001, CONTRACT-002, CONTRACT-003 (to be written)
Related ADRs: ADR-001 (to be written)
Dependencies: Human review of `docs/PROJECT.md`

## Desired outcome

Approved behavioral contracts for each pipeline stage and an approved
technology-stack decision, so that implementation tasks can be written against
them. This task is design only. It produces no application code.

## Context

See `docs/PROJECT.md`. The pipeline has three stages: collect files from the
SMB share into a dated archive, parse each `.xls` report, and load the results
into SQLite bronze. The project uses Design by Contract.

## Scope

### Included

- **ADR-001: technology stack and runtime.** Language, `.xls` reader, SQLite
  access and the test framework. Must run on Linux and Windows, and in Docker.
  Covers:
  - How the SMB share is reached: mounted on the host and passed into the
    container, or read directly from inside the container with an SMB client
    library.
  - Where scheduling lives: inside the container, or a host scheduler that
    starts the container.
  - Time zone handling, because the 23:00 Monday-to-Friday run is in plant
    local time.
  - Configuration is already decided: everything comes from environment
    variables, using a gitignored `.env` locally and TrueNAS custom app
    settings in Docker. The ADR names the variables and decides how a missing
    or invalid variable fails at startup.

  Record the result in `docs/DEVELOPMENT.md` once it is approved.
- **CONTRACT-001: Collect.** Copy files from the share to the archive.
  - Pre: the share is reachable; the source file exists and is readable.
  - Post: the archive file is named with the copy date and its hash equals the
    source hash; the source is unchanged.
  - A source file whose hash matches an already-archived file is skipped
    (the weekday no-production case).
  - Defines: the behavior when the share is unreachable, a file is missing, or
    the archive name already exists.
- **CONTRACT-002: Parse.** One section per report type.
  - Pre: the file's title and header labels match the expected layout.
  - Post: the typed rows and report metadata (window, printed time, recipe).
  - Invariant: totals reconcile where the report prints them, for example in
    Production Summary.
  - Defines: how an unrecognised layout is rejected.
- **CONTRACT-003: Load to bronze.**
  - Each file loads in one transaction, so a load fully succeeds or leaves
    nothing behind.
  - The file's hash is recorded, and a file with an already-loaded hash is
    skipped.
  - Every row records its source file, hash and load time.
  - Defines: the bronze schema at the level of what can be observed.

### Excluded

- Implementation of any stage.
- Thickness Breakdown parsing. Its files are archived but not parsed.
- Layers beyond bronze.

## Plan

1. Human reviews `docs/PROJECT.md`. Its remaining open questions are
   proposals and can be settled in ADR-001.
2. jarvis drafts ADR-001; the human approves it.
3. contract-architect drafts CONTRACT-001 to CONTRACT-003, using `Samples/` as
   reference input; the human approves them.
4. The approved contracts become the basis for implementation tasks
   (provisionally TASK-002 Collect, TASK-003 Parse, TASK-004 Load, and
   TASK-005 Scheduling).

## Acceptance criteria

- [ ] ADR-001 is approved and `docs/DEVELOPMENT.md` is updated.
- [ ] CONTRACT-001 to CONTRACT-003 are approved. Each states its
      preconditions, postconditions, invariants and failure behavior.
- [ ] Each contract condition can be tested against the files in `Samples/`.

## Validation requirements

Human review of the ADR and the contracts.

## Risks and assumptions

- Assumes the report layouts are stable from day to day. Layout changes are
  caught by the Parse preconditions.
- Copy date and report date can differ if a run is delayed past midnight.
  This is acceptable because the copy date is used for storage only.

## Blocker

None.

## Implementation handoff

Task: TASK-001
Implementer: Claude
Date: 2026-11-10

### Changes made

All new documents have status **Proposed** and are waiting for human approval:

- `docs/decisions/ADR-001-technology-stack-and-runtime.md`
- `docs/contracts/CONTRACT-001-collect.md`
- `docs/contracts/CONTRACT-002-parse-reports.md`
- `docs/contracts/CONTRACT-003-load-bronze.md`

No application code was written.

### Validation performed

- Inspected all `Samples/` files. The PDFs were read with `pdftotext`. The
  `.xls` files were converted with `ssconvert` to CSV and XLSX in a scratch
  directory outside the repo, to read values and raw cell types.
- Checked every invariant in CONTRACT-002 against `Samples/`, and all hold:
  - Downtime: 20 alarms add up to the Grand Total of 380 occurrences and
    01:49:49.
  - Production Summary: product, length, grade and width pieces each add up
    to the section Total of 58,004.
  - Production ToDate: 81 rows, all with unique `run_start`.
- Confirmed that dates are stored as Excel serial numbers and durations as
  text.

### Acceptance criteria evidence

- Criterion 1: ADR-001 is drafted. Approving it and updating
  `docs/DEVELOPMENT.md` are human or follow-up steps; `DEVELOPMENT.md`
  should be updated only after approval, as the ADR says.
- Criterion 2: the contracts are drafted. Each has sections for
  preconditions, required behavior, postconditions and invariants, and
  failure behavior. Approval is pending.
- Criterion 3: each contract's validation section lists tests using
  `Samples/`, with expected values.

### Assumptions and deviations

- No deviations from scope.
- Data findings that shaped the contracts:
  - Column positions shift between pages, so values must be found by label,
    not by position.
  - ToDate has a blank cell (2026-09-23, Slow %), so value columns can be
    null.
  - ToDate has two runs on 2026-09-16, so rows are keyed by start time, not
    by date.
  - "Page N of N" appears only once in the `.xls` export, so page
    completeness can't be checked.
- Design choices made within scope; challenge any of these at approval:
  - The scheduler runs inside the container.
  - SMB is read directly over the network rather than mounted.
  - icontract is used for program contracts, and explicit errors for bad
    input.
  - The archive is a single flat folder.
  - If an archive name already exists with different content, that file
    fails. It is never overwritten.
  - Failed loads are retried automatically on every run.
  - Lineage and load bookkeeping tables live in the bronze database.
  - Durations are stored as text, exactly as shown in the report.

### Unresolved risks

- CONTRACT-001 open question: the files on a no-production weekday may not
  be byte-identical to the previous day's. If they aren't, they will be
  archived and loaded again. To check against real share behavior.
- A run missed while the container is down cannot be caught up later
  (ADR-001).

### Documentation updated

The new ADR and contracts above. `docs/DEVELOPMENT.md` is deliberately
unchanged until ADR-001 is approved.

## Review

Not reviewed.

## Human acceptance

Pending.
