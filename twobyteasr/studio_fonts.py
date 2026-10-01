"""System-font checks for Subtitle Studio projects and render settings."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtGui import QFontDatabase

from .studio_project import SubtitleProject


def installed_font_families() -> set[str]:
    return {str(name).strip().casefold() for name in QFontDatabase.families() if str(name).strip()}


def missing_project_fonts(
    project: SubtitleProject,
    installed: Iterable[str] | None = None,
) -> list[str]:
    if installed is None:
        from .font_metadata import resolve_local_face
        return sorted({warning for style in project.styles
            for _, warning in [resolve_local_face(style.font_family, style.font_weight,
                style.font_style_name, style.bold, style.font_file, style.font_face_index)] if warning})
    available = (
        installed_font_families()
        if installed is None
        else {str(name).strip().casefold() for name in installed if str(name).strip()}
    )
    missing = {
        style.font_family.strip()
        for style in project.styles
        if style.font_family.strip().casefold() not in available
    }
    return sorted(missing, key=str.casefold)
