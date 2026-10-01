[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$ForceSourceRefresh
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LockPath = Join-Path $ProjectRoot "dependencies.lock.json"
$MainEnv = Join-Path $ProjectRoot ".venv-main"
$MossEnv = Join-Path $ProjectRoot ".venv-moss"
$MainPython = Join-Path $MainEnv "Scripts\python.exe"
$MossPython = Join-Path $MossEnv "Scripts\python.exe"

function Show-RecoveryHint {
    param([string]$Name)
    switch ($Name) {
        "uv" { Write-Host "  安装说明：https://docs.astral.sh/uv/getting-started/installation/" }
        "git" { Write-Host "  可执行：winget install --id Git.Git -e" }
        "ffmpeg" { Write-Host "  可执行：winget install --id Gyan.FFmpeg -e" }
        "ffprobe" { Write-Host "  ffprobe 随 FFmpeg 一起安装。" }
        "nvidia-smi" { Write-Host "  请安装或更新 NVIDIA 显卡驱动：https://www.nvidia.com/Download/index.aspx" }
    }
}

function Assert-Prerequisites {
    $missing = @()
    $gpuMissing = -not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
    foreach ($name in @("uv", "git", "ffmpeg", "ffprobe")) {
        if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
            $missing += $name
        }
    }
    if ($missing.Count -gt 0) {
        Write-Host "[缺少系统依赖] $($missing -join ', ')" -ForegroundColor Red
        foreach ($name in $missing) { Show-RecoveryHint $name }
        throw "请安装以上组件并重新运行 setup_environment.bat。"
    }

    if ($gpuMissing) {
        Write-Host "[硬件] 未检测到 NVIDIA GPU；基础工作台仍可正常安装。之后可选择 CPU/在线 API 模型。" -ForegroundColor Yellow
        return
    }
    $memoryText = & nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1
    $memoryMb = 0
    [void][int]::TryParse(($memoryText -replace '[^0-9]', ''), [ref]$memoryMb)
    if ($memoryMb -gt 0 -and $memoryMb -lt 14336) {
        Write-Warning "检测到约 $([math]::Round($memoryMb / 1024, 1)) GB 显存；完整流水线建议至少 16 GB。"
    } elseif ($memoryMb -gt 0) {
        Write-Host "[硬件] NVIDIA GPU 显存约 $([math]::Round($memoryMb / 1024, 1)) GB。"
    }
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "命令失败（退出码 $LASTEXITCODE）：$FilePath $($Arguments -join ' ')"
    }
}

