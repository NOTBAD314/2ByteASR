[CmdletBinding()]
param(
    [switch]$InstallPrerequisites,
    [switch]$DownloadModels,
    [switch]$CheckOnly,
    [switch]$NoLaunch,
    [switch]$NonInteractive,
    [switch]$IncludeQwen,
    [switch]$MinimalModels,
    [switch]$Repair,
    [ValidateSet("main", "moss")]
    [string[]]$RepairRole = @()
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

# 完整安装过程记录到 %TEMP%\2byteasr-setup.log，方便排查
$TranscriptPath = Join-Path $env:TEMP "2byteasr-setup.log"
Start-Transcript -Path $TranscriptPath -Append -ErrorAction SilentlyContinue | Out-Null
Write-Host "[日志] 安装过程已记录到 $TranscriptPath" -ForegroundColor DarkGray

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SetupEnvironment = Join-Path $PSScriptRoot "setup_environment.ps1"
$DownloadModelScript = Join-Path $PSScriptRoot "download_models.ps1"
$Launcher = Join-Path $ProjectRoot "2ByteASR.exe"
$SetupMarker = Join-Path $ProjectRoot "2byteasr.setup-complete"

# 安装步骤进度：标题栏 + Write-Progress 双通道，用户随时知道进度与等待时间
$script:StepIndex = 0
$script:StepTotal = if ($DownloadModels) { 3 } else { 2 }
function Set-InstallStep {
    param([string]$Label)
    $script:StepIndex++
    if ($Host.UI.RawUI) {
        $Host.UI.RawUI.WindowTitle = "2ByteASR 安装 - 步骤 $($script:StepIndex)/$($script:StepTotal)：$Label"
    }
    Write-Progress -Activity "2ByteASR 安装" -Status $Label `
        -PercentComplete ([math]::Round(100 * $script:StepIndex / $script:StepTotal))
}

# 提前询问 Qwen 复核模型：环境安装需要较长时间，不能等装完才让用户选择。
$IncludeQwenChoice = $false
if ($DownloadModels) {
    $qwenConfig = Join-Path $ProjectRoot "models\Qwen3-ASR-1.7B\config.json"
    if ($IncludeQwen -or $env:2BYTEASR_INCLUDE_QWEN -or (Test-Path $qwenConfig)) {
        $IncludeQwenChoice = $true
        if (Test-Path $qwenConfig) { Write-Host "[Qwen] 检测到 Qwen3-ASR 模型已存在。" -ForegroundColor Green }
    } elseif (-not $NonInteractive -and -not $env:2BYTEASR_NO_QWEN) {
        $answer = Read-Host "下载本地 Qwen3-ASR（约 4.7 GB；精度更高并增加独立词汇证据；不下载则使用更快的 API，需自行配置 Key）？[y/N]"
        if ($answer -match "^[yY]") { $IncludeQwenChoice = $true }
    }
    $qwenText = if ($IncludeQwenChoice) { "包含" } else { "不包含" }
    Write-Host "[选择] Qwen3-ASR 复核模型：$qwenText（可随时用 download_models.bat 补下；2BYTEASR_NO_QWEN=1 关闭提问）" -ForegroundColor Cyan
    # 按需下载：先只下基础链路（MOSS+VAD+声纹约 2 GB）还是完整（约 7 GB）？
    $MinimalChoice = $false
    if ($MinimalModels) {
        $MinimalChoice = $true
    } elseif (-not $NonInteractive -and -not $env:2BYTEASR_MINIMAL_MODELS -and -not $env:2BYTEASR_FULL_MODELS) {
        $minAnswer = Read-Host "先只下载基础模型（约 2 GB，可立即出字幕，FireRed 字级时间轴稍后补）？[y/N]"
        if ($minAnswer -match "^[yY]") { $MinimalChoice = $true }
    } elseif ($env:2BYTEASR_MINIMAL_MODELS) {
        $MinimalChoice = $true
    }
    if ($MinimalChoice) {
        Write-Host "[选择] 极简模式：先下载基础模型（约 2 GB）" -ForegroundColor Cyan
    }

    # 把安装时的模型选择同步到 GUI。未下载本地 Qwen 时默认使用便宜的
    # DashScope API；用户首次运行只需填写 Key。极简模式关闭 FireRed-AED，
    # 避免运行时要求一个明确没有下载的模型目录。
    $settingsPath = Join-Path $ProjectRoot "2byteasr_settings.json"
    if (Test-Path -LiteralPath $settingsPath) {
        try {
            $runtimeSettings = Get-Content -Raw -Encoding UTF8 $settingsPath | ConvertFrom-Json
            $runtimeSettings.models.qwen_asr_backend = if ($IncludeQwenChoice) { "local" } else { "api" }
            $runtimeSettings.models.firered_asr_backend = if ($MinimalChoice) { "off" } else { "local" }
            $settingsJson = $runtimeSettings | ConvertTo-Json -Depth 8
            [System.IO.File]::WriteAllText(
                $settingsPath,
                $settingsJson + [Environment]::NewLine,
                [System.Text.UTF8Encoding]::new($false)
            )
        } catch {
            Write-Warning "无法同步识别后端设置；可在主界面手动选择 API / 本地模型：$($_.Exception.Message)"
        }
    }
}

# 幂等退出：运行环境已完整配置时不再破坏性重装。只有显式传入
# -DownloadModels 的旧式/维护流程才把相应模型也纳入完整性判断。
$MainPy = Join-Path $ProjectRoot ".venv-main\Scripts\python.exe"
$ModelRoot = Join-Path $ProjectRoot "models"
$requiredModels = @()
if ($DownloadModels) {
    $requiredModels += @(
        "MOSS-Transcribe-Diarize\model-00000-of-00001.safetensors",
        "FireRedVAD\VAD\model.pth.tar",
        "FireRedVAD\VAD\cmvn.ark",
        "spkrec-ecapa-voxceleb\embedding_model.ckpt",
        "spkrec-ecapa-voxceleb\mean_var_norm_emb.ckpt",
        "spkrec-ecapa-voxceleb\classifier.ckpt",
        "spkrec-ecapa-voxceleb\label_encoder.txt"
    )
}
if ($DownloadModels -and -not $MinimalChoice) {
    $requiredModels += @(
        "FireRedASR2-AED\model.pth.tar",
        "FireRedASR2-AED\cmvn.ark"
    )
}
$alreadyConfigured = (Test-Path $SetupMarker) -and (Test-Path $MainPy)
if ($alreadyConfigured -and -not $Repair -and -not $env:2BYTEASR_FORCE_SETUP) {
    foreach ($rel in $requiredModels) {
        if (-not (Test-Path (Join-Path $ModelRoot $rel))) { $alreadyConfigured = $false; break }
    }
}
if ($alreadyConfigured -and -not $Repair) {
    $readyText = if ($DownloadModels) { "运行环境与所选模型均已就绪" } else { "运行环境已就绪；模型可在模型工坊按需选择" }
    Write-Host "[完成] 2ByteASR 已配置完成（$readyText），无需重装。" -ForegroundColor Green

# Hard post-check: if NVIDIA GPU is present, main environment MUST have a working CUDA torch.
# CPU-only torch on NVIDIA = installation error for 2ByteASR GPU ASR.
$gpuPresent = (Get-Command nvidia-smi -ErrorAction SilentlyContinue) -and -not $env:2BYTEASR_CPU_ONLY
if ($gpuPresent) {
    $MainPython = Join-Path $ProjectRoot ".venv-main\Scripts\python.exe"
    if (Test-Path -LiteralPath $MainPython) {
        & $MainPython -c "
import sys, torch
cuda_ok = torch.cuda.is_available() and (torch.version.cuda is not None)
if not cuda_ok:
    print('CUDA PyTorch 安装异常：检测到 NVIDIA GPU，但当前 torch 不是 CUDA 构建。')
    print('torch.__version__=', torch.__version__)
    print('torch.version.cuda=', getattr(torch.version, 'cuda', None))
    print('torch.cuda.is_available()=', torch.cuda.is_available())
    sys.exit(2)
print('CUDA torch OK for main runtime.')
" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "CUDA PyTorch 安装异常" -ForegroundColor Red
            Write-Host "检测到 NVIDIA GPU，但主运行环境安装的是 CPU 版 PyTorch。" -ForegroundColor Red
            Write-Host "这不是有效 fallback。对于 2ByteASR GPU ASR 这是安装失败状态。" -ForegroundColor Red
            Write-Host "请运行【配置或修复 2ByteASR】或手动修复 .venv-main 中的 torch/torchaudio。" -ForegroundColor Yellow
            exit 3
        }
    }
}
    Write-Host "       强制重装（会重建环境）：设置 2BYTEASR_FORCE_SETUP=1 后重跑" -ForegroundColor DarkGray
    exit 0
}

# 每次开始配置先清除完成标记：只有 venv 而无标记 = 上次配置中断，
# 2ByteASR.exe 启动器会引导“继续配置”（已下载内容续传），而不是静默失败。
# Repair Mode 必须保留 marker：修复失败时用户仍视为“已安装”，只重建损坏角色。
if (-not $Repair) {
    Remove-Item $SetupMarker -Force -ErrorAction SilentlyContinue
}

# 磁盘预检：模型（按 Qwen 选择）+ 环境/源码/缓存预留，不足直接拦截。
# （模型下载阶段还会再查一次；这里尽早拦截，避免装到一半才发现空间不够）
$modelGb = if (-not $DownloadModels) { 0 } elseif ($IncludeQwenChoice) { 11.7 } else { 7 }
$needGb = if ($DownloadModels) { [math]::Ceiling($modelGb + 3) } else { 3 }
$driveName = ([System.IO.Path]::GetPathRoot($ProjectRoot)).TrimEnd('\').TrimEnd(':')
$drive = $null
try {
    $drive = Get-PSDrive -Name $driveName
} catch {
    Write-Warning "磁盘预检失败：$($_.Exception.Message)（将继续安装，模型下载时还会再次检查）"
}
if ($drive) {
    $freeGb = [math]::Round($drive.Free / 1GB, 1)
    if ($freeGb -lt $needGb) {
        throw "磁盘空间不足：项目盘（${driveName}:）仅剩 $freeGb GB，至少需要 $needGb GB（模型 $modelGb GB + 环境预留 3 GB）。请清理空间后重试。"
    }
    $spaceLabel = if ($DownloadModels) { "本次需要约 $needGb GB" } else { "本次磁盘预留约 $needGb GB，不是额外下载量" }
    Write-Host "[检查] 磁盘空间：$freeGb GB 可用（$spaceLabel）" -ForegroundColor Cyan
}

function Add-BundledToolsToPath {
    # 便携版内置工具（tools/）优先：ffmpeg/git/uv 无需联网下载。
    # Refresh-ProcessPath 会重建整个 PATH，必须在这里一并恢复——
    # 否则便携包首次检查通过、刷新 PATH 后 tools 条目丢失，
    # 会误报“缺少系统依赖 uv, git, ffmpeg, ffprobe”。
    $tools = Join-Path $ProjectRoot "tools"
    foreach ($extra in @($tools, (Join-Path $tools "ffmpeg\bin"), (Join-Path $tools "git\cmd"), (Join-Path $tools "git\bin"))) {
        if (Test-Path $extra) { $env:Path = "$extra;$env:Path" }
    }
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $extraPaths = @(
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"),
        (Join-Path $env:LOCALAPPDATA "Programs\Git\cmd"),
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:ProgramFiles "Git\cmd")
    )
    $env:Path = (@($machinePath, $userPath) + $extraPaths | Where-Object { $_ }) -join ";"
    Add-BundledToolsToPath
}

function Get-MissingCommands {
    $missing = @()
    foreach ($name in @("uv", "git", "ffmpeg", "ffprobe", "nvidia-smi")) {
        if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
            $missing += $name
        }
    }
    return $missing
}

function Install-WinGetPackage {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][string]$Label
    )
    # 下载可能因网络瞬断失败（如 0x80072f78 超时），重试最多 3 次。
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Write-Host "[Prerequisite] Installing $Label ... (第 $attempt 次尝试)" -ForegroundColor Cyan
        if ($Label -in @("Git", "uv")) {
            Write-Host "  提示：GitHub 组件在国内网络下可能较慢，请耐心等待；失败会自动重试。" -ForegroundColor DarkYellow
        }
        & winget install --id $Id --exact --silent --disable-interactivity `
            --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { return }
        Write-Warning "$Label 安装失败（winget 退出码 $LASTEXITCODE），正在重试..."
        Start-Sleep -Seconds 5
    }
    throw "$Label installation failed (winget exit code $LASTEXITCODE).`n请手动重试：winget install --id $Id -e"
}


