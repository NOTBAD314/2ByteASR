[CmdletBinding()]
param([switch]$CheckOnly)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SourceRoot = Join-Path $ProjectRoot "third_party\FireRedASR2S"


function Get-NormalizedHash {
    param([string]$Path)
    # 换行无关校验：统一为 CRLF 后计算 SHA-256，避免 autocrlf 设置差异导致误判。
    $text = [IO.File]::ReadAllText($Path, [Text.UTF8Encoding]::new($false))
    $normalized = $text.Replace("`r`n", "`n").Replace("`n", "`r`n")
    $sha = [Security.Cryptography.SHA256]::Create()
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($normalized)
    return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '')
}

$patches = @(
    [pscustomobject]@{
        Path = "fireredasr2s\fireredasr2\asr.py"
        Upstream = "F119CD2D335B7127A4E195185D4A0992C595F42F4F121084714A06AFB0EDBC1D"
        Hardened = "CBCF07891B300274A6842BD8FAF57D0FA5BC18808A3B6029FA824055BDCC6BBB"
        Replacements = @(
            [pscustomobject]@{ Before = "import logging"; After = "import argparse`nimport logging" },
            [pscustomobject]@{
                Before = "logger = logging.getLogger(__name__)"
                After = "logger = logging.getLogger(__name__)`n`n`ndef _load_checkpoint(model_path):`n    # The pinned FireRed checkpoints contain tensors and argparse.Namespace only.`n    # Restricting the unpickler prevents arbitrary globals from executing.`n    with torch.serialization.safe_globals([argparse.Namespace]):`n        return torch.load(`n            model_path,`n            map_location=lambda storage, loc: storage,`n            weights_only=True,`n        )"
            },
            [pscustomobject]@{
                Before = 'torch.load(model_path, map_location=lambda storage, loc: storage, weights_only=False)'
                After = '_load_checkpoint(model_path)'
            }
        )
    },
    [pscustomobject]@{
        Path = "fireredasr2s\fireredvad\core\detect_model.py"
        Upstream = "B3DB6DD634ECBBA1EFC3A55B8EE0EE102AE7560B08D2E5110DE3340B865D0154"
        Hardened = "6E1CF9F27CDB1ADA27B6E872481570F150C645C6C6674B865F8790944FCA429D"
        Replacements = @(
            [pscustomobject]@{ Before = "import os"; After = "import argparse`nimport os" },
            [pscustomobject]@{
                Before = "        package = torch.load(model_path,`n            map_location=lambda storage, loc: storage, weights_only=False)"
                After = "        with torch.serialization.safe_globals([argparse.Namespace]):`n            package = torch.load(`n                model_path,`n                map_location=lambda storage, loc: storage,`n                weights_only=True,`n            )"
            }
        )
    },
    [pscustomobject]@{
        Path = "fireredasr2s\fireredlid\lid.py"
        Upstream = "8F2A26C3B11C5D2143E414052C3349F913F23CC85CCB4D920C3E0812C08A3B92"
        Hardened = "D982FE019703120A8AFF2023301A381519C2679A0909EB97765B8E752DC9FDC9"
        Replacements = @(
            [pscustomobject]@{ Before = "import os"; After = "import argparse`nimport os" },
            [pscustomobject]@{
                Before = '    package = torch.load(model_path, map_location=lambda storage, loc: storage, weights_only=False)'
                After = "    with torch.serialization.safe_globals([argparse.Namespace]):`n        package = torch.load(`n            model_path,`n            map_location=lambda storage, loc: storage,`n            weights_only=True,`n        )"
            }
        )
    },
    [pscustomobject]@{
        Path = "fireredasr2s\fireredpunc\punc.py"
        Upstream = "8B082F0CB8C8791FFB207F56DB1A548D8E753648B42C2B314F3F904D98D20CAA"
        Hardened = "4F97741276F6F3321523EE8EFDE6BDA189CFAC67D29CEEDE44ACEB93BC9937BA"
        Replacements = @(
            [pscustomobject]@{ Before = "import logging"; After = "import argparse`nimport logging" },
            [pscustomobject]@{
                Before = '    package = torch.load(model_path, map_location=lambda storage, loc: storage, weights_only=False)'
                After = "    with torch.serialization.safe_globals([argparse.Namespace]):`n        package = torch.load(`n            model_path,`n            map_location=lambda storage, loc: storage,`n            weights_only=True,`n        )"
            }
        )
    }
)

foreach ($item in $patches) {
    $path = Join-Path $SourceRoot $item.Path
    if (-not (Test-Path -LiteralPath $path)) { throw "FireRed security patch target is missing: $path" }
    $actual = Get-NormalizedHash $path
    if ($actual -eq $item.Hardened) { continue }
    if ($actual -ne $item.Upstream) {
        throw "FireRed source differs from the locked revision: $($item.Path)"
    }
    if ($CheckOnly) { throw "FireRed restricted-deserialization patch is missing: $($item.Path)" }

    $text = [IO.File]::ReadAllText($path, [Text.UTF8Encoding]::new($false))
    $text = $text.Replace("`r`n", "`n")  # 匹配上下文前统一 LF 换行（Before/After 文本按 LF 书写）
    foreach ($replacement in $item.Replacements) {
        $before = [string]$replacement.Before
        $after = [string]$replacement.After
        if (-not $text.Contains($before)) {
            throw "FireRed security patch context mismatch: $($item.Path)"
        }
        $text = $text.Replace($before, $after)
    }
    # 写入前统一为 CRLF，保证校验哈希与换行无关。
    $text = $text.Replace("`r`n", "`n").Replace("`n", "`r`n")
    [IO.File]::WriteAllText($path, $text, [Text.UTF8Encoding]::new($false))
    $patched = Get-NormalizedHash $path
    if ($patched -ne $item.Hardened) {
        throw "FireRed security patch verification failed: $($item.Path)"
    }
}

Write-Host "[security] FireRed restricted deserialization is enabled."
