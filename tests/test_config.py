from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import logging

import pytest

from raptor_etl import cli
from raptor_etl.clock import Clock
from raptor_etl.config import load_config
from raptor_etl.errors import ConfigError, LayoutError, ReconciliationError
from raptor_etl.logging import configure_logging


def test_all_errors_no_secrets(configured, monkeypatch, capsys):
    values = {'SOURCE_PATH': '//host/share', 'SMB_PASSWORD': 'secret-canary',
              'ARCHIVE_DIR': str(configured / 'missing'),
              'DB_PATH': str(configured / 'missing' / 'db'),
              'TIMEZONE': 'bad-zone', 'RUN_TIME': '24:00',
              'RUN_DAYS': 'BAD', 'LOG_LEVEL': 'secret-canary'}
    for key, value in values.items():
        monkeypatch.setenv('RAPTOR_' + key, value)
    with pytest.raises(ConfigError) as error:
        load_config()
    assert 'secret-canary' not in str(error.value)
    assert cli.main(['run']) == 2
    output = capsys.readouterr()
    assert not output.err
    assert 'secret-canary' not in output.out
    for name in ('SMB_USERNAME', 'ARCHIVE_DIR', 'DB_PATH', 'TIMEZONE', 'RUN_TIME', 'RUN_DAYS', 'LOG_LEVEL'):
        assert 'RAPTOR_' + name in output.out


def test_missing_required(configured, monkeypatch):
    for name in ('SOURCE_PATH', 'ARCHIVE_DIR', 'DB_PATH'):
        monkeypatch.delenv('RAPTOR_' + name)
    with pytest.raises(ConfigError) as error:
        load_config()
    assert len(error.value.problems) == 3


def test_env_override_defaults_and_secret_repr(configured, monkeypatch):
    (configured / '.env').write_text('RAPTOR_SOURCE_PATH=from-file\nRAPTOR_RUN_TIME=12:34\nRAPTOR_SMB_PASSWORD=hidden\n')
    config = load_config()
    assert config.source_path == str(configured / 'source')
    assert config.run_time == '12:34'
    assert config.timezone.key == 'America/Los_Angeles'
    assert config.run_days == (0, 1, 2, 3, 4)
    assert 'hidden' not in repr(config)


@pytest.mark.parametrize('name,value', [('RUN_DAYS', 'FRI-MON'), ('RUN_DAYS', 'MON,,TUE'), ('RUN_TIME', '1:00'), ('SOURCE_PATH', '//host'), ('TIMEZONE', ''), ('SMB_DOMAIN', '')])
def test_invalid_values(configured, monkeypatch, name, value):
    monkeypatch.setenv('RAPTOR_' + name, value)
    with pytest.raises(ConfigError):
        load_config()


def test_unwritable_archive(configured, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError
    monkeypatch.setattr('raptor_etl.config.tempfile.TemporaryFile', denied)
    with pytest.raises(ConfigError, match='RAPTOR_ARCHIVE_DIR'):
        load_config()


def test_clock():
    clock = Clock(ZoneInfo('America/Los_Angeles'), lambda: datetime(2026, 1, 2, 7, 30, tzinfo=timezone.utc))
    assert clock.now().strftime('%Y-%m-%d %H:%M') == '2026-01-01 23:30'
    assert ReconciliationError.__bases__ == (LayoutError,)


def test_logging(capsys):
    logger = configure_logging('WARNING')
    logger.info('hidden')
    logger.warning('visible')
    captured = capsys.readouterr()
    assert captured.out == 'WARNING visible\n'
    assert not captured.err
