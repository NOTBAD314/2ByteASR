---
language:
- en
- zh
- es
- pt
- de
- ja
- ko
- fr
- ru
- it
license: mit
pipeline_tag: automatic-speech-recognition
tags:
- ASR
- Transcription
- Speech-to-Text
- Streaming
library_name: transformers
---

## VibeVoice-ASR-Streaming-1.5B
[![GitHub](https://img.shields.io/badge/GitHub-Repo-black?logo=github)](https://github.com/microsoft/VibeVoice)
[![Live Playground](https://img.shields.io/badge/Live-Playground-green?logo=gradio)](https://aka.ms/vibeasr)

**VibeVoice-ASR-Streaming** is a unified streaming ASR model that transcribes **Who (Speaker)** said **What (Content)**, with support for **Customized Hotwords** and **10 languages**.

➡️ **Code:** [microsoft/VibeVoice](https://github.com/microsoft/VibeVoice)<br>
➡️ **Demo:** [VibeVoice-ASR-Streaming](https://aka.ms/vibeasr)<br>

<p align="left">
  <img src="figures/VibeVoice_ASR_Streaming_architecture.png" alt="VibeVoice-ASR-Streaming Architecture" height="250px">
</p>


## 🔥 Key Features


- **📝 Streaming Speaker-Attributed Transcription**:
  Continuously transcribes **who** said **what** as speech arrives.

- **👤 Customized Hotwords**:
  Users can provide customized hotwords, such as names and technical terms, to improve recognition of domain-specific content.

- **🌍 Multilingual Support**:
  It supports Chinese, English, French, German, Italian, Japanese, Korean, Portuguese, Russian, and Spanish.


## Technical Report

📄 [VibeVoice-ASR-Streaming Technical Report](https://arxiv.org/abs/2609.02812)

## Evaluation
<p align="center">
  <img src="figures/VibeVoice_ASR_Streaming_results.png" alt="VibeVoice-ASR-Streaming Results" width="80%">
</p>

## Installation and Usage

Please refer to the [GitHub repository](https://github.com/microsoft/VibeVoice).

## License
This project is licensed under the MIT License.

## Contact
This project was conducted by members of Microsoft Research. We welcome feedback and collaboration from our audience. If you have suggestions, questions, or observe unexpected/offensive behavior in our technology, please contact us at VibeVoice@microsoft.com.
If the team receives reports of undesired behavior or identifies issues independently, we will update this repository with appropriate mitigations.
