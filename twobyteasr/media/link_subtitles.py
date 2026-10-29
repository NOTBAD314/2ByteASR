"""Loss-aware JSON3 / WebVTT / SRT import; immutable raw bytes live elsewhere.

Start anchors describe display/segment starts, NOT measured phoneme ends.
Deduplication requires identical temporal anchors or an active rolling window.
"""
from __future__ import annotations
import html
import json
import re
from dataclasses import asdict, dataclass, field

# 3 (2026-10-26): captions are tidied (link_tidy) — labels dropped, automatic rows re-broken.
PARSER_VERSION = "3"
MAX_BYTES = 32 * 1024 * 1024
STAMP = r"(?:\d{1,3}:)?\d{2}:\d{2}[.,]\d{3}"
TAG = re.compile(r"<[^>]*>")
INLINE = re.compile(r"<(" + STAMP + r")>")


@dataclass
class Caption:
    start_ms: int
    end_ms: int
    text: str
    events: list[str] = field(default_factory=list)
    anchors: list[dict] = field(default_factory=list)
    precision: str = "sentence"
    end_basis: str = "source_display_end"
    display_end_ms: int | None = None


@dataclass
class ParsedSubtitles:
    format: str
    captions: list[Caption]
    warnings: list[str] = field(default_factory=list)
    input_events: int = 0
    display_repeats: int = 0
    parser_version: str = PARSER_VERSION
    tidy: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def _ms(value) -> int:
    value = float(value)
    if not 0 <= value < 2**53:
        raise ValueError("字幕时间无效。")
    return round(value)


def time_ms(value: str) -> int:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        parts.insert(0, "0")
    h, m, s = map(float, parts)
    if m >= 60 or s >= 60:
        raise ValueError("字幕时间码无效。")
    return _ms((h * 3600 + m * 60 + s) * 1000)


def clean_text(value: str) -> str:
    return html.unescape(TAG.sub("", value)).replace("\u200b", "")


def _finish(start, end, chunks, refs) -> Caption | None:
    text = "".join(c["text"] for c in chunks)
    left = len(text) - len(text.lstrip())
    text = text.strip()
    if not text or end <= start:
        return None
    anchors, offset = [], 0
    for chunk in chunks:
        lo, hi = max(0, offset-left), min(len(text), offset+len(chunk["text"])-left)
        offset += len(chunk["text"])
        anchor = chunk.get("start_ms")
        if anchor is not None and hi > lo and start <= anchor < end:
            row = dict(text=text[lo:hi], char_start=lo, char_end=hi, start_ms=anchor,
                       event_ref=chunk["ref"], precision="segment_start")
            if chunk.get("end_ms") is not None and anchor < chunk["end_ms"] <= end:
                row.update(end_ms=chunk["end_ms"], precision="segment_interval")
            anchors.append(row)
    return Caption(start, end, text, list(dict.fromkeys(refs)), anchors,
                   "segment_start" if anchors else "sentence")


