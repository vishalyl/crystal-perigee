"""
trade_logger.py — Quant-grade SQLite trade logging
===================================================
Logs every trade with full DNA: temporal data, liquidity, excursion,
fill latency, and granular tick history for replay / analysis.
"""

import sqlite3
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

EST = timezone(timedelta(hours=-5))
DB_PATH = Path(__file__).parent / "trades.db"
STARTING_EQUITY = 1000.0


import time

def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def retry_db_op(retries=5, delay=1.0):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for i in range(retries):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "locked" in str(e):
                        if i == retries - 1:
                            raise
                        time.sleep(delay)
                    else:
                        raise
        return wrapper
    return decorator


def init_db():
    """Create tables if they don't exist."""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_label          TEXT    NOT NULL,
            asset               TEXT    NOT NULL,
            side_chosen         TEXT    NOT NULL,
            token_id            TEXT    NOT NULL,

            -- Temporal
            entry_time_utc      TEXT    NOT NULL,
            entry_time_est      TEXT    NOT NULL,
            hour_of_day         INTEGER NOT NULL,
            day_of_week         TEXT    NOT NULL,

            -- Entry prices
            entry_price         REAL    NOT NULL,
            entry_bid           REAL    DEFAULT 0,
            entry_ask           REAL    DEFAULT 0,
            entry_spread        REAL    DEFAULT 0,
            yes_price_at_entry  REAL    DEFAULT 0,
            no_price_at_entry   REAL    DEFAULT 0,
            side_price_delta    REAL    DEFAULT 0,

            -- Position
            shares              REAL    NOT NULL,
            trade_amount_usd    REAL    NOT NULL DEFAULT 30.0,
            limit_sell_price    REAL    NOT NULL,

            -- Excursion (updated live)
            min_price           REAL    DEFAULT NULL,
            max_price           REAL    DEFAULT NULL,
            min_price_time      TEXT    DEFAULT NULL,
            max_price_time      TEXT    DEFAULT NULL,
            max_adverse_pct     REAL    DEFAULT 0,
            max_favorable_pct   REAL    DEFAULT 0,

            -- Tick stats
            num_price_updates   INTEGER DEFAULT 0,

            -- Exit
            exit_price          REAL    DEFAULT NULL,
            exit_time           TEXT    DEFAULT NULL,
            exit_reason         TEXT    DEFAULT NULL,
            fill_latency_sec    REAL    DEFAULT NULL,

            -- P&L
            pnl_usd             REAL    DEFAULT 0,
            pnl_pct             REAL    DEFAULT 0,
            outcome             TEXT    DEFAULT 'pending',

            -- Portfolio
            equity_before       REAL    DEFAULT 0,
            equity_after        REAL    DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS price_ticks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id    INTEGER NOT NULL,
            timestamp_utc TEXT NOT NULL,
            bid         REAL    NOT NULL,
            ask         REAL    NOT NULL,
            mid         REAL    NOT NULL,
            spread      REAL    NOT NULL,
            FOREIGN KEY (trade_id) REFERENCES trades(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ticks_trade ON price_ticks(trade_id);
        CREATE INDEX IF NOT EXISTS idx_trades_asset ON trades(asset);
        CREATE INDEX IF NOT EXISTS idx_trades_outcome ON trades(outcome);
        CREATE INDEX IF NOT EXISTS idx_trades_slot ON trades(slot_label);
    """)
    conn.close()


def get_current_equity():
    """Calculate current equity: starting + sum of all resolved P&Ls."""
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd), 0) as total_pnl FROM trades WHERE outcome != 'pending'"
    ).fetchone()
    conn.close()
    return STARTING_EQUITY + row["total_pnl"]


@retry_db_op()
def open_trade(slot_label, asset, side_chosen, token_id, entry_price,
               yes_price, no_price, shares, limit_sell_price, trade_amount=30.0):
    """Insert a new trade row. Returns the trade ID."""
    now_utc = datetime.now(timezone.utc)
    now_est = now_utc.astimezone(EST)
    equity = get_current_equity()

    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO trades (
            slot_label, asset, side_chosen, token_id,
            entry_time_utc, entry_time_est, hour_of_day, day_of_week,
            entry_price, yes_price_at_entry, no_price_at_entry,
            side_price_delta, shares, trade_amount_usd, limit_sell_price,
            min_price, max_price, equity_before
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        slot_label, asset, side_chosen, token_id,
        now_utc.isoformat(), now_est.isoformat(),
        now_est.hour, now_est.strftime("%A"),
        entry_price, yes_price, no_price,
        abs(yes_price - no_price),
        shares, trade_amount, limit_sell_price,
        entry_price, entry_price,  # min/max start at entry
        equity,
    ))
    trade_id = cur.lastrowid
    conn.commit()
    conn.close()
    return trade_id


@retry_db_op()
def record_tick(trade_id, bid, ask):
    """Record a price tick and update excursion stats."""
    now_utc = datetime.now(timezone.utc).isoformat()
    mid = (bid + ask) / 2
    spread = ask - bid

    conn = get_conn()

    # Insert tick
    conn.execute("""
        INSERT INTO price_ticks (trade_id, timestamp_utc, bid, ask, mid, spread)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (trade_id, now_utc, bid, ask, mid, spread))

    # Get current trade state
    trade = conn.execute(
        "SELECT entry_price, min_price, max_price FROM trades WHERE id = ?",
        (trade_id,)
    ).fetchone()

    if trade:
        entry = trade["entry_price"]
        new_min = min(trade["min_price"] or mid, mid)
        new_max = max(trade["max_price"] or mid, mid)
        adverse_pct = ((entry - new_min) / entry * 100) if entry > 0 else 0
        favorable_pct = ((new_max - entry) / entry * 100) if entry > 0 else 0

        updates = {}
        if new_min < (trade["min_price"] or float('inf')):
            updates["min_price"] = new_min
            updates["min_price_time"] = now_utc
        if new_max > (trade["max_price"] or 0):
            updates["max_price"] = new_max
            updates["max_price_time"] = now_utc

        conn.execute("""
            UPDATE trades SET
                min_price = ?,
                max_price = ?,
                min_price_time = COALESCE(?, min_price_time),
                max_price_time = COALESCE(?, max_price_time),
                max_adverse_pct = ?,
                max_favorable_pct = ?,
                num_price_updates = num_price_updates + 1
            WHERE id = ?
        """, (
            new_min, new_max,
            updates.get("min_price_time"),
            updates.get("max_price_time"),
            adverse_pct, favorable_pct,
            trade_id,
        ))

    conn.commit()
    conn.close()
    return mid


