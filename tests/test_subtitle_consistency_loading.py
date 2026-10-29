import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr.caption_style.word_animation import build_word_animation
from twobyteasr.projects.subtitle_consistency import validate_project
from twobyteasr.recognition import cue_word_alignment as alignment
from twobyteasr.timeline.studio_caption_timeline import recover_caption_words

FIXTURES = Path(__file__).parent / "fixtures" / "subtitle_consistency"


def project(n=40, edited=True):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    original = "啊" * n
    text = original[:n//2] + "新" + original[n//2+1:] if edited else original
    cue = StudioCue("cue", 0, n * 10, text, evidence_refs=["segment"])
    words = [dict(text="啊", start_ms=i*10, end_ms=(i+1)*10,
                  char_start=i, char_end=i+1, evidence_ref="segment") for i in range(n)]
    receipt = dict(text=original, words=words, word_alignment="exact_token_text",
                   evidence_clock_offset_ms=0, source_cue_id="cue")
    return SubtitleProject(media=StudioMedia(path="",duration_ms=n*10), cues=[cue],
        asr_evidence={"segment":{"words":[dict(text="啊", start_ms=i*10, end_ms=(i+1)*10) for i in range(n)]}},
        render_settings={"_cue_domain":"timeline"},
        studio_state={"caption_timeline":{"version":1, "source_archive":[{"id":"cue"}],
                                          "instances":{"cue":receipt}}})


def test_continuous_preview_never_fuzzy_aligns_a_changed_receipt(monkeypatch):
    p = project(3000)
    before = copy.deepcopy(p.studio_state)
    monkeypatch.setattr(alignment, "_aligned", lambda *a: pytest.fail("implicit realignment"))
    for i in range(20):
        p.cues[0].text += "改"
        plan = build_word_animation(p, p.cues[0], effect={"word_highlight":{"type":"karaoke_highlight"}})
        assert not plan["spans"] and plan["status"] == "stale_word_alignment"
    assert p.studio_state == before


def test_load_recovery_never_fuzzy_aligns_manual_edits(monkeypatch):
    p = project()
    before = copy.deepcopy(p.studio_state)
    monkeypatch.setattr(alignment, "_aligned", lambda *a: pytest.fail("implicit recovery alignment"))
    assert recover_caption_words(p, allow_realign=False) == 0
    assert p.studio_state == before


def test_explicit_alignment_remains_available_and_reuses_only_text_opcodes(monkeypatch):
    p = project()
    calls = []
    original = alignment.difflib.SequenceMatcher
    def observe(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    alignment._alignment_opcodes.cache_clear()
    monkeypatch.setattr(alignment.difflib, "SequenceMatcher", observe)
    words, reason = alignment.cue_words(p, p.cues[0])
    assert words and reason == "derived_term_source_span"
    shifted = copy.deepcopy(p)
    for word in shifted.studio_state["caption_timeline"]["instances"]["cue"]["words"]:
        word["start_ms"] += 100
        word["end_ms"] += 100
    shifted.cues[0].start_ms += 100
    shifted.cues[0].end_ms += 100
    second, _ = alignment.cue_words(shifted, shifted.cues[0])
    assert len(calls) == 1
    assert second[0].start_ms == words[0].start_ms + 100


def test_pathological_repeated_text_has_bounded_alignment_cost(monkeypatch):
    p = project(3000)
    monkeypatch.setattr(alignment.difflib, "SequenceMatcher",
                        lambda *a, **kw: pytest.fail("unbounded fuzzy matcher"))
    assert alignment.cue_words(p, p.cues[0]) == ((), "alignment_complexity_limit")


def test_exact_long_repeated_text_keeps_measured_timing(monkeypatch):
    p = project(3000, edited=False)
    monkeypatch.setattr(alignment.difflib, "SequenceMatcher",
                        lambda *a, **kw: pytest.fail("exact text used fuzzy matching"))
    words, reason = alignment.cue_words(p,p.cues[0])
    assert len(words) == 3000 and reason == "exact_token_text"
    assert words[-1].end_ms == 30000


@pytest.mark.parametrize("change,code", [
    ({"char_end":100000}, "word_index_invalid"),
    ({"start_ms":float("inf")}, "word_time_invalid"),
    ({"text":"错"}, "word_text_mismatch"),
    ({"evidence_ref":None}, "word_structure_invalid"),
    ({"evidence_ref":"missing"}, "word_source_missing"),
])
def test_same_text_invalid_receipt_warns_and_is_not_rendered_as_measured(change,code):
    p=project(5, edited=False)
    p.studio_state["caption_timeline"]["instances"]["cue"]["words"][0].update(change)
    result=validate_project(p)
    assert result.ok and code in {issue.code for issue in result.warnings}
    assert alignment.cue_words(p,p.cues[0],allow_realign=False) == ((),code)


def test_invalid_source_word_times_are_warning_without_blocking_sentence_srt():
    p=project()
    p.asr_evidence["segment"]["words"][0]["end_ms"]=float("nan")
    result=validate_project(p)
    assert result.ok and "source_word_time_invalid" in {i.code for i in result.warnings}


def test_boundary_check_is_not_scheduled_by_plain_text_changes(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    import twobyteasr.projects.subtitle_consistency as consistency
    app=QApplication.instance() or QApplication([])
    original=consistency.validate_project
    calls=[]
    def observe(*args,**kwargs):
        calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(consistency,"validate_project",observe)
    page=SubtitleStudioPage()
    monkeypatch.setattr(page,"_generate_waveform",lambda *a,**kw:None)
    page.open_project(FIXTURES/"edited_stale_words.2byteproj")
    app.processEvents()
    assert page.project and page.project.cues[0].text=="手動保留的新文字🙂"
    assert page._subtitle_consistency_result.ok
    assert "字级" in page.save_state.text()
    count=len(calls)
    for _ in range(5):
        page.cue_text.insertPlainText("改")
    assert len(calls)==count
    page.session.undo_stack.setClean()
    page.close_page(); page.deleteLater(); app.processEvents()


@pytest.mark.parametrize("name", ["broken_source_reference","invalid_sentence_time"])
def test_bad_load_preserves_previous_session_and_file(tmp_path, monkeypatch, name):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.projects.studio_project import save_project
    import twobyteasr.projects.subtitle_consistency_ui as ui
    app=QApplication.instance() or QApplication([])
    page=SubtitleStudioPage()
    current=project(10,edited=False)
    page.project=current
    page.project_path=tmp_path/"working.2byteproj"
    save_project(current,page.project_path)
    source=tmp_path/(name+".2byteproj")
    source.write_bytes((FIXTURES/source.name).read_bytes())
    before=source.read_bytes()
    shown=[]
    monkeypatch.setattr(ui,"show_load_failure",lambda *args:shown.append(args))
    page.project_controller.open_project(source,single_shot_fn=lambda *_:None,skip_dirty_guard=True)
    assert len(shown)==1
    assert page.project is current
    assert page.project_path==tmp_path/"working.2byteproj"
    assert source.read_bytes()==before
    page.close_page();page.deleteLater();app.processEvents()

