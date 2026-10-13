"""UI language overlay (zh / en / ja).

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
TRANSLATED_LANGUAGES = ("en", "ja")
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


_TRANSLATIONS: dict[str, dict[str, str]] = {
    language: _load_locale(language) for language in TRANSLATED_LANGUAGES
}

_KNOWN_KEYS = frozenset().union(*(table.keys() for table in _TRANSLATIONS.values()))

# All presentation paths share this cache and the existing settings key.
_CURRENT_LANGUAGE_CACHE: str | None = None


def current_language() -> str:
    global _CURRENT_LANGUAGE_CACHE
    if _CURRENT_LANGUAGE_CACHE is None:
        settings, _path, _warnings = load_runtime_settings()
        value = str(settings.get("ui", {}).get("language", "zh"))
        _CURRENT_LANGUAGE_CACHE = value if value in ("zh", "en", "ja") else "zh"
    return _CURRENT_LANGUAGE_CACHE


def invalidate_language_cache() -> None:
    global _CURRENT_LANGUAGE_CACHE
    _CURRENT_LANGUAGE_CACHE = None


def save_language(language: str) -> None:
    global _CURRENT_LANGUAGE_CACHE
    if language not in ("zh", "en", "ja"):
        raise ValueError(f"Unsupported UI language: {language}")
    settings, _path, _warnings = load_runtime_settings()
    settings.setdefault("ui", {})["language"] = language
    save_runtime_settings(settings)
    _CURRENT_LANGUAGE_CACHE = language
    from .i18n_widgets import refresh_application
    refresh_application(language)


def translate(text: str, language: str | None = None) -> str:
    language = current_language() if language is None else language
    return _TRANSLATIONS.get(language, {}).get(text, text)


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