@retry_db_op()
def close_trade(trade_id, exit_price, exit_reason):
    """Close a trade: compute P&L, fill latency, update equity."""
    conn = get_conn()
    trade = conn.execute(
        "SELECT entry_price, shares, entry_time_utc, equity_before FROM trades WHERE id = ?",
        (trade_id,)
    ).fetchone()

    if not trade:
        conn.close()
        return None

    now_utc = datetime.now(timezone.utc)
    entry_time = datetime.fromisoformat(trade["entry_time_utc"])
    latency = (now_utc - entry_time).total_seconds()

    entry = trade["entry_price"]
    shares = trade["shares"]
    pnl_usd = (exit_price - entry) * shares
    pnl_pct = ((exit_price - entry) / entry * 100) if entry > 0 else 0
    outcome = "win" if pnl_usd >= 0 else "loss"
    equity_after = trade["equity_before"] + pnl_usd

    conn.execute("""
        UPDATE trades SET
            exit_price = ?,
            exit_time = ?,
            exit_reason = ?,
            fill_latency_sec = ?,
            pnl_usd = ?,
            pnl_pct = ?,
            outcome = ?,
            equity_after = ?
        WHERE id = ?
    """, (
        exit_price, now_utc.isoformat(), exit_reason,
        latency, pnl_usd, pnl_pct, outcome, equity_after,
        trade_id,
    ))
    conn.commit()
    conn.close()

    return {
        "trade_id": trade_id,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
        "outcome": outcome,
        "fill_latency_sec": latency,
        "equity_after": equity_after,
    }


def get_pending_trades():
    """Return all trades with outcome = 'pending'."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades WHERE outcome = 'pending' ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_trades():
    """Return all trades ordered by entry time."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY entry_time_utc"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trade_ticks(trade_id):
    """Return all ticks for a given trade."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM price_ticks WHERE trade_id = ? ORDER BY id",
        (trade_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_price(trade_id):
    """Return the most recent mid price for a trade."""
    conn = get_conn()
    row = conn.execute(
        "SELECT mid FROM price_ticks WHERE trade_id = ? ORDER BY id DESC LIMIT 1",
        (trade_id,)
    ).fetchone()
    conn.close()
    return row["mid"] if row else None


def get_stats():
    """Return summary statistics."""
    conn = get_conn()
    stats = {}

    row = conn.execute("""
        SELECT
            COUNT(*) as total_trades,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN outcome = 'pending' THEN 1 ELSE 0 END) as pending,
            COALESCE(SUM(CASE WHEN outcome != 'pending' THEN pnl_usd ELSE 0 END), 0) as total_pnl,
            COALESCE(AVG(CASE WHEN outcome != 'pending' THEN pnl_usd END), 0) as avg_pnl,
            COALESCE(AVG(CASE WHEN outcome != 'pending' THEN fill_latency_sec END), 0) as avg_latency,
            COALESCE(AVG(max_adverse_pct), 0) as avg_adverse,
            COALESCE(AVG(max_favorable_pct), 0) as avg_favorable
        FROM trades
    """).fetchone()

    stats = dict(row)
    stats["equity"] = STARTING_EQUITY + stats["total_pnl"]
    stats["win_rate"] = (
        stats["wins"] / (stats["wins"] + stats["losses"]) * 100
        if (stats["wins"] + stats["losses"]) > 0 else 0
    )

    conn.close()
    return stats
