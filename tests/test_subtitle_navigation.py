from types import SimpleNamespace
import json
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia, StudioSpeaker
from twobyteasr.projects.studio_session import StudioSession
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.studio.subtitle_navigation import StudioSubtitleNavigationMixin, save_center_preference
from twobyteasr.studio import shortcut_registry
from twobyteasr.timeline.selection_scope import SelectionScope

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture
def timeline(app):
    t=WaveformTimeline();t.thumbnail_requests_enabled=False;t.resize(1200,600)
    p=SubtitleProject(media=StudioMedia('missing.mp4',duration_ms=30000),
        speakers=[StudioSpeaker('S0')],cues=[StudioCue('a',10000,13000,'甲','S0'),StudioCue('b',13000,16000,'乙','S0')])
    t.set_project(p);t.set_visible_window(0,20000);t.show();app.processEvents()
    yield t
    t.close();t.deleteLater();app.processEvents()

class Page(StudioSubtitleNavigationMixin):
    def __init__(self,t):
        self.timeline=t;self.project=t.project
        self.session=StudioSession(project=self.project)
        self.selected_cue_id='a';self.selection_model=SimpleNamespace(scope=SelectionScope.explicit(('a',),'a'))
        self._cue_lookup={c.id:c for c in self.project.cues}
        self.selection_center_toggle=QCheckBox();self.selection_center_toggle.setChecked(True)
        self.video=SimpleNamespace(_playback_clock=SimpleNamespace(exact_seek_pending=False))
        self.seeks=[];self.hints=[]
    def _seek(self,seconds,**kwargs):
        self.seeks.append((seconds,kwargs));self.timeline.set_playhead(round(seconds*1000))
        if self._selection_centered():self.timeline.center_playhead(round(seconds*1000),force=True)
    def _show_studio_hint(self,text):self.hints.append(text)

@pytest.mark.parametrize('position,expected',[(10000,13000),(10001,13000),(12999,10000),(13000,10000),(11500,10000),(29000,10000)])
def test_boundary_toggle_uses_real_primary_intervals(timeline,position,expected):
    p=Page(timeline);timeline.set_playhead(position)
    p._jump_current_subtitle_boundary()
    assert p.seeks[-1][0]*1000==expected
    assert p.seeks[-1][1]['preserve_subtitle_target']
    assert p.selected_cue_id=='a' and p.selection_model.scope.active_id=='a'
    assert len(p.project.cues)==2 and p.project.cues[0].end_ms==13000

@pytest.mark.parametrize('position',[0,10000,16000])
def test_content_center_at_head_middle_and_tail_preserves_zoom(timeline,position):
    timeline.set_center_playhead_mode(True);before=timeline.visible_duration_ms
    timeline.center_playhead(position,force=True)
    assert timeline._time_to_x(position)==pytest.approx((timeline.TRACK_HEADER_WIDTH+timeline._content_right())/2,abs=.1)
    assert timeline.visible_duration_ms==before
    assert timeline.horizontal_scrollbar.minimum()==-before//2
    assert timeline._bounded_time_ms(-20000)==0 and timeline._bounded_time_ms(50000)==timeline._duration_ms()
    timeline.set_center_playhead_mode(False);assert timeline.visible_start_ms>=0


def test_follow_is_per_tick_and_manual_browse_lasts_until_explicit_navigation(timeline):
    timeline.set_center_playhead_mode(True)
    positions=[]
    for at in range(10000,10500,16):
        timeline.center_playhead(at);positions.append(timeline.visible_start_ms)
    assert len(set(positions))==len(positions)
    timeline._horizontal_scrolled(4000);held=timeline.visible_start_ms
    timeline._follow_suspended_until=0
    assert not timeline.center_playhead(11000) and timeline.visible_start_ms==held
    timeline.center_playhead(13000,force=True);assert timeline.visible_start_ms==3000


