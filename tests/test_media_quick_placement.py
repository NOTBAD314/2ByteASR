"""2026-11-18 (user): adding GIFs, pictures, clips and audio should be as direct as in
Premiere / 剪映, without track glitches.

Before: in an ordinary project (one main video on V1) every drag from the
media pool was refused, a picture-only track got an empty audio row that the
height budget did not count (lanes overlapped, the top track covered the
subtitle rows), and PNG / JPG files could not be added at all.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fractions import Fraction
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.media.animated_gif import (GifFrames, STILL_IMAGE_DURATION_MS, STILL_IMAGE_MAX_SIDE,
                                           is_frame_image, prepare_gif, sampling_fps)
from twobyteasr.media.media_ingest import ingest_media
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio import studio_video_canvas
from twobyteasr.studio.studio_media_drop import MediaDropCommand
from twobyteasr.studio.studio_source_monitor import source_mime
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.timeline.source_selection import (SourceInsertCommand, SourceSelection, resolve_insert_targets)
from twobyteasr.timeline.studio_clip_edit import clip_edit_command
from twobyteasr.timeline.studio_media_pool import add_media_asset, create_video_track

FFMPEG = Path(__file__).resolve().parents[1] / 'tools/ffmpeg/bin/ffmpeg.exe'


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def make_gif(path):
    frames = []
    for x, color in [(0, 'red'), (20, 'lime'), (40, 'yellow')]:
        image = Image.new('RGBA', (80, 60), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((x, 10, x + 15, 30), fill=color)
        frames.append(image)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=[100, 300, 200], loop=0, disposal=2)
    return path


def make_picture(path, size=(120, 80), color=(200, 40, 40, 255)):
    image = Image.new('RGBA', size, (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((10, 10, size[0] - 10, size[1] - 10), fill=color)
    if path.suffix.lower() in ('.jpg', '.jpeg', '.bmp'):
        image = image.convert('RGB')
    image.save(path)
    return path


def base_project(tmp_path):
    """One 30 s main video on V1 / A1, and a clip, a song and a GIF in the pool."""
    for name in ("main.mp4", "clip.mp4", "song.wav"):
        (tmp_path / name).write_bytes(b"x")
    make_gif(tmp_path / "anim.gif")
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / "main.mp4"), display_name="main.mp4",
                                                duration_ms=30_000, fingerprint="main", width=1920, height=1080),
                              cues=[StudioCue("cue", 0, 1_000, "你好")])
    project.validate()
    project.media_pool[0].audio_metadata["has_audio"] = True
    add_media_asset(project, tmp_path / "clip.mp4", fingerprint="clip", duration_ms=4_000,
                    video_metadata={"has_video": True}, audio_metadata={"has_audio": True}, materialize_audio=False)
    add_media_asset(project, tmp_path / "song.wav", fingerprint="song", duration_ms=6_000,
                    video_metadata={"has_video": False}, audio_metadata={"has_audio": True}, materialize_audio=False)
    add_media_asset(project, tmp_path / "anim.gif", fingerprint="gif", duration_ms=600,
                    video_metadata={"has_video": True, "width": 80, "height": 60},
                    audio_metadata={"has_audio": False}, materialize_audio=False)
    project.validate()
    return project


def asset_id(project, name):
    return next(a.asset_id for a in project.media_pool if a.display_name == name)


def selection(project, name, mode='auto'):
    return SourceSelection.capture(project, asset_id(project, name), mode)


# ---------------------------------------------------------------- where it lands

def test_taken_spot_moves_up_and_reuses_free_tracks(tmp_path):
    project = base_project(tmp_path)
    gif = selection(project, 'anim.gif')
    # V1 is full at 2 s: a new track, not a refusal.
    assert resolve_insert_targets(project, gif, 2_000, 'V1') == ('new', 'new')
    SourceInsertCommand(project, gif, 2_000, 'new').redo()
    # The next one at another time shares that track, pointer or not.
    assert resolve_insert_targets(project, gif, 9_000, 'V1')[0] == 'V2'
    assert resolve_insert_targets(project, gif, 9_000)[0] == 'V2'
    # The same time again: V2 is taken there too.
    assert resolve_insert_targets(project, gif, 2_100)[0] == 'new'
    # Past the end of the main video, pointing at V1 appends to it.
    assert resolve_insert_targets(project, gif, 40_000, 'V1')[0] == 'V1'
    # Without pointing at it, the main track is left to the main video.
    assert resolve_insert_targets(project, gif, 40_000)[0] == 'V2'


def test_clip_with_sound_needs_its_audio_lane_free_and_skips_locked(tmp_path):
    project = base_project(tmp_path)
    clip = selection(project, 'clip.mp4')
    SourceInsertCommand(project, clip, 2_000, 'new').redo()            # V2 + its A lane
    lane = next(g.audio_track_id for g in project.av_track_groups if g.video_track_id == 'V2')
    song = selection(project, 'song.wav')
    SourceInsertCommand(project, song, 10_000, audio_target=lane).redo()  # sound alone on V2's lane
    assert resolve_insert_targets(project, clip, 10_000)[0] == 'new'      # picture free, lane taken
    assert resolve_insert_targets(project, selection(project, 'clip.mp4', 'video'), 10_000)[0] == 'V2'
    project.video_tracks[1].locked = True
    assert resolve_insert_targets(project, clip, 20_000, 'V2')[0] == 'new'


def test_sound_alone_reuses_a_free_standalone_lane(tmp_path):
    project = base_project(tmp_path)
    song = selection(project, 'song.wav')
    assert resolve_insert_targets(project, song, 2_000, 'V1', '') == ('new', 'new')
    assert resolve_insert_targets(project, song, 2_000, '', 'A1') == ('new', 'new')   # A1 is taken there
    assert resolve_insert_targets(project, song, 40_000, '', 'A1') == ('new', 'A1')   # free after the end
    command = SourceInsertCommand(project, song, 2_000, 'new', 'new'); command.redo()
    lane = command.placement['audio_track_id']
    assert resolve_insert_targets(project, song, 12_000) == ('new', lane)
    assert resolve_insert_targets(project, song, 3_000) == ('new', 'new')


# ---------------------------------------------------------------- in the window

@pytest.fixture
def page(tmp_path, monkeypatch):
    path = save_project(base_project(tmp_path), tmp_path / "av.2byteproj")
    monkeypatch.setattr(studio_video_canvas.MpvCanvas, "load", lambda self, media_path, *_a, **_k: None)
    studio = SubtitleStudioPage()
    monkeypatch.setattr(studio, "_generate_waveform", lambda *_args, **_kwargs: None)
    studio.resize(1600, 1000)
    studio.show()
    studio.open_project(path)
    settle()
    yield studio
    studio.close_page()
    studio.deleteLater()


def settle():
    for _ in range(10):
        QApplication.processEvents()


def lane_point(page, kind, track_id, ms):
    timeline = page.timeline
    rects = timeline._video_track_rects() if kind == "video" else timeline._audio_track_rects()
    return QPoint(round(timeline._time_to_x(ms)) + 2, round(rects[track_id].center().y()))


def drag(page, name, point, *, drop=True):
    timeline = page.timeline
    mime = source_mime(page.project, selection(page.project, name))
    args = (Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(timeline, QDragEnterEvent(point, *args))
    QApplication.sendEvent(timeline, QDragMoveEvent(point, *args))
    overlay = page.source_timeline_drop.overlay
    seen = dict(message=overlay.message, placement=dict(overlay.placement or {}),
                ghosts=overlay.ghost_rows() if not overlay.message else [])
    if drop:
        QApplication.sendEvent(timeline, QDropEvent(QPointF(point), *args))
        settle()
    return seen


def clips(project, name):
    wanted = asset_id(project, name)
    return [(t.id, c.timeline_in_ms, c.timeline_out_ms) for t in (*project.video_tracks, *project.audio_tracks)
            for c in t.clips if c.asset_id == wanted]


def lanes_are_sound(page):
    timeline, project = page.timeline, page.project
    videos, audios = timeline._video_track_rects(), timeline._audio_track_rects()
    assert set(videos) == {t.id for t in project.video_tracks}
    assert set(audios) == {t.id for t in project.audio_tracks}       # no row for a lane that does not exist
    rows = sorted([*videos.values(), *audios.values()], key=lambda r: r.top())
    for upper, lower in zip(rows, rows[1:]):
        assert upper.bottom() <= lower.top() + .5                     # nothing overlaps
    assert rows[0].top() >= timeline._stack_bottom() - timeline._pinned_bottom_height() - .5
    assert rows[-1].bottom() <= timeline._canvas_bottom() + .5        # nothing is cut off


def test_every_drop_lands_and_lanes_stay_apart(page):
    timeline, project = page.timeline, page.project
    before = page.undo_stack.count()
    seen = drag(page, 'anim.gif', lane_point(page, 'video', 'V1', 2_000))
    assert not seen['message'] and seen['placement']['video_track_id'] == 'new'
    assert seen['ghosts'] and seen['ghosts'][0][1] is True            # drawn as a new track
    assert [c[0] for c in clips(project, 'anim.gif')] == ['V2']
    lanes_are_sound(page)                                             # the GIF track has no empty A row
    assert len(project.audio_tracks) == 1
    # On the ruler: still lands, on the track that is free at that time.
    seen = drag(page, 'anim.gif', QPoint(round(timeline._time_to_x(12_000)), 8))
    assert not seen['message'] and seen['placement']['video_track_id'] == 'V2'
    # A clip with sound over the main video, then sound alone over the picture.
    drag(page, 'clip.mp4', lane_point(page, 'video', 'V1', 2_000))
    drag(page, 'song.wav', lane_point(page, 'video', 'V1', 2_000))
    drag(page, 'anim.gif', lane_point(page, 'video', 'V1', 2_050))    # a third layer at the same time
    assert page.undo_stack.count() == before + 5
    assert len(clips(project, 'clip.mp4')) == 2 and clips(project, 'clip.mp4')[0][0] == 'V3'   # picture + its sound
    assert len(clips(project, 'song.wav')) == 1
    assert {c[0] for c in clips(project, 'anim.gif')} == {'V2', 'V4'}
    lanes_are_sound(page)
    for _ in range(5):
        page.undo_stack.undo()
    settle()
    assert [t.id for t in project.video_tracks] == ['V1'] and [t.id for t in project.audio_tracks] == ['A1']
    lanes_are_sound(page)


def test_drop_snaps_to_the_playhead_and_track_name_means_playhead(page):
    timeline = page.timeline
    timeline.playhead_ms = 10_000
    near = QPoint(round(timeline._time_to_x(10_000)) + 5, lane_point(page, 'video', 'V1', 0).y())
    assert drag(page, 'anim.gif', near, drop=False)['placement']['start_ms'] == 10_000
    header = QPoint(40, lane_point(page, 'video', 'V1', 0).y())
    seen = drag(page, 'clip.mp4', header)
    assert not seen['message'] and seen['placement']['start_ms'] == 10_000
    assert clips(page.project, 'clip.mp4')[0][1] == 10_000


def test_plus_adds_at_the_playhead_in_one_undo_step(page):
    panel, project = page.media_pool_panel, page.project
    assert panel.quick_add_button.isEnabled() is False               # nothing selected yet
    view = panel.assets

    def row():   # looked up each time: adding a clip resets the pool model
        return next(panel.proxy.index(r, 0) for r in range(panel.proxy.rowCount())
                    if panel.proxy.index(r, 0).data(Qt.ItemDataRole.UserRole) == asset_id(project, 'anim.gif'))
    view.setCurrentIndex(row())
    assert panel.quick_add_button.isEnabled()
    page.timeline.playhead_ms = 5_000
    before = page.undo_stack.count()
    panel.quick_add_button.click(); settle()
    assert clips(project, 'anim.gif') == [('V2', 5_000, 5_600)]
    # The "+" of the card does the same; a second add at the same time stacks.
    from PySide6.QtTest import QTest
    assert view.currentIndex() == row()                                # the card stays selected after adding
    plus = view.plus_rect(view.visualRect(row())).center().toPoint()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, plus); settle()
    assert sorted(c[0] for c in clips(project, 'anim.gif')) == ['V2', 'V3']
    assert page.undo_stack.count() == before + 2
    assert panel.add_to_timeline(asset_id(project, 'song.wav')) is True
    lanes_are_sound(page)
    page.undo_stack.undo(); page.undo_stack.undo(); page.undo_stack.undo(); settle()
    assert clips(project, 'anim.gif') == [] and clips(project, 'song.wav') == []


def test_source_preview_inserts_on_a_free_track_by_default(page, monkeypatch):
    monitor, project = page.source_monitor, page.project
    monkeypatch.setattr(monitor, '_load_current', lambda: None)
    monitor.open_asset(asset_id(project, 'anim.gif'))
    assert monitor.video_target.currentData() == 'auto'
    page.timeline.playhead_ms = 3_000
    monitor.insert(); settle()
    page.timeline.playhead_ms = 8_000
    monitor.insert(); settle()
    assert [c[0] for c in clips(project, 'anim.gif')] == ['V2', 'V2']   # used to be a new track each time
    lanes_are_sound(page)


# ---------------------------------------------------------------- pictures

@pytest.mark.parametrize('name', ['photo.png', 'photo.jpg', 'photo.webp', 'photo.bmp'])
def test_a_picture_is_a_five_second_source_without_sound(tmp_path, name):
    path = make_picture(tmp_path / name)
    assert is_frame_image(path)
    _, meta = prepare_gif(path)
    assert (meta['frame_count'], meta['duration_ms'], meta['width'], meta['height']) == (1, STILL_IMAGE_DURATION_MS, 120, 80)
    assert sampling_fps(meta) == 30
    result = ingest_media(path, generation=1, project_token='p')
    assert not result.error and result.duration_ms == STILL_IMAGE_DURATION_MS
    assert result.has_video and not result.has_audio and (result.width, result.height) == (120, 80)
    frames = GifFrames(path)
    first, start, end, index = frames.frame_at(0)
    later = frames.frame_at(12_345)                                   # the same picture however long the clip is
    assert first == later[0] and index == later[3] == 0 and (start, end) == (0, STILL_IMAGE_DURATION_MS)
    frames.close()


def test_picture_drops_above_the_main_video_and_stretches(tmp_path):
    project = base_project(tmp_path)
    result = ingest_media(make_picture(tmp_path / 'logo.png'), generation=1, project_token='p')
    undo = QUndoStack()
    audio_before = len(project.audio_tracks)
    undo.push(MediaDropCommand(project, [result], 40_000))            # past the end, not pointing at a track
    track = project.video_tracks[-1]
    clip = track.clips[0]
    assert track.id == 'V2' and (clip.timeline_in_ms, clip.timeline_out_ms) == (40_000, 45_000)
    assert len(project.audio_tracks) == audio_before                  # no empty audio lane for a picture
    undo.push(clip_edit_command(project, track.id, 'trim', clip_id=clip.id, start=40_000, end=70_000))
    clip = project.video_tracks[-1].clips[0]
    assert clip.timeline_out_ms - clip.timeline_in_ms == 30_000       # longer than the nominal 5 s
    # From the pool: the same source lands like a GIF does.
    picture = SourceSelection.capture(project, clip.asset_id)
    assert picture.mode == 'video' and resolve_insert_targets(project, picture, 2_000, 'V1')[0] == 'V2'
    undo.undo(); undo.undo()
    assert [t.id for t in project.video_tracks] == ['V1']


def test_large_photo_is_scaled_once_and_export_reads_it(tmp_path):
    path = make_picture(tmp_path / 'big.jpg', size=(6000, 3000))
    _, meta = prepare_gif(path)
    assert (meta['width'], meta['height']) == (STILL_IMAGE_MAX_SIDE, STILL_IMAGE_MAX_SIDE // 2)
    from twobyteasr.exports.export_media import SequentialExportDecoder, probe_media
    decoder = SequentialExportDecoder(probe_media(FFMPEG, path))
    pixels, receipt = decoder.read(Fraction(7))
    assert pixels[:2] == (meta['width'], meta['height']) and receipt['gif_frame_id'] == 0
    decoder.close()


def test_picture_only_track_keeps_no_audio_row_in_a_saved_project(tmp_path):
    from twobyteasr.projects.studio_project import load_project
    project = base_project(tmp_path)
    create_video_track(project)                                       # an empty V2 with its A lane, as 新建视频轨 makes
    result = ingest_media(make_picture(tmp_path / 'logo.png'), generation=1, project_token='p')
    MediaDropCommand(project, [result], 1_000, 'V2').redo()
    lanes = len(project.audio_tracks)
    reopened = load_project(save_project(project, tmp_path / 'saved.2byteproj'))
    assert len(reopened.audio_tracks) == lanes
    assert [len(t.clips) for t in reopened.video_tracks] == [1, 1]


def test_preview_decoder_shows_a_picture_at_any_clip_time(tmp_path):
    """The preview worker serves a picture from the frame cache, like a GIF."""
    import time
    from twobyteasr.playback.secondary_video import SecondaryVideoSource
    app = QApplication.instance() or QApplication([])
    path = make_picture(tmp_path / 'logo.png', size=(160, 90), color=(20, 30, 240, 255))
    source = SecondaryVideoSource()
    try:
        source.prepare(str(path))
        for ms in (0, 12_000):                                        # 12 s: past the nominal 5 s
            source.request_frame(ms, paused=True, seek=True)
            end = time.monotonic() + 8
            while time.monotonic() < end and not (not source.image.isNull() and source.pts_ms <= ms < source.frame_end_ms):
                app.processEvents(); time.sleep(.005)
            assert not source.image.isNull() and source.pts_ms <= ms < source.frame_end_ms
            color = source.image.pixelColor(80, 45)
            assert color.blue() > 200 and color.red() < 60
            assert source.image.pixelColor(2, 2).alpha() == 0         # transparency is kept
    finally:
        source.close()


def test_export_shows_the_picture_over_the_main_video(tmp_path):
    """Actual encode: red main video, a blue picture on a new track from 1 s to 3 s."""
    import av
    from twobyteasr.exports.export_timeline import write_export_ass
    from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job
    from twobyteasr.exports.video_export import capture_video_graph
    from twobyteasr.system.processes import run_hidden_subprocess
    main = tmp_path / 'main.mp4'
    run_hidden_subprocess([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=25:d=4',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=4', '-c:v', 'libx264',
        '-preset', 'ultrafast', '-threads', '2', '-c:a', 'aac', str(main)],
        purpose='picture overlay export fixture', check=True, timeout=30)
    picture = tmp_path / 'blue.png'
    Image.new('RGBA', (160, 90), (0, 0, 255, 255)).save(picture)
    project = SubtitleProject(media=StudioMedia(str(main), duration_ms=4000, width=160, height=90))
    project.validate()
    result = ingest_media(picture, generation=1, project_token='p')
    MediaDropCommand(project, [result], 1_000).redo()
    track = project.video_tracks[-1]
    assert track.id == 'V2'
    clip_edit_command(project, track.id, 'trim', clip_id=track.clips[0].id, start=1_000, end=3_000).redo()
    ass = tmp_path / 'empty.ass'; write_export_ass(project, ass, fps=25)
    job = RenderJob(str(main), str(ass), str(tmp_path / 'output.mp4'),
                    RenderSettings(encoder='libx264', width=160, height=90, fps=25, audio_codec='aac', preset='ultrafast'),
                    duration_seconds=4, video_graph=capture_video_graph(project))
    run_render_job(FFMPEG, job)
    with av.open(job.output_path) as container:
        frames = [f.to_ndarray(format='rgb24').mean(axis=(0, 1)) for f in container.decode(video=0)]
        assert container.streams.audio                                # the main video's sound is still there
    assert len(frames) == 100
    for index, blue in ((12, False), (50, True), (70, True), (88, False)):
        red, _green, b = frames[index]
        assert (b > red + 100) if blue else (red > b + 100), (index, frames[index])
