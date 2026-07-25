param(
    [string]$RunRoot = "outputs\matched-12h"
)

$agentSummaryPath = Join-Path $RunRoot "agent\summary.json"
$baselineSummaryPath = Join-Path $RunRoot "baseline\summary.json"
$reasoningPath = Join-Path $RunRoot "agent\reasoning.jsonl"
$resultPath = Join-Path $RunRoot "comparison.json"

while (-not (Test-Path -LiteralPath $agentSummaryPath)) {
    Start-Sleep -Seconds 30
}

$baseline = Get-Content -LiteralPath $baselineSummaryPath -Raw | ConvertFrom-Json
$agent = Get-Content -LiteralPath $agentSummaryPath -Raw | ConvertFrom-Json
$events = @(
    Get-Content -LiteralPath $reasoningPath |
        Where-Object { $_.Trim() } |
        ForEach-Object { $_ | ConvertFrom-Json }
)

$energyReduction = 100.0 * ($baseline.energy_kwh - $agent.energy_kwh) /
    [Math]::Max([double]$baseline.energy_kwh, 1e-9)
$carbonReduction = 100.0 * ($baseline.carbon_kg - $agent.carbon_kg) /
    [Math]::Max([double]$baseline.carbon_kg, 1e-9)
$comfortReduction = 100.0 * (
    $baseline.comfort_violation_count - $agent.comfort_violation_count
) / [Math]::Max([double]$baseline.comfort_violation_count, 1.0)

$eventTypes = @{}
foreach ($group in ($events | Group-Object type)) {
    $eventTypes[$group.Name] = $group.Count
}

$comparison = [ordered]@{
    completed_at = (Get-Date).ToUniversalTime().ToString("o")
    supervisory_interval_minutes = 720
    expected_tier2_cycles = 56
    actual_tier2_events = $events.Count
    tier2_event_types = $eventTypes
    baseline_exit_code = $baseline.exit_code
    agent_exit_code = $agent.exit_code
    baseline_energy_kwh = [Math]::Round([double]$baseline.energy_kwh, 4)
    agent_energy_kwh = [Math]::Round([double]$agent.energy_kwh, 4)
    electricity_reduction_percent = [Math]::Round($energyReduction, 4)
    baseline_carbon_kg = [Math]::Round([double]$baseline.carbon_kg, 4)
    agent_carbon_kg = [Math]::Round([double]$agent.carbon_kg, 4)
    carbon_reduction_percent = [Math]::Round($carbonReduction, 4)
    baseline_comfort_violations = $baseline.comfort_violation_count
    agent_comfort_violations = $agent.comfort_violation_count
    comfort_violation_reduction_percent = [Math]::Round($comfortReduction, 4)
}

$comparison |
    ConvertTo-Json -Depth 6 |
    Set-Content -LiteralPath $resultPath -Encoding utf8
