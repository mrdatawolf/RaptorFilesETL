# TASK-006: Scheduler and Docker packaging

Owner role: implementer
Assigned agent: Codex (openai-coder)
Proposed by: Claude (main session)
Proposed date: 2026-11-11
Approved by:
Approved date:
Related contracts: CONTRACT-001
Related ADRs: ADR-001
Dependencies: TASK-002 (TASK-005 for a meaningful container run)

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

- [ ] Next-run tests with an injected clock: weekday 22:59 → same day 23:00; Friday 23:01 → Monday 23:00; across both DST transitions.
- [ ] Invalid schedule variables → exit code 2.
- [ ] SIGTERM stops the loop cleanly.
- [ ] `docker build` succeeds and the image contains no `.env`, `Samples/` or database files.

## Validation requirements

pytest for scheduling; `docker build` output summarized in the handoff (if
Docker is available to the implementer; otherwise say so).

## Risks and assumptions

None beyond ADR-001.

## Blocker

None.

## Implementation handoff

Not started.

## Review

Not reviewed.

## Human acceptance

Pending.
