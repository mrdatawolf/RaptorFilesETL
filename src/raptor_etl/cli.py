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


def collect_stage(config, database, clock) -> bool:
    """Collect reports; missing/failed outcomes contribute exit code 1."""
    from .collect import collect

    return all(item.outcome in ("archived", "unchanged")
               for item in collect(config, database, clock))


def load_stage(config, database, clock) -> bool:
    """Placeholder: return True when every load outcome succeeds."""
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="raptor-etl")
    parser.add_argument("command", choices=("run", "schedule"))
    args = parser.parse_args(argv)
    logger = configure_logging()
    if args.command == "schedule":
        logger.error("schedule is not implemented; scheduled execution arrives in TASK-006")
        return 2
    try:
        config = load_config()
        logger = configure_logging(config.log_level)
        with run_lock(config.db_path):
            with closing(open_database(config.db_path)) as database:
                clock = Clock(config.timezone)
                collected = collect_stage(config, database, clock)
                loaded = load_stage(config, database, clock)
                return 0 if collected and loaded else 1
    except ConfigError as error:
        for problem in error.problems:
            logger.error("%s", problem)
        return 2
    except RunLockedError:
        logger.error("Another run is in progress")
        return 3
    except (LayoutError, ArchiveIntegrityError, sqlite3.Error, OSError):
        # Raw exception messages may include credentials or configured paths.
        logger.error("A stage failed")
        return 1
