"""Real background planning, GUI ownership and latest-operation publication."""
import copy
import threading
import time
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from tests.test_presentation_scope_contract import page
from tests.test_studio_interaction_style import choose,click_scope
from twobyteasr.caption_style.scoped_style import effective_layer_style
from twobyteasr.caption_style.caption_layer_transform import resolved_values
from twobyteasr.projects.studio_revisions import StudioRevisionStore


def enlarge(page,monkeypatch):
    from twobyteasr.system import resident_worker
    monkeypatch.setattr(resident_worker,'shared_worker',lambda:None)
    p=page.project
    for i in range(25,140):
        cue=copy.deepcopy(p.cues[i%25]);cue.id='bulk-'+str(i)
        cue.start_ms=i*3000;cue.end_ms=cue.start_ms+2400
        p.cues.append(cue)
        p.generation_metadata['translations'][cue.id]='Translation '+str(i)
    page._cue_lookup={c.id:c for c in p.cues}
    page._revision_store=StudioRevisionStore(p)
    page.cue_model.set_project(p);page.timeline.set_project(p)
    page.style_scope.setCurrentIndex(page.style_scope.findData('all'))
    page.undo_stack.clear()


def settled(page):
    end=time.monotonic()+15
    while getattr(page,'_style_application_busy',False) and time.monotonic()<end:QTest.qWait(10)
    assert not page._style_application_busy
    assert not getattr(page,'_style_application_error','')


def test_rapid_preset_color_geometry_uses_last_action_and_one_undo(page,monkeypatch):
    enlarge(page,monkeypatch)
    hints=[]
    monkeypatch.setattr(page,'_show_studio_hint',hints.append)
    def presentation():
        return copy.deepcopy([(c.id,c.text,c.speaker_id,c.style_id,c.base_preset_id,c.effect_id,
                              c.appearance_override,c.transform) for c in page.project.cues])
    before=presentation()
    choose(page,monkeypatch)
    assert page._style_application_busy
    assert not any('已应用' in message for message in hints)
    page._set_style_color(page.style_outline_color,'#FFFF0000')
    page._set_style_color(page.style_outline_color,'#FF0066FF')
    page.style_apply_geometry.setChecked(True)
    settled(page)
    assert not page.save_state.text().startswith('正在应用样式')
    assert page.undo_stack.count()==1
    for cue in page.project.cues:
        assert QColor(effective_layer_style(page.project,cue,'original').outline_color)==QColor('#0066FF')
        assert resolved_values(page.project,cue,'original')['position_x']==280.
    after=presentation()
    page.undo_stack.undo();assert presentation()==before
    page.undo_stack.redo();assert presentation()==after


def test_layer_switch_retires_queued_result_without_mutating(page,monkeypatch):
    enlarge(page,monkeypatch)
    from twobyteasr.caption_style import bulk_style_preparation as bulk
    gate=threading.Event();started=threading.Event();original=bulk.prepare_style_job
    def delayed(payload,cancel_check=None):
        started.set()
        gate.wait(3)
        return original(payload,cancel_check=cancel_check)
    monkeypatch.setattr(bulk,'prepare_style_job',delayed)
    before=copy.deepcopy(page.project.cues)
    choose(page,monkeypatch)
    assert started.wait(2)
    page.style_layer.setCurrentIndex(page.style_layer.findData('translation'))
    gate.set()
    deadline=time.monotonic()+10
    while page.style_controller._bulk_application.running and time.monotonic()<deadline:QTest.qWait(10)
    assert not page._style_application_busy
    assert page.project.cues==before and page.undo_stack.count()==0


def test_project_close_cancels_an_actually_running_plan(page,monkeypatch):
    enlarge(page,monkeypatch)
    from twobyteasr.caption_style import bulk_style_preparation as bulk
    gate=threading.Event();started=threading.Event();original=bulk.prepare_style_job
    def delayed(payload,cancel_check=None):
        started.set();gate.wait(3)
        return original(payload,cancel_check=cancel_check)
    monkeypatch.setattr(bulk,'prepare_style_job',delayed)
    project=page.project;before=copy.deepcopy(project.cues)
    choose(page,monkeypatch);assert started.wait(2)
    page._close_project_session('cancel-active-style-plan');gate.set()
    end=time.monotonic()+10
    while page.style_controller._bulk_application.running and time.monotonic()<end:QTest.qWait(10)
    assert page.project is None and not page._style_application_busy
    assert project.cues==before and page.undo_stack.count()==0


def test_save_flush_waits_for_last_background_action(page,monkeypatch):
    enlarge(page,monkeypatch)
    choose(page,monkeypatch)
    assert page.style_controller.flush_pending_application()
    assert page.undo_stack.count()==1
    assert all(effective_layer_style(page.project,c,'original').font_size==63. for c in page.project.cues)


def test_distinct_pending_fields_compose_without_losing_color(page,monkeypatch):
    enlarge(page,monkeypatch);choose(page,monkeypatch);settled(page)
    page._set_style_color(page.style_outline_color,'#FF0066FF')
    page.style_font_size.setValue(71)
    page._commit_style_now()
    page.style_spacing.setValue(3)
    page._commit_style_now()
    settled(page)
    for cue in page.project.cues:
        style=effective_layer_style(page.project,cue,'original')
        assert QColor(style.outline_color)==QColor('#0066FF')
        assert style.font_size==71. and style.spacing==3.
