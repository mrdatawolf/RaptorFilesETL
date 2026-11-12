# TASK-006: Scheduler and Docker packaging

Owner role: implementer
Assigned agent: Codex (openai-coder)
Proposed by: Claude (main session)
Proposed date: 2026-11-11
Approved by: Patrick
Approved date: 2026-11-11
Related contracts: CONTRACT-001
Related ADRs: ADR-001
Dependencies: TASK-002, TASK-007 (TASK-005 for a meaningful container run)

## Desired outcome

`raptor-etl schedule` runs `run` at `RAPTOR_RUN_TIME` on `RAPTOR_RUN_DAYS`
in `RAPTOR_TIMEZONE`, and a Docker image runs it as a TrueNAS custom app.

## Context

ADR-001: scheduling inside the container, a small `zoneinfo` loop with no
cron library, no catch-up of missed runs, logs to stdout.

## Scope

### Included

- Schedule parsing (`HH:MM`, `MON-FRI` ranges and comma lists) validated at
  startup (exit 2 on invalid).
- Next-run calculation in plant time, correct across DST changes; sleep
  until then; run; repeat. A failed run is logged and the loop continues.
- Clean shutdown on SIGTERM.
- Startup connection check: when `schedule` starts, it runs the TASK-007
  check once and logs the result. A failure is logged as a warning and the
  scheduler keeps running, because the next scheduled `run` handles and logs
  the failure per CONTRACT-001.
- `Dockerfile` (slim Python 3.12 base, non-root user, `raptor-etl schedule`
  entry point, archive and DB paths as volumes) and `.dockerignore`
  excluding `.env`, `Samples/`, databases.
- A short deployment section in `docs/DEVELOPMENT.md` (env vars, volumes,
  TrueNAS notes).

### Excluded

- Catch-up of missed runs. Publishing the image to a registry.

## Plan

1. Schedule parsing and next-run calculation (pure, clock-injected).
2. Loop and signal handling.
3. Dockerfile and docs.

## Acceptance criteria

- [ ] Next-run tests with an injected clock: weekday 22:59 → same day 23:00; Friday 23:01 → Monday 23:00; normal 23:00 runs on the days either side of both DST changes; with a run time of 02:30, the spring-forward day is skipped; with a run time of 01:30, the fall-back day runs twice (ADR-001).
- [ ] Invalid schedule variables → exit code 2.
- [ ] SIGTERM stops the loop cleanly.
- [ ] On startup, `schedule` logs the connection check result, and a failing check does not stop the scheduler.
- [ ] `docker build` succeeds and the image contains no `.env`, `Samples/` or database files.

## Validation requirements

pytest for scheduling; `docker build` output summarized in the handoff (if
Docker is available to the implementer; otherwise say so).

## Risks and assumptions

None beyond ADR-001.

## Blocker

None. (Previously blocked on the DST policy. Resolved 2026-11-11 by Patrick
and recorded in ADR-001 under Runtime shape: a nonexistent spring-forward
time is skipped, and an ambiguous fall-back time runs at both occurrences.)

## Implementation handoff

Task: TASK-006 — Scheduler and Docker packaging
Implementer: Codex (openai-coder)
Date: 2026-11-11

### Changes made

- Added `src/raptor_etl/scheduler.py`: injected-clock next-run calculation,
  interruptible event waits, serial passes, startup check result logging,
  exit-code logging and SIGTERM/SIGINT handling with handler restoration.
- UTC round trips reject nonexistent local times and distinguish both folds
  of ambiguous times. Next slots are strictly after now; missed slots are
  never replayed after startup or a long pass.
- Targeted `cli.py` edits replace the schedule stub. Scheduled passes call
  the existing `main(["run"])` path, preserving lock, precheck, collection,
  loading and exit codes. Startup calls the shared TASK-007 `check` function;
  nonzero results warn and scheduling continues.
- Reused existing `config.py` validation without changes: strict HH:MM,
  ascending weekday ranges or comma lists, aggregated errors and exit 2.
- Added Python 3.12 slim Docker packaging, UID/GID 10001, archive/database
  volumes and exec-form scheduler entry point. Added `.dockerignore` rules
  excluding secrets, samples, databases, virtualenv, caches and git metadata,
  while retaining `.env.example`.
- Added 37 scheduler tests and removed the obsolete schedule-stub assertion
  from the existing CLI test. Preserved other tasks' uncommitted changes.

### Validation performed

- `.venv/bin/pytest tests/test_scheduler.py -q`: 25 passed initially.
- `.venv/bin/pytest tests/test_scheduler.py tests/test_config.py tests/test_cli_lock.py tests/test_check.py -q`:
  59 passed initially; 71 passed after expanding pass-exit-code coverage and
  wiring startup directly to the shared check function.
- `.venv/bin/pytest`: **334 passed**, no skips, in 1.73s. Local interpreter:
  Python 3.13.5; the image targets Python 3.12.
- `git diff --check`: passed before and after the final code edits; repeated
  after handoff documentation. Read-only diff/status and file inspection
  confirmed targeted integration and the Dockerfile/ignore rules.
- An initial file-edit command used unavailable `python` and failed with
  command-not-found; reran successfully with `.venv/bin/python`. No tests
  were run with the missing executable.
- Docker is not installed. **Docker build was not validated**; no build,
  image-content inspection or container run was attempted.

### Acceptance criteria evidence

- Injected-clock tests cover same-day 23:00, Friday-to-Monday rollover,
  23:00 on both sides of both DST transitions, spring-forward 02:30 skip,
  and fall-back 01:30 at both fold=0 and fold=1.
- Invalid time/day environment variables return exit 2 through the CLI.
- Stub waits advance injected time with no real waiting. Loop tests cover
  all pass exit codes 0–4 and confirm a second pass occurs, with a missed
  Monday slot skipped after a long Friday pass.
- Startup check codes 0, 1, 2 and 4 are logged at INFO/WARNING and do not
  prevent scheduled execution. CLI integration exercises the shared check
  and run paths with an unavailable source (exit 4).
- Simulated SIGTERM and SIGINT during the injected event wait stop before
  running a pass and restore previous signal handlers.
- Dockerfile and ignore rules exist as scoped; build-dependent acceptance
  remains unverified. Deployment documentation is present.

### Assumptions and deviations

- No behavior deviations from task/ADR. Existing schedule syntax validation
  was sufficient, so no config refactor or dependency was needed.
- A signal during a pass requests shutdown after that pass completes,
  allowing normal cleanup and lock release. Deployment guidance calls out
  sufficient termination grace time.
- Kept this task in `tasks/in-progress/` per explicit human instruction,
  overriding the normal handoff transition. Review and Human acceptance
  sections are unchanged. No git-writing commands were run.

### Unresolved risks

- Docker build and runtime behavior, Python 3.12 image execution, image
  contents, TrueNAS volume permissions and live SMB access still require
  deployment validation. Mounted storage must be writable by UID/GID 10001.
- A forced kill after an insufficient container grace period can interrupt
  a running pass; existing archive recovery behavior applies.
- No open policy questions or blockers.

### Documentation updated

- Added Docker and TrueNAS deployment guidance to `docs/DEVELOPMENT.md`,
  including configuration, volumes, wall-clock DST behavior, no catch-up,
  startup check, shutdown and `docker exec <container> raptor-etl check`.
- Filled this Implementation handoff in place using the implementation
  report template. No ADR or contract changes.

## Review

Not reviewed.

## Human acceptance

Pending.
