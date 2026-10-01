<div align="center">
<img src="assets/2byteasr-icon-transparent.png" width="100" alt="2ByteASR mascot" />

# 2ByteASR · 兔白字幕

**Accurate subtitles. Easier video editing.**

A free tool for subtitle transcription and video editing, with local processing.<br/>
Transcribe, proofread, design animated subtitles, and export your video in one place.

[Source scope](SOURCE_ONLY_SCOPE.md) · [Product tour](docs/product-demo.en.md) · [Quick start](#download-and-quick-start)

[中文](README.md) · [English](README_EN.md) · [日本語](README_JA.md)
</div>

![2ByteASR home: media, Subtitle Studio, and three recognition roles](docs/assets/readme/overview.png)

*Start from the home screen: prepare your media and recognition setup, or open Subtitle Studio to continue editing.*

## One set of subtitles, three roles

Platform status: Windows provides the desktop workflow; no installer is publicly available yet. The [native macOS desktop experiment](docs/deployment/macos-experimental.zh-CN.md) is in development, initially targeting Apple Silicon arm64. The linked Chinese guide records actual build and validation status.

Transcription turns speech into text. Timing places characters and words on the timeline. Review lets you compare different readings of the same line. Choose a combination for your media and hardware, then enable AI sentence segmentation as needed.

| Role | What it does | Options |
| --- | --- | --- |
| Main transcription | Produces text; models with speaker identification can also help organize speaker tracks | MOSS, SenseVoice, Whisper |
| Character and word timing | Locates boundaries for subtitle splits that fit the video | FireRedASR2-AED, Paraformer; standalone aligners for existing text |
| Text review | Compares another transcription to resolve unclear or disputed words | Qwen3-ASR and other local or online options |

![Speaker A's two lines and speaker B's reply appear on their respective subtitle tracks](docs/assets/readme/speaker-tracks.gif)

*A → B → A: transcribed line by line, arranged by speaker.*

## Split at word boundaries and shape the rhythm

Choose cut points in a long sentence and use the razor to split it. The timeline immediately shows the resulting subtitle segments. Undo or merge a split to keep refining the pacing.

![Selecting cut points in a long sentence, splitting it into three segments, and undoing each cut](docs/assets/readme/word-split.gif)

## Compare alternatives, then apply your choice

“人物” (person), “任务” (mission), or “战术” (tactics)? Compare the wording and source for the same subtitle, then apply a candidate to update the current line.

![Comparing candidates and applying the mission reading to update the current subtitle](docs/assets/readme/candidate-review.gif)

## Game glossaries: organize once, use again

Keep character names, aliases, and common recognition errors organized by game. Check reference terms and their sources, then confirm them for use in recognition. Your glossary is ready for the next recording.

![Game categories, term sources, confirmation status, and batch glossary tools](docs/assets/readme/glossary.png)

## Stream highlights and animated subtitles

**Find the moments worth cutting.** Use stream chat XML and subtitles to find candidates such as a low-health comeback, a funny failure, or a burst of chat activity. Select a clip on the left to update its explanation and timeline selection on the right, then add it to your edit.

![Switching between highlight candidates, checking their explanations and timeline selections, and adding a clip to the edit](docs/assets/readme/live-clips.gif)

**Give each line its own expression.** Fonts, materials, entrances, and exits come together in a subtitle design. Reuse an existing style, or configure an AI design service to create and revise one. Subtitle design and highlight selection can be used independently.

![Woodcut and CRT scoreboard subtitle designs entering, holding, and exiting](docs/assets/readme/caption-effects.gif)

*Woodcut: wooden panels close, engraved lettering appears, and the panels fold away. CRT scoreboard: power on, glowing text, and a screen-off exit.*

## Download and quick start

For **Windows x64**. This repository provides a limited source-only scope. **No public installer is available yet**; internal test candidates are not public downloads. This scope is not the complete Corresponding Source for an existing Setup, and a complete build from this tree has not been verified. See [source scope and build requirements](SOURCE_ONLY_SCOPE.md).

1. **Prepare the source.** Read the [scope and build requirements](SOURCE_ONLY_SCOPE.md), then prepare authorized external dependencies in a separate development environment. The following steps describe product use after dependencies are ready.
2. **Prepare recognition.** Set up local models in Model Workshop, or configure your online service.
3. **Import and transcribe.** Choose your media, content settings, and glossary, then check the text, word timing, and speaker results.
4. **Open Subtitle Studio.** Proofread, split or merge lines, adjust subtitles and video, then export subtitles, a transcript, or a video with subtitles burned in.

The default theme is **Deep Grape**. Choose another color scheme in Appearance settings.

### Requirements

- **System:** Windows 10 22H2 (19045) or later, x64.
- **Local recognition:** Download model weights as needed in Model Workshop. SenseVoice supports CPU processing; options such as MOSS use NVIDIA CUDA. Check each model's requirements in the workshop.
- **Online services:** Use your own account or API key. Billing follows your provider's terms.
- **Output:** SRT, ASS, TXT, JSON, separate speaker tracks, and MP4, MKV, or MOV video.

[Installation and first use](docs/product-guide.en.md#installation-and-setup) · [Models, formats, and advanced use](docs/product-guide.en.md) · [Source scope and build requirements](SOURCE_ONLY_SCOPE.md)

## Documentation and feedback

[Interface and feature tour](docs/product-demo.en.md) · [Run and build from source](docs/product-guide.en.md#run-and-build-from-source) · [Architecture](ARCHITECTURE.md) · [Report an issue](https://github.com/NOTBAD314/2ByteASR/issues)

Include your version, model, steps to reproduce, and screenshots when reporting an issue.

Project-owned code is licensed under **GPL-3.0-only** ([English license](LICENSE), [scope](PROJECT_LICENSE.md)). Official versions are free; GPL permits commercial use, modification and paid distribution subject to its source and other conditions. Private changes need not be published. Ordinary subtitle, video and image outputs do not become GPL merely through use of this software. See [Third-party notices](THIRD_PARTY_NOTICES.md) and the version-specific [source delivery instructions](SOURCE_DELIVERY.md).
