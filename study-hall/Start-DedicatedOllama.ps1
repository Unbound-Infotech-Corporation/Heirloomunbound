#Requires -Version 5.1
# Start the Study Hall Ollama on port 11435. Leaves the main Ollama on 11434 alone.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$models = Join-Path $root "ollama-models"
New-Item -ItemType Directory -Force -Path $models | Out-Null

$up = $false
try {
    $probe = New-Object System.Net.Sockets.TcpClient
    $probe.Connect("127.0.0.1", 11435)
    $probe.Close()
    $up = $true
} catch {
    $up = $false
}
if ($up) {
    Write-Output "Dedicated Ollama is already answering on 127.0.0.1:11435."
    exit 0
}

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Output "Ollama is not on PATH. Install it from https://ollama.com and run this script again."
    Write-Output "Models directory: $models"
    exit 1
}

$env:OLLAMA_HOST = "127.0.0.1:11435"
$env:OLLAMA_MODELS = $models
Write-Output "Starting Ollama on 127.0.0.1:11435"
Write-Output "Models: $models"
& ollama serve
