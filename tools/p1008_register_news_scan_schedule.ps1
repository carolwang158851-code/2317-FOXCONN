param(
  [switch]$Register,
  [switch]$Remove
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$bat = Join-Path $root "P1008_4_NEWS_SCAN.bat"
$tasks = @(
  @{ Name = "P1008 News Scan 0810 Preopen"; Time = "08:10"; Args = "--dry-run --allow-network --scan-window preopen" },
  @{ Name = "P1008 News Scan 1230 Intraday"; Time = "12:30"; Args = "--dry-run --allow-network --scan-window intraday" },
  @{ Name = "P1008 News Scan 1530 Postclose"; Time = "15:30"; Args = "--dry-run --allow-network --scan-window postclose" },
  @{ Name = "P1008 News Scan 2130 Global"; Time = "21:30"; Args = "--dry-run --allow-network --scan-window global" }
)

if (-not (Test-Path -LiteralPath $bat)) {
  throw "Missing BAT launcher: $bat"
}

if ($Remove) {
  foreach ($task in $tasks) {
    if (Get-ScheduledTask -TaskName $task.Name -ErrorAction SilentlyContinue) {
      Unregister-ScheduledTask -TaskName $task.Name -Confirm:$false
      Write-Host "[REMOVED] $($task.Name)"
    }
  }
  exit 0
}

if (-not $Register) {
  Write-Host "P1008 news scan schedule preview. No Windows task was changed."
  Write-Host "Run with -Register only after Owner approval. Scheduled runs fetch only enabled APPROVED sources from NEWS_SCAN_SOURCE_MANIFEST.json."
  foreach ($task in $tasks) {
    Write-Host ("- {0} at {1}: {2} {3}" -f $task.Name, $task.Time, $bat, $task.Args)
  }
  exit 0
}

foreach ($task in $tasks) {
  $action = New-ScheduledTaskAction -Execute $bat -Argument $task.Args -WorkingDirectory $root
  $trigger = New-ScheduledTaskTrigger -Daily -At $task.Time
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
  Register-ScheduledTask -TaskName $task.Name -Action $action -Trigger $trigger -Settings $settings -Description "P1008 observation-only scheduled news scan. Does not modify formal CSV or HOLD." -Force | Out-Null
  Write-Host "[REGISTERED] $($task.Name)"
}
