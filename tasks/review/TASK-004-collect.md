# TASK-004: Collect report files into the dated archive

Owner role: implementer
Assigned agent: Codex (openai-coder)
Proposed by: Claude (main session)
Proposed date: 2026-11-11
Approved by: Patrick
Approved date: 2026-11-11
Related contracts: CONTRACT-001
Related ADRs: ADR-001
Dependencies: TASK-002

## Desired outcome

The collect stage of `raptor-etl run`, implementing CONTRACT-001 for both a
local source folder and an SMB share.

## Context

CONTRACT-001 defines the 8 expected files, archive naming, the step-by-step
behavior, outcomes, failure table and tests. Its open question is answered:
files stay byte-identical on no-production days.

## Scope

### Included

- Source abstraction with two implementations: local folder and SMB
  (smbprotocol `smbclient`), chosen by `RAPTOR_SOURCE_PATH` prefix.
- Read-only access to the source; streaming SHA-256 while copying to
  `.<archive name>.partial`; verify; atomic rename; `archived_file` insert.
- All outcomes (`archived`, `unchanged`, `missing`, `failed`), the
  interrupted-run recovery case and stale `.partial` cleanup.
- Copy date fixed once per run from the injected plant-local clock.
- Wiring into `raptor-etl run` with the exit-code contribution.
- Tests from CONTRACT-001 "Validation requirements".

### Excluded

- Loading (TASK-005). Automated SMB tests (manual check only, per contract).

## Plan

1. Source abstraction (local, SMB).
2. Per-file collect procedure following CONTRACT-001 steps 1–5.
3. CLI wiring and logging.
4. Tests on a temporary copy of `Samples/`.

## Acceptance criteria

- [ ] Every CONTRACT-001 validation test is implemented and passes.
- [ ] Source folder unchanged after every test (hash and mtime).
- [ ] Copy date follows `RAPTOR_TIMEZONE` (23:30 Pacific test).
- [ ] SMB password never in logs or exception messages.
- [ ] SMB code path covered by a unit test with the client mocked; a manual SMB check procedure is written in the handoff.

## Validation requirements

pytest; handoff summarizes results.

## Risks and assumptions

- SMB login failure must produce `failed` for all 8 files and still let the
  load stage run.

## Blocker

None.

## Implementation handoff

Not started.

## Review

Not reviewed.

