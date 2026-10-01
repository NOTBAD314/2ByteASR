[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Lock = Get-Content -Raw -Encoding UTF8 (Join-Path $ProjectRoot "dependencies.lock.json") | ConvertFrom-Json
$Contract = $Lock.environments.firered_llm
$Uv = Join-Path $ProjectRoot "tools\uv.exe"
$MainPython = Join-Path $ProjectRoot ".venv-main\Scripts\python.exe"
$Target = Join-Path $ProjectRoot ".venv-firered-llm"
$Python = Join-Path $Target "Scripts\python.exe"
$Wheels = Join-Path $ProjectRoot "wheels"
$env:UV_CACHE_DIR = Join-Path $ProjectRoot "tmp\uv-cache"

if (-not (Test-Path -LiteralPath $Uv)) { throw "Missing tools\uv.exe." }
if (-not (Test-Path -LiteralPath $MainPython)) { throw "Missing .venv-main Python." }

Write-Host '[2BYTEASR_PHASE] {"phase":"runtime_installing"}'
if (-not (Test-Path -LiteralPath $Python)) {
    & $Uv venv --python $MainPython $Target
    if ($LASTEXITCODE -ne 0) { throw "Unable to create .venv-firered-llm." }
}

$computeMajor = 0
try {
    $capability = & nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null | Select-Object -First 1
    [void][int]::TryParse((([string]$capability -split '\.')[0] -replace '[^0-9]', ''), [ref]$computeMajor)
} catch {}
$cudaTag = if ($computeMajor -ge 12) { [string]$Lock.runtime.cuda_wheel_modern } else { [string]$Lock.runtime.cuda_wheel }
$packages = @(
    "torch==$($Contract.torch)+$cudaTag",
    "torchaudio==$($Contract.torchaudio)+$cudaTag"
)
foreach ($property in $Contract.packages.PSObject.Properties) {
    $packages += "$($property.Name)==$($property.Value)"
}
$arguments = @(
    "pip", "install", "--python", $Python,
    "--index", "https://download.pytorch.org/whl/$cudaTag",
    "--default-index", "https://pypi.org/simple"
)
if (Test-Path -LiteralPath $Wheels) {
    $arguments += @("--find-links", $Wheels)
}
$arguments += $packages
& $Uv @arguments
if ($LASTEXITCODE -ne 0) { throw "FireRed LLM Runtime dependency installation failed." }

Write-Host '[2BYTEASR_PHASE] {"phase":"adapter_verifying"}'
$source = Join-Path $ProjectRoot "third_party\FireRedASR2S"
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $source
    & $Python -c "import torch; from fireredasr2s.fireredasr2 import FireRedAsr2; assert torch.cuda.is_available(); print('[FireRed LLM Runtime] import + CUDA ready')"
    if ($LASTEXITCODE -ne 0) { throw "FireRed LLM Adapter import/CUDA probe failed." }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
Write-Host '[2BYTEASR_PHASE] {"phase":"runtime_ready"}'