def test_latest_pending_request_drives_fast_toggle_not_old_observation(timeline):
    p=Page(timeline);timeline.set_playhead(10000)
    p._caption_seek_preparation=SimpleNamespace(pending={'phase':'prepare'})
    for expected in (13000,10000,13000,10000):
        timeline.set_playhead(10000) # an old frame is still visible
        p._jump_current_subtitle_boundary()
        assert p.seeks[-1][0]*1000==expected


def test_modifications_and_multiselect_use_current_primary(timeline):
    p=Page(timeline);p.project.cues[0].start_ms=11000;p.project.cues[0].end_ms=14500
    timeline.refresh_cues() if hasattr(timeline,'refresh_cues') else timeline.set_project(p.project)
    p.selection_model.scope=SelectionScope.explicit(('a','b'),'a')
    timeline.set_playhead(12000);p._jump_current_subtitle_boundary()
    assert p.seeks[-1][0]==11
    p._jump_current_subtitle_boundary();assert p.seeks[-1][0]==14.5


def test_translation_identity_retained_at_shared_end(timeline):
    p=Page(timeline);timeline.set_subtitle_layer('translation');timeline.set_playhead(10000)
    p._jump_current_subtitle_boundary();assert p.seeks[-1][0]==13
    assert p._subtitle_navigation_target[2:]==('a','translation')
    assert p._held_subtitle_navigation()
    p._jump_current_subtitle_boundary();assert p.seeks[-1][0]==10
    assert timeline.active_subtitle_layer=='translation'


def test_empty_or_deleted_target_does_not_seek(timeline):
    p=Page(timeline);p.selection_model.scope=SelectionScope.empty()
    p._jump_current_subtitle_boundary();assert not p.seeks and p.hints
    p.selection_model.scope=SelectionScope.explicit(('gone',),'gone')
    p._jump_current_subtitle_boundary();assert not p.seeks


def test_click_navigation_is_release_only_and_repeats(timeline,app):
    signals=[];timeline.cue_navigation_requested.connect(signals.append)
    y=round(timeline._track_layout()[0]['S0'].center().y())
    point=QPoint(round(timeline._time_to_x(11000)),y)
    QTest.mousePress(timeline,Qt.LeftButton,Qt.NoModifier,point);assert signals==[]
    QTest.mouseRelease(timeline,Qt.LeftButton,Qt.NoModifier,point);assert signals==['a']
    QTest.mouseClick(timeline,Qt.LeftButton,Qt.NoModifier,point);assert signals==['a','a']
    for mods in (Qt.ControlModifier,Qt.ShiftModifier,Qt.AltModifier):
        QTest.mouseClick(timeline,Qt.LeftButton,mods,point)
    assert signals==['a','a']

@pytest.mark.parametrize('mode',['move','left','right','copy','marquee'])
def test_edit_gestures_do_not_emit_navigation_or_force_scroll(timeline,app,mode):
    signals=[];timeline.cue_navigation_requested.connect(signals.append)
    timeline.set_center_playhead_mode(True);timeline.set_visible_window(0,20000)
    timeline.snap_enabled=False
    y=round(timeline._track_layout()[0]['S0'].center().y())
    at={'move':11000,'left':10000,'right':13000,'copy':11000,'marquee':8000}[mode]
    point=QPoint(round(timeline._time_to_x(at)),y)
    mods=Qt.AltModifier if mode=='copy' else Qt.NoModifier
    QTest.mousePress(timeline,Qt.LeftButton,mods,point)
    QTest.mouseMove(timeline,point+QPoint(45,0));app.processEvents()
    held=timeline.visible_start_ms
    assert not timeline.center_playhead(25000,force=True) and timeline.visible_start_ms==held
    QTest.mouseRelease(timeline,Qt.LeftButton,mods,point+QPoint(45,0))
    assert signals==[]


