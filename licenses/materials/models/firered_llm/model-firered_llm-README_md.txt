---
language:
- en
- zh
license: apache-2.0
tags:
- audio
- automatic-speech-recognition
- asr
pipeline_tag: automatic-speech-recognition
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

FireRedASR2-LLM is the 8B+ parameter variant of the FireRedASR2 system, designed to achieve state-of-the-art performance and enable seamless end-to-end speech interaction. It adopts an Encoder-Adapter-LLM framework leveraging large language model capabilities.

The model was introduced in the paper [FireRedASR2S: A State-of-the-Art Industrial-Grade All-in-One Automatic Speech Recognition System](https://huggingface.co/papers/2603.10420).

**Authors**: Kaituo Xu, Yan Jia, Kai Huang, Junjie Chen, Wenpeng Li, Kun Liu, Feng-Long Xie, Xu Tang, Yao Hu.

## 🔥 News
- [2026.03.12] 🔥 We release FireRedASR2S technical report. See [arXiv](https://arxiv.org/abs/2603.10420).
- [2026.03.05] 🚀 [vLLM](https://github.com/vllm-project/vllm/pull/35727) supports FireRedASR2-LLM.
- [2026.02.25] 🔥 We release **FireRedASR2-LLM model weights**. [🤗](https://huggingface.co/FireRedTeam/FireRedASR2-LLM) [🤖](https://www.modelscope.cn/models/xukaituo/FireRedASR2-LLM/)

## Sample Usage

To use this model, please refer to the installation and setup instructions in the [official GitHub repository](https://github.com/FireRedTeam/FireRedASR2S).

```python
from fireredasr2s.fireredasr2 import FireRedAsr2, FireRedAsr2Config

batch_uttid = ["hello_zh", "hello_en"]
batch_wav_path = ["assets/hello_zh.wav", "assets/hello_en.wav"]

# FireRedASR2-LLM Configuration
asr_config = FireRedAsr2Config(
    use_gpu=True,
    decode_min_len=0,
    repetition_penalty=1.0,
    llm_length_penalty=0.0,
    temperature=1.0
)

# Load the model
model = FireRedAsr2.from_pretrained("llm", "FireRedTeam/FireRedASR2-LLM", asr_config)

# Transcribe
results = model.transcribe(batch_uttid, batch_wav_path)
print(results)
# [{'uttid': 'hello_zh', 'text': '你好世界', 'rtf': '0.0681', 'wav': 'assets/hello_zh.wav'}, {'uttid': 'hello_en', 'text': 'hello speech', 'rtf': '0.0681', 'wav': 'assets/hello_en.wav'}]
```

## Evaluation

FireRedASR2-LLM achieves state-of-the-art accuracy across Mandarin and various Chinese dialects. 

| Metric | FireRedASR2-LLM | Doubao-ASR | Qwen3-ASR | Fun-ASR |
|:---:|:---:|:---:|:---:|:---:|
| **Avg CER (Mandarin, 4 sets)** | **2.89** | 3.69 | 3.76 | 4.16 |
| **Avg CER (Dialects, 19 sets)** | **11.55**| 15.39| 11.85| 12.76|

## FAQ
**Q: What audio format is supported?**
16kHz 16-bit mono PCM wav. You can convert files using ffmpeg:
`ffmpeg -i <input_audio_path> -ar 16000 -ac 1 -acodec pcm_s16le -f wav <output_wav_path>`

**Q: What are the input length limitations?**
FireRedASR2-LLM supports audio input up to 40s.

## Citation
```bibtex
@article{xu2026fireredasr2s,
  title={FireRedASR2S: A State-of-the-Art Industrial-Grade All-in-One Automatic Speech Recognition System},
  author={Xu, Kaituo and Jia, Yan and Huang, Kai and Chen, Junjie and Li, Wenpeng and Liu, Kun and Xie, Feng-Long and Tang, Xu and Hu, Yao},
  journal={arXiv preprint arXiv:2603.10420},
  year={2026}
}
```