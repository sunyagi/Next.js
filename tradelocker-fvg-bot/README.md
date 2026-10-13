# TradeLocker XAUUSD FVG Bot

An algorithmic trading bot for **TradeLocker** that trades **XAUUSD (gold)** with a
multi-timeframe **Fair Value Gap (FVG)** strategy during the **Asia** and **New York** sessions.

| Setting | Value |
|---|---|
| Account size | $150 |
| Position size | 0.01 lot (1 oz: every $1 gold moves = $1 P/L) |
| Risk : reward | 1 : 2 |
| Trend | 4H |
| Setup | 15M |
| Entry | 2M (built from 1M candles; TradeLocker has no native 2M feed) |
| Sessions | Asia 19:00–03:00 and New York 08:00–17:00 (New York time, DST-aware) |

## The strategy

1. **4H trend.** The trend is bullish when price is above a rising 50 EMA and the latest swing
   structure shows a higher high or a higher low. Bearish is the mirror image. When neither
   holds, the bot does not trade.
2. **15M setup.** The bot looks for an FVG in the trend direction formed in the last 12 hours.
   For a bullish trend, that means candle 1's high is below candle 3's low. The gap is a
   setup only while no candle has closed through its far side.
3. **2M entry.** Price must first retrace into the 15M gap (the "tap"). Within the next hour, a
   2M FVG then has to form in the trend direction, which shows displacement and a shift back
   toward the trend. The bot enters at market when that 2M candle closes.
4. **Exits.**
   - **Stop loss:** beyond the lowest low (for a buy) or highest high (for a sell) since the
     tap, plus a $0.30 buffer.
   - **Take profit:** the entry price ± 2 × the stop distance.
   - Both are attached to the order on the broker side, so they stay in place if the bot goes
     offline.

**Guard rails:**

- Only one position at a time.
- At most 3 trades per day.
- The bot stops for the day after a $15 loss (10%).
- Each 15M setup is traded only once.
- A setup is skipped when its stop is under $1 away, because the spread would eat it.
- A setup is skipped when its stop would lose more than 5% of the account ($7.50).

### Risk with a $150 account

A fixed 0.01 lot means your dollar risk equals the stop distance in dollars. A $5 stop risks
$5 to make $10. Gold often needs $3–7 stops on these setups, so a single loss costs 2–5% of
the account. The `max_risk_pct` setting caps this. Lowering it gives you fewer but
lower-risk trades.

Check your broker's contract spec. On most brokers, 1.00 lot of XAUUSD is 100 oz. If yours
differs, change `contract_size`.

## Setup

```bash
cd tradelocker-fvg-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # fill in your TradeLocker login
cp config.example.yaml config.yaml
```

## 1. Backtest first

You need 1-minute XAUUSD history as a CSV with these columns:
`time,open,high,low,close`. Exports from Dukascopy, HistData or MT5 work.

```bash
python -m fvg_bot.backtest data/XAUUSD_M1.csv --config config.yaml --tz UTC --spread 0.30 --trades trades.csv
```

The backtest is conservative:

- Buys pay the spread on entry.
- If one 2M candle touches both the stop and the target, the trade counts as a loss.

## 2. Run on a demo account (dry run)

```bash
set -a && source .env && set +a
python -m fvg_bot.bot --config config.yaml
```

In dry-run mode, the bot reads live prices and logs every decision and signal, but does
not place any orders.

## 3. Go live

Point `TL_ENVIRONMENT` at a demo account first. When you're ready:

```bash
python -m fvg_bot.bot --config config.yaml --live
```

The bot checks the market a few seconds after every 2-minute candle closes. Keep it running
on a machine or VPS that stays online.

## Tests

```bash
python -m pytest -q
```

## Project layout

```
fvg_bot/
  config.py      settings (YAML) + credentials (env vars)
  fvg.py         FVG detection, tap and invalidation
  strategy.py    4H trend -> 15M setup -> 2M entry -> Signal (shared by bot and backtest)
  sessions.py    Asia / New York session filter
  risk.py        daily trade/loss limits, one trade per setup
  broker.py      TradeLocker API wrapper (official `tradelocker` package)
  bot.py         live loop
  backtest.py    historical replay on 1-minute data
```

> **Disclaimer:** This is software, not financial advice. Trading leveraged gold CFDs can lose
> money quickly, and this strategy has not been validated on real market data yet. Backtest it
> on several months of real data and run it on a demo account before risking money.
