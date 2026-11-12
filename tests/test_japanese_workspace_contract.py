from types import SimpleNamespace
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QPushButton
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia, StudioSpeaker
from twobyteasr.recognition.speaker_roles import KEY, GROUP_KEY
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.studio.subtitle_navigation import StudioSubtitleNavigationMixin
from twobyteasr.timeline.selection_scope import SelectionScope
from twobyteasr.caption_style.subtitle_visibility import layer_visible

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture
def timeline(app):
    p=SubtitleProject(media=StudioMedia('missing.mp4',duration_ms=1420000),
        speakers=[StudioSpeaker(f'S{i}') for i in range(32)],
        cues=[StudioCue(f'c{i}',5964+i*20000,9000+i*20000,'テスト',f'S{i}') for i in range(32)])
    p.studio_state[KEY]={'grouped':True,'expanded':True,'auto':{f'S{i}':'secondary' if i else 'main' for i in range(32)}}
    t=WaveformTimeline();t.thumbnail_requests_enabled=False;t.resize(1200,450);t.set_project(p);t.show();app.processEvents()
    yield t
    t.close();t.deleteLater();app.processEvents()

@pytest.mark.parametrize('at,duration,left',[(5964,1420000,0),(600000,1420000,592500),
    (1419000,1420000,1405000),(5964,8000,0),(0,1420000,0)])
@pytest.mark.parametrize('width',[780,1600])
def test_locate_fifteen_seconds_and_vertical_invariants(timeline,app,at,duration,left,width):
    t=timeline;t._project_duration_ms=duration;t.resize(width,450);app.processEvents()
    before=(t.vertical_scrollbar.value(),t._group_expanded,t._speaker_track_height(),tuple(t._speaker_ids))
    t.locate_subtitle_start(at)
    assert (t.visible_start_ms,t.visible_duration_ms)==(left,15000)
    assert t._x_to_time(t.TRACK_HEADER_WIDTH)==left
    assert t._x_to_time(t._content_right())==left+15000
    assert (t.vertical_scrollbar.value(),t._group_expanded,t._speaker_track_height(),tuple(t._speaker_ids))==before
    assert not t.reveal_playhead(at)  # paused observations retain the tail window

def test_only_explicit_action_uses_active_project_cue(timeline):
    class Page(StudioSubtitleNavigationMixin):
        def _seek(self,seconds,**kw): self.seeks.append(seconds)
        def _show_studio_hint(self,text): self.hint=text
    p=Page();p.timeline=timeline;p.project=timeline.project;p.session=SimpleNamespace(generation=1)
    p.selection_center_toggle=QPushButton();p.selected_cue_id='c0';p.seeks=[]
    p.selection_model=SimpleNamespace(scope=SelectionScope.explicit(('c0','c30'),'c30'))
    p._caption_following=True
    p._caption_draft=SimpleNamespace(target=SimpleNamespace(cue_id='c0',layer='translation'))
    p._caption_owns_draft=lambda draft:True
    p._locate_selected_subtitle()
    assert p.seeks==[605.964] and timeline.visible_start_ms==598464
    assert p._subtitle_navigation_target[2]=='c30'
    timeline.set_visible_window(1000,9000);p._navigate_selected_subtitle('c0')
    assert len(p.seeks)==1 and timeline.visible_duration_ms==9000

def test_secondary_default_compact_and_selection_never_expands(timeline):
    t=timeline
    assert not t._group_expanded
    assert t._display_rows()[0]==('group_header',GROUP_KEY,t.GROUP_HEADER_HEIGHT)
    assert len(t._track_layout()[0])==1
    for cue in t.project.cues[1:]:
        t.set_selected(cue.id);t.reveal_cue(cue.id)
    assert not t._group_expanded
    t.set_group_expanded(True);t.reindex_project()
    assert t._group_expanded and len(t._track_layout()[0])==32
    t.set_group_expanded(False);assert len(t._track_layout()[0])==1

def test_group_eye_preserves_children_and_filters_both_layers_and_hits(timeline,monkeypatch):
    t=timeline;t.set_group_expanded(True);t.bilingual=True;t.set_visible_window(20000,30000)
    p=t.project;p.studio_state['subtitle_track_visibility']={'S2':False,'speaker:S3':False,GROUP_KEY:False}
    before=dict(p.studio_state['subtitle_track_visibility'])
    assert layer_visible(p,p.cues[0]) and layer_visible(p,p.cues[0],'translation')
    assert not layer_visible(p,p.cues[1]) and not layer_visible(p,p.cues[1],'translation')
    point=QPoint(round(t._time_to_x(27000)),round(t._track_layout()[0]['S1'].center().y()))
    assert t._cue_at(point)[0] is None
    translation=t._track_layout()[1]
    point.setY(round(translation.center().y()));assert not t._translation_candidates_at(point)
    def no_fallback(*args,**kw):raise AssertionError('hidden timeline blank opened whole-project chooser')
    monkeypatch.setattr('twobyteasr.studio.studio_translation_edit.choose_cue',no_fallback)
    assert t._resolve_translation_at(point,choose=True) is None
    p.studio_state['subtitle_track_visibility'][GROUP_KEY]=True
    assert layer_visible(p,p.cues[1]) and not layer_visible(p,p.cues[2])
    assert p.studio_state['subtitle_track_visibility']['S2']==before['S2']
    assert not layer_visible(p,p.cues[3]) and not layer_visible(p,p.cues[3],'translation')
    assert layer_visible(p,p.cues[1],'translation')

def test_group_gate_is_shared_by_burnin_and_plain_text_export(timeline,tmp_path):
    from twobyteasr.subtitle_rules.subtitle_translation import set_manual
    from twobyteasr.exports.export_timeline import export_project_snapshot
    from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts,SubtitleExportOptions
    p=timeline.project;p.studio_state['bilingual_mode']=True
    for cue in p.cues:set_manual(p,cue.id,'译文 '+cue.id)
    p.studio_state['subtitle_track_visibility']={GROUP_KEY:False}
    snapshot=export_project_snapshot(p)
    assert {c.speaker_id for c in snapshot.cues}=={'S0'}
    artifacts=export_subtitle_artifacts(p,tmp_path,'group-hidden',SubtitleExportOptions())
    assert artifacts and all('译文 c1' not in a.path.read_text('utf-8-sig') for a in artifacts if a.path.suffix=='.srt')
