[CmdletBinding()]
param(
    [string]$OutputDir = "",
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$')]
    [string]$Version = "",
    [switch]$RefreshWheels,
    [switch]$Lite
)

# 打包便携版 2ByteASR：程序文件 + models/（模型）+ third_party/（固定版本源码）
# + tools/（git/ffmpeg/python/uv 安装器）+ wheels/（Python 依赖，离线安装）。
# 解压到任意目录即可作为完整程序使用（首次运行 setup_2byteasr.bat 安装 Python 环境）。
# 适合国内网络下载模型困难的环境：一次性下载，解压即用。
#
# -Lite：精简版（用于 GitHub Releases，<2GB）——不含模型，只带程序 + 源码 + 内置工具；
# 首次配置时模型自动下载（约 7 GB 默认 / 11.7 GB 含 Qwen，可断点续传）。
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts/build_offline_bundle.ps1 -Version 0.1.15 [-Lite]
# 产物：dist/2ByteASR-Portable-<版本>.7z（完整版，约 10-12 GB）
#       或 dist/2ByteASR-Lite-<版本>.7z（精简版，约 1 GB；需要 7-Zip）

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputDir) { $OutputDir = Join-Path $ProjectRoot "dist" }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$versionPath = Join-Path $ProjectRoot "2byteasr_version.json"
if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) {
    throw "缺少版本元数据：$versionPath"
}
$metadataVersion = (Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8 | ConvertFrom-Json).version
$lockPath = Join-Path $ProjectRoot "dependencies.lock.json"
if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
    throw "缺少依赖版本清单：$lockPath"
}
$dependencyLock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json
$torchCpuVersion = [string]$dependencyLock.runtime.torch
$audioCpuVersion = [string]$dependencyLock.runtime.torchaudio
$setuptoolsVersion = [string]$dependencyLock.runtime.setuptools
$wheelVersion = [string]$dependencyLock.runtime.wheel
if (-not $Version) { $Version = $metadataVersion }
if ($Version -ne $metadataVersion) {
    throw "请求打包版本 $Version 与项目版本 $metadataVersion 不一致。请先构建对应版本安装包。"
}

$models = Join-Path $ProjectRoot "models"
$thirdParty = Join-Path $ProjectRoot "third_party"
foreach ($required in @((Join-Path $thirdParty "MOSS-Transcribe-Diarize"), (Join-Path $thirdParty "FireRedASR2S"))) {
    if (-not (Test-Path $required)) {
        throw "缺少打包内容：$required（请先运行 setup_environment.bat）"
    }
}
if (-not $Lite -and -not (Test-Path $models)) {
    throw "缺少打包内容：$models（请先运行 download_models.bat）"
}

# 校验模型完整性（与 download_models.bat -VerifyOnly 相同口径）；精简版不含模型
if (-not $Lite) {
    & (Join-Path $PSScriptRoot "download_models.ps1") -VerifyOnly
    if ($LASTEXITCODE -ne 0) {
        throw "模型完整性校验未通过，请先修复模型再打包。"
    }
}

$sevenZipPath = ""
$sevenZipCommand = Get-Command 7z -ErrorAction SilentlyContinue
if ($sevenZipCommand) { $sevenZipPath = $sevenZipCommand.Source }
if (-not $sevenZipPath -and $env:SEVENZIP_PATH) {
    if (Test-Path $env:SEVENZIP_PATH) { $sevenZipPath = $env:SEVENZIP_PATH }
}
if (-not $sevenZipPath) {
    foreach ($candidate in @("C:\Program Files\7-Zip\7z.exe", "C:\Program Files (x86)\7-Zip\7z.exe")) {
        if (Test-Path $candidate) { $sevenZipPath = $candidate; break }
    }
}
if (-not $sevenZipPath) {
    throw "未找到 7-Zip。请安装（winget install 7zip.7zip）或设置 SEVENZIP_PATH 后重试。"
}

# 组装便携目录：程序文件（排除运行环境/缓存/产物）+ models + third_party
$staging = Join-Path $OutputDir "staging-2byteasr"
Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $staging -Force | Out-Null

$excludeDirs = @(
    ".venv-main", ".venv-moss", ".venv", ".uv-python", ".uv-cache",
    "tmp", "dist", "backups", "archive", "outputs", "output", "reports",
    "review_tracks", "artifacts", "tests", "__pycache__", ".pytest_cache", ".git",
    ".github", ".mimosa", ".zcode", "models", "third_party", "design-qa.md", "pytest.ini",
    "2byteasr.setup-complete", "2byteasr.first-run-done"
)
Get-ChildItem $ProjectRoot -Force | Where-Object { $_.Name -notin $excludeDirs } |
    ForEach-Object { Copy-Item $_.FullName (Join-Path $staging $_.Name) -Recurse -Force }