function Resolve-ProjectPath {
    param([string]$RelativePath)
    return Join-Path $ProjectRoot ($RelativePath -replace '/', '\')
}

function Ensure-PinnedSource {
    param(
        [Parameter(Mandatory = $true)]$Spec,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Marker
    )

    $destination = Resolve-ProjectPath $Spec.path
    $gitDir = Join-Path $destination ".git"
    $markerPath = Join-Path $destination $Marker

    if ((Test-Path $destination) -and -not (Test-Path $gitDir)) {
        if (-not (Test-Path $markerPath)) {
            throw "$Label 目录存在但内容不完整：$destination"
        }
        Write-Warning "$Label 是旧版无 Git 元数据目录，保留并继续使用。全新安装会固定到 $($Spec.revision)。"
        return
    }

    if (-not (Test-Path $gitDir)) {
        Write-Host "[源码] 正在获取 $Label ..."
        # 强制 autocrlf=true：FireRed 加固补丁的 Upstream/Hardened SHA-256 按 CRLF 工作区设计，
        # 全新机器 git 默认检出 LF 会导致补丁哈希校验失败（首次安装必现）。
        Invoke-External "git" @("-c", "core.autocrlf=true", "clone", "--filter=blob:none", "--no-checkout", [string]$Spec.repository, $destination)
        # 新克隆没有工作区文件，git status 会把全部文件报告为已删除（D），
        # 必须先检出固定版本，再做本地修改检查，否则首次安装会误报“本地修改”。
        Invoke-External "git" @("-c", "safe.directory=$destination", "-c", "core.autocrlf=true", "-C", $destination, "checkout", "--detach", [string]$Spec.revision)
    }

    $gitPrefix = @("-c", "safe.directory=$destination", "-C", $destination)
    $dirty = & git @gitPrefix status --porcelain
    if ($LASTEXITCODE -ne 0) {
        # git 元数据损坏（如虚拟机快照回滚后 .git 不完整），删除目录后重新获取。
        Write-Warning "$Label git 元数据异常（退出码 $LASTEXITCODE），删除后重新获取..."
        & cmd /c "rmdir /s /q `"$destination`"" 2>$null | Out-Null
        if (Test-Path $destination) {
            throw "无法清理 $Label 目录（可能被占用）：$destination"
        }
        Invoke-External "git" @("-c", "core.autocrlf=true", "clone", "--filter=blob:none", "--no-checkout", [string]$Spec.repository, $destination)
        Invoke-External "git" @("-c", "safe.directory=$destination", "-c", "core.autocrlf=true", "-C", $destination, "checkout", "--detach", [string]$Spec.revision)
        $gitPrefix = @("-c", "safe.directory=$destination", "-C", $destination)
        $dirty = & git @gitPrefix status --porcelain
        if ($LASTEXITCODE -ne 0) { throw "无法检查 $Label 工作区。" }
    }
    if ($dirty) {
        $allowedFireRedChanges = @(
            "fireredasr2s/fireredasr2/asr.py",
            "fireredasr2s/fireredvad/core/detect_model.py",
            "fireredasr2s/fireredlid/lid.py",
            "fireredasr2s/fireredpunc/punc.py"
        )
        $dirtyPaths = @($dirty | ForEach-Object { ([string]$_).Substring(3).Trim().Replace('\', '/') })
        $onlySecurityPatch = $Label -eq "FireRedASR2S" -and
            @($dirtyPaths | Where-Object { $_ -notin $allowedFireRedChanges }).Count -eq 0
        if ($onlySecurityPatch) {
            # 目录只有允许的安全补丁修改时，执行完整补丁补齐（含上次中断未完成的文件），
            # 而不是仅 CheckOnly——部分补丁状态会让 CheckOnly 误报缺失。
            & (Join-Path $PSScriptRoot "harden_firered_source.ps1")
        } else {
            throw "$Label 存在本地修改，安装器不会覆盖：$destination"
        }
    }

    $current = (& git @gitPrefix rev-parse HEAD 2>$null).Trim()
    if ($ForceSourceRefresh -or $current -ne [string]$Spec.revision) {
        & git @gitPrefix cat-file -e "$($Spec.revision)^{commit}" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Invoke-External "git" @("-c", "safe.directory=$destination", "-c", "core.autocrlf=true", "-C", $destination, "fetch", "--depth", "1", "origin", [string]$Spec.revision)
        }
        Invoke-External "git" @("-c", "safe.directory=$destination", "-c", "core.autocrlf=true", "-C", $destination, "checkout", "--detach", "--force", [string]$Spec.revision)
    }

    $resolved = (& git @gitPrefix rev-parse HEAD).Trim()
    if ($resolved -ne [string]$Spec.revision) {
        throw "$Label 版本校验失败：期望 $($Spec.revision)，实际 $resolved"
    }
    Write-Host "[源码] $Label：$resolved"
}

if (-not (Test-Path $LockPath)) {
    throw "缺少依赖版本清单：$LockPath"
}
$Lock = Get-Content -Raw -Encoding UTF8 $LockPath | ConvertFrom-Json
if ($Lock.schema_version -ne 1) {
    throw "不支持的 dependencies.lock.json schema_version：$($Lock.schema_version)"
}
$CudaTorchVersion = [string]$Lock.runtime.torch
$CudaAudioVersion = [string]$Lock.runtime.torchaudio
$CudaTorchTag = [string]$Lock.runtime.cuda_wheel
$CudaTorchModernTag = [string]$Lock.runtime.cuda_wheel_modern
$SetuptoolsVersion = [string]$Lock.runtime.setuptools
$WheelVersion = [string]$Lock.runtime.wheel
if (-not $CudaTorchVersion -or -not $CudaAudioVersion -or -not $CudaTorchTag `
        -or -not $SetuptoolsVersion -or -not $WheelVersion) {
    throw "dependencies.lock.json 缺少 runtime.torch / torchaudio / cuda_wheel / setuptools / wheel。"
}

function Select-CudaTorchTag {
    # RTX 50 / Blackwell (compute capability 12.x) needs a wheel that contains
    # sm_120 kernels.  cu126 can import successfully yet fail on the first GPU
    # tensor, so choose cu128 for that architecture and keep cu126 for older
    # cards/drivers with wider compatibility.
    if ($CudaTorchModernTag -and (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
        $capability = & nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null | Select-Object -First 1
        $majorText = ([string]$capability -split '\.')[0] -replace '[^0-9]', ''
        $major = 0
        [void][int]::TryParse($majorText, [ref]$major)
        if ($major -ge 12) {
            Write-Host "[硬件] 检测到 compute capability $capability，使用支持 RTX 50 系列的 $CudaTorchModernTag PyTorch。" -ForegroundColor Cyan
            return $CudaTorchModernTag
        }
    }
    return $CudaTorchTag
}

Write-Host "2ByteASR 轻量工作台环境安装（不下载模型，也不安装 MOSS/FireRed/Qwen/FunASR 专属运行库）" -ForegroundColor Cyan

# 便携版内置工具（tools/）优先加入 PATH：ffmpeg、git、uv 无需联网下载。
# 必须在系统依赖检查之前执行，否则仅带内置工具（未全局安装）的环境会误报缺少依赖。
$ToolsDir = Join-Path $ProjectRoot "tools"
if (Test-Path $ToolsDir) {
    foreach ($extra in @($ToolsDir, (Join-Path $ToolsDir "ffmpeg\bin"), (Join-Path $ToolsDir "git\cmd"), (Join-Path $ToolsDir "git\bin"))) {
        if (Test-Path $extra) { $env:Path = "$extra;$env:Path" }
    }
}

Assert-Prerequisites
$CudaTorchTag = Select-CudaTorchTag
$CudaTorchFindLinks = "https://mirrors.aliyun.com/pytorch-wheels/$CudaTorchTag/"
$CudaTorchOfficialIndex = "https://download.pytorch.org/whl/$CudaTorchTag"
if ($CheckOnly) {
    Write-Host "[完成] 系统依赖检查通过。"
    exit 0
}

$Uv = (Get-Command uv).Source
if (-not $Uv) {
    $localUv = Join-Path $ToolsDir "uv.exe"
    if (Test-Path $localUv) {
        $env:Path = "$ToolsDir;$env:Path"
        $Uv = (Get-Command uv).Source
    }
}
# 国内网络默认使用清华 PyPI 镜像安装依赖；
# 需要官方 PyPI 时设置环境变量 UV_DEFAULT_INDEX=https://pypi.org/simple 覆盖。
if (-not $env:UV_DEFAULT_INDEX) {
    $env:UV_DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
    Write-Host "[网络] 依赖走清华 PyPI 镜像：$env:UV_DEFAULT_INDEX（可用 UV_DEFAULT_INDEX 覆盖）" -ForegroundColor Cyan
}
# 清华镜像封禁部分包（qwen-asr 返回 403），uv 找不到/被拒时自动回退官方 PyPI。
# 离线 wheels 模式（--no-index）不受影响。
if (-not $env:UV_EXTRA_INDEX_URL) {
    $env:UV_EXTRA_INDEX_URL = "https://pypi.org/simple"
    Write-Host "[网络] 官方 PyPI 作为兜底源（清华镜像封禁的包自动回退）" -ForegroundColor Cyan
}

# 便携包内置依赖（wheels/）：--no-index + --find-links 全离线安装，零网络。
$WheelsDir = Join-Path $ProjectRoot "wheels"
$OfflineArgs = @()
if (Test-Path $WheelsDir) {
    $OfflineArgs = @("--no-index", "--find-links", $WheelsDir)
    Write-Host "[环境] 使用便携包内置依赖（wheels/），无需联网下载" -ForegroundColor Cyan
}

# 安装期间把 uv 缓存放在项目内，便于大依赖下载中断后续传；环境创建成功后
# 自动删除，因为虚拟环境已经包含运行文件，保留缓存只会重复占用数 GB。
# 用户显式指定的 UV_CACHE_DIR 可能是共享缓存，因此不会自动清理。
$ProjectUvCache = Join-Path $ProjectRoot ".uv-cache"
$UsingProjectUvCache = -not [bool]$env:UV_CACHE_DIR
if (-not $env:UV_CACHE_DIR) {
    $env:UV_CACHE_DIR = $ProjectUvCache
    Write-Host "[网络] uv 临时依赖缓存：$env:UV_CACHE_DIR（安装成功后自动清理）" -ForegroundColor Cyan
}

# torch 等大依赖在镜像上下载较慢，放宽 uv 的 HTTP 超时（默认 30 秒偏短，
# 容易导致大文件中途失败）；中断后重新运行会从缓存/断点继续。
if (-not $env:UV_HTTP_TIMEOUT) { $env:UV_HTTP_TIMEOUT = "300" }
if (-not $env:UV_CONCURRENT_DOWNLOADS) { $env:UV_CONCURRENT_DOWNLOADS = "8" }


function Resolve-SystemPython {
    param([Parameter(Mandatory = $true)][string]$MajorMinor)
    # 依次查找：常见安装路径（winget/官方安装器）→ 注册表。
    # 不用 py 启动器：找不到版本时它会把横幅写到 stderr，在
    # ErrorActionPreference=Stop 下触发 NativeCommandError。
    $short = $MajorMinor -replace '\.', ''
    foreach ($base in @((Join-Path $env:LOCALAPPDATA "Programs\Python"), (Join-Path $env:ProgramFiles "Python"))) {
        $candidate = Join-Path (Join-Path $base "Python$short") "python.exe"
        if (Test-Path $candidate) { return $candidate }
    }
    foreach ($root in @("HKLM:\SOFTWARE\Python\PythonCore\$MajorMinor\InstallPath", "HKCU:\SOFTWARE\Python\PythonCore\$MajorMinor\InstallPath")) {
        $reg = Get-ItemProperty $root -ErrorAction SilentlyContinue
        if ($reg -and $reg.'(default)' -and (Test-Path (Join-Path $reg.'(default)' "python.exe"))) {
            return (Join-Path $reg.'(default)' "python.exe")
        }
    }
    return ""
}


function Get-PythonInstallerSha256 {
    param([Parameter(Mandatory = $true)][string]$Version)
    switch ($Version) {
        "3.10.11" { return "d8dede5005564b408ba50317108b765ed9c3c510342a598f9fd42681cbe0648b" }
        "3.12.10" { return "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb" }
        default { return "" }
    }
}


function Assert-PythonInstallerIntegrity {
    param(
        [Parameter(Mandatory = $true)][string]$Installer,
        [Parameter(Mandatory = $true)][string]$Version
    )
    $expected = Get-PythonInstallerSha256 $Version
    if (-not $expected) {
        Write-Warning "Python $Version 没有内置 SHA-256 记录，跳过安装器哈希校验。"
        return
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Installer).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "Python $Version 安装器校验失败，文件可能下载不完整或已被篡改：$Installer`n期望 SHA-256：$expected`n实际 SHA-256：$actual"
    }
}


function Install-PythonFromExecutable {
    param(
        [Parameter(Mandatory = $true)][string]$Installer,
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$MajorMinor,
        [Parameter(Mandatory = $true)][string]$Label
    )
    Assert-PythonInstallerIntegrity $Installer $Version
    $logPath = Join-Path $env:TEMP "2byteasr-python-$Version-install.log"
    Remove-Item $logPath -Force -ErrorAction SilentlyContinue
    Write-Host "[环境] Python 安装日志：$logPath" -ForegroundColor DarkGray

    # python.org 的 exe 是 GUI bootstrapper。用调用运算符（&）启动时，Windows
    # PowerShell 可能在真正安装完成前就继续执行，随后立即探测 python.exe 会误判失败。
    # Start-Process -Wait 会等待完整安装进程结束，并可靠取得退出码。
    try {
        $process = Start-Process -FilePath $Installer -ArgumentList @(
            "/quiet", "/log", "`"$logPath`"",
            "InstallAllUsers=0", "PrependPath=0", "Include_launcher=0",
            "Include_test=0", "Include_doc=0", "Include_tcltk=1"
        ) -Wait -PassThru -WindowStyle Hidden
        $exitCode = $process.ExitCode
    } catch {
        throw "$Label Python $Version 安装器无法启动：$($_.Exception.Message)`n安装器：$Installer`n日志：$logPath"
    }

    # 安装完成后注册表和杀毒软件仍可能有短暂延迟，最多等待 30 秒。
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $exe = Resolve-SystemPython $MajorMinor
        if ($exe) {
            if ($exitCode -eq 3010) {
                Write-Warning "Python $Version 已安装，安装器提示重启后生效（退出码 3010）。当前安装可继续。"
            }
            return $exe
        }
        Start-Sleep -Seconds 1
    }

    $logTail = ""
    if (Test-Path $logPath) {
        $logTail = "`n--- Python 安装日志末尾 30 行 ---`n" + ((Get-Content -LiteralPath $logPath -Tail 30) -join "`n")
    }
    throw "$Label 需要 Python $MajorMinor。Python $Version 安装失败或安装后未找到 python.exe（退出码 $exitCode）。`n安装日志：$logPath$logTail"
}


function Ensure-SystemPython {
    param(
        [Parameter(Mandatory = $true)][string]$MajorMinor,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $exe = Resolve-SystemPython $MajorMinor
    if ($exe) { return $exe }
    # 便携包内置 Python 安装器优先（本地安装，不联网）
    $pyVersion = if ($MajorMinor -eq "3.10") { "3.10.11" } elseif ($MajorMinor -eq "3.12") { "3.12.10" } else { $MajorMinor }
    $localInstaller = Join-Path $ProjectRoot "tools\python-$pyVersion-amd64.exe"
    if (Test-Path $localInstaller) {
        Write-Host "[环境] 使用便携包内置 Python 安装器（$pyVersion）..." -ForegroundColor Cyan
        return (Install-PythonFromExecutable $localInstaller $pyVersion $MajorMinor $Label)
    }
    Write-Host "[环境] 未找到系统 Python $MajorMinor，尝试通过 winget 安装..." -ForegroundColor Cyan
    # winget 的进度输出会污染函数返回值，必须全部吞掉
    & winget install --id "Python.Python.$MajorMinor" --exact --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "winget 安装 Python 失败，尝试从 python.org 官方下载安装（使用系统代理）..."
        $pyVersion = if ($MajorMinor -eq "3.10") { "3.10.11" } elseif ($MajorMinor -eq "3.12") { "3.12.10" } else { $MajorMinor }
        $installer = Join-Path $env:TEMP "python-$pyVersion-amd64.exe"
        # 依次尝试 python.org 官方与华为云国内镜像
        $pyUrls = @(
            "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-amd64.exe",
            "https://mirrors.huaweicloud.com/python/$pyVersion/python-$pyVersion-amd64.exe"
        )
        for ($attempt = 1; $attempt -le ($pyUrls.Count * 2); $attempt++) {
            $url = $pyUrls[[math]::Floor(($attempt - 1) / 2)]
            try {
                Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing -ErrorAction Stop
                break
            } catch {
                if ($attempt -ge ($pyUrls.Count * 2)) {
                    throw "$Label 需要 Python $MajorMinor。官方与镜像下载均失败，请从 https://www.python.org/downloads/ 手动安装后重新运行 setup_2byteasr.bat。"
                }
                Write-Warning "下载失败（$url），正在重试..."
                Start-Sleep -Seconds 4
            }
        }
        return (Install-PythonFromExecutable $installer $pyVersion $MajorMinor $Label)
    }

    # winget 成功后也可能需要数秒才写完注册表，和 exe 安装走同一套耐心轮询。
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $exe = Resolve-SystemPython $MajorMinor
        if ($exe) { return $exe }
        Start-Sleep -Seconds 1
    }
    throw "$Label 需要 Python $MajorMinor。winget 返回成功，但安装后仍未找到 python.exe。请查看 %TEMP%\2byteasr-setup.log 并重新运行 setup_2byteasr.bat。"
}


function New-StdlibVenv {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$VenvPath
    )
    # 使用 python -m venv（标准库）创建环境，避免 uv 管理 Python 时
    # 创建版本链接（junction）触发 Windows “不受信任的装入点”（os error 448）。
    # 已存在且 python.exe 可用时复用（中断后重跑不再全删重建，依赖由 pip 补齐）；
    # 需要从零重建时手动删除目录。
    $venvPython = Join-Path $VenvPath "Scripts\python.exe"
    if (Test-Path $venvPython) {
        Write-Host "[环境] 复用已有虚拟环境：$VenvPath（缺失依赖会自动补齐）" -ForegroundColor DarkGray
        return
    }
    Remove-Item $VenvPath -Recurse -Force -ErrorAction SilentlyContinue
    Invoke-External $PythonExe @("-m", "venv", $VenvPath)
    if (-not (Test-Path $venvPython)) {
        throw "虚拟环境创建失败：$VenvPath"
    }
}

Write-Host "[环境] 创建主流程 Python $($Lock.python.main) ..."
$MainPythonExe = Ensure-SystemPython ([string]$Lock.python.main) "主流程"
Write-Host "[环境] 使用系统 Python：$MainPythonExe"
New-StdlibVenv $MainPythonExe $MainEnv
$MainPython = Join-Path $MainEnv "Scripts\python.exe"
Invoke-External $Uv (@("pip", "install", "--python", $MainPython, "pip==26.1.2") + $OfflineArgs)
Invoke-External $Uv (@("pip", "install", "--python", $MainPython, "setuptools==$SetuptoolsVersion", "wheel==$WheelVersion") + $OfflineArgs)
Invoke-External $Uv (@("pip", "install", "--python", $MainPython, "-r", (Join-Path $ProjectRoot "requirements-main.txt")) + $OfflineArgs)

# Main deep preflight and Repair Mode use the deployment contract below. A
# successful first setup must satisfy the same contract; otherwise the launcher
# immediately asks users to repair an environment setup just created.
. (Join-Path $PSScriptRoot "environment-lock.ps1")
$MainContractPackages = @(Get-EnvironmentPackages -Role main -ProjectRoot $ProjectRoot)
$MainTorchVersion = Get-EnvironmentDependency -Role main -Name torch -ProjectRoot $ProjectRoot
$MainAudioVersion = Get-EnvironmentDependency -Role main -Name torchaudio -ProjectRoot $ProjectRoot
Write-Host "[环境] 安装 Main 共享运行契约（不含模型权重）..." -ForegroundColor Cyan
Invoke-External $Uv (@("pip", "install", "--python", $MainPython) + $MainContractPackages + $OfflineArgs)
Invoke-External $Uv (@(
    "pip", "install", "--python", $MainPython,
    "torch==$MainTorchVersion+cpu", "torchaudio==$MainAudioVersion+cpu"
) + $OfflineArgs)

# NVIDIA GPU 使用经过验证、驱动覆盖面更广的 cu126 组合。不能只检查版本名
# 是否含有 “+cu”：cu130 在 580 以下驱动上同样会安装成功，却无法启动 CUDA。
function Test-CompatibleCudaTorch {
    param([Parameter(Mandatory = $true)][string]$PythonExe)
    if (-not (Test-Path -LiteralPath $PythonExe)) { return $false }
    $previousEap = $ErrorActionPreference
    try {
        # A missing torch package is an expected probe result, not a setup
        # failure. Windows PowerShell 5.1 otherwise promotes native stderr to
        # NativeCommandError while ErrorActionPreference is Stop.
        $ErrorActionPreference = "Continue"
        & $PythonExe -c "import sys, torch, torchaudio; versions = torch.__version__ == '$CudaTorchVersion+$CudaTorchTag' and torchaudio.__version__ == '$CudaAudioVersion+$CudaTorchTag'; usable = versions and torch.cuda.is_available() and torch.empty(1, device='cuda').numel() == 1; sys.exit(0 if usable else 1)" 2>$null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousEap
    }
}

function Remove-IncompleteTorchInstallation {
    param([Parameter(Mandatory = $true)][string]$PythonExe)
    $venvRoot = Split-Path -Parent (Split-Path -Parent $PythonExe)
    $sitePackages = [System.IO.Path]::GetFullPath((Join-Path $venvRoot "Lib\site-packages"))
    $projectFull = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    if (-not $sitePackages.StartsWith($projectFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝清理项目目录之外的 Python 环境：$sitePackages"
    }
    if (-not (Test-Path -LiteralPath $sitePackages)) { return }
    $broken = @(
        Get-ChildItem -LiteralPath $sitePackages -Directory -Filter "torch-*.dist-info" -ErrorAction SilentlyContinue |
            Where-Object { -not (Test-Path -LiteralPath (Join-Path $_.FullName "RECORD")) }
    )
    if ($broken.Count -eq 0) { return }
    Write-Warning "检测到上次中断留下的不完整 PyTorch（缺少 RECORD），正在安全清理后重装。"
    $targets = @(
        (Join-Path $sitePackages "torch"),
        (Join-Path $sitePackages "torchaudio"),
        (Join-Path $sitePackages "torchgen"),
        (Join-Path $sitePackages "functorch")
    ) + @(
        Get-ChildItem -LiteralPath $sitePackages -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "torch-*.dist-info" -or $_.Name -like "torchaudio-*.dist-info" } |
            Select-Object -ExpandProperty FullName
    )
    try {
        foreach ($target in ($targets | Select-Object -Unique)) {
            if (Test-Path -LiteralPath $target) {
                Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop
            }
        }
    } catch {
        throw "PyTorch 文件正在被占用，无法修复。请关闭所有 2ByteASR、模型下载器和使用该环境的 Python 进程后重试。被占用文件：$($_.Exception.Message)"
    }
}

function Install-CompatibleCudaTorch {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (Test-CompatibleCudaTorch $PythonExe) {
        Write-Host "[环境] $Label 已使用兼容 PyTorch：$CudaTorchVersion+$CudaTorchTag" -ForegroundColor DarkGray
        return
    }

    Remove-IncompleteTorchInstallation $PythonExe

    $torchSpec = "torch==$CudaTorchVersion+$CudaTorchTag"
    $audioSpec = "torchaudio==$CudaAudioVersion+$CudaTorchTag"
    Write-Host "[环境] $Label 安装兼容 CUDA PyTorch（$CudaTorchVersion+$CudaTorchTag，国内镜像，可续传）..." -ForegroundColor Cyan
    & $Uv pip install --python $PythonExe --upgrade $torchSpec $audioSpec --find-links $CudaTorchFindLinks --index-strategy unsafe-best-match --reinstall-package torch --reinstall-package torchaudio
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "阿里云 PyTorch 镜像安装失败，尝试 PyTorch 官方源..."
        Remove-IncompleteTorchInstallation $PythonExe
        & $Uv pip install --python $PythonExe --upgrade $torchSpec $audioSpec --index-url $CudaTorchOfficialIndex --index-strategy unsafe-best-match --reinstall-package torch --reinstall-package torchaudio
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-CompatibleCudaTorch $PythonExe)) {
        throw "$Label 的 CUDA PyTorch 安装失败。目标版本：$CudaTorchVersion+$CudaTorchTag。若日志含‘拒绝访问/os error 5’，请关闭所有 2ByteASR 与 Python 进程后重试；否则可切换下载源或运行【配置或修复 2ByteASR】。"
    }
}