function Download-WithProxy {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile
    )
    # Invoke-WebRequest 遵循系统代理设置；多次尝试以对抗网络抖动。
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -ErrorAction Stop
            if (Test-Path $OutFile) { return }
        } catch {
            if ($attempt -ge 3) { throw }
            Write-Warning "下载失败（$Url），正在重试（$attempt/3）..."
            Start-Sleep -Seconds 4
        }
    }
    throw "下载失败：$Url"
}


function Install-GitDirect {
    # 国内网络下 winget 直连 GitHub 可能极慢甚至卡死；
    # 改为官方安装包直装，依次尝试国内加速代理与 GitHub 官方源（带连接超时）。
    $downloads = Join-Path $env:TEMP "2byteasr-prereq"
    New-Item -ItemType Directory -Path $downloads -Force | Out-Null
    $gitInstaller = Join-Path $downloads "git.exe"
    $sources = @(
        "https://ghfast.top/https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.3/Git-2.55.0.3-64-bit.exe",
        "https://ghproxy.net/https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.3/Git-2.55.0.3-64-bit.exe",
        "https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.3/Git-2.55.0.3-64-bit.exe"
    )
    $downloaded = $false
    foreach ($url in $sources) {
        try {
            Write-Host "[Prerequisite] 正在下载 Git（约 62 MB，国内网络可能较慢）..." -ForegroundColor Cyan
            Invoke-WebRequest -Uri $url -OutFile $gitInstaller -UseBasicParsing -TimeoutSec 300 -ErrorAction Stop
            if ((Get-Item $gitInstaller).Length -gt 10MB) { $downloaded = $true; break }
        } catch {
            Write-Warning "Git 下载失败（$url），尝试下一个源..."
        }
    }
    if (-not $downloaded) {
        throw "Git 下载失败（国内网络受限）。可手动下载 Git for Windows 安装包后重新运行 setup_2byteasr.bat。"
    }
    # 装到当前用户目录（无需管理员权限），并持久化 PATH
    $gitInstallDir = Join-Path $env:LOCALAPPDATA "Programs\Git"
    $gitLog = Join-Path $env:TEMP "git-install.log"
    Remove-Item $gitLog -Force -ErrorAction SilentlyContinue
    Write-Host "[Prerequisite] 安装 Git 到 $gitInstallDir ..." -ForegroundColor Cyan
    # 兼容两种安装器：Inno（/VERYSILENT /DIR）与 NSIS（/S /D）；
    # NSIS 的 /D= 必须是命令行最后一个参数；GUI 安装器用 & 调用时
    # PowerShell 5.1 拿不到退出码，必须用 Start-Process -Wait。
    $p = Start-Process -FilePath $gitInstaller -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/S",
        "/DIR=$gitInstallDir", "/LOG=$gitLog", "/D=$gitInstallDir"
    ) -Wait -PassThru -WindowStyle Hidden
    if ($p.ExitCode -ne 0) {
        throw "Git 安装失败（退出码 $($p.ExitCode)）。安装日志：$gitLog"
    }
    $gitCmd = ""
    foreach ($candidate in @(
        (Join-Path $gitInstallDir "cmd\git.exe"), (Join-Path $gitInstallDir "bin\git.exe"),
        (Join-Path $gitInstallDir "usr\bin\git.exe"), (Join-Path $gitInstallDir "mingw64\bin\git.exe"),
        (Join-Path $env:ProgramFiles "Git\cmd\git.exe"), (Join-Path $env:ProgramFiles "Git\usr\bin\git.exe"),
        (Join-Path $env:ProgramFiles "Git\mingw64\bin\git.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Git\cmd\git.exe")
    )) {
        if (Test-Path $candidate) { $gitCmd = $candidate; break }
    }
    if (-not $gitCmd) {
        $logTail = ""
        if (Test-Path $gitLog) {
            $logTail = "`n--- Git 安装日志（末尾 25 行）---`n" + ((Get-Content $gitLog -Tail 25) -join "`n")
        }
        throw "Git 安装完成但未找到 git.exe（退出码 0）。$logTail`n请手动安装 Git for Windows（https://git-scm.com/download/win）后重新运行 setup_2byteasr.bat。"
    }
    $gitBin = Split-Path $gitCmd -Parent
    # 当前进程与用户级 PATH 持久化（后续进程也能找到 git）
    $env:Path = "$gitBin;$env:Path"
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$gitBin*") {
        [Environment]::SetEnvironmentVariable("Path", "$gitBin;$userPath", "User")
    }
    Write-Host "[Prerequisite] Git 已就绪：$gitCmd" -ForegroundColor Green
}


