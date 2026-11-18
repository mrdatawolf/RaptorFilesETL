"""Environment configuration; diagnostics contain variable names, never values."""
from dataclasses import dataclass, field
from pathlib import Path
import os
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from .errors import ConfigError

@dataclass(frozen=True)
class Config:
    source_path: str
    archive_dir: Path
    db_path: Path
    timezone: ZoneInfo
    log_level: str
    smb_username: str | None = field(repr=False)
    smb_password: str | None = field(repr=False)
    smb_domain: str | None = field(repr=False)


def load_config(env_file: str | Path = ".env", *, read_only: bool = False) -> Config:
    load_dotenv(env_file, override=False, interpolate=False)
    problems = []

    def get(name, default=None):
        value = os.environ.get("RAPTOR_" + name, default)
        if value is not None and (not value.strip() or "\x00" in value):
            problems.append(f"RAPTOR_{name}: must be nonempty and contain no NUL")
            return None
        return value

    source = get("SOURCE_PATH")
    archive = get("ARCHIVE_DIR")
    database = get("DB_PATH")
    username, password, domain = (get(n) for n in ("SMB_USERNAME", "SMB_PASSWORD", "SMB_DOMAIN"))
    for name, value in (("SOURCE_PATH", source), ("ARCHIVE_DIR", archive), ("DB_PATH", database)):
        if value is None:
            problems.append(f"RAPTOR_{name}: required")
    if source and source.startswith(("//", "\\\\")):
        if len([p for p in source.replace("\\", "/").split("/") if p]) < 2:
            problems.append("RAPTOR_SOURCE_PATH: SMB path needs host and share")
        for name, value in (("SMB_USERNAME", username), ("SMB_PASSWORD", password)):
            if value is None:
                problems.append(f"RAPTOR_{name}: required for SMB")
    zone = get("TIMEZONE", "America/Los_Angeles")
    try:
        timezone = ZoneInfo(zone or "")
    except (ZoneInfoNotFoundError, ValueError):
        problems.append("RAPTOR_TIMEZONE: invalid IANA time zone")
        timezone = None
    level = get("LOG_LEVEL", "INFO")
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        problems.append("RAPTOR_LOG_LEVEL: expected DEBUG, INFO, WARNING or ERROR")
    if archive:
        try:
            if read_only:
                if not Path(archive).is_dir() or not os.access(archive, os.W_OK | os.X_OK):
                    raise OSError
            else:
                with tempfile.TemporaryFile(dir=archive):
                    pass
        except (OSError, ValueError):
            problems.append("RAPTOR_ARCHIVE_DIR: must exist and be writable")
    if database:
        try:
            if not Path(database).parent.is_dir() or Path(database).is_dir():
                problems.append("RAPTOR_DB_PATH: parent must exist and path must name a file")
        except (OSError, ValueError):
            problems.append("RAPTOR_DB_PATH: invalid database path")
    if problems:
        raise ConfigError(problems)
    return Config(source, Path(archive), Path(database), timezone, level,
                  username, password, domain)
