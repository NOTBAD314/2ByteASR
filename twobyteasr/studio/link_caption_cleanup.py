"""AI 清理 opened after a link download.

2026-10-26: the work runs in ``ai_cleanup_dialog`` (one page: local tidy and AI
batches, in the background). This module keeps the download's light defaults
and the name tests replace (``request_text_cleanup``).
"""
from __future__ import annotations

from .ai_cleanup_dialog import AiCleanupDialog
from .studio_text_tools import request_text_cleanup  # noqa: F401  (the background run calls it through here)
from ..i18n import bind_text


def start_download_cleanup(dialog):
    dialog._do_ai_preview()


class LinkCaptionCleanupDialog(AiCleanupDialog):
    """Light defaults: remove labels, re-break by words, terms and punctuation."""

    _download_defaults = True

    def __init__(self, page, parent=None):
        super().__init__(page, parent)
        bind_text(self.status_label, "默认：删标注、按词重排，AI 只改专名、错字与标点；点「开始整理」后逐条确认。")
