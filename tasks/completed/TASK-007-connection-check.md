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

Task: TASK-007
Implementer: Codex (openai-coder)
Date: 2026-11-11

### Changes made

- Added a shared sanitized source precheck and exit 4 in `run`, under the
  lock and before database initialization, collection or loading.
- Collection now raises a precondition failure before stale-file cleanup
  instead of turning unreachable sources into eight failed outcomes.
  Missing files and individual read failures retain their existing outcomes.
- Added `check`: configuration/archive permission validation without probe
  writes, source listing, full reads with byte sizes and SHA-256, and SQLite
  read-only schema inspection without creation or migration. No lock is taken.
- Updated old source-failure expectations and added offline check tests.

### Validation performed

- `.venv/bin/pytest tests/test_collect.py tests/test_cli_lock.py -q`:
  initially 24 passed, 1 failed (fixture required partial cleanup on precheck
  failure; updated to verify the partial remains untouched).
- `.venv/bin/pytest tests/test_check.py tests/test_collect.py tests/test_cli_lock.py -q`:
  39 passed.
- `.venv/bin/pytest -q`: initially 161 passed, 1 failed (schema-version
  fixture had no source; added a source directory so it reaches database validation).
- `.venv/bin/pytest tests/test_database.py -q`: 20 passed.
- `.venv/bin/pytest -q`: 162 passed.

### Acceptance criteria evidence

- Mocked SMB login/listing failures exit 4 for run and check; planted
  passwords are absent from output. Run does not load or create the database;
  the existing-database collection test verifies zero archived records/files.
- Entry-point tests verify missing local source exits 4 and lock contention
  still exits 3 before precheck.
- A local copy of Samples passes check with every size and full hash verified.
- Mocked SMB missing files/read failures exit 1; login failure exits 4.
- Before/after byte and modification-time snapshots verify no check writes,
  including missing, current, older, newer and invalid databases. Tests reject
  lock acquisition and temporary archive write probes during check.
- Development guide includes Connection check instructions.

### Assumptions and deviations

- Archive writability in check uses filesystem access permissions, because
  the normal temporary-file probe would violate the explicit no-write rule.
  Actual run retains its write probe. This cannot prove a future write succeeds.
- Known older database versions are reported without migration; unknown newer
  versions and unreadable databases exit 2.
- Task remains in-progress by direct human instruction; Review and Human
  acceptance are unchanged. No load-stage implementation or schema was edited.

### Unresolved risks

- Real SMB access remains a human deployment validation step.
- Concurrent TASK-005 work may change the suite after this validation snapshot.

### Documentation updated

- `docs/DEVELOPMENT.md`: Connection check setup, commands, results and exit codes.


### Revision 1

Date: 2026-11-11. Addressed the request for specific, sanitized source-failure
reasons required by CONTRACT-001.

Changes:

- `source.py`: SourceError carries a reason; a shared classifier uses stdlib
  exception types/network errno values and smbprotocol exception types, including
  wrapped SMBOSError status codes. Local listing and open/read failures are
  wrapped consistently. SMB connection and listing are classified separately so
  an otherwise unqualified OSError during connect is a network failure.
- Raw exception messages are never interpolated by the classifier. Configured
  passwords are replaced with `[REDACTED]` in reasons and again at the source
  diagnostic output boundaries, including already-wrapped SourceError messages.
- `precheck.py` preserves the classified reason rather than replacing it.
  Targeted `cli.py` edits show the reason with `run stopped (exit 4)`.
  `check.py` shows it on source and per-file FAIL lines; `collect.py` carries it
  in each failed file outcome and log. Exit codes and per-file semantics remain.
- Added `tests/test_source_reasons.py` covering SMB protocol and wrapped status
  exceptions, local and network failures, connection/listing/open/read paths,
  run/check output, collect outcomes, and planted passwords inside exception
  text and existing SourceError reasons. No dependency, schema, parser or loader
  changes; the load_stage function in cli.py was not edited.

Final reason wording:

- DNS resolution: `host not found`.
- Connection failures/timeouts: `host unreachable / connection refused / timed out`.
- Authentication: `login failed`.
- SMB permissions: `access denied`.
- Missing SMB share/path: `share or path not found`.
- Missing local source directory: `folder missing`.
- Non-directory path (local or SMB): `not a directory`.
- Local permissions: `permission denied`.
- Local file disappearing before read: `file missing`.
- Unclassified exception: `unexpected error: <ExceptionTypeName>`.

Validation (in order):

- `.venv/bin/pytest tests/test_source_reasons.py -q`: **98 passed in 0.40s**.
- `.venv/bin/pytest tests/test_check.py tests/test_collect.py tests/test_cli_lock.py -q`:
  **39 passed in 0.82s**, including existing planted-password and read-only tests.
- `.venv/bin/pytest`: **274 passed in 1.75s**; no TASK-005 failures.
- `git diff --check`: passed before and after this handoff update.

