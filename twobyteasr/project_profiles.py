"""Versioned, reusable recognition profiles containing configuration references only."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 2

# 方案快照中的 ASR 参数键（与 persist_asr_configuration 写入 models 节的键一致）。
# 密钥不入快照：按 provider+base_url 引用 DPAPI 存储。
ASR_CONFIG_KEYS = (
    "primary_asr_backend",
    "qwen_asr_backend",
    "qwen_asr_model",
    "qwen_asr_api_provider",
    "qwen_asr_api_protocol",
    "qwen_asr_api_model",
    "qwen_asr_api_url",
    "firered_asr_backend",
    "api_transcribe_style",
    "speaker_source",
)


def normalize_asr_config(values: Any) -> dict[str, str]:
    """把方案 ASR 快照规整为 {键: 字符串}，未知键丢弃，深拷贝防共享。

    全空输入返回 {}——空 dict 是"无快照"（v1 旧方案/未保存）的规范形态，
    应用层据此保持全局现状而不是清空参数。
    """
    if not isinstance(values, dict):
        return {}
    normalized = {key: str(values.get(key, "") or "") for key in ASR_CONFIG_KEYS}
    return {key: value for key, value in normalized.items() if value} or {}


def normalize_llm_config(values: Any) -> dict:
    """Additive non-secret snapshot. Empty legacy bookmarks retain globals."""
    if not isinstance(values, dict):
        return {}
    result = {}
    for stage in ("polish", "group"):
        endpoint = values.get(stage)
        if not isinstance(endpoint, dict) or not endpoint.get("service"):
            return {}
        result[stage] = {key: str(endpoint.get(key) or "") for key in
                         ("service", "provider", "transport", "base_url", "model", "protocol", "provider_name")}
        for key in ("json_mode", "structured_output"):
            result[stage][key] = bool(endpoint.get(key, True))
    result["unified"] = bool(values.get("unified", True))
    result["use_ai_grouping"] = bool(values.get("use_ai_grouping", True))
    result["enable_ai_polish"] = bool(values.get("enable_ai_polish", True))
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def project_profiles_path(base: str | os.PathLike[str] | None = None) -> Path:
    root = Path(base) if base is not None else Path(
        os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    ) / "2ByteASR"
    return root / "profiles.json"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _unique_strings(values: Iterable[object]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


@dataclass
class ProjectProfile:
    id: str
    name: str
    recognition_plan: str = "custom"
    primary_asr: str = ""
    timestamp_model: str = ""
    evidence_model: str = ""
    llm_enabled: bool = False
    llm_config_ref: str = ""
    asr_config: dict[str, str] = field(default_factory=dict)
    llm_config: dict = field(default_factory=dict)
    glossary_ids: list[str] = field(default_factory=list)
    language: str = "zh"
    subtitle_mode: str = "monolingual"
    subtitle_style_preset: str = "default"
    render_preset: str = "default"
    export_format: str = "srt"
    review_threshold: float = 0.65
    review_strategy: str = "risk_first"
    project_directories: list[str] = field(default_factory=list)
    use_count: int = 0
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    last_used_at: str = ""

    def normalize(self) -> "ProjectProfile":
        self.id = str(self.id or uuid.uuid4().hex).strip()
        self.name = str(self.name or "未命名方案").strip()
        self.recognition_plan = str(self.recognition_plan or "custom")
        self.primary_asr = str(self.primary_asr or "")
        self.timestamp_model = str(self.timestamp_model or "")
        self.evidence_model = str(self.evidence_model or "")
        self.llm_enabled = bool(self.llm_enabled)
        self.llm_config_ref = str(self.llm_config_ref or "")
        self.asr_config = normalize_asr_config(self.asr_config)
        self.llm_config = normalize_llm_config(self.llm_config)
        self.glossary_ids = _unique_strings(self.glossary_ids)
        self.language = str(self.language or "zh")
        self.subtitle_mode = "bilingual" if self.subtitle_mode == "bilingual" else "monolingual"
        self.subtitle_style_preset = str(self.subtitle_style_preset or "default")
        self.render_preset = str(self.render_preset or "default")
        self.export_format = str(self.export_format or "srt")
        self.review_threshold = min(1.0, max(0.0, float(self.review_threshold)))
        self.review_strategy = str(self.review_strategy or "risk_first")
        self.project_directories = _unique_strings(self.project_directories)
        self.use_count = max(0, int(self.use_count))
        self.created_at = str(self.created_at or _utc_now())
        self.updated_at = str(self.updated_at or self.created_at)
        self.last_used_at = str(self.last_used_at or "")
        return self

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectProfile":
        allowed = {item.name for item in fields(cls)}
        return cls(**{key: copy.deepcopy(value) for key, value in payload.items() if key in allowed}).normalize()


class ProjectProfileStore:
    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path) if path is not None else project_profiles_path()

    def _load_payload(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8-sig")
        except OSError:
            raw = ""
        self._backup_v1_once(raw)
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            payload = {}
        profiles = payload.get("profiles", []) if isinstance(payload, dict) else []
        return {
            "schema_version": SCHEMA_VERSION,
            "profiles": [asdict(ProjectProfile.from_dict(item)) for item in profiles if isinstance(item, dict)],
            "last_selected_profile_id": str(payload.get("last_selected_profile_id", "")) if isinstance(payload, dict) else "",
            "last_started_profile": copy.deepcopy(payload.get("last_started_profile", {})) if isinstance(payload, dict) else {},
        }

    def _backup_v1_once(self, raw: str) -> None:
        """v1→v2（新增 asr_config 快照）迁移留痕：首次读到旧版本文件时做一次性备份。"""
        if not raw:
            return
        try:
            existing = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(existing, dict) or existing.get("schema_version", 1) >= 2:
            return
        if not existing.get("profiles"):
            return
        backup = self.path.with_name(self.path.stem + ".v1.json")
        if backup.exists():
            return
        try:
            backup.write_text(raw, encoding="utf-8")
        except OSError:
            pass

    def _save_payload(self, payload: dict[str, Any]) -> None:
        payload["schema_version"] = SCHEMA_VERSION
        _atomic_write(self.path, payload)

    def list(self) -> list[ProjectProfile]:
        return [ProjectProfile.from_dict(item) for item in self._load_payload()["profiles"]]

    def get(self, profile_id: str) -> ProjectProfile | None:
        profile_id = str(profile_id or "")
        return next((profile for profile in self.list() if profile.id == profile_id), None)

    def last_selected_id(self) -> str:
        return self._load_payload()["last_selected_profile_id"]

    def startup_profile(self) -> ProjectProfile | None:
        payload = self._load_payload()
        started = payload.get('last_started_profile')
        if isinstance(started, dict) and started.get('snapshot'):
            profile = ProjectProfile.from_dict(started['snapshot'])
            profile.id = str(started['snapshot'].get('id') or '')
            saved = self.get(profile.id)
            if saved is not None:
                profile.name = saved.name  # Stable ID survives a rename.
            elif profile.id:
                profile.name += '（已删除方案的上次运行配置）'
                profile.id = ''
            return profile
        return self.get(payload['last_selected_profile_id'])

    def record_started(self, profile_id: str, configuration: dict, media_paths=()) -> None:
        """Called only after worker.start succeeds; never save credentials."""
        payload = self._load_payload()
        saved = next((p for p in payload['profiles'] if p['id'] == profile_id), None)
        snapshot = dict(saved or {'id':'', 'name':'上次运行的自定义配置'})
        allowed = {f.name for f in fields(ProjectProfile)} - {'id','name','use_count','last_used_at','created_at','updated_at'}
        snapshot.update({k: copy.deepcopy(v) for k,v in configuration.items() if k in allowed})
        snapshot = asdict(ProjectProfile.from_dict(snapshot))
        if saved is None:
            snapshot['id'] = ''
        now = _utc_now()
        payload['last_started_profile'] = {'started_at':now, 'snapshot':snapshot}
        if saved is not None:
            saved['last_used_at'] = now
            saved['use_count'] = int(saved.get('use_count',0))+1
            directories = list(saved.get('project_directories',[]))
            directories.extend(str(Path(str(p)).resolve().parent) for p in media_paths)
            saved['project_directories'] = list(dict.fromkeys(directories))[-20:]
        self._save_payload(payload)

    def set_last_selected(self, profile_id: str) -> None:
        payload = self._load_payload()
        payload["last_selected_profile_id"] = str(profile_id or "")
        self._save_payload(payload)

    def create(self, name: str, **configuration: Any) -> ProjectProfile:
        profile = ProjectProfile(id=uuid.uuid4().hex, name=name, **configuration).normalize()
        payload = self._load_payload()
        if any(item.get("name", "").casefold() == profile.name.casefold() for item in payload["profiles"]):
            raise ValueError(f"profile already exists: {profile.name}")
        payload["profiles"].append(asdict(profile))
        payload["last_selected_profile_id"] = profile.id
        self._save_payload(payload)
        return profile

    def update(self, profile_id: str, **configuration: Any) -> ProjectProfile:
        payload = self._load_payload()
        for index, item in enumerate(payload["profiles"]):
            if item.get("id") != str(profile_id):
                continue
            merged = {**item, **copy.deepcopy(configuration), "id": str(profile_id), "updated_at": _utc_now()}
            profile = ProjectProfile.from_dict(merged)
            payload["profiles"][index] = asdict(profile)
            self._save_payload(payload)
            return profile
        raise KeyError(profile_id)

    def update_asr_config(self, profile_id: str, asr_config: dict[str, Any]) -> ProjectProfile:
        """只更新方案的 ASR 快照（隐式保存路径用），不动其他字段语义。"""
        return self.update(profile_id, asr_config=normalize_asr_config(asr_config))

    def save_as(self, source_id: str, name: str, **overrides: Any) -> ProjectProfile:
        source = self.get(source_id)
        if source is None:
            raise KeyError(source_id)
        values = asdict(source)
        for key in ("id", "name", "created_at", "updated_at", "last_used_at", "use_count"):
            values.pop(key, None)
        values.update(overrides)
        return self.create(name, **values)

    def rename(self, profile_id: str, name: str) -> ProjectProfile:
        name = str(name or "").strip()
        if not name:
            raise ValueError("profile name is required")
        if any(profile.id != profile_id and profile.name.casefold() == name.casefold() for profile in self.list()):
            raise ValueError(f"profile already exists: {name}")
        return self.update(profile_id, name=name)

    def delete(self, profile_id: str) -> bool:
        payload = self._load_payload()
        kept = [item for item in payload["profiles"] if item.get("id") != str(profile_id)]
        if len(kept) == len(payload["profiles"]):
            return False
        payload["profiles"] = kept
        if payload.get("last_selected_profile_id") == str(profile_id):
            payload["last_selected_profile_id"] = ""
        self._save_payload(payload)
        return True

    def mark_used(self, profile_id: str, media_paths: Iterable[str] = ()) -> ProjectProfile:
        profile = self.get(profile_id)
        if profile is None:
            raise KeyError(profile_id)
        directories = list(profile.project_directories)
        for raw in media_paths:
            parent = str(Path(str(raw)).resolve().parent)
            if parent not in directories:
                directories.append(parent)
        updated = self.update(
            profile_id,
            use_count=profile.use_count + 1,
            last_used_at=_utc_now(),
            project_directories=directories[-20:],
        )
        payload = self._load_payload()
        payload["last_selected_profile_id"] = profile_id
        self._save_payload(payload)
        return updated

    def recommend(
        self,
        media_paths: Iterable[str] = (),
        *,
        explicit_profile_id: str = "",
        project_profile_id: str = "",
        glossary_ids: Iterable[str] = (),
    ) -> tuple[ProjectProfile | None, str]:
        profiles = self.list()
        by_id = {profile.id: profile for profile in profiles}
        for profile_id, reason in (
            (explicit_profile_id, "用户明确选择"),
            (project_profile_id, "当前项目使用"),
        ):
            if profile_id in by_id:
                return by_id[profile_id], reason
        directories = {str(Path(str(path)).resolve().parent) for path in media_paths if str(path).strip()}
        directory_matches = [profile for profile in profiles if directories.intersection(profile.project_directories)]
        if directory_matches:
            return max(directory_matches, key=lambda item: item.last_used_at), "最近用于同目录素材"
        glossary_set = set(_unique_strings(glossary_ids))
        glossary_matches = [profile for profile in profiles if glossary_set.intersection(profile.glossary_ids)]
        if glossary_matches:
            return max(glossary_matches, key=lambda item: item.last_used_at), "词库关联"
        recent = [profile for profile in profiles if profile.last_used_at]
        if recent:
            return max(recent, key=lambda item: item.last_used_at), "最近使用"
        return None, ""
