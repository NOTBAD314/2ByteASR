# Native bootstrap; no Python, developer checkout, PATH edit or registry install.
[CmdletBinding()]
param([string]$ModelRoot = '', [string]$Sample = '', [switch]$BootstrapOnly,
      [ValidateSet('AUTO','HF_OFFICIAL','HF_MIRROR','MODELSCOPE')][string]$Source = 'AUTO')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$utf8 = [System.Text.UTF8Encoding]::new($false)
try { [Console]::OutputEncoding = $utf8 } catch {}
$OutputEncoding = $utf8
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$dataBase = if ($env:2BYTEASR_USER_DATA_ROOT) { $env:2BYTEASR_USER_DATA_ROOT } else { $env:LOCALAPPDATA }
$managed = Join-Path $dataBase '2ByteASR\runtimes'
New-Item -ItemType Directory -Path $managed -Force | Out-Null
$lockStream = $null
$phase = 'interpreter_preparing'
function Stage([string]$name) {
    $script:phase = $name
    Write-Host ('[2BYTEASR_PHASE] ' + (@{phase=$name;model='nemotron'} | ConvertTo-Json -Compress))
}
function Run-Uv([string[]]$arguments) {
    & $script:uv @arguments
    if ($LASTEXITCODE -ne 0) { throw "uv failed with exit code $LASTEXITCODE during $script:phase" }
}
function File-Sha256([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $hash.Dispose() }
}
try {
    $deadline = [DateTime]::UtcNow.AddMinutes(30)
    while ($null -eq $lockStream) {
        try { $lockStream = [IO.File]::Open((Join-Path $managed 'bootstrap.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
        catch [IO.IOException] {
            if ([DateTime]::UtcNow -ge $deadline) { throw 'Timed out waiting for the other runtime preparation task.' }
            Write-Host '[Runtime] Waiting for the other managed runtime preparation task...'
            Start-Sleep -Seconds 2
        }
    }
    Stage 'interpreter_preparing'
    $contract = Get-Content -LiteralPath (Join-Path $ProjectRoot 'dependencies.lock.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $boot = $contract.environments.nemotron.bootstrap
    $toolsRoot = Join-Path $managed ('tools\uv-' + $boot.uv_version)
    New-Item -ItemType Directory -Path $toolsRoot -Force | Out-Null
    $archive = Join-Path $toolsRoot 'uv-windows.zip'
    if (-not (Test-Path -LiteralPath $archive) -or (File-Sha256 $archive) -ne $boot.uv_sha256) {
        $pending = $archive + '.partial'
        $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
        Write-Host ('[Nemotron] Downloading pinned uv ' + $boot.uv_version + ' (23572531 bytes)')
        & $curl --fail --location --retry 2 --connect-timeout 20 --max-time 600 --output $pending $boot.uv_url
        if ($LASTEXITCODE -ne 0) { throw 'uv HTTPS download failed' }
        if ((File-Sha256 $pending) -ne $boot.uv_sha256) { throw 'uv SHA256 mismatch' }
        Move-Item -LiteralPath $pending -Destination $archive -Force
    }
    # Core .NET only: Windows PowerShell can inherit a PS7-only PSModulePath.
    # Do not depend on auto-loaded Get-FileHash / Expand-Archive modules.
    [Reflection.Assembly]::LoadWithPartialName('System.IO.Compression.FileSystem') | Out-Null
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -in @('uv.exe','uvw.exe')) {
                $sourceStream = $entry.Open()
                $destStream = [IO.File]::Create((Join-Path $toolsRoot $entry.FullName))
                try { $sourceStream.CopyTo($destStream) } finally { $destStream.Dispose(); $sourceStream.Dispose() }
            }
        }
    } finally { $zip.Dispose() }
    $script:uv = Join-Path $toolsRoot 'uv.exe'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $managed 'python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $managed 'unused-bin'
    $env:UV_CACHE_DIR = Join-Path $managed 'download-cache'
    $env:UV_NO_MODIFY_PATH = '1'
    $env:UV_PYTHON_NO_REGISTRY = '1'
    $pythonVersion = [string]$boot.python_version
    Run-Uv -arguments @('--no-config','--system-certs','python','install',$pythonVersion,'--install-dir',$env:UV_PYTHON_INSTALL_DIR,'--no-bin','--no-registry')
    $basePython = Join-Path $env:UV_PYTHON_INSTALL_DIR ('cpython-' + $pythonVersion + '-windows-x86_64-none\python.exe')
    if (-not (Test-Path -LiteralPath $basePython)) { throw "Managed interpreter missing: $basePython" }
    Write-Host ('[Nemotron] Managed interpreter: ' + $basePython + '; cwd=' + (Get-Location).Path)
    $runtime = Join-Path $managed ('nemotron\' + $boot.runtime_id)
    $reused = $false
    $registryPath = Join-Path $managed 'registry.json'
    if (Test-Path -LiteralPath $registryPath) {
        $registered = (Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json).runtimes.nemotron
        if ($registered -and (Test-Path -LiteralPath $registered.python_executable)) {
            $registeredRoot = Split-Path -Parent (Split-Path -Parent $registered.python_executable)
            $readyPath = Join-Path $registeredRoot 'nemotron-readiness.json'
            if (Test-Path -LiteralPath $readyPath) {
                $ready = Get-Content -LiteralPath $readyPath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($ready.model_loaded -and $ready.forward_verified -and $ready.model_revision -eq $contract.models.nemotron.revision -and
                    (Split-Path -Leaf $registeredRoot).StartsWith([string]$boot.runtime_id)) {
                    $runtime = $registeredRoot
                    $reused = $true
                }
            }
            # Never install packages over an already registered interpreter.
            if (-not $reused -and $registeredRoot -eq $runtime) {
                $runtime += '-' + [DateTime]::UtcNow.ToString('yyyyMMddHHmmss')
            }
        }
    }
    $runtimePython = Join-Path $runtime 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $runtimePython)) {
        Run-Uv -arguments @('--no-config','--system-certs','venv','--no-project','--python',$basePython,'--managed-python','--no-python-downloads',$runtime)
    }
    # Permanent location from creation; never rename a venv containing absolute paths.
    if ($BootstrapOnly) { Write-Host ('[Nemotron] Bootstrap verified: ' + $runtimePython); exit 0 }
    Stage 'dependencies_installing'
    if ($reused) {
        Write-Host ('[Nemotron] Reusing validated dependencies in place: ' + $runtime)
        Run-Uv -arguments @('--no-config','pip','check','--python',$runtimePython)
    } else {
    $envContract = $contract.environments.nemotron
    $tag = [string]$boot.torch_tag
    Write-Host ('[Nemotron] Dependencies: torch ' + $envContract.torch + '+' + $tag + '; weights separate: 396956673 bytes')
    Run-Uv -arguments @('--no-config','--system-certs','pip','install','--python',$runtimePython,
        ('torch==' + $envContract.torch + '+' + $tag),('torchaudio==' + $envContract.torchaudio + '+' + $tag),
        '--index-url',('https://download.pytorch.org/whl/' + $tag))
    $packages = @()
    foreach ($property in $envContract.packages.PSObject.Properties) {
        $url = $envContract.package_sources.($property.Name)
        $packages += $(if ($url) { $property.Name + ' @ ' + $url } else { $property.Name + '==' + $property.Value })
    }
    Run-Uv -arguments (@('--no-config','--system-certs','pip','install','--python',$runtimePython,'--index-url','https://pypi.org/simple') + $packages)
    Run-Uv -arguments @('--no-config','pip','check','--python',$runtimePython)
    & $script:uv --no-config pip freeze --python $runtimePython | Set-Content -LiteralPath (Join-Path $runtime 'installed.lock.txt') -Encoding UTF8
    if ($LASTEXITCODE -ne 0) { throw 'Dependency manifest failed' }
    }
    if (-not $ModelRoot) { $ModelRoot = $env:2BYTEASR_MODEL_ROOT }
    if (-not $ModelRoot) { $ModelRoot = Join-Path $ProjectRoot 'models' }
    if (-not $Sample) { $Sample = $env:TWOBYTEASR_NEMOTRON_SAMPLE }
    if (-not $Sample) {
        $bundledSample = Join-Path $ProjectRoot 'assets\diagnostics\speech_en.wav'
        if (Test-Path -LiteralPath $bundledSample) { $Sample = $bundledSample }
    }
    Stage 'weights_downloading'
    $installArgs = @('-I','-X','utf8',(Join-Path $PSScriptRoot 'install_nemotron.py'),'--root',$ProjectRoot,'--runtime',$runtime,'--models',$ModelRoot,'--source',$Source)
    if ($Sample) { $installArgs += @('--sample',$Sample) }
    & $runtimePython @installArgs
    if ($LASTEXITCODE -ne 0) { throw "Nemotron validation failed (exit $LASTEXITCODE); previous registry retained" }
    if ($Sample) { Stage 'ready' } else { Stage 'runtime_ready' }
} catch {
    Write-Host ('[2BYTEASR_INSTALL_ERROR] ' + (@{phase=$phase;model='nemotron';message=$_.Exception.Message} | ConvertTo-Json -Compress))
    throw
} finally {
    if ($lockStream) { $lockStream.Dispose() }
}
