"""Bilingual display layout (preview == export), translation commands and recognition-time translation."""
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

import subtitle_core  # noqa: F401  (legacy core first)
from twobyteasr.ass_compiler import compile_ass
from twobyteasr.bilingual_layout import BilingualSettings, companion_id, project_display_cues, settings_from_state
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


def _project(state=None, translations=None):
    return SubtitleProject(media=StudioMedia(path="x.mp4", duration_ms=5000),
                           cues=[StudioCue("1", 0, 2000, "恐ろしいわ すえ恐ろしいわ", speaker_id="S01"),
                                 StudioCue("2", 2000, 3000, "この子ら", speaker_id="S01")],
                           generation_metadata={"translations": translations if translations is not None
                                                else {"1": "好可怕啊，前途堪忧啊"}},
                           studio_state=dict(state or {}))


def _events(project):
    return [line.split(",,", 1)[-1] for line in compile_ass(project).splitlines() if line.startswith("Dialogue")]


def test_modes_and_order():
    assert len(_events(_project())) == 2                                  # original only
    bilingual = _events(_project({"bilingual": {"mode": "bilingual"}}))
    assert len(bilingual) == 3 and any("好可怕啊" in line for line in bilingual)
    translation = _events(_project({"bilingual": {"mode": "translation"}}))
    assert translation[0].endswith("好可怕啊，前途堪忧啊") and translation[1].endswith("この子ら")


def _positions(project):
    cues = {cue.id: cue for cue in project_display_cues(project)}
    original, companion = cues["1"], cues[companion_id("1")]
    return original, companion


def test_translation_first_puts_chinese_above_and_swap_moves_the_original_up():
    original, companion = _positions(_project({"bilingual": {"mode": "bilingual"}}))
    assert companion.transform["position_y"] < (original.transform.get("position_y") or 10**6)
    swapped_original, swapped_companion = _positions(_project({"bilingual": {"mode": "bilingual",
                                                                            "order": "original_first"}}))
    assert swapped_original.transform["position_y"] < swapped_companion.transform["position_y"]
    # Timing, speaker and original text never change.
    assert (swapped_original.start_ms, swapped_original.end_ms, swapped_original.text) == (0, 2000, "恐ろしいわ すえ恐ろしいわ")


def test_separate_font_and_size_for_each_language():
    project = _project({"bilingual": {"mode": "bilingual", "translation_font": "SimHei",
                                      "translation_scale": 1.2, "original_scale": 0.6}})
    original, companion = _positions(project)
    assert companion.appearance_override["font_family"] == "SimHei"
    assert companion.transform["font_size"] > original.transform["font_size"]


def test_old_boolean_switch_still_shows_both_with_old_proportions():
    settings = settings_from_state({"bilingual_mode": True})
    assert settings.mode == "bilingual" and settings.legacy and settings.translation_scale == pytest.approx(0.66)


def test_live_preview_materializes_the_same_display_cues():
    from twobyteasr.caption_playback_cache import materialize_caption_project
    from twobyteasr.studio_revisions import StudioRevisionStore
    project = _project({"bilingual": {"mode": "bilingual"}})
    store = StudioRevisionStore(project)
    live = materialize_caption_project(store.render)
    assert [cue.id for cue in live.cues] == [cue.id for cue in project_display_cues(project)]
    assert "bi:" in store.render.compile_key[-1]


def test_translation_snapshot_command_is_one_undo_step():
    from PySide6.QtGui import QUndoStack
    from twobyteasr.studio_bilingual import ApplyTranslationSnapshotCommand
    from twobyteasr.subtitle_translation import migrate, set_manual, snapshot
    project = _project(translations={})
    migrate(project)
    before = snapshot(project)
    _unused, after = set_manual(project, "1", "好可怕")
    stack = QUndoStack()
    stack.push(ApplyTranslationSnapshotCommand(project, before, after, ("1",)))
    assert project.generation_metadata["translations"] == {"1": "好可怕"}
    stack.undo()
    assert not project.generation_metadata.get("translations")
    stack.redo()
    assert project.generation_metadata["translations"] == {"1": "好可怕"}


class _FakeProvider:
    provider_id, model = "fake", "fake-model"

    def __init__(self):
        self.calls = 0

    def structured_complete(self, messages, schema=None, **kwargs):
        import json
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        items = payload.get("items") or payload.get("cues") or payload.get("lines") or []
        return {"items": [{"id": item["id"], "translation": "译文" + str(item["id"])} for item in items]}

    complete = structured_complete


