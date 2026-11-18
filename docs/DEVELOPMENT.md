# Development Guide

Project-specific operational details. The stack and runtime come from
ADR-001 through ADR-003. Behavior comes from CONTRACT-001 through CONTRACT-004.

## Technology stack

Selected in ADR-001 (approved 2026-11-11).

| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| `.xls` reading | xlrd 2.x (BIFF8 `.xls` only) |
| `.pdf` reading | pdfplumber 0.11.x, used only by `import-pdf` (ADR-002) |
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
raptor-etl import-pdf <folder>     # manual PDF backfill (CONTRACT-004)
```

Exit codes for `raptor-etl run` (CONTRACT-001):
`0` success, `1` at least one file missing or failed, `2` invalid
configuration or unusable archive or database, `3` another run in progress,
`4` source unreachable or login failed (precheck), nothing done.

## Configuration

All settings come from environment variables (ADR-001). Locally, a gitignored
`.env` is loaded if present. Never commit settings or secrets.

| Variable | Required | Default |
|---|---|---|
| `RAPTOR_SOURCE_PATH` | yes | – (`//host/share` or `\\host\share` means SMB, anything else is a local folder) |
| `RAPTOR_SMB_USERNAME` | when SMB | – |
| `RAPTOR_SMB_PASSWORD` | when SMB | – (never logged) |
| `RAPTOR_SMB_DOMAIN` | no | none |
| `RAPTOR_ARCHIVE_DIR` | yes | – |
| `RAPTOR_DB_PATH` | yes | – |
| `RAPTOR_TIMEZONE` | no | `America/Los_Angeles` |
| `RAPTOR_LOG_LEVEL` | no | `INFO` |

Python validates the `RAPTOR_*` settings listed above at startup. If any problem is found, every
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
- `Samples/` holds real reports (gitignored, local only) in this layout:
  `Samples/XLS/<MM_DD_YYYY>/` (the four share `.xls` files) and
  `Samples/PDF/<MM_DD_YYYY>/` (hand-downloaded PDFs, lowercase names, no
  Downtime Summary). Folder names are not report dates: `XLS/11_11_2026`
  holds reports printed 2026-11-13. Tests that need a missing sample skip
  with a message naming it.
- The reference day is `XLS/11_09_2026` and `PDF/11_09_2026`. The
  `make_share` fixture (`tests/conftest.py`) builds the 8 CONTRACT-001 share
  files from it, renaming the PDFs to the share's spelling and writing a
  stand-in `Downtime Summary.pdf` (collect never reads PDF content).
- Tests run offline against a local source folder. SMB is tested by hand
  against the real share before deployment.
- Time-dependent behavior (copy date) is tested with an injected
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
means the source connection, login or directory listing failed.

## Host deployment

ADR-003 installs the Linux job in `/srv/RaptorFilesETL` as `biztech`.
Use Python 3.12+ to create `.venv` there and install the package with
`.venv/bin/pip install .`. Give `biztech` access to the project, archive
and database directories. Set the configuration in `.env` using shell
assignments, quoting values as needed.

**Before the first run of this schema, delete the old database and archive.**
Create an empty writable archive directory. Both schemas use version 1,
so an existing database would retain the old schema. Archived reports
from before deployment are discarded.

Set `PUSH_PULL=push` and `RAPTOR_PUSH_DEST` to the rsync destination
directory. These two settings belong to the Linux launcher. Delivery
requires rsync and SSH access for `biztech` when using a remote
destination. For a local check, use an existing local directory.

Install `raptorbronze.service` and `raptorbronze.timer` in
`/etc/systemd/system/`, reload systemd with `systemctl daemon-reload`
and enable the timer with `systemctl enable --now raptorbronze.timer`.
The timer starts the oneshot service Monday through Friday at 23:00
America/Los_Angeles. Missed runs are skipped. Inspect logs with
`journalctl -u raptorbronze.service`.

`start.sh` runs the ETL and delivers a SQLite backup snapshot named
`trimmer.db` on exit 0 or 1. On successful delivery it returns the ETL
status. A delivery failure returns the failing command's status. Set
`TRIMMER_DB=/srv/data/bronze/trimmer.db` in the deployed SFPDataAPI
configuration and remove the stale `raptor.db` from the bronze server
during cutover.

On Windows, create `.venv`, install the package as described above and
run `start.bat` to build the local database.

## PDF backfill (last resort)

`raptor-etl import-pdf <folder>` loads Production Summary and Production
ToDate reports from their PDF exports, for days that have no `.xls` load
(CONTRACT-004). Use it only when the `.xls` files for those days are gone.
It runs against the local archive and database.

- The folder is searched recursively. File names are matched ignoring case
  (`production summary.pdf`, `Production Todate.pdf`). Thickness Breakdown,
  Downtime Summary and other PDFs are logged as `ignored: not supported`.
- A PDF is skipped when an `.xls` load exists for the same report type and
  printed date. Running the import again loads nothing new.
- Each loaded PDF is archived as `{printed date}_{Production Summary|Production Todate}.pdf`.
- PDF numbers are rounded to what the report shows. ToDate rows have no time
  in the PDF: they are stored as `00:00:00`, and a repeated date gets
  `00:00:01`, `00:00:02` and so on. These times are invented. PDF-sourced loads
  are the `file_load` rows whose `archived_file.original_name` ends in `.pdf`.

Exit codes: `0` every PDF loaded, skipped or ignored; `1` at least one PDF
failed (see its log line and `load_failure`); `2` invalid configuration,
folder or database; `3` another run in progress. To retry after a failure,
fix the cause and run the same command again.

On the Windows test box:

```bat
.venv\Scripts\activate
raptor-etl import-pdf "C:\path\to\pdfs"
```
