#Requires -Version 5.1
# Open Heirloom Study Hall on this PC. Does not touch the main Ollama.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$data = Join-Path $root "data"
New-Item -ItemType Directory -Force -Path $data | Out-Null
$env:STUDYHALL_DATA = $data
$env:HEIRLOOM_STUDY_HALL = $data
$env:STUDYHALL_HOST = "127.0.0.1"
$env:STUDYHALL_PORT = "8787"
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}
Write-Output "Study Hall: http://127.0.0.1:8787"
& $python (Join-Path $root "run.py")
