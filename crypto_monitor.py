"""
Polymarket 1h Crypto Up/Down Monitor v4 (Multi-Slot)
====================================================
- Parses upcoming_markets.txt
- Trades up to 2 active slots simultaneously (8 trades total)
- REST API → picks more expensive side (YES vs NO)
- $30 simulated BUY, limit SELL at entry + $0.05
- WebSocket monitors all active tokens
- SQLite logging (trade_logger.py)
- Telegram alerts (notifier.py)
- Resolution: limit_hit (success) or slot_expired (wipeout)
"""

import websocket
import json
import threading
import time
import re
import sys
import requests as http_requests
from datetime import datetime, timezone, timedelta
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import trade_logger as db
import notifier as tg
import market_fetcher as fetcher

# ─── Constants ──────────────────────────────────────────────────────
EST = timezone(timedelta(hours=-5))
MARKETS_FILE = Path(__file__).parent / "upcoming_markets.txt"
CLOB_PRICE_URL = "https://clob.polymarket.com/price"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
TRADE_AMOUNT = 30.0
LIMIT_OFFSET = 0.05
CRYPTOS = ["BTC", "ETH", "SOL", "XRP"]
WINDOW_SIZE = 5  # Increased queue size
MAX_CONCURRENT_SLOTS = 2  # Trade 2 slots at once

# ─── Colors ─────────────────────────────────────────────────────────
CYAN   = "\033[96m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
MAGENTA= "\033[95m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ─── Parse upcoming_markets.txt ─────────────────────────────────────

def parse_markets_file(filepath):
    """Parse the pasteable markets file into a list of slot dicts."""
    text = filepath.read_text(encoding="utf-8")
    slots = []
    slot_blocks = re.split(r"🕒\s*Slot:\s*", text)

    for block in slot_blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split("\n")
        label = lines[0].strip()

        # Parse full datetime: "2026-02-20 05:00 AM EST"
        dt_match = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\s*(AM|PM)\s*EST", label)
        if not dt_match:
            continue
        date_str = dt_match.group(1)
        hour = int(dt_match.group(2))
        minute = int(dt_match.group(3))
        ampm = dt_match.group(4)
        if ampm == "AM" and hour == 12:
            hour = 0
        elif ampm == "PM" and hour != 12:
            hour += 12

        year, month, day = map(int, date_str.split("-"))
        start_dt = datetime(year, month, day, hour, minute, tzinfo=EST)
        end_dt = start_dt + timedelta(hours=1)

        markets = {}
        current_crypto = None

        for line in lines[1:]:
            ls = line.strip()
            crypto_match = re.match(r"(BTC|ETH|SOL|XRP)\s*:", ls)
            if crypto_match:
                current_crypto = crypto_match.group(1)
                markets[current_crypto] = {}
                continue
            yes_match = re.search(r"YES\s*:\s*(\d+)", ls)
            if yes_match and current_crypto:
                markets[current_crypto]["yes"] = yes_match.group(1)
                continue
            no_match = re.search(r"NO\s*:\s*(\d+)", ls)
            if no_match and current_crypto:
                markets[current_crypto]["no"] = no_match.group(1)
                continue

        if len(markets) >= 4 and all(
            "yes" in markets.get(c, {}) and "no" in markets.get(c, {})
            for c in CRYPTOS
        ):
            slots.append({
                "label": label,
                "start_dt": start_dt,
                "end_dt": end_dt,
                "markets": markets,
            })

    slots.sort(key=lambda s: s["start_dt"])
    return slots


# ─── Rolling window ────────────────────────────────────────────────

all_slots = []

def build_slot_queue():
    """Return a deque of upcoming slots (starting strictly in the future)."""
    now = datetime.now(EST)
    upcoming = [s for s in all_slots if s["start_dt"] > now]
    if not upcoming:
        upcoming = all_slots[-WINDOW_SIZE:]
    return deque(upcoming[:WINDOW_SIZE])


