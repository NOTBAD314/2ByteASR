<div align="center">

<img src="docs/assets/readme/icon.png" width="96" alt="2ByteASR character icon: a purple-haired girl with rabbit ears">

# 2ByteASR · 兔白字幕

**More than automatic subtitles: tell speakers apart, time every word, then fix, cut and export in one window.**

A free desktop subtitle app made for game streams, stream replays and multi-speaker videos.<br>
Built for Chinese first, with Japanese and English recognition too. Run everything on your own computer, or connect your own cloud service.

[中文](README.md) · **English** · [日本語](README_JA.md) · [한국어](README_KO.md)

</div>

## Download

Current release: **0.7.5** (2026-10-17). Pick the one installer for your computer:

| Your computer | Download |
| --- | --- |
| **Windows 10 22H2 or later (64-bit)**<br>Stable | **[2ByteASR-Setup-0.7.5.exe](https://github.com/NOTBAD314/2ByteASR/releases/download/v0.7.5/2ByteASR-Setup-0.7.5.exe)** (about 1 GB)<br>The installer is not code-signed, so Windows may show an "unknown publisher" warning. See [Installing on Windows](docs/product-guide.en.md#installing-on-windows). |
| **Mac with Apple silicon (M1 or later), macOS 15 or later**<br>**Experimental** | **[2ByteASR-0.7.5-macos-arm64-Setup.dmg](https://github.com/NOTBAD314/2ByteASR/releases/download/v0.7.5/2ByteASR-0.7.5-macos-arm64-Setup.dmg)** (about 0.5 GB)<br>Tested only on GitHub's virtual Macs. **Intel Macs are not supported.** Not notarized by Apple; see [Installing on Mac](docs/product-guide.en.md#installing-on-mac-experimental) for the first launch. |

- **Slow or blocked downloads in mainland China?** Use the GitCode mirror first: [Windows installer](https://gitcode.com/Notbad314/2ByteASR/releases/download/v0.7.5/2ByteASR-Setup-0.7.5.exe) · [Mac installer](https://gitcode.com/Notbad314/2ByteASR/releases/download/v0.7.5/2ByteASR-0.7.5-macos-arm64-Setup.dmg). If that fails too, try the third-party gh-proxy accelerator: [Windows](https://gh-proxy.com/https://github.com/NOTBAD314/2ByteASR/releases/download/v0.7.5/2ByteASR-Setup-0.7.5.exe) · [Mac](https://gh-proxy.com/https://github.com/NOTBAD314/2ByteASR/releases/download/v0.7.5/2ByteASR-0.7.5-macos-arm64-Setup.dmg). The files are identical on every source; check them with `SHA256SUMS.txt`.
- **Already on 0.6.5, 0.7.0, 0.7.1, 0.7.2, 0.7.3 or 0.7.4?** Use "Check for updates" in the app; it downloads only what changed. For 0.6.0 or earlier, run the new installer over the old one without uninstalling first.
- **You don't need the other files.** The `Source`, `ThirdParty`, `update` and `.sig` files on the [Releases page](https://github.com/NOTBAD314/2ByteASR/releases/latest) are for source code, licence materials and in-app updates. `SHA256SUMS.txt` lets you check that a download is complete.

<img src="docs/assets/readme/hero-en.png" width="100%" alt="Subtitle Studio in 2ByteASR 0.7.1 with the English interface: captions list on the left, video preview with a subtitle in the middle, style panel on the right, and a timeline with one subtitle track each for Host and Teammate, a video track and the audio waveform; the home window sits behind it">

<sub>Real 0.7.1 screenshot. The sample is a self-made test card with two synthetic Chinese voices, transcribed locally with MOSS + FireRedASR2-AED + Qwen3-ASR on an NVIDIA GPU. The speaker names were set in Speaker Management.</sub>

## Before you start

- **The app is free.** Official builds cost nothing: no paid features, sign-up or subscription.
- **Local recognition downloads models first.** The installer contains no speech models. The first time you transcribe locally, the Model workshop downloads the models and runtime for the route you picked (the NVIDIA high-quality route is about 11 GB of models plus its runtime). After that it works offline and your media never leaves your computer.
- **Cloud recognition and AI features use your own accounts.** Cloud transcription needs an account and API key with the provider, is billed by them, and uploads your audio to them. AI segmentation, AI proofreading, translation and AI glossary building need your own text-AI service (only subtitle text is sent). You can transcribe, edit and export without any of these.
- **Not every computer runs every model.** Start here:

| Your computer | Recommended route | What you get |
| --- | --- | --- |
| Windows with an NVIDIA GPU | **Local**: MOSS + FireRedASR2-AED + Qwen3-ASR | Free and private; speakers, character timing, three models to compare |
| Windows without an NVIDIA GPU | **Cloud** (your API key), or **Light local** (SenseVoice on the CPU) | Cloud is pay-as-you-go and uploads audio; light local is free but slower, with one speaker |
| Mac with Apple silicon (experimental) | **Mac local** (MLX), **MOSS + FireRed** on the Apple GPU, or cloud | 16 GB of memory or more recommended; slower than an NVIDIA GPU |

- Among cloud services, MOSS Pro cloud and Qwen-Audio 3.1 (Bailian / Qwen Cloud) separate speakers. Both cloud and light local can add the local Qwen3 aligner (CPU capable) for character timing.
- The Mac MLX route is a community port and has not been checked on a physical Mac.
- Combinations that need an NVIDIA GPU are flagged before you start, with a suggestion for one that works. See [Choosing a recognition route](docs/product-guide.en.md#choosing-a-recognition-route) for details.

## What it does for you

- **[Tell speakers apart](#tell-speakers-apart).** No tagging every line by hand: routes that separate speakers put each person on their own track, with names, colours and default styles managed in one place and per-speaker export.
- **[Split subtitles on word boundaries](#split-on-word-boundaries-and-cut-the-video)**, not by scrubbing the waveform. Every character has its own timing, so a cut follows the text; you can also cut the video on the same timeline and the export follows your edit.
- **[Compare what each model heard](#compare-what-each-model-heard).** Local multi-model routes let several models transcribe the same line; differing characters are highlighted with their source, and one click applies a reading.
- **[A glossary you build once](#a-glossary-you-build-once).** Keep character names, skills and common misrecognitions per game; use them to correct recognition and to proofread existing subtitles.
- **[Find highlight candidates in stream replays](#find-highlight-candidates-in-stream-replays)** from subtitles and Bilibili danmaku XML, each with a reason and a time range, then build an edit from the ones you keep.
- **[Export subtitles, transcripts and video](#export).** SRT, ASS, TXT, JSON, per-speaker files, and MP4 / MKV / MOV with burned-in subtitles.

## See it in action

The clips and screenshots below were recorded from the real 0.7.1 window with the English interface; the subtitles are Chinese because the sample speech is Chinese. Nothing in the interface or the results was redrawn.

### Tell speakers apart

<img src="docs/assets/readme/speakers-en.png" width="100%" alt="Speaker Management dialog: two speakers, Host and Teammate, with subtitle counts and total duration; name, colour and default style fields; buttons to merge speakers, assign selected subtitles to a speaker, set as streamer and keep only one speaker's subtitles">

- Each speaker gets a subtitle track on the timeline (see the screenshot above). Drag a subtitle to another track to give it to that speaker.
- Speaker Management renames speakers, sets colours and default styles, merges speakers that were split by mistake, assigns selected subtitles, or keeps one speaker only. Everything can be undone.
- **Which routes separate speakers:** local MOSS (NVIDIA GPU, or the Apple GPU on a Mac), MOSS Pro cloud (MOSI), and Qwen-Audio 3.1 through Bailian / Qwen Cloud. Other routes return one speaker; you can split lines by hand in the Studio.

### Split on word boundaries, and cut the video

<img src="docs/assets/readme/razor-en.webp" width="100%" alt="Recorded in the app: the merge tool previews two lines joined into one, then the razor moves along the line over per-character timing blocks, with hints for snapping to character boundaries and a cut inside a character staying with the first part, and the line is split in two">

- **Splitting a subtitle** (razor, C): you see both halves before you cut, and with snapping on it stops between characters. A cut inside a character's sound keeps that character in the first half. The merge tool (B) joins two lines. Ctrl+Z undoes either.
- **Without character timing** (for example a cloud service that returns sentence times only), the split point is estimated from the text length, and the app labels the text boundary as an estimate so you can listen and check.
- **Cutting the video** is a separate thing: split clips, delete clips or ripple-delete gaps on the video track, or detect speech pauses and remove them in one step. Subtitle tracks move with the edit, the export renders the edited timeline, and your source file is never rewritten.

### Compare what each model heard

<img src="docs/assets/readme/review-en.webp" width="760" alt="Recorded in the app: in review mode one line has two candidates, the current text with MOSS and FireRed, and Qwen's reading with one differing character highlighted; choosing Qwen's reading makes it the current text">

- Press R for review mode. Each line lists the readings of the models that ran, highlights characters that differ from the current text, and names the model. Click a card (or press 1–4) to apply it; this can be undone too.
- Candidates exist only when several models ran: three on the Windows NVIDIA local route, two with MOSS + FireRed on a Mac. Cloud-only and light-local runs have nothing to compare.

### A glossary you build once

<img src="docs/assets/readme/glossary-en.png" width="100%" alt="Term library: term libraries per game on the left; on the right the selected library with Add term, AI Web Update, Smart term building, Bulk import and a term table showing each correction, category, source and Confirmed status">

These are three separate things; you can use just one of them:

1. **Maintain the glossary**: one library per game or content, each term with its correct spelling, aliases and common misrecognitions. Built-in reference terms exist for some games; only terms you confirm are used to change text. Bulk import works too, or let your AI service suggest terms (you confirm before anything is written).
2. **Apply it during recognition**: confirmed terms correct common misrecognitions by rule after recognition; local Qwen3-ASR (Chinese), Qwen-Audio 3.1 and MOSS Pro cloud also take them as hints while transcribing.
3. **Proofread existing subtitles with it** ("AI glossary proofreading"): match against the glossary only (local and free), or let your text-AI service proofread. Suggestions are listed first and applied together after you confirm, as one undo step.

This is different from comparing model readings above, which needs no glossary.

### Find highlight candidates in stream replays

In the Studio's Clip Assistant, the app reads your subtitles and, optionally, a Bilibili-format danmaku XML file. It first finds busy chat moments and strong reactions in the subtitles locally; with a text-AI service configured it then ranks them and writes titles and reasons. Each candidate has a time range: preview it, add it to the edit, then "Generate edit" to keep only those parts ("Restore full recording" brings everything back).

It reads subtitles and chat only. It does not watch the video and does not download chat for you, and its keywords and chat reactions are tuned for Chinese. Without AI, results are marked as local analysis to be checked.

### Export

- **Subtitles:** SRT, ASS, TXT, JSON; speakers merged, separate, or both. When a translation exists, export the original, the translation or bilingual SRT. SRT files also import into editors such as CapCut / Jianying.
- **Video:** MP4, MKV or MOV with subtitles burned in; the whole timeline or the in-to-out range. Fonts, outlines, positions and entrance/exit animations come as presets that need no AI.
- **Also:** still frames (PNG / JPG) and a cover editor.

## Other conveniences

- **Onboarding:** the first launch helps you pick a recognition route for your computer; a 31-step animated tutorial uses a sample project, with no models, uploads or costs.
- **Script matching:** if you already have a line-by-line script, character timing places each line without rewriting it (Chinese only from the home page for now).
- **Punctuation:** keep the original, add punctuation, or remove it; this changes display and export only.
- **Shortcuts:** every shortcut can be changed in Settings, and conflicts name the other function.
- **Interface:** Simplified Chinese, Traditional Chinese, English, Japanese, Korean; 15 themes (light, dark and high contrast) with a live preview on the Appearance page. A few labels in the English, Japanese and Korean interfaces are still shown in Chinese.
- **English, Japanese and translation:** "English recommended" and "Japanese recommended" plans; English lines break at word boundaries. Chinese, Japanese and English subtitles can be translated into Simplified or Traditional Chinese, English, Japanese or Korean with your text-AI service and exported as bilingual subtitles.
- **External AI (MCP):** lets AI clients such as Claude Desktop read and search the current project's subtitles; edits apply only after you approve them in the app. Off by default; verified on Windows only.
- **In-app updates (Windows):** download only what changed, verify before replacing, roll back automatically on failure; settings, glossaries, projects and models are kept.

## Quick start

1. **Install and launch** with the installer above.
2. **Choose how to transcribe.** On first launch pick "On this computer", "Cloud recognition" or "Light, on this computer"; the app downloads what that route needs, or opens "Apply for and set up an API" for your key.
3. **Add media and start.** Drop video or audio on the home screen, pick a glossary if you have one, and click "Start subtitles".
4. **Edit and export in Subtitle Studio.** Proofread, split and merge, adjust styles, then export subtitles or render the video.

<img src="docs/assets/readme/home-en.png" width="100%" alt="Home screen in English: drop zone for video or audio, a recent project, the Primary transcription MOSS, Subtitle timeline FireRedASR2-AED and Text review Qwen3-ASR cards, AI smart segmentation, Content & terms, and the Start subtitles button">

To learn the interface first, open Help → Beginner tutorial and follow the sample project. Installation, costs, updates and common questions are in the [user guide](docs/product-guide.en.md).

## Going further

<details>
<summary><b>How a recognition plan is put together (three roles and the model list)</b></summary>

<br>

A run uses up to three roles, combined to suit your media and hardware:

| Role | What it does | Typical choices |
| --- | --- | --- |
| Primary transcription | Writes the text; MOSS also separates speakers | MOSS, SenseVoice, Whisper, Qwen3-ASR, cloud services |
| Subtitle timeline | Gives every character a start and end time, so segmentation and cuts follow character boundaries | FireRedASR2-AED, Qwen3-ForcedAligner (CPU capable), Paraformer |
| Text review | Listens again with another model and lists the differences | Qwen3-ASR and other local or online options |

- **Local models:** MOSS-Transcribe-Diarize, FireRedASR2-AED, Qwen3-ASR 1.7B, SenseVoice Small, Paraformer Large, Whisper large-v3-turbo, Fun-ASR Nano, FireRedASR2-LLM, GLM-ASR-Nano, Canary-Qwen-2.5B (English), Qwen3-ForcedAligner 0.6B, and MLX Qwen3-ASR on Macs. On Windows, MOSS, FireRedASR2-AED, Qwen3-ASR 1.7B and FireRedASR2-LLM need an NVIDIA GPU.
- **Cloud transcription (your own account):** MOSS Pro cloud (MOSI), Alibaba Cloud Bailian / Qwen Cloud file transcription, iFlytek Spark-ASR 2.0, Groq Whisper, OpenAI, plus OpenRouter, Azure and custom compatible endpoints (advanced, not tested with real keys). Services that return sentence times only produce timing marked as estimated.
- Models are not bundled. The Model workshop downloads them on demand, checks every file against its SHA-256, and each model keeps its own licence ([model licence table](licenses/MODELS.md)).

</details>

- [User guide](docs/product-guide.en.md): installation, first launch, choosing a route, costs and privacy, updates, FAQ, running from source
- [Interface tour](docs/product-demo.en.md): progress, completion, Model workshop, export, themes and more (0.7.1 interface)
- [API setup guides](docs/api-setup/README.md) (Chinese): sign-up steps and pricing notes for each cloud and text-AI provider
- [Mac notes](docs/deployment/macos-experimental.zh-CN.md) (Chinese) · [Updating](UPDATING.md) (Chinese) · [0.7.5 release notes](docs/releases/0.7.5.md) (Chinese, English, Japanese, Korean) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

## Feedback, licences and third-party components

Please report problems in [Issues](https://github.com/NOTBAD314/2ByteASR/issues) with your version, recognition route, steps to reproduce and screenshots.

Project-owned code is licensed under **GPL-3.0-only** ([English license](LICENSE), [scope](PROJECT_LICENSE.md)). Official versions are free; GPL permits commercial use, modification and paid distribution subject to its source and other conditions. Private changes need not be published. Ordinary subtitle, video and image outputs do not become GPL merely through use of this software. Third-party components keep their own licenses: Remotion, used by the high-fidelity renderer, is free for individuals and for-profit organizations of up to 3 employees, while larger for-profit organizations need its Company License; GSAP uses its standard license. See the [third-party notices](THIRD_PARTY_NOTICES.md) and [model license table](licenses/MODELS.md); distribution materials for the full installer are still being completed ([status](licenses/DISTRIBUTION-STATUS.md)).

Source: the `main` branch holds the application source. The tag `v0.7.5` is the build source of the 0.7.5 installers, and the full build inputs are in the release's `2ByteASR-Source-0.7.5.zip` (see "Source and checksums" in the [0.7.5 release notes](docs/releases/0.7.5.md#source-and-checksums)). [SOURCE_DELIVERY.md](SOURCE_DELIVERY.md) was written for 0.5.0 and has not been updated for 0.7.5.
