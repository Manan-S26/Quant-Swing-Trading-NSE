"""Streamlit dashboard — read-only trading session monitor.

Reads the JSON file written by DashboardSessionWriter and renders a
structured status dashboard.  No credentials, no broker calls, no orders.

Run with:
    streamlit run scripts/dashboard.py

Override session file path:
    DASHBOARD_SESSION_PATH=data/my/path.json streamlit run scripts/dashboard.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Add src/ to path when running directly (outside an installed package).
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

import streamlit as st  # noqa: E402  (must be after sys.path update)

from trading_engine.dashboard.session_writer import DashboardSessionWriter  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_SESSION_PATH = "data/dashboard/session_status.json"
_SESSION_PATH = Path(os.environ.get("DASHBOARD_SESSION_PATH", _DEFAULT_SESSION_PATH))
_REFRESH_INTERVAL_SECONDS = 30

# ---------------------------------------------------------------------------
# Page config (must be the first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Trading Engine — Dashboard",
    page_icon="📊",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("Settings")
auto_refresh = st.sidebar.checkbox("Auto-refresh every 30 seconds", value=False)
st.sidebar.caption(f"Session file: `{_SESSION_PATH}`")
st.sidebar.caption("Dashboard is **read-only**. No orders are placed.")

# ---------------------------------------------------------------------------
# Load session
# ---------------------------------------------------------------------------

writer = DashboardSessionWriter(_SESSION_PATH)
session = writer.read_status()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("📊 Trading Engine Dashboard")

if session is None:
    st.warning(
        f"No session file found at `{_SESSION_PATH}`. "
        "Run the engine or generate demo data:\n\n"
        "```\npython3 scripts/write_demo_dashboard_status.py\n```"
    )
    st.stop()

col_gen, col_src, col_ver = st.columns(3)
col_gen.metric("Generated at", session.generated_at.strftime("%Y-%m-%d %H:%M:%S"))
col_src.metric("Source", session.source)
col_ver.metric("Schema version", session.version)

st.divider()

# ---------------------------------------------------------------------------
# Helper: safe field access
# ---------------------------------------------------------------------------

status = session.status


def _get(key: str, default=None):
    return status.get(key, default)


# ---------------------------------------------------------------------------
# System status metrics
# ---------------------------------------------------------------------------

st.subheader("System Status")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total orders", _get("total_orders", 0))
m2.metric("Total fills", _get("total_fills", 0))
m3.metric("Risk decisions", _get("total_risk_decisions", 0))
m4.metric("Open positions", _get("open_positions_count", 0))

st.divider()

# ---------------------------------------------------------------------------
# Orders by status
# ---------------------------------------------------------------------------

st.subheader("Orders by Status")

orders_by_status: dict[str, int] = _get("orders_by_status") or {}

if orders_by_status:
    import pandas as pd  # local import to keep top-level lean

    df_orders = pd.DataFrame(
        list(orders_by_status.items()),
        columns=["Status", "Count"],
    ).sort_values("Count", ascending=False)

    col_tbl, col_chart = st.columns([1, 2])
    with col_tbl:
        st.dataframe(df_orders, use_container_width=True, hide_index=True)
    with col_chart:
        st.bar_chart(df_orders.set_index("Status")["Count"])
else:
    st.info("No orders in ledger.")

st.divider()

# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

st.subheader("Last Reconciliation")

recon_ts = _get("last_reconciliation_timestamp")
recon_ok = _get("last_reconciliation_success")
disc_count = _get("discrepancy_count", 0)

r1, r2, r3 = st.columns(3)
r1.metric("Timestamp", recon_ts or "—")
r2.metric(
    "Result",
    "✅ OK" if recon_ok is True else ("❌ Issues" if recon_ok is False else "—"),
)
r3.metric("Discrepancies", disc_count)

# Discrepancy table (populated when reconciliation report is embedded in status)
discrepancies = _get("discrepancies")
if discrepancies:
    import pandas as pd  # noqa: F811

    df_disc = pd.DataFrame(discrepancies)
    st.dataframe(df_disc, use_container_width=True, hide_index=True)
elif recon_ts:
    st.success("No discrepancies recorded.")

st.divider()

# ---------------------------------------------------------------------------
# Raw JSON (debug)
# ---------------------------------------------------------------------------

with st.expander("Raw session JSON (debug)"):
    import json  # noqa: F811  (safe re-import)

    st.code(json.dumps(session.to_dict(), indent=2), language="json")

# ---------------------------------------------------------------------------
# Auto-refresh
# ---------------------------------------------------------------------------

if auto_refresh:
    time.sleep(_REFRESH_INTERVAL_SECONDS)
    st.rerun()