def reload_and_rebuild_queue():
    """Re-parse markets file and rebuild the rolling queue."""
    global all_slots
    try:
        all_slots = parse_markets_file(MARKETS_FILE)
        q = build_slot_queue()
        print(f"  {GREEN}✓ Loaded {len(all_slots)} slots, queue has {len(q)}{RESET}")
        return q
    except Exception as e:
        print(f"  {RED}✗ Failed to parse markets: {e}{RESET}")
        return deque()


# ─── REST API price fetch ──────────────────────────────────────────

def fetch_price(token_id, side="BUY"):
    """Fetch BUY price from CLOB for a token."""
    try:
        resp = http_requests.get(
            CLOB_PRICE_URL,
            params={"token_id": token_id, "side": side},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return float(data.get("price", 0))
        return float(data)
    except Exception as e:
        print(f"  {RED}[PRICE ERR] {e}{RESET}")
        return 0.0


# ─── Side selection ─────────────────────────────────────────────────

def select_winning_sides(slot):
    """Pick winning sides for a slot using concurrent price fetches."""
    selections = {}
    print(f"\n  {BOLD}Picking sides for {slot['label']}...{RESET}")
    print(f"  {DIM}{'CRYPTO':<6} {'YES':>10} {'NO':>10}  →  {'Side':>6} {'Entry':>8}{RESET}")

    # Fetch all 8 prices concurrently (4 cryptos × YES + NO)
    price_tasks = []
    for crypto in CRYPTOS:
        price_tasks.append((crypto, "yes", slot["markets"][crypto]["yes"]))
        price_tasks.append((crypto, "no",  slot["markets"][crypto]["no"]))

    fetched = {}  # (crypto, side) -> price
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(fetch_price, tid): (crypto, side)
            for crypto, side, tid in price_tasks
        }
        for fut in futures:
            crypto, side = futures[fut]
            fetched[(crypto, side)] = fut.result()

    for crypto in CRYPTOS:
        yes_price = fetched[(crypto, "yes")]
        no_price  = fetched[(crypto, "no")]
        yes_id = slot["markets"][crypto]["yes"]
        no_id  = slot["markets"][crypto]["no"]

        if yes_price >= no_price:
            winner_side, winner_id, winner_price = "YES", yes_id, yes_price
        else:
            winner_side, winner_id, winner_price = "NO", no_id, no_price

        color = GREEN if winner_side == "YES" else RED
        print(
            f"  {BOLD}{crypto:<6}{RESET}"
            f" ${yes_price:>9.3f}"
            f" ${no_price:>9.3f}"
            f"  →  {color}{winner_side:>6}{RESET}"
            f" ${winner_price:>7.3f}"
        )

        selections[crypto] = {
            "token_id": winner_id,
            "side": winner_side,
            "entry_price": winner_price,
            "yes_price": yes_price,
            "no_price": no_price,
        }
    return selections


# ─── State ──────────────────────────────────────────────────────────

prices = {}          # token_id -> { bid, ask, mid }
token_to_label = {}  # token_id -> "BTC YES"
token_to_trade = {}  # token_id -> trade dict
active_slots = []    # List of active slot dicts
ws_app = None
slot_queue = deque()
_last_tick_print = {}  # token_id -> last print timestamp (throttle)
_ws_msg_count = 0      # Total WS messages received (debug)

# ─── Display ────────────────────────────────────────────────────────

def print_header():
    now_est = datetime.now(EST)
    equity = db.get_current_equity()
    print()
    print(f"{BOLD}{CYAN}══════════════════════════════════════════════════════════════════════════{RESET}")
    slot_labels = " & ".join([s['label'].split(' ')[-3] + s['label'].split(' ')[-2] for s in active_slots]) if active_slots else "None"
    print(f"  {BOLD}Active:{RESET} {YELLOW}{slot_labels}{RESET}   │   {now_est.strftime('%I:%M:%S %p')} EST   │   💰 Equity: {BOLD}${equity:.2f}{RESET}")
    print(f"{BOLD}{CYAN}══════════════════════════════════════════════════════════════════════════{RESET}")


