# Prompt Recipes

Use these prompts with `build_transcription_messages(..., prompt=prompt)`, or pass them through `--prompt` in the subtitle tools.

## Timestamped Diarization (Default)

Chinese:

```text
请将音频转写为文本，每一段需以起始时间戳和说话人编号（[S01]、[S02]、[S03]…）开头，正文为对应的语音内容，并在段末标注结束时间戳，以清晰标明该段语音范围。
```

English:

```text
Transcribe the audio. For each segment, start with the timestamp and speaker ID ([S01], [S02], [S03], ...), then the spoken text, and end with the segment timestamp.
```

## Speaker-Only Transcription

Chinese:

```text
转录为文本，使用 [S01] [S02] [S03]等说话人标签。
```

English:

```text
Transcribe the audio as text using speaker labels such as [S01], [S02], and [S03].
```

## Hotword Hints

For hotwords, use the full prompt below.

Chinese:

```text
请将音频转写为文本，每一段需以起始时间戳和说话人编号（[S01]、[S02]、[S03]…）开头，正文为对应的语音内容，并在段末标注结束时间戳，以清晰标明该段语音范围。热词提示：热词1, 热词2, 热词3
```

English:

```text
Transcribe the audio. For each segment, start with the timestamp and speaker ID ([S01], [S02], [S03], ...), then the spoken text, and end with the segment timestamp. Hotwords: hotword1, hotword2, hotword3
```
