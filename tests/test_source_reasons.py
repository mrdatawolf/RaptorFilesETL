"""Sanitized reasons survive source wrappers and every operator-facing path."""
from datetime import datetime, timezone
import errno
import io
from pathlib import Path
import socket
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from smbprotocol import exceptions as smb_errors

from raptor_etl import cli, source
from raptor_etl.clock import Clock
from raptor_etl.collect import EXPECTED_FILES, collect
from raptor_etl.config import load_config
from raptor_etl.database import open_database
from raptor_etl.precheck import precheck

PASSWORD = 'PASSWORD-CANARY-REVISION-1'
NETWORK = 'host unreachable / connection refused / timed out'
# Response exceptions need a header only when formatted. Production must never
# format these exceptions: their server-supplied details can contain secrets.
SMB_CASES = [
    (smb_errors.SMBAuthenticationError('bad credentials ' + PASSWORD), 'login failed'),
    (smb_errors.LogonFailure(None), 'login failed'),
    (smb_errors.WrongPassword(None), 'login failed'),
    (smb_errors.PasswordExpired(None), 'login failed'),
    (smb_errors.AccessDenied(None), 'access denied'),
    (smb_errors.PrivilegeNotHeld(None), 'access denied'),
    (smb_errors.BadNetworkName(None), 'share or path not found'),
    (smb_errors.ObjectPathNotFound(None), 'share or path not found'),
    (smb_errors.ObjectNameNotFound(None), 'share or path not found'),
    (smb_errors.NoSuchFile(None), 'share or path not found'),
    (smb_errors.NotFound(None), 'share or path not found'),
    (smb_errors.SMBConnectionClosed(PASSWORD), NETWORK),
    (smb_errors.IOTimeout(None), NETWORK),
    (smb_errors.ServerUnavailable(None), NETWORK),
    (smb_errors.StatusNotADirectory(None), 'not a directory'),
]
for cls, reason in list(SMB_CASES):
    if isinstance(cls, smb_errors.SMBResponseException):
        SMB_CASES.append((smb_errors.SMBOSError(type(cls)._STATUS_CODE, PASSWORD), reason))
NETWORK_CASES = [
    (socket.gaierror(socket.EAI_NONAME, PASSWORD), 'host not found'),
    (ConnectionError(PASSWORD), NETWORK),
    (ConnectionRefusedError(PASSWORD), NETWORK),
    (TimeoutError(PASSWORD), NETWORK),
    (OSError(errno.EHOSTUNREACH, PASSWORD), NETWORK),
    (OSError(errno.ENETUNREACH, PASSWORD), NETWORK),
    (OSError(PASSWORD), NETWORK),  # unqualified OSError while connecting
    (RuntimeError('message contains ' + PASSWORD + ' inside it'), 'unexpected error: RuntimeError'),
]


@pytest.fixture
def remote(configured, monkeypatch):
    monkeypatch.setenv('RAPTOR_SOURCE_PATH', '//server/share')
    monkeypatch.setenv('RAPTOR_SMB_USERNAME', 'user')
    monkeypatch.setenv('RAPTOR_SMB_PASSWORD', PASSWORD)
    client = Mock()
    client.listdir.return_value = list(EXPECTED_FILES)
    client.open_file.side_effect = lambda *args, **kwargs: io.BytesIO(b'report')
    monkeypatch.setattr(source, 'smbclient', client)
    return load_config(), client


@pytest.mark.parametrize('error,reason', SMB_CASES + NETWORK_CASES,
                         ids=[f'{type(e).__name__}-{i}' for i, (e, _) in enumerate(SMB_CASES + NETWORK_CASES)])
