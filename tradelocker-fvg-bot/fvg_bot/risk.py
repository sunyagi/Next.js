"""Daily guard rails shared by the live bot and the backtester."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd

from .config import Settings


def trading_day(now: pd.Timestamp) -> date:
    """FX trading day: rolls over at 17:00 New York time, so the Asia session
    counts toward the following day."""
    local = now.tz_convert(ZoneInfo("America/New_York")) + pd.Timedelta(hours=7)
    return local.date()


class RiskManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.day: date | None = None
        self.day_start_balance = 0.0
        self.trades_today = 0
        self.used_setups: set[str] = set()

    def _roll(self, now: pd.Timestamp, balance: float) -> None:
        today = trading_day(now)
        if today != self.day:
            self.day = today
            self.day_start_balance = balance
            self.trades_today = 0

    def can_trade(self, now: pd.Timestamp, balance: float, setup_id: str) -> tuple[bool, str]:
        self._roll(now, balance)
        if setup_id in self.used_setups:
            return False, "setup already traded"
        if self.trades_today >= self.settings.max_trades_per_day:
            return False, f"max {self.settings.max_trades_per_day} trades per day reached"
        loss_today = self.day_start_balance - balance
        if loss_today >= self.settings.max_daily_loss_usd:
            return False, f"daily loss limit hit (-${loss_today:.2f})"
        return True, "ok"

    def record_trade(self, setup_id: str) -> None:
        self.trades_today += 1
        self.used_setups.add(setup_id)
