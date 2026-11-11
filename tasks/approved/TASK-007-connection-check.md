# TASK-007: Source precheck in `run` and the `raptor-etl check` command

Owner role: implementer
Assigned agent: Codex (openai-coder)
Proposed by: Claude (main session)
Proposed date: 2026-11-11
Approved by: Patrick
Approved date: 2026-11-11
Related contracts: CONTRACT-001 (amended 2026-11-11), CONTRACT-003
Related ADRs: ADR-001
Dependencies: TASK-004

## Desired outcome

One precheck runs everywhere. Every `run` checks first that the source is
reachable. If it isn't, the run stops with exit code 4 and does nothing.
Operators can also run the same check read-only with `raptor-etl check`:
by hand on a test box at the plant, by `docker exec` in the container, and
automatically when the container starts (TASK-006). If the check passes on
the test box but fails in the container, the problem is the container or its
network, not the share or the credentials.

## Context

CONTRACT-001 was amended on 2026-11-11. An unreachable source or a failed
login is now a precondition failure that stops the run (exit code 4).
Before, all 8 files were marked `failed` and the run continued to load.
TASK-004 (in review) was built against the old wording, so its behavior and
tests for that case have to change. Read the Amendments, Preconditions,
Failure behavior, Interfaces and Validation sections of CONTRACT-001.

## Scope

### Included

- A precheck module that reuses `source.py`: connect or log in and list the
  source folder. Errors are sanitized, so the password never appears.
- `run`: after configuration validation and the lock, run the precheck.
  If it fails, log the reason and exit 4 without collecting or loading.
  Remove the old "unreachable → all 8 `failed`, continue to load" behavior,
  and update the TASK-004 tests that asserted it.
- `raptor-etl check`, strictly read-only (no lock, and no writes to the
  source, archive or database). It reports `OK` or `FAIL` with a reason for:
  1. configuration (invalid → exit 2, as usual);
  2. the precheck: source reachable and login OK (failure → exit 4);
  3. each of the 8 expected files: present or absent, its size, and a full
     read with SHA-256 through the same source code (any absent or
     unreadable file → exit 1);
  4. the archive folder exists and is writable (the existing config check);
  5. the database path: opened without creating or changing anything, and
     its schema version is known. A missing file is reported as "will be
     created on first run", not as a failure.

  Exit code 0 when everything is OK.
- A short "Connection check" section in `docs/DEVELOPMENT.md`: how to run it
  on a Windows or Linux test box (venv, `pip install`, `.env`) and in the
  container (`docker exec <container> raptor-etl check`), and how to read
  the result.
- Tests for the new CONTRACT-001 validation items and the TASK-007
  acceptance criteria.

### Excluded

- The startup check in `schedule` (TASK-006).
- Any other change to collect behavior. Missing files and per-file read
  errors are still per-file outcomes, as before.
- Running against the real share, which is a human step after delivery.

## Plan

1. Precheck module.
2. Wire the precheck into `run`; update the TASK-004 tests.
3. The `check` subcommand and its report.
4. Tests, then documentation.

## Acceptance criteria

- [ ] `run` with the source unreachable or a failed login (SMB client
      mocked) exits 4, creates no archive files or `archived_file` records,
      does not call the load stage, and keeps the password out of the output.
- [ ] `run` with a missing local source folder exits 4.
- [ ] `raptor-etl check` against a local copy of `Samples/` reports
      everything OK and exits 0.
- [ ] With a mocked SMB client, `check` gives: login failure → `FAIL` and
      exit 4; a missing file → `FAIL` and exit 1; a read error → `FAIL` and
      exit 1.
- [ ] `check` creates or changes nothing in the source, the archive or the
      database location (including not creating a missing database), and
      takes no lock.
- [ ] `docs/DEVELOPMENT.md` has the Connection check section.
- [ ] The full test suite passes.

## Validation requirements

pytest. After delivery, the human runs `raptor-etl check` from a computer on
the plant network against the real share.

## Risks and assumptions

- Stopping on an unreachable source means earlier failed loads are not
  retried that night. They retry on the next run whose precheck passes
  (CONTRACT-003, amended).
- Adding `check` extends the CLI listed in ADR-001 (`run`, `schedule`). It is
  read-only and additive, so it is recorded in the contracts and
  `docs/DEVELOPMENT.md` rather than in a new ADR.

## Blocker

None.

## Implementation handoff

Not started.

## Review

Not reviewed.

## Human acceptance

Pending.
