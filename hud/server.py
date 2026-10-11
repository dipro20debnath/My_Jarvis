"""Jarvis HUD backend.

Serves the live dashboard (static/) and a JSON API on 127.0.0.1:8765:
to-dos, calendar events, notes, timers, Jarvis tasks (run by a warm
OpenJarvis worker), instant PC actions, PC stats, the free-voice "brain"
(/api/assistant) and an ElevenLabs conversation token so the API key never
reaches the browser. Data lives in my-agent\\hud-data.json.

Run:  OpenJarvis\\.venv\\Scripts\\python.exe hud\\server.py
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import urllib.parse
import uuid
import winreg
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import edge_tts
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import quick

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AGENT_HOME = ROOT / "my-agent"
SRC = ROOT / "OpenJarvis"
DATA_FILE = AGENT_HOME / "hud-data.json"
WORKER_LOG = AGENT_HOME / "hud-worker.log"
PORT = 8765
OLLAMA = "http://127.0.0.1:11434"  # not "localhost": Windows tries IPv6 first (~2 s)
JARVIS_TIMEOUT_S = 600
MAX_TASKS_KEPT = 30
NO_WINDOW = subprocess.CREATE_NO_WINDOW

app = FastAPI(title="Jarvis HUD")
lock = threading.RLock()
runner = ThreadPoolExecutor(max_workers=1)  # one Jarvis job at a time


# =========================================================================== data


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load() -> dict:
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    for key in ("todos", "events", "tasks", "notes", "timers"):
        data.setdefault(key, [])
    data.setdefault("settings", {"auto_approve": False})
    return data


def _save(data: dict) -> None:
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATA_FILE)


with lock:
    _state = _load()
    # Jobs interrupted by a shutdown can't resume.
    for _t in _state["tasks"]:
        if _t["status"] in ("running", "pending", "queued"):
            _t.update(status="cancelled", result="Stopped when the HUD was closed.")
    # Timers that ran out while the HUD was closed would all ring at once.
    _cutoff = (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")
    _state["timers"] = [_t for _t in _state["timers"] if _t["ends"] > _cutoff]
    _save(_state)


def _find(items: list, item_id: str) -> dict:
    for it in items:
        if it["id"] == item_id:
            return it
    raise HTTPException(404, "not found")


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


# =========================================================================== env


def _user_env(name: str) -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return ""


# Your ElevenLabs Conversational agent (optional; the free voice works without it).
AGENT_ID = os.environ.get("ELEVENLABS_AGENT_ID") or _user_env("ELEVENLABS_AGENT_ID")


def _jarvis_env() -> dict:
    env = dict(os.environ)
    defaults = {
        "OPENJARVIS_HOME": str(AGENT_HOME),
        "OLLAMA_MODELS": str(ROOT / "ollama-models"),
        "JARVIS_NUM_CTX": "8192",
    }
    for name, value in defaults.items():
        env[name] = env.get(name) or _user_env(name) or value
    env["OLLAMA_HOST"] = OLLAMA
    env["PYTHONIOENCODING"] = "utf-8"
    env["PATH"] = os.pathsep.join(
        [str(Path.home() / ".local" / "bin"), str(ROOT / "Ollama"), env.get("PATH", "")]
    )
    return env


# =========================================================================== jarvis worker


class JarvisWorker:
    """Keeps one warm `jarvis_worker.py` process and sends it commands."""

    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None
        self.ready = threading.Event()
        self.pending: dict[str, dict] = {}
        self.start_lock = threading.Lock()

    def start(self) -> None:
        with self.start_lock:
            if self.proc and self.proc.poll() is None:
                return
            self.ready.clear()
            err = WORKER_LOG.open("a", encoding="utf-8")
            self.proc = subprocess.Popen(
                [sys.executable, str(HERE / "jarvis_worker.py")], cwd=SRC, env=_jarvis_env(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=NO_WINDOW,
            )
            threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("ready"):
                self.ready.set()
                continue
            slot = self.pending.pop(msg.get("id"), None)
            if slot:
                slot["result"] = msg
                slot["event"].set()
        for slot in list(self.pending.values()):  # the process died
            slot["result"] = {"ok": False, "content": "Jarvis worker stopped."}
            slot["event"].set()
        self.pending.clear()

    def run(self, task_id: str, command: str) -> dict:
        self.start()
        if not self.ready.wait(90):
            self.restart()
            return {"ok": False, "content": "Jarvis worker did not start in time."}
        slot = {"event": threading.Event()}
        self.pending[task_id] = slot
        # The agent otherwise takes the date from UTC (a day behind at night here).
        now = datetime.now()
        command = (f"[Context: it is now {now:%A %d %B %Y, %H:%M} in Dhaka, Bangladesh (UTC+6). "
                   f"Use this as today's date.]\n{command}")
        try:
            self.proc.stdin.write(json.dumps({"id": task_id, "command": command}, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except OSError:  # the process died between start() and now
            self.pending.pop(task_id, None)
            self.restart()
            return {"ok": False, "content": "Jarvis worker restarted, please try again."}
        if not slot["event"].wait(JARVIS_TIMEOUT_S):
            self.restart()
            return {"ok": False, "content": f"Timed out after {JARVIS_TIMEOUT_S} seconds."}
        return slot["result"]

    def restart(self) -> None:
        proc = self.proc
        if proc and proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=NO_WINDOW)
            try:
                proc.wait(10)  # else start() may still see it alive and not respawn
            except subprocess.TimeoutExpired:
                pass
        self.start()


worker = JarvisWorker()


def _run_task(task_id: str) -> None:
    with lock:
        task = _find(_state["tasks"], task_id)
        if task["status"] != "queued":
            return
        task.update(status="running", started=_now())
        _save(_state)
        command = task["command"]
    try:
        res = worker.run(task_id, command)
        status = "done" if res.get("ok") else "failed"
        result = res.get("content") or "Jarvis finished but returned no text."
        if status == "failed":
            result = "Jarvis failed: " + result
    except Exception as exc:  # report, never kill the runner
        status, result = "failed", f"Jarvis error: {exc}"
    with lock:
        task = _find(_state["tasks"], task_id)
        if task["status"] == "running":  # not cancelled meanwhile
            task.update(status=status, result=result, finished=_now())
        _save(_state)


def _queue(task: dict) -> None:
    task["status"] = "queued"
    runner.submit(_run_task, task["id"])


class TaskIn(BaseModel):
    command: str
    source: str = "voice"


@app.post("/api/tasks")
def create_task(body: TaskIn) -> dict:
    command = body.command.strip()
    if not command:
        raise HTTPException(400, "empty command")
    with lock:
        task = {"id": _new_id(), "command": command, "source": body.source,
                "created": _now(), "status": "pending", "result": ""}
        # Typed commands are deliberate; spoken ones can be misheard, so they
        # wait for approval unless auto-approve is on.
        if body.source == "typed" or _state["settings"].get("auto_approve"):
            _queue(task)
        _state["tasks"].insert(0, task)
        del _state["tasks"][MAX_TASKS_KEPT:]
        _save(_state)
        return task


def _pending_or(task_id: Optional[str]) -> dict:
    if task_id:
        return _find(_state["tasks"], task_id)
    for t in _state["tasks"]:
        if t["status"] == "pending":
            return t
    raise HTTPException(404, "no task is waiting for approval")


@app.post("/api/tasks/approve")
@app.post("/api/tasks/{task_id}/approve")
def approve_task(task_id: Optional[str] = None) -> dict:
    with lock:
        task = _pending_or(task_id)
        if task["status"] != "pending":
            raise HTTPException(409, f"task is {task['status']}")
        _queue(task)
        _save(_state)
        return task


@app.post("/api/tasks/cancel")
@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: Optional[str] = None) -> dict:
    with lock:
        task = _pending_or(task_id)
        if task["status"] in ("done", "failed", "cancelled"):
            return task
        was_running = task["status"] == "running"
        task.update(status="cancelled", result="Cancelled.", finished=_now())
        _save(_state)
    if was_running:
        worker.restart()  # the only way to stop a running agent loop
    return task


@app.delete("/api/tasks/finished")
def clear_finished() -> dict:
    with lock:
        _state["tasks"] = [t for t in _state["tasks"]
                           if t["status"] not in ("done", "failed", "cancelled")]
        _save(_state)
        return {"ok": True}


# =========================================================================== to-dos, events, notes, timers


class TodoIn(BaseModel):
    title: str
    due: str = ""  # YYYY-MM-DD or ""


class TodoPatch(BaseModel):
    title: Optional[str] = None
    done: Optional[bool] = None
    due: Optional[str] = None


@app.post("/api/todos")
def add_todo(body: TodoIn) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "empty title")
    with lock:
        todo = {"id": _new_id(), "title": body.title.strip(), "due": body.due,
                "done": False, "created": _now()}
        _state["todos"].append(todo)
        _save(_state)
        return todo


@app.patch("/api/todos/{todo_id}")
def update_todo(todo_id: str, body: TodoPatch) -> dict:
    with lock:
        todo = _find(_state["todos"], todo_id)
        todo.update({k: v for k, v in body.model_dump().items() if v is not None})
        _save(_state)
        return todo


@app.delete("/api/todos/{todo_id}")
def delete_todo(todo_id: str) -> dict:
    with lock:
        _state["todos"] = [t for t in _state["todos"] if t["id"] != todo_id]
        _save(_state)
        return {"ok": True}


class EventIn(BaseModel):
    title: str
    date: str  # YYYY-MM-DD
    time: str = ""  # HH:MM or ""


@app.post("/api/events")
def add_event(body: EventIn) -> dict:
    try:
        datetime.strptime(body.date, "%Y-%m-%d")
        if body.time:
            datetime.strptime(body.time, "%H:%M")
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD and time HH:MM")
    with lock:
        event = {"id": _new_id(), "title": body.title.strip(),
                 "date": body.date, "time": body.time, "created": _now()}
        _state["events"].append(event)
        _state["events"].sort(key=lambda e: (e["date"], e["time"] or "99:99"))
        _save(_state)
        return event


@app.delete("/api/events/{event_id}")
def delete_event(event_id: str) -> dict:
    with lock:
        _state["events"] = [e for e in _state["events"] if e["id"] != event_id]
        _save(_state)
        return {"ok": True}


class NoteIn(BaseModel):
    text: str


@app.post("/api/notes")
def add_note(body: NoteIn) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "empty note")
    with lock:
        note = {"id": _new_id(), "text": body.text.strip(), "created": _now()}
        _state["notes"].insert(0, note)
        _save(_state)
        return note


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: str) -> dict:
    with lock:
        _state["notes"] = [n for n in _state["notes"] if n["id"] != note_id]
        _save(_state)
        return {"ok": True}


class TimerIn(BaseModel):
    seconds: int
    label: str = ""


@app.post("/api/timers")
def add_timer(body: TimerIn) -> dict:
    if not 1 <= body.seconds <= 24 * 3600:
        raise HTTPException(400, "timer must be between 1 second and 24 hours")
    with lock:
        ends = datetime.now() + timedelta(seconds=body.seconds)
        timer = {"id": _new_id(), "label": body.label.strip() or "Timer", "seconds": body.seconds,
                 "ends": ends.isoformat(timespec="seconds"), "created": _now()}
        _state["timers"].append(timer)
        _state["timers"].sort(key=lambda t: t["ends"])
        _save(_state)
        return timer


@app.delete("/api/timers/{timer_id}")
def delete_timer(timer_id: str) -> dict:
    with lock:
        _state["timers"] = [t for t in _state["timers"] if t["id"] != timer_id]
        _save(_state)
        return {"ok": True}


class SettingsIn(BaseModel):
    auto_approve: bool


@app.put("/api/settings")
def set_settings(body: SettingsIn) -> dict:
    with lock:
        _state["settings"]["auto_approve"] = body.auto_approve
        _save(_state)
        return _state["settings"]


@app.get("/api/state")
def get_state() -> dict:
    with lock:
        state = json.loads(json.dumps(_state))
    state["worker_ready"] = worker.ready.is_set()
    return state


# =========================================================================== system stats


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_byte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


_k32 = ctypes.windll.kernel32
_u32 = ctypes.windll.user32
_k32.GetTickCount64.restype = ctypes.c_ulonglong
_cpu_prev: list[int] = []
_health_cache: dict[str, Any] = {"t": 0.0}


def _cpu_percent() -> float:
    idle, kern, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
    vals = [(f.dwHighDateTime << 32) | f.dwLowDateTime for f in (idle, kern, user)]
    global _cpu_prev
    prev, _cpu_prev = _cpu_prev, vals
    if not prev:
        return 0.0
    d_idle, d_kern, d_user = (a - b for a, b in zip(vals, prev))
    total = d_kern + d_user  # kernel time includes idle time
    return round(100.0 * (total - d_idle) / total, 1) if total else 0.0


def _default_model() -> str:
    try:
        cfg = tomllib.loads((AGENT_HOME / "config.toml").read_text(encoding="utf-8"))
        return cfg.get("intelligence", {}).get("default_model", "")
    except (OSError, ValueError):
        return ""


def _ollama_up() -> bool:
    if time.time() - _health_cache["t"] > 10:
        try:
            ok = httpx.get(f"{OLLAMA}/api/tags", timeout=2).status_code == 200
        except httpx.HTTPError:
            ok = False
        _health_cache.update(t=time.time(), ollama=ok)
    return _health_cache["ollama"]


def _memory() -> _MemStatus:
    mem = _MemStatus()
    mem.dwLength = ctypes.sizeof(_MemStatus)
    _k32.GlobalMemoryStatusEx(ctypes.byref(mem))
    return mem


def _disks() -> list[dict]:
    disks = []
    for letter in ("C", "D"):
        try:
            u = shutil.disk_usage(f"{letter}:\\")
            disks.append({"name": f"{letter}:", "total": u.total, "free": u.free})
        except OSError:
            pass
    return disks


def _battery() -> Optional[dict]:
    pw = _PowerStatus()
    _k32.GetSystemPowerStatus(ctypes.byref(pw))
    if pw.BatteryLifePercent == 255:
        return None
    return {"percent": pw.BatteryLifePercent, "charging": pw.ACLineStatus == 1}


@app.get("/api/system")
def system() -> dict:
    mem = _memory()
    return {
        "cpu": _cpu_percent(),
        "ram": {"total": mem.ullTotalPhys, "free": mem.ullAvailPhys, "load": mem.dwMemoryLoad},
        "disks": _disks(),
        "battery": _battery(),
        "uptime_s": _k32.GetTickCount64() // 1000,
        "ollama": _ollama_up(),
        "model": _default_model(),
        "worker_ready": worker.ready.is_set(),
    }


def _top_processes(n: int = 5) -> list[tuple[str, int]]:
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                         creationflags=NO_WINDOW, timeout=10).stdout
    totals: dict[str, int] = {}
    for row in out.splitlines():
        parts = [p.strip('"') for p in row.split('","')]
        if len(parts) >= 5:
            kb = int(re.sub(r"[^\d]", "", parts[4]) or 0)
            totals[parts[0]] = totals.get(parts[0], 0) + kb
    return sorted(totals.items(), key=lambda kv: -kv[1])[:n]


def _system_summary() -> str:
    mem, bat = _memory(), _battery()
    gb = 1024 ** 3
    lines = [f"CPU: {_cpu_percent()}% (instant sample)",
             f"RAM: {mem.dwMemoryLoad}% used, {mem.ullAvailPhys / gb:.1f} GB free of {mem.ullTotalPhys / gb:.1f} GB"]
    lines += [f"Drive {d['name']} {d['free'] / gb:.1f} GB free of {d['total'] / gb:.0f} GB" for d in _disks()]
    if bat:
        lines.append(f"Battery: {bat['percent']}%{' (charging)' if bat['charging'] else ''}")
    up = _k32.GetTickCount64() // 1000
    lines.append(f"Uptime: {up // 3600}h {up // 60 % 60}m")
    lines.append("Top memory users: " + ", ".join(f"{name} {kb / 1024:.0f} MB" for name, kb in _top_processes()))
    return "\n".join(lines)


# =========================================================================== instant PC actions

SITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com", "gmail": "https://mail.google.com",
    "facebook": "https://www.facebook.com", "messenger": "https://www.messenger.com",
    "whatsapp": "https://web.whatsapp.com", "github": "https://github.com", "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai", "linkedin": "https://www.linkedin.com", "netflix": "https://www.netflix.com",
    "instagram": "https://www.instagram.com", "x": "https://x.com", "twitter": "https://x.com",
    "maps": "https://maps.google.com", "google maps": "https://maps.google.com", "drive": "https://drive.google.com",
    "calendar": "https://calendar.google.com", "elevenlabs": "https://elevenlabs.io/app", "ollama": "https://ollama.com",
    "tryhackme": "https://tryhackme.com", "hackthebox": "https://www.hackthebox.com", "prothom alo": "https://www.prothomalo.com",
}

_HOME = Path.home()
APPS = {  # spoken name -> what to start (whitelist: no shells, no installers)
    "notepad": "notepad.exe", "calculator": "calc.exe", "paint": "mspaint.exe", "task manager": "taskmgr.exe",
    "file explorer": "explorer.exe", "explorer": "explorer.exe", "settings": "ms-settings:",
    "camera": "microsoft.windows.camera:", "clock": "ms-clock:", "edge": "msedge.exe", "chrome": "chrome.exe",
    "vs code": "code", "vscode": "code", "visual studio code": "code", "spotify": "spotify:",
    "word": "winword.exe", "excel": "excel.exe", "powerpoint": "powerpnt.exe", "snipping tool": "ms-screenclip:",
    "downloads": str(_HOME / "Downloads"), "documents": str(_HOME / "Documents"),
    "desktop": str(_HOME / "OneDrive" / "Desktop") if (_HOME / "OneDrive" / "Desktop").exists() else str(_HOME / "Desktop"),
    "pictures": str(_HOME / "Pictures"), "music": str(_HOME / "Music"), "videos": str(_HOME / "Videos"),
    "jarvis folder": str(ROOT), "cyber field": str(ROOT.parent),
}

VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF}


def _press(*keys: int) -> None:
    for k in keys:
        _u32.keybd_event(k, 0, 0, 0)
    for k in reversed(keys):
        _u32.keybd_event(k, 0, 2, 0)  # KEYEVENTF_KEYUP


def _open_website(target: str) -> str:
    t = target.strip()
    key = quick.canonical(t, _norm).removesuffix(" com")
    if key in SITES:
        url = SITES[key]
    elif re.match(r"^(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?$", t):
        url = t if t.startswith("http") else "https://" + t
    else:
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(t)
    os.startfile(url)
    return f"Opened {url} in the browser."


_start_apps: dict[str, str] = {}  # Start-menu name (normalized) -> AppID, for every installed app
_start_apps_ready = threading.Event()


def _load_start_apps() -> None:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", creationflags=NO_WINDOW, timeout=30).stdout
        apps = json.loads(out or "[]")
        for a in apps if isinstance(apps, list) else [apps]:
            name = _norm(a.get("Name", ""))
            if name and a.get("AppID") and not re.search(r"\b(uninstall|readme|help|documentation)\b", name):
                _start_apps.setdefault(name, a["AppID"])
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    _start_apps_ready.set()


def _find_start_app(key: str) -> Optional[tuple[str, str]]:
    """Installed app whose Start-menu name matches the spoken one: (name, AppID)."""
    _start_apps_ready.wait(5)
    if not key:
        return None
    if key in _start_apps:
        return key, _start_apps[key]
    words = key.split()
    hits = [(n, i) for n, i in _start_apps.items() if all(w in n.split() for w in words)]
    return min(hits, key=lambda h: len(h[0])) if hits else None


def _open_app(name: str) -> str:
    key = quick.canonical(name, _norm)
    if not key:
        return "Error: which app should I open?"
    target = APPS.get(key)
    if not target and (app := _find_start_app(key)):
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app[1]}"], creationflags=NO_WINDOW)
        return f"Opened {app[0]}."
    target = target or next((v for k, v in APPS.items() if len(key) > 2 and (k in key or key in k)), None)
    if not target:
        return f"\"{name}\" is not installed or not in my quick-open list. Use ask_jarvis to find it."
    exe = shutil.which(target) if not (":" in target or Path(target).exists()) else None
    os.startfile(exe or target)
    return f"Opened {name}."


# --------------------------------------------------------------------------- weather (open-meteo, free, no key)

BD_CITIES = {quick.nfc(k): v for k, v in {
    "ঢাকা": "Dhaka", "সিলেট": "Sylhet", "চট্টগ্রাম": "Chittagong", "চিটাগাং": "Chittagong", "রাজশাহী": "Rajshahi",
    "খুলনা": "Khulna", "বরিশাল": "Barisal", "রংপুর": "Rangpur", "ময়মনসিংহ": "Mymensingh", "কুমিল্লা": "Comilla",
    "কক্সবাজার": "Cox's Bazar", "কক্স বাজার": "Cox's Bazar", "গাজীপুর": "Gazipur", "নারায়ণগঞ্জ": "Narayanganj",
    "বগুড়া": "Bogra", "যশোর": "Jessore", "দিনাজপুর": "Dinajpur", "ফেনী": "Feni", "নোয়াখালী": "Noakhali",
    "টাঙ্গাইল": "Tangail", "সাভার": "Savar", "পাবনা": "Pabna", "কুষ্টিয়া": "Kushtia", "ফরিদপুর": "Faridpur",
    "সুনামগঞ্জ": "Sunamganj", "মৌলভীবাজার": "Moulvibazar", "শ্রীমঙ্গল": "Sreemangal", "রাঙামাটি": "Rangamati",
    "বান্দরবান": "Bandarban", "কলকাতা": "Kolkata", "দিল্লি": "Delhi", "লন্ডন": "London", "দুবাই": "Dubai",
    "নিউ ইয়র্ক": "New York", "টোকিও": "Tokyo", "সিঙ্গাপুর": "Singapore", "কাঠমান্ডু": "Kathmandu",
}.items()}
WMO = {0: ("Clear sky", "পরিষ্কার আকাশ"), 1: ("Mainly clear", "প্রায় পরিষ্কার আকাশ"), 2: ("Partly cloudy", "আংশিক মেঘলা"),
       3: ("Overcast", "মেঘলা"), 45: ("Fog", "কুয়াশা"), 48: ("Fog", "কুয়াশা"), 51: ("Drizzle", "গুঁড়ি গুঁড়ি বৃষ্টি"),
       53: ("Drizzle", "গুঁড়ি গুঁড়ি বৃষ্টি"), 55: ("Drizzle", "গুঁড়ি গুঁড়ি বৃষ্টি"), 61: ("Light rain", "হালকা বৃষ্টি"),
       63: ("Rain", "বৃষ্টি"), 65: ("Heavy rain", "ভারী বৃষ্টি"), 80: ("Rain showers", "থেমে থেমে বৃষ্টি"),
       81: ("Rain showers", "থেমে থেমে বৃষ্টি"), 82: ("Heavy showers", "ভারী বর্ষণ"), 95: ("Thunderstorm", "বজ্রঝড়"),
       96: ("Thunderstorm", "বজ্রঝড়"), 99: ("Thunderstorm", "বজ্রঝড়")}
CITY_BN = {v: k for k, v in reversed(list(BD_CITIES.items()))}  # "Sylhet" -> "সিলেট"
_geo_cache: dict[str, Optional[dict]] = {}
_wx_cache: dict[tuple, tuple[float, dict]] = {}


def _city_names(city: str) -> list[str]:
    """Spellings to try for a spoken place name ("সিলেটের", "ঢাকার", "sylheter")."""
    c = quick.nfc(city.strip()).strip("-")
    for suf in ("", "-এর", "এর", "ের", "র", "-এ", "এ", "ে", "তে"):
        base = c[: len(c) - len(suf)] if suf and c.endswith(suf) else (c if not suf else "")
        if base in BD_CITIES:
            return [BD_CITIES[base]]
    names = [c]
    if re.search(r"[a-z](er|e)$", c, re.I):
        names.append(re.sub(r"(er|e)$", "", c, flags=re.I))
    return names


def _geocode(city: str) -> Optional[dict]:
    for name in _city_names(city):
        if name.lower() not in _geo_cache:
            try:
                r = httpx.get("https://geocoding-api.open-meteo.com/v1/search",
                              params={"name": name, "count": 1, "language": "en"}, timeout=8)
                res = (r.json().get("results") or [None])[0]
            except (httpx.HTTPError, ValueError):
                return None
            _geo_cache[name.lower()] = res and {"name": res["name"], "lat": res["latitude"], "lon": res["longitude"],
                                                "country": res.get("country", "")}
        if _geo_cache[name.lower()]:
            return _geo_cache[name.lower()]
    return None


def _weather_city() -> dict:
    with lock:
        return dict(_state["settings"].get("city") or {"name": "Dhaka", "lat": 23.81, "lon": 90.41})


def _weather(city: str = "", bn: bool = False) -> str:
    place = _geocode(city) if city.strip() else _weather_city()
    if not place:
        return f"No place called \"{city}\" found."
    key = (place["lat"], place["lon"])
    if key not in _wx_cache or time.time() - _wx_cache[key][0] > 600:
        r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=10, params={
            "latitude": place["lat"], "longitude": place["lon"], "timezone": "auto", "forecast_days": 1,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
        r.raise_for_status()
        _wx_cache[key] = (time.time(), r.json())
    w = _wx_cache[key][1]
    c, d = w["current"], w["daily"]
    desc_en, desc_bn = WMO.get(c["weather_code"], ("Mixed", "মিশ্র আবহাওয়া"))
    t, feels, hum = round(c["temperature_2m"]), round(c["apparent_temperature"]), c["relative_humidity_2m"]
    hi, lo, rain = round(d["temperature_2m_max"][0]), round(d["temperature_2m_min"][0]), d["precipitation_probability_max"][0] or 0
    if bn:
        n = quick.bn_num
        city_bn = CITY_BN.get(place["name"], place["name"])
        of = city_bn + ("র" if re.search(r"[া-ৌ]$", city_bn) else "-এর")  # ঢাকার, সিলেট-এর
        return (f"{of} আবহাওয়া: এখন {desc_bn}, তাপমাত্রা {n(t)} ডিগ্রি, অনুভূত হচ্ছে {n(feels)} ডিগ্রি। আর্দ্রতা {n(hum)}%। "
                f"আজ সর্বোচ্চ {n(hi)}, সর্বনিম্ন {n(lo)} ডিগ্রি, বৃষ্টির সম্ভাবনা {n(rain)}%।")
    return (f"Weather in {place['name']}: {desc_en}, {t}°C (feels {feels}°C), humidity {hum}%. "
            f"Today high {hi}°C, low {lo}°C, rain chance {rain}%.")


def _set_weather_city(city: str) -> str:
    place = _geocode(city)
    if not place:
        return f"No place called \"{city}\" found."
    with lock:
        _state["settings"]["city"] = place
        _save(_state)
    return f"Weather widget now shows {place['name']}."


def _news(topic: str = "", bn: bool = True, n: int = 5) -> list[tuple[str, str]]:
    """Top headlines from Google News RSS (free, no key): [(title, source)]."""
    import xml.etree.ElementTree as ET

    loc = "hl=bn&gl=BD&ceid=BD:bn" if bn else "hl=en-BD&gl=BD&ceid=BD:en"
    topic = topic.strip()
    google = (f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(topic)}&{loc}" if topic
              else f"https://news.google.com/rss?{loc}")
    # Google's Bangla edition is mostly West Bengal news, so Bangla top news
    # comes from Bangladeshi feeds first.
    feeds = [google] if topic or not bn else [
        ("https://www.prothomalo.com/feed/", "প্রথম আলো"), ("https://www.bbc.com/bengali/index.xml", "বিবিসি বাংলা"), google]
    for feed in feeds:
        url, default_source = feed if isinstance(feed, tuple) else (feed, "")
        try:
            r = httpx.get(url, timeout=10, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except (httpx.HTTPError, ET.ParseError):
            continue
        items = []
        for it in root.iter("item"):
            title = " ".join((it.findtext("title") or "").split())
            source = (it.findtext("source") or default_source).strip()
            if source and title.endswith(" - " + source):
                title = title[: -len(source) - 3]
            if title:
                items.append((title, source))
            if len(items) >= n:
                break
        if items:
            return items
    return []


def _news_text(topic: str = "", bn: bool = True) -> str:
    items = _news(topic, bn)
    if not items:
        return "No news found." if not topic else f"No news found about {topic}."
    return "\n".join(f"{i}. {t} ({s})" for i, (t, s) in enumerate(items, 1))


def _media(action: str, steps: int = 5) -> str:
    action = action.strip().lower().replace(" ", "_").replace("-", "_")
    action = {"pause": "play_pause", "play": "play_pause", "resume": "play_pause", "skip": "next",
              "prev": "previous", "back": "previous", "louder": "volume_up", "up": "volume_up",
              "quieter": "volume_down", "down": "volume_down", "unmute": "mute"}.get(action, action)
    if action not in VK:
        return f"Unknown media action. Use one of: {', '.join(VK)}."
    for _ in range(max(1, min(25, steps)) if action.startswith("volume") else 1):
        _press(VK[action])
    return f"Done: {action.replace('_', ' ')}."


# =========================================================================== free-voice brain
# The browser does speech-to-text and text-to-speech; this endpoint thinks with
# the Ollama model from config.toml and calls the HUD tools directly. The
# ElevenLabs agent calls the same tools through /api/tool.

MAX_TOOL_ROUNDS = 5


def _norm(s: str) -> str:
    # \w drops Bangla vowel signs and hasanta (combining marks), so keep the
    # whole Bengali block explicitly; zero-width joiners are dropped.
    s = quick.nfc(str(s or "")).lower().replace("‌", "").replace("‍", "")
    return " ".join(re.sub(r"[^\wঀ-৿ ]|।", " ", s).split())


def _match(items: list, title: str, field: str = "title") -> Optional[dict]:
    q, best, best_score = _norm(title), None, 0
    if not q:
        return None
    for it in items:
        t = _norm(it[field])
        score = 100 if t == q else 50 if (q in t or t in q) else len(set(q.split()) & set(t.split()))
        if score > best_score:
            best, best_score = it, score
    return best


def _agenda() -> str:
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    with lock:
        evs = [e for e in _state["events"] if e["date"] >= today][:15]
        todos = [t for t in _state["todos"] if not t["done"]]
        notes = _state["notes"][:5]
        timers = [t for t in _state["timers"] if t["ends"] > now.isoformat()]
    lines = [f"Current date/time (Asia/Dhaka): {now:%A %Y-%m-%d %H:%M}.", "Upcoming calendar:"]
    lines += [f"- {e['date']}{' ' + e['time'] if e['time'] else ''}: {e['title']}" for e in evs] or ["- nothing scheduled"]
    lines += ["Open to-dos:"] + ([f"- {t['title']}{' (due ' + t['due'] + ')' if t['due'] else ''}" for t in todos] or ["- none"])
    if timers:
        lines += ["Running timers:"] + [f"- {t['label']} ends at {t['ends'][11:16]}" for t in timers]
    if notes:
        lines += ["Latest notes:"] + [f"- {n['text'][:120]}" for n in notes]
    return "\n".join(lines)


def _tool_ask_jarvis(a: dict, source: str, made_here: set[str]) -> str:
    with lock:
        waiting = next((t for t in _state["tasks"] if t["status"] == "pending"), None)
    if waiting:
        return (f"Task {waiting['id']} (\"{waiting['command']}\") is already waiting for approval. "
                "Do not create another. If the user just agreed to it, call approve_task; "
                "if they want something else, call cancel_task first.")
    t = create_task(TaskIn(command=a.get("command", ""), source=source))
    made_here.add(t["id"])
    if t["status"] == "pending":
        return (f"Approval needed (task {t['id']}). Read the command back in one short sentence and ask "
                "the user to confirm. If they agree, call approve_task; if not, call cancel_task.")
    return (f"Jarvis started the task (task {t['id']}). Tell the user briefly you're on it. The result "
            "will arrive later in a message starting with [Jarvis result].")


def _tool_approve(a: dict, made_here: set[str]) -> str:
    with lock:
        target = _pending_or(a.get("task_id") or None)
    if target["id"] in made_here:
        return ("Refused: you cannot approve a task in the same turn you created it. Ask the user "
                "to confirm and wait for their reply.")
    return f"Approved: \"{approve_task(target['id'])['command']}\". Result will arrive later as [Jarvis result]."


def _tool_complete_todo(a: dict) -> str:
    with lock:
        t = _match([x for x in _state["todos"] if not x["done"]], a.get("title", ""))
    if not t:
        return f"No open to-do matches \"{a.get('title')}\"."
    update_todo(t["id"], TodoPatch(done=True))
    return f"Marked \"{t['title']}\" as done."


def _tool_delete_todo(a: dict) -> str:
    with lock:
        t = _match(_state["todos"], a.get("title", ""))
    if not t:
        return f"No to-do matches \"{a.get('title')}\"."
    delete_todo(t["id"])
    return f"Deleted to-do \"{t['title']}\"."


def _tool_delete_event(a: dict) -> str:
    with lock:
        pool = [e for e in _state["events"] if not a.get("date") or e["date"] == a["date"]]
        e = _match(pool, a.get("title", ""))
    if not e:
        return f"No event matches \"{a.get('title')}\"."
    delete_event(e["id"])
    return f"Deleted \"{e['title']}\" on {e['date']}."


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _tool_set_timer(a: dict) -> str:
    seconds = int(_num(a.get("hours")) * 3600 + _num(a.get("minutes")) * 60 + _num(a.get("seconds")))
    t = add_timer(TimerIn(seconds=seconds, label=a.get("label", "") or ""))
    return f"Timer \"{t['label']}\" set for {seconds // 60} min {seconds % 60} s, ends at {t['ends'][11:16]}."


def _tool_cancel_timer(a: dict) -> str:
    with lock:
        timers = list(_state["timers"])
    if not timers:
        return "No timers are running."
    t = _match(timers, a.get("label", ""), "label") if a.get("label") else timers[0]
    if not t:
        return f"No timer matches \"{a.get('label')}\"."
    delete_timer(t["id"])
    return f"Cancelled timer \"{t['label']}\"."


def _tool_delete_note(a: dict) -> str:
    with lock:
        n = _match(_state["notes"], a.get("text", ""), "text")
    if not n:
        return f"No note matches \"{a.get('text')}\"."
    delete_note(n["id"])
    return f"Deleted the note \"{n['text'][:60]}\"."


def _run_tool(name: str, a: dict, source: str, made_here: set[str]) -> str:
    """Run one HUD tool. ``made_here`` holds tasks created during this request:
    the model must not approve those itself, only after the user's next reply."""
    try:
        match name:
            case "ask_jarvis":
                return _tool_ask_jarvis(a, source, made_here)
            case "approve_task":
                return _tool_approve(a, made_here)
            case "cancel_task":
                return f"Cancelled: \"{cancel_task(a.get('task_id') or None)['command']}\"."
            case "add_todo":
                t = add_todo(TodoIn(title=a.get("title", ""), due=a.get("due", "") or ""))
                return f"Added to-do \"{t['title']}\"{' due ' + t['due'] if t['due'] else ''}."
            case "complete_todo":
                return _tool_complete_todo(a)
            case "delete_todo":
                return _tool_delete_todo(a)
            case "add_event":
                e = add_event(EventIn(title=a.get("title", ""), date=a.get("date", ""), time=a.get("time", "") or ""))
                return f"Added \"{e['title']}\" on {e['date']}{' at ' + e['time'] if e['time'] else ''}."
            case "delete_event":
                return _tool_delete_event(a)
            case "get_agenda":
                return _agenda()
            case "add_note":
                return f"Saved note: \"{add_note(NoteIn(text=a.get('text', '')))['text'][:80]}\"."
            case "delete_note":
                return _tool_delete_note(a)
            case "set_timer":
                return _tool_set_timer(a)
            case "cancel_timer":
                return _tool_cancel_timer(a)
            case "get_system_info":
                return _system_summary()
            case "get_weather":
                return _weather(a.get("city", "") or "", bn=(a.get("language") or "").lower().startswith("bn"))
            case "set_weather_city":
                return _set_weather_city(a.get("city", "") or "")
            case "get_news":
                lang = (a.get("language") or "").lower()
                return _news_text(a.get("topic", "") or "", bn=not lang.startswith("en"))
            case "open_website":
                return _open_website(a.get("target", ""))
            case "play_youtube":
                url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(a.get("query", ""))
                os.startfile(url)
                return f"Opened YouTube results for \"{a.get('query')}\". Tell the user to click the video they want."
            case "open_app":
                return _open_app(a.get("name", ""))
            case "media_control":
                return _media(a.get("action", ""), int(_num(a.get("steps")) or 5))
            case "lock_pc":
                _u32.LockWorkStation()
                return "PC locked."
            case "take_screenshot":
                _press(0x5B, 0x2C)  # Win + PrintScreen -> Pictures\Screenshots
                return "Screenshot saved to Pictures > Screenshots."
        return f"Unknown tool {name}."
    except HTTPException as exc:
        return f"Error: {exc.detail}"
    except Exception as exc:
        return f"Error: {exc}"


