# Local setup

The prepared workspace uses EnergyPlus 26.1.0 unpacked under `.local/` and a
Python 3.12 environment under `.venv/`.

Tier 2 uses Ollama's local OpenAI-compatible API. Start Ollama and install the
tool-capable model before verification:

```powershell
ollama pull llama3.1:8b
ollama serve
```

## Verify

```powershell
.\.venv\Scripts\python.exe scripts\verify_ems_callback.py
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\ecoloop.exe reason-smoke
.\.venv\Scripts\ecoloop.exe policy-evaluate
.\.venv\Scripts\python.exe scripts\run_integrated_demo.py
.\.venv\Scripts\python.exe scripts\run_self_healing_demo.py
```

## Run

```powershell
.\.venv\Scripts\ecoloop.exe simulate --mode baseline
.\.venv\Scripts\ecoloop.exe simulate --mode agent
.\.venv\Scripts\streamlit.exe run dashboard.py
```

The dashboard labels its animated timeline as **Simulated Year Replay**. It
uses completed telemetry, reasoning events, and the generated 48-hour
macro-policy log; it does not present saved data as a live stream.

Tier 2 defaults to the local Ollama server. Override these values only when
using another self-hosted OpenAI-compatible endpoint:

```dotenv
ECOLOOP_LLM_BASE_URL=http://localhost:11434/v1
ECOLOOP_LLM_API_KEY=ollama
ECOLOOP_LLM_MODEL=llama3.1:8b
ECOLOOP_REASON_ENABLED=true
```

Run `ecoloop reason-smoke` before a long simulation. It makes one real local
tool-calling request and exercises telemetry plus bounded control tools. Tier 1
continues independently when Tier 2 is disabled or Ollama is unavailable.

## MCP

```powershell
.\.venv\Scripts\ecoloop.exe mcp
```

This starts the eight-tool MCP server over stdio.
