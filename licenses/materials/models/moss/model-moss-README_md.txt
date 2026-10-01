---
license: apache-2.0
library_name: transformers
language:
- en
- zh
tags:
- moss
- audio
- speech
- asr
- diarization
- timestamp-asr
- long-form-audio
- multimodal
- multilingual
- custom_code
pipeline_tag: audio-text-to-text
---

# MOSS-Transcribe-Diarize

<div align="center">
  <a href="https://github.com/OpenMOSS/MOSS-Transcribe-Diarize"><img src="https://img.shields.io/badge/GitHub-OpenMOSS%2FMOSS--Transcribe--Diarize-black?logo=github"></a>
  <a href="https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize"><img src="https://img.shields.io/badge/HuggingFace-Model-orange?logo=huggingface"></a>
  <a href="https://arxiv.org/abs/2601.01554"><img src="https://img.shields.io/badge/arXiv-2601.01554-b31b1b?logo=arxiv"></a>
</div>

MOSS-Transcribe-Diarize 0.9B is an end-to-end audio understanding model for long-form multi-speaker transcription, diarization, timestamps, and acoustic event awareness.

It supports transcription and diarization across 50+ languages, single-pass inference on audio recordings up to 90 minutes long, and custom hotword prompting for domain-specific terms.

Given an audio or video file, the model generates a compact speaker-aware transcript in one pass, including timestamps and anonymous speaker labels such as `[S01]`, `[S02]`, and beyond.

## News

