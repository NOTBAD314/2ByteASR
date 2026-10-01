[CmdletBinding()]
param(
    [string]$OutputDir = ""
)

# 打包 GitHub Releases 可用子集（单文件 ≤ 2 GB）：
#   MOSS-Transcribe-Diarize（说话人骨架，必装）+ FireRedVAD + spkrec-ecapa（声纹）
# FireRedASR2-AED / Qwen3-ASR 单文件超过 2 GB，无法上传 GitHub，仍需联网下载。
#
# 用法：解压出 models/ 放到 2ByteASR 安装目录（与 2ByteASR.bat 同级），
#       再运行 setup_2byteasr.bat——MOSS/VAD/ECAPA 自动跳过，只下载其余模型。
#
# 运行：powershell -ExecutionPolicy Bypass -File scripts/build_github_bundle.ps1
# 产物：dist/2ByteASR-github-models-<日期>.7z（需 7-Zip）

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputDir) { $OutputDir = Join-Path $ProjectRoot "dist" }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$include = @(
    (Join-Path $ProjectRoot "models\MOSS-Transcribe-Diarize"),
    (Join-Path $ProjectRoot "models\FireRedVAD"),
    (Join-Path $ProjectRoot "models\spkrec-ecapa-voxceleb")
)
foreach ($path in $include) {
    if (-not (Test-Path $path)) { throw "缺少模型目录：$path" }
}

# 校验这三个模型完整性
& (Join-Path $PSScriptRoot "download_models.ps1") -VerifyOnly
if ($LASTEXITCODE -ne 0) { throw "模型完整性校验未通过。" }

$sevenZipPath = ""
$sevenZipCommand = Get-Command 7z -ErrorAction SilentlyContinue
if ($sevenZipCommand) { $sevenZipPath = $sevenZipCommand.Source }
if (-not $sevenZipPath) {
    foreach ($candidate in @("C:\Program Files\7-Zip\7z.exe", "C:\Program Files (x86)\7-Zip\7z.exe", "G:\VMWARE\7za.exe")) {
        if (Test-Path $candidate) { $sevenZipPath = $candidate; break }
    }
}
if (-not $sevenZipPath) { throw "未找到 7-Zip。" }

$stamp = Get-Date -Format "yyyyMMdd"
$output = Join-Path $OutputDir "2ByteASR-github-models-$stamp.7z"
Remove-Item $output -Force -ErrorAction SilentlyContinue
Write-Host "[打包] 压缩 MOSS + FireRedVAD + ECAPA（高压缩 -mx=9，可能需要一段时间）..." -ForegroundColor Cyan
$p = Start-Process -FilePath $sevenZipPath -ArgumentList @(
    "a", "-t7z", "-mx=9", "-mmt=on", $output,
    (Join-Path $ProjectRoot "models\MOSS-Transcribe-Diarize\*"),
    (Join-Path $ProjectRoot "models\FireRedVAD\*"),
    (Join-Path $ProjectRoot "models\spkrec-ecapa-voxceleb\*")
) -Wait -PassThru -NoNewWindow -RedirectStandardOutput (Join-Path $OutputDir "github-bundle.log") -RedirectStandardError (Join-Path $OutputDir "github-bundle.err.log")
if ($p.ExitCode -ne 0) { throw "7-Zip 打包失败（退出码 $($p.ExitCode)）。" }

$sizeGb = [math]::Round((Get-Item $output).Length / 1GB, 2)
if ($sizeGb -gt 2.0) {
    Remove-Item $output -Force
    throw "打包结果 ${sizeGb} GB 超过 GitHub 单文件 2 GB 限制。"
}
Write-Host "[OK] GitHub 子集包已生成：$output（$sizeGb GB）" -ForegroundColor Green
Write-Host "用法：解压出 models/ 放到安装目录，再运行 setup_2byteasr.bat（FireRed/Qwen 仍需联网下载）。" -ForegroundColor Yellow
