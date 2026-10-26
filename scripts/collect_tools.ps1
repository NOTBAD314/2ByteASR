[CmdletBinding()]
param([string]$ToolsDir = "")

# 收集内置工具（tools/）：ffmpeg、mpv（及其 Vulkan 运行库兜底）、minGit、Python 安装器、uv —— 离线安装依赖。
# 便携包构建与 Setup 安装包共用；目标目录已就绪时跳过（下载一次多包复用）。
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts/collect_tools.ps1 [-ToolsDir <dir>]
# 默认输出：项目根 tools/（Setup 与便携包共享的本地缓存）

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ToolsDir) { $ToolsDir = Join-Path $ProjectRoot "tools" }

$ExpectedHashes = @{
    "uv.exe" = "68a22cbab1674647bcda32120b214e6480f875414e3333f49f87ae99b4b0e0fa"
    "python-3.10.11-amd64.exe" = "d8dede5005564b408ba50317108b765ed9c3c510342a598f9fd42681cbe0648b"
    "python-3.12.10-amd64.exe" = "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"
    "mpv-x86_64-20260814-git-7b8915bc1d.7z" = "1bf3b029da2c98e605e00e85f21ee3142f22a1dcc4ceb5c827b5c51e36e390f9"
    "VulkanRT-X64-1.4.363.0-Components.zip" = "a25a927aa8b9f0371048f1861cf88ac3b9bc9b1fb332c42d897c8ab32695769a"
    "vulkan-1.dll" = "e1fcfc9489beefa6a6d9d11d6c7517f6a2b7f16e0d3fb8f4103bee0210f314a3"
}

function Assert-ExpectedHash {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $expected = $ExpectedHashes[$Name]
    if (-not $expected) { throw "没有为内置工具配置 SHA-256：$Name" }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "内置工具校验失败：$Name`n期望 SHA-256：$expected`n实际 SHA-256：$actual`n请删除损坏文件后重新构建。"
    }
}


function Invoke-Download {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile
    )
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


function Install-MpvTool {
    param([Parameter(Mandatory = $true)][string]$DownloadRoot)
    $mpvTarget = Join-Path $ToolsDir "mpv\mpv.exe"
    if (Test-Path -LiteralPath $mpvTarget) { return }

    $archiveName = "mpv-x86_64-20260814-git-7b8915bc1d.7z"
    $archive = Join-Path $DownloadRoot $archiveName
    $extractRoot = Join-Path $DownloadRoot "mpv-extract"
    Write-Host "[工具] 下载 mpv / libass 预览运行时 ..." -ForegroundColor Cyan
    # 上游 shinchiro/mpv-winbuild-cmake 只保留最近 30 个发布，20260814 原地址已失效（404）。
    # 同一个原包（未改动，SHA-256 相同）存档在本项目 v0.6.5 发布及 GitCode 镜像；逐个镜像校验。
    $mpvDownloaded = $false
    foreach ($mpvUrl in @(
        "https://github.com/NOTBAD314/2ByteASR/releases/download/v0.6.5/$archiveName",
        "https://gitcode.com/Notbad314/2ByteASR/releases/download/v0.6.5/$archiveName",
        "https://gh-proxy.com/https://github.com/NOTBAD314/2ByteASR/releases/download/v0.6.5/$archiveName"
    )) {
        try {
            Invoke-Download $mpvUrl $archive
            Assert-ExpectedHash $archive $archiveName
            $mpvDownloaded = $true
            break
        } catch {
            Write-Warning "mpv 下载或校验失败（$mpvUrl）：$($_.Exception.Message)"
            Remove-Item $archive -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not $mpvDownloaded) { throw "mpv 下载失败：GitHub、GitCode 与代理镜像均不可用或校验不符。" }

    $extractor = $null
    foreach ($candidate in @(
        "C:\Program Files\7-Zip\7z.exe",
        "C:\Program Files (x86)\7-Zip\7z.exe"
    )) {
        if (Test-Path -LiteralPath $candidate) { $extractor = $candidate; break }
    }
    if (-not $extractor) {
        foreach ($commandName in @("7z.exe", "7zz.exe")) {
            $command = Get-Command $commandName -ErrorAction SilentlyContinue
            if ($command) { $extractor = $command.Source; break }
        }
    }
    if (-not $extractor) {
        throw "mpv 使用 7z 发布包；构建机缺少 7-Zip。请安装 7-Zip 后重新构建。"
    }
    Remove-Item $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
    & $extractor x -y "-o$extractRoot" $archive | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "mpv 7z 解包失败（退出码 $LASTEXITCODE）。" }
    $mpvExecutable = Get-ChildItem $extractRoot -Recurse -File -Filter mpv.exe | Select-Object -First 1
    if (-not $mpvExecutable) { throw "mpv 解包后未找到 mpv.exe。" }
    $mpvSource = $mpvExecutable.Directory.FullName
    New-Item -ItemType Directory -Path (Split-Path -Parent $mpvTarget) -Force | Out-Null
    Copy-Item (Join-Path $mpvSource "*") (Split-Path -Parent $mpvTarget) -Recurse -Force
    if (-not (Test-Path -LiteralPath $mpvTarget)) { throw "mpv 收集后仍缺少 mpv.exe。" }
}


