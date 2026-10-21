[CmdletBinding()]
param([string]$InstallDir = '', [switch]$Restore)

# A single-worker fix for the published 0.7.5 build. No model/settings changes.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$originalHash = 'a84ebbfeed5197b5a900c80343c1866d9d3006d1d774d5c3eeca7783fbab850c'
$staging = $null
function Get-Sha256([string]$File) {
    $stream = [IO.File]::OpenRead($File)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $sha.Dispose() }
}
try {
    if (-not $InstallDir) { $InstallDir = Join-Path $env:LOCALAPPDATA 'Programs\2ByteASR' }
    if (-not (Test-Path -LiteralPath (Join-Path $InstallDir '2ByteASR.exe') -PathType Leaf)) {
        throw '未找到软件。请把 2ByteASR.exe 拖到 install.cmd 上，或用 -InstallDir 指定安装目录。'
    }
    $root = (Get-Item -LiteralPath $InstallDir).FullName
    $workers = Join-Path $root 'workers'
    $target = Join-Path $workers 'moss_worker.py'
    $backup = Join-Path $workers 'moss_worker.py.before-long-audio-20261017'
    $versionPath = Join-Path $root '2byteasr_version.json'
    foreach ($path in @($root, $workers, $target, $backup, $versionPath)) {
        if (Test-Path -LiteralPath $path) {
            if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "拒绝修改目录联接或符号链接：$path"
            }
        }
    }
    $version = (Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8 | ConvertFrom-Json).version
    if ($version -ne '0.7.5') { throw "补丁仅适用 0.7.5；当前是 $version。" }
    foreach ($process in @(Get-Process -Name '2ByteASR' -ErrorAction SilentlyContinue)) {
        if (-not $process.Path -or $process.Path -eq (Join-Path $root '2ByteASR.exe')) {
            throw '请先完全退出 2ByteASR，再运行补丁。'
        }
    }
    $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'patch.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $patchedHash = [string]$manifest.patched_sha256
    if ($patchedHash -notmatch '^[0-9a-f]{64}$' -or $manifest.original_sha256 -ne $originalHash) {
        throw '补丁清单无效，请重新获取补丁包。'
    }
    $currentHash = Get-Sha256 $target
    if ($Restore) {
        if ($currentHash -eq $originalHash) { Write-Host '已是原始 0.7.5 worker，无需恢复。'; exit 0 }
        if ($currentHash -ne $patchedHash) { throw '当前 worker 已有其他修改，未覆盖。' }
        if ((Get-Sha256 $backup) -ne $originalHash) { throw '原始备份缺失或校验失败。' }
        $source = $backup
        $expectedHash = $originalHash
    } else {
        if ($currentHash -eq $patchedHash) { Write-Host '补丁已经安装。重开软件，点击“重试失败项”即可。'; exit 0 }
        if ($currentHash -ne $originalHash) { throw '当前 worker 与发布的 0.7.5 不一致，未覆盖。请联系提供补丁的人。' }
        $source = Join-Path $PSScriptRoot 'moss_worker.py'
        $expectedHash = $patchedHash
        if ((Get-Sha256 $source) -ne $expectedHash) { throw '补丁文件校验失败，请重新解压。' }
        if (Test-Path -LiteralPath $backup) {
            if ((Get-Sha256 $backup) -ne $originalHash) { throw '已有备份与原版不一致，未覆盖。' }
        } else {
            [IO.File]::Copy($target, $backup, $false)
        }
    }
    # Copy first; atomically replace only after all hashes match. Never delete a directory.
    $staging = Join-Path $workers ('moss-worker-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    [IO.File]::Copy($source, $staging, $false)
    if ((Get-Sha256 $staging) -ne $expectedHash) { throw '写入校验失败，原文件未替换。' }
    [IO.File]::Replace($staging, $target, [NullString]::Value)
    $staging = $null
    if ($Restore) { Write-Host '已恢复原始 0.7.5 worker。' }
    else { Write-Host '修复完成。重开 2ByteASR，点击“重试失败项”，继续识别原视频。' }
    exit 0
} catch {
    Write-Host "未安装/恢复补丁：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($staging -and (Test-Path -LiteralPath $staging)) { Remove-Item -LiteralPath $staging -Force }
}
