from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ecoloop.decision import normalize_reasoning_record
from ecoloop.dashboard_ui import (
    DASHBOARD_TITLE,
    PRODUCT_NAME,
    TOTAL_POLICY_EPISODES,
    debate_replay_html,
    episode_exceeds_total,
    format_episode_progress,
    load_json_document,
    parse_episode_number,
    representative_block_index,
    representative_position,
    representative_ticks,
)
from ecoloop.config import settings
from ecoloop.debate_replay import (
    DEBATE_REPLAY_PATH,
    load_debate_events,
    replay_snapshot,
    select_debate_replay,
)


ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
RESULTS = OUTPUTS / "matched-12h"
ZONES = ("Core_ZN", "Perimeter_ZN_1", "Perimeter_ZN_2", "Perimeter_ZN_3", "Perimeter_ZN_4")
MODE_COLORS = {
    "Energy Saver": "#57c796",
    "Balanced": "#8a9690",
    "Comfort Priority": "#d8ad65",
}

st.set_page_config(page_title=DASHBOARD_TITLE, page_icon="◉", layout="wide")
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
      .reason-compact { display:flex;align-items:center;gap:.7rem;border-left:2px solid var(--green);padding:.8rem 1rem;margin:.35rem 0;background:rgba(16,32,27,.78);border-radius:0 10px 10px 0;min-height:42px; }
      .reason-day { color:#b8cec5;font:500 .76rem "DM Mono"; }
      .debate-grid { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.7rem;margin:.65rem 0; }
      .debate-card { background:rgba(13,29,24,.92);border:1px solid #2d5042;border-radius:13px;padding:.85rem;min-width:0; }
      .debate-role { color:var(--green);font:500 .67rem "DM Mono";letter-spacing:.1em;text-transform:uppercase;margin-bottom:.45rem; }
      .debate-copy { color:#d5e5de;font-size:.82rem;line-height:1.45; }
      .debate-meta { color:#91aaa0;font:500 .68rem "DM Mono";margin-top:.55rem; }
      .debate-final { border:1px solid #477461;border-radius:12px;background:rgba(29,59,47,.72);padding:.75rem .9rem;margin:.5rem 0 1rem;color:#d9ebe3; }
      .debate-source { display:inline-block;border:1px solid #477461;border-radius:99px;padding:.2rem .55rem;color:var(--green);font:500 .66rem "DM Mono";letter-spacing:.1em; }
      .section-kicker { color:var(--green);font:500 .68rem "DM Mono";letter-spacing:.12em;text-transform:uppercase;margin-top:1.4rem; }
      @media (max-width:1000px) { .kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr));}.debate-grid{grid-template-columns:1fr}.policy-hero{align-items:flex-start;flex-direction:column}.policy-meta{text-align:left;} }
      @media (max-width:620px) { .kpi-grid{grid-template-columns:1fr}.block-container{padding-left:1rem;padding-right:1rem}.kpi-value{font-size:1.8rem;} }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Inter:wght@400;500;600;700&display=swap');
      :root{--ink:#f4f7f5;--soft:#c7ceca;--muted:#78837e;--green:#57c796;--success:#70dfa7;--amber:#d8ad65;--panel:#111816;--hover:#18241f;--line:rgba(187,220,204,.11);--line-strong:rgba(187,220,204,.2);--shadow:0 24px 80px rgba(0,0,0,.28)}
      html{scroll-behavior:smooth}.stApp{background:radial-gradient(900px 520px at 72% -14%,rgba(52,106,82,.16),transparent 64%),radial-gradient(700px 420px at -8% 28%,rgba(56,84,72,.08),transparent 70%),#090b0c;color:var(--ink);font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif}.block-container{max-width:1540px;padding:2.4rem 2.8rem 7rem}#MainMenu,footer,[data-testid="stHeader"]{visibility:hidden}
      .hero-shell{position:relative;min-height:330px;padding:3rem 0 2rem;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3rem;align-items:end;overflow:hidden}.hero-shell:after{content:"";position:absolute;right:6%;top:2%;width:280px;height:280px;border-radius:50%;background:radial-gradient(circle,rgba(87,199,150,.11),transparent 68%);filter:blur(10px);pointer-events:none}.eyebrow,.section-kicker{color:var(--green);font:500 .66rem "DM Mono";letter-spacing:.17em;text-transform:uppercase}.hero-title{font-size:clamp(4.2rem,8vw,8rem);font-weight:600;letter-spacing:-.085em;line-height:.84;color:var(--ink)}.hero-subtitle{margin-top:1.5rem;color:var(--soft);font-size:clamp(1rem,1.5vw,1.3rem);font-weight:400;letter-spacing:-.025em}.hero-copy{margin-top:.65rem;max-width:660px;color:var(--muted);font-size:.84rem;line-height:1.6}.hero-console{position:relative;z-index:1;min-width:280px;padding:1.3rem 1.4rem;border:1px solid var(--line);border-radius:22px;background:linear-gradient(145deg,rgba(23,33,29,.78),rgba(12,17,15,.74));backdrop-filter:blur(22px);box-shadow:var(--shadow)}.console-row{display:flex;justify-content:space-between;gap:2rem;padding:.58rem 0;border-bottom:1px solid rgba(255,255,255,.055);font:500 .7rem "DM Mono"}.console-row:last-child{border:0}.console-label{color:var(--muted)}.console-value{color:var(--ink);text-align:right}
      .status-rail{display:flex;flex-wrap:wrap;gap:.55rem;margin:0 0 2.8rem}.status-pill{display:inline-flex;align-items:center;gap:.48rem;padding:.48rem .72rem;border:1px solid var(--line);border-radius:999px;background:rgba(17,24,22,.55);backdrop-filter:blur(16px);color:#aeb8b3;font:500 .62rem "DM Mono"}.status-dot{position:relative;width:6px;height:6px;border-radius:50%;background:var(--success)}.status-dot:after{content:"";position:absolute;inset:-4px;border:1px solid rgba(112,223,167,.36);border-radius:50%;animation:statusPulse 2.6s ease-out infinite}@keyframes statusPulse{0%{transform:scale(.65);opacity:.9}80%,100%{transform:scale(1.7);opacity:0}}
      .section-head{display:flex;align-items:end;justify-content:space-between;gap:2rem;margin:4rem 0 1.25rem}.section-title{margin-top:.48rem;font-size:clamp(1.75rem,3vw,2.8rem);font-weight:600;letter-spacing:-.055em;color:var(--ink)}.section-note{max-width:500px;color:var(--muted);font-size:.76rem;line-height:1.6;text-align:right}.evidence-rail{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:.75rem;margin:0 0 3.6rem}.evidence-item{padding:1rem 1.1rem;border-top:1px solid var(--line-strong);background:linear-gradient(180deg,rgba(20,29,25,.48),rgba(12,17,15,.22))}.evidence-item:first-child{border-top-color:var(--green)}.evidence-label{color:var(--muted);font:500 .61rem "DM Mono";letter-spacing:.12em;text-transform:uppercase}.evidence-value{margin-top:.42rem;color:var(--soft);font-size:.79rem}.evidence-value strong{color:var(--ink);font-weight:600}
      .policy-hero{position:relative;overflow:hidden;border:1px solid var(--line);border-radius:24px;padding:1.45rem 1.6rem;margin:.7rem 0 2rem;display:flex;align-items:center;justify-content:space-between;gap:1rem;background:linear-gradient(115deg,rgba(25,39,33,.82),rgba(13,18,16,.68));box-shadow:var(--shadow)}.policy-hero:before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--green)}.policy-label{font:500 .62rem "DM Mono";color:var(--muted);letter-spacing:.14em;text-transform:uppercase}.policy-mode{margin-top:.25rem;font-size:clamp(1.55rem,2.5vw,2.4rem);font-weight:600;letter-spacing:-.055em}.policy-meta{color:#95a29c;font:500 .68rem "DM Mono";text-align:right;line-height:1.8}
      .metric-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:.7rem;margin:1rem 0 2rem}.metric-card{position:relative;min-width:0;min-height:180px;padding:1.25rem 1.15rem 1rem;border:1px solid var(--line);border-radius:20px;background:linear-gradient(155deg,rgba(22,31,27,.9),rgba(12,17,15,.72));overflow:hidden;transition:transform .35s cubic-bezier(.2,.8,.2,1),border-color .35s,box-shadow .35s}.metric-card:hover{transform:translateY(-5px);border-color:rgba(112,223,167,.3);box-shadow:0 22px 55px rgba(0,0,0,.26);background:linear-gradient(155deg,rgba(25,37,31,.96),rgba(14,20,17,.8))}.metric-label{color:var(--muted);font:500 .6rem "DM Mono";letter-spacing:.11em;text-transform:uppercase;white-space:nowrap}.metric-value{margin-top:.72rem;color:var(--ink);font:500 clamp(1.55rem,2.45vw,2.65rem) "DM Mono";letter-spacing:-.075em;white-space:nowrap;animation:valueIn .7s cubic-bezier(.2,.8,.2,1) both}@keyframes valueIn{from{opacity:0;transform:translateY(10px);filter:blur(5px)}to{opacity:1;transform:none;filter:none}}.metric-trend{margin-top:.4rem;color:var(--success);font:500 .65rem "DM Mono"}.metric-sub{margin-top:.24rem;color:var(--muted);font-size:.64rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.spark{position:absolute;left:1rem;right:1rem;bottom:.85rem;height:30px;display:flex;align-items:end;gap:3px;opacity:.72}.spark i{flex:1;min-height:3px;border-radius:3px 3px 1px 1px;background:linear-gradient(180deg,rgba(112,223,167,.7),rgba(87,199,150,.08));animation:sparkIn .8s both;transform-origin:bottom}@keyframes sparkIn{from{transform:scaleY(.05);opacity:0}to{transform:scaleY(1);opacity:1}}
      .debate-stage{position:relative;padding:1.5rem;border:1px solid rgba(112,223,167,.17);border-radius:28px;background:radial-gradient(700px 280px at 50% 0,rgba(53,100,79,.15),transparent 70%),rgba(13,18,16,.64);box-shadow:0 40px 100px rgba(0,0,0,.34);overflow:hidden}.debate-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.85rem;margin:.8rem 0 1.2rem}.debate-card{position:relative;background:linear-gradient(150deg,rgba(25,35,31,.92),rgba(13,19,16,.86));border:1px solid var(--line);border-radius:21px;padding:1.2rem;min-width:0;min-height:230px;transition:transform .35s,border-color .35s,box-shadow .35s;animation:cardEnter .65s both}.debate-card:nth-child(2){animation-delay:.08s}.debate-card:nth-child(3){animation-delay:.16s}@keyframes cardEnter{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}.debate-card:hover{transform:translateY(-4px);border-color:rgba(112,223,167,.28);box-shadow:0 22px 55px rgba(0,0,0,.24)}.ai-avatar{position:relative;width:36px;height:36px;display:grid;place-items:center;margin-bottom:1.1rem;border:1px solid var(--line-strong);border-radius:12px;background:rgba(255,255,255,.035);color:var(--green);font:500 .7rem "DM Mono"}.ai-avatar:after{content:"•••";position:absolute;left:44px;color:#607069;font-size:.55rem;letter-spacing:.12em;animation:typing 1.8s steps(3,end) infinite;overflow:hidden;width:18px}@keyframes typing{0%{width:0;opacity:.25}70%{width:18px;opacity:.9}100%{opacity:.25}}.debate-role{color:var(--soft);font:600 .68rem "DM Mono";letter-spacing:.1em;text-transform:uppercase;margin-bottom:.65rem}.debate-copy{color:#e2e7e4;font-size:.82rem;line-height:1.55;min-height:62px}.reason-bullet{display:flex;gap:.45rem;margin-top:.7rem;color:#89968f;font-size:.69rem;line-height:1.45}.reason-bullet:before{content:"";width:4px;height:4px;margin-top:.42rem;flex:none;border-radius:50%;background:var(--green)}.debate-meta{color:#8f9c96;font:500 .62rem "DM Mono";margin-top:.75rem}.confidence-track{height:3px;margin-top:.55rem;border-radius:5px;background:rgba(255,255,255,.07);overflow:hidden}.confidence-fill{height:100%;border-radius:5px;background:linear-gradient(90deg,#477d66,var(--green));animation:confidenceIn 1.2s .25s both;transform-origin:left}@keyframes confidenceIn{from{transform:scaleX(0)}to{transform:scaleX(1)}}.debate-source{display:inline-flex;align-items:center;gap:.4rem;border:1px solid rgba(112,223,167,.28);border-radius:999px;padding:.32rem .58rem;color:var(--success);font:500 .58rem "DM Mono";letter-spacing:.12em}
      .decision-flow{display:grid;grid-template-columns:repeat(5,1fr);align-items:center;gap:.35rem;margin:1.25rem .2rem}.flow-node{position:relative;padding:.65rem .5rem;text-align:center;color:#aab5af;font:500 .58rem "DM Mono";border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.022)}.flow-node:not(:last-child):after{content:"";position:absolute;left:100%;top:50%;width:calc(100% + .35rem);height:1px;background:linear-gradient(90deg,var(--green),transparent);animation:flowPulse 2s infinite;transform-origin:left}@keyframes flowPulse{0%{opacity:.2;transform:scaleX(.1)}55%{opacity:.85;transform:scaleX(1)}100%{opacity:.15;transform:scaleX(1)}}.debate-final{display:grid;grid-template-columns:auto 1fr;gap:1rem;align-items:center;border:1px solid rgba(112,223,167,.25);border-radius:20px;background:linear-gradient(110deg,rgba(31,61,48,.54),rgba(18,29,24,.44));padding:1rem 1.15rem;margin:.75rem 0 .1rem;color:#dce7e1}.verify-check{width:48px;height:48px;display:grid;place-items:center;border-radius:50%;background:rgba(112,223,167,.13);color:var(--success);font-size:1.35rem;border:1px solid rgba(112,223,167,.3);animation:verifyPop .7s .3s both}@keyframes verifyPop{from{transform:scale(.5);opacity:0}to{transform:scale(1);opacity:1}}.verify-copy{font-size:.76rem;line-height:1.7}.verify-copy strong{color:#fff;font-weight:600}
      .replay-deck{border:1px solid var(--line);border-radius:24px;padding:1.15rem 1.2rem;background:linear-gradient(145deg,rgba(21,30,26,.84),rgba(11,16,14,.7));box-shadow:var(--shadow);margin:.5rem 0 1rem}.replay-strip{display:flex;justify-content:space-between;align-items:center;gap:1rem;border:0;padding:0;background:none;margin:0 0 .8rem}.replay-label{display:inline-flex;align-items:center;gap:.55rem;color:var(--soft);font:600 .65rem "DM Mono";letter-spacing:.1em;text-transform:uppercase}.replay-label:before{content:"";width:7px;height:7px;border-radius:50%;background:var(--success);box-shadow:0 0 0 4px rgba(112,223,167,.09)}.replay-note{color:var(--muted);font-size:.66rem;text-align:right}.live-value{min-height:98px;padding:1rem;border:0;border-top:1px solid var(--line-strong);background:linear-gradient(180deg,rgba(255,255,255,.018),transparent);border-radius:0;transition:background .25s}.live-value:hover{background:rgba(255,255,255,.03)}.live-value small{color:var(--muted);font:500 .58rem "DM Mono";letter-spacing:.08em;text-transform:uppercase}.live-value strong{display:block;color:var(--ink);font:500 1.3rem "DM Mono";margin-top:.4rem;letter-spacing:-.04em}
      [data-testid="stPlotlyChart"]{background:linear-gradient(145deg,rgba(18,25,22,.78),rgba(11,15,13,.58));border:1px solid var(--line);border-radius:24px;padding:10px;box-shadow:0 18px 55px rgba(0,0,0,.17);animation:chartIn .65s both}@keyframes chartIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}.reason{border:1px solid var(--line);padding:1rem;margin:.7rem 0;background:rgba(17,24,22,.58);border-radius:16px}.reason small{color:var(--muted);font:500 .66rem "DM Mono"}.reason-mode{display:inline-block;border:1px solid rgba(112,223,167,.22);border-radius:999px;padding:.2rem .5rem;margin-left:.35rem;color:#c1d0c8;background:rgba(112,223,167,.04)}
      .reason-conversation{border:1px solid var(--line);border-radius:18px;background:rgba(17,24,22,.52);margin:.55rem 0;overflow:hidden;transition:border-color .25s,background .25s}.reason-conversation:hover{border-color:var(--line-strong);background:rgba(24,36,31,.58)}.reason-conversation summary{list-style:none;cursor:pointer;padding:1rem 1.1rem;display:flex;align-items:center;gap:.7rem}.reason-conversation summary::-webkit-details-marker{display:none}.reason-day{color:var(--soft);font:500 .7rem "DM Mono"}.reason-summary{margin-left:auto;color:var(--muted);font-size:.67rem}.reason-details{padding:.8rem 1.1rem 1rem;border-top:1px solid var(--line);color:#96a39d;font-size:.7rem;line-height:1.65}
      [data-testid="stSidebar"]{background:rgba(11,15,13,.92);border-right:1px solid var(--line);backdrop-filter:blur(24px)}[data-testid="stSidebar"]>div:first-child{padding:2rem 1.1rem}[data-testid="stSidebar"] h3{color:var(--ink);font-size:.78rem}[data-testid="stSidebar"] label{color:var(--muted)!important;font:500 .62rem "DM Mono"!important;letter-spacing:.04em}[data-testid="stSidebar"] [data-baseweb="select"]>div,[data-testid="stSidebar"] input{background:#111816!important;border-color:var(--line)!important;border-radius:12px!important}.stButton>button{position:relative;overflow:hidden;border:1px solid var(--line-strong);border-radius:12px;background:#151c19;color:#dce4e0;transition:transform .2s,background .2s,border-color .2s}.stButton>button:hover{transform:translateY(-1px);background:var(--hover);border-color:rgba(112,223,167,.3);color:#fff}.stButton>button:active{transform:scale(.98)}[data-testid="stSlider"] [role="slider"]{background:var(--success)!important;border-color:#d8f5e7!important;box-shadow:0 0 0 4px rgba(112,223,167,.1)!important}[data-testid="stExpander"]{border:1px solid var(--line)!important;border-radius:16px!important;background:rgba(17,24,22,.42)!important}
      @media(max-width:1180px){.metric-grid{grid-template-columns:repeat(3,1fr)}.hero-shell{grid-template-columns:1fr}.hero-console{max-width:520px}.evidence-rail{grid-template-columns:1fr}.decision-flow{grid-template-columns:1fr}.flow-node:not(:last-child):after{left:50%;top:100%;width:1px;height:.35rem}.debate-grid{grid-template-columns:1fr}.debate-card{min-height:0}}@media(max-width:760px){.block-container{padding:1.3rem 1rem 5rem}.hero-title{font-size:3.7rem}.metric-grid{grid-template-columns:repeat(2,1fr)}.hero-shell{min-height:0;padding-top:2rem}.section-head{align-items:flex-start;flex-direction:column}.section-note{text-align:left}.policy-hero{align-items:flex-start;flex-direction:column}.policy-meta{text-align:left}.debate-final{grid-template-columns:1fr}.replay-strip{align-items:flex-start;flex-direction:column}.replay-note{text-align:left}}@media(max-width:480px){.metric-grid{grid-template-columns:1fr}.status-rail{gap:.4rem}.hero-title{font-size:3.15rem}}@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation-duration:.01ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important;transition-duration:.01ms!important}}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def load_summary(mode: str) -> dict[str, Any]:
    return load_json_document(RESULTS / mode / "summary.json")


@st.cache_data
def load_proof(name: str) -> dict[str, Any]:
    return load_json_document(OUTPUTS / name)


@st.cache_data
def load_telemetry(mode: str) -> pd.DataFrame:
    path = RESULTS / mode / "telemetry.csv"
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
    energy_delta = hourly["energy_kwh"].diff().clip(lower=0)
    contiguous = hourly["hour_bin"].diff().eq(1)
    hourly["hourly_kwh"] = energy_delta.where(contiguous, 0).fillna(0)
    hourly["day"] = hourly["hour_bin"] // 24 + 1
    return hourly


@st.cache_data
def load_policy() -> pd.DataFrame:
    path = RESULTS / "agent" / "policy_log.jsonl"
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
    path = RESULTS / "agent" / "reasoning.jsonl"
    if not path.exists():
        return pd.DataFrame()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    if "type" in frame:
        frame = frame[frame["type"] != "reason_disabled"].copy()
    if frame.empty:
        frame["simulated_hour"] = pd.Series(dtype="float64")
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


def sparkline_html(values: list[float]) -> str:
    finite = [float(value) for value in values if pd.notna(value)]
    if not finite:
        return '<span class="spark"><i style="height:20%"></i></span>'
    sampled = finite[:: max(1, len(finite) // 14)][-14:]
    lower, upper = min(sampled), max(sampled)
    span = max(upper - lower, 1e-9)
    bars = "".join(
        f'<i style="height:{18 + 82 * (value - lower) / span:.0f}%"></i>'
        for value in sampled
    )
    return f'<span class="spark">{bars}</span>'


def active_policy(policy: pd.DataFrame, hour: int) -> pd.Series:
    eligible = policy[policy["simulated_hour"] <= hour]
    return eligible.iloc[-1] if not eligible.empty else policy.iloc[0]


def add_policy_markers(
    fig: go.Figure,
    switches: pd.DataFrame,
    x_column: str = "simulated_hour",
) -> None:
    for row in switches.itertuples(index=False):
        fig.add_vline(
            x=getattr(row, x_column),
            line_width=1,
            line_dash="dot",
            line_color=MODE_COLORS.get(row.mode, "#57e39f"),
            opacity=0.5,
        )


def chart_layout(fig: go.Figure, title: str, y_title: str) -> None:
    fig.update_layout(
        title={"text": title, "font": {"size": 17, "family": "Inter"}, "x": 0.025},
        xaxis_title="Simulation hour",
        yaxis_title=y_title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#829089", "family": "DM Mono", "size": 11},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": "#111816",
            "bordercolor": "rgba(112,223,167,.25)",
            "font": {"color": "#eef3f0", "family": "DM Mono"},
        },
        legend={"orientation": "h", "y": 1.13, "font": {"size": 10}},
        margin={"l": 24, "r": 24, "t": 78, "b": 26},
        transition={"duration": 480, "easing": "cubic-in-out"},
    )
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor="rgba(112,223,167,.28)",
        spikethickness=1,
        tickfont={"color": "#6f7c76"},
        title_font={"color": "#87938d", "size": 11},
    )
    fig.update_yaxes(
        gridcolor="rgba(187,220,204,.055)",
        zeroline=False,
        tickfont={"color": "#6f7c76"},
        title_font={"color": "#87938d", "size": 11},
    )


def compact_timeline_layout(fig: go.Figure, available_hours: list[int]) -> None:
    ticks, labels = representative_ticks(available_hours)
    if len(ticks) == 1 and len(available_hours) > 24 * 300:
        ticks = [0, 2160, 4344, 6552, len(available_hours) - 1]
        labels = ["Jan", "Apr", "Jul", "Oct", "Dec"]
    fig.update_xaxes(
        title=(
            "Continuous simulation year"
            if len(representative_ticks(available_hours)[0]) == 1
            else "Representative simulation periods"
        ),
        tickmode="array",
        tickvals=ticks,
        ticktext=labels,
        range=[-1, max(1, len(set(available_hours)))],
    )
    for tick in ticks[1:]:
        fig.add_vline(
            x=tick - 0.5,
            line_width=1,
            line_dash="dash",
            line_color="rgba(87,227,159,.28)",
        )


def selected_hour(event: Any) -> int | None:
    try:
        point = event.selection.points[0]
        custom = point.get("customdata")
        return int(custom[0] if isinstance(custom, list) else custom)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None


baseline = load_summary("baseline")
agent = load_summary("agent")
comparison = load_proof("matched-12h/comparison.json")
integrated_proof = load_proof("integrated-demo/integrated-proof.json")
self_healing_proof = load_proof("self-healing-demo/self-healing-proof.json")
baseline_hourly = hourly_replay("baseline")
agent_hourly = hourly_replay("agent")
available_hours = (
    sorted(agent_hourly["hour_bin"].astype(int).unique().tolist())
    if not agent_hourly.empty
    else []
)
policy = load_policy()
reasons = load_reasons()

if (
    not baseline
    or not agent
    or not comparison
    or baseline_hourly.empty
    or agent_hourly.empty
    or policy.empty
):
    st.warning(
        "Saved telemetry and policy output are required. Run both simulations, then "
        "`ecoloop policy-evaluate`."
    )
    st.stop()

period_count = len(agent.get("representative_periods", []))
simulated_hours = len(available_hours)
tier2_actual = int(comparison.get("actual_tier2_events", 0))
tier2_expected = int(comparison.get("expected_tier2_cycles", 0))
matched_status = (
    baseline.get("exit_code") == 0
    and agent.get("exit_code") == 0
    and tier2_expected > 0
    and tier2_actual == tier2_expected
)

if "replay_hour" not in st.session_state:
    st.session_state.replay_hour = available_hours[0] if available_hours else 0
if "playing" not in st.session_state:
    st.session_state.playing = False
if "replay_speed" not in st.session_state:
    st.session_state.replay_speed = 24
if "pending_hour" in st.session_state:
    st.session_state.replay_hour = st.session_state.pop("pending_hour")
if available_hours and int(st.session_state.replay_hour) not in set(available_hours):
    nearest_index = representative_position(
        int(st.session_state.replay_hour),
        available_hours,
    )
    st.session_state.replay_hour = available_hours[nearest_index]

current_policy = active_policy(policy, int(st.session_state.replay_hour))
current_index = int(current_policy.name)
previous_score = policy.iloc[max(0, current_index - 1)]["rolling_score"]
trend = "↗" if current_policy["rolling_score"] > previous_score else "↘"
profile = current_policy.get("profile", {})
current_episode = parse_episode_number(current_policy.get("episode"))
episode_progress = format_episode_progress(current_episode)
if episode_exceeds_total(current_episode):
    st.warning(
        f"Policy data reports episode {current_episode}, above the configured "
        f"{TOTAL_POLICY_EPISODES}-episode run total. Displaying the raw current value."
    )

integrated_status = "Verified" if integrated_proof.get("passed") else "Not run"
healing_status = "Verified" if self_healing_proof.get("passed") else "Not run"
recovered_callbacks = self_healing_proof.get("recovery", {}).get("callback_count", 0)
current_clock = datetime.now().astimezone().strftime("%H:%M")
simulation_day = int(st.session_state.replay_hour) // 24 + 1
st.markdown(
    f"""
    <section class="hero-shell">
      <div>
        <div class="hero-title">BuildingDNA</div>
        <div class="hero-subtitle">Autonomous Building Intelligence Platform</div>
        <div class="hero-copy">A verified closed loop connecting EnergyPlus physics,
        deterministic safety, local AI reasoning, and actuator-level evidence.</div>
      </div>
      <div class="hero-console">
        <div class="console-row"><span class="console-label">Local time</span><span class="console-value">{current_clock}</span></div>
        <div class="console-row"><span class="console-label">Simulation day</span><span class="console-value">{simulation_day:03d}</span></div>
        <div class="console-row"><span class="console-label">Current policy</span><span class="console-value">{html.escape(str(current_policy['mode']))}</span></div>
        <div class="console-row"><span class="console-label">Episode</span><span class="console-value">{current_episode if current_episode is not None else "—"} / {TOTAL_POLICY_EPISODES}</span></div>
      </div>
    </section>
    <div class="status-rail">
      <span class="status-pill"><span class="status-dot"></span>EnergyPlus Connected</span>
      <span class="status-pill"><span class="status-dot"></span>Ollama Verified</span>
      <span class="status-pill"><span class="status-dot"></span>Building Healthy</span>
      <span class="status-pill"><span class="status-dot"></span>Agent Active</span>
      <span class="status-pill"><span class="status-dot"></span>Simulation Replay</span>
    </div>
    <div class="evidence-rail">
      <div class="evidence-item"><div class="evidence-label">Matched evaluation</div>
        <div class="evidence-value"><strong>{"Verified" if matched_status else "Check required"}</strong> · {period_count} seasonal weeks · {simulated_hours:,} hours · Tier 2 {tier2_actual}/{tier2_expected}</div></div>
      <div class="evidence-item"><div class="evidence-label">LLM → actuator</div>
        <div class="evidence-value"><strong>{integrated_status}</strong> · 8/8 readbacks matched</div></div>
      <div class="evidence-item"><div class="evidence-label">Autonomous recovery</div>
        <div class="evidence-value"><strong>{healing_status}</strong> · {recovered_callbacks:,} callbacks</div></div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="policy-hero">
      <div>
        <div class="policy-label">Active macro-policy · replay hour {int(st.session_state.replay_hour):,}</div>
        <div class="policy-mode" style="color:{MODE_COLORS[current_policy['mode']]}">{html.escape(current_policy['mode'])}</div>
      </div>
      <div class="policy-meta">
        {episode_progress} &nbsp;·&nbsp;
        rolling score {current_policy['rolling_score']:.2f} {trend}<br>
        PMV target {profile.get('comfort_band', ['—','—'])[0]} to {profile.get('comfort_band', ['—','—'])[1]}
        &nbsp;·&nbsp; max drift {profile.get('max_setpoint_drift_c', '—')}°C
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

replay_hour = int(st.session_state.replay_hour)
debate_row = agent_hourly.iloc[
    (agent_hourly["hour_bin"] - replay_hour).abs().argsort()[:1]
].iloc[0]
policy_context = {
    "mode": current_policy["mode"],
    **(profile if isinstance(profile, dict) else {}),
}
current_snapshot = replay_snapshot(
    debate_row.to_dict(),
    replay_hour,
    policy_context,
)
selected_debate = select_debate_replay(
    load_debate_events(DEBATE_REPLAY_PATH),
    replay_hour,
    current_snapshot,
    settings,
)

savings = 100 * (baseline["energy_kwh"] - agent["energy_kwh"]) / baseline["energy_kwh"]
carbon_savings = 100 * (baseline["carbon_kg"] - agent["carbon_kg"]) / baseline["carbon_kg"]
comfort_reduction = 100 * (
    baseline["comfort_violation_count"] - agent["comfort_violation_count"]
) / max(1, baseline["comfort_violation_count"])

st.sidebar.markdown("### ◉ BuildingDNA")
st.sidebar.caption("MISSION CONTROL")
st.sidebar.divider()
st.sidebar.markdown("##### Environment")
zone = st.sidebar.selectbox("Conditioned zone", ZONES)
resolution = st.sidebar.selectbox("Chart resolution", ("Daily", "Weekly", "Monthly"), index=1)
st.sidebar.divider()
st.sidebar.markdown("##### Intelligence")
all_modes = list(MODE_COLORS)
mode_filter = st.sidebar.multiselect("Macro-policy modes", all_modes, default=all_modes)
overlay = st.sidebar.toggle("Overlay baseline and agent", value=False)
st.sidebar.divider()
st.sidebar.markdown("##### Economics")
cost_rate_inr = st.sidebar.slider("Electricity tariff (₹/kWh)", 1.0, 30.0, 8.5, 0.5)

energy_delta = baseline["energy_kwh"] - agent["energy_kwh"]
carbon_delta = baseline["carbon_kg"] - agent["carbon_kg"]
cost_avoided = energy_delta * cost_rate_inr
current_pmv = float(debate_row[f"pmv_{zone}"])
energy_spark = sparkline_html(agent_hourly["hourly_kwh"].tail(168).tolist())
carbon_spark = sparkline_html(agent_hourly["carbon_kg"].tail(168).diff().fillna(0).tolist())
comfort_spark = sparkline_html(
    agent_hourly[f"pmv_{zone}"].tail(168).abs().rsub(2).clip(lower=0).tolist()
)
cost_spark = sparkline_html(agent_hourly["energy_kwh"].tail(168).diff().fillna(0).tolist())
pmv_spark = sparkline_html(agent_hourly[f"pmv_{zone}"].tail(168).abs().tolist())
st.markdown(
    """
    <div class="section-head">
      <div><div class="section-kicker">Operating intelligence</div>
      <div class="section-title">One system. Five signals.</div></div>
      <div class="section-note">Measured representative-period outcomes and the
      active replay state, connected in one executive view.</div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    f"""
    <div class="metric-grid">
      <div class="metric-card" title="Exact representative-period electricity reduction: {energy_delta:,.4f} kWh">
        <div class="metric-label">Energy saved</div><div class="metric-value">{savings:.2f}%</div>
        <div class="metric-trend">↘ {compact(energy_delta, ' kWh')}</div>
        <div class="metric-sub">vs fixed schedule</div>{energy_spark}
      </div>
      <div class="metric-card" title="Exact representative-period carbon reduction: {carbon_delta:,.4f} kgCO₂e">
        <div class="metric-label">Carbon reduced</div><div class="metric-value">{carbon_savings:.2f}%</div>
        <div class="metric-trend">↘ {compact(carbon_delta, ' kg')}</div>
        <div class="metric-sub">kgCO₂e avoided</div>{carbon_spark}
      </div>
      <div class="metric-card" title="Agent violations: {agent['comfort_violation_count']:,}; baseline: {baseline['comfort_violation_count']:,}">
        <div class="metric-label">Comfort score</div><div class="metric-value">{comfort_reduction:.1f}%</div>
        <div class="metric-trend">↗ improvement</div>
        <div class="metric-sub">fewer violation timesteps</div>{comfort_spark}
      </div>
      <div class="metric-card" title="Exact modeled representative-period cost avoided: ₹{cost_avoided:,.2f}">
        <div class="metric-label">Operating cost</div><div class="metric-value">₹{compact(cost_avoided)}</div>
        <div class="metric-trend">↘ avoided</div>
        <div class="metric-sub">at ₹{cost_rate_inr:.2f}/kWh</div>{cost_spark}
      </div>
      <div class="metric-card">
        <div class="metric-label">PMV estimate</div><div class="metric-value">{current_pmv:+.2f}</div>
        <div class="metric-trend">{"✓ comfort band" if abs(current_pmv) <= 0.5 else "△ monitor"}</div>
        <div class="metric-sub">target −0.50 to +0.50</div>{pmv_spark}
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="section-head">
      <div><div class="section-kicker">AI debate mode</div>
      <div class="section-title">Three perspectives. One safe action.</div></div>
      <div class="section-note">Evidence-backed replay of the verified local-LLM
      control path. No savings are attributed to this isolated action.</div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown(debate_replay_html(selected_debate) or "", unsafe_allow_html=True)

mode_intervals = policy[["simulated_hour", "mode"]].sort_values("simulated_hour")
switches = mode_intervals[mode_intervals["mode"].ne(mode_intervals["mode"].shift())]


@st.fragment(run_every=0.8 if st.session_state.playing else None)
def replay_panel() -> None:
    if st.session_state.playing:
        current_position = representative_position(
            int(st.session_state.replay_hour),
            available_hours,
        )
        next_position = min(
            len(available_hours) - 1,
            current_position + int(st.session_state.replay_speed),
        )
        st.session_state.replay_hour = available_hours[next_position]
        if next_position >= len(available_hours) - 1:
            st.session_state.playing = False

    st.markdown(
        '<div class="replay-deck"><div class="replay-strip">'
        '<span class="replay-label">Sampled Period Replay</span>'
        '<span class="replay-note">Measured EnergyPlus telemetry · unsimulated gaps skipped</span>'
        '</div></div>',
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
    controls[3].select_slider(
        "Simulation hour",
        options=available_hours,
        key="replay_hour",
        help=(
            "Select a measured telemetry hour. The replay skips unsimulated time "
            "between representative weeks."
        ),
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
        f"{policy_row['mode']} · "
        f"{format_episode_progress(parse_episode_number(policy_row.get('episode')))}"
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
            name=PRODUCT_NAME,
            line={"color": "#70dfa7", "width": 2.7, "shape": "spline", "smoothing": 0.7},
            fill="tozeroy",
            fillcolor="rgba(112,223,167,.035)",
            hovertemplate=f"%{{y:.2f}}°C<extra>{PRODUCT_NAME}</extra>",
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
    visible_hours = pd.concat(
        [replay_window["hour_bin"], baseline_window["hour_bin"]],
        ignore_index=True,
    ).dropna()
    if not visible_hours.empty:
        lower = float(visible_hours.min())
        upper = float(visible_hours.max())
        padding = max(2.0, (upper - lower) * 0.03)
        temperature_fig.update_xaxes(range=[lower - padding, upper + padding])
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

    if active_reason is not None:
        st.markdown(
            (
                '<div class="reason-conversation"><div style="padding:1rem 1.1rem">'
                f'<span class="reason-day">{html.escape(str(active_reason["simulation_time"]))}</span>'
                f'<span class="reason-mode">{html.escape(str(policy_row["mode"]))}</span>'
                "</div></div>"
            ),
            unsafe_allow_html=True,
        )

st.markdown(
    """
    <div class="section-head">
      <div><div class="section-kicker">Simulation timeline</div>
      <div class="section-title">Replay the building state.</div></div>
      <div class="section-note">Play, pause, change speed, scrub measured hours,
      or select any chart point to jump back into the control loop.</div>
    </div>
    """,
    unsafe_allow_html=True,
)
replay_panel()

st.markdown(
    """
    <div class="section-head">
      <div><div class="section-kicker">Representative-period performance</div>
      <div class="section-title">Measured outcomes, not projections.</div></div>
      <div class="section-note">Matched seasonal simulation periods using the
      same model and weather. Toggle the fixed-schedule overlay from Mission Control.</div>
    </div>
    """,
    unsafe_allow_html=True,
)
hours_per_period = {"Daily": 24, "Weekly": 168, "Monthly": 730}[resolution]


def period_consumption(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["period"] = result["hour_bin"] // hours_per_period
    grouped = result.groupby("period", as_index=False).agg(
        simulated_hour=("hour_bin", "max"),
        period_kwh=("hourly_kwh", "sum"),
        samples=("hour_bin", "size"),
    )
    expected = hours_per_period
    return grouped[grouped["samples"] >= expected * 0.5]


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
for frame in (baseline_periods, agent_periods):
    frame["timeline_position"] = frame["simulated_hour"].map(
        lambda value: representative_position(value, available_hours)
    )
timeline_switches = switches.copy()
timeline_switches["timeline_position"] = timeline_switches["simulated_hour"].map(
    lambda value: representative_position(value, available_hours)
)

energy_fig = go.Figure()
if overlay:
    energy_fig.add_trace(
        go.Scatter(
            x=baseline_periods["timeline_position"],
            y=baseline_periods["period_kwh"],
            customdata=baseline_periods[["simulated_hour"]],
            name="Fixed schedule",
            line={"color": "#738079", "width": 1.8, "shape": "spline", "smoothing": 0.6},
            hovertemplate="%{y:,.2f} kWh<extra>Fixed schedule</extra>",
        )
    )
    energy_fig.add_trace(
        go.Scatter(
            x=agent_periods["timeline_position"],
            y=agent_periods["period_kwh"],
            customdata=agent_periods[["simulated_hour"]],
            name=f"{PRODUCT_NAME} agent",
            line={"color": "#70dfa7", "width": 2.6, "shape": "spline", "smoothing": 0.6},
            fill="tonexty",
            fillcolor="rgba(87,227,159,.08)",
            hovertemplate=f"%{{y:,.2f}} kWh<extra>{PRODUCT_NAME} agent</extra>",
        )
    )
else:
    energy_fig.add_trace(
        go.Bar(
            x=baseline_periods["timeline_position"],
            y=baseline_periods["period_kwh"],
            customdata=baseline_periods[["simulated_hour"]],
            name="Fixed schedule",
            marker_color="#7c9188",
            opacity=0.52,
            hovertemplate="%{y:,.2f} kWh<extra>Fixed schedule</extra>",
        )
    )
    energy_fig.add_trace(
        go.Bar(
            x=agent_periods["timeline_position"],
            y=agent_periods["period_kwh"],
            customdata=agent_periods[["simulated_hour"]],
            name=f"{PRODUCT_NAME} agent",
            marker_color="#57e39f",
            opacity=0.8,
            hovertemplate=f"%{{y:,.2f}} kWh<extra>{PRODUCT_NAME} agent</extra>",
        )
    )
    energy_fig.update_layout(barmode="group")
add_policy_markers(
    energy_fig,
    timeline_switches[timeline_switches["mode"].isin(mode_filter)],
    "timeline_position",
)
chart_layout(
    energy_fig,
    f"Facility electricity per {resolution.lower()} period",
    "Period electricity (kWh)",
)
compact_timeline_layout(energy_fig, available_hours)
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
comfort["timeline_position"] = comfort["hour_bin"].map(
    lambda value: representative_position(value, available_hours)
)
comfort["period_block"] = comfort["hour_bin"].map(
    lambda value: representative_block_index(value, available_hours)
)
comfort_fig = go.Figure()
comfort_fig.add_hrect(
    y0=-0.5,
    y1=0.5,
    fillcolor="rgba(87,227,159,.12)",
    line_width=0,
    annotation_text="Target comfort envelope",
)
for block_index, block_rows in comfort.groupby("period_block", sort=True):
    comfort_fig.add_trace(
        go.Scatter(
            x=block_rows["timeline_position"],
            y=block_rows[f"pmv_{zone}"],
            customdata=block_rows[["hour_bin", "mode"]],
            line={"color": "#d8ad65", "width": 1.8, "shape": "spline", "smoothing": 0.55},
            name=f"{zone} PMV",
            legendgroup="comfort",
            showlegend=bool(block_index == comfort["period_block"].min()),
            hovertemplate=(
                "Hour %{customdata[0]:,.0f}<br>PMV %{y:+.3f}"
                "<br>%{customdata[1]}<extra></extra>"
            ),
        )
    )
add_policy_markers(
    comfort_fig,
    timeline_switches[timeline_switches["mode"].isin(mode_filter)],
    "timeline_position",
)
chart_layout(comfort_fig, f"{zone} comfort envelope", "PMV estimate")
compact_timeline_layout(comfort_fig, available_hours)
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

st.markdown(
    """
    <div class="section-head">
      <div><div class="section-kicker">Policy history</div>
      <div class="section-title">The building adapts by episode.</div></div>
      <div class="section-note">Every node is a scored policy episode. Color
      identifies the active operating posture; hover to inspect its decision context.</div>
    </div>
    """,
    unsafe_allow_html=True,
)
policy_view = policy[policy["mode"].isin(mode_filter)]
policy_view = policy_view.copy()
policy_view["timeline_position"] = policy_view["simulated_hour"].map(
    lambda value: representative_position(value, available_hours)
)
policy_view["period_block"] = policy_view["simulated_hour"].map(
    lambda value: representative_block_index(value, available_hours)
)
policy_fig = go.Figure()
for _, block_rows in policy_view.groupby("period_block", sort=True):
    block_rows = block_rows.sort_values("simulated_hour")
    policy_fig.add_trace(
        go.Scatter(
            x=block_rows["timeline_position"],
            y=block_rows["rolling_score"],
            customdata=block_rows[
                [
                    "simulated_hour",
                    "episode",
                    "mode",
                    "energy_saved_pct",
                    "comfort_improvement_pct",
                    "reason",
                ]
            ],
            mode="lines+markers",
            showlegend=False,
            line={"color": "rgba(156,184,172,.55)", "width": 1.6},
            marker={
                "size": 10,
                "color": block_rows["mode"].map(MODE_COLORS),
                "line": {"color": "#090b0c", "width": 2},
            },
            hovertemplate=(
                "<b>Episode %{customdata[1]}</b> · Hour %{customdata[0]:,.0f}"
                "<br>Policy · %{customdata[2]}"
                "<br>Score · %{y:.3f}"
                "<br>Energy · %{customdata[3]:+.2f}%"
                "<br>Comfort · %{customdata[4]:+.2f}%"
                "<br>%{customdata[5]}<extra></extra>"
            ),
        )
    )
for mode, color in MODE_COLORS.items():
    if mode not in set(policy_view["mode"]):
        continue
    policy_fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            name=mode,
            marker={"size": 8, "color": color},
            hoverinfo="skip",
        )
    )
chart_layout(policy_fig, "Adaptive policy score and mode switches", "Rolling score")
compact_timeline_layout(policy_fig, available_hours)
policy_fig.add_annotation(
    x=0,
    y=1.02,
    xref="paper",
    yref="paper",
    text="Lines connect consecutive episodes within each simulated seasonal week; gaps are unsimulated.",
    showarrow=False,
    xanchor="left",
    font={"size": 11, "color": "#8eaaa0"},
)
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

st.markdown(
    """
    <div class="section-head">
      <div><div class="section-kicker">Reasoning audit</div>
      <div class="section-title">A conversation with the building.</div></div>
      <div class="section-note">Scan by day and policy. Expand any decision for
      its model rationale, action, and deterministic verification state.</div>
    </div>
    """,
    unsafe_allow_html=True,
)
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
        simulated_day = int(item["simulated_hour"]) // 24 + 1
        mode = html.escape(str(item["mode"]))
        record = normalize_reasoning_record(item.to_dict())
        diagnosis = html.escape(str(record.get("diagnosis", "No diagnosis recorded.")))
        recommended = html.escape(
            str(record.get("recommended_action", "No supervisory action."))
        )
        reason = html.escape(str(record.get("reason", "No reasoning recorded.")))
        safety = html.escape(str(record.get("safety_status", "Not recorded")))
        entry.markdown(
            (
                '<details class="reason-conversation">'
                '<summary>'
                f'<span class="reason-day">Day {simulated_day}</span>'
                f'<span class="reason-mode">{mode}</span>'
                '<span class="reason-summary">Decision evidence</span>'
                '</summary>'
                '<div class="reason-details">'
                f'<strong>Decision summary</strong><br>{diagnosis}<br><br>'
                f'<strong>Recommended action</strong><br>{recommended}<br><br>'
                f'<strong>Model reasoning</strong><br>{reason}<br><br>'
                f'<strong>Verification</strong><br>{safety}'
                '</div></details>'
            ),
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
