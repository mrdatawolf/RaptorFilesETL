"""Injectable plant-local clock."""
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo


class Clock:
    def __init__(self, timezone: ZoneInfo, now: Callable[[], datetime] | None = None):
        self.timezone = timezone
        self._now = now or (lambda: datetime.now(self.timezone))

    def now(self) -> datetime:
        instant = self._now()
        if instant.tzinfo is None:
            raise ValueError("Clock provider must return a timezone-aware datetime")
        return instant.astimezone(self.timezone)
