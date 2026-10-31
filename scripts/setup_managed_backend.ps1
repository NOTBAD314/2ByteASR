# End-user bootstrap: only private, pinned tools/interpreters; no system installs.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string[]]$ModelKey, [string]$RepairRoles = '')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$root = Split-Path -Parent $PSScriptRoot
$ModelKey=@($ModelKey | ForEach-Object { $_ -split ',' } | Where-Object { $_ } | Select-Object -Unique)
if (-not $env:TWOBYTEASR_DEPLOY_JOB_ID) { $env:TWOBYTEASR_DEPLOY_JOB_ID=[guid]::NewGuid().ToString('N') }
foreach ($entry in @(Get-ChildItem Env:)) {
    if ($entry.Name -match '^(PYTHON|PIP_|UV_|CONDA_|_PYI)' -or $entry.Name -in @('VIRTUAL_ENV','__PYVENV_LAUNCHER__') -or $entry.Name -match '^TWOBYTEASR_.*_PYTHON$') {
        Remove-Item -LiteralPath ('Env:'+ $entry.Name) -ErrorAction SilentlyContinue
    }
}
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONNOUSERSITE='1'
$env:PIP_CONFIG_FILE='NUL'; $env:UV_NO_CONFIG='1'; $env:UV_HTTP_TIMEOUT='30'; $env:UV_HTTP_RETRIES='1'
$env:TWOBYTEASR_MANAGED_RUNTIME_ONLY='1'
# Reject retired keys before creating a runtime, lock or download cache.
if ($ModelKey | Where-Object { $_ -in @('diarizen','diarizen_embedding','vibevoice_1_5b','vibevoice_7b') }) {
    throw 'DiariZen / VibeVoice models have been removed; no installation or download was started.'
}
$base = if ($env:2BYTEASR_USER_DATA_ROOT) { $env:2BYTEASR_USER_DATA_ROOT } else { $env:LOCALAPPDATA }
# Runtime folder (2026-10-17): the app passes it (program folder for new
# installs, or where the user moved runtimes); otherwise the folder registered
# in runtime_paths.json, otherwise the original per-user folder.
$managed = $env:2BYTEASR_RUNTIME_ROOT
if (-not $managed) {
    try { $managed = [string](Get-Content -LiteralPath (Join-Path $base '2ByteASR\runtime_paths.json') -Raw -Encoding UTF8 | ConvertFrom-Json).runtime_root } catch { $managed = '' }
    if (-not $managed) { $managed = Join-Path $base '2ByteASR\runtimes' }
}
# install_managed_backend.py resolves the same folder from this variable.
$env:2BYTEASR_RUNTIME_ROOT = $managed
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
    Write-Host ('[2BYTEASR_PHASE] '+(@{phase=$name;models=$ModelKey;job_id=$env:TWOBYTEASR_DEPLOY_JOB_ID;pid=$PID} | ConvertTo-Json -Compress))
}
function Run-Bounded([string]$program,[string[]]$arguments,[int]$seconds=900,
                     [string]$progressFile='',[int]$idleSeconds=45,[string]$component='') {
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$program; $info.WorkingDirectory=$managed
    $quoted=@($arguments | ForEach-Object { '"'+($_ -replace '(\\*)"','$1$1\"' -replace '(\\+)$','$1$1')+'"' })
    $info.Arguments=$quoted -join ' '
    $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true; $info.RedirectStandardInput=$true
    $info.StandardOutputEncoding=[Text.UTF8Encoding]::new($false);$info.StandardErrorEncoding=[Text.UTF8Encoding]::new($false)
    $process=[Diagnostics.Process]::Start($info)
    $process.StandardInput.Close()
    $started=[DateTime]::UtcNow; $last=$started; $lastProgress=$started; $checkedProgress=$started
    [long]$transferred=0
    Write-Host ('[2BYTEASR_DEPLOY] '+(@{job_id=$env:TWOBYTEASR_DEPLOY_JOB_ID;phase=$script:phase;state='start';component=$component;executable=$program;arguments=$arguments;child_pid=$process.Id;deadline_s=$seconds} | ConvertTo-Json -Compress))
    $output=$process.StandardOutput.ReadLineAsync(); $errorOutput=$process.StandardError.ReadLineAsync()
    try {
        while (-not $process.HasExited -or $output -or $errorOutput) {
            foreach ($which in @('output','errorOutput')) {
                $task=Get-Variable -Name $which -ValueOnly
                if ($task -and $task.IsCompleted) {
                    $line=$task.GetAwaiter().GetResult()
                    if ($null -ne $line) {
                        Write-Host $line
                        if ($line -match '\(os error 32\)') { $script:inUseSeen=$true }
                        if ($line.StartsWith('[2BYTEASR_DEPLOY] ')) {
                            try {
                                $childEvent=$line.Substring(18) | ConvertFrom-Json
                                if ($childEvent.component -and $childEvent.phase -and $childEvent.state -in @('start','failed')) {
                                    $script:phase=[string]$childEvent.phase
                                }
                            } catch { }
                        }
                        $stream=if ($which -eq 'output') {$process.StandardOutput} else {$process.StandardError}
                        Set-Variable -Name $which -Value $stream.ReadLineAsync()
                    } else { Set-Variable -Name $which -Value $null }
                }
            }
            $now=[DateTime]::UtcNow
            if ($progressFile -and ($now-$checkedProgress).TotalSeconds -ge 1) {
                $checkedProgress=$now
                [long]$length=if (Test-Path -LiteralPath $progressFile) { (Get-Item -LiteralPath $progressFile).Length } else { 0 }
                if ($length -gt $transferred) { $transferred=$length; $lastProgress=$now }
            }
            $noProgress=$progressFile -and ($now-$lastProgress).TotalSeconds -gt $idleSeconds
            if (($now-$started).TotalSeconds -gt $seconds -or $noProgress) {
                $reason=if ($noProgress) { "$component 下载 $idleSeconds 秒没有新增数据，停止本次来源。" } else { "$script:phase 超过 $seconds 秒，停止本次程序。" }
                & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $process.Id /T /F 2>&1 | Out-Null
                $global:LASTEXITCODE=28
                Write-Host ('[2BYTEASR_DEPLOY] '+(@{job_id=$env:TWOBYTEASR_DEPLOY_JOB_ID;phase=$script:phase;state='failed';component=$component;child_pid=$process.Id;reason=$reason;downloaded=$transferred;next=$(if($progressFile){'next_tool_source'}else{'retry_or_repair'})} | ConvertTo-Json -Compress))
                throw $reason
            }
            if (([DateTime]::UtcNow-$last).TotalSeconds -ge 15) {
                Write-Host ('[2BYTEASR_DEPLOY] '+(@{job_id=$env:TWOBYTEASR_DEPLOY_JOB_ID;phase=$script:phase;state='waiting';component=$component;child_pid=$process.Id;elapsed_s=[int]([DateTime]::UtcNow-$started).TotalSeconds;waiting='subprocess';downloaded=$(if($progressFile){$transferred}else{$null});progress_age_s=$(if($progressFile){[int]($now-$lastProgress).TotalSeconds}else{$null})} | ConvertTo-Json -Compress))
                $last=[DateTime]::UtcNow
            }
            Start-Sleep -Milliseconds 50
        }
        $process.WaitForExit()
        $code=$process.ExitCode
        $global:LASTEXITCODE=$code
        Write-Host ('[2BYTEASR_DEPLOY] '+(@{job_id=$env:TWOBYTEASR_DEPLOY_JOB_ID;phase=$script:phase;state= $(if($code -eq 0){'done'}else{'failed'});child_pid=$process.Id;exit_code=$code} | ConvertTo-Json -Compress))
        if ($code -eq 75) { $script:category='runtime_network' }
        if ($code -ne 0) { throw "子程序退出码 $code，阶段 $script:phase" }
    } finally { $process.Dispose() }
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
        if ($RepairRoles) { $arguments=@('--no-cache')+$arguments }
        Run-Bounded $script:uv $arguments
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
function Get-VerifiedFile([string]$url,[string]$sha,[string]$destination,[int]$minimumRate=20480) {
    # Returns '' on success, otherwise a short reason. Nothing unverified stays.
    $pending=$destination+'.partial'
    Remove-Item -LiteralPath $pending -ErrorAction SilentlyContinue
    $curl=Join-Path $env:SystemRoot 'System32\curl.exe'
    # Seconds a source may stay below $minimumRate (tests shorten it).
    $speedTime=if ($script:uvSpeedTime) { [int]$script:uvSpeedTime } else { 15 }
    $http='[2BYTEASR_TOOL_HTTP] {"http_status":"%{response_code}","downloaded":%{size_download},"redirects":%{num_redirects},"elapsed_s":%{time_total},"effective_url":"%{url_effective}"}\n'
    # Independent progress supervision also covers native TLS/file waits where
    # curl's own timer may not return. No-progress applies only to this download,
    # never dependency extraction/import checks. Ignore external curlrc files.
    $global:LASTEXITCODE=1
    try {
        Run-Bounded $curl @('--disable','--silent','--show-error','--fail','--location','--retry','0',
            '--connect-timeout','10','--speed-limit',[string]$minimumRate,'--speed-time',[string]$speedTime,'--max-time','900',
            '--write-out',$http,'--output',$pending,$url) 915 $pending 45 'uv'
        $code=0
    } catch { $code=[int]$LASTEXITCODE }
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
    # Sources are tried in order; the first verified archive wins. 2026-10-28 on a
    # mainland line: Aliyun gave ~0.1 MB/s (237 s for this 24 MB file) while
    # Tencent / USTC gave 3-20 MB/s. The first pass leaves any source slower than
    # 256 KB/s for 15 s; the second pass accepts slow sources for slow lines.
    $failures=@()
    $floors=@(if ($script:uvSpeedFloors) { $script:uvSpeedFloors } else { 262144, 20480 })  # bytes/s, one pass each
    $pass=@($sources)
    foreach ($minimumRate in $floors) {
        if ($minimumRate -ne $floors[0]) {
            # Only sources that were merely slow (curl 28) get the second, slower pass.
            if (-not $pass.Count) { break }
            Write-Host '[工具] 没有来源够快，放宽速度要求再试一轮'
        }
        $slow=@()
        for ($index=0; $index -lt $pass.Count; $index++) {
            $source=$pass[$index]
            Write-Host ('[工具] 来源 '+($index+1)+'/'+$pass.Count+'：'+$source.label)
            $problem=Get-VerifiedFile $source.url $source.sha256 $archive $minimumRate
            if (-not $problem) { Write-Host ('[工具] 已从 '+$source.label+' 取得 uv，SHA-256 校验通过'); return }
            $failures+=($source.label+'：'+$problem)
            Write-Host ('[工具] '+$source.label+' 未成功（'+$problem+'）')
            if ($problem -eq '连接或传输超时') { $slow+=$source }
        }
        $pass=$slow
    }
    $script:category=if (@($failures | Where-Object { $_ -notlike '*SHA-256*' }).Count) { 'runtime_network' } else { 'checksum' }
    throw ('uv 下载失败，GitHub 与备用来源都没有成功：'+($failures -join '；'))
}
function Get-PreferredOrder($official,$fallbacks) {
    # download_models.ps1 sets 2BYTEASR_RUNTIME_SOURCE=mirror when the workshop's
    # download source is ModelScope / HF 镜像: the official host is tried last.
    if ($env:2BYTEASR_RUNTIME_SOURCE -eq 'mirror') { return @(@($fallbacks)+@($official)) }
    return @(@($official)+@($fallbacks))
}
function Get-UvSources($official,$fallbacks) {
    $domestic=@($fallbacks | Where-Object { $_.domestic })
    $others=@($fallbacks | Where-Object { -not $_.domestic })
    return @($domestic)+@(Get-PreferredOrder $official $others)
}
# 2026-10-21: on one PC Windows reported folders under the data folder as in use (os error 32) whenever uv deleted
# them. Every `uv python install` re-creates the minor-version links, so remove them first (only the link itself,
# never its target; also an empty folder left by an earlier failed re-creation) and let uv just create them.
function Remove-MinorVersionLinks([string]$folder) {
    $removed=@{}
    if (-not $folder -or -not (Test-Path -LiteralPath $folder)) { return $removed }
    foreach ($entry in @(Get-ChildItem -LiteralPath $folder -Directory -Force | Where-Object { $_.Name -match '^cpython-\d+\.\d+-windows-x86_64-none$' })) {
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            $removed[$entry.FullName]=[string]@($entry.Target)[0]
            [IO.Directory]::Delete($entry.FullName)
        } elseif (-not @(Get-ChildItem -LiteralPath $entry.FullName -Force).Count) {
            [IO.Directory]::Delete($entry.FullName)
        }
    }
    return $removed
}
function Restore-MinorVersionLinks($removed) {
    # A uv call that failed before re-creating a link: point it where it pointed before.
    foreach ($link in @($removed.Keys)) {
        if (Test-Path -LiteralPath $link) { continue }
        New-Item -ItemType Junction -Path $link -Value $removed[$link] | Out-Null
        Write-Host ('[运行库] 已恢复 Python 版本连接 '+(Split-Path $link -Leaf))
    }
}
function Invoke-PythonInstall([string[]]$arguments) {
    # Waits and runs again after an "in use" (os error 32) failure; other failures go to the next source as before.
    foreach ($wait in @(2,5,10,$null)) {
        $links=Remove-MinorVersionLinks $env:UV_PYTHON_INSTALL_DIR
        $script:inUseSeen=$false
        try { RunUv $arguments; return }
        catch {
            if ($null -eq $wait -or -not $script:inUseSeen) { throw }
            Write-Host ('[运行库] Windows 报告文件或文件夹正在被使用，'+$wait+' 秒后重试')
            Start-Sleep -Seconds $wait
        } finally { Restore-MinorVersionLinks $links }
    }
}
function Install-ManagedPython([string]$version) {
    $candidate=Join-Path $env:UV_PYTHON_INSTALL_DIR ('cpython-'+$version+'-windows-x86_64-none\python.exe')
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        try {
            Run-Bounded $candidate @('-I','-X','utf8','-c',("import sys;assert '.'.join(map(str,sys.version_info[:3]))=='"+$version+"'")) 30
            Write-Host ('[运行库] 复用已验证的基础 Python '+$version)
            return
        } catch { Write-Host ('[运行库] 基础 Python 启动检查未通过，保留诊断后重新准备：'+$_.Exception.Message) }
    }
    $arguments=@('--no-config','--system-certs','python','install',$version,'--install-dir',$env:UV_PYTHON_INSTALL_DIR,'--no-bin','--no-registry')
    foreach ($attempt in (Get-PreferredOrder ([pscustomobject]@{label='默认来源';url=''}) @($script:pythonMirrors))) {
        $extra=@()
        if ($attempt.url) {
            # uv checks every Python archive against the SHA-256 built into uv.
            $extra=@('--mirror',$attempt.url)
            Write-Host ('[运行库] 从 '+$attempt.label+' 取得 Python '+$version+'，由 uv 按内置 SHA-256 校验')
        }
        try { Invoke-PythonInstall ($arguments+$extra); return } catch { Write-Host ('[运行库] '+$attempt.label+' 未能取得 Python '+$version+'：'+$_.Exception.Message) }
    }
    $script:category='runtime_network'
    throw ('Python '+$version+' 下载失败：默认来源与国内备用来源都没有成功，请查看上方 uv 输出')
}
$guard=$null
try {
    New-Item -ItemType Directory -Path $managed -Force | Out-Null
    # OS handle ownership releases on cancellation/crash; stale filenames do not lock.
    Stage 'waiting_for_lock'
    $lockDeadline=[DateTime]::UtcNow.AddSeconds(60)
    while (-not $guard) {
        try { $guard=[IO.File]::Open((Join-Path $managed 'bootstrap.lock'),'OpenOrCreate','ReadWrite','None') }
        catch [IO.IOException] {
            if ([DateTime]::UtcNow -gt $lockDeadline) { $script:category='runtime_busy'; throw '另一项环境准备仍在运行，已停止本次等待。请回到正在进行的下载窗口；不会并行重建。' }
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
    $officialUv=[pscustomobject]@{label='GitHub 官方';url=$boot.uv_url;sha256=$boot.uv_sha256}
    $uvFallbacks=@()
    $uvBinaries=$null
    $script:pythonMirrors=@()
    $sourcesFile=Join-Path $PSScriptRoot 'runtime_sources.json'
    if (Test-Path -LiteralPath $sourcesFile) {
        $fallback=Get-Content -LiteralPath $sourcesFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($fallback.uv.version -eq $boot.uv_version) {
            $uvFallbacks=@($fallback.uv.fallbacks)
            $uvBinaries=$fallback.uv.binaries
        } else {
            Write-Host ('[工具] 备用来源清单对应 uv '+$fallback.uv.version+'，与锁定的 '+$boot.uv_version+' 不同，只使用官方来源')
        }
        $script:pythonMirrors=@($fallback.python_mirrors)
    }
    # Bootstrap is common to every model source. Measured mainland DIRECT
    # requests can spend minutes on GitHub before the first usable tool byte.
    # Prefer the pinned domestic wheels; official hosts remain fallbacks.
    $uvSources=@(Get-UvSources $officialUv $uvFallbacks)
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
    if ($RepairRoles) { $env:UV_PYTHON_INSTALL_DIR=Join-Path $managed ('python\generation-'+$env:TWOBYTEASR_DEPLOY_JOB_ID) }
    $env:TWOBYTEASR_PRIVATE_PYTHON_DIR=$env:UV_PYTHON_INSTALL_DIR
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
    $installerArguments=@('-I','-X','utf8','-B',(Join-Path $PSScriptRoot 'install_managed_backend.py'),'--root',$root,'--uv',$script:uv,'--models',($ModelKey -join ','))
    if ($RepairRoles) { $installerArguments+=@('--repair-roles',$RepairRoles) }
    Run-Bounded $python $installerArguments 3600
    $global:LASTEXITCODE=0
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