def _fn(name: str, desc: str, props: dict, required: list) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
        "required": required}}}


BRAIN_TOOLS = [
    _fn("get_system_info", "INSTANT: CPU, RAM, free space on C: and D:, battery, uptime and the top memory-using "
        "programs. Use this instead of ask_jarvis for any question about PC status or disk space.", {}, []),
    _fn("get_news", "INSTANT: latest news headlines (Google News, Bangladesh). Use for any request to read, "
        "tell or check the news, with or without a topic.", {
            "topic": "Optional topic, e.g. 'cyber security', 'cricket', 'technology'. Empty = top news.",
            "language": "bn for Bangla headlines (default), en for English."}, []),
    _fn("get_weather", "INSTANT: current weather and today's forecast for any city (default: the user's city).", {
            "city": "Optional city name in English, e.g. 'Sylhet', 'Chittagong', 'London'.",
            "language": "bn for a Bangla answer, en for English."}, []),
    _fn("set_weather_city", "Change which city the HUD weather widget shows.",
        {"city": "City name in English."}, ["city"]),
    _fn("open_website", "INSTANT: open a website or a Google search in the browser.",
        {"target": "Site name (youtube, gmail, github...), a URL, or search words."}, ["target"]),
    _fn("play_youtube", "INSTANT: search YouTube for a song or video and open the results.",
        {"query": "What to play."}, ["query"]),
    _fn("open_app", "INSTANT: open any installed app by its name (WhatsApp, Telegram, Discord, Chrome, VS Code, "
        "Word, notepad, calculator, settings, task manager...) or a folder (downloads, documents, desktop, "
        "pictures, music, videos, jarvis folder).", {"name": "App or folder name in English."}, ["name"]),
    _fn("media_control", "INSTANT: control music/video and volume.", {
        "action": "play_pause, next, previous, volume_up, volume_down or mute.",
        "steps": "Optional volume steps (each about 2%), default 5."}, ["action"]),
    _fn("lock_pc", "INSTANT: lock the computer screen.", {}, []),
    _fn("take_screenshot", "INSTANT: take a screenshot of the whole screen.", {}, []),
    _fn("set_timer", "Start a countdown timer/alarm on the HUD.", {
        "hours": "Optional number.", "minutes": "Optional number.", "seconds": "Optional number.",
        "label": "Optional name, e.g. 'tea'."}, []),
    _fn("cancel_timer", "Cancel a running timer.", {"label": "Optional timer name."}, []),
    _fn("add_note", "Save a quick note on the HUD.", {"text": "The note, in the user's words."}, ["text"]),
    _fn("delete_note", "Delete a note (closest match).", {"text": "Words from the note."}, ["text"]),
    _fn("add_todo", "Add a to-do.", {"title": "The to-do.", "due": "Optional due date YYYY-MM-DD."}, ["title"]),
    _fn("complete_todo", "Mark a to-do as done (closest title).", {"title": "The to-do."}, ["title"]),
    _fn("delete_todo", "Delete a to-do (closest title).", {"title": "The to-do."}, ["title"]),
    _fn("add_event", "Add a calendar event.", {"title": "Event title.", "date": "YYYY-MM-DD.",
        "time": "Optional HH:MM, 24-hour."}, ["title", "date"]),
    _fn("delete_event", "Delete a calendar event (closest title).", {"title": "Event title.",
        "date": "Optional YYYY-MM-DD."}, ["title"]),
    _fn("get_agenda", "Current date/time, calendar, open to-dos, timers and latest notes.", {}, []),
    _fn("ask_jarvis", "SLOW (seconds to minutes): hand a task to Jarvis, the full agent on the user's PC, for "
        "things the instant tools can't do: working with files and folders, running commands, installing "
        "or checking software, web research, reading or writing documents.",
        {"command": "One clear, complete command in English."}, ["command"]),
    _fn("approve_task", "Run the Jarvis task waiting for approval, after the user agreed.", {"task_id": "Optional."}, []),
    _fn("cancel_task", "Cancel a Jarvis task when the user says no or stop.", {"task_id": "Optional."}, []),
]

