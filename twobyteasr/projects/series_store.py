"""Formal Series / Creator World-Model store with lossless migration,
end-of-episode delta settlement, 3-adoption trust graduation, and local
ECAPA cross-episode voiceprint matching (2026-11-25).

Qt-free. Persists under ``<user_data_root>/series/``:
  - ``index.json``: catalog, active selection, migration receipt
  - ``<series_id>.json``: unified series record (recognition, glossaries,
    cast roster, break_rules, visual style, export preset, graduated rules,
    provenance)
  - ``<series_id>/voiceprints.json``: local normalized ECAPA centroids only
    (no raw audio stored, user-deletable per speaker or per series)

Backward compatibility:
  - ``.2byteproj`` schema_version 1 stays untouched; projects record only an
    additive ``studio_state['series_binding']`` dict.
  - Existing ``profiles.json`` and ``bunny/memory.json`` (``kind == 'recipe'``)
    are imported non-destructively once and left intact on disk.
"""
from __future__ import annotations

import copy
import json
import math
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1
VOICEPRINT_EMBEDDING_VERSION = "ecapa-window-v4"
VOICEPRINT_MAX_HISTORY = 5
# Calibrated from twobyteasr/recognition/scoped_voiceprint.py (6 real projects)
VP_AUTOMATIC = {"whole": 0.65, "lowest": 0.60, "seconds": 6.0, "margin": 0.08}
VP_REVIEW = {"whole": 0.45, "lowest": 0.40, "seconds": 4.0}
VP_MIN_SELF = 0.45
TRUST_GRADUATION_HITS = 3

DEFAULT_PIPELINE: dict[str, Any] = {
    "enabled": False,
    "run_glossary": True,
    "auto_apply_graduated": True,
    "run_speakers": True,
    "run_style_preset": True,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def series_root(base: str | os.PathLike[str] | None = None) -> Path:
    if base is not None:
        return Path(base) / "series"
    from ..runtime_paths import user_data_root
    return Path(user_data_root()) / "series"


def _unique_strings(values: Iterable[object]) -> list[str]:
    return list(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))


def _unit_vector(vec: Sequence[float]) -> list[float]:
    arr = [float(x) for x in vec]
    if not arr or not all(math.isfinite(x) for x in arr):
        return []
    norm = math.sqrt(sum(x * x for x in arr))
    if norm <= 1e-9:
        return []
    return [x / norm for x in arr]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or len(a) != len(b):
        return -1.0
    return max(-1.0, min(1.0, sum(float(x) * float(y) for x, y in zip(a, b))))


