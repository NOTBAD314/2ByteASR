import importlib.util
from pathlib import Path


def prepare_module():
    path = Path(__file__).resolve().parents[1]/'scripts/prepare_playback_matrix.py'
    spec = importlib.util.spec_from_file_location('playback_matrix_prepare', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rates_share_duration_repeats_prewarm_and_same_continuous_project():
    cases = prepare_module().matrix_cases()
    assert len(cases) == 6
    for layers in (1, 2):
        group = [row for row in cases if row['project'] == f'layers-{layers}.2byteproj']
        assert [row['rate'] for row in group] == [1, 2, 4]
        for key, expected in [('seconds',65),('repeat',3),('start',5),('settle',5),('zoom',110)]:
            assert all(row[key] == expected for row in group)
    assert all(len(row['regions']) == int(row['project'].startswith('layers-2')) for row in cases)


def test_two_layer_fixture_carries_full_source_duration_and_pcm_tracks(tmp_path):
    media = [tmp_path/'V1.mp4', tmp_path/'V2.mp4']
    for path in media:
        path.write_bytes(b'placeholder; this test does not encode or inspect video')
    project = prepare_module().build_project(media,267,2)
    assert [track.id for track in project.video_tracks] == ['V1','V2']
    assert len(project.audio_tracks) == 2
    for track in project.video_tracks + project.audio_tracks:
        assert track.clips[0].source_out_ms == 267000
        assert track.clips[0].timeline_out_ms == 267000
    transform = project.video_tracks[1].clips[0].transform
    assert transform.position_x - transform.scale_x/2 == .495
    assert abs(transform.position_y - transform.scale_y/2 - .075) < 1e-12