BRAIN_PROMPT = """You are Jarvis, the user's personal AI assistant, talking by voice through their HUD dashboard. The user is in Dhaka, Bangladesh. If the user writes in Bangla or Banglish, reply only in Bangla script (বাংলা); if they write in English, reply only in English. Never repeat the same sentence in two languages. Your reply is read aloud, so keep it to one to three short sentences, with no markdown, brackets, lists or emoji.

Prefer the INSTANT tools (system info, weather, news, open website/app, YouTube, media and volume, lock, screenshot, timers, notes, to-dos, calendar): they finish immediately. When reading news, read up to five headlines, one short line each. Speech recognition often writes "পড়ে" (read) as "পরে" (later): "খবর পরে দিন" means read the news now. Never use ask_jarvis for news, weather, opening apps or anything an instant tool does; use it only for work they can't do. If ask_jarvis says approval is needed, read the command back briefly and ask the user to confirm, then stop and wait. Only after the user agrees in their next message (yes, haan, ha, koro, thik ache, okay) call approve_task; if they decline, call cancel_task. You do not know a task's result until a message starting with [Jarvis result] arrives: never guess a result before that. Messages that start with [Jarvis result], [Reminder] or [Timer] come from the HUD: tell the user about them in one or two sentences.
Work out relative dates ("tomorrow", "kal", "porshu", "next Friday") from the current date below. After changing something, confirm in one short sentence. For plain questions and conversation, answer yourself without tools. When the user asks how to do something, give the best way first, then offer to have Jarvis do it. Never invent results."""