def test_recognition_translation_writes_records_for_the_project_ids(monkeypatch, tmp_path):
    from twobyteasr import recognition_translation as rt
    monkeypatch.setattr(rt, "cache_path", lambda: tmp_path / "cache.json")
    cues = [SimpleNamespace(cue_id=1, start=0.0, end=1.0, text="怖いわ", speaker="S01"),
            SimpleNamespace(cue_id=1, start=1.0, end=2.0, text="反省", speaker="S01")]
    events = []
    legacy = SimpleNamespace(record_run_event=lambda name, **kw: events.append((name, kw)),
                             add_review_item=lambda *a, **k: events.append(("review", a)))
    context = SimpleNamespace(subtitle_output="bilingual", task_language="ja", translation_script="zh-Hans",
                              game_name="日常", cancellation_token=None)
    added = rt.translate_runtime_cues(cues, context, legacy, provider=_FakeProvider())
    assert set(added["translations"]) == {"1", "1-2"}                 # same ids the project will get
    assert added["translation_records"]["records"]["1"]["source_text"] == "怖いわ"
    context.task_language = "zh"
    assert rt.translate_runtime_cues(cues, context, legacy, provider=_FakeProvider()) == {}


def test_translation_dialog_opens_with_counts_and_without_a_configured_service(monkeypatch):
    from PySide6.QtGui import QUndoStack
    from twobyteasr import studio_ai
    from twobyteasr.studio_translation_dialog import SubtitleTranslationDialog
    monkeypatch.setattr(studio_ai.GLOBAL_PROVIDER_REGISTRY, "settings", lambda: (_ for _ in ()).throw(RuntimeError("none")))
    page = SimpleNamespace(project=_project(), selected_cue_ids=lambda: ["2"], undo_stack=QUndoStack())
    dialog = SubtitleTranslationDialog(page)
    try:
        assert "未翻译" in dialog.counts.text() or "Untranslated" in dialog.counts.text()
        assert not dialog.start_button.isEnabled()            # no service: nothing is sent
        assert dialog.scope_buttons["selected"].isEnabled() and dialog.scope_buttons["pending"].isChecked()
    finally:
        dialog.deleteLater()


def test_compact_layout_keeps_the_visible_gap_from_ink_outline_and_shadow():
    from twobyteasr.bilingual_layout import ink_block
    from twobyteasr.resolved_caption_style import resolve_caption_style
    project = _project({"bilingual": {"mode": "bilingual", "layout": "ink_v1", "gap_ratio": 0.13}})
    cues = {c.id: c for c in project_display_cues(project)}
    original, companion = cues["1"], cues[companion_id("1")]
    oc = resolve_caption_style(project.styles, project.speakers, original, project.style_recipes, 1920)
    cc = resolve_caption_style(project.styles, project.speakers, companion, project.style_recipes, 1920)
    (h_o, _, o_o, _), (h_c, _, o_c, s_c) = ink_block(oc), ink_block(cc)
    gap = 0.13 * max(oc.style.font_size, cc.style.font_size)
    # Chinese above: the space between the translation's ink bottom and the original's ink top.
    inner = (original.transform["position_y"] - h_o) - companion.transform["position_y"]
    assert abs(inner - (o_c + s_c + gap + o_o)) <= 1.0
    # The old evening layout (no "layout" key) is untouched.
    old = {c.id: c for c in project_display_cues(_project({"bilingual": {"mode": "bilingual"}}))}
    assert old["1"].transform.get("position_y") is None or old[companion_id("1")].transform["position_y"] != companion.transform["position_y"]


def test_first_bilingual_choice_is_compact_and_the_compact_command_is_one_undo_step():
    from PySide6.QtGui import QUndoStack
    from twobyteasr.studio_bilingual import apply_compact_layout, apply_display
    page = SimpleNamespace(project=_project(), undo_stack=QUndoStack())
    assert apply_display(page, mode="bilingual")
    assert page.project.studio_state["bilingual"]["layout"] == "ink_v1"
    old = SimpleNamespace(project=_project({"bilingual": {"mode": "bilingual", "gap_ratio": 0.18}}), undo_stack=QUndoStack())
    before = dict(old.project.studio_state["bilingual"])
    assert apply_compact_layout(old)
    assert old.project.studio_state["bilingual"]["layout"] == "ink_v1" and old.undo_stack.count() == 1
    old.undo_stack.undo()
    assert old.project.studio_state["bilingual"] == before


def test_overlapping_speakers_reserve_the_whole_bilingual_group():
    from twobyteasr.bilingual_layout import group_extra_for
    from twobyteasr.subtitle_stacking import initialize_project_layout
    project = SubtitleProject(media=StudioMedia(path="x.mp4", duration_ms=5000),
                              cues=[StudioCue("a", 0, 3000, "一人目の台詞", speaker_id="S01"),
                                    StudioCue("b", 500, 2500, "二人目の台詞", speaker_id="S02")],
                              generation_metadata={"translations": {"a": "第一个人的台词", "b": "第二个人的台词"}},
                              studio_state={"bilingual": {"mode": "bilingual", "layout": "ink_v1", "gap_ratio": 0.13}})
    extra = group_extra_for(project, project.cues[0])
    assert extra > 30
    initialize_project_layout(project)
    ys = sorted(c.transform["initial_layout"]["position_y"] for c in project.cues)
    # The upper group sits above the lower group's translation line, not just above its original.
    assert ys[1] - ys[0] >= extra
