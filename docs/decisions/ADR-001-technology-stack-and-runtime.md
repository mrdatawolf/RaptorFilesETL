# ADR-001: Technology stack and runtime

Status: Approved
Date: 2026-11-10
Approved by: Patrick
Approved date: 2026-11-11
Decision owners: Patrick
Related tasks and contracts: TASK-001, CONTRACT-001, CONTRACT-002, CONTRACT-003

## Context

The job copies Raptor report files from an SMB share (`//test/files` for now)
into a dated archive, parses three `.xls` reports, and loads them into a SQLite
bronze database (see `docs/PROJECT.md`). It must:

- run on Linux or Windows, and end up in a Docker container deployed as a
  TrueNAS custom app;
- run at 23:00 Monday to Friday, plant local time (Pacific);
- take all settings and secrets from environment variables: `.env` locally,
  TrueNAS app settings in Docker;
- follow Design by Contract.

Facts from `Samples/` that affect the choice:

- The `.xls` files are legacy BIFF8 (Excel 97–2003) files exported by Crystal
  Reports, not `.xlsx`.
- Dates are stored as Excel serial numbers, durations as `hh:mm:ss` text.
- Layouts are sparse and change between pages. For example, the Volume column
  moves from column 29 to column 28 on page 2 of Production ToDate.

## Decision

### Language and libraries

| Concern | Choice | Why |
|---|---|---|
| Language | **Python 3.12+** | Runs the same on Linux, Windows and Docker. Strong libraries for every need below. |
| `.xls` reading | **xlrd 2.x** | Small, pure Python, reads BIFF8 `.xls` with cell types. Version 2 dropped `.xlsx` support, which this project doesn't need. |
| SQLite | **`sqlite3` (standard library)** | No extra dependency. Transactions give the all-or-nothing loads that CONTRACT-003 requires. |
| SMB access | **smbprotocol (its `smbclient` module)** | Pure Python SMB2/3 client. Works on Linux, Windows and inside a container without mounting the share. Mounting CIFS inside a container needs privileged mode, which TrueNAS apps should avoid. |
| Local `.env` | **python-dotenv** | Loads `.env` only when present. Variables that are already set (for example by TrueNAS) always take precedence. |
| Time zones | **`zoneinfo` + tzdata** | Plant-local time on every platform. tzdata provides the zone database on Windows and slim containers. |
| Contracts | **icontract** | Readable `@require` / `@ensure` / `@invariant` decorators, kept **enabled in production**. Plain `assert` is removed when Python runs with `-O`, so it is not used for contracts. |
| Tests | **pytest** | Standard. `Samples/` serves as local fixture data and is never committed. |

### How Design by Contract is applied

There are two kinds of check, and they are kept separate:

1. **Program contracts** (icontract) cover conditions that only a bug in our
   code can break, for example "the archive file's hash equals the source
   hash" or "a loaded file has exactly one load record". A violation means a
   defect: the run stops processing that file and logs it as a defect.
2. **Input validation** (explicit checks raising typed errors such as
   `ConfigError` or `LayoutError`) covers conditions the outside world can
   break, for example an unrecognised report layout, a missing file or an
   unreachable share. These are expected failures with defined behavior in
   the contracts.

The CONTRACT-NNN documents define observable behavior. icontract decorators
enforce it at function boundaries in the code.

### Runtime shape

One Python package with a command-line interface:

- `raptor-etl run` performs one complete pass (collect, then parse and load)
  and exits with a status code (see CONTRACT-001 and CONTRACT-003).
- `raptor-etl schedule` is a long-running process that calls `run` at
  `RAPTOR_RUN_TIME` on `RAPTOR_RUN_DAYS` in `RAPTOR_TIMEZONE`. This is the
  Docker entry point.

Scheduling runs **inside the container**. A TrueNAS custom app is a
long-running container, so this needs no host cron setup and works the same
on Linux, Windows and TrueNAS. The scheduler is a small loop built on
`zoneinfo`, with no cron library needed. Locally, `run` can also be started by
hand or from any OS scheduler.

