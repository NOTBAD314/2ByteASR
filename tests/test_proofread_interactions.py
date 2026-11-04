"""Regressions for repeated adoption, shared document edits and loading input."""
import copy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget, QMessageBox

from tests.test_proofread_retention import page, APP
from twobyteasr.glossary.glossary_proofread import _issue
from twobyteasr.timeline.studio_commands import BatchReplaceTextCommand
from twobyteasr.studio.studio_find_replace import FindReplaceDialog


def test_same_suggestion_toggles_and_preserves_intervening_edits(page):
    w, p = page
    w._toggle_issue('middle', 0)
    w._edit_committed('later', '另一条手动修改')
    w._edit_committed('middle', '前缀大骨龙和火龙来了后缀')
    w._toggle_issue('middle', 0)
    assert p.cues[0].text == '前缀古龙和火龙来了后缀'
    assert p.cues[1].text == '另一条手动修改'
    assert not w._by_id['middle']['issues'][0]['checked']
    w._undo()
    assert p.cues[0].text == '前缀大骨龙和火龙来了后缀'
    assert w._by_id['middle']['issues'][0]['checked']
    w._redo()
    assert p.cues[0].text == '前缀古龙和火龙来了后缀'
    w._toggle_issue('middle', 0)
    assert p.cues[0].text == '前缀大骨龙和火龙来了后缀'


def test_repeated_words_only_clicked_occurrence_changes(page):
    w, p = page
    w._edit_committed('middle', '古龙和古龙来了')
    row = w._by_id['middle']
    row['issues'] = [_issue('term', (0, 2), '古龙', '大骨龙', checked=False),
                     _issue('term', (3, 5), '古龙', '大骨龙', checked=False)]
    w._apply_filter()
    w._toggle_issue('middle', 1)
    assert p.cues[0].text == '古龙和大骨龙来了'
    w._toggle_issue('middle', 1)
    assert p.cues[0].text == '古龙和古龙来了'
    w._toggle_issue('middle', 0)
    assert p.cues[0].text == '大骨龙和古龙来了'


def test_conflicting_edit_is_not_overwritten(page):
    w, p = page
    w._toggle_issue('middle', 0)
    w._edit_committed('middle', '用户另改和火龙来了')
    count = w._live_stack().count()
    w._toggle_issue('middle', 0)
    assert p.cues[0].text == '用户另改和火龙来了'
    assert w._live_stack().count() == count
    assert any(word in w.status_label.text() for word in ('变化', '冲突', '过期'))


def test_bulk_then_toggle_then_undo_redo(page):
    w, p = page
    w._set_all(True)
    before = [c.text for c in p.cues]
    w._toggle_issue('middle', 0)
    assert p.cues[0].text == '古龙和火笼来了'
    w._undo()
    assert [c.text for c in p.cues] == before
    w._redo()
    assert p.cues[0].text == '古龙和火笼来了'
    w._set_all(True)
    assert [c.text for c in p.cues] == before


def test_reverted_suggestion_survives_empty_background_rematch(page):
    w, p = page
    w._toggle_issue('middle', 0)
    w._toggle_issue('middle', 0)
    row = w._by_id['middle']
    identity = row['issues'][0]['proposal_id']
    result = SimpleNamespace(hits=[], receipt={})
    texts = {key: item['base'] for key, item in w._by_id.items()}
    w._show_result(result, p, False, texts)
    assert any(i['proposal_id'] == identity for i in row['issues'])
    index = next(i for i, issue in enumerate(row['issues']) if issue.get('proposal_id') == identity)
    w._toggle_issue('middle', index)
    assert p.cues[0].text == '大骨龙和火龙来了'


def test_replace_before_and_after_review(page, monkeypatch):
    w, p = page
    studio = QWidget()
    studio.session = w._standalone.session
    studio.timeline = SimpleNamespace(active_subtitle_layer='original')
    studio.selected_cue_ids = lambda: ['middle']
    studio.session.selected_cue_id = 'middle'
    studio._changed = lambda: None
    studio._show_studio_hint = lambda text: None
    studio.select_cue = lambda key: None
    def replace(old, new):
        dialog = FindReplaceDialog(studio)
        try:
            dialog.find_edit.setText(old)
            dialog.replace_edit.setText(new)
            dialog._do_preview()
            assert dialog.preview.count()
            dialog._do_apply_preview()
            assert new in p.cues[0].text, dialog.status_label.text()
        finally:
            dialog.close()
            dialog.deleteLater()
    try:
        replace('来了', '来了呀')
        w._toggle_issue('middle', 0)
        w._cancel_hidden_checks()
        replace('大骨龙', '新骨龙')
    finally:
        studio.close()


