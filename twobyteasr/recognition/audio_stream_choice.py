"""Which audio stream a home-page recognition of a multi-track file hears.

2026-10-24 (user): the home page recognizes whole files without a timeline.
A multi-track MP4/MKV used to be decoded with FFmpeg's own stream pick
(``-vn``: usually the stream with the most channels) for the shared 16 kHz
audio and with ``0:a:0`` for the incremental chunks, so nobody could choose a
track and the two readers could even hear different ones. Now the home page
asks first (the Studio track picker) and every picked stream is one queue
entry:

* the entry's choice rides on the runtime context (``audio_stream``);
* the media identity carries it as ``selection``, so every stage cache of the
  entry lives apart from the other tracks of the same file;
* the two readers of the original file (shared audio, incremental chunks) map
  ``0:a:N`` and put the stream on the first audio stream's clock, the clock
  the result project's time mapping uses: a dub that starts 3 s late is
  heard 3 s late.

Without a choice nothing changes: same commands, same cache keys.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = 1


def _same_file(left: object, right: object) -> bool:
    try:
        return Path(str(left)).resolve() == Path(str(right)).resolve()
    except (OSError, ValueError):
        return False


def _start(record: Mapping[str, Any] | None) -> float:
    # A negative start is encoder priming, not a later track: the decoders
    # already drop it, exactly as before this choice existed.
    try:
        return max(0.0, float((record or {}).get("start_ms") or 0.0))
    except (TypeError, ValueError):
        return 0.0


def make_choice(media_path: str, streams: Iterable[Mapping[str, Any]], ordinal: int) -> dict:
    """The runtime record of one picked stream (``streams``: probe records)."""
    rows = [dict(row) for row in streams or ()]
    record = next((row for row in rows if int(row.get("ordinal", -1)) == int(ordinal)), None)
    if record is None:
        raise ValueError(f"素材里没有第 {int(ordinal) + 1} 条音轨：{Path(media_path).name}")
    if not record.get("decodable", True):
        raise ValueError(str(record.get("problem") or "这条音轨无法解码"))
    first = next((row for row in rows if int(row.get("ordinal", -1)) == 0), record)
    return {
        "version": VERSION,
        "media_path": str(Path(media_path).resolve()),
        "ordinal": int(ordinal),
        "stream_index": int(record.get("index", -1)),
        # Where the stream starts on the first stream's clock, and where that
        # clock starts in the container (both ms, never negative).
        "offset_ms": round(_start(record) - _start(first), 3),
        "lead_ms": round(_start(first), 3),
        "record": record,
    }


def active_choice(media_path: object, context: Any = None) -> dict:
    """The current entry's choice when it belongs to ``media_path``, else {}."""
    if context is None:
        from .run_context import get_runtime_context
        context = get_runtime_context()
    choice = getattr(context, "audio_stream", None) or {}
    if not choice or not _same_file(choice.get("media_path"), media_path):
        return {}
    return dict(choice)


def selection(choice: Mapping[str, Any] | None) -> dict:
    """What a media identity adds for a picked stream ({} without one)."""
    if not choice:
        return {}
    return {"audio_stream": int(choice["ordinal"]), "audio_stream_index": int(choice["stream_index"])}


def ffmpeg_map(choice: Mapping[str, Any] | None) -> list[str]:
    return ["-map", f"0:a:{int(choice['ordinal'])}"] if choice else []


def align_samples(audio, choice: Mapping[str, Any] | None, sample_rate: int):
    """Put a decoded stream on the first stream's clock: pad or trim its start."""
    import numpy as np
    if not choice:
        return audio
    shift = round(float(choice.get("offset_ms") or 0.0) * int(sample_rate) / 1000.0)
    if shift > 0:
        return np.concatenate([np.zeros(shift, dtype=audio.dtype), audio])
    if shift < 0:
        return np.array(audio[-shift:], copy=True)
    return audio


