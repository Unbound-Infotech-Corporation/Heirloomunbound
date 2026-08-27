# Deny agent shells that would steal focus or start Heirloom.
# Fail open: any parse error allows the command.
$ErrorActionPreference = "Stop"
try {
    $raw = [Console]::In.ReadToEnd()
    $j = $raw | ConvertFrom-Json
    $cmd = ""
    if ($null -ne $j.command) { $cmd = [string]$j.command }
    elseif ($null -ne $j.tool_input -and $null -ne $j.tool_input.command) { $cmd = [string]$j.tool_input.command }

    $deny = $false
    if ($cmd -match '(?i)dotnet\s+run\b[\s\S]*Heirloom\.csproj') { $deny = $true }
    if ($cmd -match '(?i)(Start-Process|\bstart\b\s+"")[\s\S]*Heirloom') { $deny = $true }
    if ($cmd -match '(?i)(^|[;&|]\s*)(\.\\|\./|&\s*)Heirloom\.exe') { $deny = $true }
    if ($cmd -match '(?i)\b(explorer\.exe|MessageBox|msg\.exe)\b') { $deny = $true }

    if ($deny) {
        Write-Output '{"permission":"deny","agent_message":"Do not launch Heirloom, Explorer, or dialogs unless the owner asked. Build or publish to desktop/dist/Heirloom-ready instead.","user_message":"Blocked a launch/focus-steal command. Publish to Heirloom-ready; do not start the app unless you ask."}'
        exit 0
    }

    Write-Output '{"permission":"allow"}'
    exit 0
}
catch {
    Write-Output '{"permission":"allow"}'
    exit 0
}