function Install-DirectPrerequisites {
    # winget 不可用时的降级方案：从官方渠道直接下载安装（使用系统代理）。
    $downloads = Join-Path $env:TEMP "2byteasr-prereq"
    New-Item -ItemType Directory -Path $downloads -Force | Out-Null
    if ($missing -contains "uv") {
        Write-Host "[Prerequisite] 从 GitHub 官方下载 uv ..." -ForegroundColor Cyan
        Download-WithProxy "https://github.com/astral-sh/uv/releases/download/0.12.3/uv-x86_64-pc-windows-msvc.zip" (Join-Path $downloads "uv.zip")
        Expand-Archive (Join-Path $downloads "uv.zip") (Join-Path $downloads "uv") -Force
        $uvDir = Join-Path $env:LOCALAPPDATA "uv"
        New-Item -ItemType Directory -Path $uvDir -Force | Out-Null
        Copy-Item (Join-Path $downloads "uv\uv.exe") (Join-Path $uvDir "uv.exe") -Force
        $env:Path = "$uvDir;$env:Path"
    }
    if ($missing -contains "git") {
        Install-GitDirect
    }
    if (($missing -contains "ffmpeg") -or ($missing -contains "ffprobe")) {
        Write-Host "[Prerequisite] 从 gyan.dev 官方下载 FFmpeg ..." -ForegroundColor Cyan
        $ffmpegZip = Join-Path $downloads "ffmpeg.zip"
        Download-WithProxy "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" $ffmpegZip
        Expand-Archive $ffmpegZip (Join-Path $downloads "ffmpeg") -Force
        $ffBin = Get-ChildItem (Join-Path $downloads "ffmpeg") -Recurse -Directory |
            Where-Object { $_.Name -eq "bin" } | Select-Object -First 1
        if (-not $ffBin) { throw "FFmpeg 解压后未找到 bin 目录。" }
        $dest = Join-Path $env:LOCALAPPDATA "Programs\FFmpeg\bin"
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
        Copy-Item (Join-Path $ffBin.FullName "ffmpeg.exe") $dest -Force
        Copy-Item (Join-Path $ffBin.FullName "ffprobe.exe") $dest -Force
        $env:Path = "$dest;$env:Path"
    }
}

