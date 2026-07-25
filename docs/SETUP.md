# Local setup

The prepared workspace uses EnergyPlus 26.1.0 unpacked under `.local/` and a
Python 3.11 environment under `.venv/`.

## Verify

```powershell
.\.venv\Scripts\python.exe scripts\verify_ems_callback.py
.\.venv\Scripts\pytest.exe
```

## Run

```powershell
.\.venv\Scripts\ecoloop.exe simulate --mode baseline
.\.venv\Scripts\ecoloop.exe simulate --mode agent
.\.venv\Scripts\streamlit.exe run dashboard.py
```

To enable Tier 2, rotate the previously exposed Groq key and set the replacement
only in the current terminal:

```powershell
$env:GROQ_API_KEY = "replacement-key"
```

The default Groq model is `llama-3.3-70b-versatile`. Tier 1 operates when this
variable is missing.

## MCP

```powershell
.\.venv\Scripts\ecoloop.exe mcp
```

This starts the eight-tool MCP server over stdio.

