"""Default and display choices for a parsed video (no Qt).

The full link window and the Studio quick card offer the same defaults:
the first <=1080p H.264 picture, the audio the picture needs, and one
original-language subtitle (manual before automatic). Labels are Chinese
source text; callers pass them through ``tr``.
"""
from __future__ import annotations

import re

from .link_catalog import language_matches, preferred_track, media_url

MODES = (("both", "视频＋字幕"), ("video", "仅视频"), ("audio", "仅音频"), ("subtitles", "仅字幕"))
MODE_NOTES = {"both": "推荐，字幕直接可编辑", "video": "之后自己识别",
              "audio": "体积小，适合识别", "subtitles": "对应已有素材"}
SOURCE_SHORT = {"manual": "人工", "automatic": "自动", "translated": "自动翻译", "unknown": "来源待确认"}

# Common YouTube language codes; anything else shows the track's own name.
LANGUAGE_NAMES = {
    "zh": "中文", "zh-hans": "中文（简体）", "zh-cn": "中文（简体）", "zh-sg": "中文（简体）",
    "zh-hant": "中文（繁体）", "zh-tw": "中文（繁体）", "zh-hk": "中文（香港）",
    "en": "英语", "ja": "日语", "ko": "韩语", "de": "德语", "fr": "法语", "es": "西班牙语",
    "pt": "葡萄牙语", "ru": "俄语", "it": "意大利语", "ar": "阿拉伯语", "hi": "印地语",
    "id": "印尼语", "th": "泰语", "vi": "越南语", "tr": "土耳其语", "nl": "荷兰语", "pl": "波兰语",
    "uk": "乌克兰语", "ms": "马来语",
}
CODEC_NAMES = (("avc", "H.264"), ("h264", "H.264"), ("hev", "H.265"), ("hvc", "H.265"), ("vp09", "VP9"),
               ("vp9", "VP9"), ("av01", "AV1"), ("mp4a", "AAC"), ("aac", "AAC"), ("opus", "Opus"),
               ("vorbis", "Vorbis"), ("mp3", "MP3"))


def find_video_link(text: str) -> str:
    """The first HTTP(S) video candidate in pasted text, normalized; "" if none.

    Only the start of the clipboard is read: a huge paste must not stall the
    key press that triggered the check."""
    for token in re.split(r"[\s【】（）<>\"]+", str(text or "")[:4096].strip())[:40]:
        token = token.strip("<>\"'()[]（）【】「」,，。")
        if not token.lower().startswith(("http://", "https://")):
            if not token.lower().startswith(("youtu.be/", "youtube.com/", "www.youtube.com/", "m.youtube.com/",
                    "bilibili.com/", "www.bilibili.com/", "m.bilibili.com/", "b23.tv/")):
                continue
            token = "https://" + token
        try:
            return media_url(token)
        except ValueError:
            continue
    return ""


def codec_name(codec) -> str:
    text = str(codec or "")
    lowered = text.lower()
    return next((name for prefix, name in CODEC_NAMES if lowered.startswith(prefix)), text or "?")


def size_bytes(fmt: dict):
    return fmt.get("filesize") or fmt.get("filesize_approx") or 0


def size_text(value, unknown: str = "大小未知") -> str:
    return f"{float(value)/1024/1024:.1f} MiB" if value else unknown


def language_name(code: str, fallback: str = "") -> str:
    key = str(code or "").lower()
    return LANGUAGE_NAMES.get(key) or LANGUAGE_NAMES.get(key.split("-")[0]) or fallback or str(code or "")


def has_audio(fmt: dict) -> bool:
    return fmt.get("acodec") not in (None, "none")


def video_formats(catalog: dict) -> list[dict]:
    videos = [f for f in catalog["formats"] if f.get("vcodec") not in (None, "none")]
    # Separate picture streams before the old combined ones at the same size.
    videos.sort(key=lambda f: (-(f.get("height") or 0), -(f.get("fps") or 0), has_audio(f), str(f.get("vcodec"))))
    return videos


def audio_formats(catalog: dict) -> list[dict]:
    audios = [f for f in catalog["formats"] if f.get("vcodec") in (None, "none") and has_audio(f)]
    # "-drc" copies have their dynamic range compressed: keep them last.
    audios.sort(key=lambda f: (str(f.get("format_id", "")).endswith("-drc"),
                               -(f.get("language_preference") or 0), -(f.get("abr") or 0)))
    return audios


