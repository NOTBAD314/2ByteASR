"""Same-name danmaku XML for a project's source recording (2026-10-11).

Every entry path (file dialog, drag and drop, reopening a saved project, a
project created by recognition) uses this one discovery. It looks only in the
directory of the ORIGINAL source file, never in a proxy/remux/cache folder,
and binds the XML to that source: the project-level ``danmaku_path`` is used
only while ``studio_state['danmaku_binding']['source_path']`` still names the
project's primary source. A manual choice or an explicit unbind is never
overwritten by discovery. Parsing runs on a worker thread.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .media_ingest import discover_same_stem_xml

STATE_KEY = "danmaku_binding"


def normalized_source(path: str | os.PathLike[str]) -> str:
    from .studio_project import _normalized_media_source
    return _normalized_media_source(str(path or ""))


@dataclass(frozen=True)
class DanmakuDiscovery:
    """Result of one background search next to a source recording."""

    source_path: str
    status: str  # automatic | ambiguous | invalid | none | no_media
    path: str = ""
    candidates: tuple[str, ...] = ()
    count: int = 0
    duration_ms: int = 0
    error: str = ""


def inspect_xml(path: str | os.PathLike[str]) -> tuple[int, int, str]:
    """(danmaku count, last time ms, error) after a full parse."""
    from .studio_danmaku import parse_danmaku_xml
    try:
        document = parse_danmaku_xml(path)
    except (OSError, ValueError) as exc:
        return 0, 0, str(exc) or type(exc).__name__
    if not document.count:
        return 0, 0, "XML 中没有可用的弹幕条目"
    return document.count, document.duration_ms, ""


def discover_for_source(source_path: str | os.PathLike[str]) -> DanmakuDiscovery:
    """Search beside the original recording; runs off the GUI thread."""
    source = str(source_path or "")
    key = normalized_source(source)
    if not source or not Path(source).is_file():
        return DanmakuDiscovery(key, "no_media")
    try:
        candidates, automatic = discover_same_stem_xml(source)
    except OSError as exc:
        return DanmakuDiscovery(key, "none", error=str(exc))
    if not candidates:
        return DanmakuDiscovery(key, "none")
    if not automatic:
        return DanmakuDiscovery(key, "ambiguous", candidates=tuple(candidates))
    count, duration, error = inspect_xml(automatic)
    if error:
        return DanmakuDiscovery(key, "invalid", path=automatic, candidates=tuple(candidates), error=error)
    return DanmakuDiscovery(key, "automatic", path=automatic, candidates=tuple(candidates),
                            count=count, duration_ms=duration)


def binding_of(project) -> dict:
    value = project.studio_state.get(STATE_KEY) if project is not None else None
    return dict(value) if isinstance(value, dict) else {}


def primary_source(project) -> str:
    return str(getattr(getattr(project, "media", None), "path", "") or "")


def binding_matches_source(project) -> bool:
    binding = binding_of(project)
    return bool(binding) and binding.get("source_path") == normalized_source(primary_source(project))


def needs_discovery(project) -> bool:
    """Search when this source has no binding decision of its own yet."""
    if project is None or not primary_source(project):
        return False
    binding = binding_of(project)
    if binding_matches_source(project):
        if binding.get("origin") in {"manual", "unbound"}:
            return False
        # An automatic binding is re-checked when its file vanished or changed.
        path = str(binding.get("path") or "")
        return not path or not Path(path).is_file() or binding.get("status") != "automatic"
    if binding:
        return True  # recorded for another source: look beside the new one
    # Legacy projects: a manually imported XML (no binding record yet) stays.
    from .studio_edit_sequence import sequence_of
    return not sequence_of(project).danmaku_path


def apply_discovery(project, discovery: DanmakuDiscovery) -> bool:
    """Bind/record a discovery if it still describes the project's source."""
    from .studio_edit_sequence import sequence_of
    if project is None or discovery.source_path != normalized_source(primary_source(project)):
        return False
    binding = binding_of(project)
    if binding.get("source_path") == discovery.source_path and binding.get("origin") in {"manual", "unbound"}:
        return False
    sequence = sequence_of(project)
    sequence.danmaku_path = discovery.path if discovery.status == "automatic" else ""
    project.studio_state[STATE_KEY] = {
        "source_path": discovery.source_path, "origin": "automatic", "status": discovery.status,
        "path": discovery.path, "candidates": list(discovery.candidates),
        "count": discovery.count, "duration_ms": discovery.duration_ms, "error": discovery.error,
    }
    # Compatibility keys read by older panels and audits.
    project.studio_state["media_xml_candidates"] = list(discovery.candidates)
    project.studio_state["media_xml_match"] = {"automatic": "automatic", "ambiguous": "ambiguous"}.get(
        discovery.status, "none")
    return True


def bind_manual(project, path: str, count: int = 0, duration_ms: int = 0, error: str = "") -> None:
    from .studio_edit_sequence import sequence_of
    resolved = str(Path(path).resolve())
    sequence_of(project).danmaku_path = resolved if not error else ""
    previous = binding_of(project)
    project.studio_state[STATE_KEY] = {
        "source_path": normalized_source(primary_source(project)), "origin": "manual",
        "status": "invalid" if error else "manual", "path": resolved,
        "candidates": list(previous.get("candidates") or [resolved]),
        "count": int(count), "duration_ms": int(duration_ms), "error": error,
    }
    project.studio_state["media_xml_match"] = "manual" if not error else "none"


def unbind(project) -> None:
    from .studio_edit_sequence import sequence_of
    sequence_of(project).danmaku_path = ""
    previous = binding_of(project)
    project.studio_state[STATE_KEY] = {
        "source_path": normalized_source(primary_source(project)), "origin": "unbound", "status": "unbound",
        "path": "", "candidates": list(previous.get("candidates") or project.studio_state.get("media_xml_candidates") or []),
        "count": 0, "duration_ms": 0, "error": "",
    }
    project.studio_state["media_xml_match"] = "none"


def effective_path(project) -> str:
    """The XML analysis may use: bound to the current source and present."""
    from .studio_edit_sequence import sequence_of
    path = sequence_of(project).danmaku_path if project is not None else ""
    if not path:
        return ""
    binding = binding_of(project)
    if binding and not binding_matches_source(project):
        return ""
    return path


def describe(project) -> tuple[str, str, dict]:
    """(state, file name, fields) for the panel; never a bare 'unmatched'."""
    from .studio_edit_sequence import sequence_of
    if project is None:
        return "no_project", "", {}
    source = primary_source(project)
    if not source:
        return "no_media", "", {}
    binding = binding_of(project)
    if not Path(source).is_file() and not binding_matches_source(project):
        return "offline", Path(source).stem + ".xml", {}
    path = sequence_of(project).danmaku_path
    stem = Path(source).stem + ".xml"
    if binding and not binding_matches_source(project):
        return ("searching", stem, {}) if not path else ("stale", Path(path).name, {})
    status = binding.get("status") or ("manual" if path else "")
    if path and not Path(path).is_file():
        return "missing", Path(path).name, {"path": path}
    fields = {"count": int(binding.get("count") or 0), "error": str(binding.get("error") or ""),
              "candidates": list(binding.get("candidates") or ()), "path": path or binding.get("path", "")}
    if path:
        return ("automatic" if binding.get("origin") == "automatic" else "manual"), Path(path).name, fields
    if status in {"ambiguous", "invalid", "unbound"}:
        return status, Path(str(binding.get("path") or stem)).name, fields
    if status == "none":
        return "none", stem, fields
    return "searching", stem, fields
