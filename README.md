# RaptorFilesETL

The Raptor sorter/trimmer at Sequoia Forest Products writes its daily
production reports to an SMB share and overwrites them every day. This job
saves a dated copy of each day's reports and loads their data into a SQLite
"bronze" database. SFPDataAPI then reads that database as its `trimmer`
source.

Each weeknight at 23:00 (plant time), the job:

1. **Checks** that the source share can be reached and logged into.
2. **Collects** the three `.xls` reports (Downtime Summary, Production
   Summary, Production ToDate) into the archive as
   `YYYY-MM-DD_<original name>`. Files that haven't changed since the last
   run are skipped. The share itself is never modified.
3. **Loads** each newly archived report into the bronze database. A file
   with the same hash is never loaded twice.
4. **Pushes** (Linux only, when enabled) a consistent snapshot of the
   database to the bronze server as `trimmer.db`.

More detail:

- [docs/PROJECT.md](docs/PROJECT.md): purpose, scope and domain terms
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): stack, configuration, exit codes
  and testing
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
  [docs/contracts/](docs/contracts/) and [docs/decisions/](docs/decisions/):
  design, stage contracts and ADRs

## Repository layout

```text
src/raptor_etl/         the Python package (`raptor-etl` command)
tests/                  pytest suite
start.sh                Linux launcher: runs the ETL, then pushes if enabled
push_db.sh              rsync step used by start.sh
start.bat               Windows launcher: runs the ETL only, no push
raptorbronze.service    systemd oneshot unit that runs start.sh
raptorbronze.timer      systemd timer: Mon–Fri 23:00 America/Los_Angeles
.env.example            configuration template (copy to .env)
docs/, tasks/           project documentation and task lifecycle
```

## Installation (Linux host)

The production install lives in `/srv/RaptorFilesETL` and runs as the
`biztech` user (ADR-003). It needs Python 3.12+ and rsync.

```bash
sudo mkdir -p /srv/RaptorFilesETL
sudo chown biztech:biztech /srv/RaptorFilesETL
sudo -iu biztech
git clone <repo-url> /srv/RaptorFilesETL
cd /srv/RaptorFilesETL
python3 -m venv .venv
.venv/bin/pip install .
cp .env.example .env
chmod 600 .env
```

Edit `.env` and fill in every value. The available settings are listed in
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#configuration). For delivery to
SFPDataAPI, also set:

```bash
PUSH_PULL=push
RAPTOR_PUSH_DEST=biztech@<bronze-server>:/srv/data/bronze/
```

The archive folder and the database's parent folder must already exist and
`biztech` must be able to write to them. For a remote push destination,
`biztech` needs passwordless SSH access to the bronze server. Test it once
by hand with `ssh biztech@<bronze-server>` so the host key is accepted.

> **Note:** `raptor-etl` reads `.env` from the **current directory**. Run
> every command below from `/srv/RaptorFilesETL` as `biztech`.

## Manual operation

Start a shell as the service user in the install folder:

```bash
sudo -iu biztech
cd /srv/RaptorFilesETL
```

### 1. Test run (no changes made)

```bash
.venv/bin/raptor-etl check
```

This checks the configuration, connects to the share, fully reads each of
the three expected `.xls` files, and inspects the archive and database. It
writes nothing and takes no lock, so it is safe to run at any time. Each line
reports `OK` or `FAIL` with a reason.

| Exit | Meaning |
|---|---|
| `0` | All checks passed |
| `1` | A report file is missing or unreadable |
| `2` | Invalid configuration, or an unusable/unknown database |
| `4` | Source connection, login or directory listing failed |

A missing database is reported as "will be created on first run". That is
expected on a new install.

### 2. Manual database update (no push)

```bash
.venv/bin/raptor-etl run
echo "exit: $?"
```

This collects the reports from the share into the archive and loads them
into the database at `RAPTOR_DB_PATH`. It does **not** push, whatever
`PUSH_PULL` is set to. It is safe to run again: unchanged files are skipped,
and a file that has already been loaded is never loaded twice.

| Exit | Meaning |
|---|---|
| `0` | Success |
| `1` | At least one file was missing or failed; the others were still loaded |
| `2` | Invalid configuration, or the archive or database is unusable |
| `3` | Another run is in progress (for example, the timer is running) |
| `4` | Source unreachable or login failed; nothing was done |

### 3. Push the database

Don't rsync the live database file directly: a copy taken while it's being
written can be inconsistent. Take a snapshot with the SQLite backup API
first, then push the snapshot. This is what `start.sh` does.

