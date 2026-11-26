#Requires -Version 5.1
# Start Heirloom on this PC: database, Ollama (if needed), voice (if installed), the API + web app.
# Safe to run twice: anything already running is left alone.
[CmdletBinding()]
param(
  [string]$InstallDir = "",
  [switch]$NoBrowser
)
# $PSScriptRoot is empty inside param() defaults on Windows PowerShell 5.1.
if (-not $InstallDir) { $InstallDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ErrorActionPreference = "Stop"
$Data = Join-Path $InstallDir "data"
$envFile = Join-Path $Data "heirloom.env"
if (-not (Test-Path $envFile)) { throw "Heirloom is not set up in $InstallDir. Run Heirloom Setup first." }
$cfg = @{}
Get-Content $envFile | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; $cfg[$k] = $v }
$Logs = Join-Path $Data "logs"
$Pids = Join-Path $Data "pids"
New-Item -ItemType Directory -Force -Path $Logs, $Pids | Out-Null

function Listening([int]$port) { [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) }
function Remember([string]$name, $proc) { Set-Content -Path (Join-Path $Pids "$name.pid") -Value $proc.Id }

# Database: loopback only, data under the install folder.
$mongoPort = [int]$cfg["HEIRLOOM_MONGO_PORT"]
if (-not (Listening $mongoPort)) {
  $mongod = Join-Path $InstallDir "tools\mongodb\bin\mongod.exe"
  $p = Start-Process -PassThru -WindowStyle Hidden -FilePath $mongod -ArgumentList @(
    "--dbpath", "`"$(Join-Path $Data 'mongo')`"", "--bind_ip", "127.0.0.1", "--port", $mongoPort,
    "--logpath", "`"$(Join-Path $Logs 'mongod.log')`"", "--logappend")
  Remember "mongod" $p
  for ($i = 0; $i -lt 30 -and -not (Listening $mongoPort); $i++) { Start-Sleep 1 }
}

# Ollama: reuse a running one; otherwise start the per-user install.
$ollama = $cfg["OLLAMA_BASE_URL"]
try { Invoke-RestMethod "$ollama/api/version" -TimeoutSec 3 | Out-Null } catch {
  $exe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
  if (Test-Path $exe) {
    $env:OLLAMA_CONTEXT_LENGTH = $cfg["OLLAMA_CONTEXT_LENGTH"]
    Start-Process -WindowStyle Hidden -FilePath $exe -ArgumentList "serve" | Out-Null
    Start-Sleep 3
  }
}

# Voice (optional): Chatterbox on 127.0.0.1:8010.
$voicePy = Join-Path $InstallDir "voice\Scripts\python.exe"
# Voice weights (~3 GB) stay in the data folder, not the user's global Hugging Face cache.
if ($cfg["HF_HOME"]) { $env:HF_HOME = $cfg["HF_HOME"] }
if ($cfg["HEIRLOOM_VOICE"] -eq "1" -and (Test-Path $voicePy) -and -not (Listening 8010)) {
  $p = Start-Process -PassThru -WindowStyle Hidden -WorkingDirectory (Join-Path $InstallDir "voice") -FilePath $voicePy `
    -ArgumentList "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8010" `
    -RedirectStandardOutput (Join-Path $Logs "voice.out.log") -RedirectStandardError (Join-Path $Logs "voice.err.log")
  Remember "voice" $p
}

# Heirloom API + web app.
$apiPort = [int]$cfg["HEIRLOOM_API_PORT"]
if (-not (Listening $apiPort)) {
  $py = Join-Path $InstallDir "venv\Scripts\python.exe"
  $p = Start-Process -PassThru -WindowStyle Hidden -WorkingDirectory (Join-Path $InstallDir "app\backend") -FilePath $py `
    -ArgumentList "-m", "local_box", "serve", "--data", "`"$Data`"" `
    -RedirectStandardOutput (Join-Path $Logs "api.out.log") -RedirectStandardError (Join-Path $Logs "api.err.log")
  Remember "api" $p
  for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-RestMethod "http://127.0.0.1:$apiPort/api/health" -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep 1 }
  }
}
Write-Host "Heirloom: http://127.0.0.1:$apiPort/"
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$apiPort/" }
