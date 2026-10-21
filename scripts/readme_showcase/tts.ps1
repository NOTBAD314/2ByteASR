param([string]$Dialogue, [string]$OutDir)
# Synthesizes each dialogue line with a Windows OneCore zh-CN voice (offline).
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
    $task = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
$voices = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
$map = @{ 'A' = ($voices | Where-Object { $_.DisplayName -like '*Kangkang*' })[0];
          'B' = ($voices | Where-Object { $_.DisplayName -like '*Yaoyao*' })[0] }
$lines = Get-Content -Raw -Encoding UTF8 $Dialogue | ConvertFrom-Json
New-Item -ItemType Directory -Force $OutDir | Out-Null
$i = 0
foreach ($line in $lines) {
    $i++
    $synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
    $synth.Voice = $map[$line.speaker]
    $rate = if ($line.speaker -eq 'A') { '+8%' } else { '+4%' }
    $pitch = if ($line.speaker -eq 'A') { '-4%' } else { '+6%' }
    $ssml = "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'><voice name='$($synth.Voice.DisplayName)'><prosody rate='$rate' pitch='$pitch'>$($line.text)</prosody></voice></speak>"
    $stream = Await ($synth.SynthesizeSsmlToStreamAsync($ssml)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
    $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    $size = [uint32]$stream.Size
    $null = Await ($reader.LoadAsync($size)) ([uint32])
    $bytes = New-Object byte[] $size
    $reader.ReadBytes($bytes)
    $path = Join-Path $OutDir ('line{0:D2}_{1}.wav' -f $i, $line.speaker)
    [IO.File]::WriteAllBytes($path, $bytes)
    Write-Output "$path $size $($synth.Voice.DisplayName)"
}
