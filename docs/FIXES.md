# Why console windows keep flashing on Windows — every cause we found, and the fix

Found on one busy Windows 11 machine running Claude desktop, Codex, several MCP servers, uv/uvx,
pythonw daemons and dozens of scheduled jobs. Each cause below was caught red-handed by
`flash_hunter.py` (process chain + `GetConsoleWindow`), not guessed.

## 0. How to tell what really flashes
- A `conhost.exe` in the process list does **not** mean a visible window. CREATE_NO_WINDOW children
  also get a hidden conhost. Ask the process itself: `AttachConsole(pid)` + `GetConsoleWindow()`;
  NULL = hidden.
- A Windows Terminal window's owner is always `WindowsTerminal.exe` / `svchost.exe`. Useless.
  Match the window's timestamp against processes born in the seconds before it.
- The first WT tab title is the path of the first program attached, often the culprit.

## 1. MCP servers that spawn shells without CREATE_NO_WINDOW
A server started without a console (by a desktop app) that calls `subprocess.Popen(...)` for
`powershell`/`taskkill` without `creationflags=subprocess.CREATE_NO_WINDOW` gets a brand-new
console window, every call. Seen in a Windows automation MCP server's PowerShell tool
(`run_with_graceful_timeout`: only `CREATE_NEW_PROCESS_GROUP` was set).
**Fix:** add `| subprocess.CREATE_NO_WINDOW` to every Popen/run on Windows. (Fixed upstream in CursorTouch/Windows-MCP: update the package.) Note: uvx unpacks fresh
copies of the package into its cache, so a local patch gets lost. The sitecustomize in #5 covers
those copies too.

## 2. MCP servers launched via `npx`
`cmd /d /s /c npx.cmd -y <pkg>`: `npx` on Windows is a `.cmd` shim, so a `cmd.exe` sits in every
launch.
**Fix:** `npm i -g <pkg>` once, then point the MCP config `command` at `node.exe` and `args` at the
package's entry `.js` under `%APPDATA%\npm\node_modules\...`. No cmd, no npx, faster startup.
(Re-run `npm i -g` to upgrade.)

## 3. Anything started through WMI (`Win32_Process.Create`) or a hidden parent
On Windows 11 with the default terminal = "Let Windows decide" (Windows Terminal), WT adopts the
new console and shows a window. `-WindowStyle Hidden`, `Start-Process -WindowStyle Hidden` and
`Win32_ProcessStartup.ShowWindow = 0` do **not** stop it.
**Fix:** prefix the command with `conhost.exe --headless` (see `spawn_hidden.ps1`).
**Safety net:** `set_default_terminal_conhost.ps1` + the auto-hide shield in `flash_hunter.py`.
Agents forget rules; the shield doesn't.

## 4. uv virtualenv `pythonw.exe` trampoline (older uv)
Older uv (seen with 0.11.x) created `.venv\Scripts\pythonw.exe` as a trampoline that launched the
base **console** `python.exe`. Every daemon start was a WT window.
**Fix:** upgrade uv (fixed upstream; 0.13.5 is fine), or replace the venv's `pythonw.exe` with
CPython's own `Lib\venv\scripts\nt\venvwlauncher.exe` from the same base interpreter. Recreating the
venv with an old uv undoes it.

## 5. Any console-less Python that shells out
**Fix:** `extras/sitecustomize.py`. When the process has no console it forces CREATE_NO_WINDOW on
every subprocess. Put it in each base interpreter you use (python.org install, and uv-managed ones
under `%APPDATA%\uv\python\<ver>\Lib\`).

## 6. Trap: MSIX-packaged apps virtualize AppData and HKCU
Desktop apps shipped as MSIX (e.g. some AI desktop apps) run their tools inside the package
container. New files they write under `%APPDATA%`/`%LOCALAPPDATA%` and HKCU registry writes may go
to a private virtual layer. The shell sees them; the rest of Windows doesn't. Your "fix" silently
does nothing.
**Fix:** do such writes through WMI (`spawn_hidden.ps1`), which runs outside the container, then
verify from outside too.

## 7. Trap: process-list watchers that move/hide windows after the fact
Polling for new `cmd/conhost` processes and then looking for their window mostly logs
"no window found". It's watching the wrong thing (see #0) and is always too late.
An `EVENT_OBJECT_SHOW` WinEvent hook fires the moment the window appears.