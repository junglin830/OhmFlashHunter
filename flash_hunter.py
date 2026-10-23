# -*- coding: utf-8 -*-
"""OhmFlashHunter — find (and hide) every console window that flashes on your Windows desktop.

Why: on Windows 11 the default terminal is Windows Terminal. Any console program started by a
background process (AI coding agents, MCP servers, WMI, scheduled jobs, pythonw...) without
CREATE_NO_WINDOW / `conhost --headless` pops a terminal window. `-WindowStyle Hidden` does NOT help.

How:
  1. SetWinEventHook(EVENT_OBJECT_SHOW): event driven, catches even 0.1 s flashes (no polling).
     Only console classes: ConsoleWindowClass (classic conhost) and CASCADIA_HOSTING_WINDOW_CLASS (WT).
  2. A tracker records every new process (command line + parent chain) every 0.2 s, kept 30 s.
  3. On a console window: AttachConsole + GetConsoleWindow on the processes born in the previous
     4 s. Processes started with CREATE_NO_WINDOW have no window (NULL), real culprits do — so the
     exact culprit is named. Logged to flash_hunter.jsonl + summary flash_hunter_report.md.
  4. Auto-hide shield: a ConsoleWindowClass window whose parent chain reaches WmiPrvSE.exe or an AI
     agent (claude.exe / codex.exe / chatgpt.exe), and NOT explorer.exe (= you opened it yourself),
     is hidden with ShowWindow(SW_HIDE) inside the event callback (~30-60 ms). The program keeps
     running. Put FLASHHUNTER_SHOW in a window title to opt out.
     Needs classic conhost as default terminal (see set_default_terminal_conhost.ps1) — Windows
     Terminal windows cannot be hidden safely.

Run with pythonw (Task Scheduler, at logon). Single instance. Errors go to flash_hunter.err.
Env: FLASHHUNTER_DIR (log folder, default: next to this file),
     FLASHHUNTER_OURS (semicolon-separated folders whose scripts count as "ours"),
     FLASHHUNTER_NOTIFY (optional command run with the new culprit text as last argument).
"""
import ctypes, ctypes.wintypes as w, datetime, json, os, sys, threading, time, traceback
from collections import deque, Counter

HERE = os.environ.get("FLASHHUNTER_DIR") or os.path.dirname(os.path.abspath(__file__))
OURS = [p.strip().lower().replace("/", "\\") for p in os.environ.get("FLASHHUNTER_OURS", "").split(";") if p.strip()]
LOG = os.path.join(HERE, "flash_hunter.jsonl")
REPORT = os.path.join(HERE, "flash_hunter_report.md")
ERR = os.path.join(HERE, "flash_hunter.err")
SEEN_SIG = os.path.join(HERE, "flash_hunter_seen.json")
CONSOLE_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"}
CONSOLE_EXES = {"cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe", "python.exe", "py.exe", "node.exe",
                "git.exe", "gh.exe", "bash.exe", "sh.exe", "wsl.exe", "cscript.exe", "taskkill.exe", "where.exe",
                "npx.cmd", "uv.exe", "uvx.exe", "nvidia-smi.exe", "netsh.exe", "reg.exe", "schtasks.exe",
                "wmic.exe", "tasklist.exe", "openconsole.exe", "ffmpeg.exe", "ffprobe.exe", "curl.exe"}

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import psutil  # noqa: E402


