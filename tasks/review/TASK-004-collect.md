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

Task: TASK-004 — Collect report files into the dated archive
Implementer: Codex (openai-coder)
Date: 2026-11-11

### Changes made

- Added `src/raptor_etl/source.py`: read-only local and SMB source implementations,
  selected from the configured path prefix. SMB uses `smbclient` directly,
  with optional domain-qualified username and sanitized exception messages.
- Added `src/raptor_etl/collect.py`: the eight case-sensitive expected names in
  contract order, one plant-local copy date per run, streamed SHA-256 copy,
  verification, atomic rename, transactional `archived_file` insert,
  deduplication, interrupted-run recovery, conflict protection, per-file
  outcomes/logging, and stale partial cleanup (including earlier dates).
- Connected collect to the existing CLI stage hook. Missing/failed outcomes
  contribute exit code 1 while still calling load.
- Added `tests/test_collect.py`. Updated two foundation CLI expectations that
  assumed the placeholder succeeded despite a nonexistent source folder.
  No parser modules/tests or database schema were changed.

### Validation performed

- `.venv/bin/pytest tests/test_collect.py -q`: 15 passed, 0 failed, 0 skipped
  (initial tests).
- `.venv/bin/pytest -q`: 53 passed, 2 failed, 0 skipped initially. Both failures
  were obsolete placeholder expectations for a nonexistent source; updated
  those expectations to the contract's exit code 1.
- `.venv/bin/pytest tests/test_collect.py tests/test_cli_lock.py -q`:
  25 passed, 0 failed, 0 skipped after adding streaming faults and CLI success.
- `.venv/bin/pytest`: 57 passed, 0 failed, 0 skipped (40 foundation tests plus
  17 collect tests). Samples were available. No real network calls were made.

### Acceptance criteria evidence

- Tests cover first archive, identical rerun, one changed file on a later day,
  missing/case-mismatched source, ignored extra files, conflicting archive,
  record recovery, stale partials, read/write/hash/database failures and retry,
  unavailable source, CLI success/failure, and load-stage visibility.
- Collection attempts compare temporary source file SHA-256 and nanosecond mtime
  before/after; CLI integration also checks source preservation. Tests use
  temporary copies of `Samples/` and skip clearly if it is absent.
- Injected 07:30 UTC produces the previous day's 23:30 Pacific copy date;
  a midnight-crossing provider is sampled exactly once.
- Mocked SMB tests cover both path prefixes, credentials/domain, binary read-only
  access, sanitized login/read exceptions, and all-eight-failed login behavior
  with the load hook still called. Password canaries do not appear in output.
- Concurrent CLI run returns 3 without collecting; existing subprocess lock and
  process-death tests also pass.

### Assumptions and deviations

- The answered no-production question is applied: byte-identical source files
  are unchanged regardless of the current copy date.
- Collect runs under the foundation run lock, which serializes application
  archive writers. Existing archives are checked before rename and never
  intentionally replaced. External writers must not modify the archive.
- A database failure after rename leaves the verified final file for the
  contract's interrupted-run recovery on a subsequent run; no archive is deleted.
- Direct task instructions take precedence over lifecycle guidance: this file
  remains in `tasks/in-progress/`; Review and acceptance are untouched.
- Automated SMB coverage uses mocks as explicitly requested; no live SMB test
  was performed. No behavior or schema deviations.

### Unresolved risks

Manual SMB validation is required before deployment. Procedure:

1. Use an account with read-only access to the real report share. Supply
   `RAPTOR_SOURCE_PATH`, `RAPTOR_SMB_USERNAME`, `RAPTOR_SMB_PASSWORD`, optional
   `RAPTOR_SMB_DOMAIN`, and `RAPTOR_TIMEZONE` through the environment or a
   gitignored `.env`; never paste credentials into commands or reports.
2. Set `RAPTOR_ARCHIVE_DIR` to an existing writable, empty test archive and
   `RAPTOR_DB_PATH` to a fresh test database with an existing parent directory.
   Record source hashes and modification times using authorized read-only tools.
3. Run `.venv/bin/raptor-etl run`. Confirm eight `archived` outcomes, plant-local
   dated names, matching SHA-256/size values and eight `archived_file` rows.
   Confirm source hashes/mtimes are unchanged and no partials remain.
4. Run again before source content changes: expect eight `unchanged` outcomes
   and no additional archive files or database records. Confirm logs contain
   no password. Retain test archives according to the contract.
5. Optionally use deliberately invalid test credentials and confirm eight
   sanitized `failed` outcomes and exit code 1. The automated test verifies
   continuation to load; loading itself remains TASK-005.

Real SMB permissions, server availability and behavior await that manual check.

### Documentation updated

This implementation handoff only. Contract/ADR behavior remains unchanged.

## Review

Not reviewed.

