"""Variable-delay/disposal/transparent GIFs, exact time and bounded reuse."""
from pathlib import Path
from fractions import Fraction
import json
import pytest
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.media.animated_gif import GifFrames, prepare_gif, sampling_fps
from twobyteasr.media.media_ingest import ingest_media
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project, load_project
from twobyteasr.studio.studio_media_drop import MediaDropCommand
from twobyteasr.timeline.clip_time_mapper import project_to_source
from twobyteasr.timeline.studio_clip_edit import clip_edit_command
from twobyteasr.exports.export_media import probe_media, SequentialExportDecoder

APP = QApplication.instance() or QApplication([])
FFMPEG = Path(__file__).resolve().parents[1] / 'tools/ffmpeg/bin/ffmpeg.exe'


def make_gif(path, disposal=2):
    frames = []
    for x, color in [(0, 'red'), (20, 'lime'), (40, 'yellow')]:
        image = Image.new('RGBA', (80, 60), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((x, 10, x+15, 30), fill=color)
        frames.append(image)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=[100, 300, 200],
        loop=0, disposal=disposal, optimize=True)
    return path


@pytest.fixture
def gif(tmp_path):
    return make_gif(tmp_path / 'animation.gif')


@pytest.mark.parametrize('disposal', [1, 2, 3])
def test_composed_partial_frames_keep_alpha_and_original_delays(tmp_path, disposal):
    path = make_gif(tmp_path / f'disposal-{disposal}.gif', disposal)
    cache, meta = prepare_gif(path)
    assert meta['frame_durations_ms'] == [100, 300, 200]
    assert meta['duration_ms'] == 600 and meta['loop'] == 0
    source = GifFrames(path)
    with Image.open(path) as reference:
        for i, target in enumerate([0, 100, 400]):
            reference.seek(i)
            pixels, start, end, frame = source.frame_at(target)
            expected = reference.convert('RGBA').tobytes('raw', 'BGRA')
            assert pixels[2] == expected
            assert (start, end, frame) == (target, target+meta['frame_durations_ms'][i], i)
    source.close()


def test_half_open_delay_boundaries_loop_backward_and_pause(gif):
    source = GifFrames(gif)
    targets = [0, 99, 100, 399, 400, 599, 600, 699, 700, 1199, 1200, 101, 101]
    assert [source.frame_at(t)[3] for t in targets] == [0,0,1,1,2,2,0,0,1,2,0,1,1]
    assert source.loads == 3
    source.close()


def test_sampling_lattice_preserves_variable_delay_boundaries(gif):
    _, metadata=prepare_gif(gif)
    assert sampling_fps(metadata)==10
    assert sampling_fps(dict(frame_durations_ms=[20,30,70]))==100
    from twobyteasr.exports.video_export import _video_frame_clock
    from types import SimpleNamespace
    job=SimpleNamespace(settings=SimpleNamespace(fps=0),video_graph={'fps':5,'duration_ms':2400},
        media_path=str(gif),start_seconds=None,duration_seconds=None)
    assert _video_frame_clock(FFMPEG,job)==(10.,0.,2.4,24)


@pytest.mark.parametrize('loop',[None,0,2])
def test_file_loop_metadata_does_not_override_finite_clip_mapping(tmp_path,loop):
    path=tmp_path/'loop.gif'
    frames=[Image.new('RGB',(12,12),color) for color in ('red','green')]
    options={} if loop is None else {'loop':loop}
    frames[0].save(path,save_all=True,append_images=frames[1:],duration=[100,200],**options)
    source=GifFrames(path)
    assert source.metadata['loop']==loop
    assert source.frame_at(100)[0]==source.frame_at(400)[0]
    source.close()


def test_repeated_preparation_reuses_disk_but_deleted_cache_rebuilds(gif):
    path, first = prepare_gif(gif)
    modified = path.stat().st_mtime_ns
    assert prepare_gif(gif) == (path, first)
    assert path.stat().st_mtime_ns == modified
    path.unlink()
    rebuilt, data = prepare_gif(gif)
    assert rebuilt == path and data['frame_starts_ms'] == first['frame_starts_ms']


