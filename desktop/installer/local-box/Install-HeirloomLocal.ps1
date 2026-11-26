#Requires -Version 5.1
<#
.SYNOPSIS
  Heirloom on this PC, no Twin Box. Per-user, no admin, no WSL, no reboot.

.DESCRIPTION
  1. Hardware check (GPU, VRAM, RAM, free disk) and the model tier for this PC.
  2. Python 3.12 through uv, then the Heirloom API in its own virtual environment.
  3. MongoDB as a portable per-user database (loopback only).
  4. Ollama (reused if it is already running), the tier model, and the memory search model.
  5. Hearing (faster-whisper) and, on a big enough GPU, the Chatterbox voice.
  6. Start/Stop scripts, shortcuts, sign-in for the owner, and a final check.

  Everything stays on this PC. No cloud model is configured.

.PARAMETER InstallDir   Where Heirloom lives. Default %LOCALAPPDATA%\HeirloomUnbound.
.PARAMETER AppSource    Folder with backend\ and web\ (the installer's payload). Default: ..\app next to this script.
.PARAMETER Sandbox      Test install: no shortcuts, no autostart, no app settings, no browser, leaves other Heirloom installs alone.
#>
[CmdletBinding()]
param(
  [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "HeirloomUnbound"),
  [string]$AppSource = "",
  [int]$ApiPort = 8001,
  [int]$MongoPort = 27017,
  [string]$OllamaUrl = "http://127.0.0.1:11434",
  [string]$Model = "",
  [ValidateSet("auto", "on", "off")][string]$Voice = "auto",
  [string]$OwnerEmail = "",
  [switch]$SkipModelPull,
  [switch]$NoStart,
  [switch]$AutoStart,
  [switch]$Sandbox
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$MongoVersion = "8.0.4"
$MongoZipUrl = "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-$MongoVersion.zip"
$UvZipUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
$OllamaSetupUrl = "https://ollama.com/download/OllamaSetup.exe"
$PyIndexExtra = "https://d33sy5i8bnduwe.cloudfront.net/simple/"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $AppSource) { $AppSource = Join-Path (Split-Path -Parent $here) "app" }
$Data = Join-Path $InstallDir "data"
$Tools = Join-Path $InstallDir "tools"
$Venv = Join-Path $InstallDir "venv"
$Logs = Join-Path $Data "logs"
$LogFile = $null

function Say([string]$msg) {
  $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
  Write-Host $line
  if ($LogFile) { Add-Content -Path $LogFile -Value $line }
}

function Fail([string]$msg) {
  Say "STOPPED: $msg"
  Say "Nothing was removed. Fix the problem above and run Heirloom Setup again; it picks up where it stopped."
  exit 1
}

function Download([string]$url, [string]$dest, [string]$label) {
  if (Test-Path $dest) { Say "$label already downloaded."; return }
  Say "Downloading $label..."
  $part = "$dest.part"
  & curl.exe -L --fail --retry 3 -C - -o $part $url
  if ($LASTEXITCODE -ne 0) { Fail "Could not download $label from $url" }
  Move-Item -Force $part $dest
}

function Port-Free([int]$port) {
  -not (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}

function Free-Port([int]$want) {
  $p = $want
  while (-not (Port-Free $p)) { $p++ }
  return $p
}

function Run-Py([string[]]$argv) {
  # Output only; the caller reads $LASTEXITCODE.
  $py = Join-Path $Venv "Scripts\python.exe"
  Push-Location (Join-Path $InstallDir "app\backend")
  try { & $py @argv } finally { Pop-Location }
}

# ---------------------------------------------------------------- 0. folders and payload
New-Item -ItemType Directory -Force -Path $InstallDir, $Data, $Tools, $Logs | Out-Null
$LogFile = Join-Path $Logs ("install-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
Say "Heirloom Unbound on this PC -> $InstallDir"
if ($InstallDir -match '^[A-Za-z]:\\Heirloom(\\|$)') { Fail "C:\Heirloom belongs to the Heirloom desktop app. Pick another folder." }

foreach ($part in "backend", "web") {
  if (-not (Test-Path (Join-Path $AppSource $part))) { Fail "The installer payload is missing $part (looked in $AppSource)." }
}
# Re-run (update): stop this install's own processes first so files can be replaced,
# and keep the ports it already uses unless new ones were asked for.
$oldEnv = Join-Path $Data "heirloom.env"
if (Test-Path (Join-Path $InstallDir "Stop-Heirloom.ps1")) {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallDir "Stop-Heirloom.ps1") -InstallDir $InstallDir | Out-Null
}
if (Test-Path $oldEnv) {
  foreach ($line in Get-Content $oldEnv) {
    if (-not $PSBoundParameters.ContainsKey("ApiPort") -and $line -match '^HEIRLOOM_API_PORT=(\d+)$') { $ApiPort = [int]$Matches[1] }
    if (-not $PSBoundParameters.ContainsKey("MongoPort") -and $line -match '^HEIRLOOM_MONGO_PORT=(\d+)$') { $MongoPort = [int]$Matches[1] }
  }
}
$AppDir = Join-Path $InstallDir "app"
if ((Resolve-Path $AppSource).Path -ne (Join-Path $InstallDir "app")) {
  Say "Copying Heirloom..."
  New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
  & robocopy.exe (Join-Path $AppSource "backend") (Join-Path $AppDir "backend") /MIR /NFL /NDL /NJH /NJS /NP /XD __pycache__ tests | Out-Null
  & robocopy.exe (Join-Path $AppSource "web") (Join-Path $AppDir "web") /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
  if (Test-Path (Join-Path $AppSource "voice")) {
    & robocopy.exe (Join-Path $AppSource "voice") (Join-Path $AppDir "voice") /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
  }
}
Copy-Item -Force (Join-Path $here "*.ps1") $InstallDir

# ---------------------------------------------------------------- 1. ports
$ApiPort = Free-Port $ApiPort
$MongoPort = Free-Port $MongoPort
Say "Ports: web and API $ApiPort, database $MongoPort (loopback only)."

# ---------------------------------------------------------------- 2. Python via uv
$uv = (Get-Command uv.exe -ErrorAction SilentlyContinue).Source
if (-not $uv) {
  $uvZip = Join-Path $Tools "uv.zip"
  Download $UvZipUrl $uvZip "the Python manager (uv)"
  Expand-Archive -Force $uvZip (Join-Path $Tools "uv")
  $uv = Join-Path $Tools "uv\uv.exe"
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools "python"
$env:UV_CACHE_DIR = Join-Path $Tools "uv-cache"
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
  Say "Setting up Python 3.12..."
  & $uv python install 3.12 | Out-Null
  & $uv venv --python 3.12 $Venv
  if ($LASTEXITCODE -ne 0) { Fail "Python could not be set up." }
}
$py = Join-Path $Venv "Scripts\python.exe"

# ---------------------------------------------------------------- 3. hardware check and tier
Say "Checking this PC's hardware..."
$planArgs = @("-m", "local_box", "plan", "--data", $Data, "--voice", $Voice)
if ($Model) { $planArgs += @("--model", $Model) }
$planJson = (Run-Py $planArgs | Out-String)
if ($LASTEXITCODE -ne 0) { Fail "The hardware check did not run." }
$plan = $planJson | ConvertFrom-Json
$hw = $plan.hardware
Say ("GPU: {0} ({1} MB)  RAM: {2} MB  -> tier {3}: {4}" -f ($(if ($hw.gpu) { $hw.gpu } else { "none" })), $hw.vram_mib, $hw.ram_mib, $plan.tier, $plan.model)
Say ("Disk: {0} GB free, about {1} GB needed." -f $plan.free_gb, $plan.need_gb)
if (-not $plan.disk_ok) { Fail ("Not enough free disk space on this drive. Free up {0} GB or choose another folder." -f [math]::Ceiling($plan.need_gb - $plan.free_gb)) }

# ---------------------------------------------------------------- 4. the Heirloom API
Say "Installing the Heirloom service (a few minutes the first time)..."
$req = Join-Path $AppDir "backend\requirements.txt"
& $uv pip install --python $py --quiet --extra-index-url $PyIndexExtra -r $req
if ($LASTEXITCODE -ne 0) { Fail "The Heirloom service packages did not install." }
$whisperPkgs = @("faster-whisper==1.1.1", "av==15.1.0")
if ($plan.whisper_device -eq "cuda") { $whisperPkgs += @("nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10") }
& $uv pip install --python $py --quiet @whisperPkgs
if ($LASTEXITCODE -ne 0) { Say "Hearing packages did not install; typing still works. Setup continues." }

# ---------------------------------------------------------------- 5. database
$mongod = Join-Path $Tools "mongodb\bin\mongod.exe"
if (-not (Test-Path $mongod)) {
  $zip = Join-Path $Tools "mongodb.zip"
  Download $MongoZipUrl $zip "the database (MongoDB $MongoVersion, about 750 MB)"
  Say "Unpacking the database..."
  $tmp = Join-Path $Tools "mongodb-unpack"
  Expand-Archive -Force $zip $tmp
  $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
  New-Item -ItemType Directory -Force -Path (Join-Path $Tools "mongodb\bin") | Out-Null
  Copy-Item (Join-Path $inner.FullName "bin\mongod.exe") (Join-Path $Tools "mongodb\bin\")
  Get-ChildItem (Join-Path $inner.FullName "bin") -Filter *.dll | Copy-Item -Destination (Join-Path $Tools "mongodb\bin\")
  Remove-Item -Recurse -Force $tmp, $zip
}

# ---------------------------------------------------------------- 6. Ollama and models
function Ollama-Up { try { Invoke-RestMethod "$OllamaUrl/api/version" -TimeoutSec 3 | Out-Null; $true } catch { $false } }
if (-not (Ollama-Up)) {
  $ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
  if (-not (Test-Path $ollamaExe)) {
    $setup = Join-Path $Tools "OllamaSetup.exe"
    Download $OllamaSetupUrl $setup "the local AI runner (Ollama)"
    Say "Installing Ollama for this user..."
    Start-Process -Wait -FilePath $setup -ArgumentList "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"
  }
  if (Test-Path $ollamaExe) {
    Start-Process -WindowStyle Hidden -FilePath $ollamaExe -ArgumentList "serve"
    for ($i = 0; $i -lt 30 -and -not (Ollama-Up); $i++) { Start-Sleep 2 }
  }
  if (-not (Ollama-Up)) { Fail "Ollama did not start at $OllamaUrl." }
} else {
  Say "Ollama is already running here; Heirloom will use it."
}
$have = @((Invoke-RestMethod "$OllamaUrl/api/tags").models | ForEach-Object { $_.name })
foreach ($tag in @($plan.model, "nomic-embed-text")) {
  if ($have -contains $tag -or $have -contains "$tag`:latest") { Say "$tag is already here."; continue }
  if ($SkipModelPull) { Say "Skipping the $tag download (-SkipModelPull)."; continue }
  Say "Downloading $tag (the biggest step)..."
  & (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe") pull $tag
  if ($LASTEXITCODE -ne 0) {
    $body = @{ model = $tag; stream = $false } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri "$OllamaUrl/api/pull" -Body $body -ContentType "application/json" -TimeoutSec 7200 | Out-Null
  }
}

# ---------------------------------------------------------------- 7. voice
if ($plan.voice) {
  $voiceVenv = Join-Path $InstallDir "voice"
  if (-not (Test-Path (Join-Path $voiceVenv "Scripts\python.exe"))) {
    Say "Installing the voice (Chatterbox, MIT; about 5 GB)..."
    & $uv venv --python 3.11 $voiceVenv
    $vpy = Join-Path $voiceVenv "Scripts\python.exe"
    # RTX 50xx (Blackwell, compute 12.x) needs CUDA 12.8 wheels; older cards use the box's pinned torch 2.6 / cu124.
    $cc = 0.0
    try { $cc = [double](((& nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null) | Select-Object -First 1).Trim()) } catch { $cc = 0.0 }
    $torchVer = "2.6.0"; $cuda = "cu124"
    if ($cc -ge 12.0) { $torchVer = "2.7.1"; $cuda = "cu128" }
    $torchIndex = "https://download.pytorch.org/whl/$cuda"
    $overrides = Join-Path $voiceVenv "overrides.txt"
    Set-Content -Path $overrides -Value @("torch==$torchVer", "torchaudio==$torchVer") -Encoding ASCII
    & $uv pip install --python $vpy --quiet "torch==$torchVer" "torchaudio==$torchVer" --index-url $torchIndex
    # setuptools<81 keeps pkg_resources, which librosa 0.10 still imports.
    & $uv pip install --python $vpy --quiet --override $overrides "chatterbox-tts==0.1.1" "setuptools<81" fastapi "uvicorn[standard]" --extra-index-url $torchIndex
    if ($LASTEXITCODE -ne 0) { Say "The voice did not install. Heirloom still works by text; run Setup again to retry." }
  }
  $voiceSrc = Join-Path $AppDir "voice\server.py"
  if (Test-Path $voiceSrc) { Copy-Item -Force $voiceSrc (Join-Path $voiceVenv "server.py") }
} else {
  Say "Voice: this PC's tier keeps the graphics card for thinking. Text and hearing are installed; voice can be added later."
}

# ---------------------------------------------------------------- 8. configuration and owner
$initArgs = @("-m", "local_box", "init", "--data", $Data, "--web", (Join-Path $AppDir "web"),
  "--api-port", $ApiPort, "--mongo-port", $MongoPort, "--ollama", $OllamaUrl, "--voice", $Voice, "--model", $plan.model)
Run-Py $initArgs | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "Settings could not be written." }
Say "Settings written to $Data\heirloom.env (local models only)."
Say "Hearing: fetching the speech model..."
Run-Py @("-c", "import os,local_box;local_box.load_env(__import__('pathlib').Path(r'$Data'));from faster_whisper import WhisperModel;WhisperModel('base',device='cpu',compute_type='int8',download_root=os.environ['WHISPER_CACHE'])") | Out-Null

$ownerFile = Join-Path $Data "owner\owner.pass"
if (-not (Test-Path $ownerFile) -or -not (Select-String -Path $ownerFile -Pattern '^hash=' -Quiet)) {
  if ($OwnerEmail -and $env:HEIRLOOM_SETUP_PASSWORD) {
    # Passed through the environment, never on a command line or a pipe (a pipe adds a BOM on PowerShell 5.1).
    & $py (Join-Path $AppDir "backend\local_box.py") set-owner --data $Data --email $OwnerEmail --password-env
    Remove-Item Env:\HEIRLOOM_SETUP_PASSWORD -ErrorAction SilentlyContinue
  } elseif (-not $Sandbox) {
    Say "Choose the owner sign-in. Only you will use it."
    if (-not $OwnerEmail) { $OwnerEmail = Read-Host "Your email" }
    Push-Location (Join-Path $AppDir "backend")
    & $py -m local_box set-owner --data $Data --email $OwnerEmail
    Pop-Location
  } else {
    Say "Owner sign-in not set (sandbox). Set it later: Set-HeirloomOwner.ps1"
  }
}

# ---------------------------------------------------------------- 9. shortcuts
if (-not $Sandbox) {
  $shell = New-Object -ComObject WScript.Shell
  $target = "powershell.exe"
  $lnkArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$InstallDir\Start-Heirloom.ps1`""
  foreach ($where in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
    $lnk = $shell.CreateShortcut((Join-Path $where "Heirloom.lnk"))
    $lnk.TargetPath = $target; $lnk.Arguments = $lnkArgs; $lnk.WorkingDirectory = $InstallDir
    $lnk.Description = "Heirloom Unbound on this PC"; $lnk.Save()
  }
  if ($AutoStart) {
    $lnk = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Startup")) "Heirloom.lnk"))
    $lnk.TargetPath = $target; $lnk.Arguments = "$lnkArgs -NoBrowser"; $lnk.WorkingDirectory = $InstallDir; $lnk.Save()
  }
}

# ---------------------------------------------------------------- 10. start and check
if (-not $NoStart) {
  # Its own hidden process: the long-running database/voice/API must not inherit this window's
  # output handles, or anything capturing Setup's output would wait until Heirloom stops.
  $startArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$(Join-Path $InstallDir 'Start-Heirloom.ps1')`"", "-InstallDir", "`"$InstallDir`"")
  if ($Sandbox) { $startArgs += "-NoBrowser" }
  # Not -Wait: on PowerShell 5.1 that also waits for the processes Start-Heirloom leaves running.
  $starter = Start-Process -FilePath "powershell.exe" -ArgumentList $startArgs -WindowStyle Hidden -PassThru
  $starter.WaitForExit()
  Push-Location (Join-Path $AppDir "backend")
  $check = (& $py -m local_box check --data $Data --chat --wait 90 | Out-String)
  $code = $LASTEXITCODE
  Pop-Location
  Add-Content -Path $LogFile -Value $check
  Write-Host $check
  if ($code -ne 0) { Say "Heirloom started, but a check did not pass (see above). Setup logs: $Logs" }
  else { Say "Heirloom is ready at http://127.0.0.1:$ApiPort/" }
}
Say "Done."