def chunk_window(choice: Mapping[str, Any] | None, start_ms: int) -> tuple[float, float]:
    """(input seek in seconds, leading silence in ms) of a chunk at ``start_ms``.

    Chunk time ``t`` is shared-audio time: the first stream's start plus
    ``t``. The seek lands there; a stream that starts later fills the gap
    before its first sample with silence.
    """
    if not choice:
        return start_ms / 1000.0, 0.0
    lead = float(choice.get("lead_ms") or 0.0)
    offset = float(choice.get("offset_ms") or 0.0)
    return (lead + start_ms) / 1000.0, max(0.0, offset - start_ms)


def parse_request(text: str) -> dict[str, list[dict]]:
    """``RunOptions.audio_streams_json`` → {resolved media path: [{ordinal, stream_index}]}."""
    if not text:
        return {}
    payload = json.loads(text)
    media = payload.get("media") if isinstance(payload, Mapping) else None
    result: dict[str, list[dict]] = {}
    for path, picks in (media or {}).items():
        rows = []
        for pick in picks or ():
            if isinstance(pick, Mapping) and int(pick.get("ordinal", -1)) >= 0:
                rows.append({"ordinal": int(pick["ordinal"]), "stream_index": int(pick.get("stream_index", -1))})
        if rows:
            result[str(Path(path).resolve())] = rows
    return result


def request_json(picks: Mapping[str, Iterable[Mapping[str, Any]]], bases: Mapping[str, str] | None = None) -> str:
    """The home page's picks as ``RunOptions.audio_streams_json`` ('' for none).

    ``bases``: per file, the earlier combined result a retry of failed tracks
    adds to, so the tracks that already finished keep their captions.
    """
    media = {str(Path(path).resolve()): [{"ordinal": int(row["ordinal"]), "stream_index": int(row.get("stream_index", -1))}
                                         for row in rows]
             for path, rows in picks.items() if rows}
    if not media:
        return ""
    payload = {"version": VERSION, "media": media}
    kept = {str(Path(path).resolve()): str(project) for path, project in (bases or {}).items()
            if project and str(Path(path).resolve()) in media}
    if kept:
        payload["base_projects"] = kept
    return json.dumps(payload, ensure_ascii=False)


def base_projects(text: str) -> dict[str, str]:
    """Per resolved media path, the earlier result a retry adds its tracks to."""
    if not text:
        return {}
    payload = json.loads(text)
    rows = payload.get("base_projects") if isinstance(payload, Mapping) else None
    return {str(Path(path).resolve()): str(project) for path, project in (rows or {}).items() if project}


def expand_queue(paths: Iterable[str], request: Mapping[str, list[dict]], probe) -> tuple[list[str], list[dict]]:
    """One queue entry per picked stream (``probe(path)`` → stream records).

    A file without picks stays one entry with no choice. A picked stream that
    is no longer the stream the user saw (the file changed) is refused.
    """
    entries: list[str] = []
    choices: list[dict] = []
    for path in paths:
        picks = request.get(str(Path(path).resolve())) or []
        if not picks:
            entries.append(path)
            choices.append({})
            continue
        streams = list(probe(path) or ())
        for pick in picks:
            choice = make_choice(path, streams, pick["ordinal"])
            if pick.get("stream_index", -1) >= 0 and choice["stream_index"] != pick["stream_index"]:
                raise RuntimeError(f"选择音轨后素材已改变：{Path(path).name}")
            entries.append(path)
            choices.append(choice)
    return entries, choices


def choice_label(choice: Mapping[str, Any] | None) -> str:
    """'音轨 2｜中文配音' (plain text) for logs, progress and result notes."""
    if not choice:
        return ""
    from ..media.audio_streams import stream_label
    return str(stream_label(choice.get("record") or {"ordinal": choice.get("ordinal", 0)}, with_channels=False))


__all__ = [
    "active_choice", "align_samples", "base_projects", "choice_label", "chunk_window", "expand_queue",
    "ffmpeg_map", "make_choice", "parse_request", "request_json", "selection",
]