def _json3(text: str) -> ParsedSubtitles:
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError("JSON3 缺少 events 数组。")
    result = ParsedSubtitles("json3", [], input_events=len(data["events"]))
    windows, seen, rolling = {}, {}, set()
    for index, event in enumerate(data["events"]):
        if not isinstance(event, dict) or not isinstance(event.get("segs"), list):
            continue
        refs, chunks = [], []
        if event.get("tStartMs") is None:
            if any(str(s.get("utf8", "")).strip() for s in event["segs"] if isinstance(s, dict)):
                result.warnings.append(f"event:{index}: 缺少开始时间，原稿保留。")
            continue
        start = _ms(event["tStartMs"])
        duration = event.get("dDurationMs")
        window = windows.get(event.get("wWinId"))
        if event.get("aAppend") and all(
                isinstance(seg, dict) and not str(seg.get("utf8") or "").strip() for seg in event["segs"]):
            # Actual YouTube JSON3 sample: aAppend + newline is a row-roll
            # control; its duration is retained screen time, not another utterance.
            if window:
                window.events.append(f"event:{index}/roll-control")
                rolling.add(event.get("wWinId"))
            continue
        if duration is None:
            end = window.end_ms if event.get("aAppend") and window and window.end_ms > start else start
        else:
            end = start + _ms(duration)
        for seg_index, seg in enumerate(event["segs"]):
            if not isinstance(seg, dict):
                continue
            value = clean_text(str(seg.get("utf8") or ""))
            if not value:
                continue
            ref = f"event:{index}/seg:{seg_index}"
            anchor = (start + _ms(seg["tOffsetMs"]) if "tOffsetMs" in seg else
                      start if seg_index == 0 and any(isinstance(s, dict) and "tOffsetMs" in s for s in event["segs"]) else None)
            identity = (event.get("wWinId"), anchor, value)
            if anchor is not None and "wWinId" in event and identity in seen and seen[identity].end_ms > start:
                seen[identity].events.append(ref)
                result.display_repeats += 1
                continue
            chunk = dict(text=value, start_ms=anchor, ref=ref)
            if anchor is not None and "dDurationMs" in seg:
                chunk["end_ms"] = anchor + _ms(seg["dDurationMs"])
            chunks.append(chunk)
            refs.append(ref)
        caption = _finish(start, end, chunks, refs)
        if caption is None:
            if any(c["text"].strip() for c in chunks):
                result.warnings.append(f"event:{index}: 缺少有效结束时间，原稿保留。")
            continue
        if event.get("aAppend") and window and window.end_ms >= start:
            shift = len(window.text) + (0 if window.text.endswith(" ") or caption.text.startswith(" ") else 1)
            window.text += (" " if shift > len(window.text) else "") + caption.text
            window.end_ms = max(window.end_ms, caption.end_ms)
            window.events.extend(caption.events)
            window.anchors.extend(dict(a, char_start=a["char_start"]+shift, char_end=a["char_end"]+shift)
                                  for a in caption.anchors)
            if window.anchors:
                window.precision = "segment_start"
            caption = window
        else:
            if (window and event.get("wWinId") in rolling and window.start_ms < start < window.end_ms
                    and all(a["start_ms"] < start for a in window.anchors)):
                window.display_end_ms = window.end_ms
                window.end_ms = start
                window.end_basis = "next_row_start_after_roll_control"
                result.display_repeats += 1
            result.captions.append(caption)
        rolling.discard(event.get("wWinId"))
        if "wWinId" in event:
            windows[event["wWinId"]] = caption
        for chunk in chunks:
            if chunk.get("start_ms") is not None:
                seen[(event.get("wWinId"), chunk["start_ms"], chunk["text"])] = caption
    return result


