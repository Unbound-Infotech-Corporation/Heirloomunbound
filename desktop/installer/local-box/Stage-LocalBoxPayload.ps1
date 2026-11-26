#Requires -Version 5.1
# Stage what the local-box install needs into desktop\dist\local-box-app:
#   backend\ (no tests), web\ (React build, same-origin API), voice\server.py (Chatterbox).
# Run by Build-HeirloomUnbound-Setup.bat before Inno Setup compiles.
[CmdletBinding()]
param(
  [string]$Repo = "",
  [string]$Out = "",
  [string]$PrebuiltWeb = ""
)
$ErrorActionPreference = "Stop"
if (-not $Repo) { $Repo = (Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..\..\..")).Path }
if (-not $Out) { $Out = Join-Path $Repo "desktop\dist\local-box-app" }
New-Item -ItemType Directory -Force -Path $Out | Out-Null

& robocopy.exe (Join-Path $Repo "backend") (Join-Path $Out "backend") /MIR /NFL /NDL /NJH /NJS /NP `
  /XD __pycache__ tests companion_desktop .pytest_cache /XF *.pyc .env | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copying backend failed" }

$web = Join-Path $Out "web"
if ($PrebuiltWeb) {
  & robocopy.exe $PrebuiltWeb $web /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
} else {
  Push-Location (Join-Path $Repo "frontend")
  try {
    $env:REACT_APP_BACKEND_URL = ""
    $env:CI = "false"
    $env:GENERATE_SOURCEMAP = "false"
    & corepack.cmd enable 2>$null
    & yarn.cmd install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw "yarn install failed" }
    & yarn.cmd build
    if ($LASTEXITCODE -ne 0) { throw "yarn build failed" }
  } finally { Pop-Location }
  & robocopy.exe (Join-Path $Repo "frontend\build") $web /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
}
if (-not (Test-Path (Join-Path $web "index.html"))) { throw "The web build has no index.html" }

New-Item -ItemType Directory -Force -Path (Join-Path $Out "voice") | Out-Null
Copy-Item -Force (Join-Path $Repo "box\chatterbox\server.py") (Join-Path $Out "voice\server.py")
Write-Host "Staged local-box payload in $Out"
