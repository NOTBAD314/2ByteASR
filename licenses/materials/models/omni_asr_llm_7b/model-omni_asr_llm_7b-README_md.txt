---
license: apache-2.0
datasets:
- facebook/omnilingual-asr-corpus
pipeline_tag: automatic-speech-recognition
---

# Omnilingual ASR: Open-Source Multilingual Speech Recognition for 1600+ Languages

<div align="center" style="lline-height: 1.2; font-size:16px; margin-bottom: 30px;">
  <a href="https://huggingface.co/facebook" target="_blank" style="margin: 2px;">
    🤗 Hugging Face 
  </a> | 
  <a href="https://github.com/facebookresearch/omnilingual-asr" target="_blank" style="margin: 2px;">
    🐙 GitHub
  </a> | 
  <a href="https://huggingface.co/spaces/facebook/omniasr-transcriptions" target="_blank" style="margin: 2px;">
    🤖️ Demo
  </a> | 
  <a href="https://ai.meta.com/research/publications/omnilingual-asr-open-source-multilingual-speech-recognition-for-1600-languages/" target="_blank" style="margin: 2px;">
    📃 Paper
  </a> | 
  <a href="https://ai.meta.com/blog/omnilingual-asr-advancing-automatic-speech-recognition/" target="_blank" style="margin: 2px;">
    📝 Blogpost
  </a> | 
  <a href="https://github.com/facebookresearch/omnilingual-asr/blob/main/LICENSE" style="margin: 2px;">
    📄 License: Apache 2.0
  </a>
</div>

# Model Card for omniASR-LLM-7B

## Model Description

This model is part of the **Omnilingual ASR** family released by Meta AI. The original suite includes:

