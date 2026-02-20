"""
notifier.py — Telegram trade alerts
====================================
Sends notifications on trade events via Telegram Bot API.
"""

import requests
import threading
from datetime import datetime, timezone, timedelta

EST = timezone(timedelta(hours=-5))

# Telegram config — set these directly or via env vars
TELEGRAM_BOT_TOKEN = "8342461738:AAETm6yWToExxsCans1IHzIMeD8WEflDHB0"
TELEGRAM_CHAT_ID = None  # Will be auto-detected on first /start

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _get_chat_id():
    """Auto-detect chat_id from the most recent message to the bot."""
    global TELEGRAM_CHAT_ID
    if TELEGRAM_CHAT_ID:
        return TELEGRAM_CHAT_ID
    try:
        resp = requests.get(f"{TELEGRAM_API}/getUpdates", timeout=5)
        data = resp.json()
        if data.get("ok") and data.get("result"):
            # Get the most recent chat
            for update in reversed(data["result"]):
                msg = update.get("message") or update.get("channel_post")
                if msg:
                    TELEGRAM_CHAT_ID = msg["chat"]["id"]
                    print(f"  \033[95m[TG]\033[0m Auto-detected chat_id: {TELEGRAM_CHAT_ID}")
                    return TELEGRAM_CHAT_ID
        print("  \033[93m[TG]\033[0m No chat_id found. Send /start to your bot first!")
    except Exception as e:
        print(f"  \033[91m[TG ERR]\033[0m {e}")
    return None


def send_message(text, parse_mode="HTML"):
    """Send a message via Telegram (non-blocking)."""
    def _send():
        chat_id = _get_chat_id()
        if not chat_id:
            return
        try:
            requests.post(
                f"{TELEGRAM_API}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
                timeout=10,
            )
        except Exception as e:
            print(f"  \033[91m[TG ERR]\033[0m {e}")

    threading.Thread(target=_send, daemon=True).start()


# ─── Notification templates ─────────────────────────────────────────

def notify_trade_opened(asset, side, entry_price, shares, limit_sell, equity, slot_label):
    """Notify when a trade is opened."""
    text = (
        f"🟢 <b>TRADE OPENED</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>{asset}</b> {side} @ <b>${entry_price:.3f}</b>\n"
        f"Shares: {shares:.1f} | Amount: $30.00\n"
        f"🎯 Limit Sell: <b>${limit_sell:.3f}</b> (+$0.05)\n"
        f"📅 Slot: {slot_label}\n"
        f"💰 Equity: <b>${equity:.2f}</b>"
    )
    send_message(text)


def notify_limit_sell_placed(asset, side, limit_price, entry_price):
    """Notify when limit sell order is placed."""
    text = (
        f"📋 <b>LIMIT SELL PLACED</b>\n"
        f"<b>{asset}</b> {side}\n"
        f"Entry: ${entry_price:.3f} → Target: <b>${limit_price:.3f}</b>"
    )
    send_message(text)


