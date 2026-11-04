"""Retained regressions for structural caption edits and task-language guards."""
import copy

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.timeline.studio_commands import delete_cues_command
from twobyteasr.studio.studio_timeline import WaveformTimeline

APP = QApplication.instance() or QApplication([])


def project():
    return SubtitleProject(StudioMedia('missing.mp4', duration_ms=20000), speakers=[StudioSpeaker('S00','主播')], cues=[
        StudioCue('a', 1000, 2000, '第一句'), StudioCue('b', 3000, 4000, '第二句'),
        StudioCue('c', 5000, 6000, '第三句')])


@pytest.mark.parametrize('language', ['zh', 'ja', 'en', 'ko', 'fr'])
def test_startup_guard_is_independent_of_task_language(language):
    import subtitle_core as core
    from twobyteasr.subtitle_rules.language_rules import language_scope, active_task_language
    with language_scope(language):
        before = copy.deepcopy(core.RUN_REVIEW_ITEMS)
        batch = [core.SpeechSegment(1, 0., 4., '哦耶还没到保底我就抽到了哈哈', .9, [], speaker='S01')]
        actual = core.repair_dependent_particle_boundary_offsets(batch, [11, 12, 14])
        print({'task_language': language, 'input': [11, 12, 14], 'actual': actual,
               'text': core.texts_from_boundary_offsets(batch, actual), 'expected_zh': [7, 14]})
        assert core.run_startup_self_test()['checks'] >= 10
        assert active_task_language() == language
        assert core.RUN_REVIEW_ITEMS == before


def test_media_refresh_cannot_keep_deleted_caption_objects():
    p = project()
    t = WaveformTimeline(); t.resize(1100, 350); t.set_project(p)
    try:
        t.set_visible_window(0, 10000)
        assert 'b' in {c.id for c in t.visible_cues()}
        # Unified clip edits publish a sequence delta followed by this refresh.
        p.cues = [c for c in p.cues if c.id != 'b']
        state_for(p).reindex_cues(p)
        t.refresh_media_graph()
        assert 'b' not in t._timeline_cue_by_id
        assert 'b' not in {c.id for c in t.visible_cues()}
    finally:
        t.close(); t._thumbnails.thread.join(2)


def test_source_delete_removes_linked_records_and_undo_restores_them():
    from twobyteasr.subtitle_rules.subtitle_translation import set_manual, restore_snapshot
    p = project()
    restore_snapshot(p, set_manual(p, 'b', '訳文')[1])
    before = copy.deepcopy(p.generation_metadata)
    stack = QUndoStack(); stack.push(delete_cues_command(p, ['b']))
    assert 'b' not in p.generation_metadata.get('translations', {})
    assert 'b' not in p.generation_metadata.get('translation_records', {}).get('records', {})
    stack.undo()
    assert p.generation_metadata == before
    stack.redo()
    assert 'b' not in {c.id for c in p.cues}


def test_completion_hint_requires_actual_usable_and_synced_results():
    from types import SimpleNamespace as NS
    from twobyteasr.app.completion_dialog import delivery_hint
    p = project()
    ok = NS(status='success')
    failed = NS(status='failed')
    assert '没有可用结果' in delivery_hint([])
    assert '没有可用结果' in delivery_hint([(failed, None)])
    assert '已保存' in delivery_hint([(ok, p)])
    assert '部分结果已保存' in delivery_hint([(ok, p), (failed, None)])
    assert '部分结果已同步' in delivery_hint([(ok, p), (failed, None)], NS(project=p))
    assert '部分结果已同步' in delivery_hint([(ok, p), (failed, None)], synced=True)
    assert '已保存' in delivery_hint([(ok, p)], NS(project=project()))


@pytest.mark.parametrize('applied', [False, True])
def test_range_handoff_reports_actual_commit_result(applied):
    from types import SimpleNamespace as NS
    from twobyteasr.app.ui import MainWindow
    done, hints = [], []
    host = NS(_studio_recognition_context={'snapshot': {'range_ms': [0, 1000]}, 'handoff_done': done.append},
              studio_page=NS(apply_range_recognition_result=lambda *_: applied),
              _update_completion_delivery_hint=lambda **kw: hints.append(kw))
    MainWindow._finish_studio_recognition(host, 'result.2byteproj')
    assert done == [applied] and hints == [dict(synced=applied)]


def test_real_queue_guard_under_japanese_keeps_completed_output_on_later_failure(tmp_path):
    import subtitle_core
    from tests.test_service_layer import FakeLegacy, FakePipeline, run_media_queue, _media
    from twobyteasr.recognition.service import RunOptions
    legacy = FakeLegacy(tmp_path)
    legacy.run_startup_self_test = subtitle_core.run_startup_self_test
    result = run_media_queue([_media(tmp_path, 'good.wav'), _media(tmp_path, 'bad.wav')],
        RunOptions(recognition_language='ja'), _legacy=legacy, _pipeline=FakePipeline(failing={'bad.wav'}))
    assert [r.status for r in result.results] == ['success', 'failed']
    assert (tmp_path/'good.srt').read_text('utf8') == 'ok'


@pytest.mark.parametrize('ids', [['a'], ['a', 'c'], ['a', 'b', 'c']])
def test_delete_roundtrip_and_consecutive_undo_preserve_ids_and_translations(tmp_path, ids):
    from twobyteasr.projects.studio_project import save_project, load_project
    from twobyteasr.subtitle_rules import subtitle_translation as st
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions
    p = project(); ensure_independent_captions(p)
    for cue in p.cues: st.set_manual(p, cue.id, '译文' + cue.id)
    stack = QUndoStack(); before = copy.deepcopy(p.to_dict())
    for key in ids: stack.push(delete_cues_command(p, [key]))
    save_project(p, tmp_path/'deleted.2byteproj')
    loaded = load_project(tmp_path/'deleted.2byteproj')
    assert {c.id for c in loaded.cues} == {'a', 'b', 'c'} - set(ids)
    assert not set(ids)&set(st.records_of(loaded))
    for _ in ids: stack.undo()
    assert [c.id for c in p.cues] == [c['id'] for c in before['cues']]
    assert p.generation_metadata == before['generation_metadata']
    for _ in ids: stack.redo()
    assert not set(ids)&{c.id for c in p.cues}

