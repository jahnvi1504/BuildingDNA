# BuildingDNA

### A building that measures, reasons, acts, verifies, and recovers

BuildingDNA is a live Physical AI control system for commercial buildings. It
connects EnergyPlus physics to a local open-source LLM, a deterministic safety
controller, and an MCP-compatible tool layer. The result is a building agent
that observes real operating conditions, chooses bounded control actions,
writes setpoints back into the active simulation, and leaves an auditable trail
of every decision.

> **Verified outcome:** 8.73% less electricity and 61.47% fewer estimated
> comfort violations than the matched fixed-schedule baseline.

## Results that can be audited

| Matched metric | Fixed schedule | BuildingDNA | Improvement |
|---|---:|---:|---:|
| Facility electricity | 9,156.2 kWh | 8,356.5 kWh | **8.73% lower** |
| Carbon emissions | 6,157.3 kgCO2e | 5,654.1 kgCO2e | **8.17% lower** |
| Occupied PMV-proxy violations | 7,604 | 2,930 | **61.47% fewer** |
| EnergyPlus exit code | 0 | 0 | Both successful |

These are measured totals from matched EnergyPlus runs over four representative
seasonal weeks: January 15-21, April 15-21, July 15-21, and October 15-21. Both
runs use the same DOE/PNNL Small Office model and Bengaluru weather file.
Results are deliberately **not** presented as annual totals.

Machine-readable evidence:

- [Matched comparison](outputs/matched-12h/comparison.json)
- [Baseline summary](outputs/matched-12h/baseline/summary.json)
- [BuildingDNA summary](outputs/matched-12h/agent/summary.json)
- [Baseline telemetry](outputs/matched-12h/baseline/telemetry.csv)
- [BuildingDNA telemetry](outputs/matched-12h/agent/telemetry.csv)

## What makes this Physical AI

Most building-AI demos stop after generating a recommendation. BuildingDNA
closes the loop:

```text
EnergyPlus sensors
        |
        v
Tier 1 reflex control -----> immediate safety and comfort enforcement
        |
        v
Local Llama 3.1 8B -------> structured supervisory decision
        |
        v
Tier 1 validation --------> clamp, reject, or queue safely
        |
        v
EnergyPlus actuators ------> setpoint write + readback verification
        |
        +------------------> telemetry, reasoning, dashboard, next cycle
```

The LLM never receives direct actuator authority. A deterministic controller
enforces occupied limits, absolute temperature limits, setpoint deadband, and
policy-specific drift limits before a command can reach EnergyPlus.

## Four proofs, not four promises

### 1. Live EnergyPlus callback

`scripts/verify_ems_callback.py` records 12 changing zone-temperature reads and
12 alternating thermostat writes with matching actuator readbacks inside one
EnergyPlus process.

Evidence: [callback-proof.json](outputs/callback-proof/callback-proof.json)

### 2. LLM-to-actuator control

A real local `llama3.1:8b` tool call requested a 25 C cooling setpoint. The
unchanged Tier 1 controller validated it, EnergyPlus received it, and eight
requested/readback samples matched.

Evidence: [integrated-proof.json](outputs/integrated-demo/integrated-proof.json)

### 3. Matched savings

Both baseline and BuildingDNA completed the same 672 simulated hours with zero
severe errors. Tier 2 completed all 56 configured 12-hour checkpoints.

The long-run LLM produced no valid mutating setpoint action, so the measured
savings are honestly attributed to Tier 1. The separate integrated proof closes
the LLM-to-actuator evidence gap without overstating the LLM's contribution.

### 4. Autonomous recovery

The self-healing harness injects a real broken schedule reference. EnergyPlus
fails, the local LLM diagnoses the runtime error and calls `patch_idf`, the
bounded patcher repairs a disposable model, and the supervisor restarts it.
The recovered simulation completes with 9,512 callbacks and no severe or fatal
errors.

Evidence:
[self-healing-proof.json](outputs/self-healing-demo/self-healing-proof.json)

## BuildingDNA Control Room

The Streamlit dashboard is designed as a judge-facing evidence console:

