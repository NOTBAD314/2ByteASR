# 离线 Python 依赖准备（P1-1）：从 dependencies.lock.json 推导精确版本，
# 下载到干净 staging，校验后合并进 wheels/。
#
# 职责边界：只准备 hotfix / bootstrap 所需的最小 wheel 集（setuptools +
# wheel，离线安装构建 sdist 时必需）。完整 900MB offline bundle 的 wheel
# 集合由 build_offline_bundle.ps1 -RefreshWheels 维护（需要本机
# .venv-main/.venv-moss 冻结清单，CI 不构建完整 bundle——见 Audit P2-15）。
#
# 用法（构建脚本/CI 直接调用）：
#   powershell -ExecutionPolicy Bypass -File scripts/prepare_offline_dependencies.ps1
# 自定义 Python 解释器 / index（中国大陆镜像）：
#   -PythonPath <python> -IndexUrl <mirror>
#   或环境变量 PIP_INDEX_URL
#
# fail-closed：lock 缺版本 / 下载失败 / 产物版本不符 → 抛异常，构建失败。

[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$PythonPath = "python",
    [string]$WheelsDir = "",
    [string]$IndexUrl = ""
)

$ErrorActionPreference = "Stop"

function Get-RequiredWheels {
    param(
        [Parameter(Mandatory = $true)][string]$LockPath
    )
    if (-not (Test-Path -LiteralPath $LockPath -PathType Leaf)) {
        throw "缺少依赖版本清单：$LockPath"
    }
    $lock = Get-Content -LiteralPath $LockPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $setuptools = [string]$lock.runtime.setuptools
    $wheel = [string]$lock.runtime.wheel
    if (-not $setuptools -or -not $wheel) {
        throw "dependencies.lock.json 缺少 runtime.setuptools / runtime.wheel 版本。"
    }
    return @(
        @{ Name = "setuptools"; Version = $setuptools; File = "setuptools-$setuptools-py3-none-any.whl" },
        @{ Name = "wheel"; Version = $wheel; File = "wheel-$wheel-py3-none-any.whl" }
    )
}

function Test-WheelMatchesRequirement {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [Parameter(Mandatory = $true)][string]$LockPath
    )
    $requirements = Get-RequiredWheels -LockPath $LockPath
    $fileName = Split-Path -Leaf $File
    foreach ($requirement in $requirements) {
        if ($fileName -eq $requirement.File) {
            return $true
        }
    }
    return $false
}

function Get-PipDownloadCommand {
    param(
        [Parameter(Mandatory = $true)][object[]]$Requirements,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string]$IndexUrl = ""
    )
    $arguments = @("-m", "pip", "download", "--no-deps", "--only-binary=:all:", "-d", $Destination)
    foreach ($requirement in $Requirements) {
        $arguments += ("{0}=={1}" -f $requirement.Name, $requirement.Version)
    }
    if ($IndexUrl) {
        $arguments += @("--index-url", $IndexUrl)
    } elseif ($env:PIP_INDEX_URL) {
        $arguments += @("--index-url", $env:PIP_INDEX_URL)
    }
    return $arguments
}

function Invoke-PrepareOfflineDependencies {
    param(
        [string]$ProjectRoot = "",
        [string]$PythonPath = "python",
        [string]$WheelsDir = "",
        [string]$IndexUrl = ""
    )
    if (-not $ProjectRoot) {
        $ProjectRoot = Split-Path -Parent $PSScriptRoot
    }
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
    if (-not $WheelsDir) {
        $WheelsDir = Join-Path $ProjectRoot "wheels"
    }
    $lockPath = Join-Path $ProjectRoot "dependencies.lock.json"
    $requirements = @(Get-RequiredWheels -LockPath $lockPath)

    # 干净 staging：下载到 wheels 内的临时目录，全部校验通过后再合并，
    # 不污染既有的长期 wheels/ 目录（避免 Audit P2-15 的漂移进一步恶化）。
    $staging = Join-Path $WheelsDir (".staging-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    try {
        $downloadArgs = @(Get-PipDownloadCommand -Requirements $requirements -Destination $staging -IndexUrl $IndexUrl)
        & $PythonPath @downloadArgs
        if ($LASTEXITCODE -ne 0) {
            throw "pip download 失败（退出码 $LASTEXITCODE）。"
        }
        foreach ($requirement in $requirements) {
            $downloaded = Join-Path $staging $requirement.File
            if (-not (Test-Path -LiteralPath $downloaded -PathType Leaf)) {
                throw "下载产物缺少 $($requirement.Name)==$($requirement.Version)（期望 $($requirement.File)）。"
            }
        }
        # 校验通过后合并进 wheels/（同名覆盖，幂等）
        foreach ($requirement in $requirements) {
            Copy-Item -LiteralPath (Join-Path $staging $requirement.File) `
                -Destination (Join-Path $WheelsDir $requirement.File) -Force
        }
        Write-Host "[依赖] 已准备离线 wheels：$($requirements.File -join ', ')" -ForegroundColor Green
    } finally {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# 仅作为脚本直接运行时执行主流程；dot-source（测试）只加载函数。
if ($MyInvocation.InvocationName -ne ".") {
    Invoke-PrepareOfflineDependencies -ProjectRoot $ProjectRoot -PythonPath $PythonPath `
        -WheelsDir $WheelsDir -IndexUrl $IndexUrl
}
