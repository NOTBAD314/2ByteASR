"""Pure receipt/fixture checks; no QWidget, render process or media encoding."""
import copy
import importlib.util
from pathlib import Path
import pytest

from twobyteasr.acceptance.export_target_audit import (prepare_variant, validate_video_receipt,
    validate_process_diagnostics, short_target_cases, active_main_encoding, file_sha256)


def _receipt():
    return dict(video_bitrate=dict(packet_count=9564, packet_bytes=205784509,
        duration_seconds=159.4, average_bitrate_bps=10327955.3, reliable=True),
        requested_video_bitrate_bps=10000000, actual_rate_control='target',
        actual_encoder='libx264', average_bitrate_bps=10535250,
        streams=[dict(codec_type='video', width=1920, height=1080,
            avg_frame_rate='60/1', duration='159.4', nb_frames='9564')])


def test_realistic_measured_target_is_independent_of_container_audio_rate():
    row = _receipt()
    row['average_bitrate_bps'] = 19000000  # Container total cannot replace video.
    checked = validate_video_receipt(row, 10000, 159.4)
    assert checked['passed']
    assert abs(checked['measured_video_kbps']-10327.9553) < .001


def test_container_rate_or_backend_met_flag_cannot_mask_half_video_rate():
    row = _receipt()
    row.update(average_bitrate_bps=10000000, bitrate_target_met=True)
    row['video_bitrate']['average_bitrate_bps'] = 5134903.136
    checked = validate_video_receipt(row, 10000, 159.4)
    assert not checked['passed']
    assert not checked['checks']['video_target_within_ten_percent']


def test_unknown_packet_duration_or_nonfinite_rate_is_not_target_success():
    for modification in ({'reliable': False}, {'duration_seconds': None},
                         {'average_bitrate_bps': float('nan')}, {'packet_count': 0}):
        row = _receipt()
        row['video_bitrate'].update(modification)
        assert not validate_video_receipt(row, 10000, 159.4)['passed']


def test_half_frame_rate_or_lower_resolution_cannot_pass_target_measurement():
    for modification in ({'avg_frame_rate': '30/1', 'nb_frames': '4782'},
                         {'width': 1280, 'height': 720}):
        row = _receipt()
        row['streams'][0].update(modification)
        assert not validate_video_receipt(row, 10000, 159.4)['passed']


def test_native_and_animated_fixtures_preserve_manual_speech_and_asr_originals():
    p = dict(cues=[dict(id='one', text='人工改字', start_ms=100, end_ms=2300,
        speaker_id='S01', transform=dict(position_y=826))],
        asr_evidence={'segment:1': dict(moss_text='人工改词')},
        speakers=[dict(id='S01', name='用户名称')],
        studio_state=dict(manual_caption_text={'one': '人工改字'}),
        style_recipes={'user-one': dict(engine='remotion', typography={'fontSize': 90},
            visualGraph={'motionGraph': {'tracks': []}}, motion={'mode': 'none'})})
    before = copy.deepcopy(p)
    for variant in ('authored', 'native', 'alpha'):
        result = prepare_variant(p, variant)
        for key in ('cues', 'asr_evidence', 'speakers', 'studio_state'):
            assert result[key] == before[key]
        assert p == before
        if variant == 'native':
            assert result['style_recipes'] == {}
        if variant == 'alpha':
            recipe = result['style_recipes']['user-one']
            assert recipe['motion']['entry']['type'] == 'fade'
            assert 'visualGraph' not in recipe


