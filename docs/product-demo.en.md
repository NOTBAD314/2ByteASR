# 2ByteASR: a tour of the interface

Except for the last section, "Illustrations", everything below is the **real 0.7.1 interface**, captured on 2026-10-14 from the source of tag `v0.7.1`, running in an isolated test folder that never touched anyone's data. The sample is a self-made test card with two synthetic Chinese voices, transcribed locally with MOSS + FireRedASR2-AED + Qwen3-ASR (NVIDIA RTX 5070 Ti). Captions without "Chinese interface" show the English interface; the subtitles are Chinese because the speech is. How the assets were made is described in the [asset notes](assets/readme/README.md) (Chinese).

[Back to the README](../README.md) · [User guide](product-guide.en.md) · [中文](product-demo.zh-CN.md) · [日本語](product-demo.ja.md) · [한국어](product-demo.ko.md)

## Home and recognition

![Home screen in English: drop zone, recent project, the Primary transcription, Subtitle timeline and Text review cards, AI smart segmentation, Content & terms and the Start subtitles button](assets/readme/home-en.png)

Home: drop in media, check the recognition plan, and click "Start subtitles".

![Progress page (Chinese interface): local recognition at step 6, Qwen reviewing the text, with each step's time and result on the left and the full run log on the right](assets/readme/progress.png)

Progress (Chinese interface): the current step, each step's time and result, and the full run log.

![Completion page (Chinese interface): 14 subtitles, 2:03, one item to check, entry points to export subtitles, open Subtitle Studio or return, and a subtitle preview](assets/readme/completion.png)

Completion (Chinese interface): subtitle count, time taken, items to check and a preview. A finished run does not mean every line is confirmed; items to check can be reviewed in the Studio.

## Subtitle Studio

![Subtitle Studio in English: Captions List, video preview, Tools Panel, and a timeline with Host and Teammate subtitle tracks, a video track and the audio waveform](assets/readme/studio-en.png)

The captions list, video preview, style panel and a timeline with one track per speaker share one window.

![Timeline close-up (Chinese interface): one subtitle track each for the host and the teammate, then the video track and the audio waveform](assets/readme/tracks.png)

Speaker tracks (Chinese interface): each speaker's lines sit on their own track, which can be hidden or locked; drag a line to another track to give it to that speaker.

![Speaker Management in English: subtitle counts and total duration for Host and Teammate; name, colour and default style; merge speakers, assign selected subtitles, set as streamer, keep only this speaker's subtitles](assets/readme/speakers-en.png)

Speaker Management: rename, set colours and default styles, merge speakers split by mistake; every bulk action can be undone at once.

## Recorded in the app

![Razor and merge: preview the merged length, then split along the per-character timing blocks; a cut inside a character keeps it in the first part](assets/readme/razor-en.webp)

Merge two lines into one, then split it again between characters with the razor.

![Review mode: MOSS and FireRed wrote 他, Qwen wrote 它; choosing Qwen's reading makes it current](assets/readme/review-en.webp)

Review mode: readings of the same line side by side, with the differing character and its source model highlighted; one click applies one.

## Term library and Model workshop

![Term library in English: libraries per game, Add term, AI Web Update, Smart term building, Bulk import and the term table](assets/readme/glossary-en.png)

Term library: correct spellings, aliases and common misrecognitions per game, with source and confirmation status. Some labels are still Chinese in the 0.7.1 English interface.

![Model workshop in English: models listed by role with size, how they run and the reference index](assets/readme/workshop-en.png)

Model workshop: choose models by role and see their size, how they run and the reference index (a relative guide, not an accuracy figure).

## Export

![Render complete page (Chinese interface): H.264, 1920×1080, 30 fps, 00:34, 1.0 MB, with the local output path covered](assets/readme/export.png)

Render complete (Chinese interface). The local output path in the screenshot is covered.

## Five interface themes

![Subtitle Studio in the five themes (Chinese interface): Deep Grape, Warm Cream, Warm Night, Lavender, Slate](assets/readme/themes.png)

Deep Grape (default), Warm Cream, Warm Night, Lavender and Slate (Chinese interface).

## Illustrations (not recordings of the app)

### Highlight candidates

![Illustrative animation: a chat activity curve marks highlight moments, and a candidate is added to the edit](assets/readme/clips-en.webp)

**This is an illustrative animation made on 2026-10-09**: the interface was simplified and redrawn from the software at the time, and the chat, candidate titles and reasons are sample data, not analysis results. The real feature is the Clip Assistant in the Studio; see the [user guide](product-guide.en.md#everyday-studio-actions).

### AI Subtitle Design examples

![Two sample works made with AI Subtitle Design: woodcut lettering and a CRT scoreboard, each entering, holding and exiting](assets/readme/caption-effects.gif)

The woodcut and CRT scoreboard effects are **sample works** made with AI Subtitle Design (an asset from 2026-09-30), not built-in presets. AI Subtitle Design needs an AI service you configure; the ordinary font, outline and entrance/exit presets need no AI.

[Back to the README](../README.md) · [User guide](product-guide.en.md)