@dataclass
class CastMember:
    cast_id: str
    name: str
    color: str = ""
    role: str = ""
    name_style: dict[str, Any] = field(default_factory=dict)
    episodes_seen: int = 1
    has_voiceprint: bool = False
    updated_at: str = field(default_factory=_utc_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CastMember":
        return cls(
            cast_id=str(data.get("cast_id") or uuid.uuid4().hex[:10]),
            name=str(data.get("name") or "").strip(),
            color=str(data.get("color") or "").strip(),
            role=str(data.get("role") or "").strip(),
            name_style=copy.deepcopy(data.get("name_style") or {}),
            episodes_seen=max(1, int(data.get("episodes_seen", 1) or 1)),
            has_voiceprint=bool(data.get("has_voiceprint", False)),
            updated_at=str(data.get("updated_at") or _utc_now()),
        )


@dataclass
class RuleTrustRecord:
    """Tracks clean adoptions of one deterministic rule for Tier-2 graduation."""
    rule_key: str               # e.g. "alias:元神->原神" or "local_fix:short"
    label: str
    clean_streak: int = 0
    episode_ids: list[str] = field(default_factory=list)
    graduated: bool = False
    declined: bool = False
    updated_at: str = field(default_factory=_utc_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuleTrustRecord":
        return cls(
            rule_key=str(data.get("rule_key") or "").strip(),
            label=str(data.get("label") or "").strip(),
            clean_streak=max(0, int(data.get("clean_streak", 0) or 0)),
            episode_ids=_unique_strings(data.get("episode_ids") or ()),
            graduated=bool(data.get("graduated", False)),
            declined=bool(data.get("declined", False)),
            updated_at=str(data.get("updated_at") or _utc_now()),
        )


@dataclass
class SeriesRecord:
    id: str
    name: str
    language: str = "zh"
    recognition: dict[str, Any] = field(default_factory=dict)
    glossary_ids: list[str] = field(default_factory=list)
    cast: list[CastMember] = field(default_factory=list)
    break_rules: dict[str, str] = field(default_factory=dict)   # lang -> rule text
    visual: dict[str, Any] = field(default_factory=dict)        # style preset / theme / overrides
    export: dict[str, Any] = field(default_factory=dict)        # codec, cq, lufs, format
    pipeline: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_PIPELINE))
    trust_ledger: dict[str, RuleTrustRecord] = field(default_factory=dict)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    source_profile_id: str = ""
    episode_count: int = 0
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    last_used_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "language": self.language,
            "recognition": copy.deepcopy(self.recognition),
            "glossary_ids": list(self.glossary_ids),
            "cast": [asdict(m) for m in self.cast],
            "break_rules": dict(self.break_rules),
            "visual": copy.deepcopy(self.visual),
            "export": copy.deepcopy(self.export),
            "pipeline": copy.deepcopy(self.pipeline),
            "trust_ledger": {k: asdict(v) for k, v in self.trust_ledger.items()},
            "provenance": copy.deepcopy(self.provenance[-40:]),
            "source_profile_id": self.source_profile_id,
            "episode_count": int(self.episode_count),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_used_at": self.last_used_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SeriesRecord":
        cast_rows = [CastMember.from_dict(r) for r in (data.get("cast") or ()) if isinstance(r, dict) and r.get("name")]
        raw_ledger = data.get("trust_ledger") if isinstance(data.get("trust_ledger"), dict) else {}
        ledger = {
            str(k): RuleTrustRecord.from_dict(v)
            for k, v in raw_ledger.items()
            if isinstance(v, dict) and str(k).strip()
        }
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:12]),
            name=str(data.get("name") or "未命名系列").strip(),
            language=str(data.get("language") or "zh").strip(),
            recognition=copy.deepcopy(data.get("recognition") or {}),
            glossary_ids=_unique_strings(data.get("glossary_ids") or ()),
            cast=cast_rows,
            break_rules={str(k): str(v) for k, v in (data.get("break_rules") or {}).items() if str(v).strip()},
            visual=copy.deepcopy(data.get("visual") or {}),
            export=copy.deepcopy(data.get("export") or {}),
            pipeline={**copy.deepcopy(DEFAULT_PIPELINE), **(data.get("pipeline") if isinstance(data.get("pipeline"), dict) else {})},
            trust_ledger=ledger,
            provenance=[copy.deepcopy(p) for p in (data.get("provenance") or ()) if isinstance(p, dict)][-40:],
            source_profile_id=str(data.get("source_profile_id") or ""),
            episode_count=max(0, int(data.get("episode_count", 0) or 0)),
            created_at=str(data.get("created_at") or _utc_now()),
            updated_at=str(data.get("updated_at") or _utc_now()),
            last_used_at=str(data.get("last_used_at") or ""),
        )


@dataclass
class VoiceprintObservation:
    """One anonymous speaker label's clean two-half ECAPA embedding from a single episode."""
    label: str
    whole: list[float]
    half_a: list[float]
    half_b: list[float]
    seconds: float
    embedding_version: str = VOICEPRINT_EMBEDDING_VERSION

    @property
    def self_consistency(self) -> float:
        return _cosine(self.half_a, self.half_b)


@dataclass
class VoiceprintMatch:
    label: str
    tier: str                    # "automatic" | "review" | "new" | "unavailable"
    cast_id: str = ""
    cast_name: str = ""
    whole_score: float = 0.0
    lowest_score: float = 0.0
    margin: float = 0.0
    candidates: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""


