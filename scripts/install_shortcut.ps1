[CmdletBinding()]
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot "build_launcher.ps1")
}

$LauncherPath = Join-Path $ProjectRoot "2ByteASR.exe"
$IconPath = Join-Path $ProjectRoot "assets\2byteasr.ico"
$ShortcutIdentityTool = Join-Path $PSScriptRoot "ShortcutIdentity.exe"
$AppUserModelId = "2ByteASR.Desktop.2026"
$Shell = New-Object -ComObject WScript.Shell
$ShortcutLocations = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "2ByteASR.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "2ByteASR.lnk")
)

foreach ($ShortcutPath in $ShortcutLocations) {
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $LauncherPath
    $Shortcut.WorkingDirectory = $ProjectRoot
    $Shortcut.IconLocation = "$IconPath,0"
    $Shortcut.Description = "2ByteASR game subtitle workbench"
    $Shortcut.Save()
    & $ShortcutIdentityTool $ShortcutPath $AppUserModelId
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to assign the 2ByteASR taskbar identity: $ShortcutPath"
    }
    Write-Host "[OK] Created shortcut: $ShortcutPath" -ForegroundColor Green
}

$PinnedTaskbarDirectory = Join-Path $env:APPDATA "Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"
if (Test-Path -LiteralPath $PinnedTaskbarDirectory) {
    Get-ChildItem -LiteralPath $PinnedTaskbarDirectory -Filter "*.lnk" | ForEach-Object {
        $PinnedShortcut = $Shell.CreateShortcut($_.FullName)
        if ([String]::Equals($PinnedShortcut.TargetPath, $LauncherPath, [StringComparison]::OrdinalIgnoreCase)) {
            $PinnedShortcut.WorkingDirectory = $ProjectRoot
            $PinnedShortcut.IconLocation = "$IconPath,0"
            $PinnedShortcut.Description = "2ByteASR game subtitle workbench"
            $PinnedShortcut.Save()
            & $ShortcutIdentityTool $_.FullName $AppUserModelId
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to update the pinned 2ByteASR taskbar identity: $($_.FullName)"
            }
            Write-Host "[OK] Updated pinned taskbar shortcut: $($_.FullName)" -ForegroundColor Green
        }
    }
}

Write-Host "2ByteASR shortcuts now share one Windows taskbar identity." -ForegroundColor Cyan
