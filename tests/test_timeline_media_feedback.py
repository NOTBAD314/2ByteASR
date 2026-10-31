"""Editing risks: one preview/commit time, local source grids and view-only tail."""
import copy
from fractions import Fraction
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.test_studio_clip_edit import project, add_v2, clip, edit, assert_linked
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.timeline.media_edit_time import asset_frame_rate, frame_time
from twobyteasr.timeline.studio_clip_edit import preview_clip_edit, split_audio_command
from twobyteasr.timeline.studio_edit_sequence import sequence_of, timeline_duration_ms
from twobyteasr.projects.project_range import range_points, set_range, validated_range
from twobyteasr.projects.studio_project import StudioCue, save_project, load_project


@pytest.fixture
def timeline():
    app = QApplication.instance() or QApplication([])
    p = project(); add_v2(p)
    t = WaveformTimeline(); t.resize(1250, 650); t.set_project(p)
    t.set_visible_window(0, 30000); t.show(); app.processEvents()
    t.set_snap_enabled(False)
    yield t
    t.close(); t.deleteLater(); app.processEvents()


def point(t, value, track='V2', audio=False):
    rows = t._audio_track_rects() if audio else t._video_track_rects()
    return QPoint(round(t._time_to_x(value)), round(rows[track].center().y()))


@pytest.mark.parametrize('rate,expected', [('25', 6280), ('24', 6292), ('30000/1001', 6268)])
def test_each_asset_grid_not_render_fps(timeline, rate, expected):
    t = timeline; c = clip(t.project, 'V2')
    asset = next(a for a in t.project.media_pool if a.asset_id == c.asset_id)
    asset.video_metadata = {'frame_rate': rate}
    t.project.render_settings['fps'] = 60
    value, frame = frame_time(c, 6281, asset_frame_rate(asset))
    assert value == expected
    assert frame is not None


def test_offset_speed_uses_source_grid():
    c = SimpleNamespace(source_in_ms=1010, source_out_ms=3010,
                        timeline_in_ms=5000, timeline_out_ms=6000, playback_rate=2)
    # source 1136 ms -> nearest 25fps boundary 1120 -> project 5055 ms.
    assert frame_time(c, 5063, Fraction(25)) == (5055, 28)
    assert frame_time(c, 5063, None) == (5063, None)


def test_hover_and_click_share_cut_and_do_not_use_playhead(timeline):
    t = timeline; p = t.project
    asset = next(a for a in p.media_pool if a.asset_id == clip(p, 'V2').asset_id)
    asset.video_metadata = {'fps': 25}
    t.set_tool_mode('razor'); t.set_playhead(21000)
    before = p.to_dict(); pos = point(t, 12367)
    t._update_razor_hover(pos, Qt.NoModifier)
    cut = t._media_cut
    assert cut and cut.kind == 'video' and cut.track_id == 'V2'
    assert cut.split_ms != t.playhead_ms
    assert p.to_dict() == before
    received = []
    t.video_clip_razor_requested.connect(lambda a, b, c: received.append((a, b, c)))
    QTest.mouseClick(t, Qt.LeftButton, Qt.NoModifier, pos)
    assert received == [('V2', cut.clip_id, cut.split_ms)]
    assert p.to_dict() == before


def test_snap_preview_and_alt_bypass(timeline):
    t = timeline; t.set_tool_mode('razor'); t.set_snap_enabled(True)
    t.set_playhead(12345)
    pos = point(t, 12400)
    t._update_razor_hover(pos, Qt.NoModifier)
    assert t._media_cut.split_ms == 12345
    assert t._media_cut.snap == '播放头'
    t._update_razor_hover(pos, Qt.AltModifier)
    assert t._media_cut.split_ms == t._x_to_time(pos.x())
    assert not t._media_cut.snap
    t.set_tool_mode('selection'); assert t._media_cut is None


@pytest.mark.parametrize('linked,locked', [(True, False), (False, False), (True, True)])
def test_targets_link_and_lock_are_not_inferred_from_guide_line(timeline, linked, locked):
    t = timeline; p = t.project
    group = next(g for g in p.av_track_groups if g.video_track_id == 'V2')
    group.linked = linked
    sound = next(a for a in p.audio_tracks if a.id == group.audio_track_id)
    sound.locked = locked
    t.set_tool_mode('razor'); t._update_razor_hover(point(t, 12000), Qt.NoModifier)
    cut = t._media_cut
    assert bool(cut.blocked) == locked
    assert [x[0] for x in cut.targets] == (['video', 'audio'] if linked else ['video'])
    before = copy.deepcopy(p.audio_tracks)
    if locked:
        with pytest.raises(ValueError): edit(p, 'V2', 'split', time_ms=cut.split_ms)
        assert p.audio_tracks == before
    else:
        edit(p, 'V2', 'split', time_ms=cut.split_ms)
        assert len(next(a for a in p.audio_tracks if a.id == sound.id).clips) == (2 if linked else 1)