@pytest.mark.parametrize('command', ['run', 'check'])
def test_remote_precheck_reasons(remote, monkeypatch, capsys, error, reason, command):
    config, client = remote
    client.register_session.side_effect = error
    load = Mock(return_value=True)
    monkeypatch.setattr(cli, 'load_stage', load)
    assert cli.main([command]) == 4
    output = capsys.readouterr().out
    assert f'FAIL source: {reason}' in output
    if command == 'run':
        assert 'run stopped (exit 4)' in output
    assert PASSWORD not in output
    load.assert_not_called()
    assert not config.db_path.exists()
    assert not list(config.archive_dir.glob('*_*.xls'))


@pytest.mark.parametrize('error,reason', [
    (FileNotFoundError(PASSWORD), 'folder missing'),
    (NotADirectoryError(PASSWORD), 'not a directory'),
    (PermissionError(PASSWORD), 'permission denied'),
    (RuntimeError(PASSWORD), 'unexpected error: RuntimeError'),
])
@pytest.mark.parametrize('command', ['run', 'check'])
def test_local_precheck_reasons(configured, monkeypatch, capsys, error, reason, command):
    monkeypatch.setenv('RAPTOR_SMB_PASSWORD', PASSWORD)
    original = Path.iterdir
    def entries(path):
        if path == configured / 'source':
            raise error
        return original(path)
    monkeypatch.setattr(Path, 'iterdir', entries)
    assert cli.main([command]) == 4
    output = capsys.readouterr().out
    assert f'FAIL source: {reason}' in output
    assert PASSWORD not in output
    assert not (configured / 'bronze.db').exists()


@pytest.mark.parametrize('error,reason', [
    (smb_errors.AccessDenied(None), 'access denied'),
    (smb_errors.SMBOSError(smb_errors.BadNetworkName._STATUS_CODE, PASSWORD), 'share or path not found'),
    (TimeoutError(PASSWORD), NETWORK),
    (RuntimeError('before ' + PASSWORD + ' after'), 'unexpected error: RuntimeError'),
])
def test_listing_reason_is_not_collapsed(remote, error, reason):
    config, client = remote
    client.listdir.side_effect = error
    with pytest.raises(source.SourceError) as caught:
        precheck(config)
    assert caught.value.reason == str(caught.value)
    assert caught.value.reason.startswith(reason)
    assert '//server/share' in caught.value.reason
    assert "user 'user'" in caught.value.reason


@pytest.mark.parametrize('error,reason', [
    (smb_errors.AccessDenied(None), 'access denied'),
    (smb_errors.SMBOSError(smb_errors.ObjectPathNotFound._STATUS_CODE, PASSWORD), 'share or path not found'),
    (ConnectionResetError(PASSWORD), NETWORK),
    (RuntimeError('before ' + PASSWORD + ' after'), 'unexpected error: RuntimeError'),
])
@pytest.mark.parametrize('during_read', [False, True])
def test_per_file_remote_reason_check_and_collect(remote, capsys, error, reason, during_read):
    config, client = remote
    class BrokenRead(io.BytesIO):
        def read(self, size=-1):
            raise error
    def opened(path, **kwargs):
        if path.endswith(EXPECTED_FILES[0]):
            if during_read:
                return BrokenRead()
            raise error
        return io.BytesIO(b'report')
    client.open_file.side_effect = opened
    assert cli.main(['check']) == 1
    output = capsys.readouterr().out
    assert f'FAIL {EXPECTED_FILES[0]}: present but full read failed: {reason}' in output
    assert PASSWORD not in output
    clock = Clock(ZoneInfo('America/Los_Angeles'), lambda: datetime(2026, 11, 11, tzinfo=timezone.utc))
    with open_database(config.db_path) as db:
        outcomes = collect(config, db, clock)
    assert outcomes[0].outcome == 'failed'
    assert outcomes[0].reason.startswith(reason)
    assert str(config.source_path).replace("\\", "/") in outcomes[0].reason
    assert all(outcome.outcome == 'archived' for outcome in outcomes[1:])
    assert reason in capsys.readouterr().out
    assert not list(config.archive_dir.glob('.*.partial'))


