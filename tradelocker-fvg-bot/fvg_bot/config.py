"""Bot settings: strategy and risk parameters come from YAML, credentials from env vars."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml


@dataclass
class Session:
    name: str
    start: str  # "HH:MM" in Settings.session_timezone
    end: str  # may be earlier than start, meaning the session crosses midnight


@dataclass
class Settings:
    # --- Instrument / account ---
    symbol: str = "XAUUSD"
    lot_size: float = 0.01
    contract_size: float = 100.0  # ounces per 1.00 lot of gold (check your broker's spec)
    account_size: float = 150.0

    # --- Risk ---
    risk_reward: float = 2.0
    max_risk_pct: float = 5.0  # skip setups whose stop would lose more than this % of balance
    min_stop_distance: float = 1.00  # $ price distance; tighter stops get eaten by spread
    stop_buffer: float = 0.30  # $ added beyond the swept low/high
    max_trades_per_day: int = 3
    max_daily_loss_pct: float = 10.0
    one_position_at_a_time: bool = True

    # --- 4H trend ---
    trend_ema_period: int = 50
    trend_slope_lookback: int = 5
    swing_strength: int = 2  # candles on each side to confirm a swing high/low

    # --- 15M setup ---
    setup_fvg_min_size: float = 1.00  # $ minimum gap height
    setup_lookback_bars: int = 48  # only use 15M FVGs formed in the last 12h

    # --- 2M entry ---
    entry_fvg_min_size: float = 0.20
    max_entry_bars_after_tap: int = 30  # 2M bars (= 1h) allowed between the tap and the entry

    # --- Sessions ---
    session_timezone: str = "America/New_York"
    sessions: list[Session] = field(
        default_factory=lambda: [
            Session("asia", "19:00", "03:00"),
            Session("new_york", "08:00", "17:00"),
        ]
    )

    # --- Runtime ---
    poll_seconds: int = 5
    dry_run: bool = True

    @property
    def max_risk_usd(self) -> float:
        return self.account_size * self.max_risk_pct / 100.0

    @property
    def max_daily_loss_usd(self) -> float:
        return self.account_size * self.max_daily_loss_pct / 100.0

    @classmethod
    def load(cls, path: str | Path | None) -> "Settings":
        if path is None:
            return cls()
        raw = yaml.safe_load(Path(path).read_text()) or {}
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"Unknown config keys: {sorted(unknown)}")
        if "sessions" in raw:
            raw["sessions"] = [Session(**s) for s in raw["sessions"]]
        return cls(**raw)


@dataclass
class Credentials:
    environment: str
    email: str
    password: str
    server: str
    acc_num: int

    @classmethod
    def from_env(cls) -> "Credentials":
        missing = [k for k in ("TL_EMAIL", "TL_PASSWORD", "TL_SERVER") if not os.getenv(k)]
        if missing:
            raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")
        return cls(
            environment=os.getenv("TL_ENVIRONMENT", "https://demo.tradelocker.com"),
            email=os.environ["TL_EMAIL"],
            password=os.environ["TL_PASSWORD"],
            server=os.environ["TL_SERVER"],
            acc_num=int(os.getenv("TL_ACC_NUM", "0")),
        )
