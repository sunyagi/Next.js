"""Fair Value Gap detection.

A bullish FVG is a three-candle pattern where candle 1's high is below candle 3's
low: price moved up so fast that the range in between never traded. A bearish
FVG is the mirror image (candle 1's low above candle 3's high).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

BULL = "bull"
BEAR = "bear"


@dataclass(frozen=True)
class FVG:
    direction: str  # BULL or BEAR
    top: float
    bottom: float
    start: pd.Timestamp  # open time of candle 1
    confirmed_at: pd.Timestamp  # open time of candle 3 (gap exists once it closes)

    @property
    def size(self) -> float:
        return self.top - self.bottom

    @property
    def id(self) -> str:
        return f"{self.direction}-{self.start.isoformat()}"


def find_fvgs(df: pd.DataFrame, min_size: float = 0.0, direction: str | None = None) -> list[FVG]:
    """All FVGs in `df` (oldest first), optionally filtered by direction."""
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    idx = df.index
    gaps: list[FVG] = []
    for i in range(2, len(df)):
        if direction in (None, BULL) and lows[i] - highs[i - 2] >= max(min_size, 1e-9):
            gaps.append(FVG(BULL, float(lows[i]), float(highs[i - 2]), idx[i - 2], idx[i]))
        if direction in (None, BEAR) and lows[i - 2] - highs[i] >= max(min_size, 1e-9):
            gaps.append(FVG(BEAR, float(lows[i - 2]), float(highs[i]), idx[i - 2], idx[i]))
    return gaps


def first_touch(fvg: FVG, candles: pd.DataFrame) -> pd.Timestamp | None:
    """Open time of the first candle that trades back into the gap."""
    if candles.empty:
        return None
    if fvg.direction == BULL:
        hits = candles.index[candles["low"].to_numpy() <= fvg.top]
    else:
        hits = candles.index[candles["high"].to_numpy() >= fvg.bottom]
    return hits[0] if len(hits) else None


def is_invalidated(fvg: FVG, candles: pd.DataFrame) -> bool:
    """A gap is dead once a candle *closes* through its far side."""
    if candles.empty:
        return False
    closes = candles["close"].to_numpy()
    if fvg.direction == BULL:
        return bool((closes < fvg.bottom).any())
    return bool((closes > fvg.top).any())
