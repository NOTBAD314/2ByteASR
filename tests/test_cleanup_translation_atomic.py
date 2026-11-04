"""The cleanup translation entry keeps source text and undoes result + display once."""
from __future__ import annotations

import copy
import json
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.subtitle_rules import subtitle_translation as translation
from tests.test_caption_tidy import imported_as_before


class FixedProvider:
    provider_id, model = "fixed-replay", "fixed-translation"
    def __init__(self): self.calls = 0
    def structured_complete(self, messages, schema=None, **kwargs):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        return {"items": [dict(id=cue_id, translation="固定回放译文") for cue_id in payload["output_ids"]]}


@pytest.fixture
def page(monkeypatch):
    app = QApplication.instance() or QApplication([])
    from twobyteasr.caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.providers import ai_providers, llm_config
    from twobyteasr.studio import studio_translation_dialog
    provider = FixedProvider()
    monkeypatch.setattr(ai_providers, "provider_for_stage", lambda *a, **k: provider)
    monkeypatch.setattr(llm_config, "text_ai_key_missing", lambda *a, **k: False)
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY, "selection", lambda *a, **k: SimpleNamespace(
        service="fixed-replay", provider="fixed-replay", model=provider.model,
        transport="fixture", credential_ready=True, credential_source="fixture"))
    monkeypatch.setattr(studio_translation_dialog, "load_cache", lambda: {})
    monkeypatch.setattr(studio_translation_dialog, "save_cache", lambda _: None)
    studio = SubtitleStudioPage()
    studio.project = imported_as_before()
    studio._test_provider = provider
    yield studio
    dialog = getattr(studio, "_translation_dialog", None)
    if dialog is not None:
        dialog.close()
    studio.close_page()
    studio.close()
    app.processEvents()


def wait_done(dialog):
    deadline = time.monotonic() + 10
    while dialog._thread is not None and time.monotonic() < deadline:
        time.sleep(.01)
        QApplication.processEvents()
    assert dialog._thread is None


def test_fixed_provider_translation_apply_undo_redo_and_save_reopen(page, tmp_path):
    from twobyteasr.caption_style.bilingual_layout import settings_from_state
    from twobyteasr.projects.studio_project import save_project, load_project
    ids = [page.project.cues[1].id, page.project.cues[2].id]
    original = copy.deepcopy(page.project.cues)
    page._open_translation_dialog(scope="selected", cue_ids=ids, target="zh-Hans")
    dialog = page._translation_dialog
    before = translation.snapshot(page.project)
    revision = state_for(page.project).revision
    QTest.mouseClick(dialog.start_button, Qt.LeftButton)
    wait_done(dialog)
    assert page._test_provider.calls == 1
    assert len(page.project.generation_metadata["translations"]) == 2
    assert page.project.cues == original
    assert settings_from_state(page.project.studio_state).mode == "bilingual"
    assert page.undo_stack.count() == 1 and state_for(page.project).revision == revision + 1
    after = translation.snapshot(page.project)
    page.undo_stack.undo()
    assert translation.snapshot(page.project) == before
    assert settings_from_state(page.project.studio_state).mode == "original"
    assert not page.timeline.bilingual
    page.undo_stack.redo()
    assert translation.snapshot(page.project) == after
    assert settings_from_state(page.project.studio_state).mode == "bilingual" and page.timeline.bilingual
    path = save_project(page.project, tmp_path / "translated.2byteproj")
    reopened = load_project(path)
    assert reopened.cues == original and translation.snapshot(reopened) == after
    assert settings_from_state(reopened.studio_state).mode == "bilingual"


def test_translation_preparation_checks_live_revision_without_mutating(page):
    source = translation.translation_source(page.project)
    cue = source.cues[1]
    result = translation.translate(source, [cue.id], FixedProvider(), target="zh-Hans")
    before = copy.deepcopy(page.project.generation_metadata)
    first, after = translation.apply_translation_result(page.project, result, commit=False)
    assert first != after and page.project.generation_metadata == before
    assert not page.undo_stack.count()
    stale = translation.translate(source, [cue.id], FixedProvider(), target="zh-Hans")
    state_for(page.project).content_revisions[cue.id] = 99
    first, after = translation.apply_translation_result(page.project, stale, commit=False)
    assert first == after and stale.discarded[cue.id] == "revision_changed"
    assert page.project.generation_metadata == before


def test_translation_push_failure_restores_original_and_no_display_entry(page, monkeypatch):
    page._open_translation_dialog(scope="selected", cue_ids=[page.project.cues[1].id], target="zh-Hans")
    dialog = page._translation_dialog
    before = translation.snapshot(page.project)
    display_before = copy.deepcopy(page.project.studio_state)
    original = translation.restore_snapshot
    def fail_after_mutation(project, state):
        original(project, state)
        raise RuntimeError("injected translation commit failure")
    monkeypatch.setattr(translation, "restore_snapshot", fail_after_mutation)
    QTest.mouseClick(dialog.start_button, Qt.LeftButton)
    wait_done(dialog)
    assert translation.snapshot(page.project) == before
    assert page.project.studio_state == display_before
    assert page.undo_stack.count() == 0
    assert "未写入" in dialog.status.text()


@pytest.mark.parametrize("with_success", [False, True])
def test_failed_translation_records_refresh_without_spurious_display_change(page, monkeypatch, with_success):
    from twobyteasr.caption_style.bilingual_layout import settings_from_state
    ids = [page.project.cues[1].id]
    if with_success:
        ids.append(page.project.cues[2].id)
    page._open_translation_dialog(scope="selected", cue_ids=ids, target="zh-Hans")
    dialog = page._translation_dialog
    result = translation.translate(translation.translation_source(page.project), ids, FixedProvider(), target="zh-Hans")
    failed_id = ids[-1]
    result.translations.pop(failed_id)
    result.failed[failed_id] = "fixture translation failure"
    before = translation.snapshot(page.project)
    original = copy.deepcopy(page.project.cues)
    observed, diagnostics = [], []
    state_for(page.project).subscribe(observed.append)
    monkeypatch.setattr("twobyteasr.diagnostics.studio_events.background_result",
                        lambda *args, **kwargs: diagnostics.append(kwargs))
    dialog._on_finished(result)
    assert page.project.cues == original
    assert translation.cue_status(page.project, failed_id) == "failed"
    assert len(observed) == 1 and observed[0].affected_cue_ids == frozenset(ids)
    assert diagnostics[-1]["applied_count"] == int(with_success)
    expected_mode = "bilingual" if with_success else "original"
    assert settings_from_state(page.project.studio_state).mode == expected_mode
    assert page.timeline.bilingual is with_success
    assert page.undo_stack.count() == 1
    after = translation.snapshot(page.project)
    page.undo_stack.undo()
    assert translation.snapshot(page.project) == before
    assert settings_from_state(page.project.studio_state).mode == "original"
    page.undo_stack.redo()
    assert translation.snapshot(page.project) == after
    assert settings_from_state(page.project.studio_state).mode == expected_mode
