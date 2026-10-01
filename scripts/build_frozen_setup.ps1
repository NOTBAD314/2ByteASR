[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PayloadDir,
    [string]$ReleaseDir = "",
    [switch]$QA
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$payload = (Resolve-Path -LiteralPath $PayloadDir).Path
if (-not $ReleaseDir) { $ReleaseDir = Join-Path $projectRoot "dist" }
$release = [IO.Path]::GetFullPath($ReleaseDir)
$version = (Get-Content -Raw -LiteralPath (Join-Path $payload "2byteasr_version.json") | ConvertFrom-Json).version
if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$') { throw "Invalid payload version" }
$identity = Get-Content -Raw -LiteralPath (Join-Path $payload "2byteasr_build.json") | ConvertFrom-Json
if ($identity.app_version -ne $version) { throw "Payload identity/version mismatch" }
foreach ($required in @("2ByteASR.exe", "python310.dll", "tools\node\node.exe", "tools\mpv\mpv.exe", "tools\ffmpeg\bin\ffmpeg.exe", "renderer\service.mjs", "LICENSE", "PROJECT_LICENSE.md", "SOURCE_DELIVERY.md", "BUILD_FROM_SOURCE.md", "THIRD_PARTY_NOTICES.md")) {
    if (-not (Test-Path -LiteralPath (Join-Path $payload $required))) { throw "Missing runtime: $required" }
}
$files = @(Get-ChildItem -LiteralPath $payload -File -Recurse -Force)
$bad = @($files | Where-Object {
    $relative = $_.FullName.Substring($payload.Length + 1)
    $relative -match '(^|[\\/])(\.git|__pycache__|\.pytest_cache|\.mimosa|tmp|logs|reports|Projects)([\\/]|$)' -or
    $_.Extension -in @('.log', '.2byteproj', '.2byteasr', '.pyc', '.pyo') -or
    $_.Name -in @('secrets.json', 'secrets.dat', '.env')
})
if ($bad.Count) { throw "Payload contains developer/user artifacts: $($bad[0].FullName)" }
$settings = Get-Content -Raw -LiteralPath (Join-Path $payload "2byteasr_settings.json") | ConvertFrom-Json
if ($settings.models.oss_bucket -or $settings.models.ai_service -or @($settings.models.provider_profiles.PSObject.Properties).Count) {
    throw "Payload must contain factory settings with no personal providers/bucket"
}
$compiler = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $compiler) { throw "Inno Setup 6 ISCC.exe not found" }
New-Item -ItemType Directory -Path $release -Force | Out-Null
$baseName = if ($QA) { "2ByteASR-QA-Setup-$version" } else { "2ByteASR-Setup-$version" }
$output = Join-Path $release "$baseName.exe"
if ($QA -and -not (Test-Path -LiteralPath (Join-Path $payload '2byteasr-qa-profile.marker'))) { throw 'QA payload marker missing; cannot share ordinary user data' }
if (Test-Path -LiteralPath $output) { throw "Output already exists: $output" }
$compilerArgs = @('/Qp')
if ($QA) { $compilerArgs += '/DQAInstall=1' }
$compilerArgs += @("/DPayloadDir=$payload", "/DReleaseDir=$release", "/DMyAppVersion=$version", (Join-Path $projectRoot 'installer\2ByteASR-frozen.iss'))
& $compiler @compilerArgs
if ($LASTEXITCODE -ne 0) { throw "ISCC failed: $LASTEXITCODE" }
$hash = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $([IO.Path]::GetFileName($output))" | Set-Content -LiteralPath "$output.sha256" -Encoding ascii
Write-Host "Setup: $output"
Write-Host "SHA256: $hash"
