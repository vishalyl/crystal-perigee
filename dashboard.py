"""
dashboard.py — Streamlit Quant Analytics Dashboard
===================================================
Run:  streamlit run dashboard.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sqlite3
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from streamlit_autorefresh import st_autorefresh

DB_PATH = Path(__file__).parent / "trades.db"
MARKETS_FILE = Path(__file__).parent / "upcoming_markets.txt"
STARTING_EQUITY = 1000.0
EST = timezone(timedelta(hours=-5))

st.set_page_config(
    page_title="Crystal Perigee — Quant Dashboard",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ─────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    .stApp { font-family: 'Inter', sans-serif; }
    div[data-testid="stMetricValue"] { font-size: 1.5rem; }
    div[data-testid="stMetricDelta"] { font-size: 1rem; }
    .slot-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #333;
        border-radius: 12px;
        padding: 18px;
        margin: 8px 0;
    }
    .slot-active {
        border-color: #00e676;
        box-shadow: 0 0 12px rgba(0,230,118,0.15);
    }
    .slot-upcoming {
        border-color: #ffd740;
    }
    .slot-expired {
        border-color: #555;
        opacity: 0.6;
    }
    .trade-pending { color: #ffd740; }
    .trade-win { color: #00e676; }
    .trade-loss { color: #ff5252; }
</style>
""", unsafe_allow_html=True)


# ─── Data loaders ──────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def load_trades():
    conn = get_conn()
    try:
        return pd.read_sql("SELECT * FROM trades ORDER BY entry_time_utc", conn)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


def load_ticks(trade_id):
    conn = get_conn()
    try:
        return pd.read_sql(
            "SELECT * FROM price_ticks WHERE trade_id = ? ORDER BY id",
            conn, params=(trade_id,)
        )
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


