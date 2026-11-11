"""Immutable, typed report records; nullable source values remain nullable."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Header:
    printed_at: str | None
    report_start: str | None
    report_end: str | None
    recipe: str | None


@dataclass(frozen=True)
class Alarm:
    row_order: int
    alarm_id: int | None
    description: str | None
    occurrences: int | None
    total_duration: str | None
    min_duration: str | None
    max_duration: str | None


@dataclass(frozen=True)
class GrandTotal:
    occurrences: int | None
    total_duration: str | None


@dataclass(frozen=True)
class KPIs:
    avg_bf_per_piece: float | None
    lug_fill: float | None
    trimloss: float | None
    trimmer_speed_slow_pct: float | None
    trimmer_speed_medium_pct: float | None
    trimmer_speed_fast_pct: float | None


@dataclass(frozen=True)
class Breakdown:
    row_order: int
    section: str
    label: str | None
    is_total: bool
    pieces: int | None
    volume: float | None
    pct_volume: float | None


@dataclass(frozen=True)
class Day:
    row_order: int
    run_start: str | None
    fast_pct: float | None
    medium_pct: float | None
    slow_pct: float | None
    lug_fill: float | None
    bf_per_piece: float | None
    trimloss: float | None
    total_stops: int | None
    downtime: str | None
    volume: float | None


@dataclass(frozen=True)
class ParsedReport:
    report_type: str
    header: Header
    page_count: int
    alarms: tuple[Alarm, ...] = ()
    grand_total: GrandTotal | None = None
    kpis: KPIs | None = None
    breakdown: tuple[Breakdown, ...] = ()
    days: tuple[Day, ...] = ()
