param([Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$destination = [IO.Path]::GetFullPath($Output)
if (-not $destination.StartsWith((Join-Path $workspace 'tmp') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Snapshot must be inside workspace/tmp' }
$rows = @()
foreach ($registryRoot in @('HKCU:\Software\2ByteASR')) {
    if (Test-Path -LiteralPath $registryRoot) {
        $registryKeys = @((Get-Item -LiteralPath $registryRoot)) + @(Get-ChildItem -LiteralPath $registryRoot -Recurse)
        foreach ($registryKey in $registryKeys) {
            foreach ($valueName in $registryKey.GetValueNames()) {
                $keyName = $registryKey.Name + '\' + $valueName
                if ($keyName -match '(?i)(render|frame_export|cover|geometry|windowstate|splitter|layout|theme|directory)' -and $keyName -notmatch '(?i)(secret|token|api.?key|credential)') {
                    $value = $registryKey.GetValue($valueName)
                    if ($value -is [byte[]]) { $value = [Convert]::ToBase64String($value) }
                    $rows += [ordered]@{ location=$registryKey.Name; key=$valueName; kind=$registryKey.GetValueKind($valueName).ToString(); value=$value }
                }
            }
        }
    }
}
$files = @()
foreach ($config in @((Join-Path $workspace '2byteasr_settings.json'), (Join-Path $env:LOCALAPPDATA '2ByteASR\2byteasr_settings.json'), (Join-Path $env:LOCALAPPDATA 'SubtitleStudioPreview\settings.json'), (Join-Path $env:LOCALAPPDATA '2ByteASR\SubtitleStudioPreview\settings.json'))) {
    if (Test-Path -LiteralPath $config) {
        $payload = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json -AsHashtable
        $safe = @{}
        foreach ($name in $payload.Keys) {
            if ($name -match '^(project_root|studio_preferences|window_geometry|window_state|theme|last_export_directory)$') { $safe[$name]=$payload[$name] }
        }
        $files += [ordered]@{ location=$config; sha256=(Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash; preferences=$safe }
    }
}
New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($destination)) -Force | Out-Null
[ordered]@{ captured_at=(Get-Date -Format o); registry=$rows; files=$files } | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $destination -Encoding utf8
Write-Output "Saved preference baseline: $($rows.Count) registry values, $($files.Count) existing configuration files."
