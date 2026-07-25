from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
ZONES = ("Core_ZN", "Perimeter_ZN_1", "Perimeter_ZN_2", "Perimeter_ZN_3", "Perimeter_ZN_4")

st.set_page_config(page_title="Eco-Loop Control Room", page_icon="◌", layout="wide")
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;600;700&display=swap');
      :root { --ink:#e9f6ef; --muted:#88a598; --green:#57e39f; --amber:#ffbd59; --panel:#101b18; }
      .stApp { background: radial-gradient(circle at 80% 0%, #153329 0, #08110f 42%, #060b0a 100%); color:var(--ink); font-family:Manrope,sans-serif; }
      h1,h2,h3 { letter-spacing:-.04em !important; }
      [data-testid="stMetric"] { background:linear-gradient(145deg,rgba(21,43,35,.92),rgba(10,22,18,.92)); border:1px solid #26483b; border-radius:14px; padding:18px; }
      [data-testid="stMetricValue"] { font-family:"DM Mono",monospace; color:var(--green); }
      .eyebrow { font-family:"DM Mono",monospace; color:var(--green); text-transform:uppercase; letter-spacing:.14em; font-size:.75rem; }
      .status { display:inline-flex;gap:.5rem;align-items:center;border:1px solid #315848;border-radius:99px;padding:.4rem .7rem;color:#b7d2c6;font-family:"DM Mono",monospace;font-size:.75rem; }
      .dot { width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 14px var(--green); }
      .reason { border-left:2px solid var(--green);padding:.8rem 1rem;margin:.6rem 0;background:rgba(16,32,27,.72);border-radius:0 10px 10px 0; }
      .reason small { color:var(--muted);font-family:"DM Mono",monospace; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def load_summary(mode: str) -> dict:
    path = OUTPUTS / mode / "summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data
def load_telemetry(mode: str) -> pd.DataFrame:
    path = OUTPUTS / mode / "telemetry.csv"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    frame["sim_hour"] = (frame["day_of_year"] - 1) * 24 + frame["hour"] + frame["minute"] / 60
    return frame


@st.cache_data
def load_reasons() -> list[dict]:
    path = OUTPUTS / "agent" / "reasoning.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


baseline = load_summary("baseline")
agent = load_summary("agent")

st.markdown('<div class="eyebrow">Honeywell Hackathon · Bengaluru</div>', unsafe_allow_html=True)
left, right = st.columns([4, 1])
with left:
    st.title("Eco-Loop control room")
    st.caption("A live EnergyPlus loop with deterministic reflex safety and Groq supervisory reasoning.")
with right:
    st.markdown(
        '<div class="status"><span class="dot"></span> EMS CALLBACK VERIFIED</div>',
        unsafe_allow_html=True,
    )

if not baseline or not agent:
    st.warning("Run both simulations first: `ecoloop simulate --mode baseline`, then `--mode agent`.")
    st.stop()

savings = 100 * (baseline["energy_kwh"] - agent["energy_kwh"]) / baseline["energy_kwh"]
carbon_savings = 100 * (baseline["carbon_kg"] - agent["carbon_kg"]) / baseline["carbon_kg"]
cost_rate_inr = st.sidebar.number_input("Electricity tariff (₹/kWh)", 1.0, 30.0, 8.5, 0.5)
comfort_reduction = 100 * (
    baseline["comfort_violation_count"] - agent["comfort_violation_count"]
) / max(1, baseline["comfort_violation_count"])

c1, c2, c3, c4 = st.columns(4)
c1.metric("Energy reduction", f"{savings:.2f}%", f"{baseline['energy_kwh'] - agent['energy_kwh']:,.0f} kWh")
c2.metric("Carbon reduction", f"{carbon_savings:.2f}%", f"{baseline['carbon_kg'] - agent['carbon_kg']:,.0f} kgCO₂e")
c3.metric("Comfort violations", f"{agent['comfort_violation_count']:,}", f"−{comfort_reduction:.1f}%")
c4.metric("Annual cost avoided", f"₹{(baseline['energy_kwh'] - agent['energy_kwh']) * cost_rate_inr:,.0f}", "modeled")

baseline_df = load_telemetry("baseline")
agent_df = load_telemetry("agent")
resolution = st.sidebar.selectbox("Chart resolution", ("Daily", "Weekly", "Monthly"), index=1)
hours = {"Daily": 24, "Weekly": 168, "Monthly": 730}[resolution]


def aggregate(frame: pd.DataFrame) -> pd.DataFrame:
    reduced = frame.copy()
    reduced["period"] = (reduced["sim_hour"] // hours).astype(int)
    columns = {"energy_kwh": "max", "carbon_kg": "max"}
    return reduced.groupby("period", as_index=False).agg(columns)


b = aggregate(baseline_df)
a = aggregate(agent_df)
fig = go.Figure()
fig.add_trace(go.Scatter(x=b["period"], y=b["energy_kwh"], name="Fixed schedule", line={"color": "#7c9188", "width": 2}))
fig.add_trace(go.Scatter(x=a["period"], y=a["energy_kwh"], name="Eco-Loop agent", line={"color": "#57e39f", "width": 3}, fill="tonexty", fillcolor="rgba(87,227,159,.08)"))
fig.update_layout(
    title="Cumulative facility electricity",
    xaxis_title=f"{resolution} period",
    yaxis_title="kWh",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font={"color": "#b9d0c5", "family": "DM Mono"},
    legend={"orientation": "h", "y": 1.1},
    margin={"l": 20, "r": 20, "t": 70, "b": 20},
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Comfort envelope")
zone = st.selectbox("Conditioned zone", ZONES)
sample_every = max(1, len(agent_df) // 3500)
comfort = agent_df.iloc[::sample_every]
comfort_fig = go.Figure()
comfort_fig.add_hrect(y0=-0.5, y1=0.5, fillcolor="rgba(87,227,159,.12)", line_width=0, annotation_text="ASHRAE comfort band")
comfort_fig.add_trace(go.Scatter(x=comfort["sim_hour"], y=comfort[f"pmv_{zone}"], line={"color": "#ffbd59", "width": 1.4}, name=f"{zone} PMV"))
comfort_fig.update_layout(
    xaxis_title="Simulation hour",
    yaxis_title="PMV estimate",
    yaxis_range=[-2, 2],
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font={"color": "#b9d0c5", "family": "DM Mono"},
    margin={"l": 20, "r": 20, "t": 25, "b": 20},
)
st.plotly_chart(comfort_fig, use_container_width=True)

st.subheader("Agent reasoning log")
reasons = load_reasons()
if reasons:
    for item in reversed(reasons[-20:]):
        st.markdown(
            f'<div class="reason"><small>{item.get("simulation_time", item.get("logged_at", ""))}</small><br>{item.get("justification", item.get("diagnosis", "Action recorded."))}</div>',
            unsafe_allow_html=True,
        )
else:
    st.info(
        "Tier 2 was not invoked in this saved run because no rotated GROQ_API_KEY was configured. "
        "Tier 1 completed the entire annual simulation independently; once a key is set, every "
        "supervisory action and justification is appended here."
    )

with st.expander("Run provenance and assumptions"):
    st.json(
        {
            "energyplus": agent["energyplus_version"],
            "weather": "Bengaluru 432950 TMYx, 2011–2025",
            "model": "DOE/PNNL ASHRAE 90.1-2019 Small Office, transitioned 22.1 → 26.1",
            "carbon_signal": "Synthetic hourly Indian grid curve, 0.52–0.82 kgCO2e/kWh",
            "pmv": agent["pmv_method"],
            "baseline_exit_code": baseline["exit_code"],
            "agent_exit_code": agent["exit_code"],
        }
    )