def notify_limit_hit(asset, side, exit_price, pnl_usd, pnl_pct, latency_sec, equity):
    """Notify when limit sell is hit (SUCCESS)."""
    mins = int(latency_sec // 60)
    secs = int(latency_sec % 60)
    text = (
        f"🎯 <b>LIMIT SELL HIT!</b> ✅\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>{asset}</b> {side} @ <b>${exit_price:.3f}</b>\n"
        f"P&L: <b>${pnl_usd:+.2f}</b> ({pnl_pct:+.1f}%)\n"
        f"⏱ Fill time: {mins}m {secs}s\n"
        f"💰 Equity: <b>${equity:.2f}</b>"
    )
    send_message(text)


def notify_trade_expired(asset, side, exit_price, pnl_usd, pnl_pct, equity):
    """Notify when a trade wipes out (slot expired)."""
    text = (
        f"🔴 <b>SLOT EXPIRED — WIPEOUT</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>{asset}</b> {side} @ <b>${exit_price:.3f}</b>\n"
        f"P&L: <b>${pnl_usd:+.2f}</b> ({pnl_pct:+.1f}%)\n"
        f"💰 Equity: <b>${equity:.2f}</b>"
    )
    send_message(text)


def notify_slot_summary(slot_label, results, equity):
    """Notify with a summary after a slot completes."""
    wins = sum(1 for r in results if r["outcome"] == "win")
    losses = sum(1 for r in results if r["outcome"] == "loss")
    total_pnl = sum(r["pnl_usd"] for r in results)

    lines = [
        f"📊 <b>SLOT SUMMARY</b>",
        f"━━━━━━━━━━━━━━━━━━",
        f"📅 {slot_label}",
        f"✅ Wins: {wins} | ❌ Losses: {losses}",
        f"💵 Slot P&L: <b>${total_pnl:+.2f}</b>",
        "",
    ]
    for r in results:
        icon = "✅" if r["outcome"] == "win" else "❌"
        lines.append(
            f"{icon} {r.get('asset', '???')}: ${r['pnl_usd']:+.2f} ({r['pnl_pct']:+.1f}%)"
        )
    lines.append(f"\n💰 Equity: <b>${equity:.2f}</b>")

    send_message("\n".join(lines))


# ─── Bot command handler ────────────────────────────────────────────

_last_update_id = 0


def _handle_command(text):
    """Process a Telegram bot command and return the response."""
    cmd = text.strip().lower().split()[0] if text else ""

    try:
        import trade_logger as db
    except ImportError:
        return "⚠️ Database not available."

    if cmd in ("/start", "/help"):
        return (
            "💎 <b>Crystal Perigee Bot</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "/status — Portfolio overview\n"
            "/trades — Active positions\n"
            "/pnl — P&L summary\n"
            "/equity — Equity curve\n"
            "/help — This message"
        )

    elif cmd == "/status":
        stats = db.get_stats()
        equity = stats["equity"]
        pnl = stats["total_pnl"]
        return (
            f"📊 <b>PORTFOLIO STATUS</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Equity: <b>${equity:.2f}</b>\n"
            f"💵 Total P&L: <b>${pnl:+.2f}</b>\n"
            f"📈 Win Rate: <b>{stats['win_rate']:.1f}%</b>\n"
            f"✅ Wins: {stats['wins']} | ❌ Losses: {stats['losses']} | ⏳ Pending: {stats['pending']}\n"
            f"📊 Total Trades: {stats['total_trades']}\n"
            f"📉 Avg Adverse: {stats['avg_adverse']:.1f}%\n"
            f"📈 Avg Favorable: {stats['avg_favorable']:.1f}%"
        )

    elif cmd == "/trades":
        pending = db.get_pending_trades()
        if not pending:
            return "✅ No active trades right now."

        lines = [f"⚡ <b>ACTIVE TRADES ({len(pending)})</b>\n━━━━━━━━━━━━━━━━━━"]
        for t in pending:
            entry = t["entry_price"]
            target = t["limit_sell_price"]
            
            # Get live metrics
            current = db.get_latest_price(t["id"]) or entry
            pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0
            
            ticks = t.get("num_price_updates", 0)
            lines.append(
                f"\n🪙 <b>{t['asset']}</b> {t['side_chosen']} @ ${entry:.3f}\n"
                f"   💵 Current: <b>${current:.3f}</b> ({pnl_pct:+.1f}%)\n"
                f"   🎯 Target: ${target:.3f}\n"
                f"   📊 Ticks: {ticks} | 📅 {t['slot_label']}"
            )
        return "\n".join(lines)

    elif cmd == "/pnl":
        stats = db.get_stats()
        trades = db.get_all_trades()
        resolved = [t for t in trades if t["outcome"] != "pending"]
        last_5 = resolved[-5:] if resolved else []

        lines = [
            f"💵 <b>P&L SUMMARY</b>\n━━━━━━━━━━━━━━━━━━",
            f"💰 Equity: <b>${stats['equity']:.2f}</b>",
            f"Total P&L: <b>${stats['total_pnl']:+.2f}</b>",
            f"Avg P&L/Trade: ${stats['avg_pnl']:.2f}",
            f"Avg Fill Latency: {stats['avg_latency']/60:.1f} min",
            "",
            "<b>Last 5 Trades:</b>",
        ]
        for t in last_5:
            icon = "✅" if t["outcome"] == "win" else "❌"
            lines.append(f"{icon} {t['asset']} {t['side_chosen']}: ${t['pnl_usd']:+.2f} ({t['pnl_pct']:+.1f}%)")

        return "\n".join(lines)

    elif cmd == "/equity":
        stats = db.get_stats()
        equity = stats["equity"]
        pnl = stats["total_pnl"]
        pnl_pct = (pnl / 1000) * 100
        bar = "█" * int(min(max(pnl_pct + 50, 0), 100) / 5) + "░" * (20 - int(min(max(pnl_pct + 50, 0), 100) / 5))
        return (
            f"💰 <b>EQUITY</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"Starting: $1,000.00\n"
            f"Current:  <b>${equity:.2f}</b>\n"
            f"Change:   <b>${pnl:+.2f}</b> ({pnl_pct:+.1f}%)\n"
            f"[{bar}]"
        )

    else:
        return f"❓ Unknown command: {cmd}\nType /help for available commands."


def _poll_commands():
    """Background thread: poll Telegram for bot commands."""
    global _last_update_id
    import time

    while True:
        try:
            resp = requests.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"offset": _last_update_id + 1, "timeout": 10},
                timeout=15,
            )
            data = resp.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    _last_update_id = update["update_id"]
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    chat_id = msg.get("chat", {}).get("id")

                    if chat_id:
                        global TELEGRAM_CHAT_ID
                        if not TELEGRAM_CHAT_ID:
                            TELEGRAM_CHAT_ID = chat_id
                            print(f"  \033[95m[TG]\033[0m Chat ID set: {chat_id}")

                    if text.startswith("/"):
                        response = _handle_command(text)
                        if response and chat_id:
                            try:
                                requests.post(
                                    f"{TELEGRAM_API}/sendMessage",
                                    json={
                                        "chat_id": chat_id,
                                        "text": response,
                                        "parse_mode": "HTML",
                                    },
                                    timeout=10,
                                )
                            except Exception:
                                pass
        except Exception:
            time.sleep(5)


def start_bot_polling():
    """Start the Telegram bot command listener in a background thread."""
    t = threading.Thread(target=_poll_commands, daemon=True)
    t.start()
    print(f"  \033[95m[TG]\033[0m Bot command listener started")

