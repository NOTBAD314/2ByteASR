[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "moss", "firered_vad", "firered_aed", "qwen_asr", "speaker_embedding",
        "qwen_aligner", "whisper_turbo", "sensevoice", "paraformer", "funasr_nano",
        "firered_llm", "glm_asr_nano", "canary_qwen", "omni_asr_llm_7b", "ja_ctc_aligner"
    )]
    [string[]]$ModelKey
)

& (Join-Path $PSScriptRoot 'setup_managed_backend.ps1') -ModelKey $ModelKey
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
