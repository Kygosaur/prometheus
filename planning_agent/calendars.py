from __future__ import annotations

import re

from .models import TimeWindow


DAY_INDEX = {name: index for index, name in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}
DAY_MINUTES = 24 * 60
WEEK_MINUTES = 7 * DAY_MINUTES
TIME_RANGE = re.compile(r"(?P<start>\d{1,2}:\d{2})\s*[–—-]\s*(?P<end>\d{1,2}:\d{2})", re.IGNORECASE)


def parse_calendar(text: str | None, *, default_available: bool = True) -> tuple[tuple[TimeWindow, ...], tuple[TimeWindow, ...]]:
    """Parse human calendars such as `Mon: 08:00–17:00` and maintenance windows."""
    if not text or not text.strip():
        return ((TimeWindow(0, WEEK_MINUTES),) if default_available else ()), ()
    availability: list[TimeWindow] = []
    maintenance: list[TimeWindow] = []
    explicit_days: set[int] = set()
    recurring_shift: tuple[int, int] | None = None
    for raw_line in re.split(r"[\r\n;]+", text):
        line = raw_line.strip()
        if not line:
            continue
        if line.casefold().startswith("shift:"):
            match = TIME_RANGE.search(line)
            if not match:
                raise ValueError(f"Invalid shift calendar line: {line!r}")
            recurring_shift = (_clock(match.group("start")), _clock(match.group("end")))
            continue
        if ":" not in line:
            raise ValueError(f"Calendar line must start with a day: {line!r}")
        day_text, value = line.split(":", 1)
        day = DAY_INDEX.get(day_text.strip()[:3].casefold())
        if day is None:
            raise ValueError(f"Unknown calendar day: {day_text!r}")
        explicit_days.add(day)
        value = value.strip()
        if value.casefold() in {"leave", "off", "unavailable"}:
            continue
        if value.casefold() in {"24h", "24 hours", "available"}:
            availability.append(TimeWindow(day * DAY_MINUTES, (day + 1) * DAY_MINUTES, "available"))
            continue
        match = TIME_RANGE.search(value)
        if not match:
            raise ValueError(f"Invalid calendar time range: {line!r}")
        start_clock, end_clock = _clock(match.group("start")), _clock(match.group("end"))
        start = day * DAY_MINUTES + start_clock
        end = day * DAY_MINUTES + end_clock
        if end_clock <= start_clock:
            end += DAY_MINUTES
        target = maintenance if "maintenance" in value.casefold() else availability
        target.append(TimeWindow(start, end, "maintenance" if target is maintenance else "available"))

    if recurring_shift:
        for day in range(7):
            start_clock, end_clock = recurring_shift
            start = day * DAY_MINUTES + start_clock
            end = day * DAY_MINUTES + end_clock
            if end_clock <= start_clock:
                end += DAY_MINUTES
            availability.append(TimeWindow(start, end, "shift"))
    elif default_available:
        # For maintenance-only calendars, the resource is otherwise available 24/7.
        if not availability and maintenance:
            availability.append(TimeWindow(0, WEEK_MINUTES, "available"))
        # Explicit working-day calendars intentionally leave unspecified days unavailable.
        elif not availability and not explicit_days:
            availability.append(TimeWindow(0, WEEK_MINUTES, "available"))
    return tuple(availability), tuple(maintenance)


def format_week_minute(value: int) -> str:
    day_names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    day = max(0, value) // DAY_MINUTES
    minute = max(0, value) % DAY_MINUTES
    return f"{day_names[day % 7]} {minute // 60:02d}:{minute % 60:02d}"


def _clock(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"Invalid time: {value!r}")
    return hour * 60 + minute
