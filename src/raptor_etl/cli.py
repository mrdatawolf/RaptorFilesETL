"""Command entry points; stage implementations arrive in subsequent tasks."""
import argparse
from contextlib import closing
import sqlite3

from .clock import Clock
from .config import load_config
from .database import open_database
from .errors import ArchiveIntegrityError, ConfigError, LayoutError, RunLockedError
from .lock import run_lock
from .logging import configure_logging
from .precheck import precheck
from .source import SourceError, scrub_password


def collect_stage(config, database, clock) -> bool:
    """Collect reports; missing/failed outcomes contribute exit code 1."""
    from .collect import collect

    return all(item.outcome in ("archived", "unchanged")
               for item in collect(config, database, clock))


def load_stage(config, database, clock) -> bool:
    """Load pending archived reports; failures contribute exit code 1."""
    from .load import load_stage as load_reports

    return load_reports(config, database, clock)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="raptor-etl")
    parser.add_argument("command", choices=("run", "schedule", "check"))
    args = parser.parse_args(argv)
    logger = configure_logging()
    try:
        config = load_config(read_only=True) if args.command == "check" else load_config()
        if args.command == "check":
            from .check import check
            return check(config, logger)
        logger = configure_logging(config.log_level)
        if args.command == "schedule":
            from .scheduler import schedule
            from .check import check
            return schedule(config, logger, run_pass=lambda: main(["run"]),
                            startup_check=lambda: check(config, logger))
        with run_lock(config.db_path):
            precheck(config)
            with closing(open_database(config.db_path)) as database:
                clock = Clock(config.timezone)
                collected = collect_stage(config, database, clock)
                loaded = load_stage(config, database, clock)
                return 0 if collected and loaded else 1
    except SourceError as error:
        logger.error("%s", scrub_password(
            f"FAIL source: {error.reason}; run stopped (exit 4)", config.smb_password))
        return 4
    except ConfigError as error:
        for problem in error.problems:
            logger.error("%s%s", "FAIL configuration: " if args.command == "check" else "", problem)
        return 2
    except RunLockedError:
        logger.error("Another run is in progress")
        return 3
    except (LayoutError, ArchiveIntegrityError, sqlite3.Error, OSError):
        # Raw exception messages may include credentials or configured paths.
        logger.error("A stage failed")
        return 1
