"""Small, explicit open-source font policy for Advanced subtitle styles."""

from __future__ import annotations

from dataclasses import dataclass
import re
import sys
from typing import Iterable, Any


_SYSTEM_FONT_INVENTORY: tuple["SystemFontEntry", ...] | None = None


@dataclass(frozen=True)
class OpenSourceFont:
    family: str
    license_name: str
    license_url: str
    project_url: str


RECOMMENDED_OPEN_SOURCE_FONTS = (
    OpenSourceFont(
        "Noto Sans SC", "SIL Open Font License 1.1",
        "https://scripts.sil.org/OFL",
        "https://fonts.google.com/noto/specimen/Noto+Sans+SC",
    ),
    OpenSourceFont(
        "Source Han Sans CN", "SIL Open Font License 1.1",
        "https://scripts.sil.org/OFL",
        "https://github.com/adobe-fonts/source-han-sans",
    ),
)

STYLE_FONT_RECOMMENDATIONS = {
    "cyberpunk hud": "Noto Sans SC",
    "gaming impact": "Source Han Sans CN",
    "soft neon": "Noto Sans SC",
}


def resolve_style_font(style_name: str, installed_families: Iterable[str]) -> tuple[str, bool]:
    """Return (family, installed); fallback is stable and never downloaded."""
    installed = {str(item).casefold(): str(item) for item in installed_families}
    recommended = STYLE_FONT_RECOMMENDATIONS.get(str(style_name).casefold(), "Noto Sans SC")
    if recommended.casefold() in installed:
        return installed[recommended.casefold()], True
    for fallback in ("Microsoft YaHei UI", "Microsoft YaHei", "Arial"):
        if fallback.casefold() in installed:
            return installed[fallback.casefold()], False
    return "sans-serif", False


@dataclass(frozen=True)
class SystemFontEntry:
    family: str
    styles: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedFontFace:
    family: str
    style: str
    weight: int
    source_han: bool
    fallback_reason: str = ""


SOURCE_HAN_FAMILY_ALIASES = (
    "Source Han Sans SC Heavy",
    "Source Han Sans CN Heavy",
    "思源黑体 Heavy",
    "思源黑体 CN Heavy",
    "思源黑体 SC Heavy",
    "Source Han Sans SC",
    "Source Han Sans CN",
    "思源黑体 CN",
    "思源黑体 SC",
    "思源黑体",
)


def _font_database(database: Any = None):
    if database is not None:
        return database
    from PySide6.QtGui import QFontDatabase
    return QFontDatabase


def system_font_inventory(database: Any = None) -> tuple[SystemFontEntry, ...]:
    """Enumerate the fonts Qt can actually render in the current Windows session."""
    global _SYSTEM_FONT_INVENTORY
    if database is None and _SYSTEM_FONT_INVENTORY is not None:
        return _SYSTEM_FONT_INVENTORY
    db = _font_database(database)
    families = sorted({str(item).strip() for item in db.families() if str(item).strip()}, key=str.casefold)
    result = tuple(SystemFontEntry(family, tuple(str(s) for s in db.styles(family))) for family in families)
    if database is None:
        _SYSTEM_FONT_INVENTORY = result
    return result


def windows_font_family_names() -> tuple[str, ...]:
    """Return installed Windows font display names without requiring a QApplication."""
    if sys.platform != "win32":
        return ()
    try:
        import winreg
    except ImportError:
        return ()
    names: list[str] = []
    for hive, path in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    ):
        try:
            with winreg.OpenKey(hive, path) as key:
                for index in range(winreg.QueryInfoKey(key)[1]):
                    name = str(winreg.EnumValue(key, index)[0])
                    name = re.sub(r"\s*\((?:TrueType|OpenType|All res)\)\s*$", "", name, flags=re.I).strip()
                    if name:
                        names.append(name)
        except OSError:
            continue
    return tuple(dict.fromkeys(names))


def resolve_source_han_heavy(
    inventory: Iterable[SystemFontEntry | str] | None = None,
) -> ResolvedFontFace:
    """Resolve a real Source Han Heavy face, with an explicit readable fallback."""
    if inventory is None:
        from .font_metadata import resolve_local_face
        face, warning = resolve_local_face('Source Han Sans SC Heavy', 900)
        return ResolvedFontFace(face.full_name, face.style, face.weight,
            face.family == 'Source Han Sans SC', warning)
    raw = tuple(inventory) if inventory is not None else windows_font_family_names()
    entries = tuple(
        item if isinstance(item, SystemFontEntry) else SystemFontEntry(str(item), ())
        for item in raw
        if str(getattr(item, "family", item) or "").strip()
    )
    by_name = {entry.family.casefold(): entry for entry in entries}
    for alias in SOURCE_HAN_FAMILY_ALIASES:
        entry = by_name.get(alias.casefold())
        if entry is None:
            continue
        styles = entry.styles or (("Heavy",) if "heavy" in entry.family.casefold() else ("Regular",))
        style = min(styles, key=lambda value: (abs(_style_weight(value) - 800), _style_weight(value) < 800))
        weight = max(_style_weight(style), 800 if "heavy" in entry.family.casefold() else 400)
        return ResolvedFontFace(entry.family, style, weight, True)
    fallbacks = ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Arial")
    for fallback in fallbacks:
        entry = by_name.get(fallback.casefold())
        if entry is not None:
            styles = entry.styles or ("Bold",)
            style = min(styles, key=lambda value: abs(_style_weight(value) - 700))
            return ResolvedFontFace(
                entry.family,
                style,
                max(700, _style_weight(style)),
                False,
                "Source Han Sans Heavy is not installed",
            )
    return ResolvedFontFace(
        "Microsoft YaHei UI",
        "Bold",
        700,
        False,
        "font inventory unavailable; using explicit Windows fallback",
    )


_WEIGHT_WORDS = {
    "thin": 100, "extralight": 200, "ultralight": 200, "light": 300,
    "regular": 400, "normal": 400, "book": 400, "medium": 500,
    "semibold": 600, "demibold": 600, "bold": 700, "extrabold": 800,
    "ultrabold": 800, "heavy": 800, "black": 900,
}


def _style_weight(style: str) -> int:
    compact = re.sub(r"[^a-z]", "", str(style).casefold())
    for word, weight in sorted(_WEIGHT_WORDS.items(), key=lambda item: -len(item[0])):
        if word in compact:
            return weight
    return 400


def resolve_font_weight(family: str, preferred_weight: str | int = 400,
                        database: Any = None) -> tuple[str, int]:
    """Resolve a requested semantic weight to the closest installed face."""
    if database is None:
        from .font_metadata import resolve_local_face
        requested = (_WEIGHT_WORDS.get(re.sub(r'[^a-z]', '', preferred_weight.casefold()),400)
                     if isinstance(preferred_weight,str) else int(preferred_weight))
        face, _warning = resolve_local_face(family, requested)
        return face.style, face.weight
    db = _font_database(database)
    styles = [str(item) for item in db.styles(str(family))] or ["Regular"]
    if isinstance(preferred_weight, str):
        requested = _WEIGHT_WORDS.get(re.sub(r"[^a-z]", "", preferred_weight.casefold()), 400)
    else:
        requested = max(1, min(1000, int(preferred_weight)))
    best = min(styles, key=lambda style: (abs(_style_weight(style) - requested), _style_weight(style) < requested))
    return best, _style_weight(best)