```bash
set -a; source .env; set +a
snap="$(mktemp -d)"
.venv/bin/python - "$RAPTOR_DB_PATH" "$snap/trimmer.db" <<'PY'
import sqlite3, sys
from contextlib import closing
from pathlib import Path
src = Path(sys.argv[1]).resolve().as_uri() + "?mode=ro"
with closing(sqlite3.connect(src, uri=True)) as db, closing(sqlite3.connect(sys.argv[2])) as out:
    db.backup(out)
PY
./push_db.sh "$snap/trimmer.db"
rm -rf -- "$snap"
```

The file always arrives as `trimmer.db` in the `RAPTOR_PUSH_DEST` folder.

### Steps 2 and 3 together

To run exactly what the timer runs (update, then push if
`PUSH_PULL=push`), use:

```bash
./start.sh
echo "exit: $?"
```

`start.sh` pushes only if the run exits with `0` or `1`. It exits with the
run's exit code, or with rsync's exit code if the push fails.

### Running it as the service

To trigger the installed service once, outside its schedule, and watch its
output:

```bash
sudo systemctl start raptorbronze.service
journalctl -u raptorbronze.service -n 100 --no-pager
```

## Installing the systemd service and timer

`raptorbronze.service` is a oneshot unit that runs
`/srv/RaptorFilesETL/start.sh` as `biztech`. `raptorbronze.timer` starts it
Monday to Friday at 23:00 America/Los_Angeles. Missed runs are **not** caught
up (there is no `Persistent=true`), so a catch-up run never copies files in
the middle of production.

1. **Check the paths.** If the install is not at `/srv/RaptorFilesETL` or
   the user is not `biztech`, edit `User=`, `Group=`, `WorkingDirectory=`
   and `ExecStart=` in `raptorbronze.service` first.

2. **Make sure the scripts are executable** (git normally preserves this):

   ```bash
   chmod +x /srv/RaptorFilesETL/start.sh /srv/RaptorFilesETL/push_db.sh
   ```

3. **Copy the unit files into systemd's directory.** Copy them rather than
   symlinking, so the units don't change when the checkout does:

   ```bash
   sudo cp /srv/RaptorFilesETL/raptorbronze.service /etc/systemd/system/
   sudo cp /srv/RaptorFilesETL/raptorbronze.timer   /etc/systemd/system/
   sudo chown root:root /etc/systemd/system/raptorbronze.{service,timer}
   sudo chmod 644       /etc/systemd/system/raptorbronze.{service,timer}
   ```

4. **Tell systemd to reread its unit files:**

   ```bash
   sudo systemctl daemon-reload
   ```

5. **Optional: check the units for errors:**

   ```bash
   systemd-analyze verify /etc/systemd/system/raptorbronze.{service,timer}
   systemd-analyze calendar "Mon..Fri 23:00 America/Los_Angeles"
   ```

6. **Test the service once by hand** before enabling the schedule:

   ```bash
   sudo systemctl start raptorbronze.service
   systemctl status raptorbronze.service
   journalctl -u raptorbronze.service -n 100 --no-pager
   ```

   A oneshot service shows `inactive (dead)` once it finishes. That is
   normal. Check the log and `status=` for the exit code.

7. **Enable and start the timer.** Enable the **timer**, not the service.
   The service has no `[Install]` section and is started only by the timer:

   ```bash
   sudo systemctl enable --now raptorbronze.timer
   ```

8. **Confirm the timer is scheduled:**

   ```bash
   systemctl list-timers raptorbronze.timer
   ```

   The `NEXT` column should show the next weekday at 23:00 Pacific.

### Updating the units later

After you edit either unit file in the repo, copy it to
`/etc/systemd/system/` again and reload:

```bash
sudo cp /srv/RaptorFilesETL/raptorbronze.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart raptorbronze.timer
```

### Pausing or removing

```bash
sudo systemctl disable --now raptorbronze.timer        # stop scheduling
sudo rm /etc/systemd/system/raptorbronze.{service,timer}
sudo systemctl daemon-reload                            # after removal
```

## Updating the code

```bash
sudo -iu biztech
cd /srv/RaptorFilesETL
git pull
.venv/bin/pip install .
```

If the unit files changed, reinstall them as described above.

## Windows

Windows support matches SFP_Tally_ETL: it builds the local database only,
with no push and no scheduler.

```bat
python -m venv .venv
.venv\Scripts\pip install .
copy .env.example .env
rem edit .env, then:
.venv\Scripts\raptor-etl.exe check
start.bat
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Tests run offline. Tests that need a real report from the gitignored
`Samples/` folder skip when it is missing. See
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for conventions.

## Last-resort PDF backfill

For days whose `.xls` files are gone, `raptor-etl import-pdf <folder>` loads
Production Summary and Production ToDate from their PDF exports. This is
always run by hand. See
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#pdf-backfill-last-resort) and
CONTRACT-004 before using it.
