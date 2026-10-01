# Repair Mode helpers: role-specific staging venv from the deployment lock.
# Dot-source this file to load functions.  Running as a script installs one
# staging environment and never mutates the live .venv-<role> in place.
#
# 普通 setup 的 marker 早退不在本文件；Test-RepairShouldProceed 只回答
# “Repair 是否应继续 / 无 -Repair 时 marker 是否应跳过”。

$ErrorActionPreference = "Stop"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
try { [Console]::OutputEncoding = $Utf8NoBom } catch {}
$OutputEncoding = $Utf8NoBom
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

. (Join-Path $PSScriptRoot "environment-lock.ps1")

function Test-RepairShouldProceed {
    param(
        [switch]$Repair,
        [switch]$SetupMarkerPresent
    )
    return [bool]($Repair -or -not $SetupMarkerPresent)
}

function Get-RepairTorchSpec {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("main", "moss", "firered_llm", "nemotron")][string]$Role,
        [string]$ProjectRoot = ""
    )
    return (Get-EnvironmentDependency -Role $Role -Name "torch" -ProjectRoot $ProjectRoot)
}

function Get-RepairLivePath {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("main", "moss", "firered_llm", "nemotron")][string]$Role,
        [string]$ProjectRoot = ""
    )
    if (-not $ProjectRoot) { $ProjectRoot = (Split-Path -Parent $PSScriptRoot) }
    $directory = if ($Role -eq "firered_llm") { ".venv-firered-llm" } else { ".venv-$Role" }
    return (Join-Path $ProjectRoot $directory)
}

function Get-RepairStagingPath {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("main", "moss", "firered_llm", "nemotron")][string]$Role,
        [string]$ProjectRoot = ""
    )
    if (-not $ProjectRoot) { $ProjectRoot = (Split-Path -Parent $PSScriptRoot) }
    return ((Get-RepairLivePath -Role $Role -ProjectRoot $ProjectRoot) + ".new")
}