def err(where, e=None):
    try:
        with open(ERR, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.datetime.now(), where))
            if e:
                f.write("".join(traceback.format_exception(type(e), e, e.__traceback__)) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- process tracker
_procs = {}                 # pid -> info (live + recent)
_recent = deque(maxlen=4000)  # (t, info) for newly created processes
_lock = threading.Lock()


def _info(p):
    try:
        with p.oneshot():
            cmd = " ".join(p.cmdline())[:300]
            return {"pid": p.pid, "name": p.name(), "cmd": cmd, "ppid": p.ppid(),
                    "exe": (p.exe() or "")[:200], "created": p.create_time()}
    except Exception:
        return {"pid": p.pid, "name": "?", "cmd": "", "ppid": None, "exe": "", "created": 0}


def chain(pid, depth=6):
    out, cur, seen = [], pid, set()
    for _ in range(depth):
        if cur in seen or cur is None:
            break
        seen.add(cur)
        with _lock:
            i = _procs.get(cur)
        if i is None:
            try:
                i = _info(psutil.Process(cur))
            except Exception:
                break
        out.append("%s#%s[%s]" % (i["name"], i["pid"], i["cmd"][:160]))
        cur = i["ppid"]
    return out


def tracker():
    first = True
    while True:
        try:
            now = time.time()
            live = set()
            for p in psutil.process_iter():
                live.add(p.pid)
                with _lock:
                    known = p.pid in _procs
                if not known:
                    i = _info(p)
                    with _lock:
                        _procs[p.pid] = i
                    if not first:
                        _recent.append((now, i))
            with _lock:  # forget dead processes after 60 s (keep for late attribution)
                for pid in [k for k, v in _procs.items() if k not in live and now - v.get("_dead", now) > 60]:
                    _procs.pop(pid, None)
                for k, v in _procs.items():
                    if k not in live:
                        v.setdefault("_dead", now)
            first = False
        except Exception as e:
            err("tracker", e)
        time.sleep(0.2)


# ---------------------------------------------------------------- classification
def classify(texts):
    t = " ".join(texts).lower()
    if any(p in t.replace("/", "\\") for p in OURS):
        return "ours"
    if "codex" in t or "chatgpt" in t:
        return "codex"
    if "\\windowsapps\\claude_" in t or "claude.exe" in t or "claude-code" in t:
        return "claude"
    return "other"


def signature(ev):
    c = (ev.get("culprit") or [{}])[0]
    head = c.get("chain")
    if not head:
        return ev["category"] + "|(exited; window title) " + (ev.get("title") or "?")[:80]
    parts = []
    for x in head[:4]:
        name = x.split("#")[0]
        arg = x.split("[", 1)[1][:60] if "[" in x and name.lower() in ("cmd.exe", "powershell.exe", "pwsh.exe", "python.exe", "pythonw.exe", "node.exe", "wscript.exe") else ""
        parts.append(name + (" " + arg if arg else ""))
    return ev["category"] + "|" + " <- ".join(parts)


def notify(ev, sig):
    try:
        seen = json.load(open(SEEN_SIG, encoding="utf-8")) if os.path.exists(SEEN_SIG) else {}
    except Exception:
        seen = {}
    first = sig not in seen
    seen[sig] = seen.get(sig, 0) + 1
    try:
        json.dump(seen, open(SEEN_SIG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass
    if not first:
        return
    cmd = os.environ.get("FLASHHUNTER_NOTIFY")
    if not cmd:
        return
    try:
        import shlex, subprocess
        subprocess.Popen(shlex.split(cmd, posix=False) + ["New console-window culprit (%s): %s" % (ev["category"], sig.split("|", 1)[1][:160])],
                         creationflags=0x08000000)
    except Exception as e:
        err("notify", e)


def write_report():
    try:
        events = [json.loads(l) for l in open(LOG, encoding="utf-8") if l.strip()]
    except Exception:
        return
    today = datetime.date.today().isoformat()
    week = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    recent = [e for e in events if e["ts"][:10] >= week]
    by_sig = Counter(e["sig"] for e in recent)
    lines = ["# Console flash report (OhmFlashHunter)", "",
             "Updated %s - last 7 days: %d flashes, today: %d" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                                 len(recent), sum(1 for e in recent if e["ts"][:10] == today)), "",
             "| Count | Category | Culprit (process chain) | Last seen |", "|---|---|---|---|"]
    for sig, n in by_sig.most_common(30):
        last = max(e["ts"] for e in recent if e["sig"] == sig)
        cat, who = sig.split("|", 1)
        lines.append("| %d | %s | `%s` | %s |" % (n, cat, who.replace("|", "/"), last))
    lines += ["", "Category: ours = scripts in FLASHHUNTER_OURS folders; codex / claude = AI agent apps; other = everything else.",
              "Raw log: `flash_hunter.jsonl` (window owner chain + processes born 4 s before). Hidden windows: `flash_hunter_autohide.log`."]
    try:
        open(REPORT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    except Exception as e:
        err("report", e)


SKIP_NAMES = {"conhost.exe", "openconsole.exe", "windowsterminal.exe"}
k32 = ctypes.windll.kernel32
k32.GetConsoleWindow.restype = w.HWND


def console_window_of(pid):
    """Attach to pid's console and return its console window handle (0 = no window / hidden).

    A process started with CREATE_NO_WINDOW still gets a conhost, but GetConsoleWindow()
    returns NULL — that is exactly the difference between "hidden" and "flashes"."""
    if not k32.AttachConsole(pid):
        return None
    try:
        return k32.GetConsoleWindow() or 0
    finally:
        k32.FreeConsole()


def on_console_window(hwnd, cls, title, owner_pid, t0):
    time.sleep(0.4)  # give the tracker one or two passes to see the new processes
    with _lock:
        cands = [(t, i) for t, i in _recent if t0 - 4 <= t <= t0 + 0.5
                 and i["name"].lower() in CONSOLE_EXES and i["name"].lower() not in SKIP_NAMES]
    probed = []
    for t, i in sorted(cands, key=lambda x: abs(x[0] - t0))[:12]:
        cw = console_window_of(i["pid"])
        probed.append((t, i, cw))
    # culprit: a process that owns a real console window; prefer the root of its subtree
    u32 = ctypes.windll.user32
    u32.GetWindow.restype = w.HWND
    u32.GetAncestor.restype = w.HWND

    def matches(cw):
        # classic conhost: the console window IS the shown window;
        # Windows Terminal: the console is a PseudoConsoleWindow owned by the shown WT window
        if not cw:
            return False
        if cw == hwnd:
            return True
        return hwnd in (u32.GetWindow(cw, 4), u32.GetAncestor(cw, 3))

    exact = [(t, i) for t, i, cw in probed if matches(cw)]
    owners = exact or [(t, i) for t, i, cw in probed if cw and u32.IsWindowVisible(cw)]
    pids = {i["pid"] for _, i in owners}
    roots = [(t, i) for t, i in owners if i["ppid"] not in pids] or owners
    time.sleep(1.0)
    tb = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, tb, 512)
    late_title = tb.value
    owner = chain(owner_pid)
    culprit = [{"dt": round(t - t0, 2), "chain": chain(i["pid"]) or ["%s#%s[%s]" % (i["name"], i["pid"], i["cmd"])]}
               for t, i in sorted(roots, key=lambda x: x[0])[:3]]
    others = [{"dt": round(t - t0, 2), "console_window": cw is not None and bool(cw),
               "chain": (chain(i["pid"]) or ["%s#%s" % (i["name"], i["pid"])])[:3]}
              for t, i, cw in probed if (t, i) not in roots][:6]
    texts = [title, late_title] + owner + [x for c in culprit for x in c["chain"]]
    if not culprit:  # fell back: process already gone; use title + time-nearest candidates
        texts += [x for c in others for x in c["chain"]]
    ev = {"ts": datetime.datetime.fromtimestamp(t0).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], "class": cls,
          "title": (late_title or title)[:200], "owner_chain": owner, "culprit": culprit,
          "others": others, "confidence": "exact" if exact else ("medium" if culprit else "low"), "category": classify(texts)}
    ev["sig"] = signature(ev)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    notify(ev, ev["sig"])
    write_report()



# ---------------------------------------------------------------- auto-hide shield (2026-10-23)
# Default terminal switched back to conhost (HKCU\Console\%%Startup Delegation* = conhost GUID),
# so a classic conhost window can simply be hidden with ShowWindow(SW_HIDE). Console windows spawned in the
# background by AI agents / WMI are hidden inside the EVENT_OBJECT_SHOW callback (milliseconds).
# Windows you open yourself (explorer.exe in the chain) and titles containing FLASHHUNTER_SHOW are left alone.
AI_MARKERS = ("\\windowsapps\\claude_", "codex", "chatgpt")


class _PE32(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", w.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def _snapshot():
    """pid -> (ppid, exe name lower). One pure-ctypes Toolhelp snapshot (a few ms) - no psutil, so hiding stays fast."""
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = w.HANDLE
    h = k.CreateToolhelp32Snapshot(0x2, 0)
    out = {}
    if not h or h == w.HANDLE(-1).value:
        return out
    try:
        e = _PE32(); e.dwSize = ctypes.sizeof(_PE32)
        ok = k.Process32FirstW(h, ctypes.byref(e))
        while ok:
            out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile.lower())
            ok = k.Process32NextW(h, ctypes.byref(e))
    finally:
        k.CloseHandle(h)
    return out


AI_NAMES = ("claude.exe", "codex.exe", "chatgpt.exe")


def should_autohide(owner_pid, title):
    if "FLASHHUNTER_SHOW" in (title or ""):
        return False
    snap = _snapshot()
    cur, seen = owner_pid, set()
    for _ in range(12):
        if not cur or cur in seen:
            break
        seen.add(cur)
        rec = snap.get(cur)
        if rec is None:  # parent already exited -> fall back to the tracker cache
            with _lock:
                i = _procs.get(cur)
            if not i:
                break
            rec = (i["ppid"], (i["name"] or "").lower())
        ppid, name = rec
        if name == "explorer.exe":
            return False
        if name == "wmiprvse.exe" or name in AI_NAMES:
            return True
        cur = ppid
    return False


# ---------------------------------------------------------------- window events
WINEVENTPROC = ctypes.WINFUNCTYPE(None, w.HANDLE, w.DWORD, w.HWND, w.LONG, w.LONG, w.DWORD, w.DWORD)
EVENT_OBJECT_SHOW = 0x8002
WINEVENT_OUTOFCONTEXT = 0x0000
_handled = {}


def _cb(hook, event, hwnd, id_obj, id_child, thread, ms):
    try:
        if id_obj != 0 or not hwnd:
            return
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        cls = buf.value
        if cls not in CONSOLE_CLASSES:
            return
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return
        now = time.time()
        if now - _handled.get(hwnd, 0) < 5:
            return
        _handled[hwnd] = now
        tb = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd, tb, 512)
        pid = w.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if cls == "ConsoleWindowClass":
            try:
                t_dec = time.perf_counter()
                if should_autohide(pid.value, tb.value):
                    ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
                    ms = (time.perf_counter() - t_dec) * 1000
                    with open(os.path.join(HERE, "flash_hunter_autohide.log"), "a", encoding="utf-8") as lf:
                        lf.write("%s hid pid=%s in %.0fms (event->hide %.0fms) %s\n" % (
                            datetime.datetime.now(), pid.value, ms, (time.time() - now) * 1000 + ms * 0, tb.value[:150]))
            except Exception as e:
                err("autohide", e)
        threading.Thread(target=lambda: _safe(on_console_window, hwnd, cls, tb.value, pid.value, now),
                         daemon=True).start()
    except Exception as e:
        err("callback", e)


def _safe(fn, *a):
    try:
        fn(*a)
    except Exception as e:
        err(fn.__name__, e)


_proc = WINEVENTPROC(_cb)


def single_instance():
    k = ctypes.windll.kernel32
    k.CreateMutexW.restype = w.HANDLE
    h = k.CreateMutexW(None, False, "Local\\OhmFlashHunter")
    return h if k.GetLastError() != 183 else None  # ERROR_ALREADY_EXISTS


def main():
    if not single_instance():
        return
    threading.Thread(target=tracker, daemon=True).start()
    hook = ctypes.windll.user32.SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, None, _proc, 0, 0,
                                                WINEVENT_OUTOFCONTEXT)
    if not hook:
        err("SetWinEventHook failed")
        return
    msg = w.MSG()
    while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
        ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    if "--report" in sys.argv:
        write_report(); print(open(REPORT, encoding="utf-8").read())
    else:
        try:
            main()
        except Exception as e:
            err("main", e)
