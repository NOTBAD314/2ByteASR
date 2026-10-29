"""Video seam transition looks (2026-10-17): storage, sampling, drawing, export."""
import copy
import math
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import (SubtitleProject, StudioMedia, StudioCue, VideoClip, VideoTrack,
                                                save_project, load_project)
from twobyteasr.timeline.studio_edit_sequence import sequence_of
from twobyteasr.timeline.studio_media_pool import sync_linked_av_contract
from twobyteasr.timeline.studio_transitions import (
    IDENTITY_FX, LOOK_DIRECTIONS, VIDEO_LOOKS, DEFAULT_LOOK_KEY, default_look, normalize_look, set_transition,
    transition_effect, transition_fx_active, transition_gain, transition_windows, reconcile_transitions)

FFMPEG = Path(__file__).resolve().parents[1] / "tools/ffmpeg/bin/ffmpeg.exe"


@pytest.fixture(scope='module', autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


def project():
    p = SubtitleProject(media=StudioMedia(path='test.mp4', duration_ms=30000, width=320, height=180),
                        cues=[StudioCue('c1', 1000, 1500, '字幕一', speaker_id='S1')])
    p.validate(); p.video_tracks[0].locked = True; p.video_tracks[0].enabled = False
    sequence_of(p).video_track_locked = True
    asset = p.media_pool[0]; asset.offline = False
    p.video_tracks.append(VideoTrack('V2', '剪辑', clips=[VideoClip('v2a', asset.asset_id, 3000, 7000, 1000, 5000),
                                                         VideoClip('v2b', asset.asset_id, 7000, 11000, 5000, 9000)],
                                     z_index=1))
    sync_linked_av_contract(p)
    return p


def envelope(look, role):
    return [dict(start_ms=0, end_ms=1000, role=role, curve='look', look=look, transition_id='t')]


def every_look():
    for kind in VIDEO_LOOKS[1:]:
        for direction in LOOK_DIRECTIONS.get(kind, (None,)):
            for intensity in (.5, 1., 1.5):
                yield normalize_look(dict(id=kind, direction=direction, intensity=intensity))


def test_normalize_look_canonical_values():
    assert normalize_look(None) is None and normalize_look('cross_dissolve') is None
    assert normalize_look(dict(id='future_look')) is None
    assert normalize_look('push') == dict(id='push', intensity=1., direction='left')
    assert normalize_look(dict(id='flash', direction='nope', intensity=9)) == dict(id='flash', intensity=1.5, direction='white')
    assert normalize_look(dict(id='glitch', direction='left', intensity='x')) == dict(id='glitch', intensity=1.)
    assert normalize_look(dict(id='zoom_blur', intensity=float('nan')))['intensity'] == 1.


def test_look_saved_kept_on_duration_and_replaced_explicitly(tmp_path):
    p = project()
    item = set_transition(p, 'video', 'V2', 'v2a', 'v2b', duration_ms=800, look=dict(id='push', direction='right'))
    assert item['type'] == 'cross_dissolve' and item['look'] == dict(id='push', intensity=1., direction='right')
    again = set_transition(p, 'video', 'V2', 'v2a', 'v2b', duration_ms=600)
    assert again['id'] == item['id'] and again['look'] == item['look'] and again['duration_ms'] == 600
    saved = load_project(save_project(p, tmp_path / 'look.2byteproj'))
    assert saved.studio_state['clip_transitions'] == p.studio_state['clip_transitions']
    plain = set_transition(p, 'video', 'V2', 'v2a', 'v2b', duration_ms=600, look=None)
    assert 'look' not in plain and plain['type'] == 'cross_dissolve'
    # A newer build's look is not ours to rewrite; a duration change keeps it.
    p.studio_state['clip_transitions'][0]['look'] = dict(id='future_look', speed=3)
    kept = set_transition(p, 'video', 'V2', 'v2a', 'v2b', duration_ms=700)
    assert kept['look'] == dict(id='future_look', speed=3)
    roles = [e['role'] for e in transition_windows(p, 'video')[('V2', 'v2b')]['envelopes']]
    assert roles == ['in']  # unknown looks play as the original dissolve


def test_clip_ends_and_audio_never_store_a_look():
    p = project()
    tail = set_transition(p, 'video', 'V2', 'v2b', edge='out', duration_ms=500, look='flash')
    assert 'look' not in tail
    audio = next(t for t in p.audio_tracks if t.linked_video_track_id == 'V2')
    left, right = audio.clips[:2]
    assert 'look' not in set_transition(p, 'audio', audio.id, left.id, right.id, duration_ms=300, look='push')


def test_razor_and_reconcile_keep_the_look():
    from twobyteasr.timeline.studio_clip_edit import clip_edit_command
    p = project()
    seam = set_transition(p, 'video', 'V2', 'v2a', 'v2b', duration_ms=600, look=dict(id='whip', direction='up'))
    clip_edit_command(p, 'V2', 'split', clip_id='v2a', time_ms=4000).redo()
    record = next(t for t in p.studio_state['clip_transitions'] if t['id'] == seam['id'])
    assert record['look'] == dict(id='whip', intensity=1., direction='up') and record['type'] == 'cross_dissolve'
    assert reconcile_transitions(p)[0]['look'] == record['look']


def test_default_look_setting():
    p = project()
    assert default_look(p) is None
    p.studio_state[DEFAULT_LOOK_KEY] = dict(id='stretch', direction='vertical', intensity=1.2)
    assert default_look(p) == dict(id='stretch', intensity=1.2, direction='vertical')
    p.studio_state[DEFAULT_LOOK_KEY] = 'something-else'
    assert default_look(p) is None


def test_dissolve_windows_and_gain_unchanged():
    p = project()
    set_transition(p, 'video', 'V2', 'v2a', 'v2b', duration_ms=1000)
    windows = transition_windows(p, 'video')
    assert [(e['role'], e['curve']) for e in windows['v2a']['envelopes']] == [('hold', 'linear')]
    assert [(e['role'], e['curve']) for e in windows['v2b']['envelopes']] == [('in', 'linear')]
    for t in (4500, 4800, 5000, 5300, 5499):  # seam at 5000 (clips are source, then timeline)
        fx = transition_effect(windows['v2b']['envelopes'], t)
        assert fx['opacity'] == pytest.approx((t-4500)/1000) == transition_gain(windows['v2b']['envelopes'], t)
        assert not transition_fx_active(fx) and not transition_fx_active(transition_effect(windows['v2a']['envelopes'], t))


def test_every_look_is_identity_outside_and_finite_inside():
    for look in every_look():
        assert transition_effect(envelope(look, 'out'), 0) == IDENTITY_FX
        assert transition_effect(envelope(look, 'out'), -40) == IDENTITY_FX
        end = transition_effect(envelope(look, 'in'), 1000)
        assert {k: v for k, v in end.items() if k != 'seed'} == {k: v for k, v in IDENTITY_FX.items() if k != 'seed'}
        for ms in range(0, 1001, 25):
            for role in ('out', 'in'):
                fx = transition_effect(envelope(look, role), ms)
                numbers = [v for v in fx.values() if isinstance(v, float)]
                assert all(math.isfinite(v) for v in numbers), (look, role, ms, fx)
                assert 0 <= fx['opacity'] <= 1 and fx['sx'] > 0 and fx['sy'] > 0 and 0 <= fx['tint_alpha'] <= 1
        # Exactly one picture (or a short overlap) is visible at every moment.
        for ms in range(0, 1001, 50):
            out, inc = (transition_effect(envelope(look, r), ms)['opacity'] for r in ('out', 'in'))
            assert out > 0 or inc > 0, (look, ms)


def test_push_moves_both_pictures_by_one_frame():
    look = normalize_look(dict(id='push', direction='left'))
    out, inc = (transition_effect(envelope(look, r), 500) for r in ('out', 'in'))
    assert out['dx'] == pytest.approx(-.5) and inc['dx'] == pytest.approx(.5)
    assert out['blur_x'] == pytest.approx(.16) and out['blur_y'] == 0
    down = normalize_look(dict(id='push', direction='down'))
    assert transition_effect(envelope(down, 'in'), 500)['dy'] == pytest.approx(-.5)


def test_glitch_slices_follow_project_time():
    look = normalize_look('glitch')
    first = transition_effect(envelope(look, 'out'), 410)
    assert transition_effect(envelope(look, 'out'), 415)['seed'] == first['seed']
    assert transition_effect(envelope(look, 'out'), 455)['seed'] != first['seed']


def _mean(image, x0, x1):
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    values = [image.pixelColor(x, y) for x in range(x0, x1, 4) for y in range(0, image.height(), 4)]
    return tuple(sum(getattr(c, k)() for c in values)/len(values) for k in ('red', 'green', 'blue'))


def test_shared_painter_draws_each_look():
    from twobyteasr.playback.transition_looks import compose_pair, sample_frames
    a, b = sample_frames(160, 90)
    warm, cool = _mean(a, 0, 160), _mean(b, 0, 160)
    assert warm[0] > warm[2] and cool[2] > cool[0]
    pushed = compose_pair(normalize_look('push'), .5, a, b, (160, 90))
    left, right = _mean(pushed, 0, 60), _mean(pushed, 100, 160)
    assert left[0] > left[2] and right[2] > right[0]  # outgoing on the left, incoming on the right
    white = _mean(compose_pair(normalize_look('flash'), .5, a, b, (160, 90)), 0, 160)
    black = _mean(compose_pair(normalize_look(dict(id='flash', direction='black')), .5, a, b, (160, 90)), 0, 160)
    assert min(white) > 245 and max(black) < 10
    glitch = compose_pair(normalize_look('glitch'), .45, a, b, (160, 90), transition_id='x')
    assert glitch == compose_pair(normalize_look('glitch'), .45, a, b, (160, 90), transition_id='x')
    assert glitch != compose_pair(None, 0, a, b, (160, 90))
    for kind in ('whip', 'zoom_blur', 'stretch'):
        mid = compose_pair(normalize_look(kind), .5, a, b, (160, 90))
        assert mid != compose_pair(None, 0, a, b, (160, 90)) and not mid.isNull()
    # Before and after the seam the pictures are untouched.
    assert compose_pair(normalize_look('whip'), 0, a, b, (160, 90)) == compose_pair(None, 0, a, b, (160, 90))


def test_motion_blur_keeps_brightness_and_soft_edges():
    from PySide6.QtGui import QColor, QTransform
    from twobyteasr.playback.transition_looks import _average
    solid = QImage(200, 40, QImage.Format.Format_ARGB32_Premultiplied); solid.fill(QColor(200, 90, 30))
    for taps in (2, 9, 24):
        blurred = _average(solid, [QTransform.fromTranslate(i*.5, 0) for i in range(taps)]).convertToFormat(QImage.Format.Format_ARGB32)
        inside = blurred.pixelColor(150, 20)
        assert inside.getRgb() == (200, 90, 30, 255)
        assert blurred.pixelColor(0, 20).alpha() == pytest.approx(255/taps, abs=2)


@pytest.mark.skipif(not FFMPEG.is_file(), reason="bundled ffmpeg required")
@pytest.mark.parametrize('look,check', [
    (dict(id='push', direction='left'), 'split'),
    (dict(id='flash'), 'white'),
    (None, 'dissolve'),
])
def test_export_draws_the_look_at_the_seam(tmp_path, look, check):
    from twobyteasr.system.processes import run_hidden_subprocess
    from twobyteasr.exports.studio_render import RenderJob, RenderSettings
    from twobyteasr.exports.video_export import capture_video_graph, prepared_video_job
    from twobyteasr.rendering.ass_compiler import compile_ass
    source = tmp_path / 'red then blue.mkv'
    run_hidden_subprocess([str(FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=red:s=160x90:r=10:d=2',
                           '-f', 'lavfi', '-i', 'color=blue:s=160x90:r=10:d=2', '-filter_complex', '[0][1]concat=n=2:v=1',
                           '-c:v', 'ffv1', str(source)], purpose='transition export fixture', check=True, timeout=20)
    p = SubtitleProject(media=StudioMedia(path=str(source), duration_ms=4000, width=160, height=90))
    p.validate()
    asset = p.media_pool[0]
    asset.offline = False
    asset.video_metadata = dict(asset.video_metadata or {}, width=160, height=90, has_video=True, fps=10)
    # VideoClip(id, asset, source_in, source_out, timeline_in, timeline_out):
    # red 0–1.5 s, then blue from source 2.5 s, cut at 1.5 s with handles.
    p.video_tracks[0].clips = [VideoClip('red', asset.asset_id, 0, 1500, 0, 1500),
                               VideoClip('blue', asset.asset_id, 2500, 4000, 1500, 3000)]
    p.video_tracks[0].locked = False
    sequence_of(p).video_track_locked = False
    sync_linked_av_contract(p)
    set_transition(p, 'video', p.video_tracks[0].id, 'red', 'blue', duration_ms=1000, look=look)
    ass = tmp_path / 'empty.ass'; ass.write_text(compile_ass(p), encoding='utf-8-sig')
    job = RenderJob(str(source), str(ass), str(tmp_path / 'out.mkv'),
                    RenderSettings(container='mkv', encoder='libx264', preset='ultrafast', audio_codec='none', fps=10, quality=0),
                    start_seconds=1.5, duration_seconds=.1, video_graph=capture_video_graph(p))
    with prepared_video_job(FFMPEG, job) as prepared:
        assert prepared.composition_resolved
        frame = tmp_path / 'frame.png'
        run_hidden_subprocess([str(FFMPEG), '-v', 'error', '-y', '-i', prepared.media_path, '-frames:v', '1', str(frame)],
                              purpose='transition export frame', check=True, timeout=10)
        image = QImage(str(frame))
    left, middle, right = image.pixelColor(20, 45), image.pixelColor(80, 45), image.pixelColor(140, 45)
    if check == 'split':
        assert left.red() > 200 and left.blue() < 40 and right.blue() > 200 and right.red() < 40
        # Motion blur across the seam: a band of mixed pixels and no hard edge.
        row = [image.pixelColor(x, 45) for x in range(40, 121)]
        assert any(c.red() > 40 and c.blue() > 40 for c in row[20:61])
        assert max(abs(a.red()-b.red()) for a, b in zip(row, row[1:])) < 90
    elif check == 'white':
        assert min(middle.red(), middle.green(), middle.blue()) > 240
    else:
        assert abs(middle.red()-128) <= 6 and abs(middle.blue()-128) <= 6
