---
license: cc-by-4.0
language:
- en
library_name: nemo
datasets:
- Granary
- YTC
- Yodas2
- LibriLight
- librispeech_asr
- fisher_corpus
- Switchboard-1
- WSJ-0
- WSJ-1
- National-Singapore-Corpus-Part-1
- National-Singapore-Corpus-Part-6
- vctk
- voxpopuli
- europarl
- multilingual_librispeech
- fleurs
- mozilla-foundation/common_voice_8_0
- MLCommons/peoples_speech
thumbnail: null
tags:
- automatic-speech-recognition
- speech
- audio
- Transformer
- FastConformer
- Conformer
- pytorch
- NeMo
- Qwen
- hf-asr-leaderboard
widget:
- example_title: Librispeech sample 1
  src: https://cdn-media.huggingface.co/speech_samples/sample1.flac
- example_title: Librispeech sample 2
  src: https://cdn-media.huggingface.co/speech_samples/sample2.flac
model-index:
- name: canary-qwen-2.5b
  results:
  - task:
      name: Automatic Speech Recognition
      type: automatic-speech-recognition
    dataset:
      name: AMI (Meetings test)
      type: edinburghcstr/ami
      config: ihm
      split: test
      args:
        language: en
    metrics:
    - name: Test WER
      type: wer
      value: 10.19
  - task:
      name: Automatic Speech Recognition
      type: automatic-speech-recognition
    dataset:
      name: Earnings-22
      type: revdotcom/earnings22
      split: test
      args:
        language: en
    metrics:
    - name: Test WER
      type: wer
      value: 10.45
  - task:
      name: Automatic Speech Recognition
      type: automatic-speech-recognition
    dataset:
      name: GigaSpeech
      type: speechcolab/gigaspeech
      split: test
      args:
        language: en
    metrics:
    - name: Test WER
      type: wer
      value: 9.43
  - task:
      name: Automatic Speech Recognition
      type: automatic-speech-recognition
    dataset:
      name: LibriSpeech (clean)
      type: librispeech_asr
      config: other
      split: test
      args:
        language: en
    metrics:
    - name: Test WER
      type: wer
      value: 1.61
  - task:
      name: Automatic Speech Recognition
      type: automatic-speech-recognition
    dataset:
      name: LibriSpeech (other)
      type: librispeech_asr
      config: other
      split: test
      args:
        language: en
    metrics:
    - name: Test WER
      type: wer
      value: 3.1
  - task:
      type: Automatic Speech Recognition
      name: automatic-speech-recognition
    dataset:
      name: SPGI Speech
      type: kensho/spgispeech
      config: test
      split: test
      args:
        language: en
    metrics:
    - name: Test WER
      type: wer
      value: 1.9
  - task:
      type: Automatic Speech Recognition
      name: automatic-speech-recognition
    dataset:
      name: tedlium-v3
      type: LIUM/tedlium
      config: release1
      split: test
      args:
        language: en
    metrics:
    - name: Test WER
      type: wer
      value: 2.71
  - task:
      name: Automatic Speech Recognition
      type: automatic-speech-recognition
    dataset:
      name: Vox Populi
      type: facebook/voxpopuli
      config: en
      split: test
      args:
        language: en
    metrics:
    - name: Test WER
      type: wer
      value: 5.66
metrics:
- wer
base_model:
- nvidia/canary-1b-flash
- Qwen/Qwen3-1.7B
---

<style>
img {
 display: inline;
}
</style>

