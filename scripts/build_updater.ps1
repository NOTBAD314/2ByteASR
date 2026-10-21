# SPDX-License-Identifier: GPL-3.0-only
# Compile the component updater helper with the Windows .NET Framework C#
# compiler (the same tool chain as the launcher).  Output path is explicit so a
# release build never writes into the daily program folder.
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$Output)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $projectRoot "launcher\2ByteASRUpdater.cs"
$icon = Join-Path $projectRoot "assets\app_icon.ico"
$compiler = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $compiler) { throw "Windows .NET Framework C# compiler was not found." }
$target = [IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
& $compiler /nologo /target:winexe /optimize+ "/win32icon:$icon" /codepage:65001 `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll `
    "/out:$target" $source
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $target)) { throw "Failed to build the updater helper." }
Write-Host "Updater: $target"
