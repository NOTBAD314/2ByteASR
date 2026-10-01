param(
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [int]$Rate = 1
)
$ErrorActionPreference = 'Stop'
$sampleRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $sampleRoot -Force | Out-Null
$sampleWav = Join-Path $sampleRoot 'chinese-local-qa.wav'
$sampleReceipt = Join-Path $sampleRoot 'chinese-local-qa.json'
if ((Test-Path -LiteralPath $sampleWav) -or (Test-Path -LiteralPath $sampleReceipt)) {
    throw 'Sample output already exists; select a fresh directory.'
}
$sampleText = '今天测试兔白字幕。我们使用本地模型识别中文。字幕可以编辑，剪切后保存工程，最后导出视频。'
$sampleVoice = New-Object -ComObject SAPI.SpVoice
$sampleTokens = $sampleVoice.GetVoices()
$sampleSelected = $null
foreach ($sampleToken in $sampleTokens) {
    if ($sampleToken.GetAttribute('Language') -eq '804') {
        $sampleSelected = $sampleToken
        break
    }
}
if ($null -eq $sampleSelected) {
    throw 'No installed SAPI zh-CN voice; no cloud synthesis fallback was attempted.'
}
$sampleVoice.Voice = $sampleSelected
$sampleVoice.Rate = $Rate
$sampleStream = New-Object -ComObject SAPI.SpFileStream
$sampleFormat = New-Object -ComObject SAPI.SpAudioFormat
$sampleFormat.Type = 22 # SAFT22kHz16BitMono; resulting WAV is verified below.
$sampleStream.Format = $sampleFormat
$sampleStream.Open($sampleWav, 3, $false)
try {
    $sampleVoice.AudioOutputStream = $sampleStream
    [void]$sampleVoice.Speak($sampleText, 0)
} finally {
    $sampleStream.Close()
}
$sampleData = [System.IO.File]::ReadAllBytes($sampleWav)
if ([System.Text.Encoding]::ASCII.GetString($sampleData, 0, 4) -ne 'RIFF' -or
    [System.Text.Encoding]::ASCII.GetString($sampleData, 8, 4) -ne 'WAVE') {
    throw 'Synthesized sample is not a WAV file.'
}
$sampleOffset = 12
$sampleAudioBytes = 0
$sampleChannels = 0
$sampleHz = 0
$sampleBits = 0
while ($sampleOffset + 8 -le $sampleData.Length) {
    $sampleChunk = [System.Text.Encoding]::ASCII.GetString($sampleData, $sampleOffset, 4)
    $sampleLength = [BitConverter]::ToUInt32($sampleData, $sampleOffset + 4)
    if ($sampleChunk -eq 'fmt ') {
        $sampleChannels = [BitConverter]::ToUInt16($sampleData, $sampleOffset + 10)
        $sampleHz = [BitConverter]::ToUInt32($sampleData, $sampleOffset + 12)
        $sampleBits = [BitConverter]::ToUInt16($sampleData, $sampleOffset + 22)
    }
    if ($sampleChunk -eq 'data') { $sampleAudioBytes = $sampleLength }
    $sampleOffset += 8 + $sampleLength + ($sampleLength % 2)
}
if ($sampleAudioBytes -le 0 -or $sampleHz -le 0 -or $sampleChannels -ne 1 -or $sampleBits -ne 16) {
    throw 'Unexpected or empty synthesized PCM sample.'
}
$sampleDetails = [ordered]@{
    kind = 'synthetic_speech'
    text_origin = 'Original QA text prepared for this project; contains no private user content.'
    use = 'Internal authorized recognition/media testing with an already installed Windows SAPI voice.'
    human_speech = $false
    recognition_result = $false
    cloud_requests = 0
    text = $sampleText
    voice = $sampleSelected.GetDescription()
    voice_token = $sampleSelected.Id
    rate = $Rate
    wav_path = $sampleWav
    channels = $sampleChannels
    sample_rate = $sampleHz
    bits_per_sample = $sampleBits
    duration_s = $sampleAudioBytes / ($sampleHz * $sampleChannels * $sampleBits / 8)
    bytes = $sampleData.Length
    sha256 = (Get-FileHash -LiteralPath $sampleWav -Algorithm SHA256).Hash.ToLowerInvariant()
    limitations = 'Not a human listening/physical IME result, a gaming microphone quality benchmark, or an external AI request.'
}
$sampleDetails | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $sampleReceipt -Encoding UTF8
$sampleDetails | ConvertTo-Json -Depth 4
