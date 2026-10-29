$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $sourceRoot '..\..\..'))
$pythonWindow = Join-Path $workspaceRoot '.venv-main\Scripts\pythonw.exe'
if (!(Test-Path -LiteralPath $pythonWindow)) { throw 'The local .venv-main development runtime is required.' }
$demoRoot = Join-Path $sourceRoot 'tmp\interactive-caption-demo'
New-Item -ItemType Directory -Path $demoRoot -Force | Out-Null
$demo = Join-Path $demoRoot 'demo.2byteproj'
if (!(Test-Path -LiteralPath $demo)) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'tmp\delivery-1000\fixture-0.2byteproj') -Destination $demo
}
$env:TWOBYTEASR_TEST_ROOT = $demoRoot
$env:TWOBYTEASR_STARTUP_PROJECT = $demo
$env:TWOBYTEASR_SKIP_FIRST_RUN_WIZARD = '1'
$env:PYTHONUTF8 = '1'
Remove-Item Env:TWOBYTEASR_ACCEPTANCE_SCENARIO -ErrorAction SilentlyContinue
Remove-Item Env:TWOBYTEASR_ACCEPTANCE_DIR -ErrorAction SilentlyContinue
Start-Process -FilePath $pythonWindow -WorkingDirectory $sourceRoot -WindowStyle Hidden -ArgumentList @('-X','utf8','quick_start.py')
