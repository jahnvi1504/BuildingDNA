# Eco-Loop Building Agents

Live, closed-loop building energy optimization using EnergyPlus Python API
callbacks, a deterministic safety controller, and a locally hosted open-source
LLM (Llama 3.1 8B through Ollama).

## Verified status

The live callback gate passed against EnergyPlus 26.1.0: 12 changing
zone-temperature reads and 12 thermostat schedule writes/readbacks occurred in
the same simulation process. A matched four-season evaluation completed with
zero severe errors in both the fixed-schedule baseline and Eco-Loop runs. All
56 configured local-LLM supervisory cycles completed synchronously at 12-hour
simulated-time intervals.

Two isolated proofs cover the remaining autonomous paths without modifying the
canonical baseline model:

- `outputs/integrated-demo/integrated-proof.json` records a real local-LLM
  `set_setpoint` tool call, Tier 1 validation, and eight matching EnergyPlus
  actuator readbacks from the same running process.
- `outputs/self-healing-demo/self-healing-proof.json` records an injected IDF
  failure, local-LLM diagnosis and `patch_idf` call, automatic restart, 9,512
  recovered callbacks, and zero severe/fatal errors after repair.

Tier 2 calls only `http://localhost:11434/v1`; no external inference API is
used and no API key leaves the machine. The OpenAI-compatible client receives
the non-secret placeholder key `ollama`, as required by its constructor.

## Matched results

- Electricity: 9,156.2 → 8,356.5 kWh (**8.73% reduction**)
- Carbon: 6,157.3 → 5,654.1 kgCO₂e (**8.17% reduction**)
- Estimated comfort violations: 7,604 → 2,930 (**61.47% reduction**)

The baseline and agent use the same EnergyPlus model, weather, and four
representative seasonal weeks. The exact machine-readable comparison is
`outputs/matched-12h/comparison.json`.

Tier 1 executes at every EnergyPlus system timestep. Tier 2 was enabled for
this evaluation and completed 56/56 reasoning checkpoints, but it issued no
valid mutating setpoint tool call during the long run; therefore the measured
savings are attributed to Tier 1. The separate integrated proof demonstrates
and verifies the complete LLM → Tier 1 validation → live EnergyPlus actuator
path without attributing the long-run savings to the LLM.

## Start

```powershell
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\python.exe scripts\run_integrated_demo.py
.\.venv\Scripts\python.exe scripts\run_self_healing_demo.py
.\.venv\Scripts\streamlit.exe run dashboard.py
```

See `docs/SETUP.md`, `docs/ARCHITECTURE.md`, and `docs/DEMO.md`.
