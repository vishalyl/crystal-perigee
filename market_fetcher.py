"""
market_fetcher.py — Auto-discover upcoming Polymarket 1h crypto markets
========================================================================
Fetches the next 10 hourly slots from the Gamma API, checks if they're
already in upcoming_markets.txt, and appends any new ones.

Can run standalone:  python market_fetcher.py
Also called from crypto_monitor.py every 1.5 hours as a background task.
"""

import datetime
import json
import re
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from zoneinfo import ZoneInfo

ET_TZ = ZoneInfo("America/New_York")
GAMMA_API_BASE = "https://gamma-api.polymarket.com/markets/slug/"
MARKETS_FILE = Path(__file__).parent / "upcoming_markets.txt"
FETCH_INTERVAL = 3600  # 1 hour in seconds
COUNT = 10

CRYPTOS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "xrp",
}

# Colors
CYAN   = "\033[96m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
MAGENTA= "\033[95m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def get_existing_slot_labels():
    """Read upcoming_markets.txt and return a set of slot labels already present."""
    if not MARKETS_FILE.exists():
        return set()
    text = MARKETS_FILE.read_text(encoding="utf-8")
    # Extract all slot labels like "2026-02-20 01:00 AM EST"
    return set(re.findall(r"🕒\s*Slot:\s*(.+)", text))


def _fetch_single_market(slug, label):
    """Fetch a single market's token IDs from Gamma API."""
    url = f"https://polymarket.com/event/{slug}"
    try:
        resp = requests.get(f"{GAMMA_API_BASE}{slug}", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            tokens = json.loads(data.get("clobTokenIds", "[]"))
            return label, url, tokens[0] if len(tokens) > 0 else "N/A", tokens[1] if len(tokens) > 1 else "N/A"
    except Exception:
        pass
    return label, url, "Error", "Error"


def fetch_upcoming_slots():
    """
    Fetch the next COUNT hourly market slots from the Gamma API.
    Uses ThreadPoolExecutor for concurrent requests (~15s instead of ~400s).
    """
    now_et = datetime.datetime.now(ET_TZ)
    start_hour = now_et.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)

    # Build all (slot_index, crypto_label, slug) tasks
    tasks = []
    slot_meta = []  # (display_time,) per slot
    for i in range(COUNT):
        target_time = start_hour + datetime.timedelta(hours=i)
        month = target_time.strftime("%B").lower()
        day = target_time.day
        hour_num = target_time.strftime("%I").lstrip("0")
        am_pm = target_time.strftime("%p").lower()
        time_slug = f"{month}-{day}-{hour_num}{am_pm}-et"
        display_time = target_time.strftime("%Y-%m-%d %I:00 %p EST")
        slot_meta.append(display_time)

        for crypto_label, slug_name in CRYPTOS.items():
            slug = f"{slug_name}-up-or-down-{time_slug}"
            tasks.append((i, crypto_label, slug))

    # Fire all 40 requests concurrently
    results = {}  # (slot_idx, crypto) -> (label, url, yes, no)
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {
            pool.submit(_fetch_single_market, slug, crypto_label): (idx, crypto_label)
            for idx, crypto_label, slug in tasks
        }
        for future in as_completed(futures):
            idx, crypto_label = futures[future]
            label, url, yes_tok, no_tok = future.result()
            results[(idx, crypto_label)] = {"url": url, "yes": yes_tok, "no": no_tok}

    # Assemble into slot list
    slots = []
    for i in range(COUNT):
        slot = {"label": slot_meta[i], "markets": {}}
        for crypto_label in CRYPTOS:
            slot["markets"][crypto_label] = results.get(
                (i, crypto_label), {"url": "", "yes": "Error", "no": "Error"}
            )
        slots.append(slot)

    return slots


def format_slot_block(slot):
    """Format a slot dict into the upcoming_markets.txt block format."""
    lines = [f"🕒 Slot: {slot['label']}"]
    for crypto in ["BTC", "ETH", "SOL", "XRP"]:
        if crypto in slot["markets"]:
            m = slot["markets"][crypto]
            lines.append(f"   {crypto}: {m['url']}")
            lines.append(f"        ✅ YES: {m['yes']}")
            lines.append(f"        ❌ NO : {m['no']}")
    return "\n".join(lines)


def append_new_slots(new_slots):
    """Append new slot blocks to upcoming_markets.txt."""
    if not new_slots:
        return 0

    # Read existing content (strip trailing separator/whitespace)
    existing = ""
    if MARKETS_FILE.exists():
        existing = MARKETS_FILE.read_text(encoding="utf-8").rstrip()
        # Remove trailing separator line if present
        if existing.endswith("-" * 70):
            existing = existing[:-70].rstrip()

    # Append new slots
    blocks = [format_slot_block(s) for s in new_slots]
    new_content = existing + "\n\n" + "\n\n".join(blocks) + "\n\n" + "-" * 70 + "\n"
    MARKETS_FILE.write_text(new_content, encoding="utf-8")
    return len(new_slots)


def discover_and_append():
    """Main discovery: fetch slots, deduplicate, append new ones."""
    now_str = datetime.datetime.now(ET_TZ).strftime("%I:%M %p EST")
    print(f"\n{MAGENTA}[FETCHER]{RESET} {now_str} — Checking for new market slots...")

    existing_labels = get_existing_slot_labels()
    print(f"  {DIM}Existing slots in file: {len(existing_labels)}{RESET}")

    fetched_slots = fetch_upcoming_slots()
    print(f"  {DIM}Fetched from API: {len(fetched_slots)} slots{RESET}")

    # Filter out slots already in the file
    new_slots = []
    for slot in fetched_slots:
        if slot["label"] not in existing_labels:
            # Also skip slots where all tokens are "Not indexed" or "Error"
            valid_tokens = sum(
                1 for m in slot["markets"].values()
                if m["yes"] not in ("Not indexed", "Error", "N/A")
            )
            if valid_tokens >= 3:  # at least 3 of 4 cryptos have valid tokens
                new_slots.append(slot)
                print(f"  {GREEN}+ NEW:{RESET} {slot['label']} ({valid_tokens}/4 valid)")
            else:
                print(f"  {YELLOW}~ SKIP:{RESET} {slot['label']} (only {valid_tokens}/4 indexed)")
        else:
            print(f"  {DIM}  EXISTS: {slot['label']}{RESET}")

    if new_slots:
        count = append_new_slots(new_slots)
        print(f"  {GREEN}✓ Appended {count} new slot(s) to {MARKETS_FILE.name}{RESET}")
    else:
        print(f"  {DIM}No new slots to add.{RESET}")

    return new_slots


def fetcher_loop():
    """Background loop: run discovery every FETCH_INTERVAL seconds."""
    # main() already calls discover_and_append() at startup — no double-run
    while True:
        time.sleep(FETCH_INTERVAL)
        try:
            discover_and_append()
        except Exception as e:
            print(f"{RED}[FETCHER ERR]{RESET} {e}")


def start_fetcher():
    """Start the market fetcher as a background daemon thread."""
    t = threading.Thread(target=fetcher_loop, daemon=True)
    t.start()
    print(f"  {MAGENTA}✓ Market fetcher started (every {FETCH_INTERVAL // 60} min){RESET}")


# ─── Standalone mode ─────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{BOLD}Polymarket Market Discovery{RESET}")
    print(f"  File: {MARKETS_FILE}")
    slots = discover_and_append()
    print(f"\n{GREEN}Done.{RESET}")