function Resolve-RepairCreatorPython {
    param(
        [Parameter(Mandatory = $true)][string]$MajorMinor,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$LivePython
    )
    if ($LivePython -and (Test-Path -LiteralPath $LivePython)) {
        return $LivePython
    }
    $short = $MajorMinor -replace '\.', ''
    foreach ($base in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python"),
        (Join-Path $env:ProgramFiles "Python")
    )) {
        $candidate = Join-Path (Join-Path $base "Python$short") "python.exe"
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    foreach ($root in @(
        "HKLM:\SOFTWARE\Python\PythonCore\$MajorMinor\InstallPath",
        "HKCU:\SOFTWARE\Python\PythonCore\$MajorMinor\InstallPath"
    )) {
        $reg = Get-ItemProperty $root -ErrorAction SilentlyContinue
        if ($reg -and $reg.'(default)') {
            $candidate = Join-Path $reg.'(default)' "python.exe"
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
    }
    return ""
}

function Install-RepairRoleStaging {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("main", "moss", "firered_llm", "nemotron")][string]$Role,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [string]$StagingPath = ""
    )
    if (-not $StagingPath) {
        $StagingPath = Get-RepairStagingPath -Role $Role -ProjectRoot $ProjectRoot
    }
    $livePath = Get-RepairLivePath -Role $Role -ProjectRoot $ProjectRoot
    $resolvedLive = [IO.Path]::GetFullPath($livePath)
    $resolvedStaging = [IO.Path]::GetFullPath($StagingPath)
    if ($resolvedStaging.Equals($resolvedLive, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Repair refuses to write into live directory: $StagingPath"
    }
    $contract = Get-EnvironmentContract -Role $Role -ProjectRoot $ProjectRoot
    $pythonVersion = [string]$contract.python
    $torchVersion = [string]$contract.torch
    if ($torchVersion -ne "2.11.0") {
        throw "deployment lock torch for $Role must be 2.11.0, got $torchVersion"
    }
    $livePython = Join-Path $livePath "Scripts\python.exe"
    $creator = Resolve-RepairCreatorPython $pythonVersion $ProjectRoot $livePython
    if (-not $creator) {
        throw "Cannot find Python $pythonVersion to create $Role repair environment. Original environment not modified."
    }

    if (Test-Path -LiteralPath $StagingPath) {
        try { Remove-Item -LiteralPath $StagingPath -Recurse -Force -ErrorAction Stop } catch {
            throw "Cannot remove previous staging directory (may be locked): $StagingPath. Error: $($_.Exception.Message). Original environment not modified."
        }
    }
    Write-Host "[Repair] Creating venv: $creator -m venv $StagingPath"
    $venvOut = & $creator -m venv $StagingPath 2>&1
    $code = $LASTEXITCODE
    $stagingPy = Join-Path $StagingPath "Scripts\python.exe"
    if ($code -ne 0 -or -not (Test-Path -LiteralPath $stagingPy)) {
        $log = ($venvOut | Out-String).Trim()
        throw "Failed to create staging venv (exit $code): $StagingPath`n$log`nOriginal environment not modified."
    }
    Write-Host "[Repair] Created staging python at: $stagingPy"
    try { Write-Host ("[Repair] Staging python version: " + (& $stagingPy --version 2>&1)) } catch {}

    $wheelsDir = Join-Path $ProjectRoot "wheels"
    $hasWheelsDir = Test-Path -LiteralPath $wheelsDir
    $hasTorchWheel = $false
    if ($hasWheelsDir) {
        $tw = Get-ChildItem -LiteralPath $wheelsDir -Filter "torch-2.11.0*" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($tw) { $hasTorchWheel = $true }
    }
    $pypiArgs = @()
    if ($hasWheelsDir) { $pypiArgs = @("--find-links", $wheelsDir) }
    $torchOfflineArgs = @()
    if ($hasWheelsDir) {
        if ($hasTorchWheel) { $torchOfflineArgs = @("--no-index", "--find-links", $wheelsDir) }
        else { $torchOfflineArgs = @("--find-links", $wheelsDir) }
    }

    $packageSpecs = @(Get-EnvironmentPackages -Role $Role -ProjectRoot $ProjectRoot)
    $audioVersion = [string]$contract.torchaudio
    $contractPackageSpecs = $packageSpecs

    # Load full lock for runtime cuda tags (Single Source of Truth, top-level "runtime").
    $fullLockPath = Join-Path $ProjectRoot "dependencies.lock.json"
    $rt = $null
    if (Test-Path -LiteralPath $fullLockPath) {
        try {
            $full = Get-Content -LiteralPath $fullLockPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($full -and $full.runtime) { $rt = $full.runtime }
        } catch {}
    }

    # P0: MOSS contract must use CUDA-enabled torch on machines with NVIDIA GPU.
    # main may use CPU-compatible. If CUDA wheel install fails for moss, we must fail the repair (preserve original).
    $gpuPresent = (Get-Command nvidia-smi -ErrorAction SilentlyContinue) -and -not $env:2BYTEASR_CPU_ONLY
    $gpuOnlyRole = $Role -in @("moss", "firered_llm")
    if ($gpuOnlyRole -and -not $gpuPresent) {
        throw "$Role requires an NVIDIA CUDA runtime. Original environment preserved."
    }
    if ($gpuOnlyRole -and $gpuPresent) {
        # Choose tag: cu128 for Blackwell/RTX 50 (cc >= 12) if declared, else cuda_wheel.
        $tag = $null
        try {
            $cap = & nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null | Select-Object -First 1
            $majText = ([string]$cap -split '\.')[0] -replace '[^0-9]', ''
            $maj = 0; [void][int]::TryParse($majText, [ref]$maj)
            if ($maj -ge 12 -and $rt -and $rt.cuda_wheel_modern) { $tag = [string]$rt.cuda_wheel_modern }
        } catch {}
        if (-not $tag) {
            if ($rt -and $rt.cuda_wheel) { $tag = [string]$rt.cuda_wheel } else { $tag = "cu126" }
        }
        $torchSpecs = @("torch==$torchVersion+$tag", "torchaudio==$audioVersion+$tag")
        $torchOfflineArgs = @()
        if ($hasWheelsDir) {
            $pat = "torch-2.11.0*$tag*"
            $tw = Get-ChildItem -LiteralPath $wheelsDir -Filter $pat -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($tw) { $torchOfflineArgs = @("--no-index", "--find-links", $wheelsDir) }
            else { $torchOfflineArgs = @("--find-links", $wheelsDir) }
        }
        Write-Host "[Repair] $Role will target CUDA torch $torchVersion+$tag (wheels hint: $($torchOfflineArgs -join ' '))" -ForegroundColor Cyan
    } else {
        $torchSpecs = @("torch==$torchVersion", "torchaudio==$audioVersion")
    }
    $installSpecs = $contractPackageSpecs + $torchSpecs

    foreach ($spec in $installSpecs) {
        if (-not $spec) { throw "Empty package spec detected. Aborting repair. Original environment not modified." }
        $s = [string]$spec
        if ($s -eq "+" -or $s.StartsWith("+")) { throw "Illegal package spec '$s'. Aborting. Original environment preserved." }
        if ($s -notmatch '^[A-Za-z0-9]') { throw "Package spec does not start with alphanumeric: '$s'. Aborting. Original environment preserved." }
    }

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        function Invoke-UvInstall { param([string[]]$ArgsList)
            Write-Host ("[Repair][uv] " + ($ArgsList -join ' '))
            & $uv.Source $ArgsList
            return $LASTEXITCODE
        }
        $pipBase = @("pip","install","--python",$stagingPy)
        if ((Invoke-UvInstall ($pipBase + @("pip==26.1.2") + $pypiArgs)) -ne 0) { throw "Failed to bootstrap pip in staging." }
        if ($contractPackageSpecs.Count -gt 0) {
            if ((Invoke-UvInstall ($pipBase + $contractPackageSpecs + $pypiArgs)) -ne 0) { throw "Failed to install contract packages for $Role." }
        }
        if ((Invoke-UvInstall ($pipBase + $torchSpecs + $torchOfflineArgs)) -ne 0) {
            throw "Failed to install torch family for $Role (must be $torchVersion with CUDA for GPU-only runtimes). Original environment preserved."
        }
        if ($Role -eq "main") {
            $req = Join-Path $ProjectRoot "requirements-main.txt"
            if (Test-Path -LiteralPath $req) {
                if ((Invoke-UvInstall ($pipBase + @("-r",$req) + $pypiArgs)) -ne 0) { throw "Failed to install requirements-main.txt" }
            }
        }
        if ($Role -eq "moss") {
            $mossSrc = Join-Path $ProjectRoot "third_party\MOSS-Transcribe-Diarize"
            if (Test-Path -LiteralPath $mossSrc) {
                if ((Invoke-UvInstall ($pipBase + @("-e","$mossSrc[torch-runtime]") + $pypiArgs)) -ne 0) { throw "Failed to install MOSS editable package" }
            }
        }
        # Repin after editable to guarantee exact lock pins for deep preflight
        if ($contractPackageSpecs.Count -gt 0) {
            if ((Invoke-UvInstall ($pipBase + $contractPackageSpecs + $pypiArgs)) -ne 0) { throw "Failed to repin $Role packages to contract versions after edits." }
        }
        if ((Invoke-UvInstall ($pipBase + $torchSpecs + $torchOfflineArgs)) -ne 0) { throw "Failed to repin $Role torch to contract version after edits." }
        if (-not (Test-Path -LiteralPath $stagingPy)) { throw "Staging python missing after install: $stagingPy. Original not modified." }
        return
    }

    # Fallback: python -m pip
    Write-Host ("[Repair][pip] " + $stagingPy + " -m pip install pip==26.1.2 " + ($pypiArgs -join ' '))
    & $stagingPy -m pip install pip==26.1.2 @pypiArgs
    if ($LASTEXITCODE -ne 0) { throw "Failed to bootstrap pip (fallback)." }
    if ($contractPackageSpecs.Count -gt 0) {
        & $stagingPy -m pip install @contractPackageSpecs @pypiArgs
        if ($LASTEXITCODE -ne 0) { throw "Failed to install contract packages (fallback)." }
    }
    & $stagingPy -m pip install @torchSpecs @torchOfflineArgs
    if ($LASTEXITCODE -ne 0) { throw "Failed to install torch (fallback)." }
    if ($Role -eq "main") {
        $req = Join-Path $ProjectRoot "requirements-main.txt"
        if (Test-Path -LiteralPath $req) {
            & $stagingPy -m pip install -r $req @pypiArgs
            if ($LASTEXITCODE -ne 0) { throw "Failed to install requirements-main (fallback)." }
        }
    }
    if ($Role -eq "moss") {
        $mossSrc = Join-Path $ProjectRoot "third_party\MOSS-Transcribe-Diarize"
        if (Test-Path -LiteralPath $mossSrc) {
            & $stagingPy -m pip install -e "$mossSrc[torch-runtime]" @pypiArgs
            if ($LASTEXITCODE -ne 0) { throw "Failed to install MOSS editable (fallback)." }
        }
    }
    if ($Role -eq "moss") {
        if ($contractPackageSpecs.Count -gt 0) { & $stagingPy -m pip install @contractPackageSpecs @pypiArgs; if ($LASTEXITCODE -ne 0) { throw "Repin failed (fallback)." } }
        & $stagingPy -m pip install @torchSpecs @torchOfflineArgs
        if ($LASTEXITCODE -ne 0) { throw "Torch repin failed (fallback)." }
    }
    if (-not (Test-Path -LiteralPath $stagingPy)) { throw "Staging python missing after pip install: $stagingPy. Original not modified." }
}

