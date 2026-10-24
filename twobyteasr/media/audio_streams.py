"""Audio streams of one media file: identity, labels and the default choice.

2026-10-24 (multi-track import): ffprobe reports each stream's *absolute*
index (video, audio, subtitle and data streams all counted), while FFmpeg
addresses audio by its *relative* ordinal (``0:a:N``, audio streams only).
Subtitle or data streams may sit between two audio streams, so both numbers
are stored side by side and never derived from each other.

One record is one audio stream. A stereo or 5.1 stream is one source track;
its channels are described, never split into separate tracks.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Handler names muxers write when the user gave the track no name.
_GENERIC_HANDLERS = {
    "", "soundhandler", "soundhandle", "sound media handler", "sound handler",
    "audiohandler", "audio handler", "core media audio", "gpac isomedia handler",
    "isomedia file produced by google", "applehandler", "mp4 sound handler",
}

# ISO 639-2 (and common 639-1) codes; anything else is shown as written.
_LANGUAGE_NAMES = {
    "chi": "中文", "zho": "中文", "zh": "中文", "cmn": "中文", "yue": "粤语",
    "jpn": "日语", "ja": "日语", "eng": "英语", "en": "英语",
    "kor": "韩语", "ko": "韩语", "fre": "法语", "fra": "法语", "fr": "法语",
    "ger": "德语", "deu": "德语", "de": "德语", "spa": "西班牙语", "es": "西班牙语",
    "rus": "俄语", "ru": "俄语", "por": "葡萄牙语", "pt": "葡萄牙语",
    "ita": "意大利语", "it": "意大利语", "tha": "泰语", "vie": "越南语",
}
_UNDEFINED_LANGUAGES = {"", "und", "unk", "mis", "mul", "zxx", "qaa"}


def _seconds_ms(value: object) -> float:
    try:
        return float(value) * 1000.0
    except (TypeError, ValueError):
        return 0.0


def _tag_duration_ms(text: object) -> int:
    """Matroska writes the stream length as a DURATION tag (HH:MM:SS.nnnnnnnnn)."""
    try:
        hours, minutes, seconds = str(text or "").strip().split(":")
        return max(0, round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000))
    except (TypeError, ValueError):
        return 0


def _stream_length_ms(stream: Mapping[str, Any]) -> int:
    direct = _seconds_ms(stream.get("duration"))
    if direct > 0:
        return round(direct)
    try:
        numerator, denominator = str(stream.get("time_base") or "").split("/", 1)
        seconds = float(stream.get("duration_ts") or 0) * float(numerator) / max(float(denominator), 1.0)
        if seconds > 0:
            return round(seconds * 1000)
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    tags = stream.get("tags") if isinstance(stream.get("tags"), Mapping) else {}
    for key, value in tags.items():
        if str(key).upper() == "DURATION":
            return _tag_duration_ms(value)
    return 0


def _title(tags: Mapping[str, Any]) -> str:
    lowered = {str(k).lower(): str(v or "").strip() for k, v in tags.items()}
    for key in ("title", "name"):
        if lowered.get(key):
            return lowered[key]
    handler = lowered.get("handler_name", "")
    return handler if handler.casefold() not in _GENERIC_HANDLERS else ""


def probe_audio_streams(streams: Iterable[Mapping[str, Any]], container_start_ms: float = 0.0) -> tuple[dict, ...]:
    """One record per ffprobe audio stream, in file order.

    ``start_ms`` is the stream start relative to the container start (what a
    late-starting dub track needs on the timeline); ``duration_ms`` is 0 when
    the file does not say, never a reason to hide the stream.
    """
    records = []
    for stream in streams or ():
        if not isinstance(stream, Mapping) or stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags") if isinstance(stream.get("tags"), Mapping) else {}
        disposition = stream.get("disposition") if isinstance(stream.get("disposition"), Mapping) else {}
        codec = str(stream.get("codec_name") or "").strip()
        start = stream.get("start_time")
        start_ms = _seconds_ms(start) - float(container_start_ms or 0.0) if start not in (None, "", "N/A") else 0.0
        language = str(next((v for k, v in tags.items() if str(k).lower() == "language"), "") or "").strip()
        problem = "" if codec and codec != "none" else "FFmpeg 不认识这条音轨的编码，无法解码"
        records.append({
            "ordinal": len(records),
            "index": int(stream.get("index") or 0),
            "codec": codec,
            "channels": max(0, int(stream.get("channels") or 0)),
            "channel_layout": str(stream.get("channel_layout") or ""),
            "sample_rate": max(0, int(stream.get("sample_rate") or 0)),
            "language": language,
            "title": _title(tags),
            "default": bool(int(disposition.get("default") or 0)),
            "start_ms": round(start_ms, 3),
            "duration_ms": _stream_length_ms(stream),
            "decodable": not problem,
            "problem": problem,
        })
    return tuple(records)


def normalize_streams(value: object) -> list[dict]:
    """Saved stream records in ordinal order; malformed rows are dropped."""
    rows = []
    for raw in value if isinstance(value, (list, tuple)) else ():
        if not isinstance(raw, Mapping):
            continue
        try:
            ordinal = int(raw.get("ordinal"))
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            continue
        if ordinal < 0 or index < 0:
            continue
        rows.append({**dict(raw), "ordinal": ordinal, "index": index,
                     "decodable": bool(raw.get("decodable", True))})
    rows.sort(key=lambda row: row["ordinal"])
    return rows


def asset_streams(asset) -> list[dict]:
    """Probed audio streams of a MediaAsset; [] when not probed yet."""
    metadata = getattr(asset, "audio_metadata", None) or {}
    return normalize_streams(metadata.get("streams")) if isinstance(metadata, Mapping) else []


def primary_ordinal(streams: Iterable[Mapping[str, Any]]) -> int:
    """The track a fresh import plays: the file's default stream, else the first."""
    rows = [row for row in streams or () if isinstance(row, Mapping)]
    marked = [row for row in rows if row.get("default") and row.get("decodable", True)]
    if len(marked) >= 1:
        return int(marked[0]["ordinal"])
    first = next((row for row in rows if row.get("decodable", True)), None)
    return int(first["ordinal"]) if first else 0


