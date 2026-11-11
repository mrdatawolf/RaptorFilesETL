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

Not started.

## Review

Not reviewed.

## Human acceptance

Pending.
