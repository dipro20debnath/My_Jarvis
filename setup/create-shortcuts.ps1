# Creates the Desktop and Start Menu shortcuts for Jarvis:
#   Jarvis HUD / Stop Jarvis HUD  - the live voice HUD (recommended)
#   Jarvis / Stop Jarvis          - the OpenJarvis web dashboard
# Run:  powershell -ExecutionPolicy Bypass -File setup\create-shortcuts.ps1

$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root "OpenJarvis\.venv\Scripts\pythonw.exe"
$icon = Join-Path $root "app\jarvis.ico"
if (-not (Test-Path $pythonw)) { throw "Run setup\install.ps1 first ($pythonw not found)." }

$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = [Environment]::GetFolderPath("Programs")

$shell = New-Object -ComObject WScript.Shell
$items = @(
    @{ Name = "Jarvis HUD";      Script = "hud\jarvis_hud.pyw"; Args = "" },
    @{ Name = "Stop Jarvis HUD"; Script = "hud\jarvis_hud.pyw"; Args = " stop" },
    @{ Name = "Jarvis";          Script = "app\jarvis_app.pyw"; Args = "" },
    @{ Name = "Stop Jarvis";     Script = "app\jarvis_app.pyw"; Args = " stop" }
)
foreach ($dir in @($desktop, $startMenu)) {
    foreach ($it in $items) {
        $script = Join-Path $root $it.Script
        $lnk = $shell.CreateShortcut((Join-Path $dir "$($it.Name).lnk"))
        $lnk.TargetPath = $pythonw
        $lnk.Arguments = "`"$script`"$($it.Args)"
        $lnk.WorkingDirectory = Split-Path -Parent $script
        $lnk.IconLocation = "$icon,0"
        $lnk.Save()
    }
}
Write-Output "Shortcuts created on the Desktop and in the Start Menu."
