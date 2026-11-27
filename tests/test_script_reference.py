"""Tests for Task 05: reference-script localized homophone diffing, AI reference
proofreading, inline glossary capture, Studio/Home wizard integration, and
100% backward compatibility of ``整稿替换``."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QTextCursor, QUndoStack
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.recognition.script_reference import (
    ReferenceFix,
    ai_diff_script_against_cues,
    apply_reference_fixes_to_cues,
    diff_script_against_cues,
    extract_specified_terms,
)

BANNED_JARGON = ("沉淀", "质心", "双半段自洽", "置信区", "信任分级", "生成器")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_project(texts=None):
    texts = texts or [
        "哎呀兄弟们今天去至东国看看",
        "哈哈哈这波操作太下饭了我先喝口水",
        "杰风大招一开直接起飞哈哈哈",
        "兄弟们今天大家一直在这里聊时间的问题",
        "这张图是生海明主，欧闷去封烟",
        "拍蒙别跑啊快回至东",
        "我们在玩 valorant 排位赛",
    ]
    cues = [
        StudioCue(
            id=f"c{idx + 1}",
            start_ms=idx * 2500,
            end_ms=idx * 2500 + 2100,
            text=text,
            original_text=text,
            speaker_id="S00" if idx % 2 == 0 else "S01",
            style_id="style_main" if idx == 0 else "default",
            effect_id="pop" if idx == 2 else "none",
        )
        for idx, text in enumerate(texts)
    ]
    project = SubtitleProject(
        media=StudioMedia(path="synthetic.mp4", duration_ms=60_000),
        cues=cues,
        speakers=[StudioSpeaker("S00", "主播"), StudioSpeaker("S01", "嘉宾")],
    )
    project.validate()
    project.generation_metadata["language"] = {"code": "zh"}
    return project


REFERENCE_BIO = """
参考资料与角色设定：
1. 捷风：擅长风系位移技能的决斗者。
2. 至冬：提瓦特七国之一的冰雪国度，愚人众所在地。
3. 深海明珠：水下穹顶地图。
4. 欧门：暗影控场角色。
5. 派蒙：旅行者身边的应急食品向导。
今天我们大家一直在讨论时间安排，也会打几把 Valorant 排位。
"""


def test_diff_script_against_cues_catches_homophones_and_preserves_improvisation():
    project = _make_project()
    result = diff_script_against_cues(project.cues, REFERENCE_BIO, language="zh")

    by_cue = {}
    for fix in result.fixes:
        by_cue.setdefault(fix.cue_id, []).append((fix.heard, fix.reference))

    # Localized proper-noun homophones caught accurately even out of order
    assert ("至东", "至冬") in by_cue.get("c1", [])
    assert ("杰风", "捷风") in by_cue.get("c3", [])
    assert ("生海明主", "深海明珠") in by_cue.get("c5", [])
    assert ("欧闷", "欧门") in by_cue.get("c5", [])
    assert ("拍蒙", "派蒙") in by_cue.get("c6", [])
    assert ("至东", "至冬") in by_cue.get("c6", [])
    assert ("valorant", "Valorant") in by_cue.get("c7", [])

    # Purely improvised banter & common everyday words are NEVER touched
    assert "c2" not in by_cue
    assert "c4" not in by_cue

    # Aggregated term candidates count repeated pairs and exclude single-char/stopword junk
    by_pair = {(row["from"], row["to"]): row for row in result.term_candidates}
    assert by_pair[("至东", "至冬")]["count"] == 2
    assert by_pair[("杰风", "捷风")]["count"] == 1
    assert by_pair[("生海明主", "深海明珠")]["count"] == 1
    assert all(len(row["from"]) >= 2 for row in result.term_candidates)

    # Applying fixes preserves all improvised words around the corrected tokens
    updates = apply_reference_fixes_to_cues(project.cues, result.fixes)
    assert updates["c1"] == "哎呀兄弟们今天去至冬国看看"
    assert updates["c3"] == "捷风大招一开直接起飞哈哈哈"
    assert updates["c5"] == "这张图是深海明珠，欧门去封烟"
    assert updates["c6"] == "派蒙别跑啊快回至冬"
    assert updates["c7"] == "我们在玩 Valorant 排位赛"
    assert "c2" not in updates and "c4" not in updates


def test_diff_script_against_cues_plain_prose_contextual_match():
    cues = [
        {"id": "k1", "text": "今天我们前往至东国寻找愚人众执行官，哈哈太期待了"},
        {"id": "k2", "text": "哇塞打架了快跑啊"},
    ]
    prose = "今天我们前往至冬国寻找愚人众执行官，大家做好准备。"
    result = diff_script_against_cues(cues, prose, language="zh")
    assert any(f.cue_id == "k1" and f.heard == "至东" and f.reference == "至冬" for f in result.fixes)
    # Must NOT turn improvised "打架" into "大家"
    assert all(f.cue_id != "k2" for f in result.fixes)


def test_diff_script_against_cues_respects_japanese_kanji_and_kana_rules():
    cues = [
        {"id": "j1", "text": "きょうはげーむをやります"},
        {"id": "j2", "text": "ここは市です"},
    ]
    ref = "今日はゲームをやります\nここは是です"
    result = diff_script_against_cues(cues, ref, language="ja")
    assert any(f.cue_id == "j1" and f.heard == "げーむ" and f.reference == "ゲーム" for f in result.fixes)
    # Japanese kanji 市 vs 是 share Chinese reading shi, must NOT match under language='ja'
    assert all(f.cue_id != "j2" for f in result.fixes)


def test_extract_specified_terms_reuses_dangerous_single_char_guard():
    cands = extract_specified_terms(
        "杰风 -> 捷风\n大 -> 打\n深海明珠（生海明主）",
        selected_words=["至冬", "的", "拍蒙 -> 派蒙"],
        pairs=[{"from": "至东", "to": "至冬", "count": 3}, ("我", "握")],
    )
    by_pair = {(c.source, c.target): c for c in cands}

    assert by_pair[("杰风", "捷风")].checked is True and not by_pair[("杰风", "捷风")].dangerous
    assert by_pair[("生海明主", "深海明珠")].checked is True
    assert by_pair[("至冬", "至冬")].checked is True and not by_pair[("至冬", "至冬")].is_alias
    assert by_pair[("拍蒙", "派蒙")].checked is True
    assert by_pair[("至东", "至冬")].checked is True and "3 处" in by_pair[("至东", "至冬")].note

    # Dangerous single-char aliases and common single-char terms default to unchecked
    assert by_pair[("大", "打")].dangerous is True and by_pair[("大", "打")].checked is False
    assert by_pair[("我", "握")].dangerous is True and by_pair[("我", "握")].checked is False
    assert by_pair[("的", "的")].dangerous is True and by_pair[("的", "的")].checked is False


def test_ai_diff_script_against_cues_filters_unsafe_rewrites():
    cues = [
        {"id": "c1", "text": "哎呀我去，这波去至东国找杰风"},
        {"id": "c2", "text": "哈哈笑死我了这操作太下饭了咱们先喝口水"},
    ]

    class _FakeProvider:
        def structured_complete(self, messages, schema, **kwargs):
            assert kwargs["stage"] == "polish"
            return {
                "summary": "发现 2 处专名错字",
                "fixes": [
                    {"cue_id": "c1", "heard": "至东", "reference": "至冬", "confidence": 0.95, "reason": "地名"},
                    {"cue_id": "c1", "heard": "杰风", "reference": "捷风", "confidence": 0.93, "reason": "角色名"},
                    # Illegal full-sentence rewrite of improvised banter — must be rejected
                    {
                        "cue_id": "c2",
                        "heard": "哈哈笑死我了这操作太下饭了咱们先喝口水",
                        "reference": "现在暂停休息",
                        "confidence": 0.9,
                    },
                    # Illegal single-char function word swap — must be rejected
                    {"cue_id": "c2", "heard": "了", "reference": "啦", "confidence": 0.8},
                ],
            }

    result = ai_diff_script_against_cues(cues, REFERENCE_BIO, {}, provider=_FakeProvider())
    assert [(f.cue_id, f.heard, f.reference) for f in result.fixes] == [
        ("c1", "至东", "至冬"),
        ("c1", "杰风", "捷风"),
    ]
    assert {(r["from"], r["to"]) for r in result.term_candidates} == {("至东", "至冬"), ("杰风", "捷风")}


def test_apply_reference_fixes_is_single_undo_step_and_preserves_metadata(qapp):
    from twobyteasr.studio.studio_script_match import apply_reference_fixes

    project = _make_project()
    before_cues = copy.deepcopy(project.cues)
    result = diff_script_against_cues(project.cues, REFERENCE_BIO, language="zh")
    stack = QUndoStack()
    changed_hits = []
    page = SimpleNamespace(project=project, undo_stack=stack, _changed=lambda: changed_hits.append(1))

    cmd = apply_reference_fixes(page, result.fixes)
    assert cmd is not None
    assert stack.count() == 1
    assert project.cues[0].text == "哎呀兄弟们今天去至冬国看看"
    assert project.cues[1].text == before_cues[1].text  # improvised cue untouched
    assert project.cues[2].text == "捷风大招一开直接起飞哈哈哈"
    # Timings, speakers, styles, effects remain identical
    for after, before in zip(project.cues, before_cues):
        assert (after.id, after.start_ms, after.end_ms, after.speaker_id, after.style_id, after.effect_id) == (
            before.id, before.start_ms, before.end_ms, before.speaker_id, before.style_id, before.effect_id
        )

    # Single Ctrl+Z restores every cue completely
    stack.undo()
    assert [c.text for c in project.cues] == [c.text for c in before_cues]

    stack.redo()
    assert project.cues[0].text == "哎呀兄弟们今天去至冬国看看"


def test_commit_reference_terms_skips_duplicates_blocks_single_char_and_readable_by_snapshot(monkeypatch, tmp_path):
    import subtitle_core
    from twobyteasr.glossary.quick_term_capture import QuickTermCandidate, commit_candidates
    from twobyteasr.glossary.terminology import snapshot_glossaries

    # Isolate learned_terms.json inside tmp_path so real user data is never touched
    terms_file = tmp_path / "learned_terms.json"
    monkeypatch.setattr(subtitle_core, "LEARNED_TERMS_PATH", str(terms_file))
    if hasattr(subtitle_core, "_LEARNED_TERM_CACHE"):
        monkeypatch.setattr(subtitle_core, "_LEARNED_TERM_CACHE", None, raising=False)

    lib_id = subtitle_core.glossary_catalog()[0]["id"]
    candidates = extract_specified_terms(
        "大 -> 打\n深海明珠（生海明主）",
        selected_words=["至冬"],
        pairs=[{"from": "至东", "to": "至冬", "count": 2}, {"from": "杰风", "to": "捷风", "count": 1}],
    )
    # Dangerous single char is unchecked by default
    danger = next(c for c in candidates if c.source == "大")
    assert danger.dangerous is True and danger.checked is False

    res1 = commit_candidates(subtitle_core, lib_id, candidates, origin="参考文稿")
    assert res1["added"] >= 4
    assert res1["skipped"] == 0

    snap = snapshot_glossaries(subtitle_core, [lib_id])
    ev = snap.evidence()
    mappings = {row["wrong"]: row["correct"] for row in ev["wrong_to_correct_mappings"]}
    assert "至冬" in ev["canonical_terms"]
    assert "捷风" in ev["canonical_terms"]
    assert "深海明珠" in ev["canonical_terms"]
    assert mappings.get("至东") == "至冬"
    assert mappings.get("杰风") == "捷风"
    assert "大" not in mappings

    # Committing the same batch again skips duplicates cleanly with zero error
    res2 = commit_candidates(subtitle_core, lib_id, candidates, origin="参考文稿")
    assert res2["added"] == 0
    assert res2["skipped"] >= 4

    # Attempting to overwrite existing alias target with conflicting canonical skips safely
    conflict_batch = [
        QuickTermCandidate(source="至东", target="别的词", category="参考纠错", checked=True),
        QuickTermCandidate(source="拍蒙", target="派蒙", category="参考纠错", checked=True),
    ]
    res3 = commit_candidates(subtitle_core, lib_id, conflict_batch, origin="参考文稿")
    assert res3["added"] == 1
    assert res3["skipped"] == 1
    assert res3["warnings"]
    snap2 = snapshot_glossaries(subtitle_core, [lib_id])
    mappings2 = {row["wrong"]: row["correct"] for row in snap2.evidence()["wrong_to_correct_mappings"]}
    assert mappings2.get("至东") == "至冬"
    assert mappings2.get("拍蒙") == "派蒙"


def test_studio_dialog_reference_mode_glossary_and_replace_regression(qapp, monkeypatch, tmp_path):
    import subtitle_core
    from twobyteasr.glossary.terminology import snapshot_glossaries
    from twobyteasr.studio.studio_script_match import open_script_match_dialog

    terms_file = tmp_path / "studio_learned_terms.json"
    monkeypatch.setattr(subtitle_core, "LEARNED_TERMS_PATH", str(terms_file))

    project = _make_project()
    before_texts = [c.text for c in project.cues]
    stack = QUndoStack()
    host = QWidget()
    host.legacy = subtitle_core

    class _FakePage(QWidget):
        def __init__(self):
            super().__init__(host)
            self.project = project
            self.undo_stack = stack
            self.legacy = subtitle_core
            self.runtime_settings = {}
            self._changed = lambda: None

    page = _FakePage()
    seen = {}

    def drive_reference():
        dlg = page._script_match_dialog
        # Verify copy rules: every visible button <= 6 chars & no banned jargon
        for btn in dlg.findChildren(QPushButton):
            txt = btn.text().strip().rstrip("…▾").strip()
            if txt and txt != "×":
                assert len(txt) <= 6, f"Button label too long (>6 chars): {btn.text()!r}"
            for bad in BANNED_JARGON:
                assert bad not in btn.text()

        dlg._set_mode("reference")
        dlg._editor.input.setPlainText(REFERENCE_BIO)

        # Highlight "至冬" inside editor and click 「指定词条」
        cursor = dlg._editor.input.textCursor()
        idx = REFERENCE_BIO.index("至冬")
        cursor.setPosition(idx)
        cursor.setPosition(idx + 2, QTextCursor.MoveMode.KeepAnchor)
        dlg._editor.input.setTextCursor(cursor)
        dlg._editor.pick_term.click()
        seen["picked_count"] = len(dlg._term_panel.candidates())

        # Run local homophone reference diff
        dlg._run_reference_diff()
        seen["ref_rows"] = dlg._ref_table.rowCount()
        seen["cand_count"] = len(dlg._term_panel.candidates())

        # Commit candidates to glossary via panel
        commit_res = dlg._term_panel.commit()
        seen["commit_res"] = commit_res
        seen["lib_id"] = dlg._term_panel.selected_library_id()

        # Apply checked reference fixes
        dlg._accept_reference()

    QTimer.singleShot(0, drive_reference)
    accepted = open_script_match_dialog(page)
    assert accepted is True
    assert seen["picked_count"] == 1
    assert seen["ref_rows"] >= 5
    assert seen["cand_count"] >= 4
    assert seen["commit_res"]["added"] >= 4
    assert project.cues[0].text == "哎呀兄弟们今天去至冬国看看"
    assert project.cues[1].text == before_texts[1]

    snap = snapshot_glossaries(subtitle_core, [seen["lib_id"]])
    mappings = {row["wrong"]: row["correct"] for row in snap.evidence()["wrong_to_correct_mappings"]}
    assert mappings.get("至东") == "至冬"

    # Undo restores original captions
    stack.undo()
    assert [c.text for c in project.cues] == before_texts

    # Regression check: default 整稿替换 mode still replaces all cues & undoes cleanly
    def drive_replace():
        dlg = page._script_match_dialog
        assert dlg._mode_bar.mode() == "replace"
        dlg._editor.input.setPlainText("今天去至冬国看看\n捷风大招起飞")
        dlg._run_preview()
        assert dlg._pages.currentIndex() == 1
        dlg._accept_match()

    QTimer.singleShot(0, drive_replace)
    assert open_script_match_dialog(page) is True
    assert [c.text for c in project.cues] == ["今天去至冬国看看", "捷风大招起飞"]
    stack.undo()
    assert [c.text for c in project.cues] == before_texts
    host.deleteLater()


def test_home_dialog_reference_mode_captures_glossary_and_starts_recognition(qapp, monkeypatch, tmp_path):
    import subtitle_core
    from twobyteasr.app import home_script_match as hsm
    from twobyteasr.glossary.terminology import snapshot_glossaries

    terms_file = tmp_path / "home_learned_terms.json"
    monkeypatch.setattr(subtitle_core, "LEARNED_TERMS_PATH", str(terms_file))
    monkeypatch.setattr(hsm, "timestamp_model_ready", lambda language="zh": (True, ""))
    media = tmp_path / "demo.wav"
    media.write_bytes(b"RIFF")

    class _HomeWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.media_paths = [str(media)]
            self.legacy = subtitle_core
            self.legacy.RUNTIME_SETTINGS.setdefault("glossary", {})["enabled_glossary_ids"] = []
            self.started = 0
            self.chips_refreshed = 0

        def _enabled_glossary_ids(self):
            return list(self.legacy.RUNTIME_SETTINGS.get("glossary", {}).get("enabled_glossary_ids", []))

        def _refresh_glossary_chips(self):
            self.chips_refreshed += 1

        def _start_run(self):
            self.started += 1

        def open_studio_project(self, *_a, **_kw):
            pass

        def _open_model_workshop(self):
            pass

    window = _HomeWindow()
    seen = {}

    def drive():
        dlg = window._home_script_match_dialog
        dlg._set_mode("reference")
        dlg._script.setPlainText("杰风 -> 捷风\n至东 -> 至冬\n深海明珠（生海明主）")
        dlg._term_panel.add_specified_text(dlg._script.toPlainText())
        seen["lib_id"] = dlg._term_panel.selected_library_id()
        dlg._begin_reference()

    QTimer.singleShot(0, drive)
    hsm.open_home_script_match(window)

    assert window.started == 1
    assert window.chips_refreshed >= 1
    assert seen["lib_id"] in window._enabled_glossary_ids()
    assert hasattr(window, "_pending_script_reference")
    assert "捷风" in window._pending_script_reference["text"]
    snap = snapshot_glossaries(subtitle_core, [seen["lib_id"]])
    mappings = {row["wrong"]: row["correct"] for row in snap.evidence()["wrong_to_correct_mappings"]}
    assert mappings.get("杰风") == "捷风"
    assert mappings.get("至东") == "至冬"
    window.deleteLater()
