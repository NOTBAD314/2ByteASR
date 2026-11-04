[CmdletBinding()]
param(
    [string]$Project,
    [string]$Python,
    [string]$FFmpeg,
    [string]$SettingsJson,
    [switch]$Full,
    [double]$Seconds = 120,
    [double]$Start = 0,
    [ValidateSet('quick','full')][string]$Validation = 'quick',
    [ValidateSet('software','cuda')][string]$Decode = 'software',
    [ValidateSet(1,2)][int]$Segments = 1,
    [string]$CacheProfile
)
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
if (-not $Project) {
    Add-Type -AssemblyName System.Windows.Forms
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Filter = '2ByteASR project (*.2byteproj)|*.2byteproj'
    $picker.Title = '选择只读采样工程（原工程不会被改写）'
    if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
    $Project = $picker.FileName
}
$Project = (Resolve-Path -LiteralPath $Project).Path
if (-not $Python) {
    $searchRoot = Get-Item -LiteralPath $sourceRoot
    for ($level = 0; $level -lt 6 -and $null -ne $searchRoot; $level++) {
        foreach ($relative in @('.venv-main/Scripts/python.exe','.venv/Scripts/python.exe')) {
            $candidate = Join-Path $searchRoot.FullName $relative
            if (Test-Path -LiteralPath $candidate) { $Python = $candidate; break }
        }
        if ($Python) { break }
        $searchRoot = $searchRoot.Parent
    }
}
if (-not $Python) { throw '未找到开发环境。请用 -Python 指定装有本项目依赖的 Python；此入口不是旧版 EXE 的采样开关。' }
if (-not $FFmpeg) { $FFmpeg = Join-Path $sourceRoot 'tools/ffmpeg/bin/ffmpeg.exe' }
$FFmpeg = (Resolve-Path -LiteralPath $FFmpeg).Path
$outputRoot = Join-Path $sourceRoot ('tmp/export-profile-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,6))
$arguments = @('-X','utf8',(Join-Path $PSScriptRoot 'benchmark_export_pipeline.py'),
    '--ffmpeg',$FFmpeg,'--output',$outputRoot,'--project',$Project,'--mode','project',
    '--start',$Start.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--duration',$(if ($Full) { '0' } else { $Seconds.ToString([Globalization.CultureInfo]::InvariantCulture) }),
    '--validation',$Validation,'--decode',$Decode,'--segments',[string]$Segments)
if ($SettingsJson) { $arguments += @('--settings-json',(Resolve-Path -LiteralPath $SettingsJson).Path) }
if ($CacheProfile) { $arguments += @('--cache-profile',$CacheProfile) }
Write-Host '原工程只读；输出和日志写入独立 tmp 目录。'
Write-Host ('采样目录：' + $outputRoot)
Write-Host '不传 SettingsJson 时使用 CQ20 / p4 / H.264 NVENC / AAC192k；比较原反馈请传入完全相同的 RenderSettings JSON。'
& $Python @arguments
$resultCode = $LASTEXITCODE
Write-Host ('查看 result.json、inventory.json、events.jsonl、resources.json 和 diagnostics：' + $outputRoot)
if ($resultCode -ne 0) { throw ('导出采样失败，退出码 ' + $resultCode + '；失败不计性能成功。') }