# ─── WebSocket callbacks ────────────────────────────────────────────

def send_subscribe(token_ids):
    """Send WS subscribe op for specific tokens."""
    if not ws_app or not ws_app.sock or not ws_app.sock.connected or not token_ids:
        return
    payload = {
        "operation": "subscribe",
        "assets_ids": token_ids,
    }
    try:
        ws_app.send(json.dumps(payload))
        print(f"  {GREEN}✓ Subscribed to {len(token_ids)} new tokens{RESET}")
    except Exception as e:
        print(f"  {RED}[WS SUB ERR] {e}{RESET}")

def send_unsubscribe(token_ids):
    """Send WS unsubscribe op for specific tokens."""
    if not ws_app or not ws_app.sock or not ws_app.sock.connected or not token_ids:
        return
    payload = {
        "operation": "unsubscribe",
        "assets_ids": token_ids,
    }
    try:
        ws_app.send(json.dumps(payload))
        print(f"  {YELLOW}✓ Unsubscribed from {len(token_ids)} expired tokens{RESET}")
    except Exception as e:
        print(f"  {RED}[WS UNSUB ERR] {e}{RESET}")


def on_message(ws, message):
    global _ws_msg_count
    try:
        data = json.loads(message)
    except (json.JSONDecodeError, ValueError):
        return

    items = data if isinstance(data, list) else [data]

    for item in items:
        _ws_msg_count += 1

        # First message debug
        if _ws_msg_count == 1:
            event = item.get('event_type', item.get('type', '?'))
            print(f"  {GREEN}[WS] First message received (event_type={event}){RESET}")

        if item.get("event_type") != "best_bid_ask":
            continue

        token_id = item.get("asset_id", "")
        if token_id not in token_to_label:
            continue

        bid = float(item.get("best_bid", 0))
        ask = float(item.get("best_ask", 0))
        mid = (bid + ask) / 2
        prices[token_id] = {"bid": bid, "ask": ask, "mid": mid}

        label = token_to_label[token_id]
        crypto, side = label.split()
        trade = token_to_trade.get(token_id)

        # Throttled tick printing (1 per token per 5 seconds)
        now = time.time()
        last = _last_tick_print.get(token_id, 0)
        if now - last >= 5:
            _last_tick_print[token_id] = now
            spread = ask - bid
            print(f"  {DIM}[TICK]{RESET} {crypto} {side}: ${mid:.3f} (bid=${bid:.3f} ask=${ask:.3f} spread={spread:.4f})")

        # Log tick
        if trade:
            db.record_tick(trade["trade_id"], bid, ask)

            # Check Limit Logic
            if bid >= trade["limit_sell"] and not trade["closed"]:
                trade["closed"] = True
                result = db.close_trade(trade["trade_id"], bid, "limit_hit")
                if result:
                    tg.notify_limit_hit(
                        trade["crypto"], trade["side"], bid,
                        result["pnl_usd"], result["pnl_pct"],
                        result["fill_latency_sec"], result["equity_after"]
                    )
                    print(f"  {GREEN}✅ LIMIT HIT: {crypto} {side} @ ${bid:.3f} (+${result['pnl_usd']:.2f}){RESET}")

                # Unsubscribe completed token immediately
                send_unsubscribe([token_id])
                token_to_trade.pop(token_id, None)
                token_to_label.pop(token_id, None)
                _last_tick_print.pop(token_id, None)
                print(f"  {YELLOW}↳ Unsubscribed {crypto} {side} (trade done){RESET}")
                break  # token removed from maps, stop processing this item


def on_error(ws, error):
    err_str = str(error)
    if "Expecting value" in err_str or "JSONDecode" in err_str:
        return
    print(f"\n{RED}[WS ERROR]{RESET} {error}")


def on_close(ws, close_status_code, close_msg):
    print(f"\n{YELLOW}[WS CLOSED]{RESET} code={close_status_code} msg={close_msg}")
    print(f"  {YELLOW}Will reconnect in 3 seconds...{RESET}")


