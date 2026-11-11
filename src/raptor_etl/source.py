"""Read-only local and SMB sources; remote diagnostics never expose credentials."""
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, BinaryIO, ContextManager

import smbclient

from .config import Config


class SourceError(Exception):
    """Sanitized source access failure."""


class Source(Protocol):
    def names(self) -> set[str]: ...
    def open(self, name: str) -> ContextManager[BinaryIO]: ...


class LocalSource:
    def __init__(self, root: str):
        self.root = Path(root)

    def names(self) -> set[str]:
        return {entry.name for entry in self.root.iterdir()}

    def open(self, name: str):
        return (self.root / name).open('rb')


class SMBSource:
    def __init__(self, config: Config):
        self.root = config.source_path.replace('/', '\\').rstrip('\\')
        self.host = self.root.lstrip('\\').split('\\')[0]
        self.username = config.smb_username
        if config.smb_domain:
            self.username = f'{config.smb_domain}\\{self.username}'
        self.password = config.smb_password

    def names(self) -> set[str]:
        try:
            smbclient.register_session(self.host, username=self.username, password=self.password)
            return set(smbclient.listdir(self.root))
        except Exception:
            raise SourceError('SMB connection or directory read failed') from None

    @contextmanager
    def open(self, name: str):
        try:
            with smbclient.open_file(self.root + '\\' + name, mode='rb') as handle:
                yield handle
        except Exception:
            raise SourceError('SMB file read failed') from None


def make_source(config: Config) -> Source:
    return SMBSource(config) if config.source_path.startswith(('//', '\\\\')) else LocalSource(config.source_path)
