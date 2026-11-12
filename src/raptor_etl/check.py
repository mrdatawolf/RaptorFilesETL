"""Read-only operational checks; never initialize or migrate a database."""
from contextlib import closing
import hashlib
import logging
import sqlite3

from .collect import CHUNK_SIZE, EXPECTED_FILES
from .database import CURRENT_VERSION
from .precheck import precheck
from .source import SourceError, scrub_password, source_error


def check(config, logger) -> int:
    def report(level, message, *args):
        logger.log(level, scrub_password(message % args, config.smb_password))

    report(logging.INFO, 'OK configuration: valid')
    report(logging.INFO, 'OK archive: exists and is writable')
    try:
        source, names = precheck(config)
    except SourceError as error:
        report(logging.ERROR, 'FAIL source: %s', error.reason)
        return 4
    report(logging.INFO, 'OK source: reachable and login OK')
    failed = False
    for name in EXPECTED_FILES:
        if name not in names:
            report(logging.ERROR, 'FAIL %s: absent', name)
            failed = True
            continue
        try:
            digest = hashlib.sha256()
            size = 0
            with source.open(name) as handle:
                for chunk in iter(lambda: handle.read(CHUNK_SIZE), b''):
                    size += len(chunk)
                    digest.update(chunk)
            report(logging.INFO, 'OK %s: present size=%d sha256=%s', name, size, digest.hexdigest())
        except Exception as error:
            reason = source_error(error, config.smb_password,
                                  local=not config.source_path.startswith(('//', '\\\\')),
                                  path=config.source_path, username=config.smb_username)
            report(logging.ERROR, 'FAIL %s: present but full read failed: %s', name, reason.reason)
            failed = True
    try:
        if not config.db_path.exists():
            report(logging.INFO, 'OK database: will be created on first run')
        else:
            uri = config.db_path.resolve().as_uri() + '?mode=ro'
            with closing(sqlite3.connect(uri, uri=True)) as database:
                version = database.execute('PRAGMA user_version').fetchone()[0]
                if not 0 <= version <= CURRENT_VERSION:
                    report(logging.ERROR, 'FAIL database: schema version %d is unknown', version)
                    return 2
            report(logging.INFO, 'OK database: schema version %d is known', version)
    except (sqlite3.Error, OSError, ValueError):
        report(logging.ERROR, 'FAIL database: cannot open read-only or read schema version')
        return 2
    return 1 if failed else 0
