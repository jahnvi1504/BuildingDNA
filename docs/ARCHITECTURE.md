# BuildingDNA system architecture

## 1. System outcome

BuildingDNA controls a DOE/PNNL Small Office during an active EnergyPlus 26.1
simulation. The Python API callback reads zone temperatures, occupancy, and
facility demand; applies deterministic control; writes thermostat schedule
actuators before HVAC managers execute; and verifies the resulting values.

It is a live feedback loop, not a run-parse-edit-rerun optimizer.

The matched representative-period evaluation produced:

| Metric | Fixed schedule | BuildingDNA | Change |
|---|---:|---:|---:|
| Facility electricity | 9,156.2 kWh | 8,356.5 kWh | **-8.73%** |
| Carbon | 6,157.3 kgCO2e | 5,654.1 kgCO2e | **-8.17%** |
| Occupied PMV-proxy violations | 7,604 | 2,930 | **-61.47%** |
| EnergyPlus exit code | 0 | 0 | Successful |

The numbers are reproducible from:

- `outputs/matched-12h/baseline/summary.json`
- `outputs/matched-12h/agent/summary.json`
- `outputs/matched-12h/comparison.json`
- the corresponding telemetry CSV files.

## 2. Closed-loop control

```text
                        BUILDINGDNA CLOSED LOOP

  EnergyPlus 26.1
  physics + weather + occupancy
           |
           | callback every system timestep
           v
  +-----------------------------+
  | Tier 1: ReflexController    |
  | - occupied limits           |
  | - absolute safety limits    |
  | - heating/cooling deadband  |
  | - policy drift clamp        |
  +-----------------------------+
           |                         telemetry window
           |                                   |
           |                                   v
           |                         +----------------------+
           |                         | Tier 2: ReasonAgent  |
           |                         | local Llama via      |
           |                         | Ollama + typed tools |
           |                         +----------------------+
           |                                   |
           |                           bounded request
           |                                   |
           +<----------------------------------+
           |
           | validated schedule values
           v
  EnergyPlus EMS actuators
           |
           | actuator readback
           +-----------------------> telemetry / evidence / dashboard
```

### Why two tiers

EnergyPlus can advance far faster than a local 8B model can infer. BuildingDNA
therefore separates the safety-critical control rate from the reasoning rate:

- **Tier 1** executes at every system timestep with no model or network
  dependency.
- **Tier 2** executes at a configurable supervisory interval and may request a
  bounded action.

If Tier 2 times out, returns malformed JSON, calls an invalid tool, or is
unavailable, Tier 1 continues. This preserves simulation stability and mirrors
how supervisory AI should sit above a real building's safety controls.

## 3. EnergyPlus integration

`EnergyPlusRunner` registers
`callback_after_predictor_before_hvac_managers`. During each callback it:

1. reads `Zone Mean Air Temperature` for five conditioned zones;
2. reads `Facility Total Electricity Demand Rate`;
3. reads the occupancy schedule;
4. obtains the current system-timestep duration;
5. integrates demand into cumulative kWh;
6. computes the transparent PMV proxy;
7. applies Tier 1 and any pending supervisory request;
8. writes heating and cooling `Schedule:Compact` actuators;
9. records control decisions, telemetry, carbon, and comfort counts; and
10. aggregates observations for the next Tier 2 checkpoint.

The callback proof records 12 sensor reads and 12 matching actuator writes in
one EnergyPlus process:
`outputs/callback-proof/callback-proof.json`.

## 4. Cognitive engine

The default cognitive engine is the open-source `llama3.1:8b` model served by
Ollama's local OpenAI-compatible endpoint:

```text
http://localhost:11434/v1
```

No hosted inference API is required. The `ollama` API-key value is a
non-secret client placeholder.

`ReasonAgent` sends a compact current-state object rather than raw logs. It
contains:

- current zone temperatures and PMV estimates;
- occupancy;
- cumulative electricity and current carbon intensity;
- active heating and cooling setpoints;
- macro-policy mode and drift limit;
- hard comfort constraints; and
- the previous action when relevant.

