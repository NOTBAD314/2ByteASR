"""2026-11-22 (user, 1 h stream): proofread suggestions arrived over minutes and
one deleted term cleared all of them (55 → 0)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_glossary_proofread import APP, _close, _library, _page, _row, _save, _wait  # noqa: E402,F401


def test_a_long_transcript_is_matched_in_chunks_and_a_term_edit_keeps_the_rest(tmp_path):
    import subtitle_core as legacy
    from twobyteasr.glossary.glossary_proofread import _ReviewThread
    from twobyteasr.projects.studio_project import load_project
    identity = _library("分批检查", ("autumn", "Autumn"), ("CHIOCHOO", "CHICHOO"))
    cues = []
    for number in range(200):
        text = "还是在等autumn出结果" if number % 2 else "而且CHIOCHOO能奶自己"
        cues.append((f"c{number}", number*1000, number*1000+900, text))
    path = _save(tmp_path, "chunks", cues, glossary_ids=[identity])
    assert len(cues) > _ReviewThread.LOCAL_CHUNK
    page = _page()
    partials = []
    original = _ReviewThread.__init__

    def counting(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.partial.connect(lambda _result, chunk: partials.append(len(chunk)))

    _ReviewThread.__init__ = counting
    try:
        page.open_task(str(path), load_project(path))
        assert _wait(page, 60)
        assert partials and sum(partials) == len(cues) and len(partials) >= 2
        replacements = lambda cue_id: {i["replacement"] for i in _row(page, cue_id)["issues"] if not i["checked"]}
        assert any("CHICHOO" in r for r in replacements("c0"))
        assert any("Autumn" in r for r in replacements("c1"))
        resets = []
        page.term_list.model().modelReset.connect(lambda: resets.append(True))
        page.term_filter.setText("Autumn")
        assert any(page.term_list.item(i).isHidden() for i in range(page.term_list.count()))
        page.term_filter.clear()
        assert not resets
        assert all(not page.term_list.item(i).isHidden() for i in range(page.term_list.count()))
        # Delete the Autumn term: its proposals go at once, CHICHOO stays.
        from PySide6.QtCore import Qt
        from twobyteasr.glossary.term_editing import edit_term
        item = next(page.term_list.item(i) for i in range(page.term_list.count())
                    if page.term_list.item(i).data(Qt.ItemDataRole.UserRole) == "Autumn")
        record = item.data(Qt.ItemDataRole.UserRole + 1)
        page._term_saved(edit_term(legacy, record, delete=True))
        assert not any("Autumn" in r for r in replacements("c1"))
        assert any("CHICHOO" in r for r in replacements("c0"))  # not cleared while the rematch runs
        assert _wait(page, 60)
        assert any("CHICHOO" in r for r in replacements("c0"))
        assert not any("Autumn" in r for r in replacements("c1"))
    finally:
        _ReviewThread.__init__ = original
        _close(page)
