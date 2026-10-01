# Swap in the staged build (2026-09-03 recall-quality round).
# Usage: fully exit 2ByteASR first (check tray / task manager for 2ByteASR.exe),
# then from the repo root run:
#   powershell -ExecutionPolicy Bypass -File scripts\swap_staged_build.ps1
# NOTE: keep this script ASCII-only. Windows PowerShell 5.x reads .ps1 files as
# the system ANSI codepage unless they carry a UTF-8 BOM, which turned the
# previous Chinese-comment version into mojibake parse errors.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Staging = Join-Path $Root "dist-staging/2ByteASR"
$Target = Join-Path $Root "dist/2ByteASR"

if (Get-Process 2ByteASR -ErrorAction SilentlyContinue) {
    throw "2ByteASR is still running. Exit it completely (including tray) before swapping."
}
if (-not (Test-Path -LiteralPath $Staging)) {
    throw "Staged build not found: $Staging"
}
if (Test-Path -LiteralPath $Target) {
    Remove-Item -LiteralPath $Target -Recurse -Force
}
Move-Item -LiteralPath $Staging -Destination $Target
Remove-Item -LiteralPath (Join-Path $Root "dist-staging") -Force -ErrorAction SilentlyContinue
Write-Host "Swapped staged build into: $Target"
