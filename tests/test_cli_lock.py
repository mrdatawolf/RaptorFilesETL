import os
from pathlib import Path
import subprocess
import sys

import pytest

from raptor_etl import cli
from raptor_etl.errors import ArchiveIntegrityError, LayoutError, ReconciliationError
from raptor_etl.lock import run_lock


def test_success_hooks(configured, monkeypatch):
    (configured / "source").mkdir()
    calls = []
    monkeypatch.setattr(cli, 'collect_stage', lambda *args: calls.append('collect') or False)
    monkeypatch.setattr(cli, 'load_stage', lambda *args: calls.append('load') or True)
    assert cli.main(['run']) == 1
    assert calls == ['collect', 'load']


@pytest.mark.parametrize('error', [LayoutError, ReconciliationError, ArchiveIntegrityError, OSError])
def test_stage_error(configured, monkeypatch, error):
    (configured / "source").mkdir()
    def fail(*args):
        raise error('secret-canary')
    monkeypatch.setattr(cli, 'collect_stage', fail)
    assert cli.main(['run']) == 1


def test_entry_point_with_unreachable_source(configured):
    executable = str(Path(sys.executable).with_name('raptor-etl'))
    result = subprocess.run([executable, 'run'], capture_output=True, text=True)
    assert result.returncode == 4  # The configured source does not exist.


def test_second_run_and_death_release(configured):
    path = configured / 'bronze.db'
    script = "from pathlib import Path; from raptor_etl.lock import run_lock; import sys;\nwith run_lock(Path(sys.argv[1])):\n print('ready', flush=True)\n sys.stdin.read()\n"
    process = subprocess.Popen([sys.executable, '-c', script, str(path)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'ready'
        executable = str(Path(sys.executable).with_name('raptor-etl'))
        result = subprocess.run([executable, 'run'], capture_output=True, text=True, timeout=5)
        assert result.returncode == 3
        assert not path.exists()
    finally:
        process.kill()
        process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
    with run_lock(path):
        pass
    assert cli.main(['run']) == 4  # Lock released; precheck reports the absent source.


def test_database_unusable(configured):
    (configured / 'source').mkdir()
    (configured / 'bronze.db').write_bytes(b'not a sqlite database')
    assert cli.main(['run']) == 2
