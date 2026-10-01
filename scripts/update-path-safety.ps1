# 更新/热更包路径边界校验（P1-7）。
# 用法：. (Join-Path $PSScriptRoot "update-path-safety.ps1") 后调用 Assert-PathInsideRoot。
#
# 安全不变量：任何来自更新清单的相对路径在执行 Copy/Move/Delete/Replace 前
# 必须 canonicalize（GetFullPath），且最终路径严格位于允许的 root 内——
# candidate 不得等于 root，且必须以 "root + 目录分隔符" 开头（防前缀碰撞，
# 如 C:\Temp\App 不得放行 C:\Temp\Application\...）。大小写不敏感（Windows）。
# GetFullPath 无法解析（非法路径）时抛异常，由调用方 catch → 拒绝整个操作
# （fail closed）。

function Assert-PathInsideRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Root
    )
    $fullCandidate = [IO.Path]::GetFullPath($Candidate).TrimEnd('\')
    $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $prefix = $fullRoot + '\'
    return $fullCandidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
}