_bg_threads_started = False

def on_open(ws):
    global _bg_threads_started
    
    # Always re-subscribe all active tokens (handles initial + reconnect)
    token_ids = list(token_to_label.keys())
    if token_ids:
        payload = {
            "assets_ids": token_ids,
            "type": "market",
            "initial_dump": True,
            "custom_feature_enabled": True,
        }
        ws.send(json.dumps(payload))
        print(f"  {GREEN}✓ WS connected — subscribed to {len(token_ids)} tokens{RESET}")
    else:
        print(f"  {YELLOW}⚠ WS connected but no tokens to subscribe{RESET}")
    
    print_header()
    
    # Start background threads only once (they survive WS reconnects as daemon threads)
    if not _bg_threads_started:
        _bg_threads_started = True
        threading.Thread(target=slot_watcher_thread, daemon=True).start()
        fetcher.start_fetcher()
        print(f"  {GREEN}✓ Background threads started (slot watcher + fetcher){RESET}")
    else:
        print(f"  {GREEN}✓ WS reconnected — background threads still alive{RESET}")
    
    def ping_loop():
        while True:
            time.sleep(10)
            try:
                ws.send(json.dumps({"type": "ping"}))
            except Exception:
                break
    threading.Thread(target=ping_loop, daemon=True).start()


# ─── Slot Management ────────────────────────────────────────────────

def activate_slot_trades(slot):
    """Log trades for a specific slot and return list of token_ids."""
    selections = select_winning_sides(slot)
    equity = db.get_current_equity()
    
    print(f"\n  {MAGENTA}Opening trades for {slot['label']}{RESET}")
    
    added_tokens = []
    
    for crypto in CRYPTOS:
        sel = selections[crypto]
        entry = sel["entry_price"]
        side = sel["side"]
        token = sel["token_id"]

        if entry <= 0:
            continue

        shares = TRADE_AMOUNT / entry
        limit_sell = entry + LIMIT_OFFSET

        trade_id = db.open_trade(
            slot_label=slot["label"],
            asset=crypto,
            side_chosen=side,
            token_id=token,
            entry_price=entry,
            yes_price=sel["yes_price"],
            no_price=sel["no_price"],
            shares=shares,
            limit_sell_price=limit_sell,
        )

        tg.notify_trade_opened(crypto, side, entry, shares, limit_sell, equity, slot["label"])
        tg.notify_limit_sell_placed(crypto, side, limit_sell, entry)

        print(f"  {GREEN}+ OPEN:{RESET} {crypto} {side} @ ${entry:.3f} (ID: {trade_id})")

        token_to_label[token] = f"{crypto} {side}"
        token_to_trade[token] = {
            "trade_id": trade_id,
            "crypto": crypto,
            "side": side,
            "entry_price": entry,
            "limit_sell": limit_sell,
            "shares": shares,
            "slot_label": slot["label"],
            "closed": False,
        }
        added_tokens.append(token)
        
    if added_tokens:
        send_subscribe(added_tokens)
        
    return added_tokens


def close_slot_trades(slot):
    """Close all pending trades for the specified slot."""
    print(f"\n{YELLOW}Closing trades for expired slot: {slot['label']}{RESET}")
    
    # Identify tokens to remove
    tokens_to_remove = []
    results = []
    
    for token, trade in token_to_trade.items():
        if trade["slot_label"] != slot["label"]:
            continue
            
        tokens_to_remove.append(token)
        if trade["closed"]:
            continue
            
        trade["closed"] = True
        last_bid = prices.get(token, {}).get("bid", trade["entry_price"])
        
        result = db.close_trade(trade["trade_id"], last_bid, "slot_expired")
        if result:
            results.append(result)
            print(f"  {RED}x EXPIRED:{RESET} {trade['crypto']} {trade['side']} P&L: ${result['pnl_usd']:.2f}")

    # Notify summary
    if results:
        equity = db.get_current_equity()
        tg.notify_slot_summary(slot["label"], results, equity)

    # Cleanup maps
    for t in tokens_to_remove:
        token_to_trade.pop(t, None)
        token_to_label.pop(t, None)
        
    if tokens_to_remove:
        send_unsubscribe(tokens_to_remove)