if (-not $Lite) {
    Copy-Item $models (Join-Path $staging "models") -Recurse -Force
}
Copy-Item $thirdParty (Join-Path $staging "third_party") -Recurse -Force
$stagedThirdParty = Join-Path $staging "third_party"
$stagingPrefix = [IO.Path]::GetFullPath($staging).TrimEnd('\') + '\'
$junkDirectories = Get-ChildItem $stagedThirdParty -Recurse -Directory -Force |
    Where-Object { $_.Name -in @(".git", "__pycache__", "tests") -or $_.Name -like "*.egg-info" } |
    Sort-Object { $_.FullName.Length } -Descending
foreach ($directory in $junkDirectories) {
    $resolved = [IO.Path]::GetFullPath($directory.FullName)
    if (-not $resolved.StartsWith($stagingPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝清理便携包暂存区之外的目录：$resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
Get-ChildItem $stagedThirdParty -Recurse -File -Force |
    Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
    Remove-Item -Force
Write-Host "[打包] 便携目录已组装：$staging" -ForegroundColor Cyan


function Invoke-Download {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile
    )
    if ((Test-Path -LiteralPath $OutFile -PathType Leaf) -and
        (Get-Item -LiteralPath $OutFile).Length -gt 50KB) {
        return
    }
    # 部分站点（download.pytorch.org）会拒绝 PowerShell 默认 UA，先试
    # Invoke-WebRequest，失败改用 curl 回退；多次尝试以对抗网络抖动。
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 300 `
                -UserAgent "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" -ErrorAction Stop
            if ((Get-Item $OutFile).Length -gt 50KB) { return }
            Write-Warning "文件不完整（$Url），重试..."
        } catch {
            Write-Warning "下载失败（$Url）：$($_.Exception.Message)，改用 curl ..."
        }
        if (-not ((Test-Path $OutFile) -and (Get-Item $OutFile).Length -gt 50KB)) {
            Remove-Item $OutFile -Force -ErrorAction SilentlyContinue
            & curl.exe -L --fail --silent --show-error `
                -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" -o $OutFile $Url
            if ($LASTEXITCODE -eq 0 -and (Test-Path $OutFile) -and (Get-Item $OutFile).Length -gt 50KB) {
                return
            }
            Write-Warning "curl 下载失败（$Url），重试（$attempt/3）..."
        }
        Start-Sleep -Seconds 5
    }
    throw "下载失败：$Url"
}

# 收集内置工具（tools/）：ffmpeg、minGit、Python 安装器、uv —— 便携包免联网安装依赖。
# 复用独立收集脚本（与 Setup 安装包共用），项目根 tools/ 为共享缓存。
$projectTools = Join-Path $ProjectRoot "tools"
& (Join-Path $PSScriptRoot "collect_tools.ps1") -ToolsDir $projectTools
if ($LASTEXITCODE -ne 0) {
    throw "内置工具收集失败（退出码 $LASTEXITCODE）。"
}
Copy-Item $projectTools (Join-Path $staging "tools") -Recurse -Force
Write-Host "[工具] 已复制到便携目录：$staging\tools" -ForegroundColor Green

# 思源黑体 Heavy（SIL OFL 开源）：随包分发保证所有机器字体一致；
# 同时放进项目 assets/fonts 供本机开发预览使用。
$fontDir = Join-Path $staging "assets\fonts"
New-Item -ItemType Directory -Path $fontDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ProjectRoot "assets\fonts") -Force | Out-Null
$fontLocal = Join-Path $ProjectRoot "assets\fonts\SourceHanSansSC-Heavy.otf"
$fontStaged = Join-Path $fontDir "SourceHanSansSC-Heavy.otf"
$fontLicenseLocal = Join-Path $ProjectRoot "assets\fonts\LICENSE.txt"
$fontLicenseStaged = Join-Path $fontDir "LICENSE.txt"
if (-not (Test-Path $fontLocal)) {
    Write-Host "[字体] 下载思源黑体 Heavy ..." -ForegroundColor Cyan
    Invoke-Download "https://github.com/adobe-fonts/source-han-sans/raw/release/OTF/SimplifiedChinese/SourceHanSansSC-Heavy.otf" $fontLocal
}
Copy-Item $fontLocal $fontStaged -Force
if (-not (Test-Path $fontLicenseLocal)) {
    Write-Host "[字体] 下载思源黑体许可证 ..." -ForegroundColor Cyan
    Invoke-Download "https://raw.githubusercontent.com/adobe-fonts/source-han-sans/release/LICENSE.txt" $fontLicenseLocal
}
Copy-Item $fontLicenseLocal $fontLicenseStaged -Force
Write-Host "[字体] 思源黑体 Heavy 已就绪：$fontStaged" -ForegroundColor Green

