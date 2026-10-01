[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SourcePath = Join-Path $ProjectRoot "launcher\2ByteASRLauncher.cs"
$ConfigureSourcePath = Join-Path $ProjectRoot "launcher\2ByteASRConfigure.cs"
$ShortcutSourcePath = Join-Path $ProjectRoot "launcher\ShortcutIdentity.cs"
$IconPath = Join-Path $ProjectRoot "assets\app_icon.ico"  # face-cropped Taskbar/EXE icon (80-90% face)
$OutputPath = Join-Path $ProjectRoot "2ByteASR.exe"
$ConfigureOutputPath = Join-Path $ProjectRoot "2ByteASR-Configure.exe"
$ShortcutToolPath = Join-Path $PSScriptRoot "ShortcutIdentity.exe"
$CompilerCandidates = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
)
$Compiler = $CompilerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $Compiler) {
    throw "Windows .NET Framework C# compiler was not found."
}
if (-not (Test-Path -LiteralPath $SourcePath)) {
    throw "Launcher source is missing: $SourcePath"
}
if (-not (Test-Path -LiteralPath $ShortcutSourcePath)) {
    throw "Shortcut identity source is missing: $ShortcutSourcePath"
}
if (-not (Test-Path -LiteralPath $ConfigureSourcePath)) {
    throw "Configurator source is missing: $ConfigureSourcePath"
}
if (-not (Test-Path -LiteralPath $IconPath)) {
    throw "Application icon is missing: $IconPath"
}

& $Compiler /nologo /target:winexe /optimize+ "/win32icon:$IconPath" `
    /codepage:65001 /reference:System.Windows.Forms.dll "/out:$OutputPath" $SourcePath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputPath)) {
    throw "Failed to build 2ByteASR.exe."
}

& $Compiler /nologo /target:winexe /optimize+ "/win32icon:$IconPath" `
    /codepage:65001 /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    "/out:$ConfigureOutputPath" $ConfigureSourcePath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ConfigureOutputPath)) {
    throw "Failed to build 2ByteASR-Configure.exe."
}

& $Compiler /nologo /target:exe /optimize+ /codepage:65001 "/out:$ShortcutToolPath" $ShortcutSourcePath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ShortcutToolPath)) {
    throw "Failed to build the shortcut identity helper."
}

Write-Host "[OK] Built taskbar launcher with the custom icon: $OutputPath" -ForegroundColor Green
Write-Host "[OK] Built graphical setup and retry window: $ConfigureOutputPath" -ForegroundColor Green