_YES = re.compile(r"^(yes|yeah|yep|yup|ok|okay|sure|go|go ahead|do it|run it|haa?n?|hya|hae|ji|jee|"
                  r"koro|kore dao|thik ache|thikache|accha|হ্যাঁ|হা|হুম|জি|করো|করে দাও|ঠিক আছে|আচ্ছা)"
                  r"( (please|koro|করো|ok|okay|go ahead|do it|thik ache|ঠিক আছে))*$")
_NO = re.compile(r"^(no|nope|nah|cancel|stop|don t|dont|na|naa|nah thak|thak|bad dao|baad dao|lagbe na|"
                 r"না|থাক|বাদ দাও|লাগবে না|বাতিল)( (please|thak|থাক|cancel|it))*$")


def _pending_reply(text: str) -> Optional[dict]:
    """A bare yes/no right after Jarvis asked for approval is answered here,
    without the model, so approval can't be skipped or misread."""
    words = _norm(text)
    if not (_YES.match(words) or _NO.match(words)):
        return None
    with lock:
        task = next((t for t in _state["tasks"] if t["status"] == "pending"), None)
    if not task:
        return None
    if _YES.match(words):
        approve_task(task["id"])
        bn = re.search(r"[ঀ-৿]", text) or not re.search(r"\b(yes|yeah|ok|okay|sure|go)\b", words)
        reply = "ঠিক আছে, Jarvis কাজ শুরু করেছে। ফলাফল এলে জানাব।" if bn else \
            "Okay, Jarvis is on it. I'll tell you the result when it's done."
        action = "approve_task"
    else:
        cancel_task(task["id"])
        bn = re.search(r"[ঀ-৿]", text) or not re.search(r"\b(no|cancel|stop|nope)\b", words)
        reply = "ঠিক আছে, কাজটা বাতিল করলাম।" if bn else "Okay, I cancelled that."
        action = "cancel_task"
    return {"reply": reply, "actions": [{"tool": action, "args": {"task_id": task["id"]},
                                         "result": task["command"]}], "model": "rule"}


