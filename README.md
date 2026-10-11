# My Jarvis

A personal, voice-controlled AI assistant for Windows, inspired by Iron Man's J.A.R.V.I.S.
You talk to it in **Bangla, Banglish or English**. It answers out loud, runs common PC
actions instantly, keeps your to-dos, calendar, notes and timers, and hands bigger jobs
(files, commands, web research) to a full AI agent running on your own PC.

Built on [OpenJarvis](https://github.com/open-jarvis/OpenJarvis) and [Ollama](https://ollama.com).
It works **for free**: free Ollama Cloud models, free Microsoft neural voices and free
browser speech recognition. ElevenLabs is optional.

---

## Contents

1. [Features](#1-features)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
4. [Starting and stopping Jarvis](#4-starting-and-stopping-jarvis)
5. [The HUD screen](#5-the-hud-screen)
6. [Talking to Jarvis](#6-talking-to-jarvis)
7. [Voice command reference](#7-voice-command-reference)
8. [Jarvis tasks and approval](#8-jarvis-tasks-and-approval)
9. [Typing, buttons and keyboard shortcuts](#9-typing-buttons-and-keyboard-shortcuts)
10. [Choosing the AI model](#10-choosing-the-ai-model)
11. [ElevenLabs voice (optional)](#11-elevenlabs-voice-optional)
12. [Other ways to use Jarvis](#12-other-ways-to-use-jarvis)
13. [Personalising Jarvis](#13-personalising-jarvis)
14. [Your data and privacy](#14-your-data-and-privacy)
15. [Troubleshooting](#15-troubleshooting)
16. [Project structure](#16-project-structure)
17. [For developers](#17-for-developers)
18. [Credits](#18-credits)

**বাংলায় দ্রুত শুরু:** [নিচে দেখুন](#বাংলায়-দ্রুত-শুরু)

---

## 1. Features

**Live HUD dashboard**
- Animated voice orb that moves with the real frequency of your voice and Jarvis's voice.
  Its colours show the state: cyan when listening, violet when thinking, gold when speaking.
- Clock with the English and Bangla date, weather for any city, and live PC stats
  (CPU, RAM, battery, free disk space, uptime).
- Calendar with event reminders, to-do list, quick notes and countdown timers.
- A task panel for jobs the full Jarvis agent is working on.

**Voice control**
- Speak naturally in Bangla, Banglish or English. Jarvis replies in your language.
- **Instant commands** (no AI call, answered in milliseconds): timers, volume, music,
  YouTube, opening apps and websites, time and date, weather, news, screenshots,
  locking the PC and notes.
- **Smart commands** go to a cloud AI model that uses the same tools: "add a meeting
  tomorrow at 3", "what's on my agenda", "how is my PC doing".
- **Big jobs** go to the full Jarvis agent, which can work with files, run commands and
  search the web. It always asks for your OK before it starts a spoken job.
- An optional wake word ("Jarvis"), interrupting by voice, and controlling Jarvis's
  speaking speed and language by voice.

**Free natural voices.** Microsoft neural voices through edge-tts:
- Bangla: Pradeep (male) / Nabanita (female)
- English: Ryan (British male) / Sonia (female)

---

## 2. Requirements

| | |
|---|---|
| OS | Windows 10 or 11 (64-bit) |
| Browser | Microsoft Edge (built in), used for the HUD window and speech recognition |
| RAM | 8 GB minimum, 16 GB recommended |
| Disk | ~3 GB for the software, plus ~3 GB if you want the offline model |
| Internet | Needed for the cloud model, voices, speech recognition, weather and news |
| Software | [Git for Windows](https://git-scm.com/download/win). The installer gets everything else. |
| Optional | [Node.js](https://nodejs.org) (only for the OpenJarvis web dashboard), a headset (best for interrupting by voice) |

---

## 3. Installation

### Automatic (recommended)

Open **PowerShell** and run:

```powershell
cd D:\                       # any drive with free space
git clone https://github.com/dipro20debnath/My_Jarvis.git
cd My_Jarvis
powershell -ExecutionPolicy Bypass -File setup\install.ps1
```

The installer:
1. Installs **uv** (a Python manager) if you don't have it.
2. Downloads **OpenJarvis** into `OpenJarvis\` and applies this project's changes
   from `openjarvis-patch\jarvis-changes.patch`.
3. Installs the Python packages into `OpenJarvis\.venv`.
4. Downloads portable **Ollama** into `Ollama\`.
5. Creates the shortcuts on your Desktop and in the Start Menu.

All of it stays inside the project folder. Downloaded models also go there
(`ollama-models\`), which helps when your C: drive is small.

### Sign in to Ollama (for the free cloud model)

```powershell
.\Ollama\ollama.exe serve        # leave this window open the first time
# in a second PowerShell window, from the project folder:
.\Ollama\ollama.exe signin       # opens the browser; create a free account
```

### Optional: offline model

The offline model works without internet, but it is slower and less smart:

```powershell
$env:OLLAMA_MODELS = "$PWD\ollama-models"
.\Ollama\ollama.exe pull qwen3.5:4b
```

### Manual installation (if the script fails)

```powershell
git clone https://github.com/open-jarvis/OpenJarvis.git OpenJarvis
git -C OpenJarvis checkout c14f579d864f8698fbd5d0046c2a6630d2f90667
git -C OpenJarvis apply ..\openjarvis-patch\jarvis-changes.patch
cd OpenJarvis
uv sync --extra server --extra speech --extra tools-search --extra inference-cloud
uv pip install edge-tts
cd ..
# Download ollama-windows-amd64.zip from https://github.com/ollama/ollama/releases
# and unzip it into the "Ollama" folder.
powershell -ExecutionPolicy Bypass -File setup\create-shortcuts.ps1
```

---

## 4. Starting and stopping Jarvis

| Shortcut | What it does |
|---|---|
| **Jarvis HUD** | Starts Ollama and the HUD server in the background (no console windows) and opens the HUD in its own window. **This is the main app.** |
| **Stop Jarvis HUD** | Shuts the HUD server down. |
| Jarvis | Opens the original OpenJarvis web dashboard (needs Node.js). |
| Stop Jarvis | Stops that dashboard. |

- The first start takes ~10–20 seconds. The boot screen shows the progress.
- The Jarvis agent warms up in the background. The tasks panel shows **"⚡ Jarvis warm"** when it is ready.
- If you close the HUD window, the server keeps running. Open **Jarvis HUD** again to get the window back.
- You can also open `http://127.0.0.1:8765` in Edge.
- If something fails, a message box tells you. Logs are in `my-agent\jarvis-hud.log` and `my-agent\hud-server.log`.

---

## 5. The HUD screen

```
┌───────────────┬──────────────────────────────┬───────────────┐
│ Weather       │        (voice orb)           │ Calendar      │
│ System gauges │   caption of what's said     │ To-do list    │
│ Timers        │ [Start voice] [Mute] [menus] │ Notes         │
│ Quick commands│   toggles · conversation log │               │
│               │   type a command here…       │               │
│               │ Jarvis tasks                 │               │
└───────────────┴──────────────────────────────┴───────────────┘
```

**Top bar:** greeting, status light (STANDBY / LISTENING / THINKING / SPEAKING / WORKING) and clock.

**Left column**
- **Weather**: the current weather and today's forecast. To change the city, say
  *"weather widget-এ সিলেট দেখাও"* or *"show Sylhet weather on the widget"*.
- **System**: CPU, RAM and battery gauges, free space on C: and D:, the AI model in use, Ollama status and uptime.
- **Timers**: running timers with progress bars. The **1m / 5m / 10m / 25m** buttons start one with a click.
- **Quick commands**: one-click buttons for a daily briefing, PC status, music, YouTube, a screenshot, Downloads and news.

**Centre**
- **Orb**: click it to start or stop voice. While Jarvis speaks, a click stops the speech.
- **Caption**: what you said, or what Jarvis is saying.
- **Controls:**

  | Control | Meaning |
  |---|---|
  | 🎙️ Start voice / ⏹ Stop voice | Turns the microphone conversation on or off |
  | 🔇 Mute | Pauses the mic without ending the session |
  | Voice: Auto / ElevenLabs / Free | Which voice engine to use. Auto tries ElevenLabs, then falls back to Free. |
  | বাংলা / English | The language **you** speak, which tells speech recognition what to expect |
  | 🔊 Male / Female voice | Jarvis's voice |
  | 🔈 Test | Plays a test sentence. Use it to check your speakers. |

- **Toggles:**

  | Toggle | Meaning |
  |---|---|
  | Wake word "Jarvis" | Jarvis only reacts when a sentence starts with "Jarvis". After that you have 20 s for follow-ups without the wake word. |
  | Interrupt by voice | Start talking while Jarvis speaks to cut it off. Works best with headphones. |
  | Speak replies | Jarvis reads replies aloud even when you typed the command |
  | Auto-approve ⚠️ | Spoken PC jobs run **without** asking first. Leave it off unless you trust your mic. |

- **Conversation log**: everything said, with the response time (⚡ instant or seconds).
- **Command box**: type instead of talking.
- **Jarvis tasks**: jobs for the full agent, with their status (NEEDS OK, QUEUED, WORKING, DONE, FAILED) and results.

**Right column**
- **Calendar**: click a day to see its events. Use the ◀ ▶ buttons to change month. Add an event with the small form.
  At an event's time, Jarvis plays an alarm and tells you about it.
- **To-do**: add, tick off or delete to-dos. A due date is optional; overdue ones turn red.
- **Notes**: quick notes, newest first.

All of this is saved automatically and survives restarts.

---

## 6. Talking to Jarvis

1. Click anywhere on the page once. Browsers only allow sound after a click.
2. Press **🎙️ Start voice** (or `Space`). The first time, Edge asks for **microphone permission**: choose *Allow*.
3. Speak. Your words appear live. When you pause, Jarvis answers.
4. Keep talking. Jarvis listens again after it finishes speaking.
5. Say **"থামো"** / **"stop"** or press `Esc` to make it stop talking.

**How Jarvis handles a request**

| Type | Example | Speed |
|---|---|---|
| ⚡ Instant | "৫ মিনিটের টাইমার দাও" | ~0.01–3 s (rules, no AI) |
| 🧠 Smart | "কাল বিকেল ৩টায় মিটিং রাখো" | ~1–4 s (cloud AI with tools) |
| 🛠️ Jarvis task | "Downloads ফোল্ডারে কত PDF আছে দেখো" | seconds to minutes (full agent, needs your OK) |

**Tips for better recognition**
- Choose the language you are speaking (বাংলা or English) in the menu. You can switch by
  voice: *"English-এ শোনো"* / *"বাংলায় শোনো"*.
- Speak in short, clear sentences and pause when you're done.
- Banglish is fine in Bangla mode, and English app names are understood
  ("ক্রোম খোলো", "ইউটিউবে … চালাও").

---

## 7. Voice command reference

Mix languages freely. Each example also works in similar words.

### Timers and alarms
| Say | Result |
|---|---|
| "৫ মিনিটের টাইমার দাও" · "set a timer for 10 minutes" · "dosh minute timer" | Starts a timer |
| "চায়ের জন্য ৩ মিনিটের টাইমার" · "আধা ঘণ্টার টাইমার" · "1 hour 30 minutes timer" | A labelled timer, half an hour, hours and minutes |
| "টাইমার বন্ধ করো" · "cancel the timer" | Cancels a timer |

### Volume and media
| Say | Result |
|---|---|
| "ভলিউম বাড়াও / কমাও" · "volume ektu komao" · "turn the volume up" | Volume up or down (add "একটু" for a little or "অনেক" for a lot) |
| "মিউট করো" · "mute" | Mute or unmute |
| "গান থামাও" · "pause" · "পরের গান" · "next" · "আগের গান" | Play/pause, next, previous |

### YouTube and music
| Say | Result |
|---|---|
| "ইউটিউবে অরিজিৎ সিং এর গান চালাও" · "youtube e arijit singh chalao" · "play shape of you" | Opens YouTube results |
| "রবীন্দ্র সংগীত গান চালাও" | Searches YouTube |

### Opening apps, folders and websites
| Say | Result |
|---|---|
| "হোয়াটসঅ্যাপ খোলো" · "open telegram" · "ক্রোম খোলো" · "notepad kholo" | Opens **any installed app** (Start Menu apps included) |
| "Downloads ফোল্ডার খোলো" · "open documents" | Opens a folder (downloads, documents, desktop, pictures, music, videos, jarvis folder) |
| "ইউটিউব খোলো" · "open gmail" · "open github" | Opens a website |
| "open example.com" | Opens that address |

### Information
| Say | Result |
|---|---|
| "কয়টা বাজে" · "what time is it" | Time |
| "আজ কত তারিখ" · "ki bar ajke" | Date and day |
| "আজকের আবহাওয়া কেমন" · "সিলেটের আবহাওয়া কেমন" · "weather in London" | Weather for your city or any city |
| "আজকের খবর শোনাও" · "cyber security news" · "ক্রিকেটের খবর" | Top 5 headlines (Bangla news from Prothom Alo / BBC Bangla, topics from Google News) |
| "আমার PC-র অবস্থা কেমন?" · "D drive-এ কত জায়গা আছে?" | CPU, RAM, disks, battery and the heaviest programs |
| "আজকের agenda কী?" · "give me my daily briefing" | Your day: events, to-dos, timers and weather |

### Calendar, to-dos and notes
| Say | Result |
|---|---|
| "কাল বিকেল ৩টায় মিটিং রাখো" · "add dentist on Friday at 10" | Adds a calendar event |
| "মিটিংটা মুছে দাও" | Deletes the closest-matching event |
| "টু-ডু লিস্টে বাজার করা যোগ করো" · "add buy milk to my to-do" | Adds a to-do |
| "বাজার করা শেষ" · "mark buy milk as done" | Ticks it off |
| "নোট রাখো কাল রহিমকে ফোন দিতে হবে" · "note: wifi password is on the router" | Saves a note (start the sentence with "নোট" / "note") |

### PC
| Say | Result |
|---|---|
| "স্ক্রিনশট নাও" · "take a screenshot" | Saves to Pictures › Screenshots |
| "পিসি লক করো" · "lock the computer" | Locks Windows |

### Controlling Jarvis itself
| Say | Result |
|---|---|
| "থামো" · "চুপ" · "stop" | Stops speaking |
| "আবার বলো" · "repeat that" | Repeats the last answer |
| "আস্তে বলো" · "speak faster" | Changes the speaking speed |
| "English-এ শোনো" · "বাংলায় শোনো" | Switches the listening language |
| "হ্যাঁ" / "করো" / "yes" · "না" / "বাদ দাও" / "no" | Approves or cancels a waiting Jarvis task |

### Anything else
Ask a question or give an instruction. If it needs your PC (files, programs,
research), Jarvis offers to do it as a task:
- "Downloads ফোল্ডারে সবচেয়ে বড় ১০টা ফাইল কোনগুলো?"
- "Find the latest Python version and tell me what's new"
- "আমার Documents ফোল্ডারে একটা to-do.txt ফাইল বানাও"

---

## 8. Jarvis tasks and approval

The full Jarvis agent (OpenJarvis orchestrator) can read and write files, run commands,
search the web and remember facts about you. Because it can change things on your PC:

- **Spoken** jobs are created as **NEEDS OK**. Jarvis reads the job back and waits.
  Say **"হ্যাঁ" / "yes"** to run it or **"না" / "no"** to cancel. You can also use the
  **✔ Run it / ✖ Cancel** buttons. Misheard speech can never start a job on its own.
- **Typed** jobs run straight away, because typing is deliberate.
- A running job can be stopped with **■ Stop**.
- When a job finishes, you hear a chime and Jarvis tells you the result. The full text
  stays in the tasks panel. **Clear finished** removes old tasks.
- Before deleting, overwriting, installing or sending anything, the agent itself asks
  again, as set in `my-agent\SOUL.md`.

---

## 9. Typing, buttons and keyboard shortcuts

- Type in the command box and press **Enter**. It works exactly like speaking, and the
  reply is spoken when **Speak replies** is on.
- **Quick commands** buttons run common requests with one click.

| Key | Action |
|---|---|
| `Space` | Start voice / listen now / interrupt Jarvis |
| `Esc` | Stop speaking |
| `/` | Jump to the command box |

---

## 10. Choosing the AI model

The model is set in `my-agent\config.toml`:

```toml
[intelligence]
default_model = "gpt-oss:120b-cloud"   # free Ollama Cloud model (default)
fallback_model = "qwen3.5:4b"          # local model if the cloud fails
```

| Model | Where it runs | Notes |
|---|---|---|
| `gpt-oss:120b-cloud` | Ollama Cloud (free account) | Fast, smart, good Bangla. **Default.** |
| `gemma4:cloud`, `nemotron-3-super:cloud` | Ollama Cloud | Other free options |
| `qwen3.5:4b` | Your PC | Private and offline, but slower. Needs `ollama pull qwen3.5:4b`. |

Restart the HUD after changing the model (**Stop Jarvis HUD**, then **Jarvis HUD**).

---

## 11. ElevenLabs voice (optional)

ElevenLabs gives a real-time conversational voice agent with very natural speech.
It needs ElevenLabs credits. When they run out, Jarvis switches to the free voice on its own.

1. Create an agent at [elevenlabs.io → Agents](https://elevenlabs.io/app/agents) and copy its **agent ID** (`agent_...`).
2. Create an API key at elevenlabs.io › Developers › API keys.
3. Save both in Windows. Never put them in a file or a commit:

   ```powershell
   [Environment]::SetEnvironmentVariable('ELEVENLABS_API_KEY',  'YOUR_KEY',      'User')
   [Environment]::SetEnvironmentVariable('ELEVENLABS_AGENT_ID', 'agent_xxxxxxx', 'User')
   ```
4. Give the agent the HUD's tools and prompt (safe to re-run any time):

   ```powershell
   .\OpenJarvis\.venv\Scripts\python.exe hud\setup_agent_tools.py
   ```
5. Restart the HUD and pick **Voice: ElevenLabs** (or Auto).

---

## 12. Other ways to use Jarvis

**Command line** (`bin\jarvis.cmd`):

```powershell
bin\jarvis.cmd ask "How much free space is on D:?"
bin\jarvis.cmd chat            # interactive chat that asks before each shell command
bin\jarvis.cmd chat --voice    # talk in the terminal (Whisper speech-to-text)
```

**OpenJarvis web dashboard**: the **Jarvis** shortcut, or `start-dashboard.cmd`. Needs Node.js.

**ElevenLabs voice in a terminal**: `elevenlabs-agent\start-voice-agent.cmd`. See
[elevenlabs-agent/README.md](elevenlabs-agent/README.md).

---

## 13. Personalising Jarvis

All of these are plain text files in `my-agent\`. Edit them with any editor; changes apply to the next request.

| File | What it controls |
|---|---|
| `USER.md` | About you: language, location, computer, goals and rules ("never delete without asking") |
| `SOUL.md` | Jarvis's personality, way of working and safety rules |
| `config.toml` | Model, enabled agent tools, agent turns and speech settings |

Environment variables you can set (User scope):

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_MODELS` | `<project>\ollama-models` | Where models are stored |
| `JARVIS_NUM_CTX` | `8192` | Context size (lower = less RAM) |
| `ELEVENLABS_API_KEY` / `ELEVENLABS_AGENT_ID` | none | Optional ElevenLabs voice |

---

## 14. Your data and privacy

- **On your PC:** to-dos, events, notes, timers, tasks and settings are kept in
  `my-agent\hud-data.json`. The agent's memory, logs and databases are also in
  `my-agent\`. None of it is uploaded to GitHub (see `.gitignore`).
- **Sent to the internet:**
  - your requests to the AI model (Ollama Cloud, unless you use a local model)
  - your speech to Microsoft's speech recognition (Edge)
  - Jarvis's replies to Microsoft's voice service (edge-tts)
  - city names to Open-Meteo (weather)
  - news feeds
  - ElevenLabs, only if you turn it on
- **Keys:** API keys are read from Windows environment variables, never stored in the
  project. The browser never sees the ElevenLabs key; the server hands it a short-lived token.
- **Fully offline:** use `qwen3.5:4b`. Voice still needs internet.

---

## 15. Troubleshooting

| Problem | Fix |
|---|---|
| **Jarvis doesn't speak** | 1) Click the page once, then press **🔈 Test**. 2) Check that the Windows sound output (taskbar 🔊) is your speakers, not disconnected Bluetooth earbuds. 3) Check the volume. 4) Make sure **Speak replies** is on. |
| **"Microphone blocked"** | In Edge, click the 🔒 next to the address › Microphone › Allow, then reload. Also check Windows Settings › Privacy › Microphone. |
| **It doesn't hear me / cuts me off** | Pick the right language (বাংলা / English). Speak closer to the mic. Turn off **Wake word** if it's on. |
| **Jarvis stops itself while speaking** | Turn off **Interrupt by voice**, or use headphones. |
| **"Speech recognition needs internet"** | Recognition runs on Microsoft's servers. Check your connection. |
| **"Jarvis brain error: Model error"** | Ollama isn't running, or you aren't signed in. Run `.\Ollama\ollama.exe signin`, or switch to a local model. |
| **Ollama "out of memory"** | Close heavy apps, keep `JARVIS_NUM_CTX=8192` or lower, or use a cloud model. |
| **The HUD server did not start** | Read `my-agent\hud-server.log`. Usually the port is busy (another HUD is running), so press **Stop Jarvis HUD** first. |
| **The task panel says "warming up…" for a long time** | Read `my-agent\hud-worker.log`. Re-run `setup\install.ps1` to repair the packages. |
| **An app doesn't open by voice** | Say the name as it appears in the Start Menu, e.g. "open Visual Studio Code". |
| **ElevenLabs won't connect** | Credits may be used up (Jarvis falls back to Free on its own), or `ELEVENLABS_AGENT_ID` isn't set. |

---

## 16. Project structure

```
My_Jarvis/
├── hud/                      # The live HUD (main app)
│   ├── server.py             # FastAPI server: data, PC actions, AI "brain", voices, weather, news
│   ├── quick.py              # Instant command rules (Bangla/Banglish/English)
│   ├── jarvis_worker.py      # Keeps the OpenJarvis agent warm for fast tasks
│   ├── jarvis_hud.pyw        # Launcher used by the "Jarvis HUD" shortcut
│   ├── setup_agent_tools.py  # Syncs the tools to the ElevenLabs agent
│   └── static/               # index.html, app.js (voice + orb), style.css, vendor/ (ElevenLabs SDK)
├── app/                      # Launcher for the OpenJarvis web dashboard + icon
├── bin/jarvis.cmd            # Jarvis command line
├── elevenlabs-agent/         # Terminal voice bridge for an ElevenLabs agent
├── my-agent/                 # Jarvis's home: config.toml, SOUL.md, USER.md (+ private runtime data, not in git)
├── openjarvis-patch/         # This project's changes to OpenJarvis (ElevenLabs TTS, fixes)
├── setup/                    # install.ps1, create-shortcuts.ps1
└── start-dashboard.cmd       # Starts the OpenJarvis web dashboard in a console
```

Created by the installer (not in git): `OpenJarvis/`, `Ollama/`, `ollama-models/`, `_cache/`.

---

## 17. For developers

- **Run the HUD server by hand** (to see errors):
  `.\OpenJarvis\.venv\Scripts\python.exe hud\server.py`, then open http://127.0.0.1:8765
- **Add an instant command**: add a rule in `quick.match()` in `hud/quick.py`. Return
  `{"tool": ..., "args": ...}` or `{"reply": ...}`.
- **Add a tool** for the AI brain and ElevenLabs:
  1. Add it to `BRAIN_TOOLS` and `_run_tool()` in `hud/server.py`.
  2. Add it to `TOOL_NAMES` in `hud/static/app.js`.
  3. Run `setup_agent_tools.py`.
- **OpenJarvis changes**: edit inside `OpenJarvis/`, then regenerate the patch:
  `git -C OpenJarvis diff > openjarvis-patch\jarvis-changes.patch`
  (run `git add -N` on new files first).
- **The HUD API** (JSON on `127.0.0.1:8765`):
  - `/api/state`, `/api/system`
  - `/api/assistant`, `/api/tool`, `/api/tts`
  - `/api/tasks`, `/api/todos`, `/api/events`, `/api/notes`, `/api/timers`, `/api/settings`

---

## 18. Credits

- [OpenJarvis](https://github.com/open-jarvis/OpenJarvis): the agent framework (Apache-2.0)
- [Ollama](https://ollama.com): local and cloud models
- [edge-tts](https://github.com/rany2/edge-tts): free Microsoft neural voices
- [Open-Meteo](https://open-meteo.com): free weather API
- [ElevenLabs JS SDK](https://github.com/elevenlabs/packages) (MIT): optional voice agent
- News: Prothom Alo, BBC Bangla and Google News RSS feeds

Made by **[dipro20debnath](https://github.com/dipro20debnath)**.

---

## বাংলায় দ্রুত শুরু

1. **Install:** PowerShell-এ চালান:
   ```powershell
   git clone https://github.com/dipro20debnath/My_Jarvis.git
   cd My_Jarvis
   powershell -ExecutionPolicy Bypass -File setup\install.ps1
   ```
2. **Ollama-য় sign in:** `.\Ollama\ollama.exe signin` চালান (ফ্রি account, cloud model-এর জন্য)।
3. **চালু করা:** Desktop-এর **Jarvis HUD** shortcut-এ ডাবল ক্লিক করুন। বন্ধ করতে **Stop Jarvis HUD**।
4. **কথা বলা:** পেজে একবার ক্লিক করুন, তারপর **🎙️ Start voice** (বা `Space`) চাপুন। Microphone permission চাইলে *Allow* দিন, তারপর বলুন।
5. **কিছু কমান্ড:**
   - "৫ মিনিটের টাইমার দাও"
   - "ভলিউম কমাও"
   - "হোয়াটসঅ্যাপ খোলো"
   - "ইউটিউবে অরিজিৎ সিং চালাও"
   - "সিলেটের আবহাওয়া কেমন"
   - "আজকের খবর শোনাও"
   - "কাল ৩টায় মিটিং রাখো"
   - "নোট রাখো …"
   - "থামো"
   - "আবার বলো"
6. **বড় কাজ:** ফাইল, কমান্ড বা research-এর কাজ বললে Jarvis আগে অনুমতি চাইবে। "হ্যাঁ" বললে শুরু করবে, "না" বললে বাতিল।
7. **কথা শোনা না গেলে:** **🔈 Test** চাপুন। Windows-এর sound output আর volume দেখুন।

বিস্তারিত সব উপরের ইংরেজি অংশে আছে।
