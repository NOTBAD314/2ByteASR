import copy
import json
from pathlib import Path
from types import SimpleNamespace

from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia, StudioSpeaker
from twobyteasr.exports.export_timeline import export_project_snapshot, write_export_ass
from twobyteasr.exports.studio_render import RenderJob, RenderSettings, build_render_command


def project():
    p = SubtitleProject(media=StudioMedia('source.mp4', duration_ms=180000, width=1920, height=1080),
        cues=[StudioCue('a', 1000, 2000, '原文 A', speaker_id='one'),
              StudioCue('b', 170000, 171000, '原文 B', speaker_id='two')],
        speakers=[StudioSpeaker(id='one', name='one'), StudioSpeaker(id='two', name='two')],
        generation_metadata={'translations': {'a': 'English A', 'b': 'English B'}},
        studio_state={'bilingual': {'mode': 'bilingual'}}, render_settings={'_cue_domain': 'timeline'})
    p.validate(); return p


def test_visibility_snapshot_retains_original_data_and_latest_state():
    p = project(); original = copy.deepcopy(p.cues)
    visible = export_project_snapshot(p)
    p.studio_state['subtitle_track_visibility'] = {'one': False, 'two': False}
    hidden = export_project_snapshot(p)
    assert not hidden.cues and len(visible.cues) == 2
    assert p.cues == original and p.generation_metadata['translations']['a'] == 'English A'
    restored = SubtitleProject.from_dict(json.loads(json.dumps(p.to_dict())))
    assert not export_project_snapshot(restored).cues
    restored.studio_state['subtitle_track_visibility']['two'] = True
    assert [c.id for c in export_project_snapshot(restored).cues] == ['b']
    # A clear playhead does not erase later subtitles; locks are not visibility.
    restored.studio_state['locked_speakers'] = ['two']
    assert [c.id for c in export_project_snapshot(restored, start_ms=100000).cues] == ['b']


def test_empty_burn_in_does_not_compile_ass_or_load_fonts(tmp_path, monkeypatch):
    p = project(); p.studio_state['subtitle_track_visibility'] = {'one': False, 'two': False}
    monkeypatch.setattr('twobyteasr.rendering.ass_compiler.compile_ass', lambda *a, **k: (_ for _ in ()).throw(AssertionError('hidden subtitles compiled')))
    ass = tmp_path/'hidden.ass'
    result = write_export_ass(p, ass, skip_empty=True)
    assert not ass.exists() and not result.cues
    p.studio_state['subtitle_track_visibility'].clear()
    assert not write_export_ass(p, ass, skip_empty=True, start_ms=3000, end_ms=4000).cues


def test_no_burn_in_has_no_subtitle_filter_fonts_or_soft_subtitle_mapping(tmp_path, monkeypatch):
    from twobyteasr.exports import studio_render
    media=tmp_path/'source.mp4';media.touch()
    monkeypatch.setattr(studio_render, 'select_encoder', lambda *a:'libx264')
    job=RenderJob(str(media), '', str(tmp_path/'out.mp4'), RenderSettings(encoder='libx264'))
    command=build_render_command(tmp_path/'ffmpeg.exe', job)
    assert 'ass=' not in ' '.join(command) and 'fontsdir=' not in ' '.join(command)
    assert '-c:s' not in command


def test_hidden_speaker_and_range_combine_with_eye_state():
    p=project();p.speakers[0].hidden=True
    assert not export_project_snapshot(p, end_ms=10000).cues
    p.studio_state['subtitle_track_visibility']={'two':False}
    assert not export_project_snapshot(p).cues


def test_language_mode_is_frozen_with_visible_tracks():
    from twobyteasr.caption_style.bilingual_layout import project_display_cues
    p=project();p.studio_state['bilingual']['mode']='original'
    frozen=export_project_snapshot(p)
    p.studio_state['bilingual']['mode']='translation'
    assert [c.text for c in project_display_cues(frozen)]==['原文 A','原文 B']


def test_explicit_subtitle_file_export_keeps_hidden_data():
    from twobyteasr.exports.studio_subtitle_export import compile_srt
    p=project();p.studio_state['subtitle_track_visibility']={'one':False,'two':False}
    assert '原文 A' in compile_srt(p.cues) and '原文 B' in compile_srt(p.cues)


def test_ui_progress_uses_video_clock_even_if_audio_leads():
    from twobyteasr.exports.studio_render import parse_ffmpeg_out_time_seconds
    assert parse_ffmpeg_out_time_seconds({'video_time_seconds':'1.0','out_time_us':'99000000'})==1.0


def test_export_uses_validated_seek_copy_only_after_content_mapping(tmp_path):
    from twobyteasr.exports.timeline_media import resolve_video_graph
    class Cache:
        errors={}
        def prepare_timeline_source(self, source, **kw):
            return dict(path=source, original_path=source, kind='identity')
        def wait_optimized(self, path, **kw): return 'indexed.mp4'
    graph=dict(media_pool=[dict(asset_id='a',canonical_source='late.flv')],
        video_tracks=[dict(clips=[dict(asset_id='a')])],
        audio_mix=[dict(source_path='late.flv')])
    result=resolve_video_graph(graph, 'ffmpeg', cache=Cache(), seekable=True)
    assert result['media_pool'][0]['canonical_source']=='indexed.mp4'
    assert result['audio_mix'][0]['source_path']=='indexed.mp4'
    assert graph['media_pool'][0]['canonical_source']=='late.flv'
    class Gappy(Cache):
        def prepare_timeline_source(self, source, **kw): return dict(path='continuous.mkv',kind='continuous_proxy')
        def wait_optimized(self, *args, **kw): raise AssertionError('must not bypass content proxy')
    assert resolve_video_graph(graph, 'ffmpeg', cache=Gappy(), seekable=True)['media_pool'][0]['canonical_source']=='continuous.mkv'