QUICK_ERRORS_BN = {"No timers are running.": "কোনো টাইমার চলছে না।"}


def _resolve_open(name: str) -> Optional[tuple[str, dict]]:
    """Only open things we recognise exactly; anything vaguer goes to the model.
    An installed app wins over its website (WhatsApp desktop over web.whatsapp)."""
    key = quick.canonical(name, _norm)
    if key in APPS or (key and key in _start_apps) or (len(key) > 3 and _find_start_app(key)):
        return "open_app", {"name": key}
    if key.removesuffix(" com") in SITES:
        return "open_website", {"target": key}
    return None


def _quick_reply(text: str, history: list[dict], source: str) -> Optional[dict]:
    """Answer common commands with rules (~0.1 s) instead of the model."""
    q = quick.match(text, _norm, history)
    if not q:
        return None
    if "reply" in q:
        return {"reply": q["reply"], "actions": [], "client": q.get("client") or {}, "model": "rule"}
    tool, args = q["tool"], q["args"]
    if tool == "open":
        resolved = _resolve_open(args["name"])
        if not resolved:
            return None
        tool, args = resolved
    result = _run_tool(tool, args, source, set())
    if tool == "get_weather" and result.startswith(("No place", "Error")):
        return None  # unknown place name: let the model work out what was meant
    bn = quick.wants_bangla(text)
    reply = quick.confirm(tool, args, result, bn)
    if reply is None:  # the tool already ran, so don't send it to the model again
        reply = QUICK_ERRORS_BN.get(result, result) if bn else result
    return {"reply": reply, "actions": [{"tool": tool, "args": args, "result": result}], "model": "rule"}


