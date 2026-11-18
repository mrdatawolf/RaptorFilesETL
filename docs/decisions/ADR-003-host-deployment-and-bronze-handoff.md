# ADR-003: Host deployment and hand-off to SFPDataAPI

Status: Approved
Date: 2026-11-17
Approved by: Patrick
Approved date: 2026-11-18
Decision owners: Patrick
Supersedes: the Docker/TrueNAS parts of ADR-001 (Runtime shape, Configuration
notes on Docker, Consequences). The language, library and Design by Contract
choices in ADR-001 are unchanged, including "runs on Linux or Windows".
Related tasks and contracts: TASK-011, CONTRACT-003

## Context

ADR-001 planned to run this job as a long-running Docker container on TrueNAS,
with its own scheduler. Two things have changed:

- The bronze database now has a defined consumer: **SFPDataAPI**, the
  office-side unified mill-data API. It reads it as the `trimmer` source, which
  replaces the `trimmer` placeholder among the PLC equipment sources. SFPDataAPI
  reads sources that an ETL builds as SQLite files. It finds their tables on its
  own and detects new rows by hashing their contents, together with each row's
  `rowid`.
- The sibling project **SFP_Tally_ETL** already delivers its SQLite databases
  to SFPDataAPI. It runs directly on the host, with one start script per
  platform:
  - **Linux:** `tallybronze.service` (systemd oneshot) runs `start.sh`. The
    script loads `.env` and runs the ETL. If `PUSH_PULL=push`, it then rsyncs
    the database to the bronze server (`/srv/data/bronze/`).
  - **Windows:** `start.bat` runs the ETL only, with no push and no
    scheduling.
  - Until now, SFP_Tally_ETL also pushed this project's database as
    `raptor.db`, which tied the two projects together.

Docker added a second deployment model that nothing else in the pipeline uses,
and the job is not yet doing real work. Patrick decided to drop Docker and
deliver the database the same way SFP_Tally_ETL does (2026-11-17). Windows
support is to be **at the same level as SFP_Tally_ETL**, no more
(2026-11-18).

## Decision

1. **No Docker.** Remove the `Dockerfile`, `.dockerignore` and the Docker and
   TrueNAS deployment documentation.

2. **Linux: same model as SFP_Tally_ETL.**
   - `start.sh` loads `.env`, then runs `.venv/bin/raptor-etl run`.
   - If `PUSH_PULL=push` and `run` exited with `0` or `1`, the script:
     1. makes a consistent snapshot with the SQLite backup API, the same way
        SFP_Tally_ETL snapshotted `raptor.db`;
     2. rsyncs the snapshot to `RAPTOR_PUSH_DEST`, always named
        `trimmer.db` on the remote side.

     A `1` means some files failed, but the files that did load are still
     delivered. Exit codes `2`, `3` and `4` push nothing.
   - The script exits with `run`'s exit code, or with rsync's if the push
     fails, so systemd records failed runs.
   - `push_db.sh` is the rsync step, modelled on `push_tally_db.sh`. The
     destination comes from `RAPTOR_PUSH_DEST` rather than being hard-coded,
     because ADR-001 keeps all settings in the environment.
   - `raptorbronze.service` (`Type=oneshot`, runs `start.sh` as the service
     user, modelled on `tallybronze.service`) and `raptorbronze.timer`
     (`OnCalendar=Mon..Fri 23:00 America/Los_Angeles`).
   - SMB is still read directly with smbprotocol, so no share mount and no
     `ensure_mount.sh` step are needed.

3. **Windows: same level as SFP_Tally_ETL.** `start.bat` changes to the
   project folder and runs `.venv\Scripts\raptor-etl.exe run`, passing
   through any arguments and the exit code. The program loads `.env` itself
   (ADR-001). No push and no scheduler are provided. A Windows run builds
   the local database only.

4. **SFP_Tally_ETL no longer handles Raptor data.** Its `RAPTOR_DB_PATH`
   snapshot-and-push block is removed.

5. **Remove `raptor-etl schedule` and `scheduler.py`.** The systemd timer
   replaces them, and SFP_Tally_ETL has no built-in scheduler either.
   *(Open: see Open questions.)*

### Configuration changes

| Variable | Read by | Required | Meaning |
|---|---|---|---|
| `PUSH_PULL` | `start.sh` | no | `push` turns on delivery after a run (same name and meaning as SFP_Tally_ETL) |
| `RAPTOR_PUSH_DEST` | `start.sh` | when `PUSH_PULL=push` | rsync destination folder, e.g. `biztech@10.64.10.122:/srv/data/bronze/` |

If `PUSH_PULL=push` is set without `RAPTOR_PUSH_DEST`, `start.sh` reports
an error before running anything.

`RAPTOR_RUN_TIME` and `RAPTOR_RUN_DAYS` are removed, because the schedule
now lives in the timer. `RAPTOR_TIMEZONE` stays: it still sets the copy date.

## Alternatives considered

- **Build delivery into `raptor-etl run` (Python) so that it works on
  Windows too.** That's more than SFP_Tally_ETL does. It would need an
  rsync or scp fallback for Windows and a new exit code. Rejected because
  Windows support only needs to match SFP_Tally_ETL.
- **Keep Docker and add a push step inside the container.** This keeps a
  deployment model that nothing else in the pipeline uses, and it needs SSH
  keys inside the container.
- **Keep SFP_Tally_ETL pushing this database.** This ties the two projects
  together: the Tally host would need this project's database on local disk.
- **Keep `schedule` as a long-running systemd service.** This works, but it
  runs a second scheduler alongside the timer pattern that SFP_Tally_ETL
  already uses.

## Consequences

### Benefits

- Both ETLs are deployed, scheduled and delivered the same way, on both
  platforms.
- Each project delivers its own database, right after building it.
- Less code, because the scheduler is removed.

### Costs and risks

- The host needs Python 3.12+ and a virtualenv. SFP_Tally_ETL uses only the
  standard library, so this project's host setup takes more work.
- The service user needs an SSH key that lets it rsync to the bronze server
  (the same access `biztech` already has for SFP_Tally_ETL).
- A Windows install does not deliver to SFPDataAPI, the same as
  SFP_Tally_ETL.
- As in ADR-001, missed runs are not caught up. The timer does not use
  `Persistent=true`, because a catch-up run the next morning could copy
  files in the middle of production.

## Open questions

1. Remove `raptor-etl schedule` (recommended) or keep it as an unused manual
   option?
  - Yes
2. Which host and install path? The proposal assumes `/srv/RaptorFilesETL`
   and the `biztech` user, the same as SFP_Tally_ETL.
  - Yes your assumtions are correct.

