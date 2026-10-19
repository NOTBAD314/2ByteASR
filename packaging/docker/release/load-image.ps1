param([switch]$VerifyOnly)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$bundle = Split-Path -Parent $MyInvocation.MyCommand.Path
$archive = Join-Path $bundle '2byteasr-0.8.1-docker.1.tar'
$expectedArchive = '1c2dcb24f5d74f6dd7cd6d469c78209165b10bb754f13895c58abd81256561c5'
$parts = @(
    @{ Name = '2byteasr-0.8.1-docker.1.tar.part01'; Hash = 'f98df15a4aa4e3dd4b460e345bd7f753a296558b7e3a9974827e90d0c02bd71f' },
    @{ Name = '2byteasr-0.8.1-docker.1.tar.part02'; Hash = '5a7db7b538d52770f63c22a642f129c0ea88a8b69eb5b6b2cadd208807a015dd' }
)
foreach ($part in $parts) {
    $path = Join-Path $bundle $part.Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing file: $path" }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $part.Hash) { throw "Checksum mismatch: $path" }
    Write-Host "Verified $($part.Name)"
}
if (-not (Test-Path -LiteralPath $archive)) {
    $output = [System.IO.File]::Open($archive, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
    try {
        foreach ($part in $parts) {
            $inputStream = [System.IO.File]::OpenRead((Join-Path $bundle $part.Name))
            try { $inputStream.CopyTo($output) } finally { $inputStream.Dispose() }
        }
    } finally { $output.Dispose() }
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expectedArchive) {
    throw "Archive checksum mismatch; the existing archive was preserved: $archive"
}
Write-Host 'Image archive verified.'
if (-not $VerifyOnly) {
    & docker load -i $archive
    if ($LASTEXITCODE -ne 0) { throw "docker load failed with exit code $LASTEXITCODE" }
    Write-Host 'Next: docker compose up -d --no-build'
}
