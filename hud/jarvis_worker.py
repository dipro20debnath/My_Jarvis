"""Long-lived Jarvis worker for the HUD.

Running `jarvis ask` as a new process costs ~9 s of imports, and every ask
re-probes ~15 inference engines (~6 s, mostly dead localhost ports). This
worker imports OpenJarvis once, caches engine discovery, and then runs each
command through the normal `jarvis ask` CLI path in-process.

Protocol (one JSON object per line):
  stdin:  {"id": "...", "command": "..."}
  stdout: {"ready": true}  once, then {"id": "...", "ok": bool, "content": "..."}
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import time

channel = sys.stdout
sys.stdout = sys.stderr  # stray prints must not corrupt the protocol


def emit(obj: dict) -> None:
    channel.write(json.dumps(obj, ensure_ascii=False) + "\n")
    channel.flush()


from openjarvis.cli import cli  # noqa: E402  (slow import, done once)
from openjarvis.core.config import load_config  # noqa: E402

# `openjarvis.cli.ask` the attribute is the click command; the module is here.
ask_mod = sys.modules["openjarvis.cli.ask"]

_discover = ask_mod.discover_engines
_cache: dict = {"t": 0.0, "v": None}
DISCOVERY_TTL_S = 600


def cached_discover(config):
    if _cache["v"] is None or time.time() - _cache["t"] > DISCOVERY_TTL_S:
        _cache.update(v=_discover(config), t=time.time())
    return _cache["v"]


ask_mod.discover_engines = cached_discover
cached_discover(load_config())  # warm the cache before the first task
emit({"ready": True})

for line in sys.stdin:
    try:
        req = json.loads(line)
    except ValueError:
        continue
    buf = io.StringIO()
    error = ""
    with contextlib.redirect_stdout(buf):
        try:
            cli.main(["--quiet", "ask", "-e", "ollama", "--no-stream", "--json", req["command"]],
                     standalone_mode=False)
        except SystemExit as exc:
            if exc.code not in (0, None):
                error = f"exit {exc.code}"
        except Exception as exc:  # report, keep serving
            error = f"{type(exc).__name__}: {exc}"
    out = buf.getvalue()
    m = re.search(r"^\{", out, re.M)
    content = ""
    if m:
        try:
            content = json.loads(out[m.start():]).get("content", "").strip()
        except ValueError:
            content = out[m.start():].strip()
    if content and not error:
        emit({"id": req.get("id"), "ok": True, "content": content})
    else:
        emit({"id": req.get("id"), "ok": False, "content": error or out.strip()[-300:] or "no output"})
