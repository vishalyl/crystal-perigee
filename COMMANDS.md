# Commands Reference — Polymarket Crypto Monitor

> All commands run in **PowerShell** from the project directory.

---

## 🟢 Cold Start (First Run)

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the monitor
$env:PYTHONUNBUFFERED="1"; python crypto_monitor.py

# 3. In a SECOND terminal — start the dashboard
streamlit run dashboard.py --server.port 8501
```

> **Important:** Always use `$env:PYTHONUNBUFFERED="1"` — without it, output buffers on Windows and looks frozen.

---

## 🔴 Full Wipe (Delete All Records + Fresh Start)

```powershell
# One-liner: kill → wipe → restart
taskkill /F /IM python.exe 2>$null; Start-Sleep 2; Remove-Item -Force trades.db, trades.db-wal, trades.db-shm, upcoming_markets.txt -ErrorAction SilentlyContinue; $env:PYTHONUNBUFFERED="1"; python crypto_monitor.py
```

Or step by step:
```powershell
taskkill /F /IM python.exe 2>$null
Remove-Item -Force trades.db, trades.db-wal, trades.db-shm -ErrorAction SilentlyContinue
Remove-Item -Force upcoming_markets.txt -ErrorAction SilentlyContinue
$env:PYTHONUNBUFFERED="1"; python crypto_monitor.py
```

---

## 🟡 Restart After Error (Keep Existing Trades)

```powershell
taskkill /F /IM python.exe 2>$null
$env:PYTHONUNBUFFERED="1"; python crypto_monitor.py
```

> The monitor auto-clears `upcoming_markets.txt` and re-fetches fresh slots. Your `trades.db` is preserved.

---

## 🔵 Dashboard Only

```powershell
streamlit run dashboard.py --server.port 8501
```

---

## 🛠 Debug Commands

```powershell
# Check if python is running
Get-Process python -ErrorAction SilentlyContinue | Format-Table Id, CPU, WorkingSet64

# View last 20 lines of upcoming_markets.txt
Get-Content upcoming_markets.txt -Tail 20

# View all trades in DB
python -c "import sqlite3; c=sqlite3.connect('trades.db'); [print(r) for r in c.execute('SELECT id, asset, side_chosen, entry_price, exit_price, outcome FROM trades').fetchall()]"

# Count open vs closed trades
python -c "import sqlite3; c=sqlite3.connect('trades.db'); print('Open:', c.execute('SELECT COUNT(*) FROM trades WHERE exit_price IS NULL').fetchone()[0]); print('Closed:', c.execute('SELECT COUNT(*) FROM trades WHERE exit_price IS NOT NULL').fetchone()[0])"

# Test WebSocket connection
python -c "import websocket; ws=websocket.create_connection('wss://ws-subscriptions-clob.polymarket.com/ws/market'); print('Connected!'); ws.close()"

# Fetch markets standalone
python market_fetcher.py
```

---

## 📡 WebSocket Subscribe / Unsubscribe

**Subscribe to new tokens** (done automatically when new slot activates):
```json
{"operation": "subscribe", "assets_ids": ["<token_id>"]}
```

**Unsubscribe from tokens** (done automatically when trade completes or slot expires):
```json
{"operation": "unsubscribe", "assets_ids": ["<token_id>"]}
```

---

## ⚙️ Key Configuration (in `crypto_monitor.py`)

| Constant | Default | Description |
|----------|---------|-------------|
| `MAX_CONCURRENT_SLOTS` | `2` | Trade 2 hourly slots simultaneously |
| `TRADE_AMOUNT` | `$30` | Simulated buy amount per trade |
| `LIMIT_OFFSET` | `$0.05` | Limit sell = entry + offset |
| `WINDOW_SIZE` | `5` | Queue holds up to 5 upcoming slots |

---

## 📊 Telegram Setup

1. Open Telegram → `@BotFather` → `/newbot` → copy token
2. Token is pre-configured in `notifier.py`
3. Send `/start` to your bot (required for chat_id auto-detection)
4. Run the monitor — it auto-detects your chat_id
