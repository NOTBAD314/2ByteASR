"""Local translation text split from ADR 0142 (2026-10-24 port: one implementation).

Codex's caption-marks round carried its own copy of the daily's ``split_translation_text``
with a grapheme-boundary guard; the guard now lives in ``subtitle_translation`` and this
name stays for the round's callers (``caption_translation_splice``).
"""
from .subtitle_translation import split_translation_text  # noqa: F401