Refresh-ProcessPath
$missing = @(Get-MissingCommands)

if ($CheckOnly) {
    $requiredMissing = @($missing | Where-Object { $_ -ne "nvidia-smi" })
    if ($missing -contains "nvidia-smi") {
        Write-Warning "未检测到 NVIDIA GPU 驱动；安装器结构检查仍可通过。若选择 MOSS/FireRed/Qwen 本地 CUDA 模型，请安装或更新 NVIDIA 驱动；也可选择 CPU 或在线 API 模型。"
    }
    if ($requiredMissing.Count -gt 0) {
        Write-Host "[Missing prerequisites] $($requiredMissing -join ', ')" -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] System prerequisites are ready." -ForegroundColor Green
    exit 0
}

$gpuWarned = $false
if ($missing -contains "nvidia-smi") {
    $gpuWarned = $true
    Write-Warning "未检测到 NVIDIA GPU 驱动（nvidia-smi 不可用）。运行环境仍会安装；之后可选择 CPU/在线 API 模型。只有选择 MOSS/FireRed/Qwen 本地 CUDA 模型时才需要可用的 NVIDIA 驱动。"
    $missing = @($missing | Where-Object { $_ -ne "nvidia-smi" })
}

if ($InstallPrerequisites) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Warning "winget 不可用，改用官方渠道直接下载安装依赖（使用系统代理）..."
        Install-DirectPrerequisites
    } else {
        if ($missing -contains "uv") { Install-WinGetPackage "astral-sh.uv" "uv" }
        if ($missing -contains "git") { Install-GitDirect }
        if (($missing -contains "ffmpeg") -or ($missing -contains "ffprobe")) {
            Install-WinGetPackage "Gyan.FFmpeg" "FFmpeg"
        }
    }
    Refresh-ProcessPath
}