def preferred_audio(audios: list[dict], video: dict | None = None) -> dict:
    """Audio in the picture's own container family (MP4 + M4A, WebM + WebM),
    so the merge stays a plain copy; M4A when there is no picture."""
    if not audios:
        return {}
    wanted = {"mp4": "m4a", "webm": "webm"}.get(str((video or {}).get("ext", "")), "m4a")
    return next((a for a in audios if a.get("ext") == wanted), audios[0])


def preferred_video_index(videos: list[dict]) -> int:
    return next((i for i, f in enumerate(videos)
                 if (f.get("height") or 0) <= 1080 and str(f.get("vcodec")).startswith("avc")), 0)


def fps_text(value) -> str:
    try:
        return f"{float(value):g}" if value else "?"
    except (TypeError, ValueError):
        return "?"


def video_label(fmt: dict, unknown: str = "大小未知") -> str:
    if not fmt.get("height") and not fmt.get("fps") and fmt.get("vcodec") == "unknown":
        return f"{str(fmt.get('ext') or 'HTTP').upper()} · {size_text(size_bytes(fmt), unknown)}"
    return (f"{fmt.get('height') or '?'}p · {fps_text(fmt.get('fps'))} fps · {codec_name(fmt.get('vcodec'))}"
            f" · {size_text(size_bytes(fmt), unknown)}")


def audio_label(fmt: dict, unknown_language: str = "语言未知", unknown_size: str = "大小未知") -> str:
    parts = [language_name(fmt.get("language") or "") or unknown_language, codec_name(fmt.get("acodec"))]
    if fmt.get("abr"):
        parts.append(f"{round(float(fmt['abr']))} kbps")
    elif fmt.get("format_note"):
        parts.append(str(fmt["format_note"]))
    parts.append(size_text(size_bytes(fmt), unknown_size))
    return " · ".join(parts)


def track_label(track: dict) -> str:
    name = language_name(track.get("language", ""), track.get("label", ""))
    return f"{name} · {SOURCE_SHORT.get(track.get('source'), '来源待确认')}"


def chip_tracks(catalog: dict, preferences=(), limit: int = 4) -> list[dict]:
    """The few tracks worth a one-click chip: the default first, then manual
    tracks, the original automatic track, then translations people asked for."""
    tracks = catalog["tracks"]
    preferred = preferred_track(catalog, preferences)
    wanted = [t for t in tracks if t["track_id"] == preferred]
    wanted += [t for t in tracks if t["source"] == "manual"]
    wanted += [t for t in tracks if t["source"] == "automatic"]
    for language in preferences:
        wanted += [t for t in tracks if t["source"] == "translated" and language_matches(t["language"], language)]
    seen, chosen = set(), []
    for track in wanted:
        if track["track_id"] not in seen:
            seen.add(track["track_id"])
            chosen.append(track)
    return chosen[:limit]


def default_selection(catalog: dict, preferences=(), mode: str = "both") -> dict:
    """What the quick card downloads when the user just presses Enter."""
    videos, audios = video_formats(catalog), audio_formats(catalog)
    video = videos[preferred_video_index(videos)] if videos else {}
    track = preferred_track(catalog, preferences) if mode in ("both", "subtitles") else ""
    if mode == "audio":
        audio = preferred_audio(audios).get("format_id", "")
    elif video and not has_audio(video):
        audio = preferred_audio(audios, video).get("format_id", "")
    else:
        audio = ""
    return dict(mode=mode, video_format=video.get("format_id", "") if mode in ("both", "video") else "",
                audio_format=audio if mode != "subtitles" else "",
                track_ids=[track] if track else [], primary_track_id=track, translation_track_id="")


def available_modes(catalog: dict) -> set[str]:
    modes = set()
    if video_formats(catalog):
        modes |= {"both", "video"}
    if audio_formats(catalog):
        modes.add("audio")
    if catalog["tracks"]:
        modes.add("subtitles")
    return modes


def quality_summary(catalog: dict) -> str:
    videos = video_formats(catalog)
    if not videos or not videos[0].get("height"):
        return ""
    top = videos[0]
    return f"{top.get('height') or '?'}p" + (f" · {fps_text(top['fps'])} fps" if top.get("fps") else "")


def upload_date_text(value: str) -> str:
    text = str(value or "")
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) == 8 and text.isdigit() else ""


def duration_text(seconds) -> str:
    if not seconds:
        return "—"
    total = int(round(float(seconds or 0)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
