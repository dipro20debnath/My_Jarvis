@echo off
setlocal
set "ROOT=%~dp0.."
if not defined OPENJARVIS_HOME set "OPENJARVIS_HOME=%ROOT%\my-agent"
rem Terminals opened before uv/Ollama were installed don't have them on PATH yet.
set "PATH=%USERPROFILE%\.local\bin;%ROOT%\Ollama;%PATH%"
if not defined OLLAMA_MODELS set "OLLAMA_MODELS=%ROOT%\ollama-models"
rem Smaller context = less RAM; 16384 (the default) runs out of memory on this laptop.
if not defined JARVIS_NUM_CTX set "JARVIS_NUM_CTX=8192"
rem Same for a key saved with SetEnvironmentVariable after this terminal opened.
if not defined ELEVENLABS_API_KEY for /f "tokens=2,*" %%A in ('reg query HKCU\Environment /v ELEVENLABS_API_KEY 2^>nul ^| find "ELEVENLABS_API_KEY"') do set "ELEVENLABS_API_KEY=%%B"
if not defined ELEVENLABS_AGENT_ID for /f "tokens=2,*" %%A in ('reg query HKCU\Environment /v ELEVENLABS_AGENT_ID 2^>nul ^| find "ELEVENLABS_AGENT_ID"') do set "ELEVENLABS_AGENT_ID=%%B"
uv run --project "%ROOT%\OpenJarvis" --with "elevenlabs[pyaudio]" python "%~dp0jarvis_voice.py" %*
