"""Entry/exit-only animated captions: browser renders entrance/exit, a still covers the hold.

The split must be invisible: every output frame equals the all-frames render.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path

import av
import numpy as np
import pytest

from twobyteasr.system.processes import run_hidden_subprocess

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    instance = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont(str(ROOT/'assets/fonts/SourceHanSansSC-Medium.otf'))
    return instance


def _project(tmp_path, *, hold_motion=None, overlapping=False, bilingual=False, motion=None):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
    source = tmp_path / 'source.mp4'
    if not source.exists():
        run_hidden_subprocess([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x204060:s=320x180:r=30:d=4',
                               '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4', '-c:v', 'libx264', '-c:a', 'aac',
                               str(source)], purpose='hold still fixture', check=True, timeout=60)
    spans = [(200, 1300), (1500, 2600), (2700, 3800)] if not overlapping else [(200, 1800), (1000, 2600)]
    project = SubtitleProject(media=StudioMedia(str(source), duration_ms=4000, width=320, height=180),
        styles=[SubtitleStyle('g', 'Fade', font_size=40, font_family='Source Han Sans SC', font_weight=500)],
        cues=[StudioCue(str(i), a, b, f'字幕 {i}', style_id='g') for i, (a, b) in enumerate(spans)])
    motion = dict(motion or dict(mode='fade', entry=dict(type='fade', duration=250), exit=dict(type='fade', duration=250)))
    if hold_motion:
        motion['hold'] = hold_motion
    project.style_recipes['g'] = {'name': 'Fade', 'engine': 'remotion', 'motion': motion, 'colors': {
        'fill': {'type': 'linear-gradient', 'angle': 0, 'stops': [
            {'position': 0, 'color': '#FFFFE040'}, {'position': 1, 'color': '#FF40E0FF'}]}}}
    if bilingual:
        project.generation_metadata['translations'] = {c.id: f'Line {c.id}' for c in project.cues}
        project.studio_state['bilingual'] = dict(mode='bilingual', layout='ink_v1', gap_ratio=.13)
    project.validate()
    return project


def _render(project, tmp_path, name, graph=False):
    from twobyteasr.exports.studio_render import RenderJob, RenderSettings
    from twobyteasr.exports.video_export import capture_video_graph
    from twobyteasr.rendering.advanced_renderer import AdvancedRendererBackend
    job = RenderJob(project.media.path, str(tmp_path/'sub.ass'), str(tmp_path/f'{name}.mkv'),
        RenderSettings(container='mkv', encoder='libx264', preset='ultrafast', quality_mode='cq', quality=0,
                       width=320, height=180, fps=30, audio_codec='none', pixel_format='yuv444p'),
        duration_seconds=4.0, video_graph=capture_video_graph(project) if graph else None)
    trace = []
    AdvancedRendererBackend().render(project, FFMPEG, job, trace=lambda k, v: trace.append((k, v)))
    with av.open(job.output_path) as media:
        frames = [f.to_ndarray(format='rgb24').astype(np.int16) for f in media.decode(video=0)]
    return frames, job.completion_metadata, trace


SLIDE = dict(mode='explicit', entrance={'type': 'slide', 'duration_ms': 300, 'direction': 'up'},
             exit={'type': 'fade', 'duration_ms': 200})
POP = dict(mode='explicit', entrance={'type': 'spring_pop', 'duration_ms': 300},
           exit={'type': 'collapse', 'duration_ms': 200})


@pytest.mark.parametrize('bilingual,graph,motion', [(False, False, None), (True, False, SLIDE), (False, True, None),
                                                    (False, True, SLIDE), (False, False, POP)])
def test_held_captions_match_the_all_frames_browser_render(tmp_path, app, monkeypatch, bilingual, graph, motion):
    """Holds are the browser still; entrance/exit frames are native transforms of it.

    Hold frames must equal the all-frames browser render. Entrance/exit
    frames are a close approximation (resampled, not re-rasterized text):
    small average difference, never a missing or doubled caption.
    """
    from twobyteasr.exports import mixed_caption_export
    from twobyteasr.rendering.advanced_renderer import AdvancedRendererBackend
    if not AdvancedRendererBackend().status().available:
        pytest.skip('renderer environment unavailable')
    project = _project(tmp_path, bilingual=bilingual, motion=motion)
    if not bilingual:
        split = mixed_caption_export.split_mixed_captions(project)
        assert split is not None and split[1]._hold_cue_ids == {'0', '1', '2'}
    held, metadata, trace = _render(project, tmp_path, 'held', graph)
    native = [v for k, v in trace if k == 'native_caption_motion']
    if bilingual:
        assert not native, native
    else:
        assert native and native[0]['windows'] >= 6 and native[0]['browser_fallback'] == 0, native
    monkeypatch.setattr(mixed_caption_export, 'hold_candidate', lambda project, cue: False)
    full, _, _ = _render(_project(tmp_path, bilingual=bilingual, motion=motion), tmp_path, 'full', graph)
    assert len(held) == len(full) == 120
    means = [float(np.abs(a - b).mean()) for a, b in zip(held, full)]
    # Middles of the holds (cues at 6-38, 45-77, 81-113): browser pixels.
    for index in [*range(16, 28), *range(55, 67), *range(91, 103)]:
        assert int(np.abs(held[index] - full[index]).max()) <= 8, index
    # Entrance/exit frames: close everywhere (a missing caption averages >1).
    assert max(means) < .35, [(i, round(m, 3)) for i, m in enumerate(means) if m >= .35]
    background = full[0]
    for index in (22, 62, 98):
        assert np.abs(held[index] - background).max() > 40, index


def test_hold_motion_and_overlaps_keep_every_frame(tmp_path):
    from twobyteasr.exports.mixed_caption_export import split_mixed_captions, hold_window
    assert split_mixed_captions(_project(tmp_path, hold_motion=dict(type='float'))) is None
    assert split_mixed_captions(_project(tmp_path, overlapping=True)) is None
    visual = {'motion': {'mode': 'explicit', 'entrance': {'type': 'fade', 'duration_ms': 250},
                         'exit': {'type': 'fade', 'duration_ms': 250}, 'hold': {'type': 'none'}}}
    cue = dict(id='a', startMs=1000, endMs=3000, cueDurationMs=2000, localOffsetMs=0, visual=visual)
    # 30 fps: entrance 8 frames from frame 30, exit starts at frame 30+60-8.
    assert hold_window(cue, 30) == (39, 81)
    assert hold_window(dict(cue, visual={**visual, 'decorations': ['scanline']}), 30) is None
    assert hold_window(dict(cue, visual={**visual, 'wordAnimation': {'units': [1]}}), 30) is None
    assert hold_window(dict(cue, endMs=1500, cueDurationMs=500), 30) is None
