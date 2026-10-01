[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$VerifyOnly,
    [switch]$IncludeQwen,
    [switch]$Minimal,
    # Windows PowerShell 5.1 的 powershell.exe -File 无法可靠绑定数组参数。
    # GUI 因此使用逗号分隔的一项传入，脚本内部再拆分和逐项校验。
    [string]$Only = "",
    [ValidateSet("AUTO", "MODELSCOPE", "HF_MIRROR", "HF_OFFICIAL", "Auto", "ModelScope", "HfMirror", "HuggingFace")]
    [string]$Source = "AUTO"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LockPath = Join-Path $ProjectRoot "dependencies.lock.json"
# This backend bootstraps itself natively and owns only its private runtime.
# Bypass generic Python orchestration and unrelated Qwen auto-inclusion.
if ($Only.Trim() -eq 'nemotron' -and -not $VerifyOnly) {
    $nativeSource = switch -Regex ($Source) {
        '^(?i)hfmirror|hf[_-]?mirror$' { 'HF_MIRROR' }
        '^(?i)huggingface|hf[_-]?official$' { 'HF_OFFICIAL' }
        default { $Source.ToUpperInvariant() }
    }
    & (Join-Path $PSScriptRoot 'setup_nemotron_backend.ps1') -Source $nativeSource
    exit $LASTEXITCODE
}
if ($env:2BYTEASR_MODEL_ROOT) {
    $ModelsRoot = $env:2BYTEASR_MODEL_ROOT
    New-Item -ItemType Directory -Path $ModelsRoot -Force | Out-Null
} else {
    $ModelsRoot = Join-Path $ProjectRoot "models"
}
$ManifestPath = Join-Path $ModelsRoot ".twobyteasr-models.json"

# ModelScope（魔搭）镜像（可选）：设置 2BYTEASR_MODELSCOPE_ORG=你的组织名后，
# 直链兜底会优先从魔搭拉取（国内带宽通常优于 hf-mirror→AWS 链）。
# 模型需先用 scripts/sync_models_to_modelscope.py 上传一次。
$ModelscopeOrg = $env:2BYTEASR_MODELSCOPE_ORG

# Canonical modes: AUTO / MODELSCOPE / HF_MIRROR / HF_OFFICIAL.
# Legacy CLI aliases remain accepted and are normalized here.
$Source = switch -Regex ($Source) {
    '^(?i)auto$' { "AUTO" }
    '^(?i)modelscope$' { "MODELSCOPE" }
    '^(?i)hfmirror|hf[_-]?mirror$' { "HF_MIRROR" }
    '^(?i)huggingface|hf[_-]?official$' { "HF_OFFICIAL" }
    default { $Source.ToUpperInvariant() }
}
if ($Source -eq "HF_MIRROR") {
    $env:HF_ENDPOINT = "https://hf-mirror.com"
} elseif ($Source -eq "HF_OFFICIAL") {
    $env:HF_ENDPOINT = "https://huggingface.co"
} elseif ($Source -eq "AUTO" -and -not $env:HF_ENDPOINT) {
    $env:HF_ENDPOINT = "https://hf-mirror.com"
}
Write-Host "[网络] 下载源：$Source" -ForegroundColor Cyan
Write-Host '[2BYTEASR_PHASE] {"phase":"preparing"}'
# 镜像下载大文件较慢，放宽读/连接超时（默认值会导致大文件中途 ReadTimeout）
if (-not $env:HF_HUB_DOWNLOAD_TIMEOUT) { $env:HF_HUB_DOWNLOAD_TIMEOUT = "300" }
if (-not $env:HF_HUB_ETAG_TIMEOUT) { $env:HF_HUB_ETAG_TIMEOUT = "60" }
# HF 新模型走 Xet 存储协议（cas-server.xethub.hf.co），国内无代理时
# 认证 401 且“Writing request stream”极慢；禁用后回退传统 HTTPS 下载
# （断点续传同样支持），由 hf-mirror/官方 CDN 提供。
if (-not $env:HF_HUB_DISABLE_XET) { $env:HF_HUB_DISABLE_XET = "1" }

function Resolve-ProjectPath {
    param([string]$RelativePath)
    $normalized = $RelativePath -replace '/', '\'
    if ($normalized -like 'models\*') {
        $leaf = Split-Path -Leaf $normalized
        return Join-Path $ModelsRoot $leaf
    }
    return Join-Path $ProjectRoot $normalized
}

function Test-ModelFiles {
    param($Spec, [switch]$VerifyHashes)
    $root = Resolve-ProjectPath $Spec.path
    foreach ($relative in $Spec.required_files) {
        $requiredPath = Join-Path $root ($relative -replace '/', '\')
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            return $false
        }
        if ((Get-Item -LiteralPath $requiredPath).Length -le 0) {
            return $false
        }
    }
    if ($VerifyHashes -and $Spec.sha256) {
        foreach ($property in $Spec.sha256.PSObject.Properties) {
            $path = Join-Path $root ($property.Name -replace '/', '\')
            if (-not (Test-Path -LiteralPath $path)) { return $false }
            $stream=[IO.File]::OpenRead($path)
            $hasher=[Security.Cryptography.SHA256]::Create()
            try { $actual=[BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-','') }
            finally { $stream.Dispose(); $hasher.Dispose() }
            if ($actual -ne [string]$property.Value) { return $false }
        }
    }
    return $true
}

function Test-ModelRevisionMetadata {
    param($Spec)
    $root = Resolve-ProjectPath $Spec.path
    $treeMetadata = Join-Path $root ".cache\huggingface\trees\$($Spec.revision).json"
    return Test-Path -LiteralPath $treeMetadata
}

function Test-AllRequiredFilesHashed {
    param($Spec)
    if (-not $Spec.sha256) { return $false }
    $hashed = @($Spec.sha256.PSObject.Properties | ForEach-Object { $_.Name })
    foreach ($relative in $Spec.required_files) {
        if ([string]$relative -notin $hashed) { return $false }
    }
    return $true
}

function Read-Manifest {
    if (-not (Test-Path $ManifestPath)) { return @{} }
    try {
        $payload = Get-Content -Raw -Encoding UTF8 $ManifestPath | ConvertFrom-Json
        $result = @{}
        foreach ($property in $payload.models.PSObject.Properties) {
            $result[$property.Name] = [string]$property.Value
        }
        return $result
    } catch {
        return @{}
    }
}

function Write-Manifest {
    param([hashtable]$Installed)
    $models = [ordered]@{}
    foreach ($key in ($Installed.Keys | Sort-Object)) { $models[$key] = $Installed[$key] }
    $payload = [ordered]@{
        schema_version = 1
        updated_at = (Get-Date).ToString("o")
        models = $models
    }
    $directory = Split-Path -Parent $ManifestPath
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $tempPath = "$ManifestPath.tmp"
    $payload | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $tempPath
    Move-Item -Force $tempPath $ManifestPath
}

function Get-ModelScopeEndpoint {
    param([Parameter(Mandatory = $true)]$Spec)
    $repository = ""
    if ($ModelscopeOrg) {
        $repository = "$ModelscopeOrg/$($Spec.repository.Split('/')[-1])"
    } elseif ($Spec.modelscope_repository) {
        $repository = [string]$Spec.modelscope_repository
    }
    if (-not $repository) { return $null }
    $revision = if ($Spec.modelscope_revision) { [string]$Spec.modelscope_revision } else { "master" }
    return [pscustomobject]@{
        Base = "https://modelscope.cn/api/v1/models/$repository/repo"
        Revision = $revision
        Repository = $repository
    }
}

function Get-ResolvedArtifactSources {
    param(
        [Parameter(Mandatory = $true)][string]$ModelKey,
        [Parameter(Mandatory = $true)][string]$Relative,
        [Parameter(Mandatory = $true)][string]$Mode
    )
    $resolverPython = Join-Path $ProjectRoot ".venv-main\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $resolverPython)) {
        $resolverPython = Join-Path $ProjectRoot ".venv-moss\Scripts\python.exe"
    }
    if (-not (Test-Path -LiteralPath $resolverPython)) { $resolverPython = "python" }
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        Push-Location $ProjectRoot
        $json = & $resolverPython -m twobyteasr.download_sources `
            --model $ModelKey --file $Relative --mode $Mode --lock $LockPath 2>$null
        $code = $LASTEXITCODE
    } finally {
        Pop-Location -ErrorAction SilentlyContinue
        $ErrorActionPreference = $previous
    }
    if ($code -eq 2) {
        return @()
    }
    if ($code -ne 0 -or -not $json) {
        throw "无法解析下载源（$ModelKey / $Relative / $Mode）"
    }
    return @(ConvertFrom-Json -InputObject ([string]$json))
}

function Get-ModelDownloadFiles {
    param([Parameter(Mandatory = $true)]$Spec)
    $files = @($Spec.required_files | ForEach-Object { [string]$_ })
    if ($Spec.sha256) {
        $files += @($Spec.sha256.PSObject.Properties | ForEach-Object { [string]$_.Name })
    }
    return @($files | Select-Object -Unique)
}

function Invoke-DirectModelFallback {
    param(
        [Parameter(Mandatory = $true)][string]$ModelKey,
        [Parameter(Mandatory = $true)]$Spec,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Mode
    )
    $repositoryPython = $env:TWOBYTEASR_MAIN_PYTHON
    if (-not $repositoryPython) { $repositoryPython = Join-Path $ProjectRoot ".venv-main\Scripts\python.exe" }
    if (-not (Test-Path -LiteralPath $repositoryPython)) {
        throw "缺少主工作台 Python，无法启动官方仓库下载 Adapter。"
    }
    Push-Location $ProjectRoot
    try {
        Write-Host '[2BYTEASR_PHASE] {"phase":"weights_downloading"}'
        & $repositoryPython -I (Join-Path $PSScriptRoot 'run_repository_download.py') `
            --model $ModelKey --mode $Mode --lock $LockPath --destination $Destination `
            --staging-root (Join-Path $ModelsRoot '.downloads') | ForEach-Object { Write-Host $_ }
        return $LASTEXITCODE -eq 0
    } finally {
        Pop-Location -ErrorAction SilentlyContinue
    }
}


if (-not (Test-Path $LockPath)) { throw "缺少依赖版本清单：$LockPath" }
$Lock = Get-Content -Raw -Encoding UTF8 $LockPath | ConvertFrom-Json
$Installed = Read-Manifest

$modelSpecs = @()
foreach ($property in $Lock.models.PSObject.Properties) {
    $modelSpecs += [pscustomobject]@{ Name = $property.Name; Spec = $property.Value }
}

# GUI 模型工坊可以只安装用户点击的模型。MOSS 是主流程骨架，运行时还依赖
# FireRedVAD 与说话人嵌入，因此选择 moss 时自动补齐这两个轻量依赖。
$allowedOnlyNames = @(
    "moss", "firered_vad", "firered_aed", "qwen_asr", "speaker_embedding",
    "qwen_aligner", "whisper_turbo", "sensevoice", "paraformer", "funasr_nano",
    "firered_llm", "glm_asr_nano", "canary_qwen", "omni_asr_llm_7b", "nemotron"
)
$onlyNames = @(
    $Only -split ',' |
        ForEach-Object { ([string]$_).Trim() } |
        Where-Object { $_ }
)
$unsupportedOnlyNames = @($onlyNames | Where-Object { $_ -notin $allowedOnlyNames })
if ($unsupportedOnlyNames.Count -gt 0) {
    throw "不支持的模型标识：$($unsupportedOnlyNames -join '、')"
}
if ("moss" -in $onlyNames) {
    $onlyNames += @("firered_vad", "speaker_embedding")
}
if ('canary_qwen' -in $onlyNames) { $onlyNames += 'canary_qwen_tokenizer' }
$onlyNames = @($onlyNames | Select-Object -Unique)
if ("qwen_asr" -in $onlyNames) { $IncludeQwen = $true }

# Qwen3-ASR 复核模型（约 4.7 GB）为可选附加：默认方案为
# MOSS/说话人/FireRed 字级时间轴（约 7 GB）。交互确认、-IncludeQwen
# 参数或环境变量 2BYTEASR_INCLUDE_QWEN=1 时包含；
# 模型已存在时自动纳入校验，不再提问。
if (-not $IncludeQwen -and $env:2BYTEASR_INCLUDE_QWEN) { $IncludeQwen = $true }
$qwenSpec = $Lock.models.qwen_asr
if (-not $IncludeQwen -and $qwenSpec -and (Test-ModelFiles $qwenSpec)) {
    $IncludeQwen = $true
    Write-Host "[跳过] 检测到 Qwen3-ASR 模型已存在，纳入校验。" -ForegroundColor Green
}
if (-not $IncludeQwen -and -not $Yes -and -not $VerifyOnly) {
    $answer = Read-Host "下载本地 Qwen3-ASR（约 4.7 GB；精度更高并增加独立词汇证据；不下载则使用更快的 API，需自行配置 Key）？[y/N]"
    if ($answer -match "^[yY]") { $IncludeQwen = $true }
}
if (-not $IncludeQwen) {
    $modelSpecs = @($modelSpecs | Where-Object { $_.Name -ne "qwen_asr" })
}

# 模型工坊中的扩展模型只在用户点击下载（-Only）时处理；传统安装流程
# 仍保持 MOSS + FireRed + 声纹，以及用户可选的 Qwen3-ASR，不扩大默认体积。
if ($onlyNames.Count -eq 0) {
    $defaultNames = @("moss", "firered_vad", "firered_aed", "qwen_asr", "speaker_embedding")
    $modelSpecs = @($modelSpecs | Where-Object { $_.Name -in $defaultNames })
}

# 极简模式（-Minimal / 2BYTEASR_MINIMAL_MODELS=1）：只下基础链路
# MOSS 转写/说话人 + VAD + 声纹（约 2 GB），FireRed 字级时间轴后续用
# download_models.bat 补下；运行任务时缺少 FireRed 会得到明确提示。
if (-not $Minimal -and $env:2BYTEASR_MINIMAL_MODELS) { $Minimal = $true }
if ($Minimal -and $onlyNames.Count -eq 0) {
    $minimalNames = @("moss", "firered_vad", "speaker_embedding")
    $modelSpecs = @($modelSpecs | Where-Object { $_.Name -in $minimalNames })
    Write-Host "[极简] 只下载基础链路（MOSS + VAD + 声纹，约 2 GB）；FireRed 可稍后用 download_models.bat 补下。" -ForegroundColor Yellow
}

if ($onlyNames.Count -gt 0) {
    $modelSpecs = @($modelSpecs | Where-Object { $_.Name -in $onlyNames })
    Write-Host "[模型工坊] 只处理：$($modelSpecs.Name -join '、')" -ForegroundColor Cyan
}

# MOSS 是默认主力模型，而且它的官方 ModelScope 仓库已经声明并验证。
# 优先下载它，让用户尽快拿到核心能力；后续辅助模型失败不会挡住 MOSS。
$modelSpecs = @($modelSpecs | Sort-Object { if ($_.Name -eq "moss") { 0 } else { 1 } })

# 模型权重与 Python 引擎都按需安装。首次 Setup 只创建工作台；用户点击
# 某个模型后，下载窗口在同一次流程中补齐该模型需要的 Torch/FunASR/
# MOSS 环境。已经安装好的依赖会被 uv 快速复用。
if (-not $VerifyOnly) {
    $backendSetup = Join-Path $PSScriptRoot "setup_model_backend.ps1"
    $backendKeys = @($modelSpecs | Where-Object { -not $_.Spec.resource_only } | ForEach-Object { [string]$_.Name } | Select-Object -Unique)
    if ($backendKeys.Count -gt 0) {
        $hasRuntimeInstall = @($backendKeys | Where-Object {
            $_ -notin @("firered_llm", "glm_asr_nano", "canary_qwen", "omni_asr_llm_7b", "nemotron")
        }).Count -gt 0
        if ($hasRuntimeInstall) {
            Write-Host '[2BYTEASR_PHASE] {"phase":"runtime_installing"}'
        }
        Write-Host "[运行库] 正在准备所选模型环境：$($backendKeys -join '、')" -ForegroundColor Cyan
        & $backendSetup -ModelKey $backendKeys
        if ($LASTEXITCODE -ne 0) {
            throw "所选模型运行库安装失败（退出码 $LASTEXITCODE）。已下载内容会保留，修复网络后可直接重试。"
        }
        if ($hasRuntimeInstall) {
            Write-Host '[2BYTEASR_PHASE] {"phase":"runtime_ready"}'
        }
    }
}

if ($VerifyOnly) {
    $failed = @()
    foreach ($entry in $modelSpecs) {
        $filesOk = Test-ModelFiles $entry.Spec -VerifyHashes
        $revisionOk = $Installed[$entry.Name] -eq [string]$entry.Spec.revision `
            -or (Test-ModelRevisionMetadata $entry.Spec) `
            -or (Test-AllRequiredFilesHashed $entry.Spec)
        $status = if ($filesOk -and $revisionOk) { "OK" } elseif ($filesOk) { "文件与哈希正确，版本未登记" } else { "缺文件或哈希不匹配" }
        Write-Host "[$status] $($entry.Spec.repository)"
        if (-not $filesOk) { $failed += $entry.Name }
    }
    if ($failed.Count -gt 0) { exit 1 }
    exit 0
}

$driveName = ([System.IO.Path]::GetPathRoot($ModelsRoot)).TrimEnd('\').TrimEnd(':')
$drive = Get-PSDrive -Name $driveName
$freeGb = [math]::Round($drive.Free / 1GB, 1)
$missingModels = @($modelSpecs | Where-Object { -not (Test-ModelFiles $_.Spec -VerifyHashes) })
function Confirm-PreparedModels {
    foreach ($entry in $modelSpecs) {
        if ($entry.Spec.resource_only) { continue }
        & $env:TWOBYTEASR_MAIN_PYTHON -I (Join-Path $PSScriptRoot 'validate_prepared_model.py') --root $ProjectRoot --model $entry.Name
        if ($LASTEXITCODE -ne 0) {
            throw "模型文件已校验，但实际加载或样本任务失败：$($entry.Name)。请查看 model_loading 阶段日志；文件与运行库可复用。"
        }
    }
}
Write-Host "2ByteASR 模型下载" -ForegroundColor Cyan
if ($missingModels.Count -eq 0) {
    Write-Host "- 模型已全部就绪，无需下载。" -ForegroundColor Green
    Write-Host "- 已核对必需文件与已发布校验值，复用有效文件。" -ForegroundColor DarkGray
    Confirm-PreparedModels
    exit 0
} else {
    Write-Host "- 需下载 $($missingModels.Count) 个模型：$($missingModels.Name -join '、')"
    $expectedBytes = [double](@($missingModels | ForEach-Object {
        if ($_.Spec.download_bytes) { [double]$_.Spec.download_bytes } else { 0 }
    }) | Measure-Object -Sum).Sum
    $requiredFreeBytes = if ($expectedBytes -gt 0) {
        [math]::Max(2GB, [math]::Ceiling($expectedBytes * 1.05))
    } else {
        15GB
    }
    $requiredFreeGb = [math]::Round($requiredFreeBytes / 1GB, 1)
    Write-Host "- 预计下载约 $([math]::Round($expectedBytes / 1GB, 2)) GiB；建议至少保留 $requiredFreeGb GiB 可用空间。"
    Write-Host "- 缺失或损坏文件会重新获取；有效缓存会保留。" -ForegroundColor Yellow
}
Write-Host "- 当前项目盘剩余约 $freeGb GB。"
Write-Host "- 下载可中断；重新运行会复用 Hugging Face 已完成的文件。"
$hasMissingFiles = $missingModels.Count -gt 0
if ($hasMissingFiles -and $drive.Free -lt $requiredFreeBytes) {
    throw "磁盘空间不足 $requiredFreeGb GiB，请清理空间后重试。"
}

if (-not $Yes) {
    $answer = Read-Host "开始下载？[Y/n]（回车默认继续）"
    if ($answer -match "^(n|N|no|NO)$") {
        Write-Host "已取消，未下载模型。"
        exit 0
    }
}

foreach ($entry in $modelSpecs) {
    $name = $entry.Name
    $spec = $entry.Spec
    $filesAndHashesOk = Test-ModelFiles $spec -VerifyHashes
    $revisionOk = $Installed[$name] -eq [string]$spec.revision `
        -or (Test-ModelRevisionMetadata $spec) `
        -or (Test-AllRequiredFilesHashed $spec)
    if ($filesAndHashesOk -and $revisionOk) {
        if ($Installed[$name] -ne [string]$spec.revision) {
            $Installed[$name] = [string]$spec.revision
            Write-Manifest $Installed
        }
        Write-Host "[跳过] $($spec.repository) 已是固定版本。"
        continue
    }
    $destination = Resolve-ProjectPath $spec.path
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    # 保留 Hugging Face 的 .cache：其中包含未完成的大文件分块；用户点击重试时
    # hf 客户端可以从断点继续。若客户端重试仍失败，下方直链下载器会绕过该缓存。
    Write-Host "[下载] $($spec.repository) @ $($spec.revision)"
    $downloaded = $false
    if ($Source -eq "MODELSCOPE") {
        Write-Host "[指定源] 只使用 ModelScope，失败不会改走 Hugging Face。" -ForegroundColor Cyan
        $downloaded = Invoke-DirectModelFallback $name $spec $destination $Source
        if ($downloaded -and -not (Test-ModelFiles $spec -VerifyHashes)) {
            Write-Warning "ModelScope 文件不完整或哈希不匹配。"
            $downloaded = $false
        }
        if (-not $downloaded) {
            throw "ModelScope 下载失败或该模型没有可用的 ModelScope 仓库。请更换下载源后重试；已完成分片会保留。"
        }
    } elseif ($Source -in @("AUTO", "HF_MIRROR", "HF_OFFICIAL")) {
        if ($Source -eq "AUTO") {
            Write-Host "[自动] 按顺序尝试 ModelScope（若 lock 已声明）→ HF 镜像 → HF 官方；每个源失败后最多再试 1 次。" -ForegroundColor Cyan
        } else {
            Write-Host "[指定源] 只使用 $Source，失败不会静默改走其他源。" -ForegroundColor Cyan
        }
        $downloaded = Invoke-DirectModelFallback $name $spec $destination $Source
        if ($downloaded -and -not (Test-ModelFiles $spec -VerifyHashes)) {
            Write-Warning "下载的文件不完整或哈希不匹配。"
            $downloaded = $false
        }
    }
    if ($Source -eq "MODELSCOPE" -and -not $downloaded) {
        throw "ModelScope 下载失败或该模型没有可用的 ModelScope 仓库。请更换下载源后重试。"
    }
    if ($name -eq "moss" -and $Source -eq "AUTO" -and -not $downloaded) {
        Write-Host "[MOSS] 顺序回退仍未完成。已完成分片会保留，不会改删。" -ForegroundColor Yellow
        throw @"
MOSS 大模型在当前网络下无法从已声明来源持续传输。
不需要重新安装：已完成分片会保留，恢复网络后在本窗口点击“继续重试”，或更换下载源。
"@
    }
    if (-not $downloaded) {
        throw "模型下载失败。请检查网络后重试，或更换下载源。已完成分片会保留。"
    }
    if (-not (Test-ModelFiles $spec -VerifyHashes)) {
        throw "模型下载结束但关键文件缺失或 SHA-256 不匹配：$($spec.repository)`n请点击校验并修复；有效文件保留，损坏文件会安全重下。"
    }
    if ($name -eq "speaker_embedding") {
        $customPath = Join-Path $destination "custom.py"
        if (-not (Test-Path $customPath)) { New-Item -ItemType File -Path $customPath | Out-Null }
    }
    $Installed[$name] = [string]$spec.revision
    Write-Manifest $Installed
}

Write-Host ""
Confirm-PreparedModels
Write-Host "[完成] 模型文件、运行库与适用的本地加载验证已完成。" -ForegroundColor Green
