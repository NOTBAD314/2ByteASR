"""Integrity envelope for autosaves, without changing the project schema."""
import hashlib
import json

GRAPH_FIELDS = ("media_pool", "video_tracks", "audio_tracks", "av_track_groups")


def graph_counts(payload):
    counts = {}
    for field in GRAPH_FIELDS:
        items = payload.get(field, [])
        if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
            raise ValueError(f"invalid media graph: {field}")
        counts[field] = len(items)
        if field in {"video_tracks", "audio_tracks"}:
            clips = {}
            for track in items:
                entries = track.get("clips", [])
                if not isinstance(entries, list) or any(not isinstance(x, dict) for x in entries):
                    raise ValueError(f"invalid clips: {track.get('id')}")
                clips[track["id"]] = len(entries)
            counts[field + "_clips"] = clips
    return counts


def graph_integrity(payload):
    encoded = json.dumps({key: payload.get(key, []) for key in GRAPH_FIELDS},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {"counts": graph_counts(payload), "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}


def validate_autosave_integrity(payload):
    expected = (payload.get("autosave") or {}).get("media_graph_integrity")
    if expected is not None and expected != graph_integrity(payload):
        raise ValueError("恢复快照的媒体轨道/片段校验失败；保留原工程，不自动修复此快照。")
    return expected