class SeriesStore:
    """Atomic file-backed Series Store with lossless migration & voiceprint bank."""

    def __init__(self, root: str | os.PathLike[str] | None = None):
        self.root = Path(root) if root is not None else series_root()

    @property
    def index_path(self) -> Path:
        return self.root / "index.json"

    def _series_path(self, series_id: str) -> Path:
        safe = "".join(ch for ch in str(series_id) if ch.isalnum() or ch in ("-", "_"))
        if not safe:
            raise ValueError("invalid series_id")
        return self.root / f"{safe}.json"

    def _voiceprint_path(self, series_id: str) -> Path:
        safe = "".join(ch for ch in str(series_id) if ch.isalnum() or ch in ("-", "_"))
        if not safe:
            raise ValueError("invalid series_id")
        return self.root / safe / "voiceprints.json"

    def _load_index(self) -> dict[str, Any]:
        raw = _read_json(self.index_path)
        return {
            "schema_version": SCHEMA_VERSION,
            "series_ids": _unique_strings(raw.get("series_ids") or ()),
            "last_selected_id": str(raw.get("last_selected_id") or ""),
            "migrated_from": copy.deepcopy(raw.get("migrated_from") or {}),
        }

    def _save_index(self, payload: dict[str, Any]) -> None:
        payload["schema_version"] = SCHEMA_VERSION
        _atomic_write_json(self.index_path, payload)

    def list(self) -> list[SeriesRecord]:
        idx = self._load_index()
        rows: list[SeriesRecord] = []
        for sid in idx["series_ids"]:
            rec = self.get(sid)
            if rec is not None:
                rows.append(rec)
        return rows

    def get(self, series_id: str) -> SeriesRecord | None:
        if not str(series_id or "").strip():
            return None
        try:
            path = self._series_path(series_id)
        except ValueError:
            return None
        if not path.is_file():
            return None
        data = _read_json(path)
        if not data:
            return None
        return SeriesRecord.from_dict(data)

    def find_by_name(self, name: str) -> SeriesRecord | None:
        needle = " ".join(str(name or "").split()).casefold()
        if not needle:
            return None
        return next((s for s in self.list() if s.name.casefold() == needle), None)

    def last_selected_id(self) -> str:
        return self._load_index()["last_selected_id"]

    def set_last_selected(self, series_id: str) -> None:
        idx = self._load_index()
        idx["last_selected_id"] = str(series_id or "")
        self._save_index(idx)

    def save(self, record: SeriesRecord) -> SeriesRecord:
        record.name = " ".join(str(record.name or "未命名系列").split())[:40] or "未命名系列"
        record.updated_at = _utc_now()
        _atomic_write_json(self._series_path(record.id), record.to_dict())
        idx = self._load_index()
        if record.id not in idx["series_ids"]:
            idx["series_ids"].append(record.id)
        self._save_index(idx)
        return record

    def create(self, name: str, **kwargs: Any) -> SeriesRecord:
        clean = " ".join(str(name or "").split())[:40]
        if not clean:
            raise ValueError("系列名称不能为空")
        if self.find_by_name(clean) is not None:
            raise ValueError(f"已存在同名系列：{clean}")
        rec = SeriesRecord(id=f"ser_{uuid.uuid4().hex[:10]}", name=clean, **kwargs)
        self.save(rec)
        self.set_last_selected(rec.id)
        return rec

    def delete(self, series_id: str) -> bool:
        idx = self._load_index()
        if series_id not in idx["series_ids"]:
            return False
        idx["series_ids"] = [s for s in idx["series_ids"] if s != series_id]
        if idx["last_selected_id"] == series_id:
            idx["last_selected_id"] = ""
        self._save_index(idx)
        for p in (self._series_path(series_id), self._voiceprint_path(series_id)):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        return True

    # ------------------------------------------------------------------ lossless migration
    def migrate_legacy_sources(
        self,
        *,
        profiles_path: str | os.PathLike[str] | None = None,
        bunny_memory_path: str | os.PathLike[str] | None = None,
    ) -> dict[str, int]:
        """One-time lossless import of profiles.json & bunny/memory.json recipes.

        Leaves both source files untouched on disk; idempotent on repeated calls.
        """
        idx = self._load_index()
        migrated = dict(idx.get("migrated_from") or {})
        imported_profiles = 0
        imported_recipes = 0

        if not migrated.get("profiles_done"):
            p_path = Path(profiles_path) if profiles_path is not None else self.root.parent / "profiles.json"
            raw = _read_json(p_path)
            for item in raw.get("profiles") or ():
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                existing = self.find_by_name(str(item["name"]))
                if existing is not None:
                    continue
                rec = SeriesRecord(
                    id=f"ser_{uuid.uuid4().hex[:10]}",
                    name=str(item["name"]),
                    language=str(item.get("language") or "zh"),
                    recognition={
                        "recognition_plan": item.get("recognition_plan", "custom"),
                        "primary_asr": item.get("primary_asr", ""),
                        "timestamp_model": item.get("timestamp_model", ""),
                        "evidence_model": item.get("evidence_model", ""),
                        "asr_config": copy.deepcopy(item.get("asr_config") or {}),
                        "llm_config": copy.deepcopy(item.get("llm_config") or {}),
                        "subtitle_mode": item.get("subtitle_mode", "monolingual"),
                    },
                    glossary_ids=_unique_strings(item.get("glossary_ids") or ()),
                    visual={"subtitle_style_preset": str(item.get("subtitle_style_preset") or "default")},
                    export={
                        "render_preset": str(item.get("render_preset") or "default"),
                        "export_format": str(item.get("export_format") or "srt"),
                    },
                    source_profile_id=str(item.get("id") or ""),
                    episode_count=max(0, int(item.get("use_count", 0) or 0)),
                    last_used_at=str(item.get("last_used_at") or ""),
                    provenance=[{"at": _utc_now(), "kind": "migrated_profile", "source_id": str(item.get("id") or "")}],
                )
                self.save(rec)
                imported_profiles += 1
            migrated["profiles_done"] = True
            migrated["profiles_count"] = imported_profiles

        if not migrated.get("bunny_recipes_done"):
            b_path = Path(bunny_memory_path) if bunny_memory_path is not None else self.root.parent / "bunny" / "memory.json"
            raw = _read_json(b_path)
            for row in raw.get("entries") or ():
                if not isinstance(row, dict) or row.get("kind") != "recipe":
                    continue
                name = str(row.get("text") or "").strip()
                data = row.get("data") if isinstance(row.get("data"), dict) else {}
                if not name:
                    continue
                target = self.find_by_name(name)
                if target is None:
                    target = SeriesRecord(id=f"ser_{uuid.uuid4().hex[:10]}", name=name)
                if data.get("style"):
                    target.visual["style_overrides"] = copy.deepcopy(data["style"])
                if data.get("break_rule"):
                    lang = str(data.get("language") or target.language or "zh")
                    target.break_rules[lang] = str(data["break_rule"])
                existing_names = {c.name.casefold() for c in target.cast}
                for sp_name in data.get("speakers") or ():
                    sp_clean = str(sp_name or "").strip()
                    if sp_clean and sp_clean.casefold() not in existing_names:
                        target.cast.append(CastMember(cast_id=f"cast_{uuid.uuid4().hex[:8]}", name=sp_clean))
                        existing_names.add(sp_clean.casefold())
                target.provenance.append({"at": _utc_now(), "kind": "migrated_bunny_recipe", "name": name})
                self.save(target)
                imported_recipes += 1
            migrated["bunny_recipes_done"] = True
            migrated["bunny_recipes_count"] = imported_recipes

        idx = self._load_index()
        idx["migrated_from"] = migrated
        self._save_index(idx)
        return {"profiles": imported_profiles, "recipes": imported_recipes}

    # ------------------------------------------------------------------ local ECAPA voiceprint bank
    def load_voiceprints(self, series_id: str) -> dict[str, dict[str, Any]]:
        data = _read_json(self._voiceprint_path(series_id))
        entries = data.get("cast_vectors")
        return entries if isinstance(entries, dict) else {}

    def enroll_voiceprint(
        self,
        series_id: str,
        cast_id: str,
        observation: VoiceprintObservation,
        *,
        episode_id: str = "",
    ) -> dict[str, Any]:
        """Enroll or EMA-update one cast member's local ECAPA centroid.

        Refuses noisy/mixed/short observations (<4.0s or self-consistency <0.45).
        """
        whole = _unit_vector(observation.whole)
        half_a = _unit_vector(observation.half_a)
        half_b = _unit_vector(observation.half_b)
        if not whole or not half_a or not half_b:
            raise ValueError("声音样本无效")
        if observation.seconds < VP_REVIEW["seconds"]:
            raise ValueError(f"干净语音时长不足 {VP_REVIEW['seconds']:.0f} 秒，暂时记不住这段声音")
        self_sim = _cosine(half_a, half_b)
        if self_sim < VP_MIN_SELF:
            raise ValueError("这段语音里声音不太一致，可能混入了多人声音，暂时不记住")

        rec = self.get(series_id)
        if rec is None:
            raise ValueError("常用方案不存在")
        member = next((m for m in rec.cast if m.cast_id == cast_id), None)
        if member is None:
            raise ValueError("方案里还没有这位说话人")

        bank = self.load_voiceprints(series_id)
        existing = bank.get(cast_id) if isinstance(bank.get(cast_id), dict) else None
        history: list[dict[str, Any]] = []
        if existing and existing.get("embedding_version") == observation.embedding_version:
            history = list(existing.get("history") or ())

        history.append({
            "episode_id": str(episode_id or ""),
            "whole": whole,
            "half_a": half_a,
            "half_b": half_b,
            "seconds": round(float(observation.seconds), 2),
            "self_consistency": round(self_sim, 4),
            "recorded_at": _utc_now(),
        })
        history = history[-VOICEPRINT_MAX_HISTORY:]

        # Weighted centroid across recent episodes (capped to prevent drift)
        dim = len(whole)
        accum = [0.0] * dim
        for idx_h, item in enumerate(history):
            weight = 1.0 + 0.15 * idx_h
            for i, val in enumerate(item["whole"]):
                accum[i] += val * weight
        centroid = _unit_vector(accum)
        entry = {
            "cast_id": cast_id,
            "name": member.name,
            "embedding_version": observation.embedding_version,
            "centroid": centroid,
            "history": history,
            "updated_at": _utc_now(),
        }
        bank[cast_id] = entry
        _atomic_write_json(self._voiceprint_path(series_id), {
            "schema_version": SCHEMA_VERSION,
            "embedding_version": observation.embedding_version,
            "cast_vectors": bank,
        })
        member.has_voiceprint = True
        member.updated_at = _utc_now()
        self.save(rec)
        return entry

    def clear_voiceprint(self, series_id: str, cast_id: str | None = None) -> None:
        """Delete one member's voiceprint or all voiceprints for the series."""
        rec = self.get(series_id)
        if cast_id is None:
            vp_path = self._voiceprint_path(series_id)
            if vp_path.exists():
                vp_path.unlink()
            if rec is not None:
                for m in rec.cast:
                    m.has_voiceprint = False
                self.save(rec)
            return
        bank = self.load_voiceprints(series_id)
        if cast_id in bank:
            del bank[cast_id]
            _atomic_write_json(self._voiceprint_path(series_id), {
                "schema_version": SCHEMA_VERSION,
                "embedding_version": VOICEPRINT_EMBEDDING_VERSION,
                "cast_vectors": bank,
            })
        if rec is not None:
            for m in rec.cast:
                if m.cast_id == cast_id:
                    m.has_voiceprint = False
            self.save(rec)

    def match_episode_speakers(
        self,
        series_id: str,
        observations: Sequence[VoiceprintObservation],
    ) -> list[VoiceprintMatch]:
        """Match one new episode's anonymous speakers against the series cast bank.

        Three-tier safety gate:
          - ``automatic``: whole >= 0.65, lowest half >= 0.60, seconds >= 6.0,
            self >= 0.45, margin over 2nd cast >= 0.08, and unique 1-to-1 winner.
          - ``review``: whole >= 0.45 and lowest >= 0.40, OR automatic candidate
            collided with another anonymous speaker claiming the same cast member.
          - ``new``: below review threshold (likely a guest/new teammate).
        """
        rec = self.get(series_id)
        if rec is None:
            return [VoiceprintMatch(label=obs.label, tier="unavailable", reason="未选择常用方案") for obs in observations]
        bank = self.load_voiceprints(series_id)
        if not bank:
            return [VoiceprintMatch(label=obs.label, tier="unavailable", reason="这个方案还没记住说话人的声音") for obs in observations]

        cast_by_id = {m.cast_id: m for m in rec.cast}
        provisional: list[VoiceprintMatch] = []

        for obs in observations:
            whole = _unit_vector(obs.whole)
            half_a = _unit_vector(obs.half_a)
            half_b = _unit_vector(obs.half_b)
            if not whole or not half_a or not half_b or obs.seconds < VP_REVIEW["seconds"]:
                provisional.append(VoiceprintMatch(label=obs.label, tier="new", reason="说话时间较短，听一下再选名字"))
                continue
            if _cosine(half_a, half_b) < VP_MIN_SELF:
                provisional.append(VoiceprintMatch(label=obs.label, tier="review", reason="这段里可能混了别人声音，请听一下确认"))
                continue

            scored: list[dict[str, Any]] = []
            for cid, entry in bank.items():
                if entry.get("embedding_version") != obs.embedding_version:
                    continue
                centroid = _unit_vector(entry.get("centroid") or ())
                if not centroid or len(centroid) != len(whole):
                    continue
                hist = entry.get("history") or ()
                # Check whole centroid AND worst half-to-half against latest reference
                whole_s = _cosine(whole, centroid)
                half_scores = [_cosine(half_a, centroid), _cosine(half_b, centroid)]
                if hist:
                    ref = hist[-1]
                    ra, rb = _unit_vector(ref.get("half_a") or ()), _unit_vector(ref.get("half_b") or ())
                    if ra and rb and len(ra) == len(half_a):
                        half_scores.extend([
                            _cosine(half_a, ra), _cosine(half_a, rb),
                            _cosine(half_b, ra), _cosine(half_b, rb),
                        ])
                lowest_s = min(half_scores)
                cname = cast_by_id[cid].name if cid in cast_by_id else str(entry.get("name") or cid)
                scored.append({"cast_id": cid, "cast_name": cname, "whole": round(whole_s, 4), "lowest": round(lowest_s, 4)})

            scored.sort(key=lambda r: (r["whole"], r["lowest"]), reverse=True)
            if not scored:
                provisional.append(VoiceprintMatch(label=obs.label, tier="unavailable", reason="声音记录版本不同，请重新记住"))
                continue

            top = scored[0]
            runner_up = scored[1]["whole"] if len(scored) > 1 else -1.0
            margin = round(top["whole"] - runner_up, 4) if len(scored) > 1 else 1.0

            if (
                obs.seconds >= VP_AUTOMATIC["seconds"]
                and top["whole"] >= VP_AUTOMATIC["whole"]
                and top["lowest"] >= VP_AUTOMATIC["lowest"]
                and margin >= VP_AUTOMATIC["margin"]
            ):
                provisional.append(VoiceprintMatch(
                    label=obs.label, tier="automatic", cast_id=top["cast_id"], cast_name=top["cast_name"],
                    whole_score=top["whole"], lowest_score=top["lowest"], margin=margin,
                    candidates=scored[:3], reason="声音吻合，已自动认出",
                ))
            elif top["whole"] >= VP_REVIEW["whole"] and top["lowest"] >= VP_REVIEW["lowest"]:
                provisional.append(VoiceprintMatch(
                    label=obs.label, tier="review", cast_id=top["cast_id"], cast_name=top["cast_name"],
                    whole_score=top["whole"], lowest_score=top["lowest"], margin=margin,
                    candidates=scored[:3],
                    reason="有点像但不太确定，请听一下再选",
                ))
            else:
                provisional.append(VoiceprintMatch(
                    label=obs.label, tier="new", whole_score=top["whole"], lowest_score=top["lowest"],
                    margin=margin, candidates=scored[:2], reason="没听过的新声音",
                ))

        # 1-to-1 collision guard: if two anonymous labels both claim the same cast_id automatically,
        # demote both to ``review`` so the system never mislabels two people as one.
        auto_claims: dict[str, list[VoiceprintMatch]] = {}
        for m in provisional:
            if m.tier == "automatic" and m.cast_id:
                auto_claims.setdefault(m.cast_id, []).append(m)
        for claims in auto_claims.values():
            if len(claims) > 1:
                for m in claims:
                    m.tier = "review"
                    m.reason = f"本片有 {len(claims)} 段声音都像「{m.cast_name}」，请你听一下确认"
        return provisional

    # ------------------------------------------------------------------ Series Delta & 1-Click Settle
    def compute_delta(
        self,
        series_id: str,
        *,
        glossary_ids: Sequence[str] = (),
        speakers: Sequence[dict[str, Any]] = (),
        break_rule: tuple[str, str] | None = None,
        visual: dict[str, Any] | None = None,
        export: dict[str, Any] | None = None,
        pending_terms: Sequence[dict[str, str]] = (),
    ) -> list[dict[str, Any]]:
        """Compute checkable end-of-episode asset deltas to settle into ``series_id``."""
        rec = self.get(series_id)
        if rec is None:
            return []
        items: list[dict[str, Any]] = []

        # 1. Newly bound glossaries
        for gid in _unique_strings(glossary_ids):
            if gid not in rec.glossary_ids:
                items.append({
                    "id": f"glossary:{gid}", "kind": "glossary_link",
                    "label": f"下次自动启用词库「{gid}」", "payload": {"glossary_id": gid}, "checked": True,
                })

        # 2. Confirmed terms learned during this episode
        for term in pending_terms:
            src = str(term.get("from") or "").strip()
            dst = str(term.get("to") or "").strip()
            if dst:
                items.append({
                    "id": f"term:{src}->{dst}", "kind": "term_entry",
                    "label": f"把「{src} → {dst}」加入词库" if src and src != dst else f"把「{dst}」加入词库",
                    "payload": {"from": src or dst, "to": dst, "category": str(term.get("category") or "其他")},
                    "checked": True,
                })

        # 3. Named speakers not yet in cast (or color updated)
        known_cast = {m.name.casefold(): m for m in rec.cast}
        for sp in speakers:
            name = str(sp.get("name") or "").strip()
            if not name or name.startswith(("S0", "S1", "SPEAKER_", "R00", "API_", "LOCAL_")):
                continue
            color = str(sp.get("color") or "").strip()
            existing = known_cast.get(name.casefold())
            if existing is None:
                items.append({
                    "id": f"cast_add:{name}", "kind": "cast_add",
                    "label": f"记住说话人「{name}」" + ("（记住声音，下次自动认出）" if sp.get("has_voiceprint") else ""),
                    "payload": {"name": name, "color": color, "role": str(sp.get("role") or "")},
                    "checked": True,
                })
            elif color and color != existing.color:
                items.append({
                    "id": f"cast_color:{existing.cast_id}", "kind": "cast_update",
                    "label": f"把「{name}」的字幕颜色更新为 {color}",
                    "payload": {"cast_id": existing.cast_id, "color": color},
                    "checked": True,
                })

        # 4. Break rule delta
        if break_rule and break_rule[1].strip():
            lang, rule_text = str(break_rule[0] or rec.language), str(break_rule[1]).strip()
            if rec.break_rules.get(lang, "") != rule_text:
                items.append({
                    "id": f"break_rule:{lang}", "kind": "break_rule",
                    "label": f"记住断句习惯：「{rule_text[:28]}」",
                    "payload": {"language": lang, "rule": rule_text},
                    "checked": True,
                })

        # 5. Visual style delta
        if visual and visual != rec.visual:
            items.append({
                "id": "visual:update", "kind": "visual",
                "label": "记住当前字幕样式（字体、颜色与大小）",
                "payload": copy.deepcopy(visual),
                "checked": True,
            })

        # 6. Export preset delta
        if export and export != rec.export:
            items.append({
                "id": "export:update", "kind": "export",
                "label": "记住当前压制和导出设置",
                "payload": copy.deepcopy(export),
                "checked": True,
            })

        # 7. Auto-apply suggestion after 3 clean adoptions
        for rule in self.graduated_candidates(series_id):
            items.append({
                "id": f"graduate:{rule.rule_key}", "kind": "trust_graduate",
                "label": f"你连续 {rule.clean_streak} 部片都直接采纳了「{rule.label}」，以后自动帮你改好吗？",
                "payload": {"rule_key": rule.rule_key},
                "checked": False,   # explicit human opt-in!
            })
        return items

    def settle(
        self,
        series_id: str,
        selected_items: Sequence[dict[str, Any]],
        *,
        episode_label: str = "",
    ) -> SeriesRecord:
        """Apply user-approved settlement items into the Series atomically."""
        rec = self.get(series_id)
        if rec is None:
            raise ValueError("系列不存在")
        applied_summary: list[str] = []
        for item in selected_items:
            if not item.get("checked", True):
                continue
            kind = str(item.get("kind") or "")
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            if kind == "glossary_link":
                gid = str(payload.get("glossary_id") or "").strip()
                if gid and gid not in rec.glossary_ids:
                    rec.glossary_ids.append(gid)
                    applied_summary.append(f"glossary:{gid}")
            elif kind == "cast_add":
                name = str(payload.get("name") or "").strip()
                if name and not any(m.name.casefold() == name.casefold() for m in rec.cast):
                    rec.cast.append(CastMember(
                        cast_id=f"cast_{uuid.uuid4().hex[:8]}",
                        name=name,
                        color=str(payload.get("color") or ""),
                        role=str(payload.get("role") or ""),
                    ))
                    applied_summary.append(f"cast:{name}")
            elif kind == "cast_update":
                cid = str(payload.get("cast_id") or "")
                for m in rec.cast:
                    if m.cast_id == cid and payload.get("color"):
                        m.color = str(payload["color"])
                        m.updated_at = _utc_now()
                        applied_summary.append(f"cast_color:{m.name}")
            elif kind == "break_rule":
                lang = str(payload.get("language") or rec.language)
                rule = str(payload.get("rule") or "").strip()
                if rule:
                    rec.break_rules[lang] = rule
                    applied_summary.append(f"break_rule:{lang}")
            elif kind == "visual":
                rec.visual = copy.deepcopy(payload)
                applied_summary.append("visual")
            elif kind == "export":
                rec.export = copy.deepcopy(payload)
                applied_summary.append("export")
            elif kind == "trust_graduate":
                rk = str(payload.get("rule_key") or "")
                if rk in rec.trust_ledger:
                    rec.trust_ledger[rk].graduated = True
                    rec.trust_ledger[rk].declined = False
                    rec.trust_ledger[rk].updated_at = _utc_now()
                    applied_summary.append(f"graduated:{rk}")

        rec.episode_count += 1
        rec.last_used_at = _utc_now()
        if applied_summary:
            rec.provenance.append({
                "at": _utc_now(),
                "kind": "episode_settle",
                "episode": str(episode_label or "")[:80],
                "items": applied_summary,
            })
        return self.save(rec)

    # ------------------------------------------------------------------ Tier-2 Trust Graduation Ledger
    def record_rule_outcome(
        self,
        series_id: str,
        rule_key: str,
        label: str,
        *,
        episode_id: str,
        clean_adopted: bool,
    ) -> RuleTrustRecord | None:
        """Record whether one deterministic rule was adopted cleanly or reverted/rejected.

        Any rejection/undo resets ``clean_streak`` to 0 and revokes graduation.
        """
        rec = self.get(series_id)
        if rec is None or not str(rule_key or "").strip():
            return None
        entry = rec.trust_ledger.get(rule_key) or RuleTrustRecord(rule_key=rule_key, label=label)
        entry.label = label or entry.label
        if clean_adopted:
            if episode_id and episode_id not in entry.episode_ids:
                entry.episode_ids.append(episode_id)
                entry.clean_streak += 1
        else:
            entry.clean_streak = 0
            entry.graduated = False
        entry.updated_at = _utc_now()
        rec.trust_ledger[rule_key] = entry
        self.save(rec)
        return entry

    def graduated_candidates(self, series_id: str) -> list[RuleTrustRecord]:
        rec = self.get(series_id)
        if rec is None:
            return []
        return [
            r for r in rec.trust_ledger.values()
            if r.clean_streak >= TRUST_GRADUATION_HITS and not r.graduated and not r.declined
        ]

    def set_rule_graduated(self, series_id: str, rule_key: str, graduated: bool) -> bool:
        rec = self.get(series_id)
        if rec is None or rule_key not in rec.trust_ledger:
            return False
        rec.trust_ledger[rule_key].graduated = bool(graduated)
        if not graduated:
            rec.trust_ledger[rule_key].clean_streak = 0
        rec.trust_ledger[rule_key].updated_at = _utc_now()
        self.save(rec)
        return True


__all__ = [
    "CastMember",
    "RuleTrustRecord",
    "SCHEMA_VERSION",
    "SeriesRecord",
    "SeriesStore",
    "TRUST_GRADUATION_HITS",
    "VOICEPRINT_EMBEDDING_VERSION",
    "VP_AUTOMATIC",
    "VP_REVIEW",
    "VoiceprintMatch",
    "VoiceprintObservation",
    "series_root",
]
