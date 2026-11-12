"""TASK-007 read-only checks and source preconditions, offline."""
import hashlib
import io
from pathlib import Path
import shutil
import sqlite3
from unittest.mock import Mock

import pytest

from raptor_etl import cli, source
from raptor_etl.collect import EXPECTED_FILES
from raptor_etl.database import CURRENT_VERSION, open_database


def snapshot(root):
    return {p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def local(configured):
    samples = Path(__file__).resolve().parents[1] / 'Samples'
    if not samples.is_dir():
        pytest.skip('Samples/ is absent; check requires a local copy')
    shutil.copytree(samples, configured / 'source')
    return configured


@pytest.mark.parametrize('database', ['missing', 'current', 'old', 'newer', 'invalid'])
def test_check_local_read_only(local, monkeypatch, capsys, database):
    path = local / 'bronze.db'
    if database == 'current':
        open_database(path).close()
    elif database in ('old', 'newer'):
        with sqlite3.connect(path) as db:
            db.execute(f'PRAGMA user_version = {0 if database == "old" else CURRENT_VERSION + 1}')
    elif database == 'invalid':
        path.write_bytes(b'not sqlite')
    before = snapshot(local)
    monkeypatch.setattr(cli, 'run_lock', Mock(side_effect=AssertionError('must not lock')))
    # A temporary archive probe is a write even when it is subsequently deleted.
    import raptor_etl.config as config
    monkeypatch.setattr(config.tempfile, 'TemporaryFile', Mock(side_effect=AssertionError('must not write')))
    assert cli.main(['check']) == (2 if database in ('newer', 'invalid') else 0)
    assert snapshot(local) == before
    output = capsys.readouterr().out
    for name in EXPECTED_FILES:
        data = (local / 'source' / name).read_bytes()
        assert f'OK {name}: present size={len(data)} sha256={hashlib.sha256(data).hexdigest()}' in output
    if database == 'missing':
        assert 'will be created on first run' in output
        assert not path.exists()


@pytest.mark.parametrize('command', ['run', 'check'])
@pytest.mark.parametrize('fault', ['login', 'listing', 'missing', 'read'])
def test_smb_faults(configured, monkeypatch, capsys, command, fault):
    password = 'PLANTED-PASSWORD-007'
    monkeypatch.setenv('RAPTOR_SOURCE_PATH', '//server/share')
    monkeypatch.setenv('RAPTOR_SMB_USERNAME', 'user')
    monkeypatch.setenv('RAPTOR_SMB_PASSWORD', password)
    client = Mock()
    client.listdir.return_value = list(EXPECTED_FILES)
    client.open_file.side_effect = lambda *args, **kwargs: io.BytesIO(b'report')
    if fault == 'login':
        client.register_session.side_effect = RuntimeError(password)
    elif fault == 'listing':
        client.listdir.side_effect = RuntimeError(password)
    elif fault == 'missing':
        client.listdir.return_value = list(EXPECTED_FILES[1:])
    else:
        class BrokenRead(io.BytesIO):
            def read(self, size=-1):
                raise OSError(password)
        client.open_file.side_effect = lambda *args, **kwargs: BrokenRead()
    monkeypatch.setattr(source, 'smbclient', client)
    load = Mock(return_value=True)
    monkeypatch.setattr(cli, 'load_stage', load)
    before = snapshot(configured)
    assert cli.main([command]) == (4 if fault in ('login', 'listing') else 1)
    output = capsys.readouterr().out
    assert password not in output
    if command == 'check':
        assert 'FAIL' in output
        assert snapshot(configured) == before
        assert {call[0] for call in client.method_calls} <= {'register_session', 'listdir', 'open_file'}
    if fault in ('login', 'listing'):
        load.assert_not_called()
        assert not (configured / 'bronze.db').exists()
        assert not list(configured.glob('*_*.pdf'))


def test_check_invalid_configuration(configured, monkeypatch, capsys):
    monkeypatch.delenv('RAPTOR_ARCHIVE_DIR')
    before = snapshot(configured)
    assert cli.main(['check']) == 2
    assert 'FAIL configuration: RAPTOR_ARCHIVE_DIR' in capsys.readouterr().out
    assert snapshot(configured) == before