* 2026-07-14: 🏆 MOSS-Transcribe-Diarize won first place in the [2nd MLC-SLM Challenge](https://www.nexdata.ai/competition/mlc-slm) at INTERSPEECH 2026, spanning 14 languages.
* 2026-07-09: Released MOSS-Transcribe-Diarize 0.9B.

## Contents

- [Introduction](#introduction)
- [Model Architecture](#model-architecture)
- [Evaluation](#evaluation)
- [Quickstart](#quickstart)
  - [Environment Setup](#environment-setup)
  - [Python Usage](#python-usage)
  - [Serve with vLLM and SGLang](#serve-with-vllm-and-sglang)
  - [Subtitle Web App](#subtitle-web-app)
- [Output Format](#output-format)
- [More Information](#more-information)
- [License](#license)
- [Citation](#citation)

## Introduction

MOSS-Transcribe-Diarize 0.9B turns real-world long-form audio into structured, speaker-aware transcripts in one pass. Instead of stitching together separate ASR and diarization systems, it jointly performs speech transcription and speaker diarization, producing time-aligned text with consistent speaker labels.

The model is built for meetings, calls, podcasts, interviews, lectures, videos, and other long or messy multi-speaker recordings. It can also emit acoustic event annotations, giving downstream systems a richer view of what happened, who spoke, and when.

Core capabilities:

* **Long-form transcription**: Converts long audio or video recordings into timestamped text.
* **Speaker-aware diarization**: Assigns anonymous speaker labels such as `[S01]` and `[S02]` without a separate diarization pipeline.
* **Promptable generation**: Supports custom transcription instructions, hotwords, and acoustic event annotations.

## Model Architecture

<p align="center">
  <img src="Model_Architecture.png" alt="MOSS-Transcribe-Diarize 0.9B model architecture" width="900">
</p>


This Hugging Face repository includes the custom Transformers remote code required to load the model with `trust_remote_code=True`.

## Evaluation

We evaluate MOSS-Transcribe-Diarize using three objective metrics: Character Error Rate (CER), concatenated minimum-permutation Character Error Rate (cpCER), and Delta-cp. Lower is better for all metrics. A dash (`-`) indicates that the result is unavailable.

<div style="overflow-x: auto;">
<table style="white-space: nowrap;">
  <thead>
    <tr>
      <th rowspan="2" style="min-width: 220px;">Model</th>
      <th colspan="3" style="text-align:center;">AISHELL&#8209;4</th>
      <th colspan="3" style="text-align:center;">Alimeeting</th>
      <th colspan="3" style="text-align:center;">Podcast</th>
      <th colspan="3" style="text-align:center;">Movies</th>
    </tr>
    <tr>
      <th>CER↓</th><th>cpCER↓</th><th>Δcp↓</th>
      <th>CER↓</th><th>cpCER↓</th><th>Δcp↓</th>
      <th>CER↓</th><th>cpCER↓</th><th>Δcp↓</th>
      <th>CER↓</th><th>cpCER↓</th><th>Δcp↓</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td style="white-space: nowrap;">Doubao</td>
      <td>18.18</td><td>27.86</td><td>9.68</td>
      <td>25.25</td><td>37.57</td><td>12.31</td>
      <td>7.93</td><td>10.54</td><td>2.61</td>
      <td>9.94</td><td>30.88</td><td>20.94</td>
    </tr>
    <tr>
      <td style="white-space: nowrap;">ElevenLabs</td>
      <td>19.58</td><td>37.95</td><td>18.36</td>
      <td>25.70</td><td>36.69</td><td>10.99</td>
      <td>8.50</td><td>11.34</td><td>2.85</td>
      <td>11.49</td><td>17.85</td><td>6.37</td>
    </tr>
    <tr>
      <td style="white-space: nowrap;">GPT-4o</td>
      <td>-</td><td>-</td><td>-</td>
      <td>-</td><td>-</td><td>-</td>
      <td>-</td><td>-</td><td>-</td>
      <td>14.37</td><td>23.67</td><td>9.31</td>
    </tr>
    <tr>
      <td style="white-space: nowrap;">Gemini 2.5 Pro</td>
      <td>42.70</td><td>53.42</td><td>10.72</td>
      <td>27.43</td><td>41.64</td><td>14.21</td>
      <td>7.38</td><td>10.23</td><td>2.85</td>
      <td>15.46</td><td>24.15</td><td>8.69</td>
    </tr>
    <tr>
      <td style="white-space: nowrap;">Gemini 3 Pro</td>
      <td>22.75</td><td>27.43</td><td>4.68</td>
      <td>26.75</td><td>32.84</td><td>6.09</td>
      <td>-</td><td>-</td><td>-</td>
      <td>8.62</td><td>14.73</td><td><u>6.11</u></td>
    </tr>
    <tr>
      <td style="white-space: nowrap;">VIBEVOICE ASR</td>
      <td>21.40</td><td>24.99</td><td>3.59</td>
      <td>27.40</td><td>29.33</td><td>1.93</td>
      <td>27.94</td><td>48.30</td><td>20.36</td>
      <td>14.59</td><td>42.54</td><td>27.94</td>
    </tr>
    <tr>
      <td style="white-space: nowrap;"><b>MOSS Transcribe Diarize 0.9B</b></td>
      <td><u>14.84</u></td><td><u>15.83</u></td><td><u>0.99</u></td>
      <td><u>24.86</u></td><td><u>22.17</u></td><td><u>-2.69</u></td>
      <td><u>5.97</u></td><td><u>7.37</u></td><td><b>1.40</b></td>
      <td><u>6.36</u></td><td><u>12.76</u></td><td>6.40</td>
    </tr>
    <tr>
      <td style="white-space: nowrap;"><b>MOSS Transcribe Diarize Pro</b></td>
      <td><b>13.78</b></td><td><b>14.02</b></td><td><b>0.24</b></td>
      <td><b>18.22</b></td><td><b>13.94</b></td><td><b>-4.27</b></td>
      <td><b>4.46</b></td><td><b>6.97</b></td><td><u>2.51</u></td>
      <td><b>5.86</b></td><td><b>11.78</b></td><td><b>5.92</b></td>
    </tr>
  </tbody>
</table>
</div>

## Quickstart

### Environment Setup

Use a clean Python environment. The model uses custom Transformers code, so load the model and processor with `trust_remote_code=True`.

```bash
conda create -n moss-transcribe-diarize python=3.12 -y
conda activate moss-transcribe-diarize

git clone https://github.com/OpenMOSS/MOSS-Transcribe-Diarize.git
cd MOSS-Transcribe-Diarize

pip install --index-url https://download.pytorch.org/whl/cu128 torch torchaudio
pip install -e .
```

The GitHub package provides helper utilities such as audio/video loading, transcription message construction, transcript parsing, CLI inference, and the subtitle web app. The model weights and remote-code model files are loaded from this Hugging Face repository.

### Python Usage

```python
import torch
from transformers import AutoModelForCausalLM, AutoProcessor

from moss_transcribe_diarize import parse_transcript
from moss_transcribe_diarize.inference_utils import (
    build_transcription_messages,
    generate_transcription,
    resolve_device,
)

model_id = "OpenMOSS-Team/MOSS-Transcribe-Diarize"
audio_path = "audio.wav"

device = resolve_device("auto")
dtype = torch.bfloat16 if device.type == "cuda" else torch.float32

model = AutoModelForCausalLM.from_pretrained(
    model_id,
    trust_remote_code=True,
    dtype="auto",
).to(dtype=dtype).to(device).eval()

processor = AutoProcessor.from_pretrained(
    model_id,
    trust_remote_code=True,
)

messages = build_transcription_messages(audio_path)
result = generate_transcription(
    model,
    processor,
    messages,
    max_new_tokens=2048,
    do_sample=False,
    device=device,
    dtype=dtype,
)

print(result["text"])

for segment in parse_transcript(result["text"]):
    print(segment.start, segment.end, segment.speaker, segment.text)
```

The message flow follows the common Qwen multimodal pattern:

1. `processor.apply_chat_template(messages, tokenize=False)` renders text with audio placeholders.
2. The helper utilities load audio waveforms from the same messages.
3. `processor(text=text, audio=audios)` computes Whisper input features and expands audio placeholders.
4. `model.generate(...)` produces timestamped transcription and diarization text.

### Custom Prompt and Hotwords

The default prompt is optimized for timestamped transcription and speaker diarization:

```text
请将音频转写为文本，每一段需以起始时间戳和说话人编号（[S01]、[S02]、[S03]…）开头，正文为对应的语音内容，并在段末标注结束时间戳，以清晰标明该段语音范围。
```

To add hotwords, append a short hint to the default prompt:

```text
请将音频转写为文本，每一段需以起始时间戳和说话人编号（[S01]、[S02]、[S03]…）开头，正文为对应的语音内容，并在段末标注结束时间戳，以清晰标明该段语音范围。热词提示：热词1, 热词2, 热词3
```

More prompt recipes are available in the GitHub repository: <https://github.com/OpenMOSS/MOSS-Transcribe-Diarize/blob/main/examples/prompts.md>

### Serve with SGLang and VLLM

The recommended way to serve MOSS-Transcribe-Diarize is [SGLang Omni](https://github.com/sgl-project/sglang-omni) through the OpenAI-compatible `/v1/audio/transcriptions` endpoint. If you are using a CUDA 12 environment, SGLang is currently not supported; use vLLM instead. Install `sglang-omni` by following the [installation guide](https://github.com/sgl-project/sglang-omni/blob/main/docs/get_started/installation.md), then download the model:

```bash
hf download OpenMOSS-Team/MOSS-Transcribe-Diarize
```

Serve the model:

```bash
sgl-omni serve \
  --model-path OpenMOSS-Team/MOSS-Transcribe-Diarize \
  --port 8000 \
  --max-running-requests 16 \
  --cuda-graph-max-bs 16 \
  --mem-fraction-static 0.80
```

Use `response_format=verbose_json` when you need parsed speaker segments. `json` returns the raw transcript text only.

```bash
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -F model=OpenMOSS-Team/MOSS-Transcribe-Diarize \
  -F file=@audio.wav \
  -F response_format=verbose_json
```

For longer multi-speaker audio, raise `max_new_tokens` so the decoder can finish the full diarized transcript:

```bash
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -F model=OpenMOSS-Team/MOSS-Transcribe-Diarize \
  -F file=@audio.wav \
  -F response_format=verbose_json \
  -F max_new_tokens=65536
```

MOSS-Transcribe-Diarize also supports **vLLM** serving through the OpenAI-compatible transcription API. Use a pinned vLLM nightly build that includes the MOSS-Transcribe-Diarize model registration. Choose one of the following commands: for CUDA 12 environments, use `cu129`; for CUDA 13 environments, use `cu130`.

```bash
uv pip install -U vllm \
  --torch-backend=auto \
  --extra-index-url https://wheels.vllm.ai/68b4a1d582818e67adc903bf1b8fc5a5447da2fa/cu129
```

or:

```bash
uv pip install -U vllm \
  --torch-backend=auto \
  --extra-index-url https://wheels.vllm.ai/68b4a1d582818e67adc903bf1b8fc5a5447da2fa/cu130
```

```bash
vllm serve OpenMOSS-Team/MOSS-Transcribe-Diarize --trust-remote-code
```

```bash
curl http://localhost:8000/v1/audio/transcriptions \
  -F model="OpenMOSS-Team/MOSS-Transcribe-Diarize" \
  -F file=@"audio.wav" \
  -F response_format="json" \
  -F temperature="0"
```



### Subtitle Web App

The source package includes a local subtitle workflow for upload, review, subtitle export, and optional FFmpeg burn-in:

```bash
mtd-subtitle-web \
  --model OpenMOSS-Team/MOSS-Transcribe-Diarize \
  --host 127.0.0.1 \
  --port 7860
```

Open `http://127.0.0.1:7860`, upload an audio/video file, review the parsed subtitle segments, then download JSON/SRT/ASS or burn an MP4 if `ffmpeg` and `ffprobe` are available on `PATH`.

For batch processing:

```bash
mtd-subtitle /path/to/input.mp4 \
  --model OpenMOSS-Team/MOSS-Transcribe-Diarize \
  --out-dir runs/example \
  --render
```

## Output Format

The canonical output format is:

```text
[start_time][Sxx]transcribed speech[end_time]
```

Example:

```text
[0.48][S01]Welcome everyone[1.66][12.26][S02]The new transcription pipeline is ready for evaluation[13.81][14.36][S01]Great, include the diarization results in the report[18.76]
```

In this format:

* `start_time` and `end_time` are timestamps in seconds.
* `[S01]`, `[S02]`, and similar labels are anonymous model-generated speaker labels.
* Speaker labels are relative labels within the input audio and should not be interpreted as real speaker identities.

## More Information

* **GitHub**: <https://github.com/OpenMOSS/MOSS-Transcribe-Diarize>
* **MOSI.AI**: <https://mosi.cn>
* **OpenMOSS**: <https://www.open-moss.com>

## License

MOSS-Transcribe-Diarize 0.9B is licensed under the Apache License 2.0.

## Citation

If you use MOSS-Transcribe-Diarize 0.9B, please cite the technical report:

```bibtex
@misc{moss_transcribe_diarize_2026,
  title={MOSS Transcribe Diarize Technical Report},
  author={{MOSI.AI}},
  year={2026},
  eprint={2601.01554},
  archivePrefix={arXiv},
  primaryClass={cs.SD},
  url={https://arxiv.org/abs/2601.01554}
}
```
