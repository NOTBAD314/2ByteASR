[CmdletBinding()]
param(
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$')]
    [string]$Version = "0.1.0-dev",
    [ValidatePattern('^[0-9A-Fa-f]{40}$')]
    [string]$SignThumbprint = "",
    [ValidatePattern('^https://')]
    [string]$TimestampUrl = "https://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$InstallerScript = Join-Path $ProjectRoot "installer\2ByteASR.iss"
$versionMetadata = Join-Path $ProjectRoot "2byteasr_version.json"
[ordered]@{
    version = $Version
    repository = "NOTBAD314/2ByteASR"
    channel = "stable"
} | ConvertTo-Json | Set-Content -LiteralPath $versionMetadata -Encoding UTF8

& (Join-Path $PSScriptRoot "build_launcher.ps1")
# Setup 内置工具链（tools/）：git/ffmpeg/python 安装器/uv —— 首次配置零工具下载
& (Join-Path $PSScriptRoot "collect_tools.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "内置工具收集失败（退出码 $LASTEXITCODE）。"
}

# 只把运行所需的第三方源码放入安装包，排除本机 Git 元数据、测试缓存和
# editable-install 生成物。原目录保持不变，净化仅发生在 tmp 暂存区。
$thirdPartySource = Join-Path $ProjectRoot "third_party"
$thirdPartyStaging = Join-Path $ProjectRoot "tmp\installer-third-party"
$projectPrefix = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') + '\'
if (-not [IO.Path]::GetFullPath($thirdPartyStaging).StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "第三方源码暂存区超出项目目录：$thirdPartyStaging"
}
Remove-Item $thirdPartyStaging -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $thirdPartySource) {
    Copy-Item $thirdPartySource $thirdPartyStaging -Recurse -Force
    $stagingPrefix = [IO.Path]::GetFullPath($thirdPartyStaging).TrimEnd('\') + '\'
    $junkDirectories = Get-ChildItem $thirdPartyStaging -Recurse -Directory -Force |
        Where-Object { $_.Name -in @(".git", "__pycache__", "tests") -or $_.Name -like "*.egg-info" } |
        Sort-Object { $_.FullName.Length } -Descending
    foreach ($directory in $junkDirectories) {
        $resolved = [IO.Path]::GetFullPath($directory.FullName)
        if (-not $resolved.StartsWith($stagingPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "拒绝清理暂存区之外的目录：$resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    Get-ChildItem $thirdPartyStaging -Recurse -File -Force |
        Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
        Remove-Item -Force
}

$compilerCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$compiler = $compilerCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $compiler) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { $compiler = $command.Source }
}
if (-not $compiler) {
    throw "Inno Setup 6 was not found. Run: winget install --id JRSoftware.InnoSetup -e"
}

New-Item -ItemType Directory -Path (Join-Path $ProjectRoot "dist") -Force | Out-Null
# Inno Setup otherwise prints one line for every bundled wheel/tool file.  The
# quiet-progress mode keeps CI/Codex logs usable while still reporting warnings,
# errors and the final compiler result.
$compilerArguments = @("/Qp", "/DMyAppVersion=$Version")
if ($SignThumbprint) {
    $signTool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if (-not $signTool) {
        throw "signtool.exe was not found. Install the Windows SDK before signing."
    }
    $signCommand = ('"{0}" sign /sha1 {1} /fd SHA256 /tr {2} /td SHA256 /d $q2ByteASR$q $f' -f $signTool.Source, $SignThumbprint, $TimestampUrl)
    $compilerArguments += "/S2ByteASRSign=$signCommand"
    $compilerArguments += "/DMySignTool=2ByteASRSign"
}
$compilerArguments += $InstallerScript
& $compiler @compilerArguments
if ($LASTEXITCODE -ne 0) {
    throw "Installer build failed (ISCC exit code $LASTEXITCODE)."
}

$output = Join-Path $ProjectRoot "dist\2ByteASR-Setup-$Version.exe"
if (-not (Test-Path -LiteralPath $output)) {
    throw "Installer output is missing: $output"
}
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $output).Hash
$checksumPath = "$output.sha256"
"$($hash.ToLowerInvariant())  $([IO.Path]::GetFileName($output))" | Set-Content -Encoding ascii $checksumPath
if ($SignThumbprint) {
    & $signTool.Source verify /pa /all $output
    if ($LASTEXITCODE -ne 0) { throw "Installer signature verification failed." }
}
Write-Host "[OK] $output" -ForegroundColor Green
Write-Host "SHA256 $hash"
Write-Host "[OK] $checksumPath" -ForegroundColor Green

# 每次构建安装包都刷新整个 dist 产物清单，避免只由便携包构建更新而长期陈旧。
$manifestPath = Join-Path $ProjectRoot "dist\RELEASE-MANIFEST.txt"
$rows = foreach ($artifact in @(Get-ChildItem (Join-Path $ProjectRoot "dist") -File |
        Where-Object { $_.Extension -in @(".7z", ".zip", ".exe") } | Sort-Object Name)) {
    $sizeMb = [math]::Round($artifact.Length / 1MB, 0)
    $artifactHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact.FullName).Hash.ToLowerInvariant()
    "{0}`t{1} MB`t{2}" -f $artifact.Name, $sizeMb, $artifactHash
}
@(
    "2ByteASR 发布产物清单（由构建脚本生成，勿手改）",
    "生成时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm')",
    "",
    "文件名`t大小`tSHA256",
    $rows
) | Set-Content -Encoding UTF8 $manifestPath
Write-Host "[OK] $manifestPath" -ForegroundColor Green
Remove-Item $thirdPartyStaging -Recurse -Force -ErrorAction SilentlyContinue
