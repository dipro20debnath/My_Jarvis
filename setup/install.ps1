# One-time setup of Jarvis on a new Windows PC. Run from the repo folder:
#   powershell -ExecutionPolicy Bypass -File setup\install.ps1
# Needs: Git and an internet connection. Installs uv (Python manager) if
# missing, downloads OpenJarvis and portable Ollama into this folder, applies
# Jarvis's changes to OpenJarvis and creates the shortcuts.

$ErrorActionPreference = "Continue"  # git/uv print progress on stderr
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$OPENJARVIS_COMMIT = "c14f579d864f8698fbd5d0046c2a6630d2f90667"  # the version the patch was made for

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# Keep caches next to the project (handy when C: is small).
$env:UV_CACHE_DIR = Join-Path $root "_cache\uv"
$env:OLLAMA_MODELS = Join-Path $root "ollama-models"

Step "Checking uv"
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
}

Step "Getting OpenJarvis"
if (-not (Test-Path "OpenJarvis\.git")) {
    git clone https://github.com/open-jarvis/OpenJarvis.git OpenJarvis
    if ($LASTEXITCODE -ne 0) { throw "git clone failed - is Git installed and are you online?" }
    git -C OpenJarvis checkout -q $OPENJARVIS_COMMIT
}
git -C OpenJarvis apply --check ..\openjarvis-patch\jarvis-changes.patch 2>$null
if ($LASTEXITCODE -eq 0) {
    git -C OpenJarvis apply ..\openjarvis-patch\jarvis-changes.patch
    Write-Output "Applied Jarvis changes to OpenJarvis."
} else {
    Write-Output "Jarvis changes already applied (or OpenJarvis was modified) - skipping the patch."
}

Step "Installing Python packages (a few minutes the first time)"
Push-Location OpenJarvis
uv sync --extra server --extra speech --extra tools-search --extra inference-cloud
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "uv sync failed - see the messages above." }
uv pip install edge-tts
Pop-Location

Step "Getting Ollama (portable)"
if (-not (Test-Path "Ollama\ollama.exe")) {
    New-Item -ItemType Directory -Force "_downloads" | Out-Null
    $zip = "_downloads\ollama-windows-amd64.zip"
    Invoke-WebRequest https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip -OutFile $zip
    Expand-Archive $zip -DestinationPath "Ollama" -Force
}

Step "Creating shortcuts"
& (Join-Path $PSScriptRoot "create-shortcuts.ps1")

Write-Host "`nDone. Next steps (see README):" -ForegroundColor Green
Write-Host "  1. .\Ollama\ollama.exe signin            (free Ollama account, for the cloud model)"
Write-Host "  2. .\Ollama\ollama.exe pull qwen3.5:4b   (optional offline fallback model, ~3 GB)"
Write-Host "  3. Double-click 'Jarvis HUD' on the Desktop."
