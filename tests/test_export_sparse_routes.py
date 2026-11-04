"""Route proofs retain clocks, visibility and authored compositing order."""
from copy import deepcopy
from pathlib import Path

import pytest

from twobyteasr.exports.mixed_caption_export import split_mixed_captions
from twobyteasr.exports.timeline_media import export_range_graph
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle


def project():
    value = SubtitleProject(media=StudioMedia('source.mp4', duration_ms=10000, width=320, height=180),
        styles=[SubtitleStyle('default', 'Default')], cues=[
            StudioCue('s', 0, 2000, '静态', style_id='static'),
            StudioCue('m', 4000, 6000, '动效', style_id='moving')])
    value.style_recipes['static'] = dict(name='Static', engine='remotion', motion=dict(mode='none'))
    value.style_recipes['moving'] = dict(name='Moving', engine='remotion', motion=dict(mode='explicit', entrance=dict(type='fade', duration=200)))
    return value


def test_mixed_split_requires_disjoint_time_spans_and_does_not_modify_cues():
    value = project()
    static, moving = split_mixed_captions(value)
    assert [c.id for c in static.cues] == ['s'] and [c.id for c in moving.cues] == ['m']
    assert [c.id for c in value.cues] == ['s', 'm']
    value.cues[1].start_ms = 1999
    assert split_mixed_captions(value) is None
    value.cues[1].start_ms = 2000
    assert split_mixed_captions(value) is not None  # half-open seam is safe


def test_web_theme_ambient_cannot_be_cut_to_its_cue_window(monkeypatch):
    from twobyteasr.rendering import advanced_renderer as renderer
    value = project()
    monkeypatch.setattr(renderer, 'split_renderer_cues', lambda p: ([], p.cues))
    monkeypatch.setattr(renderer, 'recipe_payload_for_cue', lambda p, cue:
        {'webTheme': {'ambient': 'composition-wide'}} if cue.id == 'm' else {'motion': {'mode':'none'}})
    assert split_mixed_captions(value) is None


def test_route_ignores_hidden_and_out_of_range_motion():
    from twobyteasr.rendering.advanced_renderer import project_requires_advanced
    from twobyteasr.exports.static_caption_export import static_graph_project
    from twobyteasr.projects.studio_project import StudioSpeaker
    value = project()
    assert static_graph_project(value, start_ms=0, end_ms=2000)
    assert not static_graph_project(value, start_ms=0, end_ms=6000)
    value.cues[1].speaker_id = 'hidden'
    value.speakers = [StudioSpeaker('hidden', 'Hidden', hidden=True)]
    assert static_graph_project(value)
    value.cues = value.cues[1:]
    assert not project_requires_advanced(value)


def test_range_pruning_precedes_preparation_and_retains_transition_expansion():
    graph = dict(media_pool=[], duration_ms=10000, audio_mix=[
        dict(source_path='first.mp4', timeline_in_ms=0, timeline_out_ms=2000),
        dict(source_path='missing.mp4', timeline_in_ms=4000, timeline_out_ms=8000)],
        video_tracks=[dict(id='V1', enabled=True, clips=[
            dict(id='first', asset_id='a', timeline_in_ms=0, timeline_out_ms=2000),
            dict(id='outside', asset_id='missing', timeline_in_ms=4000, timeline_out_ms=8000)]),
            dict(id='V2', enabled=False, clips=[dict(id='hidden', asset_id='x', timeline_in_ms=0, timeline_out_ms=10000)])])
    frozen = deepcopy(graph)
    pruned = export_range_graph(graph, 0, 2)
    assert graph == frozen
    assert [c['id'] for t in pruned['video_tracks'] for c in t['clips']] == ['first']
    assert [a['source_path'] for a in pruned['audio_mix']] == ['first.mp4']
    assert pruned['duration_ms'] == 10000


def test_static_captions_preserve_complex_video_precomposition(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from dataclasses import replace
    from twobyteasr.rendering import advanced_renderer as renderer
    from twobyteasr.exports import static_caption_export, export_filtergraph, timeline_media, video_export
    from twobyteasr.exports.studio_render import RenderJob
    value = project()
    value.cues = value.cues[:1]
    job = RenderJob('input.mp4', '', str(tmp_path/'out.mp4'), duration_seconds=2,
                    video_graph={'complex_transform': True})
    visited = []
    monkeypatch.setattr(renderer, 'project_requires_advanced', lambda p: True)
    monkeypatch.setattr(static_caption_export, 'static_graph_project', lambda p: True)
    monkeypatch.setattr(export_filtergraph, 'simple_video_clips', lambda g: None)
    monkeypatch.setattr(timeline_media, 'export_range_graph', lambda g, *a: g)
    monkeypatch.setattr(timeline_media, 'resolve_video_graph', lambda g, *a, **k: g)
    monkeypatch.setattr(renderer.AdvancedRendererBackend, 'require_available', lambda self: None)
    @contextmanager
    def prepare(ffmpeg, current, **kwargs):
        visited.append('complex video')
        yield replace(current, video_graph=None, composition_resolved=True)
    monkeypatch.setattr(video_export, 'prepared_video_job', prepare)
    def static(p, ffmpeg, current, **kwargs):
        assert current.composition_resolved and current.video_graph is None
        visited.append('captions')
        return Path(current.output_path)
    monkeypatch.setattr(static_caption_export, 'render_static_graph', static)
    result = renderer.AdvancedRendererBackend().render(value, 'ffmpeg', job)
    assert result == Path(job.output_path) and visited == ['complex video', 'captions']


def test_identity_media_does_not_build_a_full_pts_index(tmp_path, monkeypatch):
    from twobyteasr.exports import video_export
    from twobyteasr.exports.studio_render import RenderJob, RenderSettings
    from twobyteasr.exports.timeline_media import TIME_CONTRACT
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'unused decoder: graph identity is the proof')
    graph = dict(media_time_contract=TIME_CONTRACT, duration_ms=10000, width=320, height=180, fps=30,
        media_pool=[dict(asset_id='a', canonical_source=str(source))],
        video_tracks=[dict(id='V1', clips=[dict(id='one', asset_id='a', source_in_ms=0, source_out_ms=10000,
            timeline_in_ms=0, timeline_out_ms=10000, playback_rate=1)])], audio_mix=[dict(source_path=str(source), source_in_ms=0, timeline_in_ms=0,
            timeline_out_ms=10000, gain_db=0, playback_rate=1)])
    monkeypatch.setattr(video_export, 'preflight_video_job', lambda *a, **k: pytest.fail('identity path must not decode a full source index'))
    monkeypatch.setattr('twobyteasr.exports.studio_render.media_has_audio', lambda *a: False)
    job = RenderJob(str(source), '', str(tmp_path/'out.mp4'), RenderSettings(fps=30),
                    duration_seconds=2, video_graph=graph)
    with video_export.prepared_video_job(tmp_path/'ffmpeg.exe', job) as prepared:
        assert prepared.video_graph is None and not prepared.composition_resolved
        assert prepared.duration_seconds == 2 and prepared.media_path == str(source)


