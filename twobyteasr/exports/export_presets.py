"""Product and user-owned export presets. Stored outside .2byteproj."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .studio_render import encoder_choices, hardware_encoders_for


PRODUCT_PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "recommended",
        "label": "推荐",
        "container": "mp4",
        "codec": "h264",
        "encoder": "auto",
        "quality_mode": "cq",
        "quality": 20,
        "preset_speed": "balanced",
        "resolution": (0, 0),
        "fps": 0.0,
        "audio_codec": "copy",
        "requires": "h264",
    },
    {
        "id": "fast",
        "label": "快速导出",
        "container": "mp4",
        "codec": "h264",
        "encoder": "auto",
        "quality_mode": "cq",
        "quality": 23,
        "preset_speed": "fast",
        "resolution": (0, 0),
        "fps": 0.0,
        "audio_codec": "copy",
        "requires": "h264",
    },
    {
        "id": "high",
        "label": "高质量",
        "container": "mp4",
        "codec": "h264",
        "encoder": "auto",
        "quality_mode": "cq",
        "quality": 16,
        "preset_speed": "quality",
        "resolution": (0, 0),
        "fps": 0.0,
        "audio_codec": "copy",
        "requires": "h264",
    },
    {
        "id": "small",
        "label": "小体积",
        "container": "mp4",
        "codec": "hevc",
        "encoder": "auto",
        "quality_mode": "cq",
        "quality": 24,
        "preset_speed": "balanced",
        "resolution": (0, 0),
        "fps": 0.0,
        "audio_codec": "copy",
        "requires": "hevc-hw",
    },
    {
        "id": "av1",
        "label": "AV1 高压缩",
        "container": "mp4",
        "codec": "av1",
        "encoder": "auto",
        "quality_mode": "cq",
        "quality": 28,
        "preset_speed": "balanced",
        "resolution": (0, 0),
        "fps": 0.0,
        "audio_codec": "copy",
        "requires": "av1-hw",
    },
    {
        "id": "custom",
        "label": "自定义",
        "container": "mp4",
        "codec": "h264",
        "encoder": "auto",
        "quality_mode": "cq",
        "quality": 20,
        "preset_speed": "balanced",
        "resolution": (0, 0),
        "fps": 0.0,
        "audio_codec": "copy",
        "requires": "",
    },
)


def _user_preset_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return root / "2ByteASR" / "SubtitleStudio" / "export-presets.json"


def load_user_presets() -> list[dict[str, Any]]:
    try:
        payload = json.loads(_user_preset_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []
    items = payload.get("presets") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict) and item.get("id")]


def save_user_presets(presets: list[dict[str, Any]]) -> None:
    target = _user_preset_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"presets": presets}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)


def preset_available(preset: dict[str, Any], ffmpeg_path: str) -> bool:
    requires = str(preset.get("requires") or "")
    if requires == "hevc-hw":
        return bool(hardware_encoders_for("hevc", ffmpeg_path))
    if requires == "av1-hw":
        return bool(hardware_encoders_for("av1", ffmpeg_path))
    if requires in {"h264", "hevc", "av1"}:
        return bool(encoder_choices(ffmpeg_path, requires))
    return True


def visible_product_presets(ffmpeg_path: str) -> list[dict[str, Any]]:
    return [dict(item) for item in PRODUCT_PRESETS if preset_available(item, ffmpeg_path)]
