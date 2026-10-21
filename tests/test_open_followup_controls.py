"""Regression cases from the October 20 daily EXE feedback."""
import copy
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication, QMenu
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.studio import studio_chinese_script as scripts

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])

def project():
    p = SubtitleProject(StudioMedia('fixture.mp4'), cues=[
        StudioCue('1', 1000, 2000, '怖いわー'), StudioCue('2', 2000, 3000, '世代怖いわー')])
    p.generation_metadata = {'language': {'code': 'ja'}, 'translations': {'1': '头发干了', '2': '虚拟世代'}}
    st.migrate(p)
    p.validate()
    return p

def test_japanese_translation_only_selected_conversion_is_atomic_and_stale_safe(app):
    from twobyteasr.studio.translation_actions import capture_intent, intent_current
    p = project(); page = SimpleNamespace(project=p, undo_stack=QUndoStack())
    original = copy.deepcopy(p.cues); before = st.snapshot(p)
    intent = capture_intent(page, ['1'], 'zh-Hans')
    assert scripts.convert_project(page, scripts.TRADITIONAL, layer='translation', cue_ids=['1'])
    assert p.cues == original
    assert p.generation_metadata['translations'] == {'1': '頭髮幹了', '2': '虚拟世代'}
    assert p.generation_metadata['language'] == {'code': 'ja'}
    assert not intent_current(page, intent, 'zh-Hans')
    page.undo_stack.undo(); assert st.snapshot(p) == before
    page.undo_stack.redo()
    loaded = SubtitleProject.from_dict(p.to_dict())
    assert loaded.generation_metadata['translations'] == p.generation_metadata['translations']
    assert not scripts.convert_project(page, scripts.TRADITIONAL, layer='original')

def test_selected_original_conversion_does_not_change_global_script(app):
    p = project(); p.generation_metadata['language'] = {'code': 'zh'}
    p.cues[0].text = p.cues[0].original_text = '头发干了'
    page = SimpleNamespace(project=p, undo_stack=QUndoStack())
    assert scripts.convert_project(page, scripts.TRADITIONAL, cue_ids=['1'])
    assert p.generation_metadata['language'] == {'code': 'zh'}
    page.undo_stack.undo(); assert p.cues[0].text == '头发干了'

def test_translation_menu_refreshes_selection_and_partial_merge_reason(app):
    from twobyteasr.studio.translation_actions import add_actions
    page = SimpleNamespace(project=None, selected_cue_ids=lambda: [])
    menu = QMenu(); action, merge = add_actions(page, menu)
    assert not action.isEnabled()
    page.project = project(); page.selected_cue_ids = lambda: ['1']
    st.records_of(page.project)['1']['merge_missing'] = ['2']
    menu.aboutToShow.emit()
    assert action.isEnabled() and merge.isEnabled()
    assert any('1 段缺译' in a.text() for a in menu.actions())

def test_play_is_gated_by_readiness_and_cancel_drops_intent(app):
    from tests.test_playback_lifecycle import _playing_canvas
    canvas, controller = _playing_canvas(paused=True)
    gate = SimpleNamespace(active=True)
    canvas._studio_page = lambda: SimpleNamespace(_readiness=gate, _studio_trace=lambda *a, **k: None)
    canvas.set_paused(False)
    assert canvas._startup_play_requested and False not in controller.paused_commands
    canvas.resume_requested_playback()
    assert False not in controller.paused_commands
    canvas.set_paused(True); gate.active = False; canvas.resume_requested_playback()
    assert False not in controller.paused_commands
    gate.active = True; canvas.set_paused(False); gate.active = False
    canvas.resume_requested_playback()
    assert controller.paused_commands[-1] is False
    canvas.set_paused(True); canvas.deleteLater()

def test_stale_ready_callback_cannot_play_new_load(app):
    from tests.test_playback_lifecycle import _playing_canvas
    canvas, controller = _playing_canvas(paused=True)
    canvas._startup_play_requested = True
    canvas._queue_requested_startup_play()
    canvas._load_generation = getattr(canvas, '_load_generation', 0) + 1
    app.processEvents()
    assert False not in controller.paused_commands
    canvas.set_paused(True); canvas.deleteLater()


def test_bilingual_scene_readiness_counts_source_and_companion_separately():
    from twobyteasr.studio.studio_readiness import caption_scene_ready
    state = dict(expected_cue_ids=['1'], cue_pixels=[dict(cue_id='1',status='rendered'),
                                                   dict(cue_id='1#tr',status='rendered')])
    assert caption_scene_ready(state)
    state['cue_pixels'][1]['status']='pending'
    assert not caption_scene_ready(state)
    state['cue_pixels']=[]
    assert not caption_scene_ready(state)


def test_paused_open_reconciles_cache_prepared_during_hydration():
    import time
    from twobyteasr.studio.studio_readiness import StudioReadiness
    state = dict(expected_cue_ids=['24'], cue_pixels=[])
    scene = SimpleNamespace(active=True, trace=lambda: state)
    calls = []
    def present():
        calls.append('present')
        state['cue_pixels'] = [dict(cue_id='24',status='rendered'),
                               dict(cue_id='24#tr',status='rendered')]
    page = SimpleNamespace(project=SimpleNamespace(media=SimpleNamespace(path=''), cues=[object()]),
        video=SimpleNamespace(_paused=True), _caption_scene=scene, _preview_path='ready.ass',
        audio_engine=SimpleNamespace(telemetry_snapshot=lambda:{}),
        _present_caption_scene=present)
    now=time.perf_counter()
    gate = SimpleNamespace(page=page, completed={'准备播放器','准备音频'},
        started=now,last_tick=now,profile={'gui_gaps_ms':[]},steps=None,hydrated=True,
        painted=False,TASKS=StudioReadiness.TASKS,_set_stage_label=lambda _:None)
    gate.mark=gate.completed.add
    StudioReadiness._tick(gate)
    assert '准备字幕' in gate.completed
    assert calls == ['present'] and page.video._paused
