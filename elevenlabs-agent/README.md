# ElevenLabs voice agent + Jarvis

You talk to your ElevenLabs agent ("My Agent") in real time. When you ask for something
that needs your PC (files, commands, web research, memory), the agent calls the
`ask_jarvis` tool, local Jarvis does the work, and the agent tells you the result.

## One-time setup

### 1. Add the tool to your agent (elevenlabs.io → Agents → My Agent → Tools → Add tool)
- Tool type: **Client**
- Name: `ask_jarvis`  (exact spelling, case-sensitive)
- Description: `Hands a task to Jarvis, the user's local AI agent running on their Windows PC. Use it for anything that needs the user's computer: files, folders, running commands, installing or checking software, web research, or remembering facts about the user.`
- Parameter: identifier `command`, type **string**, required, description `The full task for Jarvis, in clear words, with all details the user gave.`
- **Wait for response**: ON

### 2. Add this to the agent's System prompt
```
You are Jarvis's voice. For anything that needs the user's computer, call the
ask_jarvis tool with a clear, complete command. Jarvis replies later in a message
that starts with [Jarvis result]: summarize it out loud in one or two sentences.
While waiting, you can keep talking with the user. For plain questions and
conversation, answer yourself without the tool. When the user asks how to do
something, suggest the best way first, then offer to have Jarvis do it.
```

### 3. Your API key (only needed if the agent is private / has authentication on)
In PowerShell (paste your own key, keep it secret):
```
[Environment]::SetEnvironmentVariable('ELEVENLABS_API_KEY', 'YOUR_KEY_HERE', 'User')
```
Then open a new terminal. The same key also powers `jarvis chat --voice`.

## Run
Double-click `start-voice-agent.cmd`, or in a terminal:
```
"D:\Software\My Cyber Field\Jarvis\elevenlabs-agent\start-voice-agent.cmd"
```
Speak when it says connected. Ctrl+C to stop. Use headphones so the agent doesn't hear itself.

## Safety
Before Jarvis runs anything you asked for by voice, the terminal shows the exact
command and waits for `y`. Speech can be misheard, so keep this ON.
To turn it off (not recommended): `set JARVIS_CONFIRM=0` before starting.

## Notes
- Jarvis runs on your CPU: expect 1-3 minutes per task. The agent stays responsive meanwhile.
- Ollama must be running (it starts with Windows; or run `ollama serve`).
- Different agent? `set ELEVENLABS_AGENT_ID=agent_...` before starting.