@pytest.mark.parametrize('error,reason', [
    (FileNotFoundError(PASSWORD), 'file missing'),
    (NotADirectoryError(PASSWORD), 'not a directory'),
    (PermissionError(PASSWORD), 'permission denied'),
    (RuntimeError(PASSWORD), 'unexpected error: RuntimeError'),
])
def test_per_file_local_reason_check_and_collect(configured, monkeypatch, capsys, error, reason):
    root = configured / 'source'
    root.mkdir()
    for name in EXPECTED_FILES:
        (root / name).write_bytes(b'report')
    monkeypatch.setenv('RAPTOR_SMB_PASSWORD', PASSWORD)
    original = Path.open
    def opened(path, *args, **kwargs):
        if path == root / EXPECTED_FILES[0]:
            raise error
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', opened)
    assert cli.main(['check']) == 1
    output = capsys.readouterr().out
    assert f'full read failed: {reason}' in output
    assert PASSWORD not in output
    config = load_config()
    clock = Clock(config.timezone, lambda: datetime(2026, 11, 11, tzinfo=timezone.utc))
    with open_database(config.db_path) as db:
        outcomes = collect(config, db, clock)
    assert outcomes[0].reason.startswith(reason)
    assert str(config.source_path).replace("\\", "/") in outcomes[0].reason
    assert all(outcome.outcome == 'archived' for outcome in outcomes[1:])
    assert PASSWORD not in capsys.readouterr().out


def test_defensive_scrub_of_existing_source_error(remote, monkeypatch, capsys):
    config, _ = remote
    monkeypatch.setattr(source.SMBSource, 'names', Mock(side_effect=source.SourceError(
        'unexpected error: before ' + PASSWORD + ' after')))
    with pytest.raises(source.SourceError) as caught:
        precheck(config)
    assert caught.value.reason == 'unexpected error: before [REDACTED] after'
    for command in ('run', 'check'):
        assert cli.main([command]) == 4
        output = capsys.readouterr().out
        assert 'unexpected error: before [REDACTED] after' in output
        assert PASSWORD not in output


def test_scrub_reason_at_per_file_output_boundary(remote, monkeypatch, capsys):
    config, client = remote
    # Even a SourceError supplied by an alternate source is scrubbed again.
    client.open_file.side_effect = source.SourceError('read denied ' + PASSWORD)
    assert cli.main(['check']) == 1
    output = capsys.readouterr().out
    assert 'read denied [REDACTED]' in output
    assert PASSWORD not in output
    clock = Clock(config.timezone, lambda: datetime(2026, 11, 11, tzinfo=timezone.utc))
    with open_database(config.db_path) as db:
        outcomes = collect(config, db, clock)
    assert all(item.reason == 'read denied [REDACTED]' for item in outcomes)
    assert PASSWORD not in capsys.readouterr().out


def wrapped_value_error(inner):
    try:
        raise inner
    except Exception as error:
        try:
            raise ValueError("Failed to connect to 'server:445': " + PASSWORD) from error
        except ValueError as wrapper:
            return wrapper


@pytest.mark.parametrize('inner,reason', [
    (socket.gaierror(socket.EAI_NONAME, PASSWORD), 'host not found'),
    (ConnectionRefusedError(errno.ECONNREFUSED, PASSWORD), NETWORK),
    (TimeoutError(PASSWORD), NETWORK),
    (OSError(errno.EHOSTUNREACH, PASSWORD), NETWORK),
    (OSError(errno.ENETUNREACH, PASSWORD), NETWORK),
])
@pytest.mark.parametrize('command', ['run', 'check'])
def test_real_transport_wrapping(remote, monkeypatch, capsys, inner, reason, command):
    config, client = remote
    client.register_session.side_effect = wrapped_value_error(inner)
    load = Mock()
    monkeypatch.setattr(cli, 'load_stage', load)
    assert cli.main([command]) == 4
    output = capsys.readouterr().out
    assert f'FAIL source: {reason}' in output
    assert '//server/share' in output
    assert PASSWORD not in output
    load.assert_not_called()
    assert not config.db_path.exists()


