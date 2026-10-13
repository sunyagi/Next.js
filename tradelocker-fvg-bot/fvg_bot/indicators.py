"""Candle helpers. All frames use a UTC DatetimeIndex of bar *open* times and
columns open/high/low/close."""

from __future__ import annotations

import numpy as np
import pandas as pd

OHLC = ["open", "high", "low", "close"]


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate candles to a higher timeframe (e.g. 1min -> 2min, 15min, 4h)."""
    out = df[OHLC].resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    return out.dropna()


def closed_bars(df: pd.DataFrame, timeframe: pd.Timedelta, now: pd.Timestamp) -> pd.DataFrame:
    """Drop the candle that is still forming at `now`."""
    return df[df.index + timeframe <= now]


def ema(values: pd.Series, period: int) -> pd.Series:
    return values.ewm(span=period, adjust=False).mean()


def swing_points(df: pd.DataFrame, strength: int) -> tuple[list[float], list[float]]:
    """Confirmed fractal swing highs and lows (oldest first)."""
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    swing_highs: list[float] = []
    swing_lows: list[float] = []
    for i in range(strength, len(df) - strength):
        window_h = highs[i - strength : i + strength + 1]
        window_l = lows[i - strength : i + strength + 1]
        if highs[i] == np.max(window_h):
            swing_highs.append(float(highs[i]))
        if lows[i] == np.min(window_l):
            swing_lows.append(float(lows[i]))
    return swing_highs, swing_lows
