"""Talk to your ElevenLabs voice agent; it hands PC jobs to local Jarvis.

Flow:
  you speak -> ElevenLabs agent (real-time voice) -> calls client tool `ask_jarvis`
  -> this script runs `jarvis ask` on this PC in the background
  -> the result is sent back into the conversation and the agent says it.

ElevenLabs waits at most 120 s for a tool, and Jarvis on this CPU can take
longer, so the tool returns at once and the result arrives later as a message.

Run with:  start-voice-agent.cmd      (Ctrl+C to stop)
"""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
from pathlib import Path

from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import ClientTools, Conversation
from elevenlabs.conversational_ai.default_audio_interface import DefaultAudioInterface

AGENT_ID = os.environ.get("ELEVENLABS_AGENT_ID", "")
API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
# Ask in this terminal before Jarvis runs a spoken command. Set JARVIS_CONFIRM=0 to skip.
CONFIRM = os.environ.get("JARVIS_CONFIRM", "1") != "0"
JARVIS_TIMEOUT_S = 600
MAX_RESULT_CHARS = 1500

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("OPENJARVIS_HOME", str(ROOT / "my-agent"))

tasks: "queue.Queue[str]" = queue.Queue()
conversation: Conversation | None = None


def run_jarvis(command: str) -> str:
    """Run one command through the local Jarvis agent and return its answer."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, "-c", "from openjarvis.cli import main; main()",
         "ask", "-e", "ollama", "--no-stream", "--json", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=JARVIS_TIMEOUT_S, env=env,
    )
    out = proc.stdout
    start = out.find("{")
    if proc.returncode != 0 or start < 0:
        err = (proc.stderr or out).strip().splitlines()
        return "Jarvis failed: " + (err[-1] if err else f"exit code {proc.returncode}")
    try:
        content = json.loads(out[start:]).get("content", "").strip()
    except json.JSONDecodeError:
        content = out[start:].strip()
    return content or "Jarvis finished but returned no text."


def worker() -> None:
    """Run queued Jarvis tasks one at a time and report each result."""
    while True:
        command = tasks.get()
        if CONFIRM:
            print(f"\n>>> Jarvis wants to run: {command!r}")
            answer = input(">>> Run it? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                print(">>> Skipped.")
                send(f"[Jarvis result] The user declined to run: {command}")
                continue
        print(f"\n[jarvis] working on: {command}")
        try:
            result = run_jarvis(command)
        except subprocess.TimeoutExpired:
            result = f"Jarvis timed out after {JARVIS_TIMEOUT_S} seconds."
        except Exception as exc:  # report, never kill the worker
            result = f"Jarvis error: {exc}"
        print(f"[jarvis] done:\n{result}\n")
        if len(result) > MAX_RESULT_CHARS:
            result = result[:MAX_RESULT_CHARS] + " ... (full answer is in the terminal)"
        send(f"[Jarvis result for: {command}]\n{result}\n\nTell me this result briefly.")


def send(text: str) -> None:
    if conversation is not None:
        try:
            conversation.send_user_message(text)
        except Exception as exc:
            print(f"[bridge] could not deliver result to the agent: {exc}")


def ask_jarvis(parameters: dict) -> str:
    """Client tool called by the ElevenLabs agent."""
    command = str(parameters.get("command", "")).strip()
    if not command:
        return "No command given. Ask the user what Jarvis should do."
    if command.lower().split(" ", 1)[0].strip(".,!") in ("stop", "cancel", "abort"):
        dropped = 0
        while not tasks.empty():
            tasks.get_nowait()
            dropped += 1
        print(f"\n[bridge] stop requested: cleared {dropped} waiting task(s)")
        return (
            f"Cleared {dropped} waiting Jarvis task(s). A task already running "
            "will finish, and the user can say no to it in the terminal."
        )
    tasks.put(command)
    return (
        "Task handed to Jarvis on the user's PC. It can take 1-3 minutes. "
        "Tell the user briefly that you're on it. The result will arrive later "
        "in a message starting with [Jarvis result]."
    )


def main() -> None:
    global conversation
    if not AGENT_ID:
        sys.exit("Set ELEVENLABS_AGENT_ID to your ElevenLabs agent ID first (see README).")
    tools = ClientTools()
    tools.register("ask_jarvis", ask_jarvis)
    threading.Thread(target=worker, daemon=True).start()

    conversation = Conversation(
        ElevenLabs(api_key=API_KEY or None),
        AGENT_ID,
        requires_auth=bool(API_KEY),
        audio_interface=DefaultAudioInterface(),
        client_tools=tools,
        callback_agent_response=lambda r: print(f"Agent: {r}"),
        callback_agent_response_correction=lambda o, c: print(f"Agent (corrected): {c}"),
        callback_user_transcript=lambda t: print(f"You: {t}"),
    )
    print("Connecting to your ElevenLabs agent... speak when connected. Ctrl+C to stop.")
    print(f"Confirm before running commands: {'ON' if CONFIRM else 'OFF'}")
    conversation.start_session()
    signal.signal(signal.SIGINT, lambda sig, frame: conversation.end_session())
    conversation_id = conversation.wait_for_session_end()
    print(f"Session ended. Conversation ID: {conversation_id}")


if __name__ == "__main__":
    main()
