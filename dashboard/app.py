"""Streamlit control room for the buildathon checkpoint-5 demo."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.dashboard import DashboardPaths, load_dashboard_data
from mandate_recovery.environment import load_project_environment

load_project_environment(PROJECT_ROOT)


st.set_page_config(
    page_title="Recovery Control Room",
    page_icon="₹",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --ink:#132238; --blue:#2b55d4; --mint:#16a085; --amber:#e59b27; }
    .stApp { background: #f4f7fb; color: var(--ink); }
    [data-testid="stSidebar"] { background: #101d31; }
    [data-testid="stSidebar"] * { color: #eef4ff; }
    .block-container { padding-top: 2rem; padding-bottom: 3rem; }
    .eyebrow { color:#52709d; font-size:.76rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }
    .hero { background:linear-gradient(120deg,#102340,#173b6f); color:white; border-radius:18px; padding:24px 28px; margin-bottom:20px; box-shadow:0 12px 36px rgba(17,42,78,.15); }
    .hero h1 { margin:.2rem 0 .35rem; font-size:2rem; }
    .hero p { color:#cbd9ef; margin:0; max-width:760px; }
    .status { display:inline-block; margin-top:14px; padding:5px 10px; border-radius:999px; background:#173f38; color:#8ef0d1; font-size:.78rem; font-weight:700; }
    [data-testid="stMetric"] { background:white; border:1px solid #dce5f1; border-radius:14px; padding:15px 17px; box-shadow:0 4px 16px rgba(26,54,93,.05); }
    [data-testid="stMetricLabel"] { color:#5a6c85; }
    div[data-testid="stExpander"] { background:white; border-color:#dce5f1; border-radius:12px; }
    .trace-step { border-left:3px solid #2b55d4; background:white; padding:10px 14px; margin:7px 0; border-radius:0 10px 10px 0; }
    .trace-step small { color:#61748e; }
    </style>
    """,
    unsafe_allow_html=True,
)


def money(paise: int | float) -> str:
    return f"₹{float(paise) / 100:,.0f}"


def chart(spec: dict) -> None:
    st.vega_lite_chart(spec, width="stretch")


comparison_dir = PROJECT_ROOT / "data" / "runs" / "checkpoint-3"
lifecycle_dir = PROJECT_ROOT / "data" / "runs" / "checkpoint-4"

with st.sidebar:
    st.markdown("## Recovery Agent")
    st.caption("Buildathon evidence console")
    st.markdown("---")
    st.markdown("**Evidence sources**")
    st.code("checkpoint-3\ncheckpoint-4", language=None)
    st.markdown("**Runtime boundary**")
    st.caption("Synthetic failures · bounded tools · test-mode integrations only")

try:
    data = load_dashboard_data(DashboardPaths(comparison_dir, lifecycle_dir))
except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
    st.error("Dashboard artifacts are missing or inconsistent.")
    st.code(
        "python scripts/compare_flows.py --run-id checkpoint-3 --seed 42 --provider scripted\n"
        "python scripts/run_recovery.py --run-id checkpoint-4 --seed 42",
        language="bash",
    )
    st.caption(str(error))
    st.stop()

comparison = data.comparison
lifecycle = data.lifecycle
delta = comparison["delta"]

st.markdown(
    f"""
    <section class="hero">
      <div class="eyebrow" style="color:#91acd5">AI Revenue Recovery · Track 3</div>
      <h1>Recovery Control Room</h1>
      <p>From failed mandate to bounded intervention—with every decision, retry,
      customer message, and stop condition visible.</p>
      <span class="status">AUDIT CHAIN {'VALID' if lifecycle['audit_chain_valid'] else 'INVALID'}</span>
    </section>
    """,
    unsafe_allow_html=True,
)

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric("Batch", f"{lifecycle['transactions']} payments")
kpi2.metric("Compliant recovery", f"{comparison['compliant']['recovery_rate']:.1%}")
kpi3.metric("Naive recovery", f"{comparison['naive']['recovery_rate']:.1%}")
kpi4.metric("Recovery uplift", f"+{delta['recovery_rate_percentage_points']:.1f} pp")
kpi5.metric("Incremental revenue", money(delta["recovered_amount_paise"]))