Assumptions/deviations/open questions: no contract deviations or open questions.
Network unreachable, refused and timeout failures share one network category as
requested. Diagnostics omit optional host/path/username details to avoid exposing
untrusted exception text. Existing sanitized SourceError reasons are retained,
with password scrubbing. Task remains in-progress, with Review and Human
acceptance unchanged.

Remaining risks: mocked exceptions and local fixtures verify classification and
output; real SMB access still needs the human deployment check. Unknown failure
types deliberately disclose only their exception type name.


### Revision 2

Date: 2026-11-11. Addressed real SMB exception wrapping, check report levels,
and contextual source diagnostics.

Changes:

- The source classifier walks both __cause__ and __context__, tracking exception
  identity to terminate cycles. Specific DNS/auth/path/permission errors take
  precedence over generic transport errors; unknown wrappers no longer hide
  recognized inner exceptions. Raw exception text is never formatted.
- Source failures include the SMB host/share/path and username where relevant,
  or the local path. Per-file failures include the file path. Configured
  passwords are scrubbed before path normalization and at output boundaries.
- Chose INFO for OK and ERROR for FAIL, retaining the existing logging format.
  INFO is visible with check's default INFO logger; successful checks no longer
  look like warnings. Updated the Development guide's output description.
- Added realistic chained transport/auth/share errors, both-link/cycle handling,
  contextual password scrubbing (including backslashes), and report-level tests.
  Preserved exit codes, check read-only behavior and unrelated changes. No CLI,
  loader, parser, schema or dependency changes in this revision.

Installed-library findings (inspected under .venv/lib/python3.13/site-packages):

- smbprotocol/transport.py Tcp.connect raises ValueError from the socket
  OSError/gaierror. Tests raise ValueError from gaierror, refused, timeout and
  unreachable errors, matching this shape.
- smbprotocol/session.py Session.connect wraps spnego.SpnegoError from client
  creation or context.step in SMBAuthenticationError using explicit chaining.
  Connection.receive builds SMBResponseException from a response header; its
  registry selects LogonFailure for STATUS_LOGON_FAILURE. Session.connect only
  catches MoreProcessingRequired there, so server LogonFailure propagates.
- smbclient/_pool.py get_smb_tree receives BadNetworkName for a missing share;
  it rethrows directly without DFS support (or after unsuccessful DFS fallback).
  smbclient/_io.py SMBRawIO.__init__ converts the response exception into
  SMBOSError(exc.status, path) from exc. listdir uses SMBDirectoryIO on this path.
  Tests construct actual SMB response headers for LogonFailure/BadNetworkName,
  and reproduce the missing-share SMBOSError cause chain. The spnego test
  reproduces SMBAuthenticationError raised from InvalidCredentialError.

Validation commands/results, in order:

- `.venv/bin/pytest tests/test_source_reasons.py -q`: 116 passed in 0.34s.
- `.venv/bin/pytest tests/test_source_reasons.py tests/test_check.py tests/test_collect.py tests/test_cli_lock.py -q`:
  155 passed in 0.93s.
- Real `.venv/bin/raptor-etl check` via subprocess, no mocks, from
  `/tmp/claude-1000/task007-revision2-jyvk75ze`, with all inherited RAPTOR_ settings
  removed and these explicit settings:
  RAPTOR_SOURCE_PATH=//no-such-host.invalid/files,
  RAPTOR_SMB_USERNAME=dummy-user,
  RAPTOR_SMB_PASSWORD=DUMMY-TASK007-REV2-PASSWORD,
  RAPTOR_ARCHIVE_DIR=/tmp/claude-1000/task007-revision2-jyvk75ze/archive,
  RAPTOR_DB_PATH=/tmp/claude-1000/task007-revision2-jyvk75ze/bronze.db.
  Invoked absolute executable
  `/home/patrick/Documents/Github/SFP/RaptorFilesETL/.venv/bin/raptor-etl check`.
  Scratch directory had no .env; timeout bound was 45 seconds. Exact stdout:

```text
INFO OK configuration: valid
INFO OK archive: exists and is writable
ERROR FAIL source: host not found: no-such-host.invalid (//no-such-host.invalid/files)
```

  Exit code: 4. Stderr: empty. Dummy password absent from stdout/stderr: true.
  Database remained absent. The validation subprocess driver exited 0.
- After adding password-before-normalization coverage:
  `.venv/bin/pytest tests/test_source_reasons.py -q`: 117 passed in 0.34s.
- `.venv/bin/pytest`: 293 passed in 1.63s, including TASK-005 tests.
- `git diff --check`: passed after handoff update.

Assumptions/deviations/open questions: no contract deviations or open questions.
Network refusal/unreachable/timeout retain the existing combined network category.
Existing SourceError reasons are preserved and scrubbed instead of contextualized
again, avoiding duplicate paths across source and precheck wrappers. The actual
source wrappers supply context before raising them. Task remains in-progress;
Review and Human acceptance are unchanged.

Remaining risks: real DNS failure is verified; real credentials and share access
still require the human deployment check. Authentication and missing-share
coverage mirrors installed-library source with constructed exceptions rather
than connecting to a live SMB server.

## Review

Not reviewed.

## Human acceptance

Pending.
