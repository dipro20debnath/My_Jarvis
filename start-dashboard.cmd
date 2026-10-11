@echo off
setlocal
rem Opens the Jarvis visual dashboard at http://localhost:5173 (close this window to stop it).
set "ROOT=%~dp0"
if not defined OPENJARVIS_HOME set "OPENJARVIS_HOME=%ROOT%my-agent"
set "PATH=%USERPROFILE%\.local\bin;%ROOT%Ollama;%PATH%"
if not defined OLLAMA_MODELS set "OLLAMA_MODELS=%ROOT%ollama-models"
rem Smaller context = less RAM; 16384 (the default) runs out of memory on this laptop.
if not defined JARVIS_NUM_CTX set "JARVIS_NUM_CTX=8192"
rem Keep npm's download cache off the nearly-full C: drive.
set "npm_config_cache=%ROOT%_cache\npm"
if not defined ELEVENLABS_API_KEY for /f "tokens=2,*" %%A in ('reg query HKCU\Environment /v ELEVENLABS_API_KEY 2^>nul ^| find "ELEVENLABS_API_KEY"') do set "ELEVENLABS_API_KEY=%%B"
rem Start Ollama if it isn't running yet.
curl -s -o nul http://127.0.0.1:11434/api/tags || start "" /min "%ROOT%Ollama\ollama.exe" serve
cd /d "%ROOT%OpenJarvis"
uv run jarvis gui