def load_latest_price(trade_id):
    """Fetch the most recent price from DB for a trade."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT mid FROM price_ticks WHERE trade_id = ? ORDER BY id DESC LIMIT 1",
            (trade_id,)
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        conn.close()


def parse_upcoming_slots():
    """Parse upcoming_markets.txt and return structured slot data with market names."""
    if not MARKETS_FILE.exists():
        return []

    text = MARKETS_FILE.read_text(encoding="utf-8")
    slots = []
    slot_blocks = re.split(r"🕒\s*Slot:\s*", text)

    for block in slot_blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        label = lines[0].strip()

        hour_match = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)\s*EST", label)
        if not hour_match:
            continue
        hour = int(hour_match.group(1))
        minute = int(hour_match.group(2))
        ampm = hour_match.group(3)
        if ampm == "AM" and hour == 12:
            hour = 0
        elif ampm == "PM" and hour != 12:
            hour += 12

        markets = {}
        current_crypto = None

        for line in lines[1:]:
            ls = line.strip()
            crypto_match = re.match(r"(BTC|ETH|SOL|XRP)\s*:", ls)
            if crypto_match:
                current_crypto = crypto_match.group(1)
                # Extract market name from URL
                url_match = re.search(r"https://polymarket\.com/event/([^\s]+)", ls)
                market_name = url_match.group(1).replace("-", " ").title() if url_match else current_crypto
                url = url_match.group(0) if url_match else ""
                markets[current_crypto] = {"name": market_name, "url": url}
                continue

        slots.append({
            "label": label,
            "hour": hour,
            "markets": markets,
        })

    slots.sort(key=lambda s: s["hour"])
    return slots


# ─── Sidebar ────────────────────────────────────────────────────────
st.sidebar.title("💎 Crystal Perigee")
st.sidebar.caption("Polymarket 1h Crypto Quant Engine")
auto_refresh = st.sidebar.checkbox("Auto-refresh (15s)", value=True)
if auto_refresh:
    st_autorefresh(interval=15000, key="auto_refresh")

if st.sidebar.button("🔄 Refresh Now"):
    st.rerun()

# Load data
df = load_trades()
upcoming_slots = parse_upcoming_slots()
now_est = datetime.now(EST)
current_hour = now_est.hour

# Sidebar equity display
if not df.empty:
    resolved_all = df[df["outcome"] != "pending"]
    equity = STARTING_EQUITY + (resolved_all["pnl_usd"].sum() if not resolved_all.empty else 0)
    st.sidebar.markdown("---")
    st.sidebar.metric("💰 Portfolio Equity", f"${equity:.2f}", f"${equity - STARTING_EQUITY:+.2f}")
else:
    equity = STARTING_EQUITY

st.sidebar.markdown("---")
st.sidebar.markdown("### Filters")

# ─── Title ─────────────────────────────────────────────────────────
st.title("💎 Crystal Perigee — Quant Dashboard")
st.caption(f"📡 Live  ·  {now_est.strftime('%I:%M:%S %p EST  ·  %A, %B %d, %Y')}")

# ─── TABS ──────────────────────────────────────────────────────────
tab_current, tab_upcoming, tab_analytics, tab_log, tab_replay = st.tabs([
    "⚡ Current Trades", "📅 Upcoming Slots", "📊 Analytics", "📋 Trade Log", "📈 Tick Replay"
])

# ════════════════════════════════════════════════════════════════════
# TAB 1: CURRENT TRADES
# ════════════════════════════════════════════════════════════════════
with tab_current:
    st.subheader("⚡ Active Trades — Live Positions")

    if not df.empty:
        pending = df[df["outcome"] == "pending"]
        if not pending.empty:
            # Summary metrics
            mc1, mc2, mc3, mc4 = st.columns(4)
            unrealized_pnl = 0
            for _, t in pending.iterrows():
                if pd.notna(t.get("max_price")) and pd.notna(t.get("entry_price")):
                    unrealized_pnl += (t["max_price"] - t["entry_price"]) * t["shares"]
            mc1.metric("🔴 Active Positions", len(pending))
            mc2.metric("💵 Capital Deployed", f"${len(pending) * 30:.0f}")
            mc3.metric("📊 Assets", ", ".join(sorted(pending["asset"].unique())))
            mc4.metric("💰 Equity", f"${equity:.2f}")

            st.markdown("---")

            # Cards for each active trade
            for _, trade in pending.iterrows():
                slot_name = trade["slot_label"]
                asset = trade["asset"]
                side = trade["side_chosen"]
                entry = trade["entry_price"]
                target = trade["limit_sell_price"]
                ticks = trade.get("num_price_updates", 0)

                # Get live price
                current_price = load_latest_price(trade["id"])
                if current_price is None:
                    current_price = entry  # fallback

                # Calculate Unrealized P&L
                pnl_est = (current_price - entry) * trade["shares"]
                pnl_pct = ((current_price - entry) / entry * 100) if entry > 0 else 0

                side_emoji = "✅" if side == "YES" else "❌"
                pnl_color = "trade-win" if pnl_est >= 0 else "trade-loss"

                col_a, col_b, col_c, col_d, col_e = st.columns([1.5, 1, 1, 1, 1])
                with col_a:
                    st.markdown(f"**{asset}** {side_emoji} {side}")
                    st.caption(f"📅 {slot_name}")
                with col_b:
                    st.metric("Entry", f"${entry:.3f}")
                with col_c:
                    st.metric("Current", f"${current_price:.3f}", f"{pnl_pct:+.1f}%")
                with col_d:
                    st.metric("Target", f"${target:.3f}")
                with col_e:
                    st.metric("P&L (Unr)", f"${pnl_est:+.2f}")

                st.markdown("---")
        else:
            st.info("No active trades. All positions are resolved.")

        # Recently closed trades
        recent_closed = df[df["outcome"] != "pending"].tail(8)
        if not recent_closed.empty:
            st.subheader("🕐 Recently Closed")
            for _, trade in recent_closed.iterrows():
                icon = "✅" if trade["outcome"] == "win" else "🔴"
                pnl_sign = "+" if trade["pnl_usd"] >= 0 else ""
                st.markdown(
                    f"{icon} **{trade['asset']}** {trade['side_chosen']} — "
                    f"${trade['pnl_usd']:+.2f} ({trade['pnl_pct']:+.1f}%) — "
                    f"*{trade['exit_reason']}* — {trade['slot_label']}"
                )
    else:
        st.warning("No trades yet. Start the monitor: `python crypto_monitor.py`")


# ════════════════════════════════════════════════════════════════════
# TAB 2: UPCOMING SLOTS
# ════════════════════════════════════════════════════════════════════
with tab_upcoming:
    st.subheader("📅 Market Schedule")
    st.caption(f"Current time: **{now_est.strftime('%I:%M %p EST')}** · Current hour slot: **{current_hour}:00**")

    if upcoming_slots:
        for slot in upcoming_slots:
            slot_hour = slot["hour"]
            # Determine status
            if slot_hour + 1 <= current_hour:
                status = "expired"
                status_label = "⏹ Completed"
                card_class = "slot-expired"
            elif slot_hour == current_hour:
                status = "active"
                status_label = "🔴 LIVE NOW"
                card_class = "slot-active"
            elif slot_hour == current_hour + 1:
                status = "next"
                status_label = "⏭ Next Up"
                card_class = "slot-upcoming"
            else:
                status = "upcoming"
                mins_until = (slot_hour - current_hour) * 60 - now_est.minute
                status_label = f"⏰ In {mins_until} min"
                card_class = "slot-upcoming"

            # Build market list
            market_lines = ""
            for crypto, info in slot.get("markets", {}).items():
                name = info.get("name", crypto)
                url = info.get("url", "")
                if url:
                    market_lines += f'<div style="margin-left: 12px; padding: 4px 0;">🪙 <b>{crypto}</b> — <a href="{url}" target="_blank" style="color: #90caf9; text-decoration: none;">{name}</a></div>'
                else:
                    market_lines += f'<div style="margin-left: 12px; padding: 4px 0;">🪙 <b>{crypto}</b> — {name}</div>'

            # Check if we have trades for this slot
            trade_info = ""
            if not df.empty:
                slot_trades = df[df["slot_label"] == slot["label"]]
                if not slot_trades.empty:
                    wins = len(slot_trades[slot_trades["outcome"] == "win"])
                    losses = len(slot_trades[slot_trades["outcome"] == "loss"])
                    pending_count = len(slot_trades[slot_trades["outcome"] == "pending"])
                    slot_pnl = slot_trades[slot_trades["outcome"] != "pending"]["pnl_usd"].sum()
                    parts = []
                    if wins: parts.append(f"✅ {wins}W")
                    if losses: parts.append(f"🔴 {losses}L")
                    if pending_count: parts.append(f"⏳ {pending_count} live")
                    trade_info = f'<div style="margin-top: 8px; color: #aaa;">Trades: {" · ".join(parts)} · P&L: <b style="color: {"#00e676" if slot_pnl >= 0 else "#ff5252"}">${slot_pnl:+.2f}</b></div>'

            st.markdown(f"""
            <div class="slot-card {card_class}">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <h4 style="margin: 0;">📅 {slot['label']}</h4>
                    <span style="font-size: 0.9rem; font-weight: 600; {'color: #00e676' if status == 'active' else 'color: #ffd740' if status in ('next', 'upcoming') else 'color: #777'};">{status_label}</span>
                </div>
                <div style="margin-top: 10px;">
                    {market_lines}
                </div>
                {trade_info}
            </div>
            """, unsafe_allow_html=True)
    else:
        st.warning("No upcoming markets found. Add slots to `upcoming_markets.txt`.")


# ════════════════════════════════════════════════════════════════════
# TAB 3: ANALYTICS
# ════════════════════════════════════════════════════════════════════
with tab_analytics:
    if df.empty:
        st.warning("No trades found.")
        st.stop()

    # Sidebar filters (inside analytics)
    asset_filter = st.sidebar.multiselect("Assets", options=sorted(df["asset"].unique()), default=sorted(df["asset"].unique()))
    outcome_filter = st.sidebar.multiselect("Outcome", options=["win", "loss", "pending"], default=["win", "loss", "pending"])
    df_filtered = df[df["asset"].isin(asset_filter) & df["outcome"].isin(outcome_filter)]

    resolved = df_filtered[df_filtered["outcome"] != "pending"]
    total_pnl = resolved["pnl_usd"].sum() if not resolved.empty else 0
    total_trades = len(df_filtered)
    wins = len(resolved[resolved["outcome"] == "win"])
    losses = len(resolved[resolved["outcome"] == "loss"])
    pending_count = len(df_filtered[df_filtered["outcome"] == "pending"])
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    avg_win = resolved[resolved["outcome"] == "win"]["pnl_usd"].mean() if wins > 0 else 0
    avg_loss = resolved[resolved["outcome"] == "loss"]["pnl_usd"].mean() if losses > 0 else 0

    gross_profit = resolved[resolved["pnl_usd"] > 0]["pnl_usd"].sum() if not resolved.empty else 0
    gross_loss = abs(resolved[resolved["pnl_usd"] < 0]["pnl_usd"].sum()) if not resolved.empty else 1
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("💰 Equity", f"${equity:.2f}", f"${total_pnl:+.2f}")
    col2.metric("📊 Total Trades", total_trades, f"{pending_count} pending")
    col3.metric("✅ Win Rate", f"{win_rate:.1f}%", f"{wins}W / {losses}L")
    col4.metric("📈 Avg Win", f"${avg_win:+.2f}" if wins else "N/A")
    col5.metric("📉 Avg Loss", f"${avg_loss:+.2f}" if losses else "N/A")
    col6.metric("⚡ Profit Factor", f"{profit_factor:.2f}" if profit_factor != float('inf') else "∞")

    st.markdown("---")

    # ─── Equity Curve ──────────────────────────────────────────
    st.subheader("📈 Equity Curve")
    if not resolved.empty:
        eq_df = resolved.sort_values("entry_time_utc").copy()
        eq_df["cumulative_pnl"] = eq_df["pnl_usd"].cumsum()
        eq_df["equity"] = STARTING_EQUITY + eq_df["cumulative_pnl"]
        eq_df["trade_num"] = range(1, len(eq_df) + 1)

        start_row = pd.DataFrame([{"trade_num": 0, "equity": STARTING_EQUITY, "cumulative_pnl": 0}])
        eq_df = pd.concat([start_row, eq_df], ignore_index=True)

        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=eq_df["trade_num"], y=eq_df["equity"],
            mode="lines+markers",
            line=dict(color="#00e676", width=3),
            marker=dict(size=6),
            fill="tozeroy",
            fillcolor="rgba(0,230,118,0.1)",
            name="Equity",
        ))
        fig_eq.add_hline(y=STARTING_EQUITY, line_dash="dash", line_color="#666", annotation_text="Starting ($1,000)")
        fig_eq.update_layout(
            template="plotly_dark", height=350,
            xaxis_title="Trade #", yaxis_title="Equity ($)",
            margin=dict(t=20, b=40),
        )
        st.plotly_chart(fig_eq, use_container_width=True)
    else:
        st.info("No resolved trades yet.")

    # ─── Two-column charts ─────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("🏆 Asset Performance (Beta)")
        if not resolved.empty:
            asset_stats = resolved.groupby("asset").agg(
                trades=("id", "count"),
                wins=("outcome", lambda x: (x == "win").sum()),
                total_pnl=("pnl_usd", "sum"),
                avg_pnl=("pnl_usd", "mean"),
                avg_latency=("fill_latency_sec", "mean"),
            ).reset_index()
            asset_stats["win_rate"] = asset_stats["wins"] / asset_stats["trades"] * 100

            fig_asset = make_subplots(specs=[[{"secondary_y": True}]])
            fig_asset.add_trace(go.Bar(
                x=asset_stats["asset"], y=asset_stats["total_pnl"],
                name="Total P&L",
                marker_color=["#00e676" if v >= 0 else "#ff5252" for v in asset_stats["total_pnl"]],
            ), secondary_y=False)
            fig_asset.add_trace(go.Scatter(
                x=asset_stats["asset"], y=asset_stats["win_rate"],
                name="Win Rate %", mode="lines+markers",
                line=dict(color="#90caf9", width=2),
            ), secondary_y=True)
            fig_asset.update_layout(template="plotly_dark", height=300, margin=dict(t=20, b=40))
            fig_asset.update_yaxes(title_text="P&L ($)", secondary_y=False)
            fig_asset.update_yaxes(title_text="Win Rate (%)", secondary_y=True)
            st.plotly_chart(fig_asset, use_container_width=True)

    with col_right:
        st.subheader("🕐 P&L by Hour (EST)")
        if not resolved.empty:
            hourly = resolved.groupby("hour_of_day").agg(
                total_pnl=("pnl_usd", "sum"),
                trades=("id", "count"),
                wins=("outcome", lambda x: (x == "win").sum()),
            ).reset_index()
            hourly["win_rate"] = hourly["wins"] / hourly["trades"] * 100
            hourly["hour_label"] = hourly["hour_of_day"].apply(
                lambda h: f"{h if h <= 12 else h-12}{'AM' if h < 12 else 'PM'}"
            )

            fig_hour = go.Figure(go.Bar(
                x=hourly["hour_label"],
                y=hourly["total_pnl"],
                marker_color=["#00e676" if v >= 0 else "#ff5252" for v in hourly["total_pnl"]],
                text=[f"{r:.0f}%" for r in hourly["win_rate"]],
                textposition="outside",
            ))
            fig_hour.update_layout(
                template="plotly_dark", height=300,
                xaxis_title="Hour (EST)", yaxis_title="P&L ($)",
                margin=dict(t=20, b=40),
            )
            st.plotly_chart(fig_hour, use_container_width=True)

    st.markdown("---")

    # ─── Excursion Analysis ────────────────────────────────────
    col_ex1, col_ex2 = st.columns(2)
    with col_ex1:
        st.subheader("📉 Adverse Excursion vs P&L")
        if not resolved.empty and "max_adverse_pct" in resolved.columns:
            fig_adv = px.scatter(
                resolved, x="max_adverse_pct", y="pnl_usd",
                color="outcome",
                color_discrete_map={"win": "#00e676", "loss": "#ff5252"},
                hover_data=["asset", "slot_label", "entry_price"],
                template="plotly_dark",
            )
            fig_adv.update_layout(height=300, xaxis_title="Max Adverse Excursion (%)", yaxis_title="P&L ($)", margin=dict(t=20, b=40))
            st.plotly_chart(fig_adv, use_container_width=True)

    with col_ex2:
        st.subheader("📈 Favorable Excursion vs P&L")
        if not resolved.empty and "max_favorable_pct" in resolved.columns:
            fig_fav = px.scatter(
                resolved, x="max_favorable_pct", y="pnl_usd",
                color="outcome",
                color_discrete_map={"win": "#00e676", "loss": "#ff5252"},
                hover_data=["asset", "slot_label", "entry_price"],
                template="plotly_dark",
            )
            fig_fav.update_layout(height=300, xaxis_title="Max Favorable Excursion (%)", yaxis_title="P&L ($)", margin=dict(t=20, b=40))
            st.plotly_chart(fig_fav, use_container_width=True)

    st.markdown("---")

    # ─── Spread vs Outcome & Fill Latency ──────────────────────
    col_sp, col_lat = st.columns(2)
    with col_sp:
        st.subheader("📊 Entry Spread → Outcome")
        if not resolved.empty and "entry_spread" in resolved.columns:
            fig_spread = px.box(
                resolved, x="outcome", y="entry_spread",
                color="outcome",
                color_discrete_map={"win": "#00e676", "loss": "#ff5252"},
                template="plotly_dark",
            )
            fig_spread.update_layout(height=300, yaxis_title="Entry Spread ($)", margin=dict(t=20, b=40))
            st.plotly_chart(fig_spread, use_container_width=True)

    with col_lat:
        st.subheader("⏱ Fill Latency Distribution")
        if not resolved.empty and "fill_latency_sec" in resolved.columns:
            resolved_lat = resolved.dropna(subset=["fill_latency_sec"]).copy()
            if not resolved_lat.empty:
                resolved_lat["fill_min"] = resolved_lat["fill_latency_sec"] / 60
                fig_lat = px.histogram(
                    resolved_lat, x="fill_min",
                    color="outcome",
                    color_discrete_map={"win": "#00e676", "loss": "#ff5252"},
                    nbins=20, template="plotly_dark",
                )
                fig_lat.update_layout(height=300, xaxis_title="Fill Latency (minutes)", yaxis_title="Count", margin=dict(t=20, b=40))
                st.plotly_chart(fig_lat, use_container_width=True)

    st.markdown("---")

    # ─── Side Analysis ─────────────────────────────────────────
    st.subheader("🔄 YES vs NO Side Performance")
    if not resolved.empty:
        side_stats = resolved.groupby("side_chosen").agg(
            trades=("id", "count"),
            wins=("outcome", lambda x: (x == "win").sum()),
            total_pnl=("pnl_usd", "sum"),
        ).reset_index()
        side_stats["win_rate"] = side_stats["wins"] / side_stats["trades"] * 100

        sc1, sc2 = st.columns(2)
        for _, row in side_stats.iterrows():
            col = sc1 if row["side_chosen"] == "YES" else sc2
            with col:
                st.metric(
                    f"{'✅' if row['side_chosen'] == 'YES' else '❌'} {row['side_chosen']} Side",
                    f"${row['total_pnl']:+.2f}",
                    f"Win Rate: {row['win_rate']:.0f}% ({int(row['trades'])} trades)"
                )


# ════════════════════════════════════════════════════════════════════
# TAB 4: TRADE LOG
# ════════════════════════════════════════════════════════════════════
with tab_log:
    st.subheader("📋 Full Trade Log")

    if not df.empty:
        display_cols = [
            "id", "slot_label", "asset", "side_chosen", "entry_price",
            "limit_sell_price", "exit_price", "pnl_usd", "pnl_pct",
            "outcome", "exit_reason", "fill_latency_sec",
            "max_adverse_pct", "max_favorable_pct",
            "entry_spread", "num_price_updates", "hour_of_day", "day_of_week",
        ]
        available_cols = [c for c in display_cols if c in df.columns]

        st.dataframe(
            df[available_cols].style.map(
                lambda v: "color: #00e676" if v == "win" else ("color: #ff5252" if v == "loss" else ""),
                subset=["outcome"] if "outcome" in available_cols else [],
            ),
            use_container_width=True,
            height=600,
        )

        # Download CSV
        csv = df[available_cols].to_csv(index=False)
        st.download_button("📥 Download CSV", csv, "trades_export.csv", "text/csv")
    else:
        st.info("No trades yet.")


# ════════════════════════════════════════════════════════════════════
# TAB 5: TICK REPLAY
# ════════════════════════════════════════════════════════════════════
with tab_replay:
    st.subheader("📈 Price Tick Replay")

    if not df.empty:
        trade_options = df.apply(
            lambda r: f"#{r['id']} — {r['asset']} {r['side_chosen']} ({r['slot_label']}) [{r['outcome']}]",
            axis=1,
        ).tolist()
        trade_ids = df["id"].tolist()

        selected_idx = st.selectbox("Select a trade:", range(len(trade_options)), format_func=lambda i: trade_options[i])
        selected_trade_id = trade_ids[selected_idx]
        trade_row = df[df["id"] == selected_trade_id].iloc[0]

        ticks_df = load_ticks(selected_trade_id)

        if not ticks_df.empty:
            ticks_df["timestamp"] = pd.to_datetime(ticks_df["timestamp_utc"])
            ticks_df["tick_num"] = range(1, len(ticks_df) + 1)

            fig_tick = go.Figure()
            fig_tick.add_trace(go.Scatter(
                x=ticks_df["tick_num"], y=ticks_df["mid"],
                mode="lines", name="Mid Price",
                line=dict(color="#90caf9", width=2),
            ))
            fig_tick.add_trace(go.Scatter(
                x=ticks_df["tick_num"], y=ticks_df["bid"],
                mode="lines", name="Bid",
                line=dict(color="#66bb6a", width=1, dash="dot"),
            ))
            fig_tick.add_trace(go.Scatter(
                x=ticks_df["tick_num"], y=ticks_df["ask"],
                mode="lines", name="Ask",
                line=dict(color="#ef5350", width=1, dash="dot"),
            ))

            fig_tick.add_hline(
                y=trade_row["entry_price"], line_dash="dash",
                line_color="#ffd740", annotation_text=f"Entry ${trade_row['entry_price']:.3f}",
            )
            fig_tick.add_hline(
                y=trade_row["limit_sell_price"], line_dash="dash",
                line_color="#00e676", annotation_text=f"Target ${trade_row['limit_sell_price']:.3f}",
            )

            fig_tick.update_layout(
                template="plotly_dark", height=400,
                xaxis_title="Tick #", yaxis_title="Price ($)",
                margin=dict(t=20, b=40),
            )
            st.plotly_chart(fig_tick, use_container_width=True)

            tc1, tc2, tc3, tc4 = st.columns(4)
            tc1.metric("Entry", f"${trade_row['entry_price']:.3f}")
            tc2.metric("Exit", f"${trade_row['exit_price']:.3f}" if pd.notna(trade_row.get('exit_price')) else "Pending")
            tc3.metric("P&L", f"${trade_row['pnl_usd']:+.2f}" if trade_row["outcome"] != "pending" else "—")
            tc4.metric("Ticks", len(ticks_df))
        else:
            st.info("No tick data recorded for this trade yet.")
    else:
        st.info("No trades yet.")
