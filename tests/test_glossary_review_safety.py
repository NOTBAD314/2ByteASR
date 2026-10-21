"""Stale local previews and review lineage use the same immutable snapshot."""
import copy
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QWidget

import subtitle_core as legacy
from twobyteasr.studio.studio_find_replace import FindReplaceDialog
from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.glossary.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry

APP = QApplication.instance() or QApplication([])


class Page(QWidget):
    def __init__(self, project):
        super().__init__()
        self.session = SimpleNamespace(project=project, undo_stack=QUndoStack(), selected_cue_id='a')

    def selected_cue_ids(self):
        return ['a']

    def _changed(self):
        pass

    def _show_studio_hint(self, text):
        pass


def test_local_preview_refuses_case_updated_library(monkeypatch, tmp_path):
    monkeypatch.setattr(legacy, 'LEARNED_TERMS_PATH', str(tmp_path / 'terms.json'))
    monkeypatch.setattr(legacy, 'load_game_profiles', lambda: {})
    legacy.add_learned_mapping('库', 'NameID', 'NameID')
    identity = legacy.resolve_glossary_identity('库')
    project = SubtitleProject(media=StudioMedia(path='isolated.mp4'),
        cues=[StudioCue('a', 100, 1000, 'nameid也没有接住')], glossary_ids=[identity])
    page = Page(project)
    dialog = FindReplaceDialog(page)
    try:
        dialog.tabs.setCurrentIndex(3)
        dialog._do_preview()
        assert dialog.preview.count() == 1
        legacy.edit_learned_mapping(identity, ('NameID', 'NameID'), 'NAMEid', 'NAMEid')
        dialog._do_apply_preview()
        assert project.cues[0].text == 'nameid也没有接住'
        assert page.session.undo_stack.count() == 0
        assert '词库已更新' in dialog.status_label.text()
    finally:
        dialog.close()
        page.close()


def test_review_receipt_identifies_original_project_snapshot(monkeypatch):
    import twobyteasr.providers.asr_provider_snapshot as provider
    import twobyteasr.subtitle_rules.polishing as polish
    monkeypatch.setattr(provider, 'resolve_provider_snapshot', lambda *_a, **_kw:
        SimpleNamespace(public_identity=lambda: {'provider': 'test', 'model': 'test'},
            timeout_policy=SimpleNamespace(total=120)))
    monkeypatch.setattr(polish, 'call_correction_api', lambda rows, *_a, **_kw:
        polish.PolishBatchResult({row.segment_id: row.text for row in rows}))
    original = GlossarySnapshot((GlossaryLibrary('v', '库', 'old', terms=(TermEntry('nameid'),)),))
    current = GlossarySnapshot((GlossaryLibrary('v', '库', 'new', terms=(TermEntry('NameID'),)),))
    project = SubtitleProject(media=StudioMedia(path='isolated.mp4'),
        cues=[StudioCue('a', 100, 1000, 'nameid')],
        generation_metadata={'terminology_snapshot': original.to_dict()})
    result = preview_glossary_correction(project, ['a'], current, {})
    assert result.receipt['parent_snapshot_digest'] == original.digest
    assert result.receipt['snapshot_summary']['snapshot_digest'] == current.digest
    assert result.receipt['parent_snapshot_digest'] != current.digest
    assert result.receipt['local_normalization_count'] == 1
    assert result.receipt['local_normalizations'][0]['acoustic_verified'] is False
    assert result.hits[0].reason == '当前词库本地确认名称规范化（未核验原音）'


def test_cancelled_review_never_invokes_provider(monkeypatch):
    from twobyteasr.recognition.service import CancellationToken, CancelledError
    import twobyteasr.subtitle_rules.polishing as polish
    calls = []
    monkeypatch.setattr(polish, 'call_correction_api', lambda *_a, **_kw: calls.append(True))
    token = CancellationToken()
    token.cancel()
    project = SubtitleProject(media=StudioMedia(path='isolated.mp4'), cues=[StudioCue('a', 100, 1000, '句子')])
    before = copy.deepcopy(project)
    with pytest.raises(CancelledError):
        preview_glossary_correction(project, ['a'], GlossarySnapshot(), {}, cancel_token=token)
    assert not calls
    assert project.cues == before.cues