- immediate savings, carbon, comfort, and cost KPIs;
- matched-run, LLM-to-actuator, and self-healing verification badges;
- replay over measured seasonal telemetry with unsimulated gaps removed;
- zone temperature and PMV-proxy comfort views;
- baseline overlay and configurable electricity tariff;
- adaptive policy trajectory with mode-colored episodes;
- compact reasoning audit showing simulated day and active policy;
- provenance and assumptions kept inside the application.

Start it with:

```powershell
.\.venv\Scripts\streamlit.exe run dashboard.py
```

## Agent design

BuildingDNA uses two control timescales:

- **Tier 1 - Reflex:** deterministic, local, and executed at every EnergyPlus
  system timestep. It remains operational without Ollama.
- **Tier 2 - Reason:** local Llama 3.1 8B inference through Ollama. It receives
  compact telemetry, returns typed JSON, and can request bounded tools.

An optional three-perspective debate asks an **Energy Saver**, **Comfort
Guardian**, and **BuildingDNA Arbiter** to evaluate the same state. Only the
Arbiter's final typed action may enter the Tier 1 safety queue.

The macro-policy layer scores 48-hour episodes using:

- 45% electricity savings;
- 35% comfort improvement;
- 20% carbon reduction.

It selects Energy Saver, Balanced, or Comfort Priority and adjusts the maximum
supervisory setpoint drift without bypassing hard safety limits.

## MCP-compatible tool surface

The server exposes eight tools:

```text
get_zone_temps
get_pmv
get_energy_kwh
get_grid_carbon_intensity
set_setpoint
adjust_schedule
get_error_log
patch_idf
```

The in-process agent and MCP server share the same `ControlTools`
implementation, preventing behavior drift between the demonstration and an
external MCP client.

## Quick start

Requirements:

- Windows
- Python 3.11 or 3.12
- EnergyPlus 26.1
- Ollama with `llama3.1:8b`

```powershell
ollama pull llama3.1:8b
ollama serve

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify_ems_callback.py
.\.venv\Scripts\streamlit.exe run dashboard.py
```

Run the closed-loop simulations:

```powershell
.\.venv\Scripts\ecoloop.exe simulate --mode baseline
.\.venv\Scripts\ecoloop.exe simulate --mode agent
```

Run the MCP server:

```powershell
.\.venv\Scripts\ecoloop.exe mcp
```

Local inference is bounded by `ECOLOOP_LLM_TIMEOUT_SECONDS`; a timeout or
malformed response becomes a logged fallback and Tier 1 continues.

## Repository map

```text
dashboard.py                 Judge-facing BuildingDNA Control Room
src/ecoloop/simulation.py    EnergyPlus callback and closed-loop runner
src/ecoloop/reflex.py        Deterministic actuator safety authority
src/ecoloop/reason.py        Local structured LLM reasoning
src/ecoloop/mcp_server.py    MCP-compatible tool server
src/ecoloop/policy.py        Adaptive macro-policy scoring
src/ecoloop/healing.py       Validated IDF patching
models/baseline/             Canonical building model
models/runtime/              Disposable proof models
outputs/                     Committed machine-readable evidence
docs/ARCHITECTURE.md         Detailed technical design and limitations
docs/DEMO.md                 Three-minute demonstration runbook
```

## Honest limitations

- The comfort value is a transparent operative-temperature PMV proxy, not a
  full ISO 7730 Fanger calculation.
- Carbon uses a documented synthetic hourly Indian grid-intensity curve.
- Reported savings cover 672 representative hours, not an annual simulation.
- The long-run savings are attributed to deterministic Tier 1; the local LLM
  control path is verified separately.

Those boundaries are intentional. BuildingDNA is designed so every headline
claim maps to committed telemetry or a reproducible proof.

## Documentation

- [Setup guide](docs/SETUP.md)
- [System architecture](docs/ARCHITECTURE.md)
- [Three-minute demo](docs/DEMO.md)

---

**BuildingDNA turns a building model from a passive calculator into an agent
with reflexes, reasoning, memory, and a verifiable connection to the physical
control loop.**
