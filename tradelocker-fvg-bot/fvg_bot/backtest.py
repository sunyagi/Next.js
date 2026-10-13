"""Replay the strategy over historical 1-minute XAUUSD candles.

    python -m fvg_bot.backtest data/XAUUSD_M1.csv --config config.yaml --trades trades.csv

The CSV needs a timestamp column (time/datetime/date/timestamp) and
open/high/low/close columns. Prices are assumed to be bid prices; buys pay
`--spread` on entry. If a 2M candle touches both the stop and the target, the
backtest assumes the stop was hit first (conservative).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .config import Settings
from .indicators import resample_ohlc
from .risk import RiskManager
from .sessions import active_session
from .strategy import evaluate

H4 = pd.Timedelta(hours=4)
M15 = pd.Timedelta(minutes=15)
M2 = pd.Timedelta(minutes=2)


@dataclass
class Trade:
    side: str
    session: str
    entry_time: pd.Timestamp
    entry: float
    stop_loss: float
    take_profit: float
    exit_time: pd.Timestamp | None = None
    exit: float | None = None
    pnl: float = 0.0
    result: str = ""


def load_csv(path: str, tz: str = "UTC") -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    time_col = next(c for c in ("time", "datetime", "date", "timestamp", "gmt time") if c in df.columns)
    stamps = pd.to_datetime(df[time_col])
    stamps = stamps.dt.tz_localize(tz) if stamps.dt.tz is None else stamps
    out = df[["open", "high", "low", "close"]].astype(float)
    out.index = stamps.dt.tz_convert("UTC")
    return out.sort_index()


def run_backtest(m1: pd.DataFrame, settings: Settings, spread: float = 0.30) -> list[Trade]:
    h4 = resample_ohlc(m1, "4h")
    m15 = resample_ohlc(m1, "15min")
    m2 = resample_ohlc(m1, "2min")

    h4_close = h4.index + H4
    m15_close = m15.index + M15
    h4_window = settings.trend_ema_period * 3
    m2_window = settings.setup_lookback_bars * 8 + settings.max_entry_bars_after_tap

    risk = RiskManager(settings)
    balance = settings.account_size
    units = settings.contract_size * settings.lot_size
    trades: list[Trade] = []
    open_trade: Trade | None = None

    highs, lows = m2["high"].to_numpy(), m2["low"].to_numpy()
    for i in range(len(m2)):
        now = m2.index[i] + M2

        if open_trade is not None:
            buy = open_trade.side == "buy"
            hit_sl = lows[i] <= open_trade.stop_loss if buy else highs[i] + spread >= open_trade.stop_loss
            hit_tp = highs[i] >= open_trade.take_profit if buy else lows[i] + spread <= open_trade.take_profit
            if hit_sl or hit_tp:
                exit_price = open_trade.stop_loss if hit_sl else open_trade.take_profit
                direction = 1 if buy else -1
                open_trade.exit_time, open_trade.exit = now, exit_price
                open_trade.pnl = round(direction * (exit_price - open_trade.entry) * units, 2)
                open_trade.result = "loss" if hit_sl else "win"
                balance += open_trade.pnl
                open_trade = None
            continue

        if active_session(now, settings.sessions, settings.session_timezone) is None:
            continue

        n_h4 = h4_close.searchsorted(now, side="right")
        n_m15 = m15_close.searchsorted(now, side="right")
        decision = evaluate(
            h4.iloc[max(0, n_h4 - h4_window) : n_h4],
            m15.iloc[max(0, n_m15 - settings.setup_lookback_bars) : n_m15],
            m2.iloc[max(0, i + 1 - m2_window) : i + 1],
            now,
            settings,
        )
        signal = decision.signal
        if signal is None:
            continue
        ok, _ = risk.can_trade(now, balance, signal.setup_id)
        if not ok:
            continue

        # Same re-anchoring as the live bot: fill on the right side of the spread.
        entry = signal.entry + spread if signal.side == "buy" else signal.entry
        stop_distance = abs(entry - signal.stop_loss)
        if stop_distance * units > settings.max_risk_usd:
            continue
        direction = 1 if signal.side == "buy" else -1
        target = entry + direction * settings.risk_reward * stop_distance
        open_trade = Trade(signal.side, signal.session, now, round(entry, 2), signal.stop_loss, round(target, 2))
        trades.append(open_trade)
        risk.record_trade(signal.setup_id)

    if open_trade is not None:  # still running at the end of the data
        trades.pop()
    return trades


def summarize(trades: list[Trade], settings: Settings) -> str:
    if not trades:
        return "No trades."
    pnl = np.array([t.pnl for t in trades])
    wins = int((pnl > 0).sum())
    curve = np.concatenate([[settings.account_size], settings.account_size + np.cumsum(pnl)])
    drawdown = float((np.maximum.accumulate(curve) - curve).max())
    by_session = pd.Series([t.session for t in trades]).value_counts().to_dict()
    gross_win, gross_loss = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    lines = [
        f"Trades:         {len(trades)}  {by_session}",
        f"Win rate:       {wins / len(trades):.1%}  ({wins}W / {len(trades) - wins}L)",
        f"Net P/L:        ${pnl.sum():.2f}",
        f"Profit factor:  {gross_win / gross_loss:.2f}" if gross_loss else "Profit factor:  inf",
        f"Max drawdown:   ${drawdown:.2f}",
        f"Final balance:  ${curve[-1]:.2f}  (start ${settings.account_size:.2f})",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the FVG strategy on 1-minute candles")
    parser.add_argument("csv", help="1-minute OHLC CSV")
    parser.add_argument("--config", default=None)
    parser.add_argument("--tz", default="UTC", help="timezone of the CSV timestamps")
    parser.add_argument("--spread", type=float, default=0.30, help="spread in $ (price units)")
    parser.add_argument("--trades", default=None, help="write the trade list to this CSV")
    args = parser.parse_args()

    settings = Settings.load(args.config)
    trades = run_backtest(load_csv(args.csv, args.tz), settings, args.spread)
    print(summarize(trades, settings))
    if args.trades and trades:
        pd.DataFrame([asdict(t) for t in trades]).to_csv(args.trades, index=False)
        print(f"Trade list written to {args.trades}")


if __name__ == "__main__":
    main()