<!-- TODO : add new tokenizer, we'll get two tokenizer, add mssing speed numbers-->
| Model Name          | Features      | Parameters | Download Size (FP32) | Inference VRAM¹ | Real-Time Factor¹ (relative speed)² |
|---------------------|---------------|------------:|---------------:|---------------:|-----------:|
| [`omniASR_W2V_300M`](https://huggingface.co/facebook/omniASR-W2V-300M)      | SSL  | 317_390_592   | 1.2 GiB | | |
| [`omniASR_W2V_1B`](https://huggingface.co/facebook/omniASR-W2V-1B)          | SSL  | 965_514_752   | 3.6 GiB | | |
| [`omniASR_W2V_3B`](https://huggingface.co/facebook/omniASR-W2V-3B)          | SSL  | 3_064_124_672 | 12.0 GiB | | |
| [`omniASR_W2V_7B`](https://huggingface.co/facebook/omniASR-W2V-7B)          | SSL  | 6_488_487_168 | 25.0 GiB | | |
| [`omniASR_CTC_300M`](https://huggingface.co/facebook/omniASR-CTC-300M)      | ASR  | 325_494_996   | 1.3 GiB   | ~2 GiB  | 0.001 (96x) |
| [`omniASR_CTC_1B`](https://huggingface.co/facebook/omniASR-CTC-1B)          | ASR  | 975_065_300   | 3.7 GiB   | ~3 GiB  | 0.002 (48x) |
| [`omniASR_CTC_3B`](https://huggingface.co/facebook/omniASR-CTC-3B)          | ASR  | 3_080_423_636 | 12.0 GiB  | ~8 GiB  | 0.003 (32x) |
| [`omniASR_CTC_7B`](https://huggingface.co/facebook/omniASR-CTC-7B)          | ASR  | 6_504_786_132 | 25.0 GiB  | ~15 GiB | 0.006 (16x) |
| [`omniASR_LLM_300M`](https://huggingface.co/facebook/omniASR-LLM-300M)      | ASR with optional language conditioning  | 1_627_603_584 | 6.1 GiB   | ~5 GiB  | 0.090 (~1x) |
| [`omniASR_LLM_1B`](https://huggingface.co/facebook/omniASR-LLM-1B)          | ASR with optional language conditioning  | 2_275_710_592 | 8.5 GiB   | ~6 GiB  | 0.091 (~1x) |
| [`omniASR_LLM_3B`](https://huggingface.co/facebook/omniASR-LLM-3B)          | ASR with optional language conditioning  | 4_376_679_040 | 17.0 GiB  | ~10 GiB | 0.093 (~1x) |
| [`omniASR_LLM_7B`](https://huggingface.co/facebook/omniASR-LLM-7B)          | ASR with optional language conditioning  | 7_801_041_536 | 30.0 GiB  | ~17 GiB | 0.092 (~1x) |
| [`omniASR_LLM_7B_ZS`](https://huggingface.co/facebook/omniASR-LLM-7B-ZS)    | Zero-Shot ASR | 7_810_900_608 | 30.0 GiB | ~20 GiB | 0.194 (~0.5x) |


¹ (batch=1, audio_len=30s, BF16, A100)

² Relative speed to `omniASR_LLM_7B`

---

## Installation

The models were developed using [fairseq2](https://github.com/facebookresearch/fairseq2), a research-focused sequence modeling toolkit. While we provide a **reference** inference pipeline that works across platforms, audio support requires [libsndfile](https://github.com/facebookresearch/fairseq2?tab=readme-ov-file#system-dependencies) (Mac: `brew install libsndfile`; Windows may need an additional [setup](https://github.com/facebookresearch/fairseq2?tab=readme-ov-file#installing-on-windows)).

```bash
# using pip
pip install omnilingual-asr

# using uv
uv add omnilingual-asr
```


## Inference

```python
from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline

pipeline = ASRInferencePipeline(model_card="omniASR_LLM_7B")

audio_files = ["/path/to/eng_audio1.flac", "/path/to/deu_audio2.wav"]
lang = ["eng_Latn", "deu_Latn"]
transcriptions = pipeline.transcribe(audio_files, lang=lang, batch_size=2)
```

## Supported Languages

To view the full list of 1600+ supported languages, you can access the language list [programmatically](/src/omnilingual_asr/models/wav2vec2_llama/lang_ids.py):

```python
from omnilingual_asr.models.wav2vec2_llama.lang_ids import supported_langs

# Print all supported languages
print(f"Total supported languages: {len(supported_langs)}")
print(supported_langs)

# Check if a specific language is supported
if "eng_Latn" in supported_langs:
    print("English (Latin script) is supported!")
```

Languages follow the format `{language_code}_{script}`, for example `eng_Latn` - English (Latin script), `cmn_Hans` - Mandarin Chinese (Simplified), ...

---

## Training

To further finetune the released checkpoints on your own data, use our [data preparation guide](/workflows/dataprep/README.md) followed by the [finetuning recipe guide](/workflows/recipes/wav2vec2/asr/README.md).

---

## Citation

**BibTeX:**

```bibtex
@misc{omnilingualasr2025,
  title={{Omnilingual ASR}: Open-Source Multilingual Speech Recognition for 1600+ Languages},
  author={{Omnilingual ASR Team} and Keren, Gil and Kozhevnikov, Artyom and Meng, Yen and Ropers, Christophe and Setzler, Matthew and Wang, Skyler and Adebara, Ife and Auli, Michael and Can, Balioglu and Chan, Kevin and Cheng, Chierh and Chuang, Joe and Droof, Caley and Duppenthaler, Mark and Duquenne, Paul-Ambroise and Erben, Alexander and Gao, Cynthia and Mejia Gonzalez, Gabriel and Lyu, Kehan and Miglani, Sagar and Pratap, Vineel and Sadagopan, Kaushik Ram and Saleem, Safiyyah and Turkatenko, Arina and Ventayol-Boada, Albert and Yong, Zheng-Xin and Chung, Yu-An and Maillard, Jean and Moritz, Rashel and Mourachko, Alexandre and Williamson, Mary and Yates, Shireen},
  year={2025},
  url={https://ai.meta.com/research/publications/omnilingual-asr-open-source-multilingual-speech-recognition-for-1600-languages/},
}
```

* **Developed by:** Meta AI / Omnilingual ASR Team([GitHub][1])
* **Model type:** End-to-end automatic speech recognition model (wav2vec2-style encoder with CTC head / encoder-decoder, depending on checkpoint).
* **Language(s) (NLP):** 1,600+ languages overall in Omnilingual ASR; this corpus release specifically covers **348 under-served languages** across many writing systems (Latin, Arabic, Devanagari, etc.).([GitHub][1])
* **License:** Apache-2.0 (for the model and code), CC-BY-4.0 for the `facebook/omnilingual-asr-corpus` dataset.([GitHub][1])

---

[1]: https://github.com/facebookresearch/omnilingual-asr?tab=readme-ov-file "GitHub - facebookresearch/omnilingual-asr: Omnilingual ASR Open-Source Multilingual SpeechRecognition for 1600+ Languages"
[2]: https://huggingface.co/datasets/facebook/omnilingual-asr-corpus/blob/main/README.md "README.md · facebook/omnilingual-asr-corpus at main"
[3]: https://huggingface.co/datasets/facebook/omnilingual-asr-corpus?utm_source=chatgpt.com "facebook/omnilingual-asr-corpus · Datasets at ..."
[4]: https://venturebeat.com/ai/meta-returns-to-open-source-ai-with-omnilingual-asr-models-that-can?utm_source=chatgpt.com "Meta returns to open source AI with Omnilingual ASR ..."
[5]: https://huggingface.co/spaces/facebook/omniasr-transcriptions?utm_source=chatgpt.com "Omnilingual ASR Media Transcription"
[6]: https://huggingface.co/collections/bezzam/omnilingual-asr-1-600-languages?utm_source=chatgpt.com "Omnilingual ASR (1600+ Languages) - a bezzam Collection"