overview_tab, lifecycle_tab, audit_tab, live_tab = st.tabs(
    ["Flow comparison", "Lifecycle health", "Decision explorer", "Live Razorpay"]
)

with overview_tab:
    left, right = st.columns([1.15, 0.85])
    with left:
        st.subheader("The compliant path wins back more")
        chart({
            "data": {"values": data.flow_rows},
            "mark": {"type": "bar", "cornerRadiusEnd": 6},
            "encoding": {
                "x": {"field": "flow", "type": "nominal", "title": None, "sort": None},
                "y": {"field": "recovery_rate_percent", "type": "quantitative", "title": "Recovery rate (%)", "scale": {"domain": [0, 100]}},
                "color": {"field": "flow", "type": "nominal", "scale": {"domain": ["Compliant", "Naive"], "range": ["#2b55d4", "#d5deeb"]}, "legend": None},
                "tooltip": [
                    {"field": "flow", "type": "nominal"},
                    {"field": "recovered_count", "type": "quantitative", "title": "Recovered"},
                    {"field": "recovery_rate_percent", "type": "quantitative", "title": "Rate", "format": ".1f"},
                ],
            },
            "height": 310,
        })
    with right:
        st.subheader("Measured value")
        st.metric("Compliant recovered", money(comparison["compliant"]["recovered_amount_paise"]))
        st.metric("Naive recovered", money(comparison["naive"]["recovered_amount_paise"]))
        st.metric("Additional recovered", money(delta["recovered_amount_paise"]))
        st.caption("Both flows use the same batch and paired latent customer response. Values are synthetic demo measurements.")

    st.subheader("Recovery by root cause")
    chart({
        "data": {"values": data.category_rows},
        "transform": [{"fold": ["recovered", "unresolved"], "as": ["outcome", "transactions"]}],
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "y": {"field": "category", "type": "nominal", "title": None, "sort": "-x"},
            "x": {"field": "transactions", "type": "quantitative", "title": "Transactions"},
            "color": {"field": "outcome", "type": "nominal", "scale": {"domain": ["recovered", "unresolved"], "range": ["#16a085", "#e4e9f1"]}, "title": None},
            "tooltip": [
                {"field": "category", "type": "nominal"},
                {"field": "outcome", "type": "nominal"},
                {"field": "transactions", "type": "quantitative"},
            ],
        },
        "height": 280,
    })

with lifecycle_tab:
    a, b, c, d = st.columns(4)
    a.metric("Lifecycle recovered", f"{lifecycle['recovered_count']} / {lifecycle['transactions']}")
    b.metric("Recovered value", money(lifecycle["recovered_amount_paise"]))
    c.metric("Average recovery time", f"{lifecycle['average_time_to_recovery_hours']:.1f} h")
    d.metric("Audited decisions", f"{lifecycle['audit_event_count']:,}")

    left, right = st.columns(2)
    with left:
        st.subheader("Final states")
        chart({
            "data": {"values": data.outcome_rows},
            "mark": {"type": "arc", "innerRadius": 62},
            "encoding": {
                "theta": {"field": "transactions", "type": "quantitative"},
                "color": {"field": "state", "type": "nominal", "scale": {"range": ["#16a085", "#e59b27", "#d65858"]}, "title": None},
                "tooltip": [{"field": "state"}, {"field": "transactions"}],
            },
            "height": 290,
        })
    with right:
        st.subheader("Honest exceptions")
        chart({
            "data": {"values": data.reason_rows},
            "mark": {"type": "bar", "color": "#e59b27", "cornerRadiusEnd": 5},
            "encoding": {
                "y": {"field": "reason", "type": "nominal", "title": None, "sort": "-x"},
                "x": {"field": "transactions", "type": "quantitative", "title": "Transactions"},
                "tooltip": [{"field": "reason"}, {"field": "transactions"}],
            },
            "height": 290,
        })

    st.subheader("Notification evidence")
    purpose = st.selectbox(
        "Message type",
        sorted({str(row["purpose"]) for row in data.notifications}),
    )
    samples = [row for row in data.notifications if row["purpose"] == purpose]
    if samples:
        sample = samples[0]
        st.info(sample["response"])
        st.caption(
            f"{sample['provider']} · {sample['model']} · validation: {sample['validation_status']}"
        )
        with st.expander("View the exact prompt"):
            st.code(sample["prompt"], language=None)

