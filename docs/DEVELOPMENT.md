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