def test_incomplete_disk_cache_rebuilds_from_original(gif):
    import sqlite3
    from contextlib import closing
    cache, metadata=prepare_gif(gif)
    with closing(sqlite3.connect(cache)) as db:
        db.execute('delete from frames where id=1');db.commit()
    assert prepare_gif(gif)[1]['frame_count']==3
    source=GifFrames(gif)
    assert source.frame_at(200)[3]==1
    source.close()


def test_cache_has_byte_limit_and_releases_all_pixels(gif):
    source = GifFrames(gif, memory_bytes=80*60*4)
    for i in range(40):
        source.frame_at(i*100)
        assert source.cached_bytes <= 80*60*4
    source.close()
    assert source.cached_bytes == 0 and not source.cache


def test_invalid_import_returns_explicit_error_and_cancel_publishes_no_cache(tmp_path):
    broken = tmp_path / 'broken.gif'
    broken.write_bytes(b'not a gif')
    result = ingest_media(broken, generation=1, project_token='p')
    assert result.error and not result.has_audio
    with pytest.raises(InterruptedError):
        prepare_gif(broken, cancelled=lambda: True)


def test_import_move_trim_extend_undo_redo_and_save_reopen(gif, tmp_path):
    result = ingest_media(gif, generation=1, project_token='p')
    assert not result.error and result.duration_ms == 600
    assert result.has_video and not result.has_audio
    project = SubtitleProject(media=StudioMedia(path=''))
    undo = QUndoStack()
    undo.push(MediaDropCommand(project, [result], 0))
    track = project.video_tracks[-1]
    clip = track.clips[0]
    clip_id, track_id = clip.id, track.id
    assert not any(t.clips for t in project.audio_tracks)
    undo.push(clip_edit_command(project, track_id, 'move', clip_id=clip_id, start=1000))
    undo.push(clip_edit_command(project, track_id, 'trim', clip_id=clip_id, start=1100, end=2800))
    clip = next(c for t in project.video_tracks for c in t.clips if c.id == clip_id)
    assert (clip.source_in_ms, clip.source_out_ms) == (100, 1800)
    assert project_to_source(clip, 1100) == 100
    assert project_to_source(clip, 1700) == 700
    assert project_to_source(clip, 2800) is None
    undo.undo(); undo.redo()
    path = save_project(project, tmp_path / 'saved.2byteproj')
    loaded = load_project(path)
    restored = next(c for t in loaded.video_tracks for c in t.clips if c.id == clip_id)
    assert (restored.timeline_in_ms, restored.timeline_out_ms, restored.source_in_ms) == (1100, 2800, 100)
    assert loaded.media_pool[0].canonical_source == str(gif.resolve())


def test_export_decoder_repeats_rgba_for_unwrapped_source_time(gif):
    index = probe_media(FFMPEG, gif)
    decoder = SequentialExportDecoder(index)
    first, receipt = decoder.read(Fraction(1, 5))
    repeated, later = decoder.read(Fraction(4, 5))
    assert first == repeated
    assert receipt['gif_frame_id'] == later['gif_frame_id'] == 1
    assert later['frame_end_ms'] == 1000
    assert first[2][-1] == 0
    decoder.close()


def test_overlay_does_not_create_an_empty_linked_audio_lane(gif, tmp_path):
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path/'video.mp4'), duration_ms=4000))
    project.validate()
    before = len(project.audio_tracks)
    result = ingest_media(gif, generation=1, project_token='p')
    command = MediaDropCommand(project, [result], 1000)
    command.redo()
    assert len(project.audio_tracks) == before
    assert project.video_tracks[-1].clips[0].asset_id != project.video_tracks[0].clips[0].asset_id
    command.undo()
    assert len(project.audio_tracks) == before


def test_long_gif_frame_is_ready_for_playback_through_its_entire_duration():
    from types import SimpleNamespace
    from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin
    source = SimpleNamespace(pts_ms=100,frame_end_ms=400,
        image=SimpleNamespace(isNull=lambda:False),performance_snapshot=lambda:{'state':'READY'})
    layer={'clip_id':'gif','source_ms':350}
    page=SimpleNamespace(audio_engine=SimpleNamespace(ready_for_playback=lambda:True),
        video_compositor=SimpleNamespace(_layers=[layer],_composes_base=False,_players={'gif':source}))
    assert StudioPlaybackFlowMixin._playback_buffers_ready(page)
    layer['source_ms']=450
    assert not StudioPlaybackFlowMixin._playback_buffers_ready(page)
