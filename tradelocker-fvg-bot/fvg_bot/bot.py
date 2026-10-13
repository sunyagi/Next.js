"""Live trading loop for TradeLocker.

    python -m fvg_bot.bot --config config.yaml          # dry run (logs signals only)
    python -m fvg_bot.bot --config config.yaml --live   # sends real orders
"""

from __future__ import annotations

import argparse
import logging
import time

import pandas as pd

from .broker import TradeLockerBroker
from .config import Credentials, Settings
from .indicators import closed_bars, resample_ohlc
from .risk import RiskManager
from .sessions import active_session
from .strategy import Signal, evaluate

log = logging.getLogger("fvg_bot")

H4 = pd.Timedelta(hours=4)
M15 = pd.Timedelta(minutes=15)
M2 = pd.Timedelta(minutes=2)
M1 = pd.Timedelta(minutes=1)


class Bot:
    def __init__(self, broker: TradeLockerBroker, settings: Settings):
        self.broker = broker
        self.settings = settings
        self.risk = RiskManager(settings)
        self.last_reason = ""

    def fetch(self, now: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        h4 = closed_bars(self.broker.candles("4H", "60D"), H4, now)
        m15 = closed_bars(self.broker.candles("15m", "3D"), M15, now)
        m1 = closed_bars(self.broker.candles("1m", "1D"), M1, now)
        m2 = closed_bars(resample_ohlc(m1, "2min"), M2, now)
        return h4, m15, m2

    def tick(self) -> None:
        now = pd.Timestamp.now(tz="UTC")
        if active_session(now, self.settings.sessions, self.settings.session_timezone) is None:
            self._log_once("outside trading sessions")
            return
        if self.settings.one_position_at_a_time and self.broker.has_open_position():
            self._log_once("position open, managing via SL/TP")
            return

        decision = evaluate(*self.fetch(now), now, self.settings)
        self._log_once(decision.reason)
        if decision.signal is None:
            return

        balance = self.broker.balance()
        ok, why = self.risk.can_trade(now, balance, decision.signal.setup_id)
        if not ok:
            log.info("Signal skipped: %s", why)
            return
        self.execute(decision.signal)

    def execute(self, signal: Signal) -> None:
        # Re-anchor the target on the real fill side of the spread so the trade stays 2R.
        price = self.broker.quote(signal.side)
        risk = abs(price - signal.stop_loss)
        wrong_side = (signal.side == "buy" and price <= signal.stop_loss) or (
            signal.side == "sell" and price >= signal.stop_loss
        )
        risk_usd = risk * self.settings.contract_size * self.settings.lot_size
        if wrong_side or risk < self.settings.min_stop_distance or risk_usd > self.settings.max_risk_usd:
            log.info("Signal skipped at live price %.2f (risk %.2f / $%.2f)", price, risk, risk_usd)
            return
        direction = 1 if signal.side == "buy" else -1
        take_profit = round(price + direction * self.settings.risk_reward * risk, 2)

        log.info(
            "%s %s %.2f lot @ ~%.2f  SL %.2f  TP %.2f  (risk $%.2f, reward $%.2f, session %s)",
            "DRY-RUN" if self.settings.dry_run else "ORDER",
            signal.side.upper(),
            self.settings.lot_size,
            price,
            signal.stop_loss,
            take_profit,
            risk_usd,
            risk_usd * self.settings.risk_reward,
            signal.session,
        )
        if not self.settings.dry_run:
            order_id = self.broker.market_order(signal.side, signal.stop_loss, take_profit)
            if order_id is None:
                log.error("Order was not accepted by the broker")
                return
            log.info("Order placed, id=%s", order_id)
        self.risk.record_trade(signal.setup_id)

    def _log_once(self, reason: str) -> None:
        if reason != self.last_reason:
            log.info(reason)
            self.last_reason = reason

    def run(self) -> None:
        log.info("Bot started (%s)", "DRY RUN" if self.settings.dry_run else "LIVE")
        while True:
            # Wake a few seconds after each 2-minute candle closes.
            now = time.time()
            next_close = (now // 120 + 1) * 120
            time.sleep(next_close - now + self.settings.poll_seconds)
            try:
                self.tick()
            except Exception:  # keep running through network blips / API errors
                log.exception("Tick failed")


def main() -> None:
    parser = argparse.ArgumentParser(description="TradeLocker XAUUSD FVG bot")
    parser.add_argument("--config", default=None, help="YAML settings file")
    parser.add_argument("--live", action="store_true", help="send real orders (default: dry run)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load(args.config)
    settings.dry_run = not args.live
    broker = TradeLockerBroker(Credentials.from_env(), settings)
    Bot(broker, settings).run()


if __name__ == "__main__":
    main()
