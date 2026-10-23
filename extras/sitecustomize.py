# -*- coding: utf-8 -*-
"""Never flash a console window from a background (console-less) Python process.

Drop this file into a Python install's `Lib\site-packages` (or `Lib`) folder. Python imports it at
startup. When the current process has NO console (pythonw.exe, scheduled/background jobs, MCP
servers started by a desktop app), every subprocess.Popen / os.system call gets CREATE_NO_WINDOW
added, so child cmd/powershell/git/node processes never pop a window.
Interactive Python run from a terminal is untouched. Callers that explicitly ask for
CREATE_NEW_CONSOLE are respected.
"""
import sys

if sys.platform == "win32":
    try:
        import ctypes

        if ctypes.windll.kernel32.GetConsoleWindow() == 0:
            import subprocess

            _CNW = 0x08000000  # CREATE_NO_WINDOW
            _NEW = 0x00000010  # CREATE_NEW_CONSOLE (caller wants a window: respect it)
            _orig_init = subprocess.Popen.__init__

            def _quiet_init(self, *a, **kw):
                try:
                    cf = kw.get("creationflags", 0)
                    if not (cf & _NEW):
                        kw["creationflags"] = cf | _CNW
                except Exception:
                    pass
                return _orig_init(self, *a, **kw)

            subprocess.Popen.__init__ = _quiet_init

            import os as _os

            _orig_system = _os.system

            def _quiet_system(cmd):
                try:
                    return subprocess.call(cmd, shell=True)
                except Exception:
                    return _orig_system(cmd)

            _os.system = _quiet_system
    except Exception:
        pass