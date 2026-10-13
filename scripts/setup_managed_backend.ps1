# End-user bootstrap: only private, pinned tools/interpreters; no system installs.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string[]]$ModelKey)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$root = Split-Path -Parent $PSScriptRoot
# Reject retired keys before creating a runtime, lock or download cache.
if ($ModelKey | Where-Object { $_ -in @('diarizen','diarizen_embedding','vibevoice_1_5b','vibevoice_7b') }) {
    throw 'DiariZen / VibeVoice models have been removed; no installation or download was started.'
}
$base = if ($env:2BYTEASR_USER_DATA_ROOT) { $env:2BYTEASR_USER_DATA_ROOT } else { $env:LOCALAPPDATA }
$managed = Join-Path $base '2ByteASR\runtimes'
if ($env:TWOBYTEASR_TEST_ROOT) {
    $isolatedPrefix=[IO.Path]::GetFullPath($env:TWOBYTEASR_TEST_ROOT).TrimEnd('\')+'\'
    foreach ($directory in @($managed,$env:LOCALAPPDATA,$env:TEMP,$env:HF_HOME,$env:MODELSCOPE_CACHE,$env:TORCH_HOME)) {
        if ($directory -and -not [IO.Path]::GetFullPath($directory).StartsWith($isolatedPrefix,[StringComparison]::OrdinalIgnoreCase)) { throw '隔离运行库或缓存目录越界，未开始安装。' }
    }
    Write-Host ('[2BYTEASR_ISOLATION] '+(@{pid=$PID;runtime=$managed;root=$env:TWOBYTEASR_TEST_ROOT} | ConvertTo-Json -Compress))
}
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
    # A managed Python parent may export its own PYTHONHOME again. uv build
    # backends must receive neither that stdlib nor a foreign venv launcher.
    $savedEnvironment=@{}
    foreach ($name in @('PYTHONHOME','PYTHONPATH','__PYVENV_LAUNCHER__','VIRTUAL_ENV','PYTHONEXECUTABLE','PYTHONPLATLIBDIR','_PYTHON_SYSCONFIGDATA_NAME','UV_PYTHON','UV_PROJECT_ENVIRONMENT','UV_SYSTEM_PYTHON')) {
        $present=Test-Path -LiteralPath ('Env:'+ $name)
        $savedEnvironment[$name]=@{Exists=$present;Value=[Environment]::GetEnvironmentVariable($name,'Process')}
        # .NET on newer PowerShell turns null into an empty value, which uv
        # treats as an invalid boolean. Use the environment provider to delete.
        Remove-Item -LiteralPath ('Env:'+ $name) -ErrorAction SilentlyContinue
    }
    try {
        & $script:uv @arguments
        if ($LASTEXITCODE -ne 0) { throw "uv exit $LASTEXITCODE during $script:phase" }
    } finally {
        foreach ($name in $savedEnvironment.Keys) {
            $saved=$savedEnvironment[$name]
            if ($saved.Exists) {
                if ($saved.Value -eq '' -and [Environment]::Version.Major -lt 5) {
                    # Windows PowerShell/.NET Framework deletes empty values;
                    # preserve an originally present empty variable exactly.
                    if (-not ('TwoByteASREnvironmentValue' -as [type])) {
                        Add-Type 'using System.Runtime.InteropServices; public static class TwoByteASREnvironmentValue { [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] public static extern bool SetEnvironmentVariable(string name, string value); }'
                    }
                    if (-not [TwoByteASREnvironmentValue]::SetEnvironmentVariable($name,'')) {throw 'Failed to restore original empty environment variable'}
                } else {
                    [Environment]::SetEnvironmentVariable($name,$saved.Value,'Process')
                }
            } else {
                Remove-Item -LiteralPath ('Env:'+ $name) -ErrorAction SilentlyContinue
            }
        }
    }
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
    $boot=$contract.managed_bootstrap
    $tools=Join-Path $managed ('tools\uv-'+$boot.uv_version)
    New-Item -ItemType Directory -Path $tools -Force | Out-Null
    $archive=Join-Path $tools 'uv-windows.zip'
    $toolReceipt=Join-Path $tools 'tool-receipt.json'
    $toolReady=$false
    if (Test-Path -LiteralPath $toolReceipt) {
        try {
            $saved=Get-Content -LiteralPath $toolReceipt -Raw -Encoding UTF8 | ConvertFrom-Json
            $toolReady=($saved.archive_sha256 -eq $boot.uv_sha256)
            foreach ($name in @('uv.exe','uvw.exe')) {
                $file=Join-Path $tools $name
                if (-not (Test-Path -LiteralPath $file) -or (Sha $file) -ne $saved.files.$name) { $toolReady=$false }
            }
        } catch { $toolReady=$false }
    }
    if (-not $toolReady) {
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
      $fileHashes=@{}
      foreach ($name in @('uv.exe','uvw.exe')) { $fileHashes[$name]=Sha (Join-Path $tools $name) }
      @{archive_sha256=$boot.uv_sha256;files=$fileHashes} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $toolReceipt -Encoding UTF8
    }
    $script:uv=Join-Path $tools 'uv.exe'
    $env:UV_PYTHON_INSTALL_DIR=Join-Path $managed 'python'
    $env:UV_PYTHON_BIN_DIR=Join-Path $managed 'unused-bin'
    $env:UV_CACHE_DIR=Join-Path $managed 'download-cache'
    $env:UV_LINK_MODE='hardlink'
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
    # The pinned archive is only an acquisition intermediate. Keep verified
    # uv.exe/uvw.exe, rather than re-extracting/downloading it on every install.
    if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -ErrorAction Stop }
    Stage 'runtime_ready'
} catch {
    Write-Host ('[2BYTEASR_INSTALL_ERROR] '+(@{phase=$phase;message=$_.Exception.Message;models=$ModelKey} | ConvertTo-Json -Compress))
    throw
} finally { if ($guard) { $guard.Dispose() } }