def test_relocated_primary_source_leaves_other_media_and_original_payload_unchanged():
    script = Path(__file__).resolve().parents[1]/'scripts/verify_export_target_real.py'
    spec = importlib.util.spec_from_file_location('target_driver_helpers', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = 'C:\\Users\\12\\Desktop\\real.mp4'
    p = dict(media={'path': old}, tracks=[{'path': 'C:/Users/12/Desktop/real.mp4'},
        {'path': 'C:/Users/12/Desktop/other.mp4'}])
    before = copy.deepcopy(p)
    result = module.relocate_media(p, old, 'C:/tmp/owned-real.mp4')
    assert result['media']['path'] == result['tracks'][0]['path'] == 'C:/tmp/owned-real.mp4'
    assert result['tracks'][1]['path'] == before['tracks'][1]['path']
    assert p == before


def _driver():
    script = Path(__file__).resolve().parents[1]/'scripts/verify_export_target_real.py'
    spec = importlib.util.spec_from_file_location('target_driver_integrity_helpers', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _autosave():
    from twobyteasr.projects.media_graph_integrity import graph_integrity
    p = dict(media={'path': 'C:/real/source.mp4'},
        media_pool=[dict(asset_id='video', path='C:/real/source.mp4')],
        video_tracks=[dict(id='V1', clips=[dict(id='c1', asset_id='video', start_ms=0, end_ms=159400)])],
        audio_tracks=[], av_track_groups=[],
        studio_state={'manual_caption_text': {'cue:1': '用户保留的人工改字'}},
        cues=[dict(id='cue:1', text='用户保留的人工改字', start_ms=20, end_ms=1500)],
        autosave={'media_graph_integrity': None})
    p['autosave']['media_graph_integrity'] = graph_integrity(p)
    return p


def test_relocated_autosave_rebinds_only_owned_validated_envelope():
    from twobyteasr.projects.media_graph_integrity import validate_autosave_integrity
    original = _autosave()
    before = copy.deepcopy(original)
    result, receipt = _driver().relocate_project_media(original, 'C:/real/source.mp4', 'C:/tmp/frozen/source.mp4')
    assert validate_autosave_integrity(result) == receipt['relocated_graph_integrity']
    assert receipt['original_graph_integrity'] == before['autosave']['media_graph_integrity']
    assert receipt['original_graph_integrity']['sha256'] != receipt['relocated_graph_integrity']['sha256']
    assert original == before
    assert result['cues'] == before['cues']
    assert result['studio_state'] == before['studio_state']


def test_invalid_original_autosave_is_not_hidden_by_fixture_rebinding():
    original = _autosave()
    original['video_tracks'][0]['clips'][0]['end_ms'] = 10
    before = copy.deepcopy(original)
    with pytest.raises(ValueError, match='校验失败'):
        _driver().relocate_project_media(original, 'C:/real/source.mp4', 'C:/tmp/frozen/source.mp4')
    assert original == before


def test_actual_frozen_timeline_159400_ms_does_not_invent_container_tail_frames():
    payload = dict(media=dict(duration_ms=159408),
        edit_sequence=dict(source_duration_ms=159400, segments=[dict(timeline_out_ms=159400)]),
        video_tracks=[dict(id='V1', clips=[dict(timeline_out_ms=159400)])],
        audio_tracks=[dict(id='A1', clips=[dict(timeline_out_ms=159400)])],
        av_track_groups=[dict(audio_track_id='A1', linked=True)],
        render_settings={'_cue_domain': 'timeline'}, cues=[dict(end_ms=159310)])
    before = copy.deepcopy(payload)
    extent = _driver().project_timeline_extent(payload)
    assert extent['source_container_ms'] == 159408
    assert extent['sequence_end_ms'] == extent['video_end_ms'] == extent['timeline_ms'] == 159400
    assert extent['unlinked_audio_end_ms'] == 0
    assert round(extent['timeline_ms']/1000*60) == 9564
    assert payload == before


def _diagnostics(path, *, encoder_purpose='advanced preview/render child', crf=False, merged=False):
    import json
    context = dict(job_id='job-one', project_revision='sha256:actual-frozen-project',
        requested_encoder='libx264', requested_settings={'quality_mode': 'target', 'bitrate_kbps': 10000})
    manifest = dict(context, target_video_bitrate_bps=10000000)
    (path/'manifest.json').write_text(json.dumps(manifest), 'utf-8')
    log = '001.stdout.log' if merged else '001.stderr.log'
    argv = ['ffmpeg', '-c:v', 'libx264', '-b:v', '10000k']
    if crf:
        argv += ['-crf', '20']
    events = []
    for identity, purpose in [('001', encoder_purpose), ('002', 'complete staged export decode'),
                              ('003', 'export v:0 packet bitrate measurement')]:
        payload = dict(process_id=identity, purpose=purpose)
        if identity == '001':
            payload.update(actual_encoder='libx264', argv=argv, stderr_log=log,
                stderr_merged_with_stdout=merged, stdout_payload_logged=merged,
                stdout_log=log if merged else None)
        events += [dict(job_id=context['job_id'], event='process_started', payload=payload),
            dict(job_id=context['job_id'], event='process_exited', payload=dict(process_id=identity, returncode=0))]
    events += [dict(job_id=context['job_id'], event='job_finished', payload=dict(published=True))]
    (path/'processes.jsonl').write_text('\n'.join(json.dumps(row) for row in events), 'utf-8')
    (path/log).write_text('[libx264] actual full stderr\nvideo final statistics\n', 'utf-8')
    return context


@pytest.mark.parametrize('merged', [False, True])
def test_actual_final_process_requires_target_lifecycle_and_retained_stderr(tmp_path, merged):
    context = _diagnostics(tmp_path, merged=merged)
    checked = validate_process_diagnostics(tmp_path, context, 10000)
    assert checked['passed']
    assert checked['actual_final_process']['stdout_log'] == ('001.stdout.log' if merged else None)


def test_capability_probe_cannot_count_as_actual_final_encoding(tmp_path):
    context = _diagnostics(tmp_path, encoder_purpose='ffmpeg capability probe')
    checked = validate_process_diagnostics(tmp_path, context, 10000)
    assert not checked['passed']
    assert not checked['checks']['actual_final_encode_exited_successfully']


def test_actual_crf_or_missing_full_stderr_cannot_pass_target_diagnostics(tmp_path):
    context = _diagnostics(tmp_path, crf=True)
    checked = validate_process_diagnostics(tmp_path, context, 10000)
    assert not checked['passed']
    assert not checked['checks']['actual_target_command_excludes_quality_control']
    (tmp_path/'001.stderr.log').unlink()
    assert not validate_process_diagnostics(tmp_path, context, 10000)['checks']['complete_encoder_stderr_retained']


def test_encoder_plans_cover_the_same_three_targets_and_keep_mixed_compatibility():
    assert short_target_cases() == ((5000, 'libx264', False), (10000, 'libx264', True), (20000, 'auto', False))
    for plan, encoder in [('software', 'libx264'), ('auto', 'auto')]:
        assert short_target_cases(plan) == ((5000, encoder, False), (10000, encoder, True), (20000, encoder, False))
    with pytest.raises(ValueError):
        short_target_cases('unknown')


def test_cancel_gate_needs_actual_main_popen_and_not_preparation_probe_or_finished_encode(tmp_path):
    import json
    log = tmp_path/'processes.jsonl'
    assert active_main_encoding(tmp_path) is None
    def started(purpose, encoder='libx264', pid=123):
        return dict(event='process_started', payload=dict(process_id='001', purpose=purpose,
            actual_encoder=encoder, pid=pid))
    for row in [started('ffmpeg capability probe'), started('advanced preview/render child', 'ffv1'),
                started('ffmpeg studio render', pid=None), dict(event='job_started', payload={})]:
        log.write_text(json.dumps(row), 'utf-8')
        assert active_main_encoding(tmp_path) is None
    actual = started('advanced preview/render child')
    log.write_text(json.dumps(actual), 'utf-8')
    assert active_main_encoding(tmp_path) == actual['payload']
    with log.open('a', encoding='utf-8') as stream:
        stream.write('\n'+json.dumps(dict(event='process_exited', payload=dict(process_id='001', returncode=0))))
    assert active_main_encoding(tmp_path) is None


def test_same_name_sha_distinguishes_overwrite_even_if_size_is_unchanged(tmp_path):
    product = tmp_path/'existing.mp4'
    product.write_bytes(b'original product')
    original = file_sha256(product)
    assert file_sha256(product) == original
    product.write_bytes(b'replaced product')
    assert product.stat().st_size == len(b'original product')
    assert file_sha256(product) != original