class ChatMsg(BaseModel):
    role: str
    content: str


class AssistantIn(BaseModel):
    messages: list[ChatMsg]
    source: str = "voice"  # "typed" commands run without approval
    context: str = ""  # extra live context from the page, e.g. weather


@app.post("/api/assistant")
def assistant(body: AssistantIn) -> dict:
    started = time.time()
    last = body.messages[-1].content if body.messages and body.messages[-1].role == "user" else ""
    if last and (fast := _pending_reply(last) or _quick_reply(
            last, [m.model_dump() for m in body.messages], body.source)):
        fast["ms"] = int((time.time() - started) * 1000)
        return fast
    bn = quick.wants_bangla(last)
    with lock:
        pending = [t for t in _state["tasks"] if t["status"] == "pending"]
    waiting = ("Jarvis tasks waiting for the user's approval:\n"
               + "\n".join(f"- task {t['id']}: {t['command']}" for t in pending)) if pending else ""
    system = f"{BRAIN_PROMPT}\n\n{_agenda()}\n{waiting}\n{body.context}".strip()
    messages: list[dict] = [{"role": "system", "content": system}]
    messages += [m.model_dump() for m in body.messages[-14:] if m.role in ("user", "assistant")]
    actions: list[dict] = []
    made_here: set[str] = set()
    model = _default_model() or "gpt-oss:120b-cloud"
    for _ in range(MAX_TOOL_ROUNDS):
        payload: dict = {"model": model, "messages": messages, "stream": False, "options": {"num_ctx": 8192}}
        if model.startswith("gpt-oss"):
            payload["think"] = "low"  # least reasoning = fastest reply
        # Once a task waits for approval, the only next step is asking the user.
        if not made_here:
            payload["tools"] = BRAIN_TOOLS
        try:
            r = httpx.post(f"{OLLAMA}/api/chat", json=payload, timeout=120)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            detail = exc.response.text[:200] if isinstance(exc, httpx.HTTPStatusError) else str(exc)
            raise HTTPException(502, f"Model error ({model}): {detail}")
        msg = r.json().get("message", {})
        calls = msg.get("tool_calls") or []
        if not calls:
            reply = (msg.get("content") or "").strip()
            if not reply:  # the model went quiet: never leave the user without an answer
                reply = ("ঠিক আছে, হয়ে গেছে।" if actions else "দুঃখিত, বুঝতে পারিনি। আরেকবার বলবেন?") if bn else                     ("Done." if actions else "Sorry, I didn't catch that. Could you say it again?")
            return {"reply": reply, "actions": actions, "model": model, "ms": int((time.time() - started) * 1000)}
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        confirmations: list[Optional[str]] = []
        for c in calls:
            fn = c.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            name = fn.get("name", "")
            result = _run_tool(name, args, body.source, made_here)
            actions.append({"tool": name, "args": args, "result": result})
            messages.append({"role": "tool", "content": result, "tool_name": name})
            confirmations.append(quick.confirm(name, args, result, bn) if name in quick.DIRECT_TOOLS else None)
        # Simple actions confirm themselves: skip the second model round (~2 s).
        if confirmations and all(confirmations):
            return {"reply": " ".join(confirmations), "actions": actions, "model": model,
                    "ms": int((time.time() - started) * 1000)}
    return {"reply": "Sorry, that took too many steps. Please try again more simply.", "actions": actions,
            "model": model, "ms": int((time.time() - started) * 1000)}