$remaining = @(Get-MissingCommands)
if ($gpuWarned) {
    $remaining = @($remaining | Where-Object { $_ -ne "nvidia-smi" })
}
if ($remaining.Count -gt 0) {
    $tools = Join-Path $ProjectRoot "tools"
    if (Test-Path $tools) {
        Write-Host "tools/ 目录存在（$tools），但以下命令仍不可用。tools 内文件（前 25 项）：" -ForegroundColor Yellow
        Get-ChildItem $tools -Recurse -File -ErrorAction SilentlyContinue |
            Select-Object -First 25 | ForEach-Object {
                Write-Host "  $($_.FullName.Substring($tools.Length + 1))" -ForegroundColor DarkGray
            }
    } else {
        Write-Host "便携版应自带 tools/ 目录（$tools），当前缺失。请确认解压完整，或改用 Setup 安装版。" -ForegroundColor Yellow
    }
    throw "Prerequisites are still missing: $($remaining -join ', ')."
}

if ($Repair) {
    Write-Host "[修复] Repair Mode：忽略 setup-complete 早退，只重建检查失败的运行环境。" -ForegroundColor Cyan
    Set-InstallStep "修复运行环境（不删除原环境，成功后才切换）"
    $repairHelper = Join-Path $PSScriptRoot "repair_environment.ps1"
    . $repairHelper
    $repairCode = Invoke-EnvironmentRepair -ProjectRoot $ProjectRoot -Role $RepairRole
    if ($repairCode -ne 0) {
        throw "运行环境修复失败（退出码 $repairCode）。原环境已保留。"
    }
    if (-not (Test-Path -LiteralPath $SetupMarker)) {
        Set-Content -LiteralPath $SetupMarker -Value (Get-Date).ToString("o") -Encoding ascii
    }
    Write-Host "[OK] 运行环境修复完成。" -ForegroundColor Green
    if (-not $NoLaunch -and (Test-Path -LiteralPath $Launcher)) {
        Start-Process -FilePath $Launcher -WorkingDirectory $ProjectRoot
    }
    exit 0
}

