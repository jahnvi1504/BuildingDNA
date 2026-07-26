# BuildingDNA three-minute demo

## Before recording

Do not spend the video waiting for local inference. Generate and verify all
proofs beforehand, then use the committed JSON evidence during the recording.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify_ems_callback.py
.\.venv\Scripts\python.exe scripts\run_integrated_demo.py
.\.venv\Scripts\python.exe scripts\run_self_healing_demo.py
.\.venv\Scripts\streamlit.exe run dashboard.py
```

Confirm that the dashboard shows:

- `MATCHED EVALUATION VERIFIED`;
- `LLM -> ACTUATOR VERIFIED`;
- `SELF-HEALING VERIFIED`;
- 8.73% energy reduction;
- 8.17% carbon reduction;
- 61.47% fewer estimated comfort violations.

## 0:00-0:20 - The hook

Show the dashboard hero and say:

> Buildings use enormous amounts of energy, but conventional schedules cannot
> react to changing occupancy, comfort, or grid conditions. BuildingDNA turns
> an EnergyPlus building into a closed-loop agent that senses, reasons, acts,
> verifies, and recovers.

Pause on the three verification badges. Establish immediately that this is an
operational proof, not a recommendation-only chatbot.

## 0:20-0:55 - Quantified outcome

Show the four KPI cards and the baseline overlay.

Say:

> Against the identical building and weather, BuildingDNA reduced measured
> electricity from 9,156.2 to 8,356.5 kilowatt-hours: an 8.73% reduction. It
> also reduced estimated occupied comfort violations by 61.47%, so savings did
> not come from simply sacrificing occupants.

Show the representative-period label and add:

> These are four matched seasonal weeks totaling 672 simulated hours, not
> inflated annualized claims. Both simulations exited successfully.

## 0:55-1:25 - Show the live control loop

Switch briefly to
`outputs/callback-proof/callback-proof.json` or a prepared terminal showing
`CALLBACK_PROOF=PASS`.

Point out:

- changing zone-temperature readings;
- alternating requested cooling setpoints;
- identical actuator readbacks;
- EnergyPlus exit code 0.

Say:

> This callback runs before the HVAC managers. Sensor values and actuator
> writes occur inside the same active EnergyPlus process.

Then show `outputs/integrated-demo/integrated-proof.json`:

> A local Llama 3.1 8B model called `set_setpoint`. Tier 1 validated the request,
> injected 25 degrees Celsius into EnergyPlus, and eight readbacks matched.
> The LLM proposes; deterministic safety remains the final authority.

## 1:25-1:55 - Explain the intelligence

Show the policy chart and switch zones once.

Say:

> Tier 1 reacts at every system timestep. Tier 2 reasons at a slower supervisory
> cadence using compact telemetry. A 48-hour macro-policy score balances 45%
> energy, 35% comfort, and 20% carbon, then selects Energy Saver, Balanced, or
> Comfort Priority.

Point to the colored policy markers:

> Lines connect consecutive episodes inside each simulated seasonal week.
> Marker colors show the active policy; the large gaps are calendar periods we
> intentionally did not simulate.

Scroll to the compact reasoning audit:

> Every checkpoint remains traceable by simulated day and active policy, with a
> Jump control back to the corresponding telemetry.

## 1:55-2:25 - Show autonomous recovery

Open `outputs/self-healing-demo/self-healing-proof.json`.

Say:

> We deliberately broke an IDF schedule reference. EnergyPlus failed with a
> real fatal model error. The local LLM diagnosed that log and called the
> bounded `patch_idf` tool. BuildingDNA validated the exact object and field
> against the EnergyPlus data dictionary, created a backup, patched a disposable
> copy, and restarted automatically.

Highlight:

- fault exit code 1;
- `patch_idf`;
- old and new schedule names;
- recovery exit code 0;
- 9,512 recovered callbacks;
- no severe or fatal recovery errors.

## 2:25-2:50 - Architecture and resilience

Show this flow from `docs/ARCHITECTURE.md`:

```text
EnergyPlus -> Tier 1 -> local LLM/MCP -> Tier 1 validation -> actuators
     ^                                                        |
     +---------------- telemetry and readback ----------------+
```

Say:

> Ollama runs locally and no inference secret leaves the machine. If the LLM is
> unavailable, slow, or malformed, the request times out, the failure is logged,
> and Tier 1 continues. Intelligence is optional; safety is not.

## 2:50-3:00 - Close

Return to the dashboard KPIs and say:

> BuildingDNA proves the full Physical AI loop: measurable savings, protected
> comfort, local reasoning, actuator verification, and autonomous recovery.
> It does not just tell a building what to do. It safely does it and proves it.

## Claims to phrase carefully

Use these exact distinctions:

- Say **representative-period savings**, not annual savings.
- Say **PMV estimate** or **PMV proxy**, not ISO-certified PMV.
- Say the long-run measured savings are attributable to **Tier 1**.
- Say the separate integrated proof verifies the **LLM-to-actuator path**.
- Say self-healing performs a validated patch and **automatic restart**, not
  arbitrary physics-state resumption.

These qualifications make the demonstration more credible, not less.
