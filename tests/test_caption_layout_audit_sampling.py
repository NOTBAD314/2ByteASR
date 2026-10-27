"""Sampling receipts must distinguish complete semantics from animated alpha."""
from fractions import Fraction
import hashlib
import json
from types import SimpleNamespace
import sys

import pytest

from twobyteasr.acceptance import caption_layout_audit as audit
from scripts.verify_caption_layout_headed import caption_completion_errors


def test_four_requested_samples_bind_to_real_encoded_frame_numbers():
    result = audit.layout_sample_schedule({'sample_ms': [150, 650, 1500, 2700]})
    assert [row['frame'] for row in result] == [4, 20, 45, 81]
    assert [row['requested_ms'] for row in result] == [150, 650, 1500, 2700]


@pytest.mark.parametrize('sample', [-1, 3000, 2999, float('nan'), float('inf')])
def test_invalid_or_out_of_stream_sample_is_not_silently_retargeted(sample):
    with pytest.raises(ValueError):
        audit.layout_sample_schedule({'sample_ms': [sample]})


def test_final_decode_continues_after_last_sample_and_keeps_actual_pts(monkeypatch, tmp_path):
    decoded = []
    stream = SimpleNamespace(thread_count=0)
    class Frame:
        def __init__(self, index):
            self.pts, self.time_base = index, Fraction(1, 30)
            self.width, self.height = 1920, 1080
        def to_image(self):
            return SimpleNamespace(save=lambda path: path.write_bytes(b'controlled image payload'))
        def to_ndarray(self, **_kwargs):
            return SimpleNamespace(tobytes=lambda: b'controlled RGB pixels')
    class Container:
        streams = SimpleNamespace(video=[stream])
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def decode(self, _stream):
            for index in range(90):
                decoded.append(index)
                yield Frame(index)
    monkeypatch.setitem(sys.modules, 'av', SimpleNamespace(open=lambda _path: Container()))
    (tmp_path/'source.mp4').write_bytes(b'controlled movie identity')
    result = audit.decode_gui_layout_samples(tmp_path/'source.mp4', tmp_path, {'sample_ms': [150, 650, 1500, 2700]})
    assert decoded[-1] == 89 and result['decoded_frames'] == 90
    assert stream.thread_count == 2
    assert result['samples'][0]['actual_ms'] == pytest.approx(4000/30)
    assert result['samples'][0]['requested_ms'] == 150


def test_semantic_comparison_keeps_all_text_and_lines_but_not_raster_size():
    left = dict(cue_id='a', text='First\nSecond', layout={'lines': ['First', 'Second'], 'overflow': False},
                position=[960, 900], word_animation={}, resolution=[1920, 1080], snapshot_hash='full')
    right = dict(left, resolution=[960, 540], snapshot_hash='half')
    assert audit.semantic_layout_receipt([left]) == audit.semantic_layout_receipt([right])
    right['text'] = 'First'
    assert audit.semantic_layout_receipt([left]) != audit.semantic_layout_receipt([right])


def test_transparent_entrance_is_ready_when_current_rows_and_time_are_ready(monkeypatch):
    from twobyteasr.studio import studio_readiness
    monkeypatch.setattr(studio_readiness, 'player_surface_ready', lambda _page: True)
    row = dict(active=True, current=True, sample_ms=133, visible=False,
               expected_cue_ids=['long'], cue_pixels=[{'cue_id': 'long', 'status': 'rendered'}])
    monkeypatch.setattr(audit, 'scene_sample_receipt', lambda _page: row)
    page = SimpleNamespace(timeline=SimpleNamespace(playhead_ms=133))
    assert audit.gui_layout_sample_ready(page, 4000/30)
    row['current'] = False
    assert not audit.gui_layout_sample_ready(page, 4000/30)
    row['current'] = True
    row['sample_ms'] = 650
    assert not audit.gui_layout_sample_ready(page, 4000/30)


def test_decoder_witness_is_still_required_for_native_caption_samples(monkeypatch):
    from twobyteasr.studio import studio_readiness
    monkeypatch.setattr(studio_readiness, 'player_surface_ready', lambda _page: False)
    monkeypatch.setattr(audit, 'scene_sample_receipt', lambda _page: {'active': False})
    page = SimpleNamespace(timeline=SimpleNamespace(playhead_ms=1500))
    assert not audit.gui_layout_sample_ready(page, 1500)