def test_loading_guard_does_not_swallow_recovery_buttons(tmp_path):
    from twobyteasr.design.native_loading_cover import InputHostLease
    from twobyteasr.projects.studio_project_controller import StudioProjectController
    root = QWidget()
    host, cover = QWidget(root), QWidget(root)
    controller = StudioProjectController(host, SimpleNamespace())
    host._studio_trace = lambda *args, **kw: None
    lease = InputHostLease(host)
    host._readiness = SimpleNamespace(loading=SimpleNamespace(_input_lease=lease))
    root.show()
    host.show()
    lease.acquire(root, cover)
    received = []
    def click():
        box = next(x for x in APP.topLevelWidgets() if isinstance(x, QMessageBox) and x.isVisible())
        button = next(b for b in box.buttons() if b.text() == '恢复自动保存')
        button.clicked.connect(lambda: received.append(True))
        QTest.mouseClick(button, Qt.LeftButton)
        if box.isVisible():
            box.reject()
    QTimer.singleShot(50, click)
    try:
        choice = controller._recovery_choice(tmp_path / 'missing.json')
        assert received and choice == 'recover'
        assert lease.held
    finally:
        lease.release()
        root.close()


def test_failed_commit_does_not_claim_success_or_enter_undo(page, monkeypatch):
    w, p = page
    before = [c.text for c in p.cues]
    count = w._live_stack().count()
    def fail(*args, **kwargs):
        raise ValueError('injected transaction failure')
    monkeypatch.setattr(BatchReplaceTextCommand, '_apply', fail)
    w._toggle_issue('middle', 0)
    assert [c.text for c in p.cues] == before
    assert w._live_stack().count() == count
    assert w._last_text_edit_result.states == {'middle': 'failed'}
    assert 'injected transaction failure' in w.status_label.text()
    assert '已写回' not in w.status_label.text()


def test_review_metadata_invalidated_old_replace_binding_but_not_text_binding(page):
    from twobyteasr.studio.studio_find_replace import PreviewBinding, TextReplaceBinding
    w, p = page
    old, current = PreviewBinding.capture(p), TextReplaceBinding.capture(p)
    row = w._by_id['middle']
    row['issues'].append(_issue('near', (0, 2), '古龙', '新骨龙', checked=False))
    w._apply_filter()
    assert not old.matches(p)  # baseline's rejected command despite identical text
    assert current.matches(p)
    p.studio_state['timeline_view'] = {'mode': 'fit', 'duration_ms': 8000}
    assert current.matches(p)  # autosave captures this bookmark without a text edit
    p.cues[0].text = '真正的新文本'
    assert not current.matches(p)


def test_submission_distinguishes_success_unchanged_conflict_missing(page):
    from twobyteasr.studio.text_edit_submission import submit_text_changes
    from twobyteasr.studio.subtitle_text_targets import entry_lookup
    w, p = page
    entries = entry_lookup(p)
    p.cues[1].text = '其他编辑'
    outcome = submit_text_changes(w._standalone,
        {'middle': '实际改动', 'later': '不要覆盖', 'missing': '没有这条'}, entries, label='check')
    assert outcome.states == {'later': 'conflict', 'missing': 'missing', 'middle': 'changed'}
    outcome = submit_text_changes(w._standalone, {'middle': '实际改动'}, entry_lookup(p), label='noop')
    assert outcome.states == {'middle': 'already_target'}
    assert p.cues[1].text == '其他编辑'


@pytest.mark.parametrize('choice, recovered, exists', [('recover', True, True), ('saved', False, True), ('ignore', False, False)])
def test_recovery_decision_preserves_ownership_and_files(tmp_path, choice, recovered, exists):
    from tests.test_project_recovery_inspection import fixture
    from twobyteasr.projects.studio_project_controller import StudioProjectController
    path, official, candidate = fixture(tmp_path)
    page = SimpleNamespace(_studio_trace=lambda *a, **k: None, _studio_preferences=lambda: {})
    controller = StudioProjectController(page, SimpleNamespace())
    steps = controller._resolve_project_recovery_steps(path, official, single_shot_fn=lambda *a: None)
    request = next(steps)
    assert candidate.exists()
    request.choice = choice
    with pytest.raises(StopIteration) as done:
        next(steps)
    project, actual = done.value.value
    assert actual is recovered and candidate.exists() is exists
    assert project.cues[0].text == ('recovered' if recovered else 'official')
    assert path.exists() and project.project_id == official.project_id


def test_recovery_delete_failure_can_retry_or_cancel(tmp_path, monkeypatch):
    from tests.test_project_recovery_inspection import fixture
    from twobyteasr.projects import studio_project as persistence
    from twobyteasr.projects.studio_project_controller import StudioProjectController
    from twobyteasr.projects.project_recovery_dialog import RecoveryCancelled
    path, official, candidate = fixture(tmp_path)
    page = SimpleNamespace(_studio_trace=lambda *a, **k: None, _studio_preferences=lambda: {})
    controller = StudioProjectController(page, SimpleNamespace())
    steps = controller._resolve_project_recovery_steps(path, official, single_shot_fn=lambda *a: None)
    request = next(steps)
    request.choice = 'ignore'
    monkeypatch.setattr(persistence, 'discard_autosave', lambda p: (_ for _ in ()).throw(PermissionError('injected denied')))
    retry = next(steps)
    assert 'injected denied' in retry.error and candidate.exists()
    retry.choice = 'cancel'
    with pytest.raises(RecoveryCancelled):
        next(steps)
    assert candidate.exists()