Only one run happens at a time, enforced with a lock. A second `run` started
while one is in progress exits at once with exit code 3 and does nothing.

The source can be **SMB or a local folder**. If `RAPTOR_SOURCE_PATH` starts
with `//` or `\\`, it is read over SMB; otherwise it is treated as a local
directory. The local option lets tests and development runs use a copy of
`Samples/`.

The archive and the SQLite database live under paths supplied by environment
variables. In Docker these are mounted TrueNAS volumes.

### Configuration

All configuration comes from environment variables. If a `.env` file is
present in the working directory, it is loaded first without overriding
variables that are already set.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `RAPTOR_SOURCE_PATH` | yes | – | Source folder, e.g. `//test/files` (SMB) or a local path |
| `RAPTOR_SMB_USERNAME` | when SMB | – | SMB user |
| `RAPTOR_SMB_PASSWORD` | when SMB | – | SMB password. Never logged. |
| `RAPTOR_SMB_DOMAIN` | no | none | SMB domain or workgroup, if needed |
| `RAPTOR_ARCHIVE_DIR` | yes | – | Archive folder. Must exist and be writable. |
| `RAPTOR_DB_PATH` | yes | – | SQLite file. Created if missing; the parent folder must exist. |
| `RAPTOR_TIMEZONE` | no | `America/Los_Angeles` | Plant time zone (IANA name). Sets the copy date and the schedule. |
| `RAPTOR_RUN_TIME` | no | `23:00` | Scheduled time, `HH:MM` 24-hour |
| `RAPTOR_RUN_DAYS` | no | `MON-FRI` | Scheduled days: a range or comma list of `MON`…`SUN` |
| `RAPTOR_LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

All variables are checked at startup, before any work. If a required
variable is missing or any value is invalid, the process logs every problem,
naming each variable but never printing secret values, and exits with code 2.
A `.env.example` with placeholder values is committed; `.env` is gitignored.

Logs go to standard output, which is what `docker logs` and the TrueNAS app
log viewer show. Each run ends with a one-line summary per file.

## Alternatives considered

- **pandas for reading `.xls`.** Heavy, and built for tidy tables. These
  reports are sparse page layouts that need cell-level access anyway.
- **Converting with LibreOffice or ssconvert first.** Adds a large binary to
  the container and a second failure point.
- **Mounting the SMB share (host mount or CIFS in the container).** Host
  mounts differ between Windows, Linux and TrueNAS. CIFS inside a container
  needs privileged mode. Reading over SMB directly avoids both.
- **Host scheduler (cron, Task Scheduler, TrueNAS cron) running
  `docker run`.** Works, but the schedule then lives outside the app and
  differs per platform.
- **Plain `assert` or hand-written checks for contracts.** `assert` is removed
  by `-O`. Hand-written checks work but are less readable and less consistent
  than icontract decorators.
- **A database other than SQLite.** Out of scope; SQLite was required.

## Consequences

### Benefits

- One code path everywhere. The same container runs on TrueNAS and on any
  Docker host, and the same package runs directly on Linux or Windows.
- No privileged container and no host mount setup.
- Tests can run fully offline against a local copy of `Samples/`.

### Costs and risks

- A run missed while the container is down is **not caught up later**,
  because the share only holds the current day's files. That day's data is
  lost unless someone runs the job manually before the share is overwritten.
- The SMB password is stored in TrueNAS app settings. Use a read-only
  account limited to the share.
- xlrd is in maintenance mode. That is acceptable because the `.xls` format
  is frozen, but it is still a dependency to watch.
- icontract checks add a small runtime cost, which is negligible at 8 files
  a day.

## Follow-up work

- After approval: record the stack, layout and commands in
  `docs/DEVELOPMENT.md`, and add Python entries to `.gitignore` (`.venv/`,
  `__pycache__/`, `.pytest_cache/`).
- Implementation tasks: Collect (CONTRACT-001), Parse (CONTRACT-002),
  Load (CONTRACT-003), scheduler and Docker packaging.