def test_sparse_integer_frame_boundaries_do_not_round_trip_through_float(tmp_path):
    from PIL import Image
    from twobyteasr.exports.static_caption_timeline import build_caption_timeline
    path = tmp_path / 'caption.png'
    Image.new('RGBA', (2, 2), 'red').save(path)
    layer = dict(path=path, bounds=(0, 0, 2, 2), start=1/30, end=2/30, first_frame=1, last_frame=2)
    result = build_caption_timeline([layer], tmp_path, fps=30, duration=.1)
    manifest = result['path'].read_text('utf8')
    assert manifest.count('duration 0.033333333333') == 3


def test_cuda_comparison_keeps_software_filter_frames_and_skips_ffv1_intermediates():
    from dataclasses import replace
    from twobyteasr.exports.studio_render import RenderJob, video_input_acceleration
    job = RenderJob('', '', '', export_context={'decode_backend':'cuda'})
    assert video_input_acceleration(job) == ['-hwaccel', 'cuda']
    assert video_input_acceleration(replace(job, composition_resolved=True)) == []
    assert '-hwaccel_output_format' not in video_input_acceleration(job)


def test_target_encoder_probe_checks_real_geometry_and_depth(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.exports import studio_render as render
    commands = []
    monkeypatch.setattr(render, '_nvidia_driver_info', lambda *a: 'fixture driver')
    monkeypatch.setattr(render, 'run_hidden_subprocess', lambda command, **kw:
        commands.append(command) or SimpleNamespace(returncode=0, stderr=''))
    settings = render.RenderSettings(width=3840, height=2160, fps=60, codec='hevc',
        encoder='hevc_nvenc', pixel_format='p010le', preset='p4', profile='main10')
    result = render.probe_encoder_detail('ffmpeg', 'hevc_nvenc', settings=settings)
    assert result['functional'] and result['frame_size'] == '3840x2160'
    assert result['pixel_format'] == 'p010le'
    command = commands[0]
    assert 'color=c=black:s=3840x2160:r=60' in command
    assert command[command.index('-profile:v')+1] == 'main10'


@pytest.mark.parametrize('intentional', [False, True])
def test_empty_browser_still_needs_a_proof_of_intentional_transparency(tmp_path, monkeypatch, intentional):
    from PIL import Image
    from twobyteasr.rendering import advanced_renderer as renderer
    from twobyteasr.exports.mixed_caption_export import prepare_mixed_stills
    cache = tmp_path/'cache'; cache.mkdir()
    monkeypatch.setattr(renderer, 'compile_composition_data', lambda *a, **k: dict(
        durationInFrames=30, cues=[dict(id='s', text='Hidden paint', startMs=0, endMs=1000, visual={})]))
    monkeypatch.setattr(renderer, '_renderer_cache_fingerprint', lambda: 'fixture')
    monkeypatch.setattr(renderer, '_overlay_cache_dir', lambda: cache)
    monkeypatch.setattr(renderer, '_trim_overlay_cache', lambda: None)
    def cached(source, destination):
        Image.new('RGBA', (20,20)).save(destination)
        return True
    monkeypatch.setattr(renderer, '_copy_verified_overlay', cached)
    monkeypatch.setattr('twobyteasr.caption_style.visual_snapshot.build_visual_cue_snapshot', lambda *a, **k: object())
    monkeypatch.setattr('twobyteasr.exports.static_caption_contract.intentional_empty_reason',
                        lambda *a: 'explicitly_transparent_paint' if intentional else None)
    if intentional:
        result = prepare_mixed_stills(project(), tmp_path, tmp_path, width=20, height=20, fps=30, start=0, duration=1)
        assert result['scenes'] == 1
    else:
        with pytest.raises(RuntimeError, match='像素为空'):
            prepare_mixed_stills(project(), tmp_path, tmp_path, width=20, height=20, fps=30, start=0, duration=1)
