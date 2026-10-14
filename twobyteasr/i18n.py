"""UI language overlay (zh / zh-Hant / en / ja).

The application's built-in strings are Chinese. This module overlays English
or Japanese translations at runtime by walking the widget tree, so the UI
can switch languages without touching every call site. Strings without a
translation entry are left untouched. The choice persists in
2byteasr_settings.json under the "ui" section.

Translations live in ``twobyteasr/locales/<language>.json``: one flat JSON
object per language whose keys are the exact Chinese source strings (after
the "●  " decoration and surrounding whitespace are stripped) and whose
values are the translations. Both files carry the same keys. Add or change
entries with ``python scripts/i18n_locales.py``; keep the existing key order
(when two sources share one translation, the later one wins the reverse
lookup used to recapture widgets after a language switch).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from twobyteasr.settings import load_runtime_settings, save_runtime_settings


LOCALE_DIR = Path(__file__).resolve().parent / "locales"
# 2026-10-14: 繁體中文 (zh-Hant) is generated from the Simplified sources by
# scripts/make_zh_hant.py; "zh" stays the Simplified source text.
TRANSLATED_LANGUAGES = ("en", "ja", "zh-Hant")
SUPPORTED_LANGUAGES = ("zh", "zh-Hant", "en", "ja")
# language -> reason, for a locale file that could not be read. The UI then
# keeps the Chinese source text for that language instead of failing to start.
LOCALE_LOAD_ERRORS: dict[str, str] = {}


def _load_locale(language: str) -> dict[str, str]:
    path = LOCALE_DIR / f"{language}.json"
    try:
        with path.open(encoding="utf-8") as stream:
            table = json.load(stream)
        if not isinstance(table, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in table.items()):
            raise ValueError("expected one JSON object of strings")
    except (OSError, ValueError) as exc:
        LOCALE_LOAD_ERRORS[language] = f"{path}: {exc}"
        print(f"[i18n] {language} translations unavailable: {path}: {exc}", file=sys.stderr)
        return {}
    return table


# en / ja load at import; zh-Hant (about 1 MB with the code literals) only
# when it is first used, so Simplified, English and Japanese starts pay nothing.
_TRANSLATIONS: dict[str, dict[str, str]] = {
    language: _load_locale(language) for language in TRANSLATED_LANGUAGES if language != "zh-Hant"
}

_KNOWN_KEYS = frozenset().union(*(table.keys() for table in _TRANSLATIONS.values()))


def _load_hant() -> dict[str, str]:
    """zh-Hant.json (the en/ja UI keys) plus zh-Hant-literals.json (2026-10-14).

    The literals file holds every other Chinese string constant of the program
    source, converted by scripts/make_zh_hant.py: help texts, tooltips and
    labels that have no English translation yet would otherwise stay
    Simplified in 繁體中文. Only strings passed to translate()/tr()/bind_text()
    or set as known widget text are looked up; user content never is.
    """
    table = dict(_load_locale("zh-Hant"))
    try:
        with (LOCALE_DIR / "zh-Hant-literals.json").open(encoding="utf-8") as stream:
            literals = json.load(stream)
        if isinstance(literals, dict):
            for key, value in literals.items():
                if isinstance(key, str) and isinstance(value, str):
                    table.setdefault(key, value)
    except (OSError, ValueError) as exc:
        print(f"[i18n] zh-Hant literals unavailable: {exc}", file=sys.stderr)
    return table


def language_table(language: str) -> dict[str, str]:
    """The translation table of ``language`` (loads zh-Hant on first use)."""
    global _KNOWN_KEYS
    table = _TRANSLATIONS.get(language)
    if table is None:
        if language != "zh-Hant":
            return {}
        table = _TRANSLATIONS[language] = _load_hant()
        _KNOWN_KEYS = _KNOWN_KEYS | frozenset(table)
    return table

# All presentation paths share this cache and the existing settings key.
_CURRENT_LANGUAGE_CACHE: str | None = None


def current_language() -> str:
    global _CURRENT_LANGUAGE_CACHE
    if _CURRENT_LANGUAGE_CACHE is None:
        settings, _path, _warnings = load_runtime_settings()
        value = str(settings.get("ui", {}).get("language", "zh"))
        _CURRENT_LANGUAGE_CACHE = value if value in SUPPORTED_LANGUAGES else "zh"
    return _CURRENT_LANGUAGE_CACHE


def invalidate_language_cache() -> None:
    global _CURRENT_LANGUAGE_CACHE
    _CURRENT_LANGUAGE_CACHE = None


def save_language(language: str) -> None:
    global _CURRENT_LANGUAGE_CACHE
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported UI language: {language}")
    settings, _path, _warnings = load_runtime_settings()
    settings.setdefault("ui", {})["language"] = language
    save_runtime_settings(settings)
    _CURRENT_LANGUAGE_CACHE = language
    from .i18n_widgets import refresh_application
    refresh_application(language)


_HANT_CHARS: dict[str, str] | None = None


def _hant_fallback(text: str) -> str:
    """Character-level 繁體 for a UI string added after zh-Hant.json was generated."""
    global _HANT_CHARS
    if _HANT_CHARS is None:
        try:
            with (LOCALE_DIR / "zh-Hant-chars.json").open(encoding="utf-8") as stream:
                _HANT_CHARS = dict(json.load(stream))
        except (OSError, ValueError):
            _HANT_CHARS = {}
    return "".join(_HANT_CHARS.get(ch, ch) for ch in text)


def translate(text: str, language: str | None = None) -> str:
    language = current_language() if language is None else language
    table = language_table(language)
    if language == "zh-Hant" and text not in table and text in _KNOWN_KEYS:
        # Only known UI source strings are converted; user content never is.
        return _hant_fallback(text)
    return table.get(text, text)


def ui_literal(text: str, language: str | None = None) -> str:
    """Program-written UI text that is not one catalog key (2026-10-14).

    For strings the program composes from its own literals (a catalog help
    joined with a provider note, the unit in ``f"{n} 个词库"``): the table when
    it has the text, otherwise for 繁體中文 the character conversion. Never pass
    user content (subtitles, file names, custom names).
    """
    language = current_language() if language is None else language
    table = language_table(language)
    if text in table:
        return table[text]
    return _hant_fallback(text) if language == "zh-Hant" else text


class TranslatedText(str):
    """A display value carrying its source through legacy helper functions."""
    def __new__(cls, source, arguments):
        value = translate(source)
        if arguments:
            value = value.format(**render_arguments(arguments))
        result = str.__new__(cls, value)
        result.source, result.arguments = source, arguments
        return result

    def __reduce__(self):
        return (TranslatedText, (self.source, self.arguments))


def join_text(parts, separator=" · "):
    values = {"part"+str(i): part for i, part in enumerate(parts)}
    return TranslatedText(separator.join("{"+key+"}" for key in values), values)


def render_arguments(arguments, language=None):
    language = current_language() if language is None else language
    return {key: (translate(value.source, language).format(**render_arguments(value.arguments, language))
                  if isinstance(value, TranslatedText) else value)
            for key, value in arguments.items()}


def tr(source: str, **arguments) -> str:
    """Translate one complete sentence, keeping user parameters opaque."""
    return TranslatedText(source, arguments)


def apply_ui_language(root, language: str | None = None) -> None:
    from .i18n_widgets import apply, install_language_events
    install_language_events()
    apply(root, current_language() if language is None else language)


from .i18n_widgets import bind_text, user_text
