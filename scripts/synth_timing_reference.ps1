# Synthesize one utterance with a built-in Windows OneCore voice and write
# (1) the WAV and (2) the synthesizer's own word boundaries (start, duration).
# Used only to build local timing benchmarks; generated audio is not shipped.
param(
    [Parameter(Mandatory = $true)][string]$Text,
    [Parameter(Mandatory = $true)][string]$Voice,
    [Parameter(Mandatory = $true)][string]$OutWav,
    [Parameter(Mandatory = $true)][string]$OutJson,
    [double]$Rate = 1.0
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait() | Out-Null
    return $task.Result
}
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$chosen = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.DisplayName -like "*$Voice*" } | Select-Object -First 1
if (-not $chosen) { throw "voice not found: $Voice" }
$synth.Voice = $chosen
$synth.Options.IncludeWordBoundaryMetadata = $true
$synth.Options.SpeakingRate = $Rate
$stream = Await ($synth.SynthesizeTextToStreamAsync($Text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$words = @()
foreach ($track in $stream.TimedMetadataTracks) {
    foreach ($cue in $track.Cues) {
        $words += [pscustomobject]@{ text = $cue.Text; start_ms = [math]::Round($cue.StartTime.TotalMilliseconds, 3);
            duration_ms = [math]::Round($cue.Duration.TotalMilliseconds, 3); start_position = $cue.StartPositionInInput;
            track = $track.Id }
    }
}
$reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
$size = [uint32]$stream.Size
$null = Await ($reader.LoadAsync($size)) ([uint32])
$bytes = New-Object byte[] $size
$reader.ReadBytes($bytes)
[System.IO.File]::WriteAllBytes($OutWav, $bytes)
$payload = [pscustomobject]@{ text = $Text; voice = $chosen.DisplayName; language = $chosen.Language; rate = $Rate; words = $words }
[System.IO.File]::WriteAllText($OutJson, ($payload | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding($false)))
