# Crystal Perigee — Polymarket 1h Crypto Quant Engine

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start the monitor (runs trades + logs + Telegram alerts)
python crypto_monitor.py

# In a separate terminal, start the dashboard
streamlit run dashboard.py
```

## Architecture

| File | Purpose |
|---|---|
| `crypto_monitor.py` | Main bot: market parsing, side selection, WebSocket monitoring, trade execution |
| `trade_logger.py` | SQLite database: 30+ columns per trade, tick recording, excursion tracking |
| `notifier.py` | Telegram alerts: trade open, limit sell hit, wipeout, slot summary |
| `dashboard.py` | Streamlit analytics: equity curve, asset beta, hourly heatmap, excursion analysis |
| `upcoming_markets.txt` | Paste your Polymarket market token IDs here |
| `trades.db` | Auto-created SQLite database (don't delete!) |

## How It Works

1. **Parses** `upcoming_markets.txt` for token IDs
2. **Rolling 3-slot queue** — always monitors the next 3 hours
3. **REST API** checks YES and NO prices → picks the more expensive side
4. **Simulates** a $30 BUY at entry price, places a limit SELL at entry + $0.05
5. **WebSocket** monitors only the 4 winning-side tokens
6. **Resolution**: `limit_hit` (bid reaches target → ✅ win) or `slot_expired` (hour ends → 🔴 wipeout)
7. All trades logged to SQLite with full quant DNA

## Telegram Setup

1. Open Telegram → search `@BotFather` → `/newbot` → get your token
2. Token is already configured in `notifier.py`
3. **Send `/start` to your bot** (this is required for auto chat_id detection)
4. Run the monitor — it will auto-detect your chat_id

## Adding New Markets

Paste new slots into `upcoming_markets.txt` in this format:

```
🕒 Slot: 2026-02-20 10:00 AM EST
   BTC: https://polymarket.com/event/...
        ✅ YES: <token_id>
        ❌ NO : <token_id>
   ETH: ...
   SOL: ...
   XRP: ...
```

The bot reloads the file when the queue runs empty.

## Dashboard

The Streamlit dashboard shows:
- **Equity curve** (starting at $1,000)
- **Asset beta** (BTC vs ETH vs SOL vs XRP performance)
- **Hourly heatmap** (which hours are profitable?)
- **Excursion analysis** (adverse & favorable)
- **Spread vs outcome** (does wide spread = loss?)
- **Fill latency** distribution
- **Full trade log** with filters
- **Tick replay** chart for any individual trade