Write-Host "[1/2] Creating the lightweight workbench environment (no models) ..." -ForegroundColor Cyan
Set-InstallStep "创建轻量工作台环境（不下载模型，通常约 2-8 分钟）"
& $SetupEnvironment
if ($LASTEXITCODE -ne 0) {
    throw "Python environment setup failed (exit code $LASTEXITCODE)."
}

if ($DownloadModels) {
    $totalText = if ($IncludeQwenChoice) { "约 11.7 GB（含 Qwen 复核模型）" } else { "约 7 GB" }
    Set-InstallStep "下载模型（$totalText，可断点续传）"
    Write-Host "[2/2] 下载固定版本模型（$totalText：MOSS 转写/说话人、FireRed 字级时间轴、声纹；可续传）..." -ForegroundColor Cyan
    # 不使用数组 splatting 传递 switch。Windows PowerShell 5.1 在从安装器
    # 启动的脚本调用链中可能把字符串 "-Yes" 重新绑定给父脚本，导致
    # PositionalParameterNotFound。四种组合全部用真正的命名参数调用。
    if ($IncludeQwenChoice -and $MinimalChoice) {
        & $DownloadModelScript -Yes -IncludeQwen -Minimal
    } elseif ($IncludeQwenChoice) {
        & $DownloadModelScript -Yes -IncludeQwen
    } elseif ($MinimalChoice) {
        & $DownloadModelScript -Yes -Minimal
    } else {
        & $DownloadModelScript -Yes
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Model download failed (exit code $LASTEXITCODE)."
}} else {
    Write-Host "[2/2] 运行环境已准备好。模型不在 Setup 中强制下载，请首次启动后在模型工坊按需选择。" -ForegroundColor Green
}

Set-InstallStep "收尾"
# 全部成功后才写完成标记：2ByteASR.exe 启动器据此判断环境是否完整。
# 必须先写标记再启动启动器，避免启动器先读到缺标记而误弹“继续配置”。
Set-Content -LiteralPath $SetupMarker -Value (Get-Date).ToString("o") -Encoding ascii

if (-not $NoLaunch -and (Test-Path -LiteralPath $Launcher)) {
    Start-Process -FilePath $Launcher -WorkingDirectory $ProjectRoot
}

Write-Host "[OK] 2ByteASR is ready." -ForegroundColor Green
