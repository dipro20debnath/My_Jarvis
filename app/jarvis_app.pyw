"""Jarvis desktop app launcher.

Starts Ollama, the Jarvis API server and the dashboard in the background with
no console windows, then opens the dashboard in its own app window (Edge app
mode). Anything already running is reused. Run with `stop` to shut it down.
Runs under pythonw.exe, so errors are shown in a message box and logged to
my-agent\\jarvis-app.log.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
import traceback
import urllib.request
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "OpenJarvis"
VENV = SRC / ".venv" / "Scripts"
AGENT_HOME = ROOT / "my-agent"
LOG = AGENT_HOME / "jarvis-app.log"
DASHBOARD_LOG = AGENT_HOME / "dashboard.log"
FRONTEND_PID = AGENT_HOME / "dashboard.pid"

DASHBOARD_URL = "http://127.0.0.1:5173"
API_HEALTH = "http://127.0.0.1:8000/health"
OLLAMA_URL = "http://127.0.0.1:11434/api/tags"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
START_TIMEOUT_S = 180

NO_WINDOW = subprocess.CREATE_NO_WINDOW
BACKGROUND = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def log(msg: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def message(text: str, error: bool = False) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "Jarvis", 0x10 if error else 0x40)


def user_env(name: str) -> str:
    """Read a variable saved with SetEnvironmentVariable(..., 'User')."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return ""


def is_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status < 500
    except Exception:
        return False


def build_env() -> dict:
    env = dict(os.environ)
    defaults = {
        "OPENJARVIS_HOME": str(AGENT_HOME),
        "OLLAMA_MODELS": str(ROOT / "ollama-models"),
        # Smaller context = less RAM; the 16384 default runs out of memory here.
        "OLLAMA_CONTEXT_LENGTH": "8192",
        "JARVIS_NUM_CTX": "8192",
        # Keep npm's download cache off the nearly-full C: drive.
        "npm_config_cache": str(ROOT / "_cache" / "npm"),
    }
    for name, value in defaults.items():
        env[name] = env.get(name) or user_env(name) or value
    key = env.get("ELEVENLABS_API_KEY") or user_env("ELEVENLABS_API_KEY")
    if key:
        env["ELEVENLABS_API_KEY"] = key
    extra_path = [str(Path.home() / ".local" / "bin"), str(ROOT / "Ollama"), str(VENV)]
    env["PATH"] = os.pathsep.join(extra_path + [env.get("PATH", "")])
    # Same as `jarvis gui`: browser requests go through Vite's proxy to the API.
    env["VITE_API_URL"] = ""
    env["OPENJARVIS_VITE_PROXY_TARGET"] = "http://127.0.0.1:8000"
    return env


def start_ollama(env: dict) -> None:
    if is_up(OLLAMA_URL):
        return
    log("starting ollama serve")
    subprocess.Popen(
        [str(ROOT / "Ollama" / "ollama.exe"), "serve"],
        env=env, creationflags=BACKGROUND,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def start_server(env: dict) -> None:
    if is_up(API_HEALTH):
        return
    log("starting jarvis server")
    subprocess.run(
        [str(VENV / "jarvis.exe"), "start", "--port", "8000"],
        cwd=SRC, env=env, creationflags=NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
    )


def start_dashboard(env: dict) -> None:
    if is_up(DASHBOARD_URL):
        return
    log("starting dashboard (vite)")
    out = DASHBOARD_LOG.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        ["cmd", "/c", "npm", "run", "dev", "--", "--host", "127.0.0.1",
         "--port", "5173", "--strictPort"],
        cwd=SRC / "frontend", env=env, creationflags=BACKGROUND,
        stdout=out, stderr=subprocess.STDOUT,
    )
    FRONTEND_PID.write_text(str(proc.pid), encoding="ascii")


def wait_until_ready() -> bool:
    deadline = time.time() + START_TIMEOUT_S
    while time.time() < deadline:
        if is_up(DASHBOARD_URL) and is_up(API_HEALTH):
            return True
        time.sleep(2)
    return False


def open_window() -> None:
    if EDGE.exists():
        subprocess.Popen([str(EDGE), f"--app={DASHBOARD_URL}", "--window-size=1280,860"])
    else:
        os.startfile(DASHBOARD_URL)


def stop() -> None:
    env = build_env()
    if FRONTEND_PID.exists():
        pid = FRONTEND_PID.read_text(encoding="ascii").strip()
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                       creationflags=NO_WINDOW, capture_output=True)
        FRONTEND_PID.unlink(missing_ok=True)
    subprocess.run([str(VENV / "jarvis.exe"), "stop"], cwd=SRC, env=env,
                   creationflags=NO_WINDOW, capture_output=True, timeout=60)
    # Ollama keeps running (it uses little RAM when idle and unloads the model
    # by itself after a few minutes).
    log("stopped dashboard and server")
    message("Jarvis stopped.")


def main() -> None:
    AGENT_HOME.mkdir(parents=True, exist_ok=True)
    if "stop" in sys.argv[1:]:
        stop()
        return
    env = build_env()
    start_ollama(env)
    start_server(env)
    start_dashboard(env)
    if not wait_until_ready():
        log("timed out waiting for dashboard/server")
        message(
            "Jarvis took too long to start.\n\n"
            f"Check the logs in:\n{AGENT_HOME}\n(jarvis-app.log, dashboard.log, server.log)",
            error=True,
        )
        return
    log("ready, opening window")
    open_window()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log(traceback.format_exc())
        message("Jarvis could not start:\n\n" + traceback.format_exc(limit=2), error=True)