# Vulkan 运行库兜底（2026-10-17）：随包 mpv 的导入表直接依赖 vulkan-1.dll，而它只随显卡驱动安装，
# 虚拟机、远程桌面和基本显示驱动的电脑没有，mpv 一启动就退出。工作台只用 D3D11，这个文件只为让
# Windows 能加载 mpv.exe。Studio 启动 mpv 时把它所在的文件夹放在 PATH 末尾，系统里有就用系统的。
# 冻结程序把 tools/vulkan-loader 装到 third_party/vulkan-loader（属于“主程序”更新元件）。
function Install-VulkanLoader {
    param([Parameter(Mandatory = $true)][string]$DownloadRoot)
    $loaderDir = Join-Path $ToolsDir "vulkan-loader"
    $loaderTarget = Join-Path $loaderDir "vulkan-1.dll"
    if (Test-Path -LiteralPath $loaderTarget) {
        Assert-ExpectedHash $loaderTarget "vulkan-1.dll"
        return
    }

    $archiveName = "VulkanRT-X64-1.4.363.0-Components.zip"
    $archive = Join-Path $DownloadRoot $archiveName
    $extractRoot = Join-Path $DownloadRoot "vulkan-extract"
    Write-Host "[工具] 下载 Vulkan 运行库（LunarG 1.4.363.0，mpv 兜底）..." -ForegroundColor Cyan
    Invoke-Download "https://sdk.lunarg.com/sdk/download/1.4.363.0/windows/$archiveName" $archive
    Assert-ExpectedHash $archive $archiveName
    Remove-Item $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive $archive $extractRoot -Force
    $package = Join-Path $extractRoot "VulkanRT-X64-1.4.363.0-Components"
    $loader = Join-Path $package "x64\vulkan-1.dll"
    if (-not (Test-Path -LiteralPath $loader)) { throw "Vulkan 运行库解压后未找到 x64\vulkan-1.dll。" }
    Assert-ExpectedHash $loader "vulkan-1.dll"
    New-Item -ItemType Directory -Path $loaderDir -Force | Out-Null
    Copy-Item $loader $loaderTarget -Force
    Copy-Item (Join-Path $package "VulkanRT-License.txt") (Join-Path $loaderDir "VulkanRT-License.txt") -Force
}


function Install-YtDlpTool {
    $lock = Get-Content -LiteralPath (Join-Path $ProjectRoot "dependencies.lock.json") -Raw | ConvertFrom-Json
    $spec = $lock.tools.yt_dlp
    $file = $spec.files.windows
    $targetDir = Join-Path $ToolsDir "yt-dlp"
    $target = Join-Path $targetDir $file.name
    if ((Test-Path -LiteralPath $target) -and
        (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -eq $file.sha256) { return }
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    $partial = Join-Path $targetDir ($file.name + ".partial")
    Invoke-Download $file.url $partial
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.sha256) {
        throw "yt-dlp 校验失败；未替换现有工具。"
    }
    Move-Item -LiteralPath $partial -Destination $target -Force
    Write-Host "[工具] yt-dlp $($spec.version)（含 EJS $($spec.ejs_version)）校验通过。"
}

Install-YtDlpTool

$coreReady = (Test-Path (Join-Path $ToolsDir "ffmpeg\bin\ffmpeg.exe")) -and
         (Test-Path (Join-Path $ToolsDir "ffmpeg\bin\ffprobe.exe")) -and
         (Test-Path (Join-Path $ToolsDir "git\cmd\git.exe")) -and
         (Test-Path (Join-Path $ToolsDir "uv.exe")) -and
         (Test-Path (Join-Path $ToolsDir "python-3.10.11-amd64.exe")) -and
         (Test-Path (Join-Path $ToolsDir "python-3.12.10-amd64.exe"))
if ($coreReady) {
    Assert-ExpectedHash (Join-Path $ToolsDir "uv.exe") "uv.exe"
    Assert-ExpectedHash (Join-Path $ToolsDir "python-3.10.11-amd64.exe") "python-3.10.11-amd64.exe"
    Assert-ExpectedHash (Join-Path $ToolsDir "python-3.12.10-amd64.exe") "python-3.12.10-amd64.exe"
    $mpvDownload = Join-Path $env:TEMP "2byteasr-tools"
    New-Item -ItemType Directory -Path $mpvDownload -Force | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $ToolsDir "mpv\mpv.exe"))) {
        Install-MpvTool $mpvDownload
    }
    Install-VulkanLoader $mpvDownload
    Remove-Item $mpvDownload -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[工具] 已就绪（含 mpv 与 Vulkan 运行库兜底）：$ToolsDir" -ForegroundColor Green
    exit 0
}

