param(
    [Parameter(Mandatory=$true)][int]$GuiProcessId,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$candidateRoot = Split-Path -Parent $PSScriptRoot
$probePath = Join-Path $candidateRoot 'tools\diagnostics\native_crash_probe.exe'
if (-not (Test-Path -LiteralPath $probePath -PathType Leaf)) { throw "Missing diagnostic helper: $probePath" }
$guiProcess = Get-Process -Id $GuiProcessId
$resolvedOutput = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null
@{
    pid = $GuiProcessId
    executable = $guiProcess.Path
    started = $guiProcess.StartTime.ToUniversalTime().ToString('o')
    local_private_dump = $true
    instructions = 'Attach to the actual GUI PID in diagnostic session, not the launcher. Stop with Ctrl+C to detach. Dumps are not included in support ZIPs.'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $resolvedOutput 'target.json') -Encoding utf8
& $probePath $GuiProcessId $resolvedOutput
exit $LASTEXITCODE
