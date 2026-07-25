# Eco-Loop Building Agents

Live, closed-loop building energy optimization using EnergyPlus Python API
callbacks, a deterministic safety controller, and a locally hosted open-source
LLM (Llama 3.1 8B through Ollama).

## Verified status

The live callback gate passed against EnergyPlus 26.1.0: 12 changing
zone-temperature reads and 12 thermostat schedule writes/readbacks occurred in
the same simulation process. The full annual baseline and Tier 1 agent runs
also complete with zero severe errors.

Two isolated proofs cover the remaining autonomous paths without modifying the
annual baseline model:

- `outputs/integrated-demo/integrated-proof.json` records a real local-LLM
  `set_setpoint` tool call, Tier 1 validation, and eight matching EnergyPlus
  actuator readbacks from the same running process.
- `outputs/self-healing-demo/self-healing-proof.json` records an injected IDF
  failure, local-LLM diagnosis and `patch_idf` call, automatic restart, 9,512
  recovered callbacks, and zero severe/fatal errors after repair.

Tier 2 calls only `http://localhost:11434/v1`; no external inference API is
used and no API key leaves the machine. The OpenAI-compatible client receives
the non-secret placeholder key `ollama`, as required by its constructor.

## Results

- Electricity: 79,870.9 → 78,605.0 kWh (**1.58% reduction**)
- Carbon: 52,259.4 → 51,961.0 kgCO₂e (**0.57% reduction**)
- Estimated comfort violations: 89,179 → 35,475 (**60.22% reduction**)

## Start

```powershell
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\python.exe scripts\run_integrated_demo.py
.\.venv\Scripts\python.exe scripts\run_self_healing_demo.py
.\.venv\Scripts\streamlit.exe run dashboard.py
```

See `docs/SETUP.md`, `docs/ARCHITECTURE.md`, and `docs/DEMO.md`.
