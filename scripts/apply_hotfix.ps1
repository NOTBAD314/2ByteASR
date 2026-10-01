# 热更包应用（P1-7：路径越界防护，fail-closed）。
# 由根目录 apply_hotfix.bat 调用；也可直接：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\apply_hotfix.ps1 -ZipPath <zip> -Root <root>
#
# 任何来自 HOTFIX.json 的相对路径在 Copy/Delete 前必须通过
# Assert-PathInsideRoot（canonicalize + root containment）：
# - files 的 source 必须位于解压目录内
# - files 的 destination 必须位于安装 root 内
# - delete 的目标必须位于安装 root 内
# 任一越界 → 拒绝整个热更（不应用任何条目，fail-closed）。

[CmdletBinding()]
param(
    [string]$ZipPath = "",
    [string]$Root = ""
)

$ErrorActionPreference = "Stop"
if (-not $Root) { $Root = Split-Path $PSScriptRoot -Parent }
$Root = [IO.Path]::GetFullPath($Root).TrimEnd('\')

if (-not $ZipPath) {
    $candidates = @(
        Get-ChildItem -LiteralPath $Root -Filter "2ByteASR-Update-*.zip" -File -ErrorAction SilentlyContinue
        Get-ChildItem -LiteralPath $Root -Filter "2ByteASR-hotfix-*.zip" -File -ErrorAction SilentlyContinue
    )
    if ($candidates.Count -eq 0) {
        Write-Error "未找到 2ByteASR-Update-*.zip 更新包；请把包放到本目录或拖到本脚本上。"
        exit 1
    }
    $ZipPath = $candidates[0].FullName
}

. (Join-Path $PSScriptRoot "update-path-safety.ps1")

$temporary = ""
try {
    $temporary = Join-Path $env:TEMP ("2byteasr-hotfix-apply-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $temporary -Force | Out-Null
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $temporary -Force

    $manifestPath = Join-Path $temporary "HOTFIX.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "热更包缺少 HOTFIX.json。"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json

    # 第一阶段：全量校验（fail-closed 原子性）——任一越界/缺失即整体拒绝，
    # 不应用任何条目，避免"合法条目已复制、后续越界条目才被发现"的部分应用。
    $operations = @()
    foreach ($relative in @($manifest.files)) {
        # source 必须位于解压目录内，destination 必须位于安装 root 内（P1-7）
        $source = [IO.Path]::GetFullPath((Join-Path $temporary $relative))
        $target = [IO.Path]::GetFullPath((Join-Path $Root $relative))
        if (-not (Assert-PathInsideRoot $source $temporary) -or
            -not (Assert-PathInsideRoot $target $Root)) {
            throw "热更包包含越界路径：$relative"
        }
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "热更包文件缺失：$relative"
        }
        $operations += @{ Type = "copy"; Source = $source; Target = $target }
    }
    foreach ($relative in @($manifest.delete)) {
        $target = [IO.Path]::GetFullPath((Join-Path $Root $relative))
        if (-not (Assert-PathInsideRoot $target $Root)) {
            throw "热更包删除路径越界：$relative"
        }
        $operations += @{ Type = "delete"; Target = $target }
    }

    # 第二阶段：全部校验通过后统一应用
    foreach ($operation in $operations) {
        if ($operation.Type -eq "copy") {
            New-Item -ItemType Directory -Path (Split-Path -Parent $operation.Target) -Force | Out-Null
            Copy-Item -LiteralPath $operation.Source -Destination $operation.Target -Force
        } else {
            Remove-Item -LiteralPath $operation.Target -Force -ErrorAction SilentlyContinue
        }
    }

    $shortcutScript = Join-Path $Root "scripts\install_shortcut.ps1"
    if (Test-Path -LiteralPath $shortcutScript) {
        try { & $shortcutScript -SkipBuild } catch {
            Write-Warning "快捷方式刷新失败（不影响热更）：$_"
        }
    }
    Write-Host "[OK] Hotfix applied: $($manifest.files.Count) files."
} catch {
    Write-Error "热更失败：$_"
    exit 1
} finally {
    if ($temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
    }
}