def test_independent_audio_razor_keeps_video_and_undo_reopen(timeline, tmp_path):
    t = timeline; p = t.project
    group = next(g for g in p.av_track_groups if g.video_track_id == 'V2'); group.linked = False
    sound = next(a for a in p.audio_tracks if a.id == group.audio_track_id)
    audio = sound.clips[0]
    t.set_tool_mode('razor'); t._update_razor_hover(point(t, 12000, sound.id, True), Qt.NoModifier)
    cut = t._media_cut
    assert cut.kind == 'audio' and cut.targets == (('audio', sound.id, audio.id),)
    videos = copy.deepcopy(p.video_tracks); original = copy.deepcopy(p.audio_tracks)
    duration = timeline_duration_ms(p)
    command = split_audio_command(p, sound.id, audio.id, cut.split_ms)
    command.redo()
    assert p.video_tracks == videos and timeline_duration_ms(p) == duration
    children = next(a for a in p.audio_tracks if a.id == sound.id).clips
    assert len(children) == 2 and children[0].source_out_ms == children[1].source_in_ms
    command.undo(); assert p.audio_tracks == original
    command.redo(); loaded = load_project(save_project(p, tmp_path/'audio.2byteproj'))
    assert loaded.audio_tracks == p.audio_tracks and loaded.video_tracks == videos


def test_real_edge_has_ten_logical_pixels_both_sides(timeline):
    t = timeline; c = clip(t.project, 'V2')
    t.set_visible_window(45000, 40000)
    pos = point(t, c.timeline_out_ms); pos.setX(pos.x()+9)
    assert t._media_edge_at(pos) == ('V2', c.id, 'trim_right')
    QTest.mousePress(t, Qt.LeftButton, Qt.NoModifier, pos)
    assert t._clip_drag and t._clip_drag['mode'] == 'trim_right'
    QTest.keyClick(t, Qt.Key_Escape)


def test_viewport_edge_is_not_a_real_clip_edge(timeline):
    t = timeline
    pos = QPoint(t._content_right()-2, round(t._video_track_rect('V2').center().y()))
    assert t._video_clip_at('V2', t._x_to_time(pos.x())) is not None
    assert t._media_edge_at(pos) is None


def test_narrow_clip_nearest_edge(timeline):
    t = timeline; edit(t.project, 'V2', 'trim', start=5000, end=5200)
    c = clip(t.project, 'V2')
    assert t._media_edge_at(point(t, 5180)) == ('V2', c.id, 'trim_right')
    assert t._media_edge_at(point(t, 5020)) == ('V2', c.id, 'trim_left')


def test_tail_and_manual_view_do_not_change_document(timeline):
    t = timeline; p = t.project; before = p.to_dict()
    t.set_visible_window(t._project_duration_ms, 20000)
    assert t.visible_start_ms + t.visible_duration_ms > t._project_duration_ms
    assert 32 <= (t.visible_start_ms+t.visible_duration_ms-t._project_duration_ms) * (t._content_right()-t.TRACK_HEADER_WIDTH)/t.visible_duration_ms <= 181
    window = t.visible_start_ms, t.visible_duration_ms
    t.set_project(p); t.refresh_media_graph()
    assert (t.visible_start_ms, t.visible_duration_ms) == window
    assert p.to_dict() == before
    t.fit_all_time()
    assert t.visible_duration_ms > t._project_duration_ms and t.visible_start_ms == 0


def test_resize_preserves_manual_pixels_per_second(timeline):
    t = timeline; app = QApplication.instance()
    t.set_visible_window(8000, 18000)
    scale = (t._content_right()-t.TRACK_HEADER_WIDTH)/t.visible_duration_ms
    t.resize(1450, 650); app.processEvents()
    assert abs((t._content_right()-t.TRACK_HEADER_WIDTH)/t.visible_duration_ms - scale) < .00001
    assert t.visible_start_ms == 8000


def test_trim_preview_never_copies_or_projects_captions(timeline, monkeypatch):
    t = timeline; p = t.project; c = clip(p, 'V2')
    def forbidden(*args): raise AssertionError('caption copied during pointer preview')
    monkeypatch.setattr(StudioCue, '__deepcopy__', forbidden, raising=False)
    before = p.to_dict()
    drag = dict(track_id='V2', clip_id=c.id, mode='trim_right', origin_in=c.timeline_in_ms,
                origin_out=c.timeline_out_ms, group_intervals={}, preview_in=5000, preview_out=23000)
    snapshot = preview_clip_edit(p, drag)
    assert snapshot[0][1].clips[0].timeline_out_ms == 23000
    assert snapshot[1][1].clips[0].timeline_out_ms == 23000
    assert p.to_dict() == before