with audit_tab:
    st.subheader("Trace one recovery from evidence to outcome")
    query = st.text_input("Filter transaction ID", placeholder="txn_42_")
    options = [item for item in data.transaction_ids if query.lower() in item.lower()]
    if not options:
        st.warning("No matching transaction.")
    else:
        transaction_id = st.selectbox("Transaction", options)
        result = next(
            row for row in data.lifecycle_results
            if row["transaction_id"] == transaction_id
        )
        x, y, z = st.columns(3)
        x.metric("Category", result["category"])
        y.metric("Final state", result["final_state"])
        z.metric("Attempts", result["final_attempt_number"])

        events = data.events_for(transaction_id)
        for event in events:
            rationale = event.get("metadata", {}).get("rationale")
            detail = f" · {rationale}" if rationale else ""
            st.markdown(
                f"<div class='trace-step'><b>{event['event_type']}</b> — {event['reason_code']}"
                f"<br><small>{event['timestamp']} · {event['actor']}{detail}</small></div>",
                unsafe_allow_html=True,
            )
        with st.expander("Machine-readable trace"):
            st.dataframe(events, width="stretch", hide_index=True)

        related_messages = data.notifications_for(transaction_id)
        if related_messages:
            st.markdown("**Customer messages drafted**")
            for message in related_messages:
                st.success(message["response"])

with live_tab:
    st.subheader("Verified Test Mode events")
    st.caption(
        "PII-minimized decisions produced from signed Razorpay webhooks. "
        "Razorpay remains the retry owner; this agent never creates a duplicate debit."
    )
    base_url = os.environ.get(
        "WEBHOOK_API_BASE_URL", "https://mandate-recovery-webhook.onrender.com"
    ).rstrip("/")
    try:
        request = urllib.request.Request(
            f"{base_url}/recoveries/recent?limit=20",
            headers={"User-Agent": "mandate-recovery-dashboard/1.0"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            live_payload = json.load(response)
        live_rows = list(live_payload.get("recoveries", []))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
        st.warning("The live webhook feed is temporarily unavailable.")
        st.caption(str(error))
        live_rows = []

    if not live_rows:
        st.info("No processed live events are available yet.")
    else:
        a, b, c = st.columns(3)
        a.metric("Live events", len(live_rows))
        b.metric(
            "Pending failures",
            sum(row.get("event") == "subscription.pending" for row in live_rows),
        )
        c.metric(
            "Agent decisions",
            sum(bool(row.get("tool_result")) for row in live_rows),
        )
        for row in live_rows:
            classification = row.get("classification") or {}
            tool_result = row.get("tool_result") or {}
            with st.expander(
                f"{row.get('event')} · {row.get('subscription_id')} · "
                f"{row.get('processing_status')}"
            ):
                st.write(
                    {
                        "received_at": row.get("received_at"),
                        "subscription_status": row.get("subscription_status"),
                        "category": classification.get("predicted_category"),
                        "classification_reason": classification.get("reason"),
                        "decision_provider": row.get("decision_provider"),
                        "decision_model": row.get("decision_model"),
                        "action": tool_result.get("tool_name"),
                        "action_status": tool_result.get("status"),
                        "reason_code": tool_result.get("reason_code"),
                        "audit_chain_valid": row.get("audit_chain_valid"),
                        "audit_event_count": row.get("audit_event_count"),
                    }
                )

st.caption(
    f"Run {lifecycle['run_id']} · decision model {lifecycle['decision_model']} · "
    f"notification model {lifecycle['notification_model']} · seed {lifecycle['seed']}"
)
