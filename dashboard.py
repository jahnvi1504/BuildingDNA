from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
ZONES = ("Core_ZN", "Perimeter_ZN_1", "Perimeter_ZN_2", "Perimeter_ZN_3", "Perimeter_ZN_4")
MODE_COLORS = {
    "Energy Saver": "#57e39f",
    "Balanced": "#4bb7d8",
    "Comfort Priority": "#ffbd59",
}

st.set_page_config(page_title="Eco-Loop Control Room", page_icon="◉", layout="wide")
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;600;700;800&display=swap');
      :root { --ink:#eef8f3; --muted:#8eaaa0; --green:#57e39f; --cyan:#4bb7d8; --amber:#ffbd59; --panel:#101c18; --line:#28483c; }
      .stApp { background:radial-gradient(circle at 82% -8%,#183d30 0,#091511 38%,#060b0a 100%); color:var(--ink); font-family:Manrope,sans-serif; }
      .block-container { max-width:1500px; padding-top:1.8rem; padding-bottom:4rem; }
      h1,h2,h3 { letter-spacing:-.045em !important; }
      h1 { font-weight:800 !important; font-size:clamp(2.2rem,5vw,4.6rem) !important; line-height:.95 !important; }
      [data-testid="stSidebar"] { background:#08110f; border-right:1px solid #1d362d; }
      [data-testid="stPlotlyChart"] { background:linear-gradient(145deg,rgba(18,34,29,.9),rgba(7,15,13,.9)); border:1px solid var(--line); border-radius:18px; padding:8px; }
      .brand { font:500 .72rem "DM Mono"; color:var(--green); letter-spacing:.15em; text-transform:uppercase; }
      .trust { display:inline-flex;gap:.55rem;align-items:center;border:1px solid #315848;border-radius:99px;padding:.48rem .75rem;color:#c7ddd3;font:500 .72rem "DM Mono"; white-space:nowrap; }
      .dot { width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 14px var(--green);animation:pulse 2s infinite; }
      @keyframes pulse { 50% { opacity:.45;transform:scale(.8); } }
      .policy-hero { background:linear-gradient(120deg,rgba(25,58,46,.96),rgba(10,24,20,.96));border:1px solid #35614f;border-radius:18px;padding:1.15rem 1.3rem;margin:.7rem 0 1.25rem;display:flex;align-items:center;justify-content:space-between;gap:1rem;box-shadow:0 12px 40px rgba(0,0,0,.2); }
      .policy-label { font:500 .68rem "DM Mono";color:#9eb8ad;letter-spacing:.12em;text-transform:uppercase; }
      .policy-mode { font-size:clamp(1.35rem,2.4vw,2.15rem);font-weight:800;letter-spacing:-.04em; }
      .policy-meta { color:#abc1b8;font:500 .78rem "DM Mono";text-align:right; }
      .kpi-grid { display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.85rem;margin:.7rem 0 1.4rem; }
      .kpi { min-width:0;background:linear-gradient(145deg,rgba(21,43,35,.96),rgba(9,20,17,.96));border:1px solid var(--line);border-radius:16px;padding:1rem 1.05rem;transition:transform .22s,border-color .22s; }
      .kpi:hover { transform:translateY(-2px);border-color:#4a7865; }
      .kpi-label { font:500 .67rem "DM Mono";color:#93aea3;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap; }
      .kpi-value { color:var(--green);font:500 clamp(1.35rem,2.2vw,2.2rem) "DM Mono";letter-spacing:-.06em;white-space:nowrap;margin:.38rem 0 .22rem; }
      .kpi-context { color:#94aaa1;font-size:.76rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }
      .replay-strip { border:1px solid #305444;border-radius:16px;padding:.85rem 1rem;background:rgba(10,24,20,.82);margin:.4rem 0 1rem; }
      .replay-label { display:inline-flex;align-items:center;gap:.45rem;color:var(--cyan);font:500 .72rem "DM Mono";letter-spacing:.1em;text-transform:uppercase; }
      .live-value { border-left:2px solid var(--green);padding:.7rem .9rem;background:rgba(15,31,26,.8);border-radius:0 10px 10px 0;min-height:92px; }
      .live-value small { color:var(--muted);font:500 .67rem "DM Mono";letter-spacing:.06em;text-transform:uppercase; }
      .live-value strong { display:block;color:var(--ink);font:500 1.45rem "DM Mono";margin-top:.25rem; }
      .reason { border-left:2px solid var(--green);padding:.8rem 1rem;margin:.6rem 0;background:rgba(16,32,27,.78);border-radius:0 10px 10px 0; }
      .reason small { color:var(--muted);font:500 .7rem "DM Mono"; }
      .reason-mode { display:inline-block;border:1px solid #365c4c;border-radius:99px;padding:.15rem .45rem;margin-left:.4rem;color:#b9d3c8; }
      .section-kicker { color:var(--green);font:500 .68rem "DM Mono";letter-spacing:.12em;text-transform:uppercase;margin-top:1.4rem; }
      @media (max-width:1000px) { .kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr));}.policy-hero{align-items:flex-start;flex-direction:column}.policy-meta{text-align:left;} }
      @media (max-width:620px) { .kpi-grid{grid-template-columns:1fr}.block-container{padding-left:1rem;padding-right:1rem}.kpi-value{font-size:1.8rem;} }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def load_summary(mode: str) -> dict[str, Any]:
    path = OUTPUTS / mode / "summary.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@st.cache_data
def load_telemetry(mode: str) -> pd.DataFrame:
    path = OUTPUTS / mode / "telemetry.csv"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    frame["sim_hour"] = (
        (frame["day_of_year"] - 1) * 24 + frame["hour"] + frame["minute"] / 60
    ).clip(0, 8759.999)
    frame["hour_bin"] = frame["sim_hour"].astype(int)
    return frame


@st.cache_data
def hourly_replay(mode: str) -> pd.DataFrame:
    frame = load_telemetry(mode)
    if frame.empty:
        return frame
    value_columns = [
        *(f"temp_{zone}" for zone in ZONES),
        *(f"pmv_{zone}" for zone in ZONES),
        "heating_setpoint_c",
        "cooling_setpoint_c",
    ]
    aggregations = {column: "last" for column in value_columns}
    aggregations.update(
        {
            "energy_kwh": "max",
            "carbon_kg": "max",
            "comfort_violation_count": "max",
        }
    )
    hourly = frame.groupby("hour_bin", as_index=False).agg(aggregations)
    hourly["hourly_kwh"] = hourly["energy_kwh"].diff().clip(lower=0).fillna(0)
    hourly["day"] = hourly["hour_bin"] // 24 + 1
    return hourly


@st.cache_data
def load_policy() -> pd.DataFrame:
    path = OUTPUTS / "agent" / "policy_log.jsonl"
    if not path.exists():
        return pd.DataFrame()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return pd.DataFrame(rows)


def simulation_hour(value: str) -> int | None:
    if not value.startswith("day-"):
        return None
    try:
        day_text, clock = value.split()
        day = int(day_text.removeprefix("day-"))
        hour, minute = (int(part) for part in clock.split(":"))
        return min(8759, (day - 1) * 24 + hour + minute // 60)
    except (TypeError, ValueError):
        return None


@st.cache_data
def load_reasons() -> pd.DataFrame:
    path = OUTPUTS / "agent" / "reasoning.jsonl"
    if not path.exists():
        return pd.DataFrame()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["simulated_hour"] = frame.get("simulation_time", "").map(simulation_hour)
    return frame


def compact(value: float, unit: str = "") -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.2f}M{unit}"
    if absolute >= 1_000:
        return f"{value / 1_000:.2f}k{unit}"
    return f"{value:,.1f}{unit}"


def active_policy(policy: pd.DataFrame, hour: int) -> pd.Series:
    eligible = policy[policy["simulated_hour"] <= hour]
    return eligible.iloc[-1] if not eligible.empty else policy.iloc[0]


def add_policy_markers(fig: go.Figure, switches: pd.DataFrame) -> None:
    for row in switches.itertuples(index=False):
        fig.add_vline(
            x=row.simulated_hour,
            line_width=1,
            line_dash="dot",
            line_color=MODE_COLORS.get(row.mode, "#57e39f"),
            opacity=0.5,
        )


def chart_layout(fig: go.Figure, title: str, y_title: str) -> None:
    fig.update_layout(
        title=title,
        xaxis_title="Simulation hour",
        yaxis_title=y_title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#b9d0c5", "family": "DM Mono"},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.12},
        margin={"l": 18, "r": 18, "t": 70, "b": 20},
        transition={"duration": 280, "easing": "cubic-in-out"},
    )
    fig.update_xaxes(gridcolor="rgba(92,130,113,.12)")
    fig.update_yaxes(gridcolor="rgba(92,130,113,.12)")


def selected_hour(event: Any) -> int | None:
    try:
        point = event.selection.points[0]
        custom = point.get("customdata")
        return int(custom[0] if isinstance(custom, list) else custom)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None


baseline = load_summary("baseline")
agent = load_summary("agent")
baseline_hourly = hourly_replay("baseline")
agent_hourly = hourly_replay("agent")
policy = load_policy()
reasons = load_reasons()

st.markdown('<div class="brand">Honeywell Hackathon · Bengaluru</div>', unsafe_allow_html=True)
hero_left, hero_right = st.columns([4, 1])
with hero_left:
    st.title("Eco-Loop control room")
    st.caption(
        "Verified EnergyPlus telemetry, adaptive macro-policy scoring, and explainable control replay."
    )
with hero_right:
    st.markdown(
        '<div class="trust"><span class="dot"></span> EMS CALLBACK VERIFIED</div>',
        unsafe_allow_html=True,
    )

if (
    not baseline
    or not agent
    or baseline_hourly.empty
    or agent_hourly.empty
    or policy.empty
):
    st.warning(
        "Saved telemetry and policy output are required. Run both simulations, then "
        "`ecoloop policy-evaluate`."
    )
    st.stop()

if "replay_hour" not in st.session_state:
    st.session_state.replay_hour = 0
if "playing" not in st.session_state:
    st.session_state.playing = False
if "replay_speed" not in st.session_state:
    st.session_state.replay_speed = 24
if "pending_hour" in st.session_state:
    st.session_state.replay_hour = st.session_state.pop("pending_hour")

current_policy = active_policy(policy, int(st.session_state.replay_hour))
current_index = int(current_policy.name)
previous_score = policy.iloc[max(0, current_index - 1)]["rolling_score"]
trend = "↗" if current_policy["rolling_score"] > previous_score else "↘"
profile = current_policy.get("profile", {})

st.markdown(
    f"""
    <div class="policy-hero">
      <div>
        <div class="policy-label">Active macro-policy · replay hour {int(st.session_state.replay_hour):,}</div>
        <div class="policy-mode" style="color:{MODE_COLORS[current_policy['mode']]}">{html.escape(current_policy['mode'])}</div>
      </div>
      <div class="policy-meta">
        Episode {int(current_policy['episode'])} / {len(policy)} &nbsp;·&nbsp;
        rolling score {current_policy['rolling_score']:.2f} {trend}<br>
        PMV target {profile.get('comfort_band', ['—','—'])[0]} to {profile.get('comfort_band', ['—','—'])[1]}
        &nbsp;·&nbsp; max drift {profile.get('max_setpoint_drift_c', '—')}°C
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

savings = 100 * (baseline["energy_kwh"] - agent["energy_kwh"]) / baseline["energy_kwh"]
carbon_savings = 100 * (baseline["carbon_kg"] - agent["carbon_kg"]) / baseline["carbon_kg"]
comfort_reduction = 100 * (
    baseline["comfort_violation_count"] - agent["comfort_violation_count"]
) / max(1, baseline["comfort_violation_count"])

st.sidebar.markdown("### View controls")
zone = st.sidebar.selectbox("Conditioned zone", ZONES)
resolution = st.sidebar.selectbox("Chart resolution", ("Daily", "Weekly", "Monthly"), index=1)
all_modes = list(MODE_COLORS)
mode_filter = st.sidebar.multiselect("Macro-policy modes", all_modes, default=all_modes)
overlay = st.sidebar.toggle("Overlay baseline and agent", value=False)
cost_rate_inr = st.sidebar.number_input("Electricity tariff (₹/kWh)", 1.0, 30.0, 8.5, 0.5)

energy_delta = baseline["energy_kwh"] - agent["energy_kwh"]
carbon_delta = baseline["carbon_kg"] - agent["carbon_kg"]
cost_avoided = energy_delta * cost_rate_inr
st.markdown(
    f"""
    <div class="kpi-grid">
      <div class="kpi" title="Exact annual electricity reduction: {energy_delta:,.4f} kWh">
        <div class="kpi-label">Energy reduction</div><div class="kpi-value">{savings:.2f}%</div>
        <div class="kpi-context">{compact(energy_delta, ' kWh')} avoided</div>
      </div>
      <div class="kpi" title="Exact annual carbon reduction: {carbon_delta:,.4f} kgCO₂e">
        <div class="kpi-label">Carbon reduction</div><div class="kpi-value">{carbon_savings:.2f}%</div>
        <div class="kpi-context">{compact(carbon_delta, ' kg')} CO₂e avoided</div>
      </div>
      <div class="kpi" title="Agent violations: {agent['comfort_violation_count']:,}; baseline: {baseline['comfort_violation_count']:,}">
        <div class="kpi-label">Comfort violations</div><div class="kpi-value">{compact(agent['comfort_violation_count'])}</div>
        <div class="kpi-context">{comfort_reduction:.1f}% fewer zone-timesteps</div>
      </div>
      <div class="kpi" title="Exact modeled annual cost avoided: ₹{cost_avoided:,.2f}">
        <div class="kpi-label">Annual cost avoided</div><div class="kpi-value">₹{compact(cost_avoided)}</div>
        <div class="kpi-context">modeled at ₹{cost_rate_inr:.2f}/kWh</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

mode_intervals = policy[["simulated_hour", "mode"]].sort_values("simulated_hour")
switches = mode_intervals[mode_intervals["mode"].ne(mode_intervals["mode"].shift())]


@st.fragment(run_every=0.8 if st.session_state.playing else None)
def replay_panel() -> None:
    if st.session_state.playing:
        st.session_state.replay_hour = min(
            8759, st.session_state.replay_hour + int(st.session_state.replay_speed)
        )
        if st.session_state.replay_hour >= 8759:
            st.session_state.playing = False

    st.markdown(
        '<div class="replay-strip"><span class="replay-label">▶ Simulated Year Replay</span>'
        '<br><small>Replay of the completed, callback-verified EnergyPlus run — not live telemetry.</small></div>',
        unsafe_allow_html=True,
    )
    controls = st.columns([1, 1, 2, 8])
    if controls[0].button("▶ Play", use_container_width=True, disabled=st.session_state.playing):
        st.session_state.playing = True
        st.rerun(scope="app")
    if controls[1].button("Ⅱ Pause", use_container_width=True, disabled=not st.session_state.playing):
        st.session_state.playing = False
        st.rerun(scope="app")
    controls[2].selectbox(
        "Replay speed",
        (1, 6, 24, 168),
        index=2,
        format_func=lambda value: f"{value} sim h/tick",
        key="replay_speed",
        label_visibility="collapsed",
    )
    controls[3].slider(
        "Simulation hour",
        0,
        8759,
        key="replay_hour",
        help="Drag across the completed simulated year.",
    )

    hour = int(st.session_state.replay_hour)
    agent_row = agent_hourly.iloc[(agent_hourly["hour_bin"] - hour).abs().argsort()[:1]].iloc[0]
    baseline_row = baseline_hourly.iloc[
        (baseline_hourly["hour_bin"] - hour).abs().argsort()[:1]
    ].iloc[0]
    policy_row = active_policy(policy, hour)
    prior_reasons = reasons[
        reasons["simulated_hour"].notna() & (reasons["simulated_hour"] <= hour)
    ]
    active_reason = prior_reasons.iloc[-1] if not prior_reasons.empty else None

    st.caption(
        f"Day {hour // 24 + 1:03d} · {hour % 24:02d}:00 · "
        f"{policy_row['mode']} · Episode {int(policy_row['episode'])}"
    )
    values = st.columns(5)
    cards = [
        ("Zone temperature", f"{agent_row[f'temp_{zone}']:.2f} °C"),
        ("PMV estimate", f"{agent_row[f'pmv_{zone}']:+.2f}"),
        ("Hourly electricity", f"{agent_row['hourly_kwh']:.2f} kWh"),
        ("Cumulative energy", f"{agent_row['energy_kwh']:,.1f} kWh"),
        ("Baseline delta", f"{baseline_row['energy_kwh'] - agent_row['energy_kwh']:+,.1f} kWh"),
    ]
    for column, (label, value) in zip(values, cards, strict=True):
        column.markdown(
            f'<div class="live-value"><small>{label}</small><strong>{value}</strong></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-kicker">Replay telemetry</div>', unsafe_allow_html=True)
    replay_window = agent_hourly[
        (agent_hourly["hour_bin"] >= max(0, hour - 168))
        & (agent_hourly["hour_bin"] <= min(8759, hour + 168))
    ].copy()
    baseline_window = baseline_hourly[
        (baseline_hourly["hour_bin"] >= max(0, hour - 168))
        & (baseline_hourly["hour_bin"] <= min(8759, hour + 168))
    ]
    replay_window = pd.merge_asof(
        replay_window.sort_values("hour_bin"),
        mode_intervals.rename(columns={"simulated_hour": "policy_hour"}).sort_values(
            "policy_hour"
        ),
        left_on="hour_bin",
        right_on="policy_hour",
        direction="backward",
    )
    replay_window = replay_window[replay_window["mode"].isin(mode_filter)]

    temperature_fig = go.Figure()
    if overlay:
        temperature_fig.add_trace(
            go.Scatter(
                x=baseline_window["hour_bin"],
                y=baseline_window[f"temp_{zone}"],
                customdata=baseline_window[["hour_bin"]],
                name="Fixed schedule",
                line={"color": "#7c9188", "width": 2},
                hovertemplate="%{y:.2f}°C<extra>Fixed schedule</extra>",
            )
        )
    temperature_fig.add_trace(
        go.Scatter(
            x=replay_window["hour_bin"],
            y=replay_window[f"temp_{zone}"],
            customdata=replay_window[["hour_bin"]],
            name="Eco-Loop",
            line={"color": "#57e39f", "width": 2.5},
            hovertemplate="%{y:.2f}°C<extra>Eco-Loop</extra>",
        )
    )
    temperature_fig.add_vline(x=hour, line_color="#ffffff", line_width=1.5)
    add_policy_markers(
        temperature_fig,
        switches[
            (switches["simulated_hour"] >= max(0, hour - 168))
            & (switches["simulated_hour"] <= min(8759, hour + 168))
        ],
    )
    chart_layout(temperature_fig, f"{zone} temperature · ±7 day window", "Temperature (°C)")
    event = st.plotly_chart(
        temperature_fig,
        use_container_width=True,
        key="replay_temperature",
        on_select="rerun",
        selection_mode="points",
    )
    clicked = selected_hour(event)
    if clicked is not None and clicked != hour:
        st.session_state.pending_hour = clicked
        st.rerun(scope="app")

    reason_text = (
        active_reason.get("justification", active_reason.get("diagnosis", "Action recorded."))
        if active_reason is not None
        else "No Tier 2 reasoning event was logged at or before this simulated hour."
    )
    st.markdown(
        f'<div class="reason"><small>Active reasoning at hour {hour:,}'
        f'<span class="reason-mode">{html.escape(policy_row["mode"])}</span></small><br>'
        f'{html.escape(str(reason_text))}</div>',
        unsafe_allow_html=True,
    )


replay_panel()

st.markdown('<div class="section-kicker">Annual performance</div>', unsafe_allow_html=True)
hours_per_period = {"Daily": 24, "Weekly": 168, "Monthly": 730}[resolution]


def period_consumption(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["period"] = result["hour_bin"] // hours_per_period
    grouped = result.groupby("period", as_index=False).agg(
        simulated_hour=("hour_bin", "max"),
        cumulative_kwh=("energy_kwh", "max"),
        samples=("hour_bin", "size"),
    )
    grouped["period_kwh"] = grouped["cumulative_kwh"].diff()
    expected = hours_per_period
    return grouped[grouped["period_kwh"].notna() & (grouped["samples"] >= expected * 0.5)]


baseline_periods = period_consumption(baseline_hourly)
agent_periods = period_consumption(agent_hourly)
agent_periods = pd.merge_asof(
    agent_periods.sort_values("simulated_hour"),
    mode_intervals.sort_values("simulated_hour"),
    on="simulated_hour",
    direction="backward",
)
agent_periods = agent_periods[agent_periods["mode"].isin(mode_filter)]
baseline_periods = baseline_periods[
    baseline_periods["period"].isin(agent_periods["period"])
]

energy_fig = go.Figure()
if overlay:
    energy_fig.add_trace(
        go.Scatter(
            x=baseline_periods["simulated_hour"],
            y=baseline_periods["period_kwh"],
            customdata=baseline_periods[["simulated_hour"]],
            name="Fixed schedule",
            line={"color": "#9aaca4", "width": 2},
            hovertemplate="%{y:,.2f} kWh<extra>Fixed schedule</extra>",
        )
    )
    energy_fig.add_trace(
        go.Scatter(
            x=agent_periods["simulated_hour"],
            y=agent_periods["period_kwh"],
            customdata=agent_periods[["simulated_hour"]],
            name="Eco-Loop agent",
            line={"color": "#57e39f", "width": 2.5},
            fill="tonexty",
            fillcolor="rgba(87,227,159,.08)",
            hovertemplate="%{y:,.2f} kWh<extra>Eco-Loop agent</extra>",
        )
    )
else:
    energy_fig.add_trace(
        go.Bar(
            x=baseline_periods["simulated_hour"],
            y=baseline_periods["period_kwh"],
            customdata=baseline_periods[["simulated_hour"]],
            name="Fixed schedule",
            marker_color="#7c9188",
            opacity=0.78,
            hovertemplate="%{y:,.2f} kWh<extra>Fixed schedule</extra>",
        )
    )
    energy_fig.add_trace(
        go.Bar(
            x=agent_periods["simulated_hour"],
            y=agent_periods["period_kwh"],
            customdata=agent_periods[["simulated_hour"]],
            name="Eco-Loop agent",
            marker_color="#57e39f",
            opacity=0.86,
            hovertemplate="%{y:,.2f} kWh<extra>Eco-Loop agent</extra>",
        )
    )
    energy_fig.update_layout(barmode="group")
add_policy_markers(energy_fig, switches[switches["mode"].isin(mode_filter)])
chart_layout(
    energy_fig,
    f"Facility electricity per {resolution.lower()} period",
    "Period electricity (kWh)",
)
energy_event = st.plotly_chart(
    energy_fig,
    use_container_width=True,
    key="annual_energy",
    on_select="rerun",
    selection_mode="points",
)
energy_clicked = selected_hour(energy_event)
if energy_clicked is not None:
    st.session_state.pending_hour = energy_clicked
    st.rerun()

comfort = agent_hourly.copy()
comfort = pd.merge_asof(
    comfort.sort_values("hour_bin"),
    mode_intervals.rename(columns={"simulated_hour": "policy_hour"}).sort_values("policy_hour"),
    left_on="hour_bin",
    right_on="policy_hour",
    direction="backward",
)
comfort = comfort[comfort["mode"].isin(mode_filter)]
sample_every = {"Daily": 1, "Weekly": 3, "Monthly": 6}[resolution]
comfort = comfort.iloc[::sample_every]
comfort_fig = go.Figure()
comfort_fig.add_hrect(
    y0=-0.5,
    y1=0.5,
    fillcolor="rgba(87,227,159,.12)",
    line_width=0,
    annotation_text="Target comfort envelope",
)
comfort_fig.add_trace(
    go.Scattergl(
        x=comfort["hour_bin"],
        y=comfort[f"pmv_{zone}"],
        customdata=comfort[["hour_bin", "mode"]],
        line={"color": "#ffbd59", "width": 1.35},
        name=f"{zone} PMV",
        hovertemplate="PMV %{y:+.3f}<br>%{customdata[1]}<extra></extra>",
    )
)
add_policy_markers(comfort_fig, switches[switches["mode"].isin(mode_filter)])
chart_layout(comfort_fig, f"{zone} comfort envelope", "PMV estimate")
comfort_fig.update_yaxes(range=[-2, 2])
comfort_event = st.plotly_chart(
    comfort_fig,
    use_container_width=True,
    key="annual_comfort",
    on_select="rerun",
    selection_mode="points",
)
comfort_clicked = selected_hour(comfort_event)
if comfort_clicked is not None:
    st.session_state.pending_hour = comfort_clicked
    st.rerun()

st.markdown('<div class="section-kicker">Policy episodes</div>', unsafe_allow_html=True)
policy_view = policy[policy["mode"].isin(mode_filter)]
policy_fig = go.Figure()
for mode, color in MODE_COLORS.items():
    mode_rows = policy_view[policy_view["mode"] == mode]
    policy_fig.add_trace(
        go.Scatter(
            x=mode_rows["simulated_hour"],
            y=mode_rows["rolling_score"],
            customdata=mode_rows[["simulated_hour", "episode", "mode"]],
            mode="lines+markers",
            name=mode,
            line={"color": color, "width": 2},
            marker={"size": 6},
            hovertemplate=(
                "Episode %{customdata[1]}<br>Rolling score %{y:.3f}"
                "<br>%{customdata[2]}<extra></extra>"
            ),
        )
    )
chart_layout(policy_fig, "Adaptive policy score and mode switches", "Rolling score")
policy_event = st.plotly_chart(
    policy_fig,
    use_container_width=True,
    key="policy_score",
    on_select="rerun",
    selection_mode="points",
)
policy_clicked = selected_hour(policy_event)
if policy_clicked is not None:
    st.session_state.pending_hour = policy_clicked
    st.rerun()

st.markdown('<div class="section-kicker">Reasoning audit trail</div>', unsafe_allow_html=True)
search_col, range_col = st.columns([2, 3])
query = search_col.text_input("Search reasoning", placeholder="Search evidence, action, diagnosis…")
day_range = range_col.slider("Simulated day range", 1, 365, (1, 365))
reason_view = reasons.copy()
if not reason_view.empty:
    reason_view["mode"] = reason_view["simulated_hour"].apply(
        lambda hour: active_policy(policy, int(hour))["mode"] if pd.notna(hour) else "Unmapped"
    )
    reason_view = reason_view[
        reason_view["simulated_hour"].between((day_range[0] - 1) * 24, day_range[1] * 24)
        & reason_view["mode"].isin(mode_filter)
    ]
    if query:
        text = reason_view.apply(lambda row: json.dumps(row.to_dict()), axis=1)
        reason_view = reason_view[text.str.contains(query, case=False, regex=False)]

if reason_view.empty:
    st.info("No Tier 2 reasoning entries match the selected modes, date range, and search.")
else:
    for index, item in reason_view.sort_values("simulated_hour", ascending=False).head(40).iterrows():
        entry, jump = st.columns([8, 1])
        justification = item.get("justification", item.get("diagnosis", "Action recorded."))
        entry.markdown(
            f'<div class="reason"><small>{html.escape(str(item.get("simulation_time", "")))}'
            f'<span class="reason-mode">{html.escape(str(item["mode"]))}</span></small><br>'
            f'{html.escape(str(justification))}</div>',
            unsafe_allow_html=True,
        )
        if jump.button("Jump", key=f"reason-{index}", use_container_width=True):
            st.session_state.pending_hour = int(item["simulated_hour"])
            st.rerun()

with st.expander("Run provenance and assumptions"):
    st.json(
        {
            "view": "Replay of a completed simulation; not live telemetry",
            "energyplus": agent["energyplus_version"],
            "weather": "Bengaluru 432950 TMYx, 2011–2025",
            "model": "DOE/PNNL ASHRAE 90.1-2019 Small Office, transitioned 22.1 → 26.1",
            "carbon_signal": "Synthetic hourly Indian grid curve, 0.52–0.82 kgCO₂e/kWh",
            "pmv": agent["pmv_method"],
            "policy": "48-hour scored state machine; no gradient training or actuator access",
            "score_weights": "45% energy saved, 35% comfort improvement, 20% carbon avoided",
            "baseline_exit_code": baseline["exit_code"],
            "agent_exit_code": agent["exit_code"],
        }
    )