def test_range_drag_is_preview_only_and_one_undo(timeline):
    t = timeline; p = t.project; stack = QUndoStack()
    set_range(p, 8000, 17000)
    t.range_edit_committed.connect(lambda a,b:set_range(p,a,b,stack))
    pos = QPoint(round(t._time_to_x(8000)), 5)
    assert t._range_press(pos)
    target_x=pos.x()+4000*(t._content_right()-t.TRACK_HEADER_WIDTH)/t.visible_duration_ms
    t._range_move(QPointF(target_x,5), Qt.NoModifier)
    assert range_points(p) == (8000,17000)
    assert abs(t._range_preview[0]-12000)<=1 and t._range_preview[1]==17000
    t._range_release()
    applied=validated_range(p)
    assert stack.count() == 1 and abs(applied[0]-12000)<=1 and applied[1]==17000
    stack.undo(); assert validated_range(p) == (8000,17000)
    stack.redo(); assert validated_range(p) == applied


@pytest.mark.parametrize('index',[0,1])
def test_grabbing_center_of_range_flag_keeps_endpoint(timeline,index):
    t=timeline;set_range(t.project,8000,17000)
    handle=next(h for h in t._range_handles() if h[0]==index)
    center=handle[3].center()
    assert t._range_press(center)
    t._range_move(center,Qt.NoModifier)
    assert t._range_preview==(8000,17000)
    t._range_release(cancel=True)


def test_range_crossing_cancel_and_offscreen(timeline):
    t = timeline; p = t.project; set_range(p,8000,17000)
    t._range_press(QPoint(round(t._time_to_x(8000)),5))
    t._range_move(QPointF(t._time_to_x(20000),5), Qt.AltModifier)
    assert t._range_preview == (16999,17000)
    QTest.keyClick(t,Qt.Key_Escape)
    assert t._range_preview is None and range_points(p) == (8000,17000)
    t.set_visible_window(20000,10000)
    handles = t._range_handles()
    assert all(h[-1] == -1 for h in handles)
    assert range_points(p) == (8000,17000)


def test_decode_observations_cannot_pull_view_during_trim(timeline):
    from time import perf_counter
    t = timeline;t.set_visible_window(300000,1000)
    before=t.visible_start_ms,t.visible_duration_ms
    t._clip_drag={'mode':'trim_right'}
    assert not t.reveal_playhead(2500)
    t._clip_drag=None;t._follow_suspended_until=perf_counter()+2
    assert not t.reveal_playhead(2500)
    assert (t.visible_start_ms,t.visible_duration_ms)==before


def test_high_zoom_draw_bounds_do_not_alias_viewport_as_edge(timeline, monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    import twobyteasr.studio.studio_video_track as paint
    t=timeline;t.set_visible_window(300000,1000)
    p=t.project;seq=sequence_of(p)
    assert t._time_to_x(seq.segments[0].timeline_out_ms)>1_000_000
    image=QImage(t.size(),QImage.Format_ARGB32);painter=QPainter(image)
    drawn=[]
    class RecordingPainter:
        def __getattr__(self,name):return getattr(painter,name)
        def drawRoundedRect(self,rect,*args):
            drawn.append(QRectF(rect));painter.drawRoundedRect(rect,*args)
        def drawPath(self,path):
            drawn.append(path.boundingRect());painter.drawPath(path)
    paint.paint_video_track(RecordingPainter(),seq,t._timeline_palette(),t._video_track_rect('V1'),
                           t.TRACK_HEADER_WIDTH,t._content_right(),t._time_to_x,'',None,False,False,False)
    painter.end()
    bodies=[r for r in drawn if r.width()>(t._content_right()-t.TRACK_HEADER_WIDTH)*.5]
    assert bodies
    assert all(r.left()>=t.TRACK_HEADER_WIDTH-17 and r.right()<=t._content_right()+17 for r in bodies)
    assert any(r.left()<t.TRACK_HEADER_WIDTH and r.right()>t._content_right() for r in bodies)


def test_trim_edge_scroll_is_bounded_and_keeps_scale(timeline):
    t=timeline;edit(t.project,'V2','trim',start=5000,end=20000)
    t.refresh_media_graph();t.set_visible_window(5000,15000)
    c=clip(t.project,'V2');pos=point(t,c.timeline_out_ms)
    t._begin_video_drag('V2',c,SimpleNamespace(position=lambda:QPointF(pos)))
    t._clip_drag['moved']=True
    pointer=QPointF(t._content_right()-2,pos.y())
    t._update_clip_drag(pointer,Qt.NoModifier)
    before=t.visible_start_ms
    step_limit=16*t.visible_duration_ms/(t._content_right()-t.TRACK_HEADER_WIDTH)+1
    for _ in range(5):
        t._scroll_clip_drag()
        assert 0<=t.visible_start_ms-before<=step_limit
        assert t.visible_duration_ms==15000
        before=t.visible_start_ms
    assert before>5000 and c.timeline_out_ms==20000
    t._clip_drag['limit']='已到可用素材结尾'
    t._scroll_clip_drag()
    assert t.visible_start_ms==before and not t._clip_scroll_timer.isActive()
