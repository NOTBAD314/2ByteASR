"""Actual production export with legal Unicode and filter-significant paths."""
from pathlib import Path

import av
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job
from twobyteasr.exports.video_export import capture_video_graph
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
from twobyteasr.rendering.advanced_renderer import AdvancedRendererBackend
from twobyteasr.rendering.ass_compiler import compile_ass
from twobyteasr.system.processes import run_hidden_subprocess


FFMPEG = Path(__file__).resolve().parents[1] / 'tools/ffmpeg/bin/ffmpeg.exe'
REPORTED_NAME = '[10-23-26] cerberVT - FNAF IN VR ＊GONE WRONG＊ ＊COPS WERE CALLED＊ ↜૮^ ＞ω＜^ა 💜🦴 !patreon.mp4'


@pytest.mark.parametrize('backend', ['native', 'static', 'direct-static', 'mixed-static'])
@pytest.mark.parametrize('directory', ['中文💜🦴', "O'Brien [片段];逗号,百分% &!#="])
def test_special_paths_export_and_decode(tmp_path, backend, directory):
    app = QApplication.instance() or QApplication([])
    folder = tmp_path / directory
    folder.mkdir()
    media = folder / REPORTED_NAME
    run_hidden_subprocess(
        [FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
         'color=c=0x202020:s=320x180:r=30:d=1', '-f', 'lavfi', '-i',
         'sine=frequency=440:duration=1', '-c:v', 'libx264', '-threads', '2',
         '-c:a', 'aac', media], check=True, timeout=30, purpose='special filename fixture')
    original = media.read_bytes()
    project = SubtitleProject(
        media=StudioMedia(str(media), duration_ms=1000, width=320, height=180),
        styles=[SubtitleStyle('g', 'Caption', font_size=90)],
        cues=[StudioCue('a', 0, 900, 'PATH OK', style_id='g')])
    if backend != 'native':
        project.style_recipes['g'] = {
            'name': 'Gradient', 'engine': 'remotion', 'motion': {'mode': 'none'},
            'colors': {'fill': {'type': 'linear-gradient', 'angle': 0, 'stops': [
                {'position': 0, 'color': '#FFFF0000'},
                {'position': 1, 'color': '#FF00FFFF'}]}}}
    if backend == 'mixed-static':
        project.styles.append(SubtitleStyle('n', 'Native', font_size=50))
        project.cues.append(StudioCue('b', 0, 900, 'NATIVE', style_id='n'))
    project.validate()
    ass = folder / "字幕 O'Brien [0];百分%.ass"
    ass.write_text(compile_ass(project), encoding='utf-8-sig')
    output = folder / "成品 O'Brien [1],100% 💜🦴.mp4"
    previews = []
    job = RenderJob(str(media), str(ass), str(output),
        RenderSettings(encoder='libx264', preset='ultrafast', width=320, height=180,
                       fps=30, audio_codec='aac'), duration_seconds=1,
        video_graph=capture_video_graph(project) if backend == 'direct-static' else None,
        preview_callback=(lambda *args: previews.append(args)) if backend != 'native' else None)
    if backend == 'native':
        run_render_job(FFMPEG, job)
    else:
        AdvancedRendererBackend().render(project, FFMPEG, job)
        assert previews
    with av.open(str(output)) as container:
        frames = list(container.decode(video=0))
    assert len(frames) == 30
    rgb = frames[5].to_ndarray(format='rgb24').astype(int)
    if backend == 'native':
        assert np.count_nonzero(rgb.min(axis=2) > 180) > 10
    else:
        assert np.count_nonzero((rgb[:, :, 0] > 120) & (rgb[:, :, 0] > rgb[:, :, 1] + 30)) > 5
    with av.open(str(output)) as container:
        assert sum(frame.samples for frame in container.decode(audio=0)) > 40000
    assert media.name == REPORTED_NAME and media.read_bytes() == original
