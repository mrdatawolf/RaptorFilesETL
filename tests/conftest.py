import os
import pytest


@pytest.fixture
def configured(tmp_path, monkeypatch):
    for key in os.environ:
        if key.startswith('RAPTOR_'):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    for key, value in {
        'SOURCE_PATH': str(tmp_path / 'source'),
        'ARCHIVE_DIR': str(tmp_path),
        'DB_PATH': str(tmp_path / 'bronze.db'),
    }.items():
        monkeypatch.setenv('RAPTOR_' + key, value)
    return tmp_path
