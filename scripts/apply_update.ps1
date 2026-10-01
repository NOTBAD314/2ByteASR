[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Package,
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ExpectedSha256,
    [int]$WaitForPid = 0,
    [switch]$Restart,
    # 测试隔离：非交互模式不弹 MessageBox，失败只写日志 + stderr + exit 1。
    # 生产入口（launch_update_helper）不传此开关，保留正常错误 UI。
    [switch]$NonInteractive,
    # 测试隔离：日志目录注入；为空时用 %LOCALAPPDATA%\2ByteASR（生产默认）。
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"
if ($LogPath) {
    $logDir = Split-Path -Parent $LogPath
    if (-not $logDir) { $logDir = "." }
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
} else {
    $logDir = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "2ByteASR"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $LogPath = Join-Path $logDir "update.log"
}
$temporary = Join-Path $env:TEMP ("2byteasr-update-" + [guid]::NewGuid().ToString("N"))

# P1-7：与 apply_hotfix.ps1 共用同一路径边界校验实现，避免两套判断。
. (Join-Path $PSScriptRoot "update-path-safety.ps1")

try {
    "[$(Get-Date -Format o)] update started" | Set-Content -LiteralPath $LogPath -Encoding UTF8
    $root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $packagePath = [IO.Path]::GetFullPath($Package)
    if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf)) {
        throw "更新包不存在：$packagePath"
    }
    $actual = (Get-FileHash -LiteralPath $packagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "更新包 SHA-256 校验失败。"
    }
    if ($WaitForPid -gt 0) {
        try { Wait-Process -Id $WaitForPid -Timeout 120 -ErrorAction Stop } catch {
            if (Get-Process -Id $WaitForPid -ErrorAction SilentlyContinue) {
                throw "2ByteASR 未能在 120 秒内退出，更新已取消。"
            }
        }
    }
    New-Item -ItemType Directory -Path $temporary -Force | Out-Null
    Expand-Archive -LiteralPath $packagePath -DestinationPath $temporary -Force
    $manifestPath = Join-Path $temporary "HOTFIX.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "更新包缺少 HOTFIX.json。"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($relative in @($manifest.files)) {
        $source = [IO.Path]::GetFullPath((Join-Path $temporary $relative))
        $target = [IO.Path]::GetFullPath((Join-Path $root $relative))
        if (-not (Assert-PathInsideRoot $source $temporary) -or
            -not (Assert-PathInsideRoot $target $root)) {
            throw "更新包包含越界路径：$relative"
        }
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "更新包文件缺失：$relative"
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
    foreach ($relative in @($manifest.delete)) {
        $target = [IO.Path]::GetFullPath((Join-Path $root $relative))
        if (-not (Assert-PathInsideRoot $target $root)) {
            throw "更新包删除路径越界：$relative"
        }
        Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
    }
    $shortcutScript = Join-Path $root "scripts\install_shortcut.ps1"
    if (Test-Path -LiteralPath $shortcutScript) {
        try { & $shortcutScript -SkipBuild } catch {
            "快捷方式刷新失败（不影响程序更新）：$_" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        }
    }
    "[$(Get-Date -Format o)] update completed: $($manifest.version)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
    Remove-Item -LiteralPath $packagePath -Force -ErrorAction SilentlyContinue
    if ($Restart) {
        $launcher = Join-Path $root "2ByteASR.exe"
        if (Test-Path -LiteralPath $launcher) {
            Start-Process -FilePath $launcher -WorkingDirectory $root
        }
    }
} catch {
    $message = "2ByteASR 自动更新失败：$($_.Exception.Message)`n`n日志：$LogPath"
    "[$(Get-Date -Format o)] $message`n$($_ | Out-String)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
    if (-not $NonInteractive) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            $message,
            "2ByteASR 更新失败",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    } else {
        Write-Error $message
    }
    exit 1
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
