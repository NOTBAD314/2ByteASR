"""A delayed translation must never enter another project's undo history."""
from types import SimpleNamespace
import copy
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.subtitle_rules.subtitle_translation import TranslationResult, TranslatedItem, source_sha


@pytest.mark.parametrize('mode', ['switch', 'close', 'new_session'])
@pytest.mark.parametrize('atomic_display', [False, True])
def test_late_result_after_project_switch_or_close_is_not_applied(monkeypatch, mode, atomic_display):
    app = QApplication.instance() or QApplication([])
    from twobyteasr.caption_design import studio_ai
    from twobyteasr.studio.studio_translation_dialog import SubtitleTranslationDialog
    monkeypatch.setattr(studio_ai.GLOBAL_PROVIDER_REGISTRY, 'settings', lambda: (_ for _ in ()).throw(RuntimeError('no service')))
    monkeypatch.setattr('twobyteasr.studio.studio_bilingual.apply_display', lambda *a, **k: None)
    original = SubtitleProject(media=StudioMedia(''), cues=[StudioCue('c0', 0, 1000, 'Hello')])
    original.validate()
    page = SimpleNamespace(project=original, selected_cue_ids=lambda: ['c0'], undo_stack=QUndoStack(),
                           session=SimpleNamespace(generation=7))
    dialog = SubtitleTranslationDialog(page, atomic_display=atomic_display)
    before = copy.deepcopy(original.generation_metadata)
    other = SubtitleProject(media=StudioMedia(''), cues=[StudioCue('c0', 0, 1000, 'New project')])
    other.validate()
    if mode == 'close': page._close_requested = True
    elif mode == 'new_session': page.session.generation += 1
    else: page.project = other
    result = TranslationResult('zh-Hans', 'offline-fixture', 'offline-fixture', sources={'c0':'Hello'},
        translations={'c0':TranslatedItem('c0', '你好', 'Hello', source_sha('Hello'), '')})
    try:
        dialog._on_finished(result)
        assert page.undo_stack.count() == 0
        assert original.generation_metadata == before
        assert not other.generation_metadata.get('translations')
    finally:
        dialog.deleteLater()