Invoke-External $MainPython @(
    "-m", "py_compile",
    (Join-Path $ProjectRoot "auto_asr.py"),
    (Join-Path $ProjectRoot "moss_firered_pipeline.py"),
    (Join-Path $ProjectRoot "subtitle_core.py"),
    (Join-Path $ProjectRoot "twobyteasr\ui.py"),
    (Join-Path $ProjectRoot "twobyteasr\model_workshop.py")
)

if ($UsingProjectUvCache -and (Test-Path -LiteralPath $ProjectUvCache)) {
    try {
        $resolvedProject = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
        $resolvedCache = [System.IO.Path]::GetFullPath($ProjectUvCache).TrimEnd('\')
        $expectedCache = $resolvedProject + "\.uv-cache"
        if (-not $resolvedCache.Equals($expectedCache, [StringComparison]::OrdinalIgnoreCase)) {
            throw "缓存路径超出预期范围：$resolvedCache"
        }
        $cacheBytes = (
            Get-ChildItem -LiteralPath $resolvedCache -File -Recurse -Force -ErrorAction SilentlyContinue |
                Measure-Object -Property Length -Sum
        ).Sum
        if ($null -eq $cacheBytes) { $cacheBytes = 0 }
        Remove-Item -LiteralPath $resolvedCache -Recurse -Force -ErrorAction Stop
        $cacheGb = [math]::Round([double]$cacheBytes / 1GB, 1)
        Write-Host "[清理] 已删除 uv 临时依赖缓存，释放约 $cacheGb GB：$resolvedCache" -ForegroundColor Green
    } catch {
        Write-Warning "uv 临时缓存清理失败，可在关闭 2ByteASR 后手动删除 $ProjectUvCache：$($_.Exception.Message)"
    }
} elseif (-not $UsingProjectUvCache) {
    Write-Host "[保留] 检测到用户自定义 UV_CACHE_DIR，不自动清理：$env:UV_CACHE_DIR" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "[完成] 轻量工作台环境已准备好。启动 2ByteASR 后再从模型工坊按需安装模型。" -ForegroundColor Green
