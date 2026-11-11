"""Offline contract validation; source snapshots bracket every collection attempt."""
from dataclasses import replace
from datetime import datetime, timezone
import io
import logging
from pathlib import Path
import shutil
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from raptor_etl import cli
from raptor_etl.clock import Clock
from raptor_etl.collect import EXPECTED_FILES, collect, file_hash
from raptor_etl.config import Config
from raptor_etl.database import open_database
from raptor_etl.lock import run_lock
from raptor_etl.source import SMBSource, SourceError

SAMPLES = Path(__file__).resolve().parents[1] / 'Samples'


def snapshot(root):
    return {p.relative_to(root): (file_hash(p), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def setup(tmp_path):
    if not SAMPLES.is_dir():
        pytest.skip('Samples/ is absent; collect tests require a temporary copy of Samples/')
    source = tmp_path / 'source'
    shutil.copytree(SAMPLES, source)
    archive = tmp_path / 'archive'
    archive.mkdir()
    config = Config(str(source), archive, tmp_path / 'bronze.db',
                    ZoneInfo('America/Los_Angeles'), '23:00', (0,), 'INFO', None, None, None)
    database = open_database(config.db_path)
    clock = Clock(config.timezone, lambda: datetime(2026, 11, 11, 7, 30, tzinfo=timezone.utc))

    def run(selected=config, selected_clock=clock):
        before = snapshot(source)
        try:
            return collect(selected, database, selected_clock)
        finally:
            assert snapshot(source) == before
            assert not list(archive.glob('*.partial'))
    yield config, database, run
    database.close()


def statuses(results):
    return [r.outcome for r in results]


def test_first_second_changed_and_timezone(setup):
    config, db, run = setup
    first = run()
    assert statuses(first) == ['archived'] * 8
    assert [r.original_name for r in first] == list(EXPECTED_FILES)
    for row in db.execute('SELECT original_name, archive_name, copy_date, sha256, size_bytes, archived_at FROM archived_file'):
        name, archived, date, digest, size, timestamp = row
        assert archived == f'2026-11-10_{name}'
        assert date == '2026-11-10'
        assert timestamp == '2026-11-10 23:30:00'
        assert file_hash(config.archive_dir / archived) == file_hash(Path(config.source_path) / name) == digest
        assert size == (config.archive_dir / archived).stat().st_size
    before = snapshot(config.archive_dir)
    assert statuses(run()) == ['unchanged'] * 8
    assert snapshot(config.archive_dir) == before
    changed = Path(config.source_path) / EXPECTED_FILES[0]
    changed.write_bytes(changed.read_bytes() + b'changed fixture')
    tomorrow = Clock(config.timezone, lambda: datetime(2026, 11, 12, 7, 30, tzinfo=timezone.utc))
    result = run(config, tomorrow)
    assert statuses(result) == ['archived'] + ['unchanged'] * 7
    assert db.execute('SELECT COUNT(*) FROM archived_file').fetchone()[0] == 9


def test_missing_case_sensitive_ignored_and_exit(setup, monkeypatch, caplog):
    config, db, run = setup
    path = Path(config.source_path) / EXPECTED_FILES[0]
    path.rename(path.with_name(path.name.lower()))
    (Path(config.source_path) / 'ignored.txt').write_text('ignored')
    caplog.set_level(logging.INFO, logger='raptor_etl')
    assert statuses(run()) == ['missing'] + ['archived'] * 7
    assert 'ignored.txt' not in caplog.text
    monkeypatch.setattr(cli, 'load_config', lambda: config)
    monkeypatch.setattr(cli, 'Clock', lambda zone: Clock(zone, lambda: datetime(2026, 11, 11, tzinfo=timezone.utc)))
    assert cli.main(['run']) == 1


@pytest.mark.parametrize('same', [True, False])
def test_existing_archive_recovery_or_conflict(setup, same):
    config, db, run = setup
    name = EXPECTED_FILES[0]
    final = config.archive_dir / f'2026-11-10_{name}'
    final.write_bytes((Path(config.source_path) / name).read_bytes() if same else b'keep forever')
    before = (file_hash(final), final.stat().st_mtime_ns)
    assert statuses(run()) == [('archived' if same else 'failed')] + ['archived'] * 7
    assert (file_hash(final), final.stat().st_mtime_ns) == before
    assert db.execute('SELECT COUNT(*) FROM archived_file').fetchone()[0] == (8 if same else 7)


def test_stale_partials_and_missing_source(setup):
    config, db, run = setup
    for date in ('2026-11-09', '2026-11-10'):
        for name in EXPECTED_FILES:
            (config.archive_dir / f'.{date}_{name}.partial').write_bytes(b'interrupted')
    (Path(config.source_path) / EXPECTED_FILES[0]).unlink()
    assert statuses(run()) == ['missing'] + ['archived'] * 7
    assert not list(config.archive_dir.glob('.*.partial'))


@pytest.mark.parametrize('fault', ['read', 'write', 'verify', 'database'])
def test_independent_failures_and_cleanup(setup, monkeypatch, fault):
    config, db, run = setup
    import raptor_etl.collect as module
    if fault == 'read':
        from raptor_etl.source import LocalSource
        original = LocalSource.open
        class BrokenRead(io.BytesIO):
            def read(self, size=-1):
                raise OSError('injected read failure')
        monkeypatch.setattr(LocalSource, 'open', lambda self, name:
                            BrokenRead(b'bytes') if name == EXPECTED_FILES[0]
                            else original(self, name))
    elif fault == 'write':
        original = Path.open
        class BrokenWrite(io.BytesIO):
            def write(self, data):
                raise OSError('injected write failure')
        def opened(path, *args, **kwargs):
            if path.name == f'.2026-11-10_{EXPECTED_FILES[0]}.partial':
                path.touch()
                return BrokenWrite()
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'open', opened)
    elif fault == 'verify':
        original = module.file_hash
        monkeypatch.setattr(module, 'file_hash', lambda path: '0' * 64 if EXPECTED_FILES[0] in path.name else original(path))
    else:
        db.execute("CREATE TRIGGER fail_first BEFORE INSERT ON archived_file WHEN NEW.original_name = 'Downtime Summary.pdf' BEGIN SELECT RAISE(FAIL, 'injected'); END")
    assert statuses(run()) == ['failed'] + ['archived'] * 7
    assert db.execute('SELECT COUNT(*) FROM archived_file').fetchone()[0] == 7
    if fault == 'database':
        db.execute('DROP TRIGGER fail_first')
        assert statuses(run()) == ['archived'] + ['unchanged'] * 7


def test_midnight_uses_one_clock_read(setup):
    config, db, run = setup
    provider = Mock(side_effect=[datetime(2026, 11, 11, 7, 59, tzinfo=timezone.utc),
                                datetime(2026, 11, 11, 8, 1, tzinfo=timezone.utc)])
    results = run(config, Clock(config.timezone, provider))
    assert all(r.archive_name.startswith('2026-11-10_') for r in results)
    assert provider.call_count == 1


@pytest.mark.parametrize('prefix', ['//server/share', r'\\server\share'])
def test_mock_smb_read_only(setup, monkeypatch, prefix):
    config, db, run = setup
    from raptor_etl import source
    client = Mock()
    client.listdir.return_value = list(EXPECTED_FILES)
    def opened(path, mode):
        assert mode == 'rb'
        return io.BytesIO((Path(config.source_path) / path.split('\\')[-1]).read_bytes())
    client.open_file.side_effect = opened
    monkeypatch.setattr(source, 'smbclient', client)
    remote = replace(config, source_path=prefix, smb_username='user', smb_password='secret', smb_domain='DOMAIN')
    assert statuses(run(remote)) == ['archived'] * 8
    client.register_session.assert_called_once_with('server', username=r'DOMAIN\user', password='secret')
    assert client.open_file.call_count == 8
    assert {call[0] for call in client.method_calls} == {'register_session', 'listdir', 'open_file'}


def test_smb_login_failure_sanitized_and_load_continues(setup, monkeypatch, capsys):
    config, db, run = setup
    from raptor_etl import source
    password = 'PASSWORD-CANARY'
    client = Mock()
    client.register_session.side_effect = RuntimeError(password)
    monkeypatch.setattr(source, 'smbclient', client)
    remote = replace(config, source_path='//server/share', smb_username='user', smb_password=password)
    with pytest.raises(SourceError) as error:
        SMBSource(remote).names()
    assert password not in str(error.value)
    assert statuses(run(remote)) == ['failed'] * 8
    monkeypatch.setattr(cli, 'load_config', lambda: remote)
    load = Mock(return_value=True)
    monkeypatch.setattr(cli, 'load_stage', load)
    assert cli.main(['run']) == 1
    load.assert_called_once()
    output = capsys.readouterr().out
    assert output.count(': failed') == 8
    assert password not in output


def test_smb_read_error_sanitized(setup, monkeypatch):
    config, db, run = setup
    from raptor_etl import source
    client = Mock()
    client.listdir.return_value = list(EXPECTED_FILES)
    client.open_file.side_effect = RuntimeError('PASSWORD-CANARY')
    monkeypatch.setattr(source, 'smbclient', client)
    remote = replace(config, source_path='//server/share', smb_username='user', smb_password='PASSWORD-CANARY')
    with pytest.raises(SourceError) as error:
        with SMBSource(remote).open(EXPECTED_FILES[0]):
            pass
    assert 'PASSWORD-CANARY' not in str(error.value)
    assert statuses(run(remote)) == ['failed'] * 8


def test_concurrent_run_exits_three(setup, monkeypatch):
    config, db, run = setup
    monkeypatch.setattr(cli, 'load_config', lambda: config)
    before = snapshot(Path(config.source_path))
    with run_lock(config.db_path):
        assert cli.main(['run']) == 3
    assert snapshot(Path(config.source_path)) == before
    assert db.execute('SELECT COUNT(*) FROM archived_file').fetchone()[0] == 0


def test_cli_success_and_load_visibility(setup, monkeypatch):
    config, db, run = setup
    before = snapshot(Path(config.source_path))
    monkeypatch.setattr(cli, 'load_config', lambda: config)
    def load(config, database, clock):
        rows = database.execute('SELECT archive_name FROM archived_file').fetchall()
        assert len(rows) == 8
        assert all((config.archive_dir / row[0]).is_file() for row in rows)
        return True
    monkeypatch.setattr(cli, 'load_stage', load)
    assert cli.main(['run']) == 0
    assert cli.main(['run']) == 0
    assert snapshot(Path(config.source_path)) == before


def test_unreachable_source_stale_cleanup(setup):
    config, db, run = setup
    partial = config.archive_dir / f'.2026-11-09_{EXPECTED_FILES[0]}.partial'
    partial.write_bytes(b'interrupted')
    assert statuses(run(replace(config, source_path=config.source_path + '-absent'))) == ['failed'] * 8
    assert not partial.exists()
