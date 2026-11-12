from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event
import signal

import pytest

from raptor_etl import cli, scheduler
from raptor_etl.clock import Clock
from raptor_etl.config import load_config
from raptor_etl.logging import configure_logging


def local(config, value, fold=0):
    return datetime.fromisoformat(value).replace(tzinfo=config.timezone, fold=fold)


@pytest.mark.parametrize('now,expected', [
    ('2026-11-10T22:59', '2026-11-10T23:00'),
    ('2026-11-13T23:01', '2026-11-16T23:00'),
    ('2026-03-07T22:59', '2026-03-07T23:00'),
    ('2026-03-07T23:01', '2026-03-08T23:00'),
    ('2026-03-08T23:01', '2026-03-09T23:00'),
    ('2026-10-31T22:59', '2026-10-31T23:00'),
    ('2026-10-31T23:01', '2026-11-01T23:00'),
    ('2026-11-01T23:01', '2026-11-02T23:00'),
])
def test_next_run(configured, now, expected):
    config = load_config()
    if now[:10] not in ('2026-11-10', '2026-11-13'):
        config = replace(config, run_days=tuple(range(7)))
    result = scheduler.next_run(config, Clock(config.timezone, lambda: local(config, now)))
    assert result.isoformat() == local(config, expected).isoformat()


def test_spring_gap(configured):
    config = replace(load_config(), run_time='02:30', run_days=tuple(range(7)))
    clock = Clock(config.timezone, lambda: local(config, '2026-03-07T02:30'))
    assert scheduler.next_run(config, clock).isoformat() == local(config, '2026-03-09T02:30').isoformat()


def test_fall_both_folds(configured):
    config = replace(load_config(), run_time='01:30', run_days=tuple(range(7)))
    now = local(config, '2026-11-01T00:59')
    results = []
    for _ in range(3):
        result = scheduler.next_run(config, Clock(config.timezone, lambda: now))
        results.append(result)
        now = result
    assert [r.isoformat() for r in results] == [
        '2026-11-01T01:30:00-07:00', '2026-11-01T01:30:00-08:00',
        '2026-11-02T01:30:00-08:00']
    assert [r.fold for r in results] == [0, 1, 0]


@pytest.mark.parametrize('name,value', [('RUN_TIME', '24:00'), ('RUN_TIME', '1:30'),
                                       ('RUN_DAYS', 'FRI-MON'), ('RUN_DAYS', 'MON,,TUE')])
def test_invalid_schedule(configured, monkeypatch, name, value):
    monkeypatch.setenv('RAPTOR_' + name, value)
    assert cli.main(['schedule']) == 2


@pytest.mark.parametrize('check_result', [0, 1, 2, 4])
@pytest.mark.parametrize('pass_result', [0, 1, 2, 3, 4])
def test_loop_continues(configured, capsys, check_result, pass_result):
    config = load_config()
    now = local(config, '2026-11-13T22:59')
    calls = []

    class Stop(Event):
        def wait(self, seconds):
            nonlocal now
            now = (now.astimezone(timezone.utc) + timedelta(seconds=seconds)).astimezone(config.timezone)
            return False

    stop = Stop()

    def run_pass():
        nonlocal now
        calls.append(now)
        if len(calls) == 2:
            stop.set()
        # A long pass misses Monday's slot. It must not be replayed.
        now = local(config, '2026-11-16T23:01')
        return pass_result

    checks = []
    assert scheduler.schedule_loop(config, configure_logging(),
        clock=Clock(config.timezone, lambda: now), stop=stop, run_pass=run_pass,
        startup_check=lambda: checks.append(True) or check_result) == 0
    assert checks == [True]
    assert [value.isoformat() for value in calls] == [
        '2026-11-13T23:00:00-08:00', '2026-11-17T23:00:00-08:00']
    output = capsys.readouterr().out
    level = 'WARNING' if check_result else 'INFO'
    assert f'{level} Scheduler startup check exited with code {check_result}' in output
    assert output.count(f'Scheduled run exited with code {pass_result}') == 2


@pytest.mark.parametrize('signum', [signal.SIGTERM, signal.SIGINT])
def test_signal_interrupts_wait(configured, monkeypatch, signum):
    config = load_config()
    handlers = {}
    restored = []
    def install(sig, handler):
        if callable(handler):
            handlers[sig] = handler
        else:
            restored.append((sig, handler))
        return signal.SIG_DFL
    monkeypatch.setattr(scheduler.signal, 'signal', install)
    class Stop(Event):
        def wait(self, seconds):
            handlers[signum](signum, None)
            assert self.is_set()
            return True
    monkeypatch.setattr(scheduler, 'Event', Stop)
    monkeypatch.setattr(scheduler, 'Clock', lambda zone: Clock(zone, lambda: local(config, '2026-11-10T22:59')))
    calls = []
    assert scheduler.schedule(config, configure_logging(), run_pass=lambda: calls.append('run'),
                              startup_check=lambda: 0) == 0
    assert calls == []
    assert restored == [(signal.SIGTERM, signal.SIG_DFL), (signal.SIGINT, signal.SIG_DFL)]


def test_cli_uses_existing_commands(configured, monkeypatch):
    calls = []
    def schedule(config, logger, *, run_pass, startup_check):
        assert startup_check() == 4  # Absent source, through the existing check path.
        assert run_pass() == 4
        calls.append(True)
        return 0
    monkeypatch.setattr(scheduler, 'schedule', schedule)
    assert cli.main(['schedule']) == 0
    assert calls == [True]