New-Item -ItemType Directory -Path $ToolsDir -Force | Out-Null
$tmpDownload = Join-Path $env:TEMP "2byteasr-tools"
New-Item -ItemType Directory -Path $tmpDownload -Force | Out-Null

# FFmpeg（gyan.dev essentials，含 ffmpeg/ffprobe）
Write-Host "[工具] 下载 FFmpeg ..." -ForegroundColor Cyan
$ffmpegZip = Join-Path $tmpDownload "ffmpeg.zip"
Invoke-Download "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" $ffmpegZip
Expand-Archive $ffmpegZip (Join-Path $tmpDownload "ffmpeg") -Force
$ffBin = Get-ChildItem (Join-Path $tmpDownload "ffmpeg") -Recurse -Directory | Where-Object { $_.Name -eq "bin" } | Select-Object -First 1
if (-not $ffBin) { throw "FFmpeg 解压后未找到 bin 目录。" }
New-Item -ItemType Directory -Path (Join-Path $ToolsDir "ffmpeg\bin") -Force | Out-Null
Copy-Item (Join-Path $ffBin.FullName "ffmpeg.exe") (Join-Path $ToolsDir "ffmpeg\bin") -Force
Copy-Item (Join-Path $ffBin.FullName "ffprobe.exe") (Join-Path $ToolsDir "ffmpeg\bin") -Force

# minGit（Git for Windows 精简便携版，含 git）；多源备援（国内代理 → GitHub 官方）
Write-Host "[工具] 下载 minGit ..." -ForegroundColor Cyan
$gitZip = Join-Path $tmpDownload "mingit.zip"
$gitDownloaded = $false
foreach ($gitUrl in @(
    "https://ghfast.top/https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.3/MinGit-2.55.0.3-64-bit.zip",
    "https://ghproxy.net/https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.3/MinGit-2.55.0.3-64-bit.zip",
    "https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.3/MinGit-2.55.0.3-64-bit.zip"
)) {
    try { Invoke-Download $gitUrl $gitZip; $gitDownloaded = $true; break } catch { Write-Warning "minGit 下载失败（$gitUrl）" }
}
if (-not $gitDownloaded) { throw "minGit 下载失败（国内网络受限）。" }
Expand-Archive $gitZip (Join-Path $ToolsDir "git") -Force
if (-not (Test-Path (Join-Path $ToolsDir "git\cmd\git.exe"))) { throw "minGit 解压后未找到 git.exe。" }

# uv；多源备援
Write-Host "[工具] 下载 uv ..." -ForegroundColor Cyan
$uvZip = Join-Path $tmpDownload "uv.zip"
$uvDownloaded = $false
foreach ($uvUrl in @(
    "https://ghfast.top/https://github.com/astral-sh/uv/releases/download/0.12.3/uv-x86_64-pc-windows-msvc.zip",
    "https://ghproxy.net/https://github.com/astral-sh/uv/releases/download/0.12.3/uv-x86_64-pc-windows-msvc.zip",
    "https://github.com/astral-sh/uv/releases/download/0.12.3/uv-x86_64-pc-windows-msvc.zip"
)) {
    try { Invoke-Download $uvUrl $uvZip; $uvDownloaded = $true; break } catch { Write-Warning "uv 下载失败（$uvUrl）" }
}
if (-not $uvDownloaded) { throw "uv 下载失败（国内网络受限）。" }
Expand-Archive $uvZip (Join-Path $tmpDownload "uv") -Force
Copy-Item (Join-Path $tmpDownload "uv\uv.exe") (Join-Path $ToolsDir "uv.exe") -Force
Assert-ExpectedHash (Join-Path $ToolsDir "uv.exe") "uv.exe"

# Python 官方安装器（3.10 / 3.12）
foreach ($py in @("3.10.11", "3.12.10")) {
    Write-Host "[工具] 下载 Python $py 安装器 ..." -ForegroundColor Cyan
    $pyInstaller = Join-Path $ToolsDir "python-$py-amd64.exe"
    $ok = $false
    foreach ($url in @(
        "https://www.python.org/ftp/python/$py/python-$py-amd64.exe",
        "https://mirrors.huaweicloud.com/python/$py/python-$py-amd64.exe"
    )) {
        try { Invoke-Download $url $pyInstaller; $ok = $true; break } catch { Write-Warning "Python $py 下载失败（$url），尝试镜像..." }
    }
    if (-not $ok) { throw "Python $py 安装器下载失败。" }
    Assert-ExpectedHash $pyInstaller "python-$py-amd64.exe"
}

Install-MpvTool $tmpDownload
Install-VulkanLoader $tmpDownload

Remove-Item $tmpDownload -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "[工具] 内置工具收集完成：$ToolsDir" -ForegroundColor Green