def stream_by_ordinal(asset, ordinal: int) -> dict | None:
    return next((row for row in asset_streams(asset) if row["ordinal"] == int(ordinal)), None)


def language_name(code: str) -> str:
    """Display name, or '' when the file does not mark a language."""
    key = str(code or "").strip().lower()
    if key in _UNDEFINED_LANGUAGES:
        return ""
    return _LANGUAGE_NAMES.get(key, key)


def channel_text(channels: int, layout: str = ""):
    from ..i18n import tr
    count = int(channels or 0)
    if count == 1:
        return tr("单声道")
    if count == 2:
        return tr("立体声")
    if count > 2:
        name = str(layout or "").split("(")[0].strip()
        return tr("{layout} 多声道", layout=name) if name and name[0].isdigit() else tr("{count} 声道", count=count)
    return tr("声道未知")


def stream_label(record: Mapping[str, Any], *, with_channels: bool = True):
    """'音轨 2｜中文配音｜中文｜立体声' — nothing guessed when the file is silent."""
    from ..i18n import join_text, tr
    parts = [tr("音轨 {number}", number=int(record.get("ordinal", 0)) + 1)]
    title = str(record.get("title") or "").strip()
    if title:
        parts.append(title)
    language = language_name(str(record.get("language") or ""))
    parts.append(tr(language) if language in _LANGUAGE_NAMES.values() else (language or tr("语言未标示")))
    if with_channels:
        parts.append(channel_text(int(record.get("channels") or 0), str(record.get("channel_layout") or "")))
    return join_text(parts, "｜")


def stream_caption(record: Mapping[str, Any]):
    """Short lane caption: '音轨 2｜中文配音', or the language without a title."""
    from ..i18n import join_text, tr
    title = str(record.get("title") or "").strip()
    if not title:
        language = language_name(str(record.get("language") or ""))
        title = tr(language) if language in _LANGUAGE_NAMES.values() else (language or tr("语言未标示"))
    return join_text([tr("音轨 {number}", number=int(record.get("ordinal", 0)) + 1), title], "｜")


def stream_details(record: Mapping[str, Any]):
    """Codec, length, default flag and the technical indexes (tooltips, logs)."""
    from ..i18n import tr
    lines = []
    codec = str(record.get("codec") or "").strip()
    rate = int(record.get("sample_rate") or 0)
    lines.append(tr("编码：{codec}", codec=codec.upper() if codec else "?") if not rate
                 else tr("编码：{codec} · {rate} Hz", codec=codec.upper() if codec else "?", rate=rate))
    duration = int(record.get("duration_ms") or 0)
    if duration > 0:
        minutes, rest = divmod(duration // 1000, 60)
        lines.append(tr("时长：{minutes}:{seconds:02d}", minutes=minutes, seconds=rest))
    else:
        lines.append(tr("时长：文件未标明"))
    start = float(record.get("start_ms") or 0.0)
    if start >= 1.0:
        lines.append(tr("在 {seconds:.2f} 秒处开始", seconds=start / 1000.0))
    if record.get("default"):
        lines.append(tr("文件标示的默认音轨"))
    lines.append(tr("技术索引：音频 {ordinal} · 串流 {index}", ordinal=int(record.get("ordinal", 0)),
                    index=int(record.get("index", 0))))
    if not record.get("decodable", True):
        lines.append(tr(str(record.get("problem") or "无法解码")))
    return lines


__all__ = [
    "asset_streams", "channel_text", "language_name", "normalize_streams", "primary_ordinal",
    "probe_audio_streams", "stream_by_ordinal", "stream_caption", "stream_details", "stream_label",
]
