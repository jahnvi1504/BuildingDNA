# Eco-Loop system architecture

## Outcome

Eco-Loop controls a DOE/PNNL Small Office *during* an EnergyPlus 26.1.0 run.
The verified Python API callback reads five live zone temperatures and facility
electric demand, then writes thermostat schedule actuators before HVAC managers
execute. It is not a run–parse–edit–rerun batch pipeline.

The saved comparison produced:

| Metric | Fixed-schedule baseline | Eco-Loop closed loop | Change |
|---|---:|---:|---:|
| Facility electricity | 9,156.2 kWh | 8,356.5 kWh | **−8.73%** |
| Carbon | 6,157.3 kgCO₂e | 5,654.1 kgCO₂e | **−8.17%** |
| PMV-proxy violations | 7,604 | 2,930 | **−61.47%** |
| Severe EnergyPlus errors | 0 | 0 | — |

These numbers are reproducible from
`outputs/matched-12h/baseline/summary.json`,
`outputs/matched-12h/agent/summary.json`, and the derived
`outputs/matched-12h/comparison.json`. Both runs use the same model, weather,
and representative periods. The carbon result uses the documented synthetic
hourly signal in `src/ecoloop/carbon.py`.

Tier 2 was enabled at a 12-hour supervisory interval and completed all 56
scheduled reasoning cycles synchronously. Its logged actions in this long run
were observational (`get_pmv`) rather than mutating setpoint calls, so the
quantified savings are attributed to the deterministic Tier 1 controller.
`outputs/integrated-demo/integrated-proof.json` separately proves a real local
LLM `set_setpoint` action, Tier 1 validation, and matching live EnergyPlus
actuator readbacks.

## Representative-period evaluation

The default evaluation runs four inclusive seasonal weeks: **January 15–21,
April 15–21, July 15–21, and October 15–21**. Together they cover 28 days, or
672 simulated hours. EnergyPlus still executes normal physics and live EMS
callbacks, but only for these four `RunPeriod` objects. The source IDF is never
edited; Eco-Loop writes a generated `representative_periods.idf` into the run's
output directory.

The reported comparison values are totals over these same representative
periods and are not presented as annual totals. They may be annualized only
with an explicitly reported scaling factor. This methodology samples winter,
spring, monsoon, and autumn operating conditions while keeping local Tier 2 evaluation practical.
Self-hosted Llama inference takes tens of wall-clock seconds per cycle, whereas
an accelerated continuous EnergyPlus year completes in only a few minutes.
Running all 8,760 accelerated hourly triggers therefore would not meaningfully
test hourly local inference throughput.

The periods are configurable with `ECOLOOP_REPRESENTATIVE_PERIODS` (a JSON
list of `MM-DD:MM-DD` values). `ECOLOOP_FULL_YEAR=true` restores a continuous
full-calendar-year EnergyPlus run.

## Reflex + Reason

```text
EnergyPlus 26.1.0 physics
    │ live callback every system timestep
    ▼
Tier 1 — ReflexController (local, deterministic, zero network latency)
    │ hard temperature limits, occupied comfort band, deadband enforcement
    │ schedule actuator writes before HVAC managers
    ├──────────────────────────────► telemetry.csv / dashboard
    │ aggregated telemetry window
    ▼
Tier 2 — ReasonAgent (local Llama 3.1 8B via Ollama, synchronous)
    │ local tool calls mirrored by the MCP tool surface
    │ bounded supervisory setpoint requests + natural-language justification
    ▼
Tier 1 validation/clamping ────────► next EnergyPlus timestep
```

At each configured supervisory interval, the EnergyPlus callback completes one
Tier 2 cycle synchronously before simulation time advances. An unavailable
local model server, timeout, malformed tool call, or inference error becomes a
`reason_failure` log entry and Tier 1 continues on the next timestep.

The matched evaluation sets `ECOLOOP_REASON_INTERVAL_MINUTES=720`, so Tier 2
runs every 12 simulated hours while Tier 1 continues at every system timestep.

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
context as a PMV target and maximum setpoint drift. The same profile's numeric
drift limit is passed to `ReflexController` on every agent timestep and clamps
supervisory heating/cooling requests around that occupancy state's base
setpoint. With the unchanged occupied cooling base of 25.4°C, Comfort Priority
permits at most 25.9°C (+0.5°C), Balanced 26.4°C (+1.0°C), and Energy Saver
26.9°C (+1.5°C). The separate occupied ceiling is 27.5°C and the absolute
ceiling remains 28°C. Tier 1 remains the final safety authority and the policy
wrapper never writes an actuator.

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
estimate. Occupied PMV values outside -0.5 to +0.5 are counted as comfort
violations. The enforced macro-policy drift clamp bounds every supervisory
request before the occupied 27.5°C and absolute 28°C safety ceilings are
applied; widening the occupied ceiling does not bypass the active mode's
tighter drift limit. Enabling EnergyPlus's native Fanger outputs is a clear
next calibration step for field-grade claims.

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
tool-calling smoke test and callback gate without altering the matched comparison.

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

The production callback performs Tier 2 inference synchronously at each
configured trigger. This prevents an accelerated EnergyPlus run from racing
past a slower local model or silently dropping overlapping cycles. Each
successful cycle records `reason_action`; exceptions record `reason_failure`
and are contained so Tier 1 continues for the full configured evaluation
window using its local occupied/unoccupied policy.

Measured on the hackathon workstation, the warmed local `llama3.1:8b` smoke
cycle completed in 36.45 seconds. The integrated two-call action/justification
proof took 91.90 seconds total, and the self-healing proof took 43.25 seconds
including two EnergyPlus launches. This is materially slower than the former
hosted backend. It remains below a real one-hour supervisory interval, but an
the accelerated simulation now pauses at each Tier 2 trigger. This makes the
completion rate auditable, but total wall-clock time scales directly with local
inference latency. The four-week seasonal evaluation limits that cost without
changing Tier 1 safety behavior.