# 依赖 wheel 集（wheels/）：首次配置时离线安装 Python 依赖，无需联网下载。
# 版本来源：本地两个 venv（python -m venv 自带 pip）的精确冻结列表；
# 剔除 torch 家族（离线装 CPU 版，GPU 机器安装后由 setup 自动升级 CUDA 版）。
$WheelsDir = Join-Path $staging "wheels"
if ($RefreshWheels -and (Test-Path -LiteralPath $WheelsDir -PathType Container)) {
    # staging 由本脚本在 dist 下创建；刷新时必须先移除旧版本轮子，避免同一
    # 包名的多个 torch 版本一起进入发布包，造成体积膨胀和离线解析歧义。
    Remove-Item -LiteralPath $WheelsDir -Recurse -Force
}
New-Item -ItemType Directory -Path $WheelsDir -Force | Out-Null
$projectWheels = Join-Path $ProjectRoot "wheels"
$projectWheelBytes = 0
if (Test-Path -LiteralPath $projectWheels -PathType Container) {
    $projectWheelBytes = (Get-ChildItem -LiteralPath $projectWheels -File | Measure-Object Length -Sum).Sum
}
if (-not $RefreshWheels -and $projectWheelBytes -gt 100MB) {
    Write-Host "[依赖] 复用项目已验证 wheels/：$([math]::Round($projectWheelBytes / 1MB)) MB（完全离线）" -ForegroundColor Green
} else {
# 冻结清单等中间文件放系统临时目录
$tmpDownload = Join-Path $env:TEMP "2byteasr-bundle"
New-Item -ItemType Directory -Path $tmpDownload -Force | Out-Null
$uvExe = (Get-Command uv).Source
$wheelSpecs = @(
    @{ Label = "主流程(3.10)"; Py = Join-Path $ProjectRoot ".venv-main\Scripts\python.exe" },
    @{ Label = "MOSS(3.12)"; Py = Join-Path $ProjectRoot ".venv-moss\Scripts\python.exe" }
)
foreach ($spec in $wheelSpecs) {
    if (-not (Test-Path $spec.Py)) {
        throw "缺少本地环境 $($spec.Label)（$($spec.Py)），无法收集依赖 wheel。请先运行 setup_environment.bat。"
    }
    Write-Host "[依赖] 冻结 $($spec.Label) 版本清单 ..." -ForegroundColor Cyan
    $freezeFile = Join-Path $tmpDownload "freeze-$($spec.Label).txt"
    # uv 会向 stderr 打印解释器提示，PS 5.1 在 EAP=Stop 下会把它当 NativeCommandError，
    # 调用期间临时降级为 Continue 并丢弃 stderr。
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $freezeLines = & $uvExe pip freeze --python $spec.Py 2>$null
    $ErrorActionPreference = $previousEap
    $freezeLines |
        Where-Object {
            $_ -and $_ -notmatch '^(torch|torchaudio|torchvision|nvidia-|pip==|setuptools==|wheel==)' `
                -and $_ -notmatch '^-e '
        } |
        Set-Content $freezeFile -Encoding ascii
    if ((Get-Item $freezeFile).Length -lt 50) {
        throw "冻结 $($spec.Label) 版本清单为空，请先运行 setup_environment.bat。"
    }
    Write-Host "[依赖] 下载 $($spec.Label) 依赖 wheel（本地 pip 缓存命中，无需网络）..." -ForegroundColor Cyan
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    # uv 创建的 venv 可能不带 pip；ensurepip 离线补装
    & $spec.Py -m ensurepip --upgrade --default-pip 2>$null | Out-Null
    # MOSS 以可编辑方式从源码安装（setuptools 构建后端）；离线构建隔离环境
    # 需要 setuptools/wheel 在 wheels/ 里，否则报 “failed to build moss”。
    & $spec.Py -m pip download "pip==26.1.2" "setuptools==$setuptoolsVersion" "wheel==$wheelVersion" --no-deps -d $WheelsDir --quiet --disable-pip-version-check
    # 不用 --only-binary：jieba / sox 等包在 PyPI 只有 sdist（pip download 只下载归档、
    # 不构建）；保留 setuptools/wheel 以便离线安装时构建这些 sdist。
    & $spec.Py -m pip download -r $freezeFile --no-deps `
        -d $WheelsDir --quiet --disable-pip-version-check
    $pipExit = $LASTEXITCODE
    $ErrorActionPreference = $previousEap
    if ($pipExit -ne 0) {
        throw "pip download 失败（$($spec.Label)，退出码 $pipExit）。"
    }
}
# CPU torch / torchaudio（cp310 + cp312），离线安装用；GPU 机器安装后自动升级 CUDA 版。
# 注意：PyTorch 索引对路径中的字面 '+' 返回 403，必须用 %2B 编码。
foreach ($tag in @("cp310", "cp312")) {
    foreach ($pkg in @("torch-$torchCpuVersion%2Bcpu", "torchaudio-$audioCpuVersion%2Bcpu")) {
        $url = "https://download.pytorch.org/whl/cpu/$pkg-$tag-$tag-win_amd64.whl"
        $out = Join-Path $WheelsDir ($pkg.Replace("%2B", "+") + "-$tag-$tag-win_amd64.whl")
        Invoke-Download $url $out
    }
}
}
if ($RefreshWheels) {
    # 将经过全量重建的 wheel 集回写项目缓存，后续 Setup/Portable/Lite 共用
    # 同一份已验证依赖，不再复活旧的 torch 轮子。
    if (Test-Path -LiteralPath $projectWheels -PathType Container) {
        Remove-Item -LiteralPath $projectWheels -Recurse -Force
    }
    Copy-Item -LiteralPath $WheelsDir -Destination $projectWheels -Recurse -Force
    Write-Host "[依赖] 已刷新项目 wheels/ 缓存：$projectWheels" -ForegroundColor Green
}
$wheelBytes = (Get-ChildItem $WheelsDir -File | Measure-Object Length -Sum).Sum
Write-Host "[依赖] wheels/ 就绪：$([math]::Round($wheelBytes / 1MB)) MB（首次配置零依赖下载）" -ForegroundColor Green

$baseName = if ($Lite) { "2ByteASR-Lite" } else { "2ByteASR-Portable" }
$output = Join-Path $OutputDir "$baseName-$Version.7z"
Remove-Item $output -Force -ErrorAction SilentlyContinue
# 精简版受 GitHub 2GB 单文件限制：超限时自动剔除 wheels/（依赖退回联网安装）
if ($Lite) {
    $stagingBytes = (Get-ChildItem $staging -Recurse -File | Measure-Object Length -Sum).Sum
    if ($stagingBytes -gt 1.9GB) {
        Remove-Item $WheelsDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Warning "精简版打包内容超过 1.9GB，已剔除 wheels/（Python 依赖将联网安装）。"
    }
}
$label = if ($Lite) { "精简版（不含模型，约 1.2 GB）" } else { "完整版（约 9-12 GB）" }
Write-Host "[打包] 正在压缩（$label，可能需要一段时间）..." -ForegroundColor Cyan
$logOut = Join-Path $OutputDir "portable-bundle.log"
$logErr = Join-Path $OutputDir "portable-bundle.err.log"
$zipArgs = @("a", "-t7z", "-mx=1", "-mmt=on", $output, (Join-Path $staging "*"))
$previousEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $sevenZipPath @zipArgs 1> $logOut 2> $logErr
$zipExit = $LASTEXITCODE
$ErrorActionPreference = $previousEap
if ($zipExit -ne 0) {
    $tail = ""
    if (Test-Path $logErr) { $tail = "`n" + ((Get-Content $logErr -Tail 10) -join "`n") }
    throw "7-Zip 打包失败（退出码 $zipExit）。$tail"
}
Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $logOut, $logErr -Force -ErrorAction SilentlyContinue

Write-Host "[OK] 便携包已生成：$output" -ForegroundColor Green
$outputHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $output).Hash.ToLowerInvariant()
$checksumPath = "$output.sha256"
"$outputHash  $([IO.Path]::GetFileName($output))" | Set-Content -Encoding ascii $checksumPath
Write-Host "SHA256 $outputHash"
Write-Host "[OK] 校验文件：$checksumPath" -ForegroundColor Green
if ($Lite) {
    Write-Host "用法：解压到任意目录，双击 setup_2byteasr.bat —— 内置 git/ffmpeg/python/uv 无需联网安装，模型会自动下载（约 7 GB，可续传）。" -ForegroundColor Yellow
} else {
    Write-Host "用法：解压到任意目录（如 D:\2ByteASR），双击 setup_2byteasr.bat 完成环境配置后即可使用。" -ForegroundColor Yellow
}

# 汇总产物清单（README/发布说明的数字以它为准，避免人工维护失真）
$manifestPath = Join-Path $OutputDir "RELEASE-MANIFEST.txt"
$rows = @()
foreach ($artifact in @(Get-ChildItem $OutputDir -File | Where-Object { $_.Extension -in @(".7z", ".zip", ".exe") } | Sort-Object Name)) {
    $sizeMb = [math]::Round($artifact.Length / 1MB, 0)
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact.FullName).Hash.ToLowerInvariant()
    $rows += "{0}`t{1} MB`t{2}" -f $artifact.Name, $sizeMb, $hash
}
@(
    "2ByteASR 发布产物清单（由构建脚本生成，勿手改）",
    "生成时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm')",
    "",
    "文件名`t大小`tSHA256",
    $rows
) | Set-Content -Encoding UTF8 $manifestPath
Write-Host "[OK] 产物清单：$manifestPath" -ForegroundColor Green
