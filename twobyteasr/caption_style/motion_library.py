"""System and user-owned Motion Library presets for Subtitle Studio."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .effect_dsl import builtin_effects, validate_effect
from ..projects.studio_project import studio_data_root


@dataclass(frozen=True)
class MotionPreset:
    id: str
    name: str
    motion: dict[str, Any]
    preview_effect_id: str = "soft_fade"
    native_effect_id: str = ""
    system: bool = True
    favorite: bool = False
    description: str = ""
    category: str = ""
    created_at: str = ""

    def validate(self) -> "MotionPreset":
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", str(self.id or "")):
            raise ValueError("motion preset id invalid")
        if not str(self.name or "").strip():
            raise ValueError("motion preset name required")
        if not isinstance(self.motion, Mapping):
            raise ValueError("motion preset payload must be an object")
        json.dumps(self.motion, ensure_ascii=False)
        if 'nativeEffect' in self.motion:
            if not isinstance(self.motion['nativeEffect'], Mapping):
                raise ValueError('native motion must be an object')
            validate_effect(self.motion['nativeEffect'])
        if self.preview_effect_id not in builtin_effects():
            raise ValueError("motion preview effect is unknown")
        if self.native_effect_id:
            if self.native_effect_id not in builtin_effects():
                raise ValueError('native motion is unknown')
            validate_effect(builtin_effects()[self.native_effect_id])
        return self

    def describe(self) -> str:
        """Human label for the card's second line."""
        if self.description:
            return self.description
        entrance = self.motion.get("entrance", {}) if isinstance(self.motion, Mapping) else {}
        return MOTION_TYPE_LABELS.get(str(entrance.get("type") or ""), str(entrance.get("type") or "动效"))


# Short, card-friendly labels for known entrance types.
MOTION_TYPE_LABELS = {
    "none": "无动效",
    "fade": "淡入",
    "soft_fade": "柔和淡入",
    "pop": "弹出",
    "soft_pop": "柔和弹出",
    "scale": "缩放",
    "punch": "冲击",
    "bounce": "弹跳",
    "bounce_lite": "轻弹跳",
    "float_up": "上浮",
    "slide": "滑动",
    "slide_soft": "柔和滑入",
    "zoom": "变焦",
    "shake": "抖动",
    "typewriter": "打字机",
    "glitch_reveal": "故障揭示",
    "digital_scan": "数字扫描",
    "chromatic_split": "色差分裂",
    "gaming_impact": "游戏冲击",
    "blur_reveal": "模糊显现",
    "emphasis": "强调",
}


def _motion(entry: str, *, duration: int = 220, hold: Mapping[str, Any] | None = None,
            exit_type: str = "soft_fade", **parameters: Any) -> dict[str, Any]:
    return {
        "entrance": {"type": entry, "duration_ms": duration, **parameters},
        "hold": dict(hold or {}),
        "exit": {"type": exit_type, "duration_ms": 150},
    }


SYSTEM_MOTIONS = {
    preset.id: preset
    for preset in (
        MotionPreset("glitch_reveal", "Glitch Reveal", _motion(
            "glitch_reveal", duration=240, hold={"micro_glitch_interval_ms": 1800},
            glitch_intensity=0.9, slice_count=5, chromatic_offset=6,
        ), "punch"),
        MotionPreset("digital_scan", "Digital Scan", _motion(
            "digital_scan", duration=260, hold={"scanline": True, "scan_speed": 1.7},
        ), "soft_fade"),
        MotionPreset("chromatic_split", "Chromatic Split", _motion(
            "chromatic_split", duration=210, chromatic_offset=6,
        ), "punch"),
        MotionPreset("gaming_impact", "Gaming Impact", _motion(
            "gaming_impact", duration=180, scale_keyframes=[0.70, 1.18, 0.96, 1.0],
        ), "punch", "punch"),
        MotionPreset("bounce", "Bounce", _motion("bounce", duration=280), "bounce_lite", "bounce_lite"),
        MotionPreset("punch", "Punch", _motion("punch", duration=180), "punch", "punch"),
        MotionPreset("soft_fade", "Soft Fade", _motion("soft_fade", duration=180), "soft_fade", "soft_fade"),
        MotionPreset("float", "Float", _motion("float_up", duration=240), "float_up", "float_up"),
        MotionPreset("typewriter", "Typewriter", _motion("typewriter", duration=520), "soft_fade"),
        MotionPreset("slide", "Slide", _motion("slide_soft", duration=240), "slide_soft", "slide_soft"),
        MotionPreset("zoom", "Zoom", _motion("zoom", duration=200), "soft_pop", "soft_pop"),
        MotionPreset("shake", "Shake", _motion("shake", duration=260, hold={"amplitude": 4}), "punch"),
    )
}