The system prompt demands one typed building-control decision. Generic schema
explanations and telemetry summaries are rejected. A malformed response gets
one repair attempt; a second failure becomes a deterministic no-action fallback.

Local inference is bounded by `ECOLOOP_LLM_TIMEOUT_SECONDS`, which defaults to
120 seconds. Timeouts are recorded and contained.

## 5. Debate and arbitration

`AI_DEBATE_MODE` supports three modes:

- `off`: one structured reasoner;
- `compact`: Energy Saver, Comfort Guardian, and BuildingDNA Arbiter in one
  strict JSON response;
- `full`: up to three sequential role calls.

Energy Saver proposes an efficiency action. Comfort Guardian critiques its
comfort and safety consequences. BuildingDNA Arbiter returns the only final
action eligible for execution.

Proposal and critique actions are never sent to control tools. The Arbiter's
typed request is queued through `ControlTools` and still passes through Tier 1.
Model-projected percentages are always labeled as estimates.

## 6. MCP-compatible tool surface

`src/ecoloop/mcp_server.py` exposes:

| Tool | Purpose |
|---|---|
| `get_zone_temps()` | Current zone temperatures |
| `get_pmv()` | Current PMV-proxy values |
| `get_energy_kwh()` | Cumulative facility electricity |
| `get_grid_carbon_intensity()` | Current synthetic grid signal |
| `set_setpoint(zone, value, kind)` | Queue a bounded supervisory request |
| `adjust_schedule(schedule_name, ops)` | Apply bounded schedule operations |
| `get_error_log()` | Retrieve recent simulation errors |
| `patch_idf(diff)` | Validate and patch an IDF copy |

The local agent and MCP server use the same `ControlTools` class. Tool behavior
therefore cannot drift between the in-process proof and an external MCP client.

`set_setpoint` does not write EnergyPlus directly. It creates a
`SetpointRequest` in `LiveState`; Tier 1 remains the final actuator authority.

## 7. Adaptive macro-policy

`PolicyReasonWrapper` scores each 48-hour episode:

```text
score =
    0.45 * electricity_saved_percent
  + 0.35 * comfort_improvement_percent
  + 0.20 * carbon_avoided_percent
```

Three consecutive episode scores establish a trend. The wrapper selects:

| Mode | PMV target | Maximum supervisory drift |
|---|---:|---:|
| Energy Saver | -0.5 to +0.5 | 1.5 C |
| Balanced | -0.4 to +0.4 | 1.0 C |
| Comfort Priority | -0.3 to +0.3 | 0.5 C |

The wrapper cannot access actuators. It supplies policy context to Tier 2 and a
numeric drift limit to Tier 1. Hard occupied and absolute safety limits remain
in force regardless of mode.

## 8. Representative-period methodology

The validated comparison runs four inclusive seasonal weeks:

- January 15-21
- April 15-21
- July 15-21
- October 15-21

Together they cover 28 days or 672 simulated hours. Both baseline and agent use
the same IDF, weather, and periods. BuildingDNA generates
`representative_periods.idf` inside each output directory; it does not modify
the canonical baseline model.

The four-week design samples seasonal operating regimes while keeping
synchronous local inference practical. It is not an annual total and is never
presented as one. Set `ECOLOOP_FULL_YEAR=true` for a continuous calendar-year
Tier 1 run.

The matched configuration used a 720-minute supervisory interval. Tier 2
completed 56 of 56 scheduled checkpoints. Those long-run events contained no
valid mutating setpoint call, so the measured 8.73% energy reduction is
attributed to Tier 1.

## 9. LLM-to-actuator evidence

`scripts/run_integrated_demo.py` supplies live occupied-period telemetry to the
local model inside a real EnergyPlus callback. The model requests:

```json
{
  "tool": "set_setpoint",
  "arguments": {
    "zone": "Core_ZN",
    "value": 25,
    "kind": "cooling"
  }
}
```

Tier 1 validates the request, EnergyPlus receives the schedule value, and eight
requested/readback samples match. This proof demonstrates the complete local
LLM -> tool -> Tier 1 -> EnergyPlus path without misattributing long-run
savings.

