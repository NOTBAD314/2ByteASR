# 环境依赖契约读取（Phase A）：dependencies.lock.json 的 environments 段
# 是 Main/MOSS 两个 venv 的部署版本真相（deployment lock）。
#
# 概念区分：
# - package metadata constraint（MOSS pyproject "transformers>=5,<6"）= 上游兼容范围
# - deployment lock（本文件读取的 environments 段，== 精确版本）= 发行版验证版本
# - installed environment（.venv-main/.venv-moss）= 必须与 lock 一致
#
# 用法（安装脚本 / Phase B preflight / Phase D repair 共用）：
#   . (Join-Path $PSScriptRoot "environment-lock.ps1")
#   $pkgs = Get-EnvironmentPackages -Role moss     # @("transformers==5.14.1", ...)
#   $ver  = Get-EnvironmentDependency -Role main -Name transformers
#
# fail-closed：environments 段缺失、role 未知、8 项关键字段缺失 → 抛异常。

$ErrorActionPreference = "Stop"

function Get-EnvironmentContract {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("main", "moss", "firered_llm", "nemotron")]
        [string]$Role,
        [string]$ProjectRoot = ""
    )
    if (-not $ProjectRoot) {
        $ProjectRoot = Split-Path -Parent $PSScriptRoot
    }
    $lockPath = Join-Path $ProjectRoot "dependencies.lock.json"
    if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
        throw "缺少依赖版本清单：$lockPath"
    }
    $lock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $environment = $lock.environments.$Role
    if (-not $environment) {
        throw "dependencies.lock.json 缺少 environments.$Role 契约。"
    }
    foreach ($field in @("python", "torch", "torchaudio")) {
        if (-not ([string]$environment.$field)) {
            throw "environments.$Role 缺少 $field 版本。"
        }
    }
    if (-not $environment.packages -or -not $environment.packages.transformers -or
        -not $environment.packages.huggingface_hub) {
        throw "environments.$Role.packages 缺少 transformers / huggingface_hub 精确版本。"
    }
    return $environment
}

function Get-EnvironmentDependency {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("main", "moss", "firered_llm", "nemotron")]
        [string]$Role,
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$ProjectRoot = ""
    )
    $contract = Get-EnvironmentContract -Role $Role -ProjectRoot $ProjectRoot
    if ($Name -eq "python") { return [string]$contract.python }
    if ($Name -eq "torch") { return [string]$contract.torch }
    if ($Name -eq "torchaudio") { return [string]$contract.torchaudio }
    $value = $contract.packages.$Name
    if (-not $value) {
        throw "environments.$Role.packages 缺少 $Name 精确版本。"
    }
    return [string]$value
}

function Get-EnvironmentPackages {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("main", "moss", "firered_llm", "nemotron")]
        [string]$Role,
        [string]$ProjectRoot = ""
    )
    $contract = Get-EnvironmentContract -Role $Role -ProjectRoot $ProjectRoot
    $specs = @()
    foreach ($property in $contract.packages.PSObject.Properties) {
        $source = if ($contract.package_sources) { $contract.package_sources.($property.Name) } else { $null }
        $specs += $(if ($source) { "{0} @ {1}" -f $property.Name, [string]$source } else { "{0}=={1}" -f $property.Name, [string]$property.Value })
    }
    return $specs
}
