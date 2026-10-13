"""Trading-session filter (Asia and New York by default)."""

from __future__ import annotations

from datetime import time
from zoneinfo import ZoneInfo

import pandas as pd

from .config import Session


def _parse(hhmm: str) -> time:
    hours, minutes = hhmm.split(":")
    return time(int(hours), int(minutes))


def active_session(now: pd.Timestamp, sessions: list[Session], timezone: str) -> str | None:
    """Name of the session `now` falls in, or None. Uses the zone's local clock,
    so DST shifts are handled automatically."""
    local = now.tz_convert(ZoneInfo(timezone)).time()
    for session in sessions:
        start, end = _parse(session.start), _parse(session.end)
        if start <= end:
            inside = start <= local < end
        else:  # crosses midnight, e.g. 19:00 -> 03:00
            inside = local >= start or local < end
        if inside:
            return session.name
    return None
