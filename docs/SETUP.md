# Local setup

The prepared workspace uses EnergyPlus 26.1.0 unpacked under `.local/` and a
Python 3.12 environment under `.venv/`.

## Verify

```powershell
.\.venv\Scripts\python.exe scripts\verify_ems_callback.py
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\ecoloop.exe reason-smoke
```

## Run

```powershell
.\.venv\Scripts\ecoloop.exe simulate --mode baseline
.\.venv\Scripts\ecoloop.exe simulate --mode agent
.\.venv\Scripts\streamlit.exe run dashboard.py
```

To enable Tier 2, rotate any previously exposed Groq key and store the replacement
in the ignored `.env` file:

```dotenv
GROQ_API_KEY=replacement-key
GROQ_MODEL=llama-3.3-70b-versatile
ECOLOOP_REASON_ENABLED=true
```

Run `ecoloop reason-smoke` before a long simulation. It makes one real Groq
request, exercises telemetry and bounded control tools, and redacts the key from
its output. Tier 1 continues independently when Tier 2 is disabled or unavailable.

## MCP

```powershell
.\.venv\Scripts\ecoloop.exe mcp
```

This starts the eight-tool MCP server over stdio.
