# 2ByteASR user guide

Last checked: 2026-10-15, for the public release **0.7.2**. This guide replaces the earlier version that described "0.5.0" and said no public installer was available; that is no longer true.

[Back to the README](../README_EN.md) · [Interface tour](product-demo.en.md) · [API setup guides (Chinese)](api-setup/README.md) · [中文](product-guide.zh-CN.md) · [日本語](product-guide.ja.md) · [한국어](product-guide.ko.md)

**Contents:** [Which file to download](#which-file-to-download) · [Installing on Windows](#installing-on-windows) · [Installing on Mac (experimental)](#installing-on-mac-experimental) · [First launch](#first-launch) · [Choosing a recognition route](#choosing-a-recognition-route) · [Costs and privacy](#costs-and-privacy) · [Recognition plans and models](#recognition-plans-and-models) · [Everyday Studio actions](#everyday-studio-actions) · [Input and output](#input-and-output) · [Updating](#updating) · [Common questions](#common-questions) · [Running from source](#running-from-source) · [Reporting problems](#reporting-problems)

## Which file to download

| Your computer | Download | Status |
| --- | --- | --- |
| Windows 10 22H2 (19045) or later, 64-bit | [`2ByteASR-Setup-0.7.2.exe`](https://github.com/NOTBAD314/2ByteASR/releases/download/v0.7.2/2ByteASR-Setup-0.7.2.exe) (about 1 GB) | Stable |
| Mac with Apple silicon (M1 or later), macOS 15 or later | [`2ByteASR-0.7.2-macos-arm64-Setup.dmg`](https://github.com/NOTBAD314/2ByteASR/releases/download/v0.7.2/2ByteASR-0.7.2-macos-arm64-Setup.dmg) (about 0.5 GB) | Experimental; Intel Macs not supported |

What the other files on the [Releases page](https://github.com/NOTBAD314/2ByteASR/releases/latest) are for:

| File | For |
| --- | --- |
| `2ByteASR-Source-0.7.2.zip` | Reading or rebuilding the installer: the complete build inputs of the Windows installer |
| `2ByteASR-ThirdParty-Materials-0.7.2.zip`, `mingw-w64-libiconv-…src.tar.zst`, `…GPL-Additional-Permission.txt` | Third-party licence terms, notices and upstream source |
| `2ByteASR-update.json(.sig)`, `2ByteASR-0.7.2-<component>-<hash>.zip` | Used automatically by in-app updates; no need to download |
| `SHA256SUMS.txt(.sig)` | Checking that a download is complete and was published by this project |

## Installing on Windows

1. Download `2ByteASR-Setup-0.7.2.exe`. To check it, open PowerShell in the download folder, run `certutil -hashfile 2ByteASR-Setup-0.7.2.exe SHA256`, and compare with `SHA256SUMS.txt` from the release.
2. Run the installer. It installs to `%LOCALAPPDATA%\Programs\2ByteASR` by default, needs no administrator rights, and can go on another drive. It takes about 1.9 GB.
3. The installer is **not code-signed**, so Windows may show "unknown publisher" or "Windows protected your PC". Once you have confirmed the file came from this repository's Releases and the checksum matches, click "More info" → "Run anyway". **There is no need to turn off SmartScreen, antivirus or other security features, and you should not.**
4. Start the app from the Start menu or the desktop shortcut.

**Already installed an earlier version?** From 0.6.5, 0.7.0 or 0.7.2, use "Check for updates" in the app; it downloads only what changed (about 50 MB from 0.7.2). From 0.6.0 or earlier, close the app and run the new installer over it **without uninstalling first**. Settings, glossaries, projects, downloaded models and runtimes are kept.

**Where files go:** settings, glossaries, projects and logs live in `%LOCALAPPDATA%\2ByteASR`. On a new installation, models download to a `models` folder next to the program (install on drive D and the models go to D too); models downloaded earlier are reused where they are.

## Installing on Mac (experimental)

**Supported:** Apple silicon (M series) with macOS 14 or later (from 0.8.5; 0.8.4 and earlier need macOS 15). **Intel Macs are not supported.** 16 GB of memory or more is recommended; 8 GB Macs have not been tested. This version was checked only on GitHub's virtual Macs (virtual M1, 7 GB of memory), not on a physical Mac.

1. Download the DMG. To check it, run `shasum -a 256 2ByteASR-0.7.2-macos-arm64-Setup.dmg` in Terminal and compare with `SHA256SUMS.txt`.
2. Open the DMG and drag `2ByteASR` into Applications.
3. The app has **no Developer ID signature and is not notarized by Apple**. The first time, Control-click the app in Finder, choose "Open", then "Open" again. If it is still blocked, go to System Settings → Privacy & Security and click "Open Anyway" near the bottom. **There is no need to turn off Gatekeeper or other security settings, and you should not.**
4. After that, open it normally.

Models, runtimes, settings, projects and logs are in `~/Library/Application Support/2ByteASR`; API keys are kept in the macOS Keychain. Known limits of the Mac version (speed, the top toolbar overlapping in narrow windows, the status "部分降级成功", partially degraded, without text review) are listed in the [Mac notes](deployment/macos-experimental.zh-CN.md) (Chinese).

## First launch

On a fresh installation, the first launch asks how you want to transcribe (once; you can reopen it later from the home screen hint or the Help menu):

| Choice | What it uses | First download | Good for |
| --- | --- | --- | --- |
| **On this computer** (Windows) | MOSS + FireRedASR2-AED + Qwen3-ASR | About 11 GB of models plus the runtime (including CUDA PyTorch) | An NVIDIA GPU; speakers, character timing and model comparison |
| **Cloud recognition** | MOSS Pro cloud (MOSI), Alibaba Cloud Bailian, Qwen Cloud and others | No models | No GPU and quick results; needs an API key, pay as you go |
| **Light, on this computer** | SenseVoice on the CPU | About 0.9 GB plus the runtime | No GPU and no uploads; slower, one speaker |
| **On this Mac** (Apple silicon) | MLX Qwen3-ASR and aligner | About 2.3 GB plus the runtime | Macs, without uploads; a community port not yet checked on a physical Mac |

Local choices open the Model workshop and start downloading; the cloud choice opens "Apply for and set up an API" so you can sign up and enter your key. Without an NVIDIA GPU, the "On this computer" card says no usable NVIDIA GPU was found and cannot be selected.

To learn the interface first, open Help → Beginner tutorial. The 31-step animated tutorial walks through the home screen and Subtitle Studio with a sample project; you can follow along or press "Do it for me". It needs no models, uploads nothing and costs nothing.

## Choosing a recognition route

| Your computer | Recommended | Speakers | Character timing | Model candidates |
| --- | --- | --- | --- | --- |
| Windows with an NVIDIA GPU | Local MOSS + FireRedASR2-AED + Qwen3-ASR | Yes (MOSS) | Yes (measured by FireRed) | Three |
| Windows without an NVIDIA GPU | Cloud recognition | MOSS Pro cloud and Qwen-Audio 3.1 yes; other services no | Bailian / Qwen Cloud yes; services with sentence times only are marked as estimated | None |
| Windows without an NVIDIA GPU, no uploads | Light local (SenseVoice) | No | Yes once you add the local Qwen3 aligner (CPU capable) | None |
| Cloud + local alignment | Cloud writes the text, the local Qwen3 aligner adds timing | Depends on the service | Yes (aligned locally, nothing uploaded) | None |
| Mac with Apple silicon | On this Mac (MLX), or MOSS + FireRed on the Apple GPU (prepared in the Model workshop), or cloud | Yes with MOSS | Yes | Two with MOSS + FireRed |

Notes:

- **Components that need an NVIDIA GPU** on Windows: MOSS, FireRedASR2-AED, Qwen3-ASR 1.7B and FireRedASR2-LLM. The role cards, the home screen hint and the start check all say so and offer "Switch to one that works here".
- **CPU-capable components:** SenseVoice and Qwen3-ForcedAligner (alignment, slower). Whisper, Paraformer and Fun-ASR also fall back to the CPU without a GPU, but they have not been fully tested on the CPU.
- **How cloud services differ** (see the [API setup guides](api-setup/README.md), Chinese): MOSS Pro cloud needs one key and separates speakers but returns sentence times only; Bailian / Qwen Cloud file transcription returns word times, Qwen-Audio 3.1 also separates speakers, and regular use needs your own private OSS bucket. Before each run the app lists the engine, where the timing comes from, where audio is uploaded and the expected cost; it never silently switches to a paid service.
- **Mac:** MOSS + FireRed ran about 3–4 times slower than real time on the virtual Mac; components that only run on NVIDIA are marked as unavailable on that computer.

## Costs and privacy

- **The app is free**, with no paid features, sign-up or subscription.
- **Local recognition:** after the models are downloaded it works offline; your media stays on your computer.
- **Cloud recognition:** audio is uploaded to the provider you choose and billed by them (check their pricing page). The app never signs you up or pays for you.
- **Text AI** (DeepSeek, Alibaba Cloud Bailian, OpenAI, Gemini, xAI or a custom compatible service, all with your own key): only subtitle text is sent. It is used by AI segmentation, AI proofreading, the AI mode of AI glossary proofreading, subtitle translation (Chinese, Japanese and English subtitles into Simplified or Traditional Chinese, English, Japanese or Korean), AI term building and web updates of glossaries, AI ranking of highlight candidates, and AI Subtitle Design. Without it these features are unavailable or fall back to local rules; recognition, editing and export work as usual.
- **External AI (MCP):** off by default. When enabled, your AI client reads the current project's subtitle text and sends it to the AI service that client uses.

## Recognition plans and models

A run uses up to three roles:

| Role | What it does | Common choices |
| --- | --- | --- |
| Primary transcription | Writes the text; MOSS and some cloud services also separate speakers | MOSS, SenseVoice, Whisper, Qwen3-ASR, cloud services |
| Subtitle timeline | Gives every character a start and end time, so segmentation and cuts follow character boundaries | FireRedASR2-AED, Qwen3-ForcedAligner, Paraformer |
| Text review | Listens again with another model and lists the differences for you to compare in the Studio | Qwen3-ASR and other local or online options |

- The home screen's Recognition plan offers ready-made combinations by goal (Quality first, light and fast, online, Japanese recommended, English recommended and more), or you can change each role yourself.
- Models are downloaded in the Model workshop. Each card shows size, how it runs and a "reference index" (a relative 1–100 guide for choosing, **not an accuracy figure**).
- Downloads try ModelScope (pinned revisions), then official Hugging Face, then hf-mirror.com. Every file must match its locked SHA-256, and downloads resume after interruptions.
- Local models: MOSS-Transcribe-Diarize, FireRedASR2-AED, Qwen3-ASR 1.7B, SenseVoice Small, Paraformer Large, Whisper large-v3-turbo, Fun-ASR Nano, FireRedASR2-LLM, GLM-ASR-Nano, Canary-Qwen-2.5B (English), Qwen3-ForcedAligner 0.6B, a Japanese CTC aligner, and MLX Qwen3-ASR with its aligner on Macs. See the [model licence table](../licenses/MODELS.md).

## Everyday Studio actions

| To do this | Do this |
| --- | --- |
| Split a subtitle | Razor tool (C): move to preview, click to split; with snapping (S) on it stops between characters |
| Merge subtitles | Merge tool (B), or Ctrl+Shift+M to merge with the next line |
| Undo / redo | Ctrl+Z / Ctrl+Y |
| Compare candidates, apply another reading | R for review mode; 1–4 applies and moves to the next line |
| Rename a speaker, set colour and default style | Speaker Management; or drag a subtitle to another speaker's track |
| Cut part of the video | Select a video clip and ripple-cut with Q / W, or right-click a clip to delete it; the Clip Assistant can detect speech pauses |
| Find highlight candidates | Analyse subtitles and danmaku XML in the Clip Assistant, then "Generate edit" |
| Proofread with a glossary | "AI proofread" at the top left of the Studio, or "AI glossary proofreading…" on the completion page |
| Time an existing script | "Match script" in the Studio: preview first, then replace |
| Change shortcuts | Settings → Shortcuts |

These are the default shortcuts; all of them can be changed.

**AI Subtitle Design (advanced, needs an AI service):** the Studio's AI Design tab turns a description into three editable caption looks with motion, using the AI service you configured. Ordinary presets for font, outline, position and entrance/exit animation need no AI. The woodcut and CRT effects in the [interface tour](product-demo.en.md#ai-subtitle-design-examples) are sample works made with AI Subtitle Design, not built-in presets.

## Input and output

| Purpose | Formats |
| --- | --- |
| Video input | MP4, MOV, MKV, WebM, FLV, AVI |
| Audio input | MP3, WAV, M4A, FLAC, AAC |
| Subtitle import in the Studio | SRT, ASS |
| Danmaku (for highlight candidates) | Bilibili-format danmaku XML (local file) |
| Subtitle export | SRT, ASS, TXT, JSON; speakers merged, separate or both; original, translation or bilingual SRT when a translation exists |
| Video export | MP4, MKV, MOV with burned-in subtitles; the whole timeline or in to out |
| Other | Still frames (PNG / JPG), covers; the `.2byteproj` project file keeps every edit |

## Updating

- **Windows 0.6.5 or later:** "Check for updates" in the app. Only changed parts are downloaded and each file is verified; files are replaced after you save your project and agree to quit, and any failure restores the previous version.
- **Windows 0.6.0 or earlier:** run the new installer over the old one without uninstalling.
- **Mac:** download the new DMG and drag the app over the old one in Applications.

The full description is in [UPDATING.md](../UPDATING.md) (Chinese).

## Common questions

**The installer says "unknown publisher" or "Windows protected your PC".** The installer is not code-signed. After confirming it came from this repository's Releases and the checksum matches, click "More info" → "Run anyway". Do not turn off your antivirus or SmartScreen.

**The home screen says an NVIDIA GPU is needed.** The current combination includes a component that only runs on NVIDIA GPUs. Click "Switch to one that works here", or pick cloud recognition or light local as described in [Choosing a recognition route](#choosing-a-recognition-route).

**Model downloads are slow or stop.** Downloads resume, and the app tries ModelScope, Hugging Face and hf-mirror.com in turn; the download window shows the current source and why it switched. Every file must pass its SHA-256 check before use.

**The run finished "with items to review".** A completed run does not mean every line has been confirmed. Open review mode (R) in the Studio and go through the suggested items.

**A subtitle's timing is marked as estimated.** That line has no measured character timing (for example the cloud service returned sentence times only), so split points are estimated from text length. Adding the local Qwen3 aligner, or using a service with word times, gives measured timing.

**Is my data kept if I uninstall?** Yes. Uninstalling removes only the program files the installer put there; models downloaded later, projects, settings and glossaries are kept, and updates or reinstalling keep them too. To remove everything, delete `%LOCALAPPDATA%\2ByteASR` and the `models` folder in the program folder (on a Mac, `~/Library/Application Support/2ByteASR`).

## Running from source

```powershell
git clone https://github.com/NOTBAD314/2ByteASR.git
cd 2ByteASR
.\setup_environment.bat
.\.venv-main\Scripts\python.exe quick_start.py
```

- The `main` branch holds the application source. The tag `v0.7.2` is the build source of the 0.7.2 installers, and the full build inputs are in the release's `2ByteASR-Source-0.7.2.zip`; see "Source and checksums" in the [0.7.2 release notes](releases/0.7.2.md#source-and-checksums).
- Development and testing conventions are in [CONTRIBUTING.md](../CONTRIBUTING.md).
- [BUILD_FROM_SOURCE.md](../BUILD_FROM_SOURCE.md), [SOURCE_ONLY_SCOPE.md](../SOURCE_ONLY_SCOPE.md) and [SOURCE_DELIVERY.md](../SOURCE_DELIVERY.md) were written for 0.5.0. They record that release's source scope and build, and have not been updated for 0.7.2.

## Reporting problems

Open an [issue](https://github.com/NOTBAD314/2ByteASR/issues) with your version, operating system, recognition route, steps to reproduce and screenshots. For recognition problems you can attach the run log from the completion page (remove local paths and other personal details first).

[Back to the README](../README_EN.md) · [Interface tour](product-demo.en.md) · [Third-party notices](../THIRD_PARTY_NOTICES.md)
