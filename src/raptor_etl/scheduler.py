"""Plant wall-clock scheduling, with no replay of missed runs."""
from datetime import datetime, time, timedelta, timezone
import logging
import signal
from threading import Event

from .clock import Clock


def next_run(config, clock: Clock) -> datetime:
    """Return the first scheduled instant strictly after the injected now.

    Round-tripping each fold through UTC rejects nonexistent wall times and
    duplicate folds on ordinary days. Compare instants in UTC: comparing two
    datetimes with the same ZoneInfo would ignore their differing folds.
    """
    now = clock.now()
    hour, minute = map(int, config.run_time.split(":"))
    day = now.date()
    while True:
        if day.weekday() in config.run_days:
            candidates = []
            for fold in (0, 1):
                candidate = datetime.combine(day, time(hour, minute), config.timezone).replace(fold=fold)
                instant = candidate.astimezone(timezone.utc)
                restored = instant.astimezone(config.timezone)
                if restored == candidate and restored.fold == fold and instant > now.astimezone(timezone.utc):
                    candidates.append(candidate)
            if candidates:
                return min(candidates, key=lambda value: value.astimezone(timezone.utc))
        day += timedelta(days=1)


def schedule_loop(config, logger, *, clock, stop, run_pass, startup_check) -> int:
    """Check once, then wait interruptibly and run serial passes until stopped."""
    result = startup_check()
    logger.log(logging.WARNING if result else logging.INFO,
               "Scheduler startup check exited with code %d", result)
    while not stop.is_set():
        target = next_run(config, clock)
        logger.info("Next scheduled run: %s", target.isoformat())
        # Recheck the clock after each wait, including an early/spurious wake.
        while not stop.is_set():
            remaining = (target.astimezone(timezone.utc)
                         - clock.now().astimezone(timezone.utc)).total_seconds()
            if remaining <= 0:
                break
            stop.wait(min(remaining, 60))
        if stop.is_set():
            break
        result = run_pass()
        logger.log(logging.WARNING if result else logging.INFO,
                   "Scheduled run exited with code %d", result)
        # Calculate anew after the pass: missed slots are never replayed.
    logger.info("Scheduler stopped")
    return 0


def schedule(config, logger, *, run_pass, startup_check) -> int:
    """Install shutdown handlers for the scheduler's lifetime only.

    A signal during a pass lets that pass finish and release its lock before
    exiting. During a wait, setting the event wakes it immediately.
    """
    stop = Event()
    previous = {}

    def shutdown(signum, frame):
        stop.set()

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, shutdown)
        return schedule_loop(config, logger, clock=Clock(config.timezone), stop=stop,
                             run_pass=run_pass, startup_check=startup_check)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