# The main library offers effects with an honest native preview and export.
# Historical authored presets remain available under the legacy filter.
for _id, _label, _description in (
    ('none', '无入退场', '直接显示，适合对白'),
    ('soft_fade', '柔和淡入', '自然进入，轻微淡出'),
    ('bounce', '轻盈回弹', '短促弹入，适合提示'),
    ('punch', '重点强调', '放大回落，适合高能瞬间'),
    ('float', '轻微上浮', '向上进入，适合旁白'),
    ('slide', '侧边滑入', '从左滑入'),
    ('word_reveal', '逐词出现', '按语音时间逐字／词显示'),
    ('karaoke_highlight', '卡拉 OK', '已读的字词依次点亮'),
    ('word_current', '当前词高亮', '只突出正在说的字词'),
):
    _native = {'bounce': 'bounce_lite', 'float': 'float_up', 'slide': 'slide_soft'}.get(_id, _id)
    SYSTEM_MOTIONS[_id] = MotionPreset(_id, _label, _motion(_native), _native, _native,
                                      description=_description, category='常用')


from .letter_motion import PRESETS as LETTER_PRESETS
for _id, (_label, _description, _color) in LETTER_PRESETS.items():
    SYSTEM_MOTIONS[_id] = MotionPreset(_id, _label, _motion(_id), _id, _id,
        description=_description, category='精选字效')


class MotionPresetStore:
    def __init__(self, base: str | os.PathLike[str] | None = None) -> None:
        self.path = studio_data_root(base) / "motion-presets.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"schema_version": 1, "favorites": [], "presets": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def load_user(self) -> dict[str, MotionPreset]:
        payload = self._load()
        result: dict[str, MotionPreset] = {}
        for item in payload.get("presets", []):
            if not isinstance(item, Mapping) or str(item.get("id") or "") in SYSTEM_MOTIONS:
                continue
            try:
                preset = MotionPreset(
                    id=str(item.get("id") or ""), name=str(item.get("name") or ""),
                    motion=copy.deepcopy(dict(item.get("motion") or {})),
                    preview_effect_id=str(item.get("preview_effect_id") or "soft_fade"),
                    native_effect_id=str(item.get("native_effect_id") or ""),
                    system=False,
                    favorite=str(item.get("id") or "") in set(payload.get("favorites", [])),
                    description=str(item.get("description") or ""),
                    category=str(item.get("category") or ""),
                    created_at=str(item.get("created_at") or ""),
                ).validate()
            except (TypeError, ValueError):
                continue
            result[preset.id] = preset
        return result

    def all(self) -> dict[str, MotionPreset]:
        favorites = set(self._load().get("favorites", []))
        system = {
            key: MotionPreset(**{**asdict(value), "favorite": key in favorites})
            for key, value in SYSTEM_MOTIONS.items()
        }
        return {**system, **self.load_user()}

    def _write(self, presets: Mapping[str, MotionPreset], favorites: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".motion-presets.", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump({
                    "schema_version": 1,
                    "favorites": sorted(favorites),
                    "presets": [
                        {key: value for key, value in asdict(preset).items() if key not in {"system", "favorite"}}
                        for preset in presets.values() if not preset.system
                    ],
                }, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                pass

    def upsert(self, preset: MotionPreset) -> None:
        preset.validate()
        if preset.id in SYSTEM_MOTIONS or preset.system:
            raise ValueError("system motion presets are read-only")
        current = self.load_user()
        current[preset.id] = preset
        favorites = set(self._load().get("favorites", []))
        if preset.favorite:
            favorites.add(preset.id)
        self._write(current, favorites)

    def delete(self, preset_id: str) -> None:
        if preset_id in SYSTEM_MOTIONS:
            raise ValueError("system motion presets cannot be deleted")
        current = self.load_user()
        current.pop(str(preset_id), None)
        favorites = set(self._load().get("favorites", []))
        favorites.discard(str(preset_id))
        self._write(current, favorites)

    def set_favorite(self, preset_id: str, favorite: bool) -> None:
        if preset_id not in self.all():
            raise KeyError(preset_id)
        current = self.load_user()
        favorites = set(self._load().get("favorites", []))
        favorites.add(preset_id) if favorite else favorites.discard(preset_id)
        self._write(current, favorites)

    def rename(self, preset_id: str, name: str, description: str = "") -> None:
        """Rename a custom motion; built-ins are immutable."""
        if preset_id in SYSTEM_MOTIONS:
            raise ValueError("system motion presets cannot be renamed")
        current = self.load_user()
        preset = current.get(str(preset_id))
        if preset is None:
            raise KeyError(preset_id)
        current[str(preset_id)] = MotionPreset(
            **{
                **asdict(preset),
                "name": str(name or preset.name),
                "description": description if description is not None else preset.description,
            }
        ).validate()
        favorites = set(self._load().get("favorites", []))
        self._write(current, favorites)
