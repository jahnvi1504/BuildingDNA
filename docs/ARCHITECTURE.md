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
Tier 2 — ReasonAgent (local Llama 3.1 8B via Ollama, asynchronous)
    │ local tool calls mirrored by the MCP tool surface
    │ bounded supervisory setpoint requests + natural-language justification
    ▼
Tier 1 validation/clamping ────────► next EnergyPlus timestep
```

Tier 1 never waits for Tier 2. An unavailable local model server, timeout,
malformed tool call, or inference error becomes a `reason_failure` log entry
while the simulation continues.

## Macro-policy wrapper

`PolicyReasonWrapper` surrounds the existing reason agent. It observes the same
cumulative metrics but has no actuator or reflex-controller reference. Every
48 simulated hours it calculates a fixed weighted score:

- 45% episode electricity saved versus the baseline;
- 35% reduction in occupied comfort-violation zone-timesteps;
- 20% episode carbon avoided.

Three consecutive episode scores establish a trend. A declining trend moves
from `Energy Saver` toward `Balanced` and then `Comfort Priority`; an improving
trend permits the reverse. The selected profile is added to Tier 2's telemetry
context as a PMV target and maximum setpoint drift. Tier 1 remains the final
safety authority and the policy wrapper never writes an actuator.

Every completed episode is appended to `outputs/agent/policy_log.jsonl`.
`ecoloop policy-evaluate` applies the identical state machine to saved baseline
and agent telemetry for the completed-run replay.

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

The in-process local-LLM agent uses the same `ControlTools` implementation as MCP,
so tool semantics cannot drift between the demo loop and external MCP clients.
`set_setpoint` only queues a request. Tier 1 applies it after safety checks;
the model never gives the LLM direct actuator authority.

## Prompt and context management

The system prompt gives one objective hierarchy: safety, occupied comfort,
then energy/carbon. It restricts each supervisory cycle to at most two actions
and requires an evidence/action/expected-effect justification.

Raw timestep logs are not sent to the model. `ReasonAgent` keeps a bounded
12-observation deque of already-aggregated snapshots, serializes it compactly,
and calls the local Ollama server hourly by default. This caps inference
frequency and latency independently of simulation length.

The default model is the open-source `llama3.1:8b`, served locally by Ollama's
OpenAI-compatible endpoint at `http://localhost:11434/v1`. The base URL, client
placeholder key, and model are configurable through `ECOLOOP_LLM_BASE_URL`,
`ECOLOOP_LLM_API_KEY`, and `ECOLOOP_LLM_MODEL`. No inference request or API key
leaves the machine.

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

The deterministic proof in `scripts/run_self_healing_demo.py` copies the
canonical IDF, injects an invalid cooling-schedule reference, and runs
EnergyPlus to a real fatal termination. The supervisor extracts the actual
error, asks the local LLM to diagnose it, executes its forced `patch_idf` tool call
against a separate repair copy, and restarts EnergyPlus. The committed proof
records failed exit code 1 and zero callbacks before repair, followed by exit
code 0, 9,512 callbacks, and no severe/fatal errors after repair. EnergyPlus
cannot resume arbitrary physics state, so "healing" correctly means restoring
the model and automatically restarting its run.

## Integrated LLM-to-actuator evidence

`scripts/run_integrated_demo.py` is a disposable two-day proof harness. During
an occupied timestep it pauses inside the real EnergyPlus callback, supplies
live zone PMV and energy telemetry to the local LLM, executes the resulting
`set_setpoint` tool request through the unchanged `ReflexController`, and
writes the validated schedule value through EMS. The saved proof contains the
LLM justification and eight matching requested/readback actuator samples from
that same process. This closes the evidence gap between the independent local
tool-calling smoke test and callback gate without altering the annual comparison.

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

The production callback performs no inference I/O. Tier 2 runs on a daemon
thread and drops overlapping triggers instead of accumulating stale decisions.
Every local-model request is revalidated on the next callback. If Ollama is
unavailable, Tier 1 continues for the full simulation using its local
occupied/unoccupied policy.

Measured on the hackathon workstation, the warmed local `llama3.1:8b` smoke
cycle completed in 36.45 seconds. The integrated two-call action/justification
proof took 91.90 seconds total, and the self-healing proof took 43.25 seconds
including two EnergyPlus launches. This is materially slower than the former
hosted backend. It remains below a real one-hour supervisory interval, but an
accelerated annual simulation advances much faster than wall time, so the
single-flight agent will intentionally skip overlapping hourly triggers. Tier
1 timing and safety are unchanged.
