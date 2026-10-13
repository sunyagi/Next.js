"""Multi-timeframe FVG strategy.

1. 4H  -> trend bias: price vs. a rising/falling EMA, confirmed by swing structure.
2. 15M -> setup: an unfilled FVG in the trend direction that price retraces into.
3. 2M  -> entry: after the tap, a 2M FVG forms in the trend direction (displacement).
          Enter at market, stop beyond the extreme made since the tap, target = 2R.

`evaluate` is pure: it only looks at the closed candles it is given, so the live
bot and the backtester share exactly the same logic.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import Settings
from .fvg import BEAR, BULL, FVG, find_fvgs, first_touch, is_invalidated
from .indicators import ema, swing_points
from .sessions import active_session

M15 = pd.Timedelta(minutes=15)


@dataclass(frozen=True)
class Signal:
    side: str  # "buy" or "sell"
    entry: float
    stop_loss: float
    take_profit: float
    setup_id: str  # the 15M FVG this trade came from, so it is traded only once
    session: str

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop_loss)


@dataclass(frozen=True)
class Decision:
    signal: Signal | None
    reason: str


def trend_bias(h4: pd.DataFrame, settings: Settings) -> str | None:
    """BULL, BEAR, or None when the 4H chart has no clear direction."""
    needed = settings.trend_ema_period + settings.trend_slope_lookback
    if len(h4) < needed:
        return None
    line = ema(h4["close"], settings.trend_ema_period)
    close = h4["close"].iloc[-1]
    rising = line.iloc[-1] > line.iloc[-1 - settings.trend_slope_lookback]
    falling = line.iloc[-1] < line.iloc[-1 - settings.trend_slope_lookback]

    highs, lows = swing_points(h4.iloc[-needed:], settings.swing_strength)
    higher_structure = len(highs) >= 2 and len(lows) >= 2 and (highs[-1] > highs[-2] or lows[-1] > lows[-2])
    lower_structure = len(highs) >= 2 and len(lows) >= 2 and (highs[-1] < highs[-2] or lows[-1] < lows[-2])

    if close > line.iloc[-1] and rising and higher_structure:
        return BULL
    if close < line.iloc[-1] and falling and lower_structure:
        return BEAR
    return None


def build_signal(
    setup: FVG, m2_since_tap: pd.DataFrame, settings: Settings, session: str
) -> Signal | None:
    entry = float(m2_since_tap["close"].iloc[-1])
    if setup.direction == BULL:
        stop = float(m2_since_tap["low"].min()) - settings.stop_buffer
        risk = entry - stop
        side, target = "buy", entry + settings.risk_reward * risk
    else:
        stop = float(m2_since_tap["high"].max()) + settings.stop_buffer
        risk = stop - entry
        side, target = "sell", entry - settings.risk_reward * risk
    if risk <= 0:
        return None
    return Signal(side, round(entry, 2), round(stop, 2), round(target, 2), setup.id, session)


def evaluate(
    h4: pd.DataFrame,
    m15: pd.DataFrame,
    m2: pd.DataFrame,
    now: pd.Timestamp,
    settings: Settings,
) -> Decision:
    """Decide whether to enter on the 2M candle that just closed.

    All frames must contain closed candles only.
    """
    if h4.empty or m15.empty or m2.empty:
        return Decision(None, "not enough candle data")

    session = active_session(now, settings.sessions, settings.session_timezone)
    if session is None:
        return Decision(None, "outside trading sessions")

    bias = trend_bias(h4, settings)
    if bias is None:
        return Decision(None, "no clear 4H trend")

    setups = find_fvgs(m15.iloc[-settings.setup_lookback_bars :], settings.setup_fvg_min_size, bias)
    if not setups:
        return Decision(None, f"4H {bias}: no 15M {bias} FVG")

    last_bar = m2.index[-1]
    waiting = 0
    for setup in reversed(setups):  # newest setup first
        after = m2[m2.index >= setup.confirmed_at + M15]
        tap = first_touch(setup, after)
        if tap is None:
            continue
        if is_invalidated(setup, after):
            continue
        since_tap = after[after.index >= tap]
        if len(since_tap) > settings.max_entry_bars_after_tap:
            continue
        waiting += 1
        triggers = find_fvgs(since_tap, settings.entry_fvg_min_size, bias)
        if not triggers or triggers[-1].confirmed_at != last_bar:
            continue
        signal = build_signal(setup, since_tap, settings, session)
        if signal is None:
            continue
        if signal.risk_per_unit < settings.min_stop_distance:
            return Decision(None, f"stop too tight ({signal.risk_per_unit:.2f})")
        risk_usd = signal.risk_per_unit * settings.contract_size * settings.lot_size
        if risk_usd > settings.max_risk_usd:
            return Decision(None, f"stop too wide (${risk_usd:.2f} > ${settings.max_risk_usd:.2f})")
        return Decision(signal, f"4H {bias} + 15M FVG tap + 2M FVG confirmation")

    if waiting:
        return Decision(None, f"4H {bias}: 15M FVG tapped, waiting for 2M confirmation")
    return Decision(None, f"4H {bias}: waiting for price to reach a 15M FVG")