class ToolIn(BaseModel):
    name: str
    args: dict = {}
    source: str = "voice"


@app.post("/api/tool")
def run_tool(body: ToolIn) -> dict:
    """Used by the ElevenLabs agent's client tools (the page relays them)."""
    return {"result": _run_tool(body.name, body.args, body.source, set())}


# =========================================================================== voice

TTS_VOICES = {
    ("bn", "male"): "bn-BD-PradeepNeural", ("bn", "female"): "bn-BD-NabanitaNeural",
    ("en", "male"): "en-GB-RyanNeural", ("en", "female"): "en-GB-SoniaNeural",
}


@app.get("/api/tts")
async def tts(text: str, gender: str = "male", rate: int = 0) -> StreamingResponse:
    """Microsoft neural voices via edge-tts (free). Streams MP3 so the browser
    starts playing before the whole sentence is synthesized."""
    lang = "bn" if re.search(r"[ঀ-৿]", text) else "en"
    voice = TTS_VOICES.get((lang, gender), TTS_VOICES[(lang, "male")])
    rate = max(-50, min(60, rate))

    text = text.strip()[:1500]
    if not text:
        raise HTTPException(400, "empty text")
    stream = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%").stream()

    async def next_audio() -> Optional[bytes]:
        async for chunk in stream:
            if chunk["type"] == "audio":
                return chunk["data"]
        return None

    # Wait for the first audio bytes before answering, so a failure (offline,
    # service down) is a clean error the page can fall back from, not a
    # silent empty stream.
    try:
        first = await next_audio()
    except Exception as exc:
        raise HTTPException(502, f"TTS failed: {type(exc).__name__}")
    if not first:
        raise HTTPException(502, "TTS returned no audio")

    async def audio():
        yield first
        try:
            while (data := await next_audio()) is not None:
                yield data
        except Exception:
            return  # the page plays what arrived

    return StreamingResponse(audio(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/voice/token")
def voice_token() -> dict:
    """Short-lived WebRTC token, so the browser never sees the API key."""
    key = os.environ.get("ELEVENLABS_API_KEY") or _user_env("ELEVENLABS_API_KEY")
    if not AGENT_ID:
        return {"agent_id": None, "token": None}
    if not key:
        return {"agent_id": AGENT_ID, "token": None}
    try:
        r = httpx.get("https://api.elevenlabs.io/v1/convai/conversation/token",
                      params={"agent_id": AGENT_ID}, headers={"xi-api-key": key}, timeout=15)
        r.raise_for_status()
        return {"agent_id": AGENT_ID, "token": r.json().get("token")}
    except httpx.HTTPError:
        return {"agent_id": AGENT_ID, "token": None}


# =========================================================================== static

app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    threading.Thread(target=worker.start, daemon=True).start()  # warm Jarvis up front
    threading.Thread(target=_load_start_apps, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
