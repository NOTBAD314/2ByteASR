[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "moss", "firered_vad", "firered_aed", "qwen_asr", "speaker_embedding",
        "qwen_aligner", "qwen_ultra_aligner", "qwen_ultra_head", "whisper_turbo", "sensevoice", "paraformer", "funasr_nano",
        "firered_llm", "glm_asr_nano", "canary_qwen", "omni_asr_llm_7b", "mfa_aligner"
    )]
    [string[]]$ModelKey,
    [string]$RepairRoles = ''
)

$ModelKey = @($ModelKey | ForEach-Object { if ($_ -eq 'qwen_aligner') { 'qwen_ultra_aligner' } else { $_ } })
& (Join-Path $PSScriptRoot 'setup_managed_backend.ps1') -ModelKey $ModelKey -RepairRoles $RepairRoles
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
