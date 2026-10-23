# OhmFlashHunter

**Find, and then stop, every console window that flashes on your Windows desktop.**
Built for machines where AI coding agents (Claude, Codex…), MCP servers, uv/uvx, pythonw daemons
and scheduled jobs all spawn `cmd` / `powershell` in the background.

> 揪出（並藏起）Windows 桌面上每一個「一閃而過的 CMD／終端機視窗」。給同時跑很多 AI agent、MCP、
> 背景排程的電腦用。

- **Event driven.** A `SetWinEventHook(EVENT_OBJECT_SHOW)` hook. Catches 0.1 s flashes, no polling.
- **Names the real culprit.** It doesn't trust the window owner (always Windows Terminal / svchost).
  It calls `AttachConsole` + `GetConsoleWindow` on processes born in the previous 4 s. Only
  processes that really own a visible console count. The full parent chain is logged.
- **Auto-hide shield.** Console windows spawned by WMI or an AI agent (and not by you via
  Explorer) are hidden inside the callback, in ~30–60 ms. The program keeps running.
- **Report.** `flash_hunter_report.md` counts culprits for the last 7 days; `flash_hunter.jsonl` holds every event.
- **The fixes, too.** [`docs/FIXES.md`](docs/FIXES.md) lists every root cause we caught (MCP servers
  without `CREATE_NO_WINDOW`, `npx.cmd`, WMI + Windows Terminal, uv `pythonw` trampoline, MSIX
  virtualization…) and how to fix each. Includes `spawn_hidden.ps1` and `extras/sitecustomize.py`.

## Quick start
```powershell
git clone https://github.com/junglin830/OhmFlashHunter
cd OhmFlashHunter
# 1) let the shield hide windows: classic conhost as default terminal (undo: -Undo)
powershell -NoProfile -File set_default_terminal_conhost.ps1
# 2) run at logon (pythonw, no window); optional: mark your own script folders as "ours"
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Ours "D:\scripts"
```
Then just work. When something flashes, open `flash_hunter_report.md`:

```
| Count | Category | Culprit (process chain)                                              | Last seen |
| 6     | other    | powershell.exe powershell -NoProfile -WindowStyle Hidden ... <- ?    | ...       |
| 1     | ours     | cmd.exe cmd /c D:\scripts\start_comfy.bat <- ?                         | ...       |
```
Hidden windows are listed in `flash_hunter_autohide.log` with timing (`hid pid=… in 30ms`).

## Launch console programs from background code without a window
```powershell
powershell -NoProfile -File spawn_hidden.ps1 -Cmd 'cmd.exe /c build.bat > "C:\temp\log.txt"' -Wait
```
`-WindowStyle Hidden` does not work against Windows Terminal; `conhost.exe --headless` does.

## Options (environment variables)
| Variable | Meaning |
|---|---|
| `FLASHHUNTER_DIR` | where logs/report go (default: next to `flash_hunter.py`) |
| `FLASHHUNTER_OURS` | `;`-separated folders whose scripts are categorized **ours** |
| `FLASHHUNTER_NOTIFY` | command run once per *new* culprit, text appended as last argument |

Put `FLASHHUNTER_SHOW` in a window title to keep that window visible.

## Requirements
Windows 10/11, Python 3.9+ (`pythonw.exe` on PATH), `psutil`. No admin rights needed.

## Uninstall
`powershell -File install.ps1 -Uninstall` and `powershell -File set_default_terminal_conhost.ps1 -Undo`.

## Origin
A one-person studio in Taiwan runs most of its work through parallel AI agents on one PC. CMD
windows kept flashing for weeks, and every "fix" was a guess. This tool stopped the guessing:
it caught seven different causes in a few days. Once the agents' launches were hidden
automatically, the desktop finally went quiet.

License: MIT