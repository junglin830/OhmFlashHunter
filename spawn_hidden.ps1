# Start a console program from a background context WITHOUT any window.
# Wraps the command in `conhost.exe --headless` and launches it through WMI (Win32_Process.Create),
# which also escapes MSIX app containers (e.g. AI desktop apps) so the process sees the real
# registry / AppData.
# `-WindowStyle Hidden`, `Start-Process -WindowStyle Hidden` and Win32_ProcessStartup ShowWindow=0
# do NOT stop Windows Terminal from opening a window. This does.
# Usage:
#   powershell -NoProfile -File spawn_hidden.ps1 -Cmd 'cmd.exe /c dir > "C:\temp\o.txt"' [-Wait] [-TimeoutSec 600]
param(
    [Parameter(Mandatory = $true)][string]$Cmd,
    [string]$Cwd = $env:USERPROFILE,
    [switch]$Wait,
    [int]$TimeoutSec = 600
)
$line = $Cmd.Trim()
if ($line -notmatch '^(\S*\\)?conhost(\.exe)?\s+--headless\b') {
    $line = "$env:WINDIR\System32\conhost.exe --headless $line"
}
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $line; CurrentDirectory = $Cwd }
if ($r.ReturnValue -ne 0) { Write-Error "Win32_Process.Create failed, ReturnValue=$($r.ReturnValue)"; exit 1 }
$procId = $r.ProcessId
if ($Wait) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Process -Id $procId -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
}
$procId