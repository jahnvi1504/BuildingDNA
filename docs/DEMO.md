# Three-minute demo runbook

## 0:00–0:30 — establish the live loop

Open a terminal and run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_ems_callback.py
```

Highlight `CALLBACK_PROOF=PASS`, the changing zone temperatures, and the
alternating actuator readback values. State that both occur inside one
EnergyPlus process.

## 0:30–1:20 — show the architecture

Open `docs/ARCHITECTURE.md`. Trace EnergyPlus → Tier 1 → synchronous Tier 2 →
Tier 1 clamp. Emphasize that Tier 1 has no LLM or network dependency.

Run the isolated end-to-end proof:

```powershell
.\.venv\Scripts\python.exe scripts\run_integrated_demo.py
```

Point to `INTEGRATED_LLM_ENERGYPLUS_PROOF=PASS`, the local Llama 3.1 8B
`set_setpoint` action, Tier 1's bounded decision, and eight matching actuator
readbacks. Ollama serves inference entirely on the demo machine.

## 1:20–2:30 — dashboard and evidence

```powershell
.\.venv\Scripts\streamlit.exe run dashboard.py
```

Show the 8.73% electricity reduction, 8.17% carbon reduction, 61.47% reduction
in estimated comfort violations, and the Tier 2 reasoning panel. Explain that
the values come from matched four-season runs, that Tier 2 completed 56/56
12-hour supervisory checkpoints, and that the measured savings are attributed
to Tier 1 because the long-run Tier 2 log contains no mutating setpoint action.

## 2:30–3:00 — self-healing

Run:

```powershell
.\.venv\Scripts\python.exe scripts\run_self_healing_demo.py
```

Show the initial EnergyPlus fatal termination, the local LLM's `patch_idf` tool call,
the exact old/new schedule reference, and `SELF_HEALING_PROOF=PASS`. The
repaired restart completes with 9,512 callbacks and no severe/fatal errors.
Both the faulted and repaired disposable IDFs are committed under
`models/runtime/`; the canonical baseline is never changed.