def test_exception_context_both_branches_and_cycle():
    outer = OSError('transport ' + PASSWORD)
    wrapper = wrapped_value_error(socket.gaierror(socket.EAI_NONAME, PASSWORD))
    outer.__cause__ = RuntimeError(PASSWORD)
    outer.__context__ = wrapper
    wrapper.__cause__.__context__ = outer
    assert source.source_error(outer, PASSWORD, operation='connect').reason == 'host not found'
    unknown = ValueError(PASSWORD)
    unknown.__cause__ = unknown
    assert source.source_error(unknown, PASSWORD).reason == 'unexpected error: ValueError'


def test_real_authentication_wrapping(remote):
    import spnego.exceptions
    config, client = remote
    # session.py wraps spnego failures with SMBAuthenticationError, from err.
    try:
        raise spnego.exceptions.InvalidCredentialError(context_msg=PASSWORD)
    except spnego.exceptions.SpnegoError as inner:
        try:
            raise smb_errors.SMBAuthenticationError('Failed to authenticate with server: ' + PASSWORD) from inner
        except smb_errors.SMBAuthenticationError as outer:
            client.register_session.side_effect = outer
    with pytest.raises(source.SourceError) as caught:
        precheck(config)
    assert caught.value.reason == "login failed for user 'user' on //server/share"
    assert PASSWORD not in str(caught.value)


@pytest.mark.parametrize('command', ['run', 'check'])
@pytest.mark.parametrize('status,reason,stage', [
    (smb_errors.LogonFailure._STATUS_CODE, 'login failed', 'login'),
    (smb_errors.BadNetworkName._STATUS_CODE, 'share or path not found', 'list'),
])
def test_real_server_status_wrapping(remote, capsys, command, status, reason, stage):
    from smbprotocol.header import SMB2HeaderResponse
    config, client = remote
    # Connection.receive constructs the registered subclass from the SMB header.
    header = SMB2HeaderResponse()
    header['status'] = status
    response_error = smb_errors.SMBResponseException(header)
    if stage == 'list':
        # SMBRawIO.__init__: get_smb_tree's BadNetworkName becomes SMBOSError
        # with the original response exception as its explicit cause.
        try:
            raise response_error
        except smb_errors.SMBResponseException as inner:
            try:
                raise smb_errors.SMBOSError(inner.status, '//server/share') from inner
            except smb_errors.SMBOSError as outer:
                client.listdir.side_effect = outer
    else:
        # Session.connect only catches MoreProcessingRequired here, so a
        # server's LogonFailure propagates unchanged through register_session.
        client.register_session.side_effect = response_error
    assert cli.main([command]) == 4
    output = capsys.readouterr().out
    assert reason in output
    assert '//server/share' in output
    assert "user 'user'" in output
    assert PASSWORD not in output


@pytest.mark.parametrize('secret', ['secret-with-slashes', r'secret\with\slashes'])
def test_context_scrubs_password_in_path_and_username(remote, secret):
    config, client = remote
    from dataclasses import replace
    config = replace(config, source_path=f'//{secret}/share/{secret}',
                     smb_username=f'user-{secret}', smb_password=secret)
    client.register_session.side_effect = smb_errors.SMBAuthenticationError(secret)
    with pytest.raises(source.SourceError) as caught:
        precheck(config)
    assert secret not in caught.value.reason
    assert "user 'user-[REDACTED]'" in caught.value.reason
    assert '//[REDACTED]/share/[REDACTED]' in caught.value.reason


def test_check_ok_info_fail_error_visible_default(remote, capsys):
    config, client = remote
    assert cli.main(['check']) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 12
    assert all(line.startswith('INFO OK ') for line in lines)
    client.listdir.return_value = []
    assert cli.main(['check']) == 1
    lines = capsys.readouterr().out.splitlines()
    assert sum(line.startswith('ERROR FAIL ') for line in lines) == 8
    assert not any(line.startswith('WARNING') for line in lines)