def _text_subtitles(text: str, fmt: str, *, rollup=False) -> ParsedSubtitles:
    result = ParsedSubtitles(fmt, [])
    previous_lines, previous_end = [], -1
    for index, block in enumerate(re.split(r"\n[ \t]*\n", text)):
        lines = block.strip().splitlines()
        if not lines or (fmt == "vtt" and lines[0].startswith(("NOTE", "STYLE", "REGION", "WEBVTT"))):
            continue
        timing_index = next((n for n, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        match = re.match(r"^(" + STAMP + r")\s+-->\s+(" + STAMP + r")(?:\s.*)?$", lines[timing_index])
        if not match:
            raise ValueError(f"字幕块 {index+1} 的时间码无效。")
        start, end = map(time_ms, match.groups())
        body = lines[timing_index+1:]
        if end <= start:
            raise ValueError(f"字幕块 {index+1} 的时间范围无效。")
        result.input_events += 1
        displayed = [clean_text(line).strip() for line in body]
        # Retained whole first line, still visible, followed by a new timed line.
        # Never fuzzy/global dedup or dedup of single-line repeated speech.
        if (rollup and fmt == "vtt" and len(body) > 1 and start < previous_end
                and displayed[0] and displayed[0] in previous_lines
                and not INLINE.search(body[0]) and any(INLINE.search(line) for line in body[1:])):
            if result.captions:
                result.captions[-1].events.append(f"block:{index}/retained-line:0")
            body = body[1:]
            result.display_repeats += 1
        chunks = []
        for line_index, line in enumerate(body):
            if line_index:
                chunks.append(dict(text="\n", start_ms=None, ref=f"block:{index}"))
            parts = INLINE.split(line)
            anchor = start if len(parts) > 1 else None
            for n in range(0, len(parts), 2):
                if n:
                    anchor = time_ms(parts[n-1])
                value = clean_text(parts[n])
                if value:
                    chunks.append(dict(text=value, start_ms=anchor, ref=f"block:{index}/line:{line_index}/part:{n//2}"))
        caption = _finish(start, end, chunks, [c["ref"] for c in chunks])
        if caption:
            if result.captions and (start, end, caption.text) == (
                    result.captions[-1].start_ms, result.captions[-1].end_ms, result.captions[-1].text):
                result.captions[-1].events.extend(caption.events)
                result.display_repeats += 1
            else:
                result.captions.append(caption)
        previous_lines, previous_end = displayed, end
    return result


def parse_subtitles(raw: bytes, *, expected_format: str = "", source: str = "unknown") -> ParsedSubtitles:
    if len(raw) > MAX_BYTES:
        raise ValueError("字幕文件超过 32 MiB；请先按范围整理。")
    try:
        text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").strip()
    except UnicodeError:
        raise ValueError("字幕必须是 UTF-8 编码（可含 BOM）。") from None
    actual = "json3" if text.startswith("{") else "vtt" if text.startswith("WEBVTT") else "srt"
    result = _json3(text) if actual == "json3" else _text_subtitles(
        text, actual, rollup=source == "automatic" or "scroll:up" in text[:2048])
    if not result.captions:
        raise ValueError("字幕没有可用的文本与时间；原始文件已保留。")
    if expected_format and expected_format != actual:
        result.warnings.append(f"内容为 {actual}，来源声称 {expected_format}；按实际内容处理。")
    result.captions.sort(key=lambda c: c.start_ms)
    return result


def _vtt_stamp(value: int) -> str:
    seconds, ms = divmod(int(value), 1000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{ms:03}"


def words_vtt_bytes(parsed: ParsedSubtitles) -> bytes:
    """WebVTT with each word's start inline (YouTube's own automatic-caption
    form), so players can show the words as they are spoken (2026-10-26)."""
    blocks = ["WEBVTT", ""]
    for caption in parsed.captions:
        anchors = sorted(caption.anchors, key=lambda a: a["char_start"])
        if anchors:
            first = anchors[0]
            parts = [caption.text[:first["char_end"]]]
            cursor = first["char_end"]
            for anchor in anchors[1:]:
                parts.append(f"<{_vtt_stamp(anchor['start_ms'])}><c>{caption.text[cursor:anchor['char_end']]}</c>")
                cursor = anchor["char_end"]
            parts.append(caption.text[cursor:])
            text = "".join(parts)
        else:
            text = caption.text
        blocks += [f"{_vtt_stamp(caption.start_ms)} --> {_vtt_stamp(caption.end_ms)}", text, ""]
    return "\n".join(blocks).encode("utf-8")


def srt_bytes(parsed: ParsedSubtitles) -> bytes:
    def stamp(value):
        seconds, ms = divmod(value, 1000)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"
    text = "\n\n".join(f"{i}\n{stamp(c.start_ms)} --> {stamp(c.end_ms)}\n{c.text}"
                       for i, c in enumerate(parsed.captions, 1)) + "\n"
    return text.encode("utf-8")
