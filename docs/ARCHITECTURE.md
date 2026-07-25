# Eco-Loop system architecture

## Outcome

Eco-Loop controls a DOE/PNNL Small Office *during* an EnergyPlus 26.1.0 run.
The verified Python API callback reads five live zone temperatures and facility
electric demand, then writes thermostat schedule actuators before HVAC managers
execute. It is not a run–parse–edit–rerun batch pipeline.

The saved annual comparison produced:

| Metric | Fixed-schedule baseline | Eco-Loop Tier 1 | Change |
|---|---:|---:|---:|
| Facility electricity | 79,870.9 kWh | 78,605.0 kWh | **−1.58%** |
| Carbon | 52,259.4 kgCO₂e | 51,961.0 kgCO₂e | **−0.57%** |
| PMV-proxy violations | 89,179 | 35,475 | **−60.22%** |
| Severe EnergyPlus errors | 0 | 0 | — |

These numbers are reproducible from `outputs/baseline/summary.json` and
`outputs/agent/summary.json`. The carbon result uses the documented synthetic
hourly signal in `src/ecoloop/carbon.py`.

## Reflex + Reason

```text
EnergyPlus 26.1.0 physics
    │ live callback every system timestep
    ▼
Tier 1 — ReflexController (local, deterministic, zero network latency)
    │ hard temperature limits, occupied comfort band, deadband enforcement
    │ schedule actuator writes before HVAC managers
    ├──────────────────────────────► telemetry.csv / dashboard
    │ aggregated hourly window
    ▼
Tier 2 — ReasonAgent (Groq, asynchronous)
    │ local tool calls mirrored by the MCP tool surface
    │ bounded supervisory setpoint requests + natural-language justification
    ▼
Tier 1 validation/clamping ────────► next EnergyPlus timestep
```

Tier 1 never waits for Tier 2. A missing key, timeout, malformed tool call, or
provider error becomes a `reason_failure` log entry while the simulation
continues. The saved agent run intentionally demonstrates this independence:
it completed with no `GROQ_API_KEY`.

## Live EnergyPlus integration

`EnergyPlusRunner` registers
`callback_after_predictor_before_hvac_managers`. During each callback it:

1. reads `Zone Mean Air Temperature` for the five conditioned zones;
2. reads `Facility Total Electricity Demand Rate`;
3. reads the occupancy schedule;
4. integrates demand using EnergyPlus's current system-timestep duration;
5. runs Tier 1;
6. writes the heating/cooling `Schedule:Compact` actuators; and
7. records telemetry and aggregates hourly observations for Tier 2.

The standalone gate in `scripts/verify_ems_callback.py` proved 12 consecutive
sensor reads and actuator writes in one simulation. Its machine-readable result
is `outputs/callback-proof/callback-proof.json`.

## MCP tool-calling design

`src/ecoloop/mcp_server.py` exposes exactly:

- `get_zone_temps()`
- `get_pmv()`
- `get_energy_kwh()`
- `get_grid_carbon_intensity()`
- `set_setpoint(zone, value, kind)`
- `adjust_schedule(schedule_name, ops)`
- `get_error_log()`
- `patch_idf(diff)`

The in-process Groq agent uses the same `ControlTools` implementation as MCP,
so tool semantics cannot drift between the demo loop and external MCP clients.
`set_setpoint` only queues a request. Tier 1 applies it after safety checks;
the model never gives the LLM direct actuator authority.

## Prompt and context management

The system prompt gives one objective hierarchy: safety, occupied comfort,
then energy/carbon. It restricts each supervisory cycle to at most two actions
and requires an evidence/action/expected-effect justification.

Raw timestep logs are not sent to the model. `ReasonAgent` keeps a bounded
12-observation deque of already-aggregated snapshots, serializes it compactly,
and calls Groq hourly by default. This caps cost and latency independently of
simulation length.

The default production model is `llama-3.3-70b-versatile`, selected because
Groq currently lists it as a production model with local tool support. The
model ID remains configurable through `GROQ_MODEL`.

## Comfort metric

The current `get_pmv()` value is an explicit operative-temperature proxy:

```text
PMV = clip((zone_temperature_c - 24.0) × 0.35, -3, 3)
```

This is transparent and deterministic, but it is not a complete ISO 7730
Fanger calculation because the DOE prototype does not define clothing,
air-speed, and work-efficiency schedules. The dashboard labels it as an
estimate. Enabling EnergyPlus's native Fanger outputs is a clear next
calibration step for field-grade claims.

## Self-healing

`get_error_log` returns recent runtime faults. `patch_idf` accepts a bounded
JSON diff (maximum 20 operations) containing EnergyPlus object type, object
name, field, and replacement value. `IDFSelfHealer`:

1. validates every object and field against `Energy+.idd` through eppy;
2. refuses ambiguous or unknown objects;
3. writes a timestamped backup;
4. applies the patch; and
5. logs the diagnosis and exact changes.

The build itself exercised this path conceptually: transitioning the DOE model
from 22.1 to 26.1 surfaced a severe water-heater node error. Correctly assigning
the plant branch to the water heater's **use-side** nodes removed the severe
error. A production restart supervisor should rerun from the most recent
checkpoint after a patch; EnergyPlus cannot resume a terminated process at an
arbitrary physics timestep.

## Model and data provenance

- Engine: EnergyPlus 26.1.0, commit `6f2e40d102`.
- Building: DOE/PNNL ASHRAE 90.1-2019 Small Office, New Delhi variant,
  transitioned with every official converter from 22.1 through 26.1.
- Weather: Bengaluru WMO 432950 TMYx, period 2011–2025.
- Grid signal: synthetic 24-hour Indian curve, 0.52–0.82 kgCO₂e/kWh.
- Service water: draw flow set to zero after the legacy prototype/transition
  combination generated 690,000 irrelevant water-temperature warnings. The
  same correction is used for both comparison runs; the optimization target is
  HVAC.

## Latency and failure behavior

The callback performs no network I/O. Tier 2 runs on a daemon thread and drops
overlapping triggers instead of accumulating stale decisions. Every external
request is revalidated on the next callback. If Tier 2 is unavailable, Tier 1
continues for the full simulation using its local occupied/unoccupied policy.

