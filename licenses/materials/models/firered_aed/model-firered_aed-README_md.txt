---
language:
- en
- zh
license: apache-2.0
pipeline_tag: automatic-speech-recognition
tags:
- audio
- asr
---

<div align="center">
<h1>
FireRedASR2S
<br>
A SOTA Industrial-Grade All-in-One ASR System
</h1>

</div>

[[Code]](https://github.com/FireRedTeam/FireRedASR2S)
[[Paper]](https://huggingface.co/papers/2603.10420)
[[Model]](https://huggingface.co/FireRedTeam)
[[Blog]](https://fireredteam.github.io/demos/firered_asr/)
[[Demo]](https://huggingface.co/spaces/FireRedTeam/FireRedASR)

FireRedASR2S is a state-of-the-art (SOTA), industrial-grade, all-in-one ASR system presented in the paper [FireRedASR2S: A State-of-the-Art Industrial-Grade All-in-One Automatic Speech Recognition System](https://huggingface.co/papers/2603.10420). It integrates four modules into a unified pipeline: ASR, Voice Activity Detection (VAD), Spoken Language Identification (LID), and Punctuation Prediction (Punc).

### Key Features
- **FireRedASR2**: Supports speech and singing transcription for Mandarin, Chinese dialects/accents, English, and code-switching.
- **FireRedVAD**: Ultra-lightweight module (0.6M parameters) supporting streaming and multi-label VAD (speech/singing/music).
- **FireRedLID**: Supports Spoken Language Identification for 100+ languages and 20+ Chinese dialects.
- **FireRedPunc**: BERT-style punctuation prediction for Chinese and English.

## Sample Usage

To use the system, first clone the [official repository](https://github.com/FireRedTeam/FireRedASR2S) and install the dependencies. Then you can use the following Python API:

```python
from fireredasr2s import FireRedAsr2System, FireRedAsr2SystemConfig

# Initialize the system with default config
asr_system_config = FireRedAsr2SystemConfig() 
asr_system = FireRedAsr2System(asr_system_config)

# Process an audio file (16kHz 16-bit mono PCM)
result = asr_system.process("assets/hello_zh.wav")
print(result['text'])
# Output: 你好世界。
```

## 🔥 News
- [2026.03.12] 🔥 We release FireRedASR2S technical report. See [arXiv](https://arxiv.org/abs/2603.10420).
- [2026.02.25] 🔥 We release **FireRedASR2-LLM model weights**. [🤗](https://huggingface.co/FireRedTeam/FireRedASR2-LLM)
- [2026.02.12] 🔥 We release FireRedASR2S (FireRedASR2-AED, FireRedVAD, FireRedLID, and FireRedPunc) with **model weights and inference code**. 

## Evaluation
FireRedASR2-LLM achieves 2.89% average CER on 4 public Mandarin benchmarks and 11.55% on 19 public Chinese dialects and accents benchmarks, outperforming competitive baselines including Doubao-ASR, Qwen3-ASR, and Fun-ASR.

| Model | Mandarin (Avg CER%) | Dialects (Avg CER%) |
| :--- | :---: | :---: |
| FireRedASR2-LLM | **2.89** | **11.55** |
| FireRedASR2-AED | 3.05 | 11.67 |
| Doubao-ASR | 3.69 | 15.39 |
| Qwen3-ASR | 3.76 | 11.85 |

## Citation
```bibtex
@article{xu2026fireredasr2s,
  title={FireRedASR2S: A State-of-the-Art Industrial-Grade All-in-One Automatic Speech Recognition System},
  author={Xu, Kaituo and Jia, Yan and Huang, Kai and Chen, Junjie and Li, Wenpeng and Liu, Kun and Xie, Feng-Long and Tang, Xu and Hu, Yao},
  journal={arXiv preprint arXiv:2603.10420},
  year={2026}
}
```