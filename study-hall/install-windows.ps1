#Requires -Version 5.1
# Install Heirloom Study Hall into a folder on this PC.
# Default: G:\HeirloomStudyHall
# Does not request administrator rights, does not start UAC, and does not download models.
param(
    [string]$Destination = "G:\HeirloomStudyHall"
)

$ErrorActionPreference = "Stop"
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = [System.IO.Path]::GetFullPath($Destination)

function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @{ Exe = $py.Source; Args = @("-3") } }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @{ Exe = $python.Source; Args = @() } }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Output "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ and run this script again."
    exit 1
}

New-Item -ItemType Directory -Force -Path $dest | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dest "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dest "ollama-models") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dest "data\knowledge") | Out-Null

$same = $false
try {
    $same = ([System.IO.Path]::GetFullPath($source) -eq $dest)
} catch {
    $same = $false
}

if (-not $same) {
    $exclude = @(".venv", "data", "__pycache__", ".pytest_cache")
    Get-ChildItem -Path $source -Force | Where-Object { $exclude -notcontains $_.Name } | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination (Join-Path $dest $_.Name) -Recurse -Force
    }
}

$config = @{
    ollama = @(
        @{ name = "study"; url = "http://127.0.0.1:11435" },
        @{ name = "main"; url = "http://127.0.0.1:11434" }
    )
    local_servers = @()
    cloud = @()
    min_interval = 1.5
    embed_models = @("mxbai-embed-large", "nomic-embed-text")
    panel = @{
        readers = @(
            @{ model = "phi4:14b"; host = "study" },
            @{ model = "mistral-small3.2:24b"; host = "study" },
            @{ model = "gemma3:27b"; host = "study" }
        )
        moderator = @{ model = "llama3.1:8b"; host = "study" }
        moderator_fallbacks = @(
            @{ model = "qwen3:8b"; host = "main" }
        )
    }
}
$configPath = Join-Path $dest "config.json"
if (-not (Test-Path $configPath)) {
    $config | ConvertTo-Json -Depth 6 | Set-Content -Path $configPath -Encoding UTF8
}

$venv = Join-Path $dest ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    & $python.Exe @($python.Args + @("-m", "venv", $venv))
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
}
$venvPython = Join-Path $venv "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $dest "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install Study Hall." }

Write-Output ""
Write-Output "Installed to $dest"
Write-Output "Open the room:  $dest\Start-StudyHall.ps1"
Write-Output "Study Ollama:   $dest\Start-DedicatedOllama.ps1"
Write-Output "Models folder:  $dest\ollama-models"
Write-Output "Then run Start-StudyHall.ps1. It opens http://127.0.0.1 on port 8788, or the next free port."
Write-Output "The twin reads filed lessons from $dest\data\knowledge\approved.json"
if ($dest -ne "G:\HeirloomStudyHall") {
    Write-Output "This folder is not G:\HeirloomStudyHall. Set HEIRLOOM_STUDY_HALL to $dest\data so the twin can find filed lessons."
}
