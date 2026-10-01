---
license: apache-2.0
language:
- zh
- en
metrics:
- cer
pipeline_tag: automatic-speech-recognition
tags:
- Paraformer
- FunASR
- ASR
- non-autoregressive
- speech-recognition
library_name: funasr
---

<div align="center">

### ⭐ Powered by [FunASR](https://github.com/modelscope/FunASR) — please give us a GitHub Star!

This model is part of the **FunASR** ecosystem — one industrial-grade open-source toolkit for **ASR · VAD · punctuation · speaker diarization · emotion / event · LLM-ASR**. A Star really helps the project (and keeps you updated):

[**🌟 FunASR**](https://github.com/modelscope/FunASR)  ·  [**🌟 SenseVoice**](https://github.com/FunAudioLLM/SenseVoice)  ·  [**🌟 Fun-ASR**](https://github.com/FunAudioLLM/Fun-ASR)  ·  [**🌟 FunClip**](https://github.com/modelscope/FunClip)

</div>


# Paraformer-zh

**Non-autoregressive end-to-end speech recognition** — 120x realtime on GPU, production-ready for Mandarin Chinese.

Paraformer is a non-autoregressive (NAR) ASR model that generates the entire output in parallel, achieving significant speedups over autoregressive models like Whisper while maintaining competitive accuracy.

## Quick Start

```python
from funasr import AutoModel

# Basic recognition
model = AutoModel(model="funasr/paraformer-zh", hub="hf", device="cuda")
result = model.generate(input="audio.wav")
print(result[0]["text"])
```

## Full Pipeline (VAD + ASR + Punctuation + Speaker Diarization)

```python
from funasr import AutoModel

model = AutoModel(
    model="funasr/paraformer-zh",
    hub="hf",
    vad_model="funasr/fsmn-vad",
    punc_model="funasr/ct-punc",
    spk_model="funasr/campplus",
    device="cuda",
)

result = model.generate(input="meeting.wav")
# Output includes timestamps, punctuation, and speaker labels
for sentence in result[0]["sentence_info"]:
    print(f"[Speaker {sentence['spk']}] {sentence['text']}")
```

## Features

- **120x realtime** on GPU (non-autoregressive parallel decoding)
- **Chinese + English** mixed recognition
- Built-in **VAD** (voice activity detection) for long audio
- **Punctuation restoration** with ct-punc model
- **Speaker diarization** with cam++ model
- Streaming and offline modes
- ONNX export supported

## Model Details

| Property | Value |
|----------|-------|
| Architecture | Paraformer (Non-autoregressive) |
| Parameters | 220M |
| Languages | Chinese, English |
| Sample Rate | 16kHz |
| Training Data | 60,000+ hours |

## Related Models

| Model | Description | Link |
|-------|-------------|------|
| funasr/fsmn-vad | Voice Activity Detection | [HF](https://huggingface.co/funasr/fsmn-vad) |
| funasr/ct-punc | Punctuation Restoration | [HF](https://huggingface.co/funasr/ct-punc) |
| funasr/campplus | Speaker Verification | [HF](https://huggingface.co/funasr/campplus) |
| funasr/paraformer-zh-streaming | Streaming version | [HF](https://huggingface.co/funasr/paraformer-zh-streaming) |

## Links

- **GitHub**: [FunASR](https://github.com/modelscope/FunASR)
- **Docs**: [modelscope.github.io/FunASR](https://modelscope.github.io/FunASR/)
- **Paper**: [Paraformer: Fast and Accurate Parallel Transformer for Non-autoregressive End-to-End Speech Recognition](https://arxiv.org/abs/2206.08317)

## Citation

```bibtex
@inproceedings{gao2022paraformer,
  title={Paraformer: Fast and Accurate Parallel Transformer for Non-autoregressive End-to-End Speech Recognition},
  author={Gao, Zhifu and Zhang, Shiliang and McLoughlin, Ian and Yan, Zhijie},
  booktitle={INTERSPEECH},
  year={2022}
}
```
