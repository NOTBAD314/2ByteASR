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
$category = $null
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
function Use-SystemProxy($system=$null) {
    # Weight downloads (requests) already follow the Windows proxy setting;
    # curl.exe and uv only read *_PROXY variables. A user's own value wins.
    foreach ($name in @('HTTPS_PROXY','HTTP_PROXY','ALL_PROXY')) {
        if ([Environment]::GetEnvironmentVariable($name,'Process') -or [Environment]::GetEnvironmentVariable($name.ToLowerInvariant(),'Process')) { return }
    }
    try {
        $target=[Uri]'https://pypi.org/'
        if (-not $system) { $system=[Net.WebRequest]::GetSystemWebProxy() }
        if ($system.IsBypassed($target)) { return }
        $resolved=$system.GetProxy($target)
    } catch { return }
    if (-not $resolved -or $resolved.Host -eq $target.Host -or $resolved.Scheme -notin @('http','https')) { return }
    # Authority is host:port only; credentials never reach the log.
    $value=$resolved.Scheme+'://'+$resolved.Authority
    # A proxy app that exited can leave the Windows setting on; direct is better then.
    $client=New-Object Net.Sockets.TcpClient
    try { $reachable=$client.ConnectAsync($resolved.Host,$resolved.Port).Wait(2000) } catch { $reachable=$false } finally { $client.Dispose() }
    if (-not $reachable) { Write-Host ('[网络] Windows 系统代理 '+$value+' 无法连接，按直连下载'); return }
    $env:HTTPS_PROXY=$value; $env:HTTP_PROXY=$value
    if (-not $env:NO_PROXY -and -not $env:no_proxy) { $env:NO_PROXY='localhost,127.0.0.1,::1' }
    Write-Host ('[网络] 使用 Windows 系统代理 '+$value+'（curl/uv 不会自行读取系统代理）')
}
function Get-VerifiedFile([string]$url,[string]$sha,[string]$destination) {
    # Returns '' on success, otherwise a short reason. Nothing unverified stays.
    $pending=$destination+'.partial'
    Remove-Item -LiteralPath $pending -ErrorAction SilentlyContinue
    & (Join-Path $env:SystemRoot 'System32\curl.exe') --fail --location --retry 1 --connect-timeout 10 --speed-limit 20480 --speed-time 30 --max-time 900 --output $pending $url
    $code=$LASTEXITCODE
    if ($code -ne 0) {
        Remove-Item -LiteralPath $pending -ErrorAction SilentlyContinue
        $reason=@{6='域名无法解析';7='无法连接';22='来源返回错误状态';28='连接或传输超时';35='TLS 握手失败';56='连接中断'}[$code]
        if (-not $reason) { $reason='curl 退出码 '+$code }
        return $reason
    }
    if ((Sha $pending) -ne $sha) { Remove-Item -LiteralPath $pending -ErrorAction SilentlyContinue; return 'SHA-256 不符，已丢弃' }
    Move-Item -LiteralPath $pending -Destination $destination -Force
    return ''
}
function Get-UvArchive($sources,[string]$archive) {
    # Sources are tried in order; the first verified archive wins.
    $failures=@()
    for ($index=0; $index -lt $sources.Count; $index++) {
        $source=$sources[$index]
        Write-Host ('[工具] 来源 '+($index+1)+'/'+$sources.Count+'：'+$source.label)
        $problem=Get-VerifiedFile $source.url $source.sha256 $archive
        if (-not $problem) { Write-Host ('[工具] 已从 '+$source.label+' 取得 uv，SHA-256 校验通过'); return }
        $failures+=($source.label+'：'+$problem)
        Write-Host ('[工具] '+$source.label+' 未成功（'+$problem+'）')
    }
    $script:category=if (@($failures | Where-Object { $_ -notlike '*SHA-256*' }).Count) { 'runtime_network' } else { 'checksum' }
    throw ('uv 下载失败，GitHub 与备用来源都没有成功：'+($failures -join '；'))
}
function Install-ManagedPython([string]$version) {
    $arguments=@('--no-config','--system-certs','python','install',$version,'--install-dir',$env:UV_PYTHON_INSTALL_DIR,'--no-bin','--no-registry')
    try { RunUv $arguments; return } catch { Write-Host ('[运行库] 默认来源未能取得 Python '+$version+'：'+$_.Exception.Message) }
    foreach ($mirror in @($script:pythonMirrors)) {
        # uv checks every Python archive against the SHA-256 built into uv.
        Write-Host ('[运行库] 改用 '+$mirror.label+' 取得 Python '+$version+'，由 uv 按内置 SHA-256 校验')
        try { RunUv ($arguments+@('--mirror',$mirror.url)); return } catch { Write-Host ('[运行库] '+$mirror.label+' 未成功：'+$_.Exception.Message) }
    }
    $script:category='runtime_network'
    throw ('Python '+$version+' 下载失败：默认来源与国内备用来源都没有成功，请查看上方 uv 输出')
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
    Use-SystemProxy
    # Official first; fallbacks are only for the same pinned uv version and are
    # accepted solely by SHA-256, so a mirror cannot substitute other bytes.
    $uvSources=@([pscustomobject]@{label='GitHub 官方';url=$boot.uv_url;sha256=$boot.uv_sha256})
    $uvBinaries=$null
    $script:pythonMirrors=@()
    $sourcesFile=Join-Path $PSScriptRoot 'runtime_sources.json'
    if (Test-Path -LiteralPath $sourcesFile) {
        $fallback=Get-Content -LiteralPath $sourcesFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($fallback.uv.version -eq $boot.uv_version) {
            $uvSources+=@($fallback.uv.fallbacks)
            $uvBinaries=$fallback.uv.binaries
        } else {
            Write-Host ('[工具] 备用来源清单对应 uv '+$fallback.uv.version+'，与锁定的 '+$boot.uv_version+' 不同，只使用官方来源')
        }
        $script:pythonMirrors=@($fallback.python_mirrors)
    }
    $archiveHashes=@($uvSources | ForEach-Object { $_.sha256 })
    $tools=Join-Path $managed ('tools\uv-'+$boot.uv_version)
    New-Item -ItemType Directory -Path $tools -Force | Out-Null
    $archive=Join-Path $tools 'uv-windows.zip'
    $toolReceipt=Join-Path $tools 'tool-receipt.json'
    $toolReady=$false
    if (Test-Path -LiteralPath $toolReceipt) {
        try {
            $saved=Get-Content -LiteralPath $toolReceipt -Raw -Encoding UTF8 | ConvertFrom-Json
            $toolReady=($archiveHashes -contains $saved.archive_sha256)
            foreach ($name in @('uv.exe','uvw.exe')) {
                $file=Join-Path $tools $name
                if (-not (Test-Path -LiteralPath $file) -or (Sha $file) -ne $saved.files.$name) { $toolReady=$false }
            }
        } catch { $toolReady=$false }
    }
    if (-not $toolReady) {
      # The archive name is kept for every source (a ZIP or the PyPI wheel, both
      # ZIP files), so a manually placed official archive is still accepted.
      if (-not ((Test-Path -LiteralPath $archive) -and ($archiveHashes -contains (Sha $archive)))) {
        Write-Host ('[工具] 获取固定版本 uv '+$boot.uv_version+'，每个来源都校验 SHA-256')
        Get-UvArchive $uvSources $archive
      }
    [Reflection.Assembly]::LoadWithPartialName('System.IO.Compression.FileSystem') | Out-Null
    $zip=[IO.Compression.ZipFile]::OpenRead($archive)
    try {
        foreach ($entry in $zip.Entries) {
            # Official ZIP: uv.exe at the root; PyPI wheel: uv-<version>.data/scripts/uv.exe.
            $leaf=[IO.Path]::GetFileName($entry.FullName)
            if ($leaf -in @('uv.exe','uvw.exe') -and ($entry.FullName -eq $leaf -or $entry.FullName -eq ('uv-'+$boot.uv_version+'.data/scripts/'+$leaf))) {
                $inputStream=$entry.Open(); $outputStream=[IO.File]::Create((Join-Path $tools $leaf))
                try { $inputStream.CopyTo($outputStream) } finally { $inputStream.Dispose(); $outputStream.Dispose() }
            }
        }
    } finally { $zip.Dispose() }
      $fileHashes=@{}
      foreach ($name in @('uv.exe','uvw.exe')) {
          $file=Join-Path $tools $name
          if (-not (Test-Path -LiteralPath $file)) { throw ('uv 压缩包缺少 '+$name) }
          $fileHashes[$name]=Sha $file
          if ($uvBinaries -and $fileHashes[$name] -ne $uvBinaries.$name) { $script:category='checksum'; throw ($name+' 与锁定的 SHA-256 不符') }
      }
      @{archive_sha256=(Sha $archive);files=$fileHashes} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $toolReceipt -Encoding UTF8
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
    Install-ManagedPython $version
    $python=Join-Path $env:UV_PYTHON_INSTALL_DIR ('cpython-'+$version+'-windows-x86_64-none\python.exe')
    if (-not (Test-Path -LiteralPath $python)) { throw 'Managed Python missing after installation' }
    Stage 'dependencies_installing'
    & $python -I (Join-Path $PSScriptRoot 'install_managed_backend.py') --root $root --uv $script:uv --models ($ModelKey -join ',')
    # 75 = install_managed_backend.SOURCES_EXHAUSTED: official and mirror sources all failed.
    if ($LASTEXITCODE -eq 75) { $script:category='runtime_network'; throw '运行库下载失败：官方来源与国内镜像都没有成功（详见上方日志）' }
    if ($LASTEXITCODE -ne 0) { throw "Managed runtime installation exit $LASTEXITCODE" }
    $registry=Get-Content -LiteralPath (Join-Path $managed 'registry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $env:TWOBYTEASR_MAIN_PYTHON=$registry.runtimes.main.python_executable
    # The pinned archive is only an acquisition intermediate. Keep verified
    # uv.exe/uvw.exe, rather than re-extracting/downloading it on every install.
    if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -ErrorAction Stop }
    Stage 'runtime_ready'
} catch {
    $failure=@{phase=$phase;message=$_.Exception.Message;models=$ModelKey}
    if ($category) { $failure.category=$category }
    Write-Host ('[2BYTEASR_INSTALL_ERROR] '+($failure | ConvertTo-Json -Compress))
    throw
} finally { if ($guard) { $guard.Dispose() } }
