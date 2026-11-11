"""Nonblocking OS lock; the persistent lock file is never unlinked."""
from contextlib import contextmanager
import os
from pathlib import Path

from .errors import ConfigError, RunLockedError


@contextmanager
def run_lock(database: Path):
    try:
        handle = open(str(database) + ".lock", "a+b")
    except OSError:
        raise ConfigError("RAPTOR_DB_PATH: cannot open run lock") from None
    acquired = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            raise RunLockedError("Another run is in progress") from None
        yield
    finally:
        try:
            if acquired:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
