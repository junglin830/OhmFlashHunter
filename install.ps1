# Register OhmFlashHunter to start at logon (pythonw, no window) and start it now.
#   powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 [-Ours "D:\work;D:\scripts"] [-Uninstall]
param([string]$Ours = "", [switch]$Uninstall)
$name = 'OhmFlashHunter'
if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'flash_hunter\.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    "Uninstalled."; return
}
$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "pythonw.exe not found on PATH (install Python 3.9+ from python.org)." }
& ($py -replace 'pythonw\.exe$', 'python.exe') -m pip install --quiet -r "$PSScriptRoot\requirements.txt"
if ($Ours) { [Environment]::SetEnvironmentVariable('FLASHHUNTER_OURS', $Ours, 'User') }
$act = New-ScheduledTaskAction -Execute $py -Argument "`"$PSScriptRoot\flash_hunter.py`"" -WorkingDirectory $PSScriptRoot
$trg = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $name -Action $act -Trigger $trg -Settings $set -Force | Out-Null
Start-ScheduledTask -TaskName $name
"Installed and started. Report: $PSScriptRoot\flash_hunter_report.md"