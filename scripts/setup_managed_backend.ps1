# End-user bootstrap: only private, pinned tools/interpreters; no system installs.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string[]]$ModelKey)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$root = Split-Path -Parent $PSScriptRoot
$base = if ($env:2BYTEASR_USER_DATA_ROOT) { $env:2BYTEASR_USER_DATA_ROOT } else { $env:LOCALAPPDATA }
$managed = Join-Path $base '2ByteASR\runtimes'
$phase = 'tools_preparing'
function Stage([string]$name) {
    $script:phase=$name
    Write-Host ('[2BYTEASR_PHASE] '+(@{phase=$name;models=$ModelKey} | ConvertTo-Json -Compress))
}
function Sha([string]$file) {
    $stream=[IO.File]::OpenRead($file); $hasher=[Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $hasher.Dispose() }
}
function RunUv([string[]]$arguments) {
    & $script:uv @arguments
    if ($LASTEXITCODE -ne 0) { throw "uv exit $LASTEXITCODE during $script:phase" }
}
$guard=$null
try {
    New-Item -ItemType Directory -Path $managed -Force | Out-Null
    # OS handle ownership releases on cancellation/crash; stale filenames do not lock.
    $lockDeadline=[DateTime]::UtcNow.AddMinutes(30)
    while (-not $guard) {
        try { $guard=[IO.File]::Open((Join-Path $managed 'bootstrap.lock'),'OpenOrCreate','ReadWrite','None') }
        catch [IO.IOException] {
            if ([DateTime]::UtcNow -gt $lockDeadline) { throw '等待其他模型运行库准备超时，请稍后重试。' }
            Write-Host '[运行库] 另一项准备正在使用环境，等待安全完成。'
            Start-Sleep -Seconds 2
        }
    }
    Stage 'tools_preparing'
    $contract=Get-Content -LiteralPath (Join-Path $root 'dependencies.lock.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $boot=$contract.environments.nemotron.bootstrap
    $tools=Join-Path $managed ('tools\uv-'+$boot.uv_version)
    New-Item -ItemType Directory -Path $tools -Force | Out-Null
    $archive=Join-Path $tools 'uv-windows.zip'
    if (-not (Test-Path -LiteralPath $archive) -or (Sha $archive) -ne $boot.uv_sha256) {
        $pending=$archive+'.partial'
        Write-Host ('[工具] 获取固定版本 uv '+$boot.uv_version+'，校验 SHA-256')
        & (Join-Path $env:SystemRoot 'System32\curl.exe') --fail --location --retry 1 --connect-timeout 20 --max-time 600 --output $pending $boot.uv_url
        if ($LASTEXITCODE -ne 0) { throw 'uv HTTPS download failed' }
        if ((Sha $pending) -ne $boot.uv_sha256) { throw 'uv SHA256 mismatch' }
        Move-Item -LiteralPath $pending -Destination $archive -Force
    }
    [Reflection.Assembly]::LoadWithPartialName('System.IO.Compression.FileSystem') | Out-Null
    $zip=[IO.Compression.ZipFile]::OpenRead($archive)
    try {
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -in @('uv.exe','uvw.exe')) {
                $inputStream=$entry.Open(); $outputStream=[IO.File]::Create((Join-Path $tools $entry.FullName))
                try { $inputStream.CopyTo($outputStream) } finally { $inputStream.Dispose(); $outputStream.Dispose() }
            }
        }
    } finally { $zip.Dispose() }
    $script:uv=Join-Path $tools 'uv.exe'
    $env:UV_PYTHON_INSTALL_DIR=Join-Path $managed 'python'
    $env:UV_PYTHON_BIN_DIR=Join-Path $managed 'unused-bin'
    $env:UV_CACHE_DIR=Join-Path $managed 'download-cache'
    $env:UV_NO_MODIFY_PATH='1'; $env:UV_PYTHON_NO_REGISTRY='1'
    Stage 'interpreter_preparing'
    # Patch version is explicit; preserves the existing main cp310 ABI contract.
    $version='3.10.19'
    RunUv @('--no-config','--system-certs','python','install',$version,'--install-dir',$env:UV_PYTHON_INSTALL_DIR,'--no-bin','--no-registry')
    $python=Join-Path $env:UV_PYTHON_INSTALL_DIR ('cpython-'+$version+'-windows-x86_64-none\python.exe')
    if (-not (Test-Path -LiteralPath $python)) { throw 'Managed Python missing after installation' }
    Stage 'dependencies_installing'
    & $python -I (Join-Path $PSScriptRoot 'install_managed_backend.py') --root $root --uv $script:uv --models ($ModelKey -join ',')
    if ($LASTEXITCODE -ne 0) { throw "Managed runtime installation exit $LASTEXITCODE" }
    $registry=Get-Content -LiteralPath (Join-Path $managed 'registry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $env:TWOBYTEASR_MAIN_PYTHON=$registry.runtimes.main.python_executable
    Stage 'runtime_ready'
} catch {
    Write-Host ('[2BYTEASR_INSTALL_ERROR] '+(@{phase=$phase;message=$_.Exception.Message;models=$ModelKey} | ConvertTo-Json -Compress))
    throw
} finally { if ($guard) { $guard.Dispose() } }
