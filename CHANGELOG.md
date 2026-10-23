# Changelog

## V1.0.0 — 2026-10-23
- First public release.
- Event-driven console-window detector (`EVENT_OBJECT_SHOW`) with exact culprit attribution
  (`AttachConsole` + `GetConsoleWindow`), JSONL log and 7-day Markdown report.
- Auto-hide shield: WMI- / AI-agent-spawned conhost windows hidden in ~30–60 ms (pure-ctypes Toolhelp
  snapshot; an earlier psutil-based walk occasionally took ~2 s).
- `set_default_terminal_conhost.ps1` (with `-Undo`), `spawn_hidden.ps1`, `install.ps1` (Task Scheduler, logon).
- `extras/sitecustomize.py`: CREATE_NO_WINDOW for every subprocess of console-less Python.
- `docs/FIXES.md`: seven root causes with fixes (MCP servers missing CREATE_NO_WINDOW, `npx.cmd`,
  WMI + Windows Terminal, uv `pythonw` trampoline, sitecustomize, MSIX virtualization, process-list watchers).