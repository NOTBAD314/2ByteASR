"""One local, source-labelled content scene shared by recognition text stages."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Any

SCENE_VERSION = "content-scene-v2-clause-topic"
NORMALIZATION_POLICY = "confirmed_scoped_aliases_local; canonical_spelling_exact; ambiguous_review; no_acoustic_claim"


@dataclass(frozen=True)
class ContentScene:
    domain: str = ""
    domain_ids: tuple[str, ...] = ()
    source: str = "unknown"
    language: str = "zh-CN"
    content_type: str = "speech"
    glossary_versions: tuple[tuple[str, str], ...] = ()
    normalization_policy: str = NORMALIZATION_POLICY
    version: str = SCENE_VERSION

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["glossary_versions"] = dict(self.glossary_versions)
        return result

    def summary(self) -> str:
        libraries = ",".join(f"{key}@{revision}" for key, revision in self.glossary_versions) or "none"
        return f"domain={self.domain or 'unknown'}; source={self.source}; type={self.content_type}; language={self.language}; glossaries={libraries}"


def library_domain(library) -> tuple[str, str]:
    """Read domain metadata; a generic/custom library title is not a game guess.

    Existing task snapshots froze the built-in profile JSON. Its identity is
    therefore authoritative metadata even when the Home game field was blank.
    New user libraries may explicitly store domain/game metadata in that JSON.
    """
    try:
        metadata = json.loads(library.profile_json or "{}")
    except (ValueError, TypeError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    assigned = metadata.get('_content_domain') or {}
    if isinstance(assigned, dict) and assigned.get('id') and assigned.get('name'):
        return str(assigned['id']), str(assigned['name'])
    domain = str(metadata.get("domain") or metadata.get("game") or metadata.get("name") or "").strip()
    identity = str(metadata.get("domain_id") or metadata.get("identity") or "").strip()
    if identity:
        return identity, domain or library.name
    if domain:
        return domain.casefold(), domain
    return "", ""


def resolve_content_scene(context, snapshot=None) -> ContentScene:
    from dataclasses import replace
    scene = _resolve_content_scene(context, snapshot)
    # The spoken language of the task (resolved after the primary transcript).
    language = str(getattr(context, "task_language", "") or "")
    if language == "ja":
        scene = replace(scene, language="ja-JP")
    elif language == "en":
        scene = replace(scene, language="en-US")
    return scene


def _resolve_content_scene(context, snapshot=None) -> ContentScene:
    snapshot = snapshot if snapshot is not None else getattr(context, "glossary_snapshot", None)
    libraries = tuple(getattr(snapshot, "libraries", ())) if getattr(context, "enable_domain_terms", False) else ()
    versions = tuple((library.id, library.revision) for library in libraries)
    domains = tuple(dict.fromkeys(library_domain(library) for library in libraries if library_domain(library)[0]))
    by_name = {}
    for identity, label in domains:
        by_name.setdefault(label.casefold(), []).append((identity, label))
    explicit = str(getattr(context, "game_name", "") or "").strip()
    if explicit:
        # Matching metadata supplies a stable ID without changing the user's label.
        ids = tuple(key for key, label in domains if explicit in (key, label))
        return ContentScene(explicit, ids or (explicit,), "user_selected", content_type="game_commentary", glossary_versions=versions)
    if len(by_name) == 1:
        matching = next(iter(by_name.values()))
        return ContentScene(matching[0][1], tuple(dict.fromkeys(row[0] for row in matching)),
            "enabled_glossary_metadata", content_type="game_commentary", glossary_versions=versions)
    if len(by_name) > 1:
        return ContentScene("", tuple(dict.fromkeys(row[0] for row in domains)),
            "mixed_enabled_glossaries", content_type="mixed", glossary_versions=versions)
    return ContentScene(glossary_versions=versions)


def runtime_content_scene() -> ContentScene:
    from .runtime import get_runtime_context
    return resolve_content_scene(get_runtime_context())


def alias_context_conflict(text: str, source: str, canonical: str, *, category: str = "", scene=None, span=None) -> str:
    """A confirmed player nickname has no authority over a clear media topic.

    This is a generic local scope guard, not a guessed nickname association.
    Semantic uncertainty stays in the current existing model request. Literal
    custom terms remain useful even when there is no game metadata.
    """
    if source.casefold() == canonical.casefold():
        return ""
    is_person = any(value in str(category).lower() for value in ("选手", "player", "昵称", "人名"))
    is_person = is_person or bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{2,}", canonical) and re.search(r"[\u4e00-\u9fff]", source))
    if not is_person or source not in text:
        return ""
    for match in re.finditer(re.escape(source), str(text)):
        if span is not None and match.span() != tuple(span):
            continue
        before = re.split(r"[。！？!?；;，,\n]", str(text[max(0, match.start()-32):match.start()]))[-1]
        after = re.split(r"[。！？!?；;，,\n]", str(text[match.end():match.end()+32]))[0]
        local = before + source + after
        if re.search(re.escape(source) + r'(?:这个)?(?:选手|队员|队友|ID)', local, re.I):
            continue
        if re.search(r"动画|动漫|电视剧|电影|特摄|小时候|童年|卡通|追剧", local):
            return "alias_context_topic_conflict"
        if re.search(re.escape(source) + r'.{0,8}(?:打比赛|比赛|电竞|架枪|击杀)', local):
            continue
        if re.search(r"看过|喜欢看|观看", local):
            return "alias_context_topic_conflict"
    return ""