function Invoke-EnvironmentRepair {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot, [string[]]$Role = @())
    $candidates = @(
        (Join-Path $ProjectRoot ".venv-main\Scripts\python.exe"),
        (Join-Path $ProjectRoot ".venv-moss\Scripts\python.exe")
    )
    $python = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $python) { throw "No python available to start repair. Original environment not modified." }
    $argumentList = @("-m", "twobyteasr.environment_repair") + @($Role)
    $previousEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        Push-Location $ProjectRoot
        # Route every native output line to the Host/Transcript stream instead
        # of returning it from this function. This keeps progress live while
        # ensuring callers receive exactly one scalar integer exit code.
        & $python @argumentList 2>&1 | ForEach-Object { Write-Host ([string]$_) }
        $exitCode = $LASTEXITCODE
        return [int]$exitCode
    } finally {
        Pop-Location -ErrorAction SilentlyContinue
        $ErrorActionPreference = $previousEap
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    if ($Role -and $ProjectRoot) {
        if (-not $StagingPath) { $StagingPath = Get-RepairStagingPath -Role $Role -ProjectRoot $ProjectRoot }
        Install-RepairRoleStaging -Role $Role -ProjectRoot $ProjectRoot -StagingPath $StagingPath
        exit $LASTEXITCODE
    }
}