[![Model architecture](https://img.shields.io/badge/Model_Arch-SALM-blue#model-badge)](#model-architecture)
| [![Model size](https://img.shields.io/badge/Params-2.5B-green#model-badge)](#model-architecture)
| [![Language](https://img.shields.io/badge/Language-en-orange#model-badge)](#datasets)


# Model Overview

## Description:
NVIDIA NeMo Canary-Qwen-2.5B is an English speech recognition model that achieves state-of-the art performance on multiple English speech benchmarks. With 2.5 billion parameters and running at 418 RTFx, Canary-Qwen-2.5B supports automatic speech-to-text recognition (ASR) in English with punctuation and capitalization (PnC). The model works in two modes: as a transcription tool (ASR mode) and as an LLM (LLM mode). In ASR mode, the model is only capable of transcribing the speech into text, but does not retain any LLM-specific skills such as reasoning. In LLM mode, the model retains all of the original LLM capabilities, which can be used to post-process the transcript, e.g. summarize it or answer questions about it. In LLM mode, the model does not "understand" the raw audio anymore - only its transcript. This model is ready for commercial use.

### License/Terms of Use: 
Canary-Qwen-2.5B is released under the CC-BY-4.0 license. By using this model, you are agreeing to the [terms and conditions](https://choosealicense.com/licenses/cc-by-4.0/) of the license. <br>

### Discover more from NVIDIA: 
For documentation, deployment guides, enterprise-ready APIs, and the latest open models—including Nemotron and other cutting-edge speech, translation, and generative AI—visit the NVIDIA Developer Portal at developer.nvidia.com.
Join the community to access tools, support, and resources to accelerate your development with NVIDIA’s NeMo, Riva, NIM, and foundation models.<br>

#### Explore more from NVIDIA: <br>
What is [Nemotron](https://www.nvidia.com/en-us/ai-data-science/foundation-models/nemotron/)?<br>
NVIDIA Developer [Nemotron](https://developer.nvidia.com/nemotron)<br>
[NVIDIA Riva Speech](https://developer.nvidia.com/riva?sortBy=developer_learning_library%2Fsort%2Ffeatured_in.riva%3Adesc%2Ctitle%3Aasc#demos)<br>
[NeMo Documentation](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/models.html)<br>

## References:
[1] [Less is More: Accurate Speech Recognition & Translation without Web-Scale Data](https://www.isca-archive.org/interspeech_2024/puvvada24_interspeech.pdf)

[2] [Fast Conformer with Linearly Scalable Attention for Efficient Speech Recognition](https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=10389701)

[3] [Attention Is All You Need](https://arxiv.org/abs/1706.03762)

[4] [Qwen/Qwen3-1.7B Model Card](https://huggingface.co/Qwen/Qwen3-1.7B)

[5] [Training and Inference Efficiency of Encoder-Decoder Speech Models](https://arxiv.org/abs/2503.05931)

[6] [NVIDIA NeMo Toolkit](https://github.com/NVIDIA/NeMo)

[7] [Granary: Speech Recognition and Translation Dataset in 25 European Languages](https://arxiv.org/abs/2505.13404)

[8] [Towards Measuring Fairness in AI: the Casual Conversations Dataset](https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=9634168)

[9] [SALM: Speech-augmented Language Model with In-context Learning for Speech Recognition and Translation](https://arxiv.org/abs/2310.09424) 

### Deployment Geography:

Global

### Use Case:

The model is intended for users requiring speech-to-text transcription capabilities for English speech, and/or transcript post-processing capabilities enabled by prompting the underlying LLMs. Typical use-cases: transcription, summarization, answering user questions about the transcript.

### Release Date:

Huggingface 07/17/2025 via https://huggingface.co/nvidia/canary-qwen-2.5b

## Discover more from NVIDIA:
For documentation, deployment guides, enterprise-ready APIs, and the latest open models—including Nemotron and other cutting-edge speech, translation, and generative AI—visit the NVIDIA Developer Portal at [developer.nvidia.com](https://developer.nvidia.com/).
Join the community to access tools, support, and resources to accelerate your development with NVIDIA’s NeMo, Riva, NIM, and foundation models.<br>

### Explore more from NVIDIA:  <br>
What is [Nemotron](https://www.nvidia.com/en-us/ai-data-science/foundation-models/nemotron/)?<br>
NVIDIA Developer [Nemotron](https://developer.nvidia.com/nemotron)<br>
[NVIDIA Riva Speech](https://developer.nvidia.com/riva?sortBy=developer_learning_library%2Fsort%2Ffeatured_in.riva%3Adesc%2Ctitle%3Aasc#demos)<br>
[NeMo Documentation](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/models.html)<br>

## Model Architecture:
Canary-Qwen is a Speech-Augmented Language Model (SALM) [9] model with FastConformer [2] Encoder and Transformer Decoder [3]. It is built using two base models: `nvidia/canary-1b-flash` [1,5] and `Qwen/Qwen3-1.7B` [4], a linear projection, and low-rank adaptation (LoRA) applied to the LLM. The audio encoder computes audio representation that is mapped to the LLM embedding space via a linear projection, and concatenated with the embeddings of text tokens. The model is prompted with "Transcribe the following: <audio>", using Qwen's chat template.

### Limitations

**Input length.** The maximum audio duration in training was 40s, and the maximum token sequence length was 1024 tokens (including prompt, audio, and response). The model may technically be able to process longer sequences, but its accuracy may be degraded.

**Exclusively ASR oriented capabilities.** The model is not expected to preserve any of the underlying LLM's capabilities into speech modality. 

**English-only language support.** The model was trained using English data only. It may be able to spuriously transcribe other languages as the underlying encoder was pretrained using German, French, and Spanish speech in addition to English, but it's unlikely to be reliable as a multilingual model.

## NVIDIA NeMo

To train, fine-tune or transcribe with Canary-Qwen-2.5B, you will need to install [NVIDIA NeMo](https://github.com/NVIDIA/NeMo).

```bash
# Currently requires installing the latest trunk version of NeMo, and PyTorch 2.6+ for FSDP2 support.
python -m pip install "nemo_toolkit[asr,tts] @ git+https://github.com/NVIDIA/NeMo.git"
```

## How to Use this Model

The model is available for use in the NVIDIA NeMo toolkit [6], and can be used as a pre-trained checkpoint for inference or for fine-tuning on another dataset.

### Loading the Model

```python
from nemo.collections.speechlm2.models import SALM

model = SALM.from_pretrained('nvidia/canary-qwen-2.5b')
```

## Input: 

**Input Type(s):** Audio, text prompt <br>
**Input Format(s):** Audio: .wav or .flac files. Text prompt string for ASR mode: `Transcribe the following: <|audioplaceholder|>` <br>
**Input Parameters(s):** Audio: Two-Dimensional (batch, audio-samples); Text: One-Dimensional (string) <br>
**Other Properties Related to Input:** 16000 Hz Mono-channel Audio, Pre-Processing Not Needed <br>

Input to Canary-Qwen-2.5B is a batch of prompts that include audio.

Example usage in ASR mode (speech-to-text):

```python
answer_ids = model.generate(
    prompts=[
        [{"role": "user", "content": f"Transcribe the following: {model.audio_locator_tag}", "audio": ["speech.wav"]}]
    ],
    max_new_tokens=128,
)
print(model.tokenizer.ids_to_text(answer_ids[0].cpu()))
```

Example usage in LLM mode (text-only):

```python
prompt = "..."
transcript = "..."
with model.llm.disable_adapter():
    answer_ids = model.generate(
        prompts=[[{"role": "user", "content": f"{prompt}\n\n{transcript}"}]],
        max_new_tokens=2048,
    )
```

To transcribe a dataset of recordings, specify the input as jsonl manifest file, where each line in the file is a dictionary containing the following fields: 

```yaml
# Example of a line in input_manifest.json
{
    "audio_filepath": "/path/to/audio.wav",  # path to the audio file
    "duration": 30.0,  # duration of the audio
}
```

and then use:
```bash
cd NeMo
python examples/speechlm2/salm_generate.py \
  pretrained_name=nvidia/canary-qwen-2.5b \
  inputs=input_manifest.json \
  output_manifest=generations.jsonl \
  batch_size=128 \
  user_prompt="Transcribe the following:"  # audio locator is added automatically at the end if not present
```

## Output:
**Output Type(s):** Text <br>
**Output Format:** Text transcript as a sequence of token IDs or a string <br> 
**Output Parameters:** One-Dimensional text string <br>
**Other Properties Related to Output:** May Need Inverse Text Normalization <br>

Our AI models are designed and/or optimized to run on NVIDIA GPU-accelerated systems. By leveraging NVIDIA’s hardware (e.g. GPU cores) and software frameworks (e.g., CUDA libraries), the model achieves faster training and inference times compared to CPU-only solutions.

## Software Integration:
**Runtime Engine(s):** 
* NeMo - 2.5.0 or higher <br>

**Supported Hardware Microarchitecture Compatibility:** <br>
* [NVIDIA Ampere] <br>
* [NVIDIA Blackwell] <br>
* [NVIDIA Jetson]  <br>
* [NVIDIA Hopper] <br>
* [NVIDIA Lovelace] <br>
* [NVIDIA Pascal] <br>
* [NVIDIA Turing] <br>
* [NVIDIA Volta] <br>

**[Preferred/Supported] Operating System(s):** <br>
* [Linux] <br>
* [Linux 4 Tegra] <br>
* [Windows] <br>

## Model Version(s): 
Canary-Qwen-2.5B <br>

## Training

Canary-Qwen-2.5B was trained using the NVIDIA NeMo toolkit [6] for a total of 90k steps on 32 NVIDIA A100 80GB GPUs. LLM parameters were kept frozen. Speech encoder, projection, and LoRA parameters were trainable. The encoder's output frame rate is 80ms, or 12.5 tokens per second. The model was trained on approximately 1.3B tokens in total (this number inlcudes the speech encoder output frames, text response tokens, prompt tokens, and chat template tokens). 

The model can be trained using this [example script](https://github.com/NVIDIA/NeMo/blob/main/examples/speechlm2/salm_train.py) and [base config](https://github.com/NVIDIA/NeMo/blob/main/examples/speechlm2/conf/salm.yaml).

The tokenizer was inherited from `Qwen/Qwen3-1.7B`.

# Training and Evaluation Datasets: 

## Training Dataset:

** The total size (in number of data points): approx. 40 million (speech, text) pairs
** Total number of datasets: 26, with 18 for training and 8 for test
** Dataset partition: Training 99.6%, testing 0.04%, validation 0%
** Time period for training data collection: 1990-2025
** Time period for testing data collection: 2005-2022
** Time period for validation data collection N/A (unused)

The Canary-Qwen-2.5B model is trained on a total of 234K hrs of publicly available speech data.
The datasets below include conversations, videos from the web and audiobook recordings.

**Data Collection Method:**
* Human <br>

**Labeling Method:**
* Hybrid: Human, Automated <br>

### Properties

#### English (234.5k hours)

The majority of the training data comes from the English portion of the Granary dataset [7]:

- YouTube-Commons (YTC) (109.5k hours)
- YODAS2 (77k hours)
- LibriLight (13.6k hours)

In addition, the following datasets were used:
- Librispeech 960 hours
- Fisher Corpus
- Switchboard-1 Dataset
- WSJ-0 and WSJ-1
- National Speech Corpus (Part 1, Part 6)
- VCTK
- VoxPopuli (EN)
- Europarl-ASR (EN)
- Multilingual Librispeech (MLS EN)
- Mozilla Common Voice (v11.0)
- Mozilla Common Voice (v7.0)
- Mozilla Common Voice (v4.0)
- AMI
- FLEURS

AMI was oversampled during model training to constitute about 15% of the total data observed. 
This skewed the model towards predicting verbatim transcripts that include conversational speech disfluencies such as repetitions.

The training transcripts contained punctuation and capitalization.

## Evaluation Dataset:

**Data Collection Method:** <br>
* Human <br>

**Labeling Method:** <br>
* Human <br>

Automatic Speech Recognition: 
* [HuggingFace OpenASR Leaderboard evaluation sets](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard)

Hallucination Robustness:
* [MUSAN](https://www.openslr.org/17/) 48 hrs eval set

Noise Robustness:
* [Librispeech](https://www.openslr.org/12)

Model Fairness:
* [Casual Conversations Dataset](https://arxiv.org/pdf/2104.02821)

## Performance

The ASR predictions were generated using greedy decoding.

### ASR Performance (w/o PnC) 

The ASR performance is measured with word error rate (WER), and we process the groundtruth and predicted text with [whisper-normalizer](https://pypi.org/project/whisper-normalizer/) version 0.1.12.

WER on [HuggingFace OpenASR leaderboard](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard):

| **Version** | **Model**     | **RTFx**   | **Mean**   | **AMI**   | **GigaSpeech**   | **LS Clean**   | **LS Other**   | **Earnings22**   | **SPGISpech**   | **Tedlium**   | **Voxpopuli**   |
|:---------:|:-----------:|:------:|:------:|:------:|:------:|:------:|:------:|:------:|:------:|:------:|:------:|
| 2.5.0  | Canary-Qwen-2.5B | 418 | 5.63 | 10.18 | 9.41 | 1.60 | 3.10 | 10.42 | 1.90 | 2.72 | 5.66 |

More details on evaluation can be found at [HuggingFace ASR Leaderboard](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard)

### Hallucination Robustness
Number of characters per minute on [MUSAN](https://www.openslr.org/17) 48 hrs eval set (`max_new_tokens=50` following `nvidia/canary-1b-flash` evaluation)
| **Version** | **Model** | **# of character per minute** |
|:-----------:|:---------:|:----------:|
| 2.5.0       | Canary-Qwen-2.5B |   138.1   |

### Noise Robustness
WER on [Librispeech Test Clean](https://www.openslr.org/12) at different SNR (signal to noise ratio) levels of additive white noise

| **Version** | **Model** | **SNR 10** | **SNR 5** | **SNR 0** | **SNR -5** |
|:-----------:|:---------:|:----------:|:----------:|:----------:|:----------:|
| 2.5.0       | Canary-Qwen-2.5B |    2.41%   |   4.08%   |   9.83%   |    30.60%  |

## Model Fairness Evaluation

As outlined in the paper "Towards Measuring Fairness in AI: the Casual Conversations Dataset" [8], we assessed the Canary-Qwen-2.5B model for fairness. The model was evaluated on the CasualConversations-v1 dataset with inference done on non-overlapping 40s chunks, and the results are reported as follows:

### Gender Bias:

| Gender | Male | Female | N/A | Other |
| :--- | :--- | :--- | :--- | :--- |
| Num utterances | 18471 | 23378 | 880 | 18 |
| % WER | 16.71 | 13.85 | 17.71 | 29.46 |

### Age Bias:

| Age Group | (18-30) | (31-45) | (46-85) | (1-100) |
| :--- | :--- | :--- | :--- | :--- |
| Num utterances | 15058 | 13984 | 12810 | 41852 |
| % WER | 15.73 | 15.3 | 14.14 | 15.11 |

(Error rates for fairness evaluation are determined by normalizing both the reference and predicted text, similar to the methods used in the evaluations found at https://github.com/huggingface/open_asr_leaderboard.)

## Inference:
**Engine:** NVIDIA NeMo <br>
**Test Hardware :** <br>
* A6000 <br>
* A100 <br>
* RTX 5090 <br>

## Ethical Considerations:
NVIDIA believes Trustworthy AI is a shared responsibility and we have established policies and practices to enable development for a wide array of AI applications.  When downloaded or used in accordance with our terms of service, developers should work with their internal model team to ensure this model meets requirements for the relevant industry and use case and addresses unforeseen product misuse.  
For more detailed information on ethical considerations for this model, please see the Model Card++ Explainability, Bias, Safety & Security, and Privacy Subcards. Please report security vulnerabilities or NVIDIA AI Concerns [here](https://www.nvidia.com/en-us/support/submit-security-vulnerability/).
