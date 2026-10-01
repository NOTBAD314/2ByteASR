[CmdletBinding()]
param(
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$')]
    [string]$Version = ""
)

# 生成 hotfix 覆盖包：已发布便携包的用户解压覆盖即可获得修复，
# 无需重新下载 1GB/10GB 整包。文件清单随版本维护，此处即唯一真源。
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts/build_hotfix.ps1 -Version 0.1.15
# 产物：dist/2ByteASR-Update-<版本>.zip + .sha256

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$OutputDir = Join-Path $ProjectRoot "dist"
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$versionPath = Join-Path $ProjectRoot "2byteasr_version.json"
if (-not $Version) {
    if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) {
        throw "未指定 -Version，且缺少 2byteasr_version.json。"
    }
    $Version = (Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8 | ConvertFrom-Json).version
}
if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "无效版本号：$Version"
}
$output = Join-Path $OutputDir "2ByteASR-Update-$Version.zip"

# 覆盖包文件清单：只放修复/演进所需的最小集合。
# 原则：不包含 models/、.venv*、tools/ 等大件（wheels/ 只放构建
# sdist 必需的 setuptools/wheel 两个小包，版本从 lock 动态推导）；
# 新增修复文件时在这里登记，并同步更新 README 的 hotfix 说明。
$lockPath = Join-Path $ProjectRoot "dependencies.lock.json"
if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
    throw "缺少依赖版本清单：$lockPath"
}
$dependencyLock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json
$setuptoolsVersion = [string]$dependencyLock.runtime.setuptools
$wheelVersion = [string]$dependencyLock.runtime.wheel
if (-not $setuptoolsVersion -or -not $wheelVersion) {
    throw "dependencies.lock.json 缺少 runtime.setuptools / runtime.wheel 版本。"
}
$files = @(
    "2ByteASR.exe",
    "2ByteASR-Configure.exe",
    "2byteasr_version.json",
    "apply_hotfix.bat",
    "dependencies.lock.json",
    "CHANGELOG.md",
    "README.md",
    "TERMINOLOGY.md",
    "auto_asr.py",
    "quick_start.py",
    "subtitle_core.py",
    "setup_2byteasr.bat",
    "clean_models.bat",
    "scripts\bootstrap_install.ps1",
    "scripts\setup_environment.ps1",
    "scripts\environment-lock.ps1",
    "scripts\repair_environment.ps1",
    "scripts\download_models.ps1",
    "scripts\download_file_fast.py",
    "scripts\install_shortcut.ps1",
    "scripts\apply_update.ps1",
    "scripts\ShortcutIdentity.exe",
    "scripts\prepare_offline_dependencies.ps1",
    "wheels\setuptools-$setuptoolsVersion-py3-none-any.whl",
    "wheels\wheel-$wheelVersion-py3-none-any.whl",
    "moss_firered_pipeline.py",
    "twobyteasr\environment.py",
    "twobyteasr\environment_probe.py",
    "twobyteasr\environment_repair.py",
    "twobyteasr\download_sources.py",
    "twobyteasr\hardware.py",
    "twobyteasr\asr.py",
    "twobyteasr\grouping.py",
    "twobyteasr\llm_config.py",
    "twobyteasr\service.py",
    "twobyteasr\output.py",
    "twobyteasr\ui.py",
    "twobyteasr\model_workshop.py",
    "twobyteasr\typography.py",
    "twobyteasr\smart_glossary.py",
    "twobyteasr\updater.py",
    "twobyteasr\i18n.py",
    "twobyteasr\settings.py",
    "twobyteasr\model_integrity.py",
    "twobyteasr\segmentation.py",
    "twobyteasr\pipeline_runtime.py",
    "assets\ui-chevron-down.png",
    "assets\2byteasr-icon-transparent.png"
)

# 需要删除的旧文件（避免新代码与旧残留冲突）；按版本登记。
# 例：@("setup_moss_firered.bat")
$deleteFiles = @(
    "wheels\setuptools-83.0.0-py3-none-any.whl",
    "wheels\setuptools-84.0.0-py3-none-any.whl",
    "wheels\torch-2.13.0+cpu-cp310-cp310-win_amd64.whl",
    "wheels\torch-2.13.0+cpu-cp312-cp312-win_amd64.whl"
)

$missing = @($files | Where-Object { -not (Test-Path (Join-Path $ProjectRoot $_)) })
if ($missing.Count -gt 0) {
    throw "hotfix 清单中的文件缺失：$($missing -join ', ')"
}

# HOTFIX.json：apply_hotfix.bat 按它做覆盖与删除；也是版本追溯依据
$hotfixManifest = Join-Path $env:TEMP "HOTFIX.json"
[ordered]@{
    schema_version = 1
    version = $Version
    built_at = (Get-Date).ToString("o")
    files = $files
    delete = $deleteFiles
} | ConvertTo-Json -Depth 3 | Set-Content -Encoding UTF8 $hotfixManifest

$sevenZipPath = ""
$sevenZipCommand = Get-Command 7z -ErrorAction SilentlyContinue
if ($sevenZipCommand) { $sevenZipPath = $sevenZipCommand.Source }
if (-not $sevenZipPath -and $env:SEVENZIP_PATH -and (Test-Path $env:SEVENZIP_PATH)) {
    $sevenZipPath = $env:SEVENZIP_PATH
}
if (-not $sevenZipPath) {
    foreach ($candidate in @("C:\Program Files\7-Zip\7z.exe", "C:\Program Files (x86)\7-Zip\7z.exe")) {
        if (Test-Path $candidate) { $sevenZipPath = $candidate; break }
    }
}
if (-not $sevenZipPath) {
    throw "未找到 7-Zip（winget install 7zip.7zip）或设置 SEVENZIP_PATH。"
}

Remove-Item $output -Force -ErrorAction SilentlyContinue
# 先打包内容（含 HOTFIX.json 清单），再把清单加入 zip
$zipArgs = @("a", "-tzip", $output) + $files
& $sevenZipPath @zipArgs | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "hotfix 打包失败（退出码 $LASTEXITCODE）。"
}
& $sevenZipPath a -tzip $output $hotfixManifest | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "hotfix 清单写入失败（退出码 $LASTEXITCODE）。"
}

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $output).Hash
$checksumPath = "$output.sha256"
"$($hash.ToLowerInvariant())  $([IO.Path]::GetFileName($output))" | Set-Content -Encoding ascii $checksumPath
Write-Host "[OK] $output" -ForegroundColor Green
Write-Host "SHA256 $hash"
Write-Host "用法：解压后覆盖到便携版根目录即可（文件清单见本脚本头部）。" -ForegroundColor Yellow

# hotfix 会覆盖同日文件；同步刷新发布清单，避免清单保留旧包的哈希。
$manifestPath = Join-Path $OutputDir "RELEASE-MANIFEST.txt"
$rows = foreach ($artifact in @(Get-ChildItem $OutputDir -File |
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
