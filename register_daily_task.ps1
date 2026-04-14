$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $ProjectRoot '.env'

$settings = @{}
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -notmatch '=') {
            return
        }
        $parts = $_ -split '=', 2
        $settings[$parts[0].Trim()] = $parts[1].Trim()
    }
}

$taskName = if ($settings.ContainsKey('SCHEDULED_TASK_NAME')) { $settings['SCHEDULED_TASK_NAME'] } else { 'InstagramNatureAutoPoster' }
$runTime = if ($settings.ContainsKey('DAILY_RUN_TIME')) { $settings['DAILY_RUN_TIME'] } else { '09:00' }
$runner = Join-Path $ProjectRoot 'run_daily.ps1'
$taskCommand = "powershell.exe -ExecutionPolicy Bypass -File `"$runner`""

schtasks /Create /SC DAILY /TN $taskName /TR $taskCommand /ST $runTime /F