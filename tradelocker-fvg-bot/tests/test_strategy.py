import numpy as np
import pandas as pd
import pytest

from fvg_bot.config import Settings
from fvg_bot.fvg import BEAR, BULL, find_fvgs, first_touch, is_invalidated
from fvg_bot.risk import RiskManager
from fvg_bot.sessions import active_session
from fvg_bot.strategy import evaluate, trend_bias

NOW = pd.Timestamp("2026-10-14 14:00", tz="UTC")  # 10:00 New York (EDT)


def frame(rows, start, freq):
    idx = pd.date_range(start, periods=len(rows), freq=freq, tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)


def uptrend_h4():
    i = np.arange(120)
    close = 2000 + i * 2 + 6 * np.sin(i / 2)  # rising with pullbacks so swings form
    rows = [(c - 1, c + 2, c - 2, c) for c in close]
    return frame(rows, NOW - pd.Timedelta(hours=4 * 120), "4h")


def m15_with_bull_fvg():
    flat = [(2238, 2240, 2236, 2238)] * 37
    gap = [(2238, 2240, 2236, 2239), (2240, 2251, 2239, 2250), (2250, 2252, 2243, 2250)]
    return frame(flat + gap, NOW - pd.Timedelta(hours=2) - pd.Timedelta(minutes=15 * 40), "15min")


def m2_tap_then_displacement():
    rows = [(2249, 2250, 2247, 2249)] * 40
    rows += [(2249 - k, 2249.5 - k, 2248 - k, 2248.5 - k) for k in range(5)]  # pull back
    rows += [(2244.5, 2245, 2241.5, 2243), (2243, 2244, 2242, 2243.5)]  # tap the 15M gap
    rows += [(2243.5, 2244, 2242.5, 2243.5)] * 10
    rows += [(2243.5, 2244, 2243, 2243.8), (2243.8, 2247, 2243.5, 2246.8), (2246.8, 2247.5, 2245.5, 2247)]
    return frame(rows, NOW - pd.Timedelta(minutes=2 * len(rows)), "2min")


def test_find_bull_and_bear_fvgs():
    df = frame(
        [(10, 11, 9, 10.5), (10.5, 15, 10.4, 14.8), (14.8, 16, 12, 15),
         (15, 15.5, 14, 14.2), (14.2, 14.3, 9, 9.5), (9.5, 13, 8, 9)],
        "2026-01-01", "15min",
    )
    gaps = find_fvgs(df)
    bull = [g for g in gaps if g.direction == BULL]
    bear = [g for g in gaps if g.direction == BEAR]
    assert (bull[0].bottom, bull[0].top) == (11, 12)
    assert (bear[0].bottom, bear[0].top) == (13, 14)
    assert find_fvgs(df, min_size=2) == []


def test_touch_and_invalidation():
    gap = find_fvgs(m15_with_bull_fvg(), direction=BULL)[-1]
    later = frame([(2250, 2251, 2245, 2249), (2249, 2250, 2242, 2244), (2244, 2245, 2238, 2239)],
                  "2026-10-14 12:00", "2min")
    assert first_touch(gap, later) == later.index[1]
    assert not is_invalidated(gap, later.iloc[:2])
    assert is_invalidated(gap, later)  # closed below the gap


def test_sessions_follow_new_york_clock():
    settings = Settings()
    # 12:30 UTC is 08:30 in New York during summer time but 07:30 in winter.
    assert active_session(pd.Timestamp("2026-07-01 12:30", tz="UTC"), settings.sessions, settings.session_timezone) == "new_york"
    assert active_session(pd.Timestamp("2026-01-05 12:30", tz="UTC"), settings.sessions, settings.session_timezone) is None
    assert active_session(pd.Timestamp("2026-07-01 23:30", tz="UTC"), settings.sessions, settings.session_timezone) == "asia"
    assert active_session(pd.Timestamp("2026-07-01 10:00", tz="UTC"), settings.sessions, settings.session_timezone) is None


def test_trend_bias():
    h4 = uptrend_h4()
    assert trend_bias(h4, Settings()) == BULL
    flipped = h4.copy()
    flipped[["open", "close"]] = 4000 - h4[["open", "close"]]
    flipped["high"], flipped["low"] = 4000 - h4["low"], 4000 - h4["high"]
    assert trend_bias(flipped, Settings()) == BEAR


def test_full_long_setup_produces_2r_signal():
    decision = evaluate(uptrend_h4(), m15_with_bull_fvg(), m2_tap_then_displacement(), NOW, Settings())
    signal = decision.signal
    assert signal is not None, decision.reason
    assert signal.side == "buy"
    assert signal.entry == 2247
    assert signal.stop_loss == pytest.approx(2241.2)
    assert signal.take_profit == pytest.approx(signal.entry + 2 * (signal.entry - signal.stop_loss))


def test_no_signal_before_confirmation_or_outside_session():
    m2 = m2_tap_then_displacement()
    waiting = evaluate(uptrend_h4(), m15_with_bull_fvg(), m2.iloc[:-1], NOW - pd.Timedelta(minutes=2), Settings())
    assert waiting.signal is None and "waiting for 2M" in waiting.reason
    late = NOW + pd.Timedelta(hours=8)  # 18:00 New York, between sessions
    assert evaluate(uptrend_h4(), m15_with_bull_fvg(), m2, late, Settings()).signal is None


def test_stop_wider_than_risk_budget_is_skipped():
    settings = Settings(max_risk_pct=2.0)  # $3 on a $150 account; this setup risks $5.80
    decision = evaluate(uptrend_h4(), m15_with_bull_fvg(), m2_tap_then_displacement(), NOW, settings)
    assert decision.signal is None and "too wide" in decision.reason


def test_risk_manager_limits():
    settings = Settings(max_trades_per_day=1)
    rm = RiskManager(settings)
    assert rm.can_trade(NOW, 150, "a")[0]
    rm.record_trade("a")
    assert not rm.can_trade(NOW, 150, "a")[0]
    assert not rm.can_trade(NOW, 150, "b")[0]  # daily cap
    assert rm.can_trade(NOW + pd.Timedelta(days=1), 150, "b")[0]
    assert not rm.can_trade(NOW + pd.Timedelta(days=1), 130, "c")[0]  # -$20 > 10% daily loss
