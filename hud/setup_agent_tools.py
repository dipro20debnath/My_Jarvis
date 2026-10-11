"""Create/update the HUD client tools on the ElevenLabs agent and set its prompt.

The tool list is taken from server.BRAIN_TOOLS, so the ElevenLabs agent and
the free-voice brain always have the same tools. Safe to re-run: existing
tools with the same name are updated, not duplicated.
Run:  OpenJarvis\\.venv\\Scripts\\python.exe hud\\setup_agent_tools.py
"""

from __future__ import annotations

import importlib.util
import sys
import winreg
from pathlib import Path

import httpx

BASE = "https://api.elevenlabs.io/v1/convai"

spec = importlib.util.spec_from_file_location("hud_server", Path(__file__).with_name("server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)  # defines the app; does not start the server
AGENT = hud.AGENT_ID
if not AGENT:
    sys.exit("Set ELEVENLABS_AGENT_ID first (see README).")

with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
    H = {"xi-api-key": winreg.QueryValueEx(k, "ELEVENLABS_API_KEY")[0]}

PROMPT = hud.BRAIN_PROMPT.replace(
    "talking by voice through their HUD dashboard.",
    "talking by voice through their HUD dashboard. Call get_agenda at the start of a conversation if you need "
    "today's date, schedule or the weather.",
)


def config(fn: dict) -> dict:
    f = fn["function"]
    return {"tool_config": {
        "type": "client", "name": f["name"], "description": f["description"],
        "expects_response": True, "response_timeout_secs": 30,
        "parameters": f["parameters"],
    }}


existing = {t["tool_config"]["name"]: t["id"]
            for t in httpx.get(f"{BASE}/tools", headers=H, timeout=30).raise_for_status().json()["tools"]}
ids = []
for fn in hud.BRAIN_TOOLS:
    name, body = fn["function"]["name"], config(fn)
    if name in existing:
        r = httpx.patch(f"{BASE}/tools/{existing[name]}", headers=H, json=body, timeout=30)
        tool_id = existing[name]
    else:
        r = httpx.post(f"{BASE}/tools", headers=H, json=body, timeout=30)
        tool_id = r.json().get("id") if r.status_code < 300 else None
    print(f"{name:16} {r.status_code} {'' if r.status_code < 300 else r.text[:300]}")
    if r.status_code >= 300:
        sys.exit(1)
    ids.append(tool_id)

agent = httpx.get(f"{BASE}/agents/{AGENT}", headers=H, timeout=30).json()
params = {"branch_id": agent["branch_id"]} if agent.get("branch_id") else {}
body = {
    "conversation_config": {"agent": {"prompt": {"prompt": PROMPT, "tool_ids": ids}}},
    "version_description": "HUD tools: instant PC actions, timers, notes, to-do, calendar, Jarvis tasks",
}
r = httpx.patch(f"{BASE}/agents/{AGENT}", headers=H, params=params, json=body, timeout=30)
print("patch agent:", r.status_code, "" if r.status_code < 300 else r.text[:500])
p = httpx.get(f"{BASE}/agents/{AGENT}", headers=H, params=params, timeout=30).json()["conversation_config"]["agent"]["prompt"]
print("tools on agent:", len(p.get("tool_ids") or []), "| prompt updated:", p.get("prompt") == PROMPT)
