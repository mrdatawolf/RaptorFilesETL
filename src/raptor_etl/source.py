"""Read-only local and SMB sources; remote diagnostics never expose credentials."""
from contextlib import contextmanager
import errno
from pathlib import Path
import socket
from typing import Protocol, BinaryIO, ContextManager

import smbclient
from smbprotocol import exceptions as smb_errors

from .config import Config


class SourceError(Exception):
    """Source access failure carrying a sanitized, operator-facing reason."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def scrub_password(text: str, password: str | None) -> str:
    return text.replace(password, '[REDACTED]') if password else text


def _reason(error, local, operation):
    """Recognize one exception without formatting server-supplied text."""
    status = error.ntstatus if isinstance(error, smb_errors.SMBOSError) else None

    def smb_type(*types):
        return isinstance(error, types) or status in tuple(
            cls._STATUS_CODE for cls in types if hasattr(cls, '_STATUS_CODE'))

    if isinstance(error, SourceError):
        reason = error.reason
    elif isinstance(error, socket.gaierror):
        reason = 'host not found'
    elif smb_type(smb_errors.SMBAuthenticationError, smb_errors.LogonFailure,
                  smb_errors.WrongPassword, smb_errors.PasswordExpired):
        reason = 'login failed'
    elif smb_type(smb_errors.AccessDenied, smb_errors.PrivilegeNotHeld):
        reason = 'access denied'
    elif smb_type(smb_errors.BadNetworkName, smb_errors.ObjectNameNotFound,
                  smb_errors.ObjectPathNotFound, smb_errors.NoSuchFile, smb_errors.NotFound):
        reason = 'share or path not found'
    elif isinstance(error, PermissionError):
        reason = 'permission denied' if local else 'access denied'
    elif isinstance(error, FileNotFoundError):
        reason = ('folder missing' if operation == 'list' else 'file missing') if local else 'share or path not found'
    elif isinstance(error, NotADirectoryError) or smb_type(smb_errors.StatusNotADirectory):
        reason = 'not a directory'
    elif (isinstance(error, (TimeoutError, ConnectionError))
          or smb_type(smb_errors.SMBConnectionClosed, smb_errors.IOTimeout, smb_errors.ServerUnavailable)
          or (isinstance(error, OSError) and (operation == 'connect' or error.errno in (
              errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ECONNREFUSED,
              errno.ECONNRESET, errno.ECONNABORTED, errno.ETIMEDOUT, errno.ENETDOWN)))):
        reason = 'host unreachable / connection refused / timed out'
    else:
        return None
    return reason


def source_error(error: Exception, password: str | None = None, *,
                 local: bool = False, operation: str = 'read',
                 path: str | None = None, username: str | None = None) -> SourceError:
    """Walk both exception links, preferring specific failures to generic network ones.

    Both links are inspected even when context display is suppressed. Identity
    tracking handles cycles; raw exception messages are never formatted.
    """
    if isinstance(error, SourceError):
        return SourceError(scrub_password(error.reason, password))
    pending, seen, candidates = [error], set(), []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        reason = _reason(current, local, operation)
        if reason is not None:
            # DNS and authentication/path/permission errors are more specific
            # than a generic OSError introduced by a transport wrapper.
            priority = 0 if reason == 'host not found' else (
                2 if reason == 'host unreachable / connection refused / timed out' else 1)
            candidates.append((priority, len(candidates), reason))
        for linked in (current.__context__, current.__cause__):
            if linked is not None:
                pending.append(linked)
    reason = min(candidates)[2] if candidates else f'unexpected error: {type(error).__name__}'
    if path:
        path = scrub_password(path, password)
        if not local:
            path = path.replace('\\', '/')
        if reason == 'host not found':
            host = path.lstrip('/').split('/')[0]
            reason = f'{reason}: {host} ({path})'
        elif reason == 'login failed':
            reason = f"{reason} for user '{username}' on {path}"
        else:
            reason = f'{reason}: {path}'
            if username and not local:
                reason += f" (user '{username}')"
    return SourceError(scrub_password(reason, password))


class Source(Protocol):
    def names(self) -> set[str]: ...
    def open(self, name: str) -> ContextManager[BinaryIO]: ...


class LocalSource:
    def __init__(self, root: str, password: str | None = None):
        self.root = Path(root)
        self.password = password

    def names(self) -> set[str]:
        try:
            return {entry.name for entry in self.root.iterdir()}
        except Exception as error:
            raise source_error(error, self.password, local=True, operation='list', path=str(self.root)) from None

    @contextmanager
    def open(self, name: str):
        try:
            with (self.root / name).open('rb') as handle:
                yield handle
        except Exception as error:
            raise source_error(error, self.password, local=True, path=str(self.root / name)) from None


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
        except Exception as error:
            raise source_error(error, self.password, operation='connect', path=self.root, username=self.username) from None
        try:
            return set(smbclient.listdir(self.root))
        except Exception as error:
            raise source_error(error, self.password, operation='list', path=self.root, username=self.username) from None

    @contextmanager
    def open(self, name: str):
        try:
            with smbclient.open_file(self.root + '\\' + name, mode='rb') as handle:
                yield handle
        except Exception as error:
            raise source_error(error, self.password, path=self.root + '\\' + name,
                               username=self.username) from None


def make_source(config: Config) -> Source:
    return SMBSource(config) if config.source_path.startswith(('//', '\\\\')) else LocalSource(config.source_path, config.smb_password)
