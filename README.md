# Eco-Loop Building Agents

Live, closed-loop building energy optimization using EnergyPlus Python API
callbacks, a deterministic safety controller, and a Groq-hosted supervisory
agent.

## Verified status

The live callback gate passed against EnergyPlus 26.1.0: 12 changing
zone-temperature reads and 12 thermostat schedule writes/readbacks occurred in
the same simulation process. The full annual baseline and Tier 1 agent runs
also complete with zero severe errors.

Two isolated proofs cover the remaining autonomous paths without modifying the
annual baseline model:

- `outputs/integrated-demo/integrated-proof.json` records a real Groq
  `set_setpoint` tool call, Tier 1 validation, and eight matching EnergyPlus
  actuator readbacks from the same running process.
- `outputs/self-healing-demo/self-healing-proof.json` records an injected IDF
  failure, Groq diagnosis and `patch_idf` call, automatic restart, 9,512
  recovered callbacks, and zero severe/fatal errors after repair.

Secrets are read only from `GROQ_API_KEY`. Copy `.env.example` to `.env` and
provide a newly rotated key locally; never commit it.

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
