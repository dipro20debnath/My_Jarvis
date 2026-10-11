@echo off
setlocal
set "SRC=%~dp0..\OpenJarvis"
if not defined OPENJARVIS_HOME set "OPENJARVIS_HOME=%~dp0..\my-agent"
rem Terminals opened before uv/Ollama were installed don't have them on PATH yet.
set "PATH=%USERPROFILE%\.local\bin;%~dp0..\Ollama;%PATH%"
if not defined OLLAMA_MODELS set "OLLAMA_MODELS=%~dp0..\ollama-models"
rem Smaller context = less RAM; 16384 (the default) runs out of memory on this laptop.
if not defined JARVIS_NUM_CTX set "JARVIS_NUM_CTX=8192"
if not defined ELEVENLABS_API_KEY for /f "tokens=2,*" %%A in ('reg query HKCU\Environment /v ELEVENLABS_API_KEY 2^>nul ^| find "ELEVENLABS_API_KEY"') do set "ELEVENLABS_API_KEY=%%B"
uv run --project "%SRC%" jarvis %*