Evidence: `outputs/integrated-demo/integrated-proof.json`.

## 10. Self-healing

`IDFSelfHealer` accepts a bounded JSON diff with at most 20 operations. For each
operation it:

1. validates object type and field against `Energy+.idd` through eppy;
2. resolves the exact object by name;
3. rejects ambiguous or unknown targets;
4. creates a timestamped backup;
5. writes the replacement value; and
6. records the diagnosis and applied changes.

The proof harness injects an invalid cooling schedule reference into a
disposable IDF. EnergyPlus exits with code 1. The local model extracts the
runtime error and calls `patch_idf`. The repaired model restarts, exits with
code 0, produces 9,512 callbacks, and contains no severe or fatal recovery
errors.

EnergyPlus cannot resume arbitrary internal physics state. "Self-healing"
therefore means validated repair and automatic restart, not in-memory resume.

Evidence: `outputs/self-healing-demo/self-healing-proof.json`.

## 11. Comfort and carbon metrics

### PMV proxy

```text
PMV = clip((zone_temperature_c - 24.0) * 0.35, -3, 3)
```

Occupied values outside -0.5 to +0.5 count as violations. This is an auditable
operative-temperature proxy, not a complete ISO 7730 Fanger calculation. The
prototype model lacks the clothing, metabolic-rate, air-speed, and
work-efficiency schedules required for that claim. The dashboard labels it as
an estimate.

### Carbon

The carbon signal is a deterministic synthetic hourly Indian grid curve from
0.52 to 0.82 kgCO2e/kWh. It makes carbon-aware reasoning reproducible offline
but is not represented as live grid data.

## 12. Dashboard and evidence design

The BuildingDNA Control Room reads committed run artifacts rather than
inventing live values. It provides:

- verification badges for the matched evaluation, integrated actuator proof,
  and self-healing proof;
- measured energy, carbon, comfort, and tariff-based cost KPIs;
- sampled-period replay that removes unsimulated calendar gaps;
- zone temperature and PMV charts;
- optional fixed-schedule overlay;
- policy episodes connected inside each simulated seasonal block, with mode
  encoded by marker color;
- a compact reasoning audit showing only simulated day and active policy; and
- a provenance panel that states the model, weather, carbon source, PMV method,
  and exit codes.

JSON loading accepts plain UTF-8 and UTF-8 with BOM so evidence produced by
Python or PowerShell renders reliably.

## 13. Failure containment

| Failure | Behavior |
|---|---|
| Ollama unavailable | Log failure; Tier 1 continues |
| Local inference timeout | Abort Tier 2 request after configured bound |
| Malformed model JSON | One repair attempt, then no-action fallback |
| Invalid tool arguments | Reject request; no actuator write |
| Unsafe setpoint | Clamp or reject through Tier 1 |
| IDF runtime error | Diagnose, validate patch, back up, restart |
| Missing dashboard evidence | Show a clear warning and stop rendering |

This separation ensures that AI improves supervision without becoming a single
point of failure.

## 14. Provenance

- EnergyPlus: 26.1.0, commit `6f2e40d102`
- Building: DOE/PNNL ASHRAE 90.1-2019 Small Office, New Delhi variant
- Model transition: official converters from 22.1 through 26.1
- Weather: Bengaluru WMO 432950 TMYx, 2011-2025
- LLM: `llama3.1:8b`, Q4_K_M, served locally through Ollama
- Grid signal: synthetic hourly Indian curve
- Application: Python 3.11/3.12, Streamlit, Plotly, MCP, eppy

## 15. Verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check dashboard.py src tests scripts
.\.venv\Scripts\python.exe scripts\verify_ems_callback.py
.\.venv\Scripts\ecoloop.exe reason-smoke
.\.venv\Scripts\python.exe scripts\run_integrated_demo.py
.\.venv\Scripts\python.exe scripts\run_self_healing_demo.py
.\.venv\Scripts\streamlit.exe run dashboard.py
```

The committed proof artifacts make the core claims inspectable even when local
model inference is too slow to rerun during a short judging session.
