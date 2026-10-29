"""Type dispatch shared by command-line, IPC and desktop drops.

Classification deliberately does not open files: only the project loader may
interpret a project, and only media intake may validate recognition inputs.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..media.media_intake import SUPPORTED_MEDIA_SUFFIXES

PROJECT_SUFFIXES = frozenset({".2byteproj", ".2byteasrproj"})
SUBTITLE_SUFFIXES = frozenset({".srt", ".ass"})
SUPPORTED_OPEN_SUFFIXES = PROJECT_SUFFIXES | SUBTITLE_SUFFIXES | SUPPORTED_MEDIA_SUFFIXES


def path_identity(path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def classify_open_paths(paths):
    """Return ordered typed requests, coalescing duplicate path identities."""
    result, seen = [], set()
    for raw in paths or ():
        path = str(Path(str(raw)).expanduser())
        identity = path_identity(path)
        if identity in seen:
            continue
        seen.add(identity)
        suffix = Path(path).suffix.lower()
        kind = ("project" if suffix in PROJECT_SUFFIXES else
                "subtitle" if suffix in SUBTITLE_SUFFIXES else
                "media" if suffix in SUPPORTED_MEDIA_SUFFIXES else "unsupported")
        result.append((kind, path))
    return result


def startup_destination(paths, preferences, *, explicit_operation=False):
    """Explicit files/operations take precedence over the no-file preference."""
    requests = classify_open_paths(paths)
    if any(kind in {"project", "subtitle"} for kind, _ in requests):
        return "project_library"
    if requests or explicit_operation:
        return "recognition"
    return ("project_library" if preferences.get("startup_page") == "project_library"
            else "recognition")
