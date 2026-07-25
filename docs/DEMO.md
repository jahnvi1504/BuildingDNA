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

Open `docs/ARCHITECTURE.md`. Trace EnergyPlus → Tier 1 → asynchronous Tier 2 →
Tier 1 clamp. Emphasize that Tier 1 has no LLM or network dependency.

Start a short agent run or show the saved annual output:

```powershell
.\.venv\Scripts\ecoloop.exe simulate --mode agent
```

For a live Groq demonstration, first set a newly rotated key in the terminal:

```powershell
$env:GROQ_API_KEY = "..."
```

Never show the key on screen.

## 1:20–2:30 — dashboard and evidence

```powershell
.\.venv\Scripts\streamlit.exe run dashboard.py
```

Show the 1.58% electricity reduction, carbon reduction, comfort chart, and
reasoning panel. Explain that the checked-in annual comparison was generated
before the dashboard.

## 2:30–3:00 — self-healing

Show the severe node error in `outputs/small-office-smoke/eplusout.err`, then
the successful repaired run. Briefly open `patch_idf` in
`src/ecoloop/mcp_server.py` and explain validation, backup, patch, and restart.

