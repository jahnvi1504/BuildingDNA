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
.\.venv\Scripts\ecoloop.exe debate-preview --mode compact
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

The dashboard labels its animated timeline as **Sampled Period Replay**. It
uses completed telemetry, reasoning events, and the generated 48-hour
macro-policy log; it does not present saved data as a live stream or the
four-week sample as an annual total.

Tier 2 defaults to the local Ollama server. Override these values only when
using another self-hosted OpenAI-compatible endpoint:

```dotenv
ECOLOOP_LLM_BASE_URL=http://localhost:11434/v1
ECOLOOP_LLM_API_KEY=ollama
ECOLOOP_LLM_MODEL=llama3.1:8b
ECOLOOP_LLM_TIMEOUT_SECONDS=120
ECOLOOP_REASON_ENABLED=true
ECOLOOP_REASON_INTERVAL_MINUTES=720
```

Run `ecoloop reason-smoke` before a long simulation. It makes one real local
tool-calling request and exercises telemetry plus bounded control tools. Tier 1
continues independently when Tier 2 is disabled or Ollama is unavailable.

## MCP

```powershell
.\.venv\Scripts\ecoloop.exe mcp
```

This starts the eight-tool MCP server over stdio.

## AI debate mode

`AI_DEBATE_MODE=compact` is the recommended demo setting. It asks the configured
local model for Energy Saver, Comfort Guardian, and BuildingDNA Arbiter
perspectives in one strict JSON response. `full` makes three sequential role
calls; `off` preserves the original single-agent flow.

To populate the dashboard debate panel without rerunning EnergyPlus:

```powershell
.\.venv\Scripts\ecoloop.exe debate-preview --mode compact
```

The preview uses the saved matched summary, never applies its proposed action,
and labels all projected savings as estimates. During a live agent simulation,
only the Arbiter's final action is queued for the unchanged Tier 1 safety clamp.
