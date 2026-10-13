"""Thin wrapper around the official `tradelocker` Python client (TLAPI)."""

from __future__ import annotations

import logging

import pandas as pd
from tradelocker import TLAPI

from .config import Credentials, Settings

log = logging.getLogger(__name__)


class TradeLockerBroker:
    def __init__(self, creds: Credentials, settings: Settings):
        self.settings = settings
        self.api = TLAPI(
            environment=creds.environment,
            username=creds.email,
            password=creds.password,
            server=creds.server,
            acc_num=creds.acc_num,
            log_level="info",
        )
        self.instrument_id = self.api.get_instrument_id_from_symbol_name(settings.symbol)
        log.info("Connected. %s instrument id = %s", settings.symbol, self.instrument_id)

    def candles(self, resolution: str, lookback: str) -> pd.DataFrame:
        """OHLC candles indexed by UTC open time. TradeLocker resolutions:
        1m, 5m, 15m, 30m, 1H, 4H, 1D (there is no 2m; the bot builds it from 1m)."""
        raw = self.api.get_price_history(
            self.instrument_id, resolution=resolution, lookback_period=lookback
        )
        df = pd.DataFrame(
            {
                "open": raw["o"].astype(float).to_numpy(),
                "high": raw["h"].astype(float).to_numpy(),
                "low": raw["l"].astype(float).to_numpy(),
                "close": raw["c"].astype(float).to_numpy(),
            },
            index=pd.to_datetime(raw["t"].astype("int64"), unit="ms", utc=True),
        )
        return df.sort_index()

    def balance(self) -> float:
        accounts = self.api.get_all_accounts()
        row = accounts[accounts["accNum"] == self.api.acc_num]
        return float(row["accountBalance"].iloc[0])

    def has_open_position(self) -> bool:
        positions = self.api.get_all_positions()
        if positions.empty:
            return False
        return bool((positions["tradableInstrumentId"] == self.instrument_id).any())

    def quote(self, side: str) -> float:
        if side == "buy":
            return self.api.get_latest_asking_price(self.instrument_id)
        return self.api.get_latest_bid_price(self.instrument_id)

    def market_order(self, side: str, stop_loss: float, take_profit: float) -> int | None:
        return self.api.create_order(
            self.instrument_id,
            quantity=self.settings.lot_size,
            side=side,
            type_="market",
            stop_loss=stop_loss,
            stop_loss_type="absolute",
            take_profit=take_profit,
            take_profit_type="absolute",
        )
