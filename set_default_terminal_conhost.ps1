# Make classic conhost the default terminal for console apps (instead of "Let Windows decide" =
# Windows Terminal). Required for the auto-hide shield: a conhost window can be hidden instantly,
# a Windows Terminal window cannot (and it ignores -WindowStyle Hidden).
# Side effect: double-clicking a .bat or Win+R "cmd" opens a classic console window.
# Opening "Terminal" from the Start menu is unaffected.  Undo:  -Undo
#
# IMPORTANT: if you run this from inside an MSIX-packaged app (e.g. an AI desktop app's shell tool),
# HKCU writes may land in the app's private virtual registry and have no effect. Run it from a normal
# PowerShell, or through spawn_hidden.ps1 (WMI escapes the container).
param([switch]$Undo)
$k = 'HKCU:\Console\%%Startup'
$conhost = '{B23D10C0-E52E-411E-9D5B-C09FDF709C7D}'
if (-not (Test-Path $k)) { New-Item -Path $k -Force | Out-Null }
if ($Undo) {
    Remove-ItemProperty $k -Name DelegationConsole, DelegationTerminal -ErrorAction SilentlyContinue
    "Default terminal reset to 'Let Windows decide'."
} else {
    New-ItemProperty $k -Name DelegationConsole  -Value $conhost -PropertyType String -Force | Out-Null
    New-ItemProperty $k -Name DelegationTerminal -Value $conhost -PropertyType String -Force | Out-Null
    "Default terminal set to Windows Console Host (conhost)."
}
Get-ItemProperty $k | Select-Object DelegationConsole, DelegationTerminal