def maintain_active_slots():
    """Ensure we have filled up to MAX_CONCURRENT_SLOTS."""
    if not slot_queue:
        new_q = reload_and_rebuild_queue()
        if new_q:
            slot_queue.extend(new_q)
            
    added = False
    now = datetime.now(EST)
    
    while len(active_slots) < MAX_CONCURRENT_SLOTS and slot_queue:
        next_slot = slot_queue.popleft()
        # Skip slots that have already ended
        if next_slot["end_dt"] <= now:
            print(f"  {DIM}Skipping expired slot: {next_slot['label']}{RESET}")
            continue
             
        active_slots.append(next_slot)
        activate_slot_trades(next_slot)
        added = True
        
    if added:
        print_header()


def slot_watcher_thread():
    """Check for expirations and refill slots every 5 seconds. Never dies."""
    while True:
        try:
            time.sleep(5)
            now = datetime.now(EST)
            
            expired_indices = []
            for i, slot in enumerate(active_slots):
                if now >= slot["end_dt"]:
                    print(f"\n  {YELLOW}⏰ Slot expired: {slot['label']} (end_dt={slot['end_dt'].strftime('%I:%M %p')}){RESET}")
                    try:
                        close_slot_trades(slot)
                    except Exception as e:
                        print(f"  {RED}[CLOSE ERR] {e}{RESET}")
                    expired_indices.append(i)
                    
            if expired_indices:
                for i in reversed(expired_indices):
                    del active_slots[i]
                
                try:
                    maintain_active_slots()
                except Exception as e:
                    print(f"  {RED}[REFILL ERR] {e}{RESET}")
        except Exception as e:
            print(f"  {RED}[SLOT WATCHER ERR] {e}{RESET}")
            time.sleep(5)  # Don't spin on repeated errors


# ─── Main ───────────────────────────────────────────────────────────

def main():
    global ws_app, slot_queue

    print(f"\n{BOLD}{CYAN}Polymarket Multi-Slot Monitor v4{RESET}")
    db.init_db()

    # ── Step 1: Clear old slots and fetch fresh ──────────────────────
    print(f"\n  {CYAN}[STARTUP] Clearing old slots...{RESET}")
    if MARKETS_FILE.exists():
        MARKETS_FILE.unlink()

    fetcher.discover_and_append()

    if not MARKETS_FILE.exists():
        print(f"  {RED}[ERROR] No markets found after fresh fetch. Exiting.{RESET}")
        sys.exit(1)

    slot_queue = reload_and_rebuild_queue()
    print(f"  {GREEN}✓ Fresh queue built: {len(slot_queue)} upcoming slots{RESET}")

    # ── Step 2: Open trades for up to 2 slots ────────────────────────
    print(f"\n  {CYAN}[STARTUP] Opening trades...{RESET}")
    maintain_active_slots()
    print(f"  {GREEN}✓ {len(active_slots)} active slot(s), {len(token_to_label)} tokens ready{RESET}")

    # ── Step 3: Start Telegram bot (non-blocking) ────────────────────
    tg.start_bot_polling()

    # ── Step 4: Connect WebSocket ────────────────────────────────────
    # Background threads start AFTER WS connects (in on_open)
    print(f"\n  {CYAN}[STARTUP] Connecting WebSocket...{RESET}")
    while True:
        try:
            ws_app = websocket.WebSocketApp(
                WS_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws_app.run_forever()
            # If run_forever returns, WS disconnected
            print(f"\n  {YELLOW}[WS] run_forever() returned — reconnecting in 3s...{RESET}")
            time.sleep(3)
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Exiting...{RESET}")
            sys.exit(0)
        except Exception as e:
            print(f"  {RED}[WS RECONNECT] {e}{RESET}")
            time.sleep(3)

if __name__ == "__main__":
    main()
