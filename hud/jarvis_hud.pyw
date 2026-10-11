"""Jarvis HUD launcher: starts Ollama and the HUD server hidden, then opens the
HUD in its own Edge app window. Run with `stop` to shut the HUD server down.
Errors go to a message box and my-agent\\jarvis-hud.log.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AGENT_HOME = ROOT / "my-agent"
PYTHON = ROOT / "OpenJarvis" / ".venv" / "Scripts" / "python.exe"
PID_FILE = AGENT_HOME / "hud-server.pid"
LOG = AGENT_HOME / "jarvis-hud.log"
URL = "http://127.0.0.1:8765"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
BACKGROUND = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def log(msg: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def message(text: str, error: bool = False) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "Jarvis HUD", 0x10 if error else 0x40)


def is_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status < 500
    except Exception:
        return False


def start() -> None:
    env = dict(os.environ, OLLAMA_MODELS=os.environ.get("OLLAMA_MODELS") or str(ROOT / "ollama-models"),
               OLLAMA_CONTEXT_LENGTH=os.environ.get("OLLAMA_CONTEXT_LENGTH") or "8192")
    if not is_up("http://127.0.0.1:11434/api/tags"):
        log("starting ollama")
        subprocess.Popen([str(ROOT / "Ollama" / "ollama.exe"), "serve"], env=env, creationflags=BACKGROUND,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not is_up(f"{URL}/api/state"):
        log("starting hud server")
        err = (AGENT_HOME / "hud-server.log").open("a", encoding="utf-8")
        proc = subprocess.Popen([str(PYTHON), str(HERE / "server.py")], cwd=HERE, env=env,
                                creationflags=BACKGROUND, stdout=subprocess.DEVNULL, stderr=err)
        PID_FILE.write_text(str(proc.pid), encoding="ascii")
        deadline = time.time() + 40
        while not is_up(f"{URL}/api/state"):
            if time.time() > deadline or proc.poll() is not None:
                log("hud server failed to start")
                message(f"The HUD server did not start.\n\nSee {AGENT_HOME / 'hud-server.log'}", error=True)
                return
            time.sleep(0.5)
    if EDGE.exists():
        subprocess.Popen([str(EDGE), f"--app={URL}", "--window-size=1440,960"])
    else:
        os.startfile(URL)
    log("opened HUD")


def stop() -> None:
    if PID_FILE.exists():
        pid = PID_FILE.read_text(encoding="ascii").strip()
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        PID_FILE.unlink(missing_ok=True)
    log("stopped hud server")
    message("Jarvis HUD stopped.")


if __name__ == "__main__":
    AGENT_HOME.mkdir(parents=True, exist_ok=True)
    try:
        stop() if "stop" in sys.argv[1:] else start()
    except Exception:
        log(traceback.format_exc())
        message("Jarvis HUD could not start:\n\n" + traceback.format_exc(limit=2), error=True)
