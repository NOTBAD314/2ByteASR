[CmdletBinding()]
param(
    [switch]$DryRun
)
# 2026-11-19 (user: the daily should rebuild the outer launcher too). Daily promotions only replace
# dist\2ByteASR, so the root 2ByteASR.exe stayed the October build and never drew the startup
# skeleton (launcher\LaunchCover.cs). Run this before a daily is promoted:
#   - the launcher sources unchanged since the last refresh: nothing happens ("current");
#   - otherwise the launcher is built into tmp\root-launcher\<time>\, checked, the old root launcher
#     is kept beside it, and the new one replaces the root 2ByteASR.exe.
# The result is one JSON line (status, old/new SHA-256) to record as the daily's launcher_sha256.
# It refuses while the root launcher is running.

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RootLauncher = Join-Path $ProjectRoot "2ByteASR.exe"
$StageRoot = Join-Path $ProjectRoot "tmp\root-launcher"
$StampPath = Join-Path $StageRoot "stamp.json"
$Sources = @("launcher\2ByteASRLauncher.cs", "launcher\LaunchCover.cs", "assets\app_icon.ico")

function Get-Sha([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-SourceSha {
    $parts = foreach ($relative in $Sources) {
        $path = Join-Path $ProjectRoot $relative
        if (-not (Test-Path -LiteralPath $path)) { throw "Launcher source is missing: $path" }
        "$relative=$(Get-Sha $path)"
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($parts -join "`n"))
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return (($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join "") } finally { $sha.Dispose() }
}

function Write-Result([hashtable]$Result) {
    $Result | ConvertTo-Json -Compress
}

$sourceSha = Get-SourceSha
$oldSha = Get-Sha $RootLauncher
$stamp = $null
if (Test-Path -LiteralPath $StampPath) {
    try { $stamp = Get-Content -LiteralPath $StampPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $stamp = $null }
}
if ($stamp -and $stamp.source_sha256 -eq $sourceSha -and $stamp.launcher_sha256 -eq $oldSha -and $oldSha) {
    Write-Result @{ status = "current"; launcher_sha256 = $oldSha; source_sha256 = $sourceSha }
    return
}
if ($DryRun) {
    Write-Result @{ status = "would_rebuild"; launcher_sha256 = $oldSha; source_sha256 = $sourceSha }
    return
}

$running = Get-CimInstance Win32_Process -Filter "Name = '2ByteASR.exe'" |
    Where-Object { $_.ExecutablePath -and ([System.IO.Path]::GetFullPath($_.ExecutablePath) -ieq [System.IO.Path]::GetFullPath($RootLauncher)) }
if ($running) {
    throw "The root launcher is running (PID $(@($running.ProcessId) -join ', ')). Close 2ByteASR first."
}

$stage = Join-Path $StageRoot (Get-Date -Format "yyyyMMdd-HHmmss")
New-Item -ItemType Directory -Force -Path $stage | Out-Null
& (Join-Path $PSScriptRoot "build_launcher.ps1") -OutputDirectory $stage -LauncherOnly 6>$null | Out-Null
$built = Join-Path $stage "2ByteASR.exe"
if (-not (Test-Path -LiteralPath $built)) { throw "The launcher was not built: $built" }
# The new launcher must carry the startup skeleton (its handoff event name).
$marker = [System.Text.Encoding]::Unicode.GetBytes("2ByteASR-launch-cover-")
$content = [System.IO.File]::ReadAllBytes($built)
$text = [System.BitConverter]::ToString($content)
if (-not $text.Contains([System.BitConverter]::ToString($marker))) {
    throw "The built launcher has no startup skeleton: $built"
}

$backup = ""
if ($oldSha) {
    $backup = Join-Path $stage "previous-2ByteASR.exe"
    Copy-Item -LiteralPath $RootLauncher -Destination $backup -Force
}
Copy-Item -LiteralPath $built -Destination $RootLauncher -Force
$newSha = Get-Sha $RootLauncher
if ($newSha -ne (Get-Sha $built)) {
    if ($backup) { Copy-Item -LiteralPath $backup -Destination $RootLauncher -Force }
    throw "The root launcher could not be replaced; the previous one was put back."
}
@{ source_sha256 = $sourceSha; launcher_sha256 = $newSha; built = $stage; at = (Get-Date).ToString("o") } |
    ConvertTo-Json | Set-Content -LiteralPath $StampPath -Encoding UTF8
Write-Result @{ status = "rebuilt"; previous_sha256 = $oldSha; launcher_sha256 = $newSha; source_sha256 = $sourceSha; backup = $backup }