def paired_receipt(tmp_path, *, derived=False, route='graph'):
    """Small fake evidence for completion-validator tests, never GUI evidence."""
    from PIL import Image
    folder = tmp_path/'fixture'; folder.mkdir()
    canvas, output = [16, 9], ([9, 16] if derived else [16, 9])
    design = [5, 9] if derived else canvas
    times = [150, 650, 1500, 2700, 2850]
    case = dict(id='fixture', route=route, canvas=canvas, output=output, sample_ms=times)
    layout = [dict(cue_id='long', text='First\nSecond', layout={'lines': ['First', 'Second']},
                   position=[8, 8], word_animation={})]
    (folder/'preview-layout-receipt.json').write_text(json.dumps(layout))
    movie = folder/'gui-export.mp4'; movie.write_bytes(b'controlled movie identity')
    reopening = dict(required=derived, performed=derived)
    if derived:
        path = folder/'derived-output-preview.2byteproj'; path.write_text('{}')
        reopening.update(project_path=str(path), entry_calls=[str(path)], before_generation=1,
                         reopened_generation=2, old_object_id=10, new_object_id=20)
    samples = []
    for index, requested in enumerate(times):
        frame = round(requested*30/1000); actual = frame*1000/30
        exported, preview = folder/f'export-{frame}.png', folder/f'preview-{frame}.png'
        image = Image.new('RGB', tuple(output), (20+index*20, 0, 0)); image.save(exported)
        preview_image = Image.new('RGB', tuple(design), (0, 25+index*20, 0)); preview_image.save(preview)
        samples.append(dict(requested_ms=requested, frame=frame, pts=frame, time_base='1/30',
            actual_ms=actual, requested_preview_ms=actual, actual_playhead_ms=actual,
            file=exported.name, sha256=hashlib.sha256(exported.read_bytes()).hexdigest(),
            rgb_sha256=hashlib.sha256(image.tobytes()).hexdigest(), dimensions=output,
            preview=preview.name, preview_sha256=hashlib.sha256(preview.read_bytes()).hexdigest(),
            preview_rgb_sha256=hashlib.sha256(preview_image.tobytes()).hexdigest(), preview_dimensions=design,
            original_canvas=canvas, sampled_canvas=design, render_truth={'project': {'play_res': design}},
            complete_layout_semantics=True, layout=layout, gui_reopen=dict(reopening),
            scene={'active': True, 'current': True, 'sample_ms': actual,
                   'cue_pixels': [{'cue_id': 'long', 'status': 'rendered'}]}))
    record = dict(id='fixture', original_canvas=canvas, output_canvas={'design': design, 'output': output, 'relayout': derived},
                  animation_samples=5, decoded_frames=90, movie_sha256=hashlib.sha256(movie.read_bytes()).hexdigest())
    result = dict(passed=True, gui_shutdown=True, cases=[record])
    return case, result, folder, samples


def save_pairs(folder, samples):
    (folder/'gui-animation-samples.json').write_text(json.dumps(samples))


@pytest.mark.parametrize('derived', [False, True])
def test_wrapper_accepts_complete_unique_pts_artifacts_and_canvas_identity(tmp_path, derived):
    case, result, folder, samples = paired_receipt(tmp_path, derived=derived)
    save_pairs(folder, samples)
    assert not caption_completion_errors(result, [case], tmp_path, require_render=True)


def test_old_exe_and_missing_case_cannot_ignore_five_sample_request(tmp_path):
    case, result, folder, samples = paired_receipt(tmp_path)
    save_pairs(folder, samples)
    assert caption_completion_errors({'passed': True, 'cases': []}, [case], tmp_path, require_render=True)
    del result['cases'][0]['animation_samples']
    assert caption_completion_errors(result, [case], tmp_path, require_render=True)


@pytest.mark.parametrize('corruption', ['missing_pair', 'duplicate_target', 'wrong_pts', 'reused_path',
                                      'missing_png', 'wrong_canvas', 'no_gui_reopen', 'settled_pixels'])
def test_wrapper_rejects_incomplete_or_repeated_visual_evidence(tmp_path, corruption):
    from copy import deepcopy
    case, result, folder, samples = paired_receipt(tmp_path, derived=True)
    if corruption == 'missing_pair':
        samples.pop()
    elif corruption == 'duplicate_target':
        samples[-1] = deepcopy(samples[2])
    elif corruption == 'wrong_pts':
        samples[0]['pts'] = 45
    elif corruption == 'reused_path':
        samples[1]['preview'] = samples[0]['preview']
    elif corruption == 'missing_png':
        (folder/samples[0]['file']).unlink()
    elif corruption == 'wrong_canvas':
        samples[0]['sampled_canvas'] = [16, 9]
    elif corruption == 'no_gui_reopen':
        samples[0]['gui_reopen']['performed'] = False
    else:
        source = folder/samples[2]['preview']
        target = folder/samples[0]['preview']
        target.write_bytes(source.read_bytes())
        samples[0]['preview_sha256'] = samples[2]['preview_sha256']
        samples[0]['preview_rgb_sha256'] = samples[2]['preview_rgb_sha256']
    save_pairs(folder, samples)
    assert caption_completion_errors(result, [case], tmp_path, require_render=True)
