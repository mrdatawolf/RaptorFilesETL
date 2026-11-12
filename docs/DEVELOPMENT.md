# Development Guide

Project-specific operational details. The stack and runtime come from
ADR-001; behavior comes from CONTRACT-001 to CONTRACT-003.

## Technology stack

Selected in ADR-001 (approved 2026-11-11).

| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| `.xls` reading | xlrd 2.x (BIFF8 `.xls` only) |
| Database | SQLite through the standard-library `sqlite3` module |
| SMB access | smbprotocol (`smbclient` module), read directly, no mount |
| Local `.env` | python-dotenv. Variables that are already set take precedence. |
| Time zones | `zoneinfo` + tzdata |
| Contracts | icontract, enabled in production |
| Tests | pytest |

New runtime dependencies need a decision recorded in an ADR.

## Repository layout

Planned. TASK-002 creates it.

```text
pyproject.toml          package metadata, dependencies, `raptor-etl` entry point
.env.example            placeholder configuration (committed)
src/raptor_etl/         the package
tests/                  pytest suite
docs/                   project documentation, contracts, ADRs
tasks/                  task lifecycle
Samples/                real report files, local only, never committed
```

## Setup and commands

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env               # then fill in local values

pytest                             # run the test suite
raptor-etl run                     # one complete pass: collect, parse, load
raptor-etl schedule                # long-running scheduler (Docker entry point)
```

Exit codes for `raptor-etl run` (CONTRACT-001):
`0` success, `1` at least one file missing or failed, `2` invalid
configuration or unusable archive or database, `3` another run in progress,
`4` source unreachable or login failed (precheck), nothing done.

## Configuration

All settings come from environment variables (ADR-001). Locally, a gitignored
`.env` is loaded if present. In Docker, they are set in the TrueNAS custom
app's environment settings. Never commit settings or secrets.

| Variable | Required | Default |
|---|---|---|
| `RAPTOR_SOURCE_PATH` | yes | – (`//host/share` or `\\host\share` means SMB, anything else is a local folder) |
| `RAPTOR_SMB_USERNAME` | when SMB | – |
| `RAPTOR_SMB_PASSWORD` | when SMB | – (never logged) |
| `RAPTOR_SMB_DOMAIN` | no | none |
| `RAPTOR_ARCHIVE_DIR` | yes | – |
| `RAPTOR_DB_PATH` | yes | – |
| `RAPTOR_TIMEZONE` | no | `America/Los_Angeles` |
| `RAPTOR_RUN_TIME` | no | `23:00` |
| `RAPTOR_RUN_DAYS` | no | `MON-FRI` |
| `RAPTOR_LOG_LEVEL` | no | `INFO` |

All variables are validated at startup. If any problem is found, every
problem is logged and the process exits with code 2.

## Coding conventions

- Design by Contract (ADR-001). Use icontract `@require`, `@ensure` and
  `@invariant` for conditions only a bug can break. Use typed exceptions
  (`ConfigError`, `LayoutError`, `ReconciliationError`,
  `ArchiveIntegrityError`) for conditions the outside world can break. Never
  use `assert` for contracts.
- Parsing finds values by label, never by fixed cell coordinates
  (CONTRACT-002).
- Logs go to standard output. Secrets never appear in logs or error messages.
- Timestamps are plant-local text `YYYY-MM-DD HH:MM:SS`, with no offset.

## Testing philosophy

- Each contract's "Validation requirements" section is the minimum test list
  for that stage.
- `Samples/` is the reference fixture set. It is gitignored, so tests that
  need it skip with a clear message when it is absent.
- Tests run offline against a local source folder. SMB is tested by hand
  against the real share before deployment.
- Time-dependent behavior (copy date, schedule) is tested with an injected
  clock, never the system clock.

## Security and privacy

- Secrets come only from environment variables. `.env` is gitignored, and
  `.env.example` holds placeholders only.
- Use a read-only SMB account limited to the report share.
- Plant report files (`Samples/`, the archive) and databases are never
  committed.

## Connection check

On a Windows or Linux test box, create and activate a virtual environment
(`python -m venv .venv`, then `.venv\Scripts\activate` on Windows or
`source .venv/bin/activate` on Linux). Run `pip install -e ".[dev]"` from
the checkout, copy `.env.example` to `.env`, and fill in the source,
credentials, archive and database settings. Then run:

```bash
raptor-etl check
docker exec <container> raptor-etl check  # same check inside the container
```

Each result says `INFO OK` or `ERROR FAIL` with a reason. Successful checks
use INFO (visible by default); failures use ERROR. Source failures include the
host/share or local path and the username where relevant, with passwords scrubbed. Every expected file is fully
read and reports its byte size and SHA-256. A missing database says "will be
created on first run" and is left absent; existing databases are inspected
without migration. The check takes no run lock and writes no files.
Archive writability is checked from filesystem access permissions without
creating a probe file; an actual run still validates writes.
Exit `0` means all checks passed, `1` means a file is absent or unreadable,
`2` means invalid configuration or an unusable/unknown database, and `4`
means the source connection, login or directory listing failed. Compare the
test box and container results to isolate network or container setup issues.

## Docker and TrueNAS deployment

Build the image from the repository root with `docker build -t raptor-etl .`.
The image uses Python 3.12 slim, runs as UID/GID `10001:10001`, and starts
`raptor-etl schedule`. Logs go to stdout (`docker logs <container>`).

Mount persistent storage at `/archive` and `/database`; the defaults are
`RAPTOR_ARCHIVE_DIR=/archive` and `RAPTOR_DB_PATH=/database/bronze.db`.
Mount the entire database directory so the run lock and SQLite sidecar files
share persistent storage. Ensure both mounts already exist and are writable
by UID/GID 10001. For a local source, mount it read-only and set
`RAPTOR_SOURCE_PATH` to its container path. SMB sources need no share mount
or privileged container.

In a TrueNAS custom app, select the built image (make it available to the
TrueNAS host), retain its default entry point, add the two storage mounts,
and set environment variables using the configuration table above. Set
`RAPTOR_SOURCE_PATH` and, for SMB, `RAPTOR_SMB_USERNAME` and
`RAPTOR_SMB_PASSWORD` (plus optional `RAPTOR_SMB_DOMAIN`). Keep credentials
in app environment settings. `.env` files, local samples and databases are
excluded from the build context; `.env.example` remains available.

The defaults are `RAPTOR_RUN_TIME=23:00`, `RAPTOR_RUN_DAYS=MON-FRI`,
`RAPTOR_TIMEZONE=America/Los_Angeles`, and `RAPTOR_LOG_LEVEL=INFO`.
Run time must be `HH:MM` in 24-hour form; days accept an inclusive ascending
range such as `MON-FRI` or a comma list such as `MON,WED,FRI`.
Scheduling uses `RAPTOR_TIMEZONE` directly and does not require `TZ`.
A nonexistent spring-forward time is skipped; both occurrences of a
fall-back time run. Missed runs while stopped or busy are not caught up.

Startup performs `raptor-etl check` once and logs its exit code; a failure
warns and scheduling continues. To diagnose connectivity later, run:

```bash
docker exec <container> raptor-etl check
```

SIGTERM (container stop) and SIGINT interrupt the scheduler wait immediately.
If a pass is active, it finishes and releases its lock before shutdown;
allow enough container termination grace time for a full pass.
