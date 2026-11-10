#Requires -Version 5.1
# Open Heirloom Study Hall on this PC. Does not touch the main Ollama.
param([switch]$Hidden)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$data = Join-Path $root "data"
New-Item -ItemType Directory -Force -Path $data | Out-Null
$env:STUDYHALL_DATA = $data
$env:HEIRLOOM_STUDY_HALL = $data
$env:STUDYHALL_HOST = "127.0.0.1"
Remove-Item Env:STUDYHALL_PORT -ErrorAction SilentlyContinue
$listen = Join-Path $data "listen.url"
if (Test-Path $listen) { Remove-Item $listen -Force }
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$style = "Hidden"
if (-not $Hidden) { $style = "Minimized" }
Start-Process -FilePath $python -ArgumentList (Join-Path $root "run.py") -WorkingDirectory $root -WindowStyle $style | Out-Null
$deadline = (Get-Date).AddSeconds(25)
while (-not (Test-Path $listen) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 200
}
if (-not (Test-Path $listen)) {
    Write-Output "Study Hall did not report a port. Look in the data folder and try again."
    exit 1
}
$url = (Get-Content -Path $listen -Raw).Trim()
Write-Output "Study Hall: $url"
if (-not $Hidden) {
    Start-Process $url | Out-Null
}