def test_preference_roundtrip_keeps_other_settings(tmp_path,monkeypatch):
    from twobyteasr.projects import studio_project
    path=tmp_path/'studio.json';path.write_text(json.dumps({'shortcuts':{'play_pause':'K'},'studio_preferences':{'autosave_enabled':False}}),'utf8')
    monkeypatch.setattr(studio_project,'studio_settings_path',lambda:path)
    save_center_preference(True);payload=json.loads(path.read_text('utf8'))
    assert payload['studio_preferences']=={'autosave_enabled':False,'selection_centered':True}
    assert payload['shortcuts']=={'play_pause':'K'}
    save_center_preference(False);assert json.loads(path.read_text('utf8'))['studio_preferences']['selection_centered'] is False


def test_registry_default_is_free_rebindable_and_settings_roundtrip():
    values=shortcut_registry.platform_defaults('win32')
    assert values['jump_cue_boundary']=='Alt+J'
    assert [k for k,v in values.items() if v=='Alt+J']==['jump_cue_boundary']
    loaded,_=shortcut_registry.load_values({'jump_cue_boundary':'Ctrl+Shift+J'})
    assert loaded['jump_cue_boundary']=='Ctrl+Shift+J'


def test_new_default_uses_free_fallback_when_older_custom_binding_owns_alt_j():
    values,unbound=shortcut_registry.load_values({'smart_align':'Alt+J'})
    assert values['smart_align']=='Alt+J'
    assert values['jump_cue_boundary']=='Alt+Shift+J'
    assert 'jump_cue_boundary' not in unbound
    assert not [c for c in shortcut_registry.blocking_conflicts(values) if 'jump_cue_boundary' in (c.first,c.second)]


@pytest.mark.parametrize('layer',['original','translation'])
def test_double_click_keeps_first_clicked_caption_after_center_scroll(timeline,layer):
    timeline.set_center_playhead_mode(True)
    timeline.set_visible_window(8000,10000)
    timeline.cue_navigation_requested.connect(lambda cue_id: timeline.center_playhead(timeline._timeline_cue_by_id[cue_id].start_ms,force=True))
    timeline.set_bilingual(True)
    timeline.project.generation_metadata['translations']={'a':'Translation A'}
    rect=timeline._track_layout()[1] if layer=='translation' else timeline._track_layout()[0]['S0']
    y=round(rect.center().y())
    pos=QPoint(round(timeline._time_to_x(11000)),y)
    QTest.mouseClick(timeline,Qt.LeftButton,Qt.NoModifier,pos)
    QTest.mouseDClick(timeline,Qt.LeftButton,Qt.NoModifier,pos)
    assert timeline._inline_target==('a',layer=='translation')
    timeline._cancel_inline_edit()


def test_manual_identity_is_retained_by_clock_even_with_center_mode_disabled(timeline):
    from twobyteasr.studio.studio_cue_controller import StudioCueController
    p=Page(timeline);p.selection_center_toggle.setChecked(False)
    p.session.selected_cue_id='a';p._remember_subtitle_navigation('a')
    mirrors=[]
    class Controller(StudioCueController):
        def _mirror_clock_selection(self, cue_id, **kwargs):
            mirrors.append(cue_id)
    controller=Controller(p,p.session)
    controller.sync_playhead_target(14000,force=True)
    assert p._held_subtitle_navigation() and not mirrors
    timeline.set_playhead(14000);p._jump_current_subtitle_boundary()
    assert p.seeks[-1][0]==10.0
    p._jump_current_subtitle_boundary();assert p.seeks[-1][0]==13.0
    assert p.selection_model.scope.active_id=='a'


def test_buffer_hold_and_repeated_play_receipts_do_not_cancel_manual_browsing(timeline):
    p=Page(timeline);p.video.playback_intended=True
    p._sync_navigation_playback_intent(False)
    timeline.hold_manual_view()
    for paused in (False,True,False,False):
        p._sync_navigation_playback_intent(paused)
        assert timeline._manual_view_hold
    p.video.playback_intended=False;p._sync_navigation_playback_intent(True)
    p.video.playback_intended=True;p._sync_navigation_playback_intent(True)
    assert timeline._manual_view_hold
    p._sync_navigation_playback_intent(False)
    assert not timeline._manual_view_hold and timeline._follow_suspended_until==0
