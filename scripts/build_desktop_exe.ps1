[CmdletBinding()]
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv-main\Scripts\python.exe"
$Spec = Join-Path $ProjectRoot "packaging\2byteasr_main.spec"
$DistRoot = Join-Path $ProjectRoot "dist"
$Output = Join-Path $DistRoot "2ByteASR"
$WorkRoot = Join-Path $ProjectRoot "build\pyinstaller-main"
$BuildMetadata = Join-Path $ProjectRoot "build\2byteasr_build.json"
$BuildIdentityScript = Join-Path $ProjectRoot "twobyteasr\build_identity.py"
$ProjectPrefix = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') + '\'

foreach ($path in @($Output, $WorkRoot)) {
    $resolved = [IO.Path]::GetFullPath($path)
    if (-not $resolved.StartsWith($ProjectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Build target is outside the project root: $resolved"
    }
    if ((Test-Path -LiteralPath $resolved) -and -not $Clean) {
        throw "Build target already exists; rerun with -Clean: $resolved"
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Main Python environment is missing: $Python"
}
if (-not (Test-Path -LiteralPath $Spec)) {
    throw "PyInstaller spec is missing: $Spec"
}
if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) {
    throw "Node.js is required so the release can bundle the fidelity renderer runtime."
}

if ($Clean) {
    foreach ($path in @($Output, $WorkRoot)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}

New-Item -ItemType Directory -Path $DistRoot -Force | Out-Null
& $Python $BuildIdentityScript --root $ProjectRoot --write $BuildMetadata
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $BuildMetadata)) {
    throw "Build identity generation failed with exit code $LASTEXITCODE."
}
$env:TWOBYTEASR_BUILD_METADATA = $BuildMetadata
try {
    & $Python -m PyInstaller `
        --noconfirm `
        --distpath $DistRoot `
        --workpath $WorkRoot `
        $Spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE."
    }
} finally {
    Remove-Item Env:TWOBYTEASR_BUILD_METADATA -ErrorAction SilentlyContinue
}

$Exe = Join-Path $Output "2ByteASR.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    throw "Packaged executable is missing: $Exe"
}
$PackagedBuildMetadata = Join-Path $Output "2byteasr_build.json"
if (-not (Test-Path -LiteralPath $PackagedBuildMetadata)) {
    throw "Packaged build identity is missing: $PackagedBuildMetadata"
}
$BuildIdentity = Get-Content -LiteralPath $PackagedBuildMetadata -Raw -Encoding UTF8 | ConvertFrom-Json
$Version = (Get-Item -LiteralPath $Exe).VersionInfo
$SizeMb = [math]::Round(
    (Get-ChildItem -LiteralPath $Output -Recurse -File | Measure-Object Length -Sum).Sum / 1MB,
    1
)
Write-Host "[OK] $Exe" -ForegroundColor Green
Write-Host "[OK] Product=$($Version.ProductName) Description=$($Version.FileDescription) Size=${SizeMb}MB" -ForegroundColor Green
Write-Host "[OK] Git=$($BuildIdentity.git_sha) Dirty=$($BuildIdentity.git_dirty) Built=$($BuildIdentity.build_time)" -ForegroundColor Green
Write-Host "[OK] SourceSHA256=$($BuildIdentity.source_sha256) Files=$($BuildIdentity.source_file_count)" -ForegroundColor Green
