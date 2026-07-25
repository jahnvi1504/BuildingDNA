$runRoot = "outputs\matched-12h"
$reasoningPath = Join-Path $runRoot "agent\reasoning.jsonl"
$summaryPath = Join-Path $runRoot "agent\summary.json"
$comparisonPath = Join-Path $runRoot "comparison.json"

while ($true) {
    Clear-Host
    Write-Host "Eco-Loop matched 12-hour Tier 2 evaluation" -ForegroundColor Cyan
    Write-Host "Workspace: $((Get-Location).Path)"
    Write-Host ""

    $events = @()
    if (Test-Path -LiteralPath $reasoningPath) {
        $events = @(
            Get-Content -LiteralPath $reasoningPath |
                Where-Object { $_.Trim() } |
                ForEach-Object { $_ | ConvertFrom-Json }
        )
    }

    $percent = [Math]::Round(100.0 * $events.Count / 56, 1)
    Write-Host "Tier 2 progress: $($events.Count) / 56 ($percent%)" -ForegroundColor Yellow

    if ($events.Count -gt 0) {
        $latest = $events[-1]
        Write-Host "Latest simulated time: $($latest.simulation_time)"
        Write-Host "Latest event type:     $($latest.type)"
        Write-Host "Latest logged time:    $($latest.logged_at)"
        Write-Host ""
        Write-Host "Latest justification:"
        Write-Host $latest.justification
    }

    Write-Host ""
    if (Test-Path -LiteralPath $comparisonPath) {
        Write-Host "RUN COMPLETE" -ForegroundColor Green
        Get-Content -LiteralPath $comparisonPath
        Write-Host ""
        Write-Host "This window will remain open. Press Ctrl+C to close it."
        break
    }
    elseif (Test-Path -LiteralPath $summaryPath) {
        Write-Host "EnergyPlus finished; final comparison is being generated." -ForegroundColor Green
    }
    else {
        Write-Host "EnergyPlus + local Llama are running..." -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "Refreshing every 15 seconds. Press Ctrl+C to stop watching."
    Start-Sleep -Seconds 15
}

while ($true) {
    Start-Sleep -Seconds 60
}
