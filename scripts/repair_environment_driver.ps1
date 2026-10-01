# ASCII-only driver. Invoked with -File from Python.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet("main","moss","firered_llm","nemotron")][string]$Role,
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [Parameter(Mandatory=$true)][string]$StagingPath
)
$ErrorActionPreference = "Stop"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
try { [Console]::OutputEncoding = $Utf8NoBom } catch {}
$OutputEncoding = $Utf8NoBom
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $here "repair_environment.ps1"
if (-not (Test-Path -LiteralPath $src)) { throw "Missing: $src" }
. $src
if (-not (Get-Command Install-RepairRoleStaging -ErrorAction SilentlyContinue)) {
    throw "Install-RepairRoleStaging not defined after dot-source."
}
Install-RepairRoleStaging -Role $Role -ProjectRoot $ProjectRoot -StagingPath $StagingPath
exit $LASTEXITCODE
