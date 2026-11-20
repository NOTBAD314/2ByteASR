"""Native entrance/exit motion mirrors TrustedSubtitle's per-frame formulas."""
from twobyteasr.rendering.native_caption_motion import motion_state, native_supported


def visual(entrance=None, exit_=None, **extra):
    return dict(motion=dict(mode='explicit', entrance=entrance or {}, exit=exit_ or {}, hold={'type': 'none'}), **extra)


def test_soft_entrance_fades_slides_and_spreads():
    v = visual({'type': 'fade', 'duration_ms': 300})
    start = motion_state(v, 0, 60, 30)
    assert start['opacity'] == 0 and start['dx'] == -28 and start['tracking'] == 8
    middle = motion_state(v, 4.5, 60, 30)  # 9 entrance frames at 30 fps
    assert abs(middle['opacity'] - .5) < 1e-9 and abs(middle['dx'] + 14) < 1e-9
    held = motion_state(v, 20, 60, 30)
    assert held == dict(opacity=1., dx=0., dy=0., scale_x=1., scale_y=1., rotation=0., clip=1., tracking=0.)


def test_punch_scale_curve_and_squash():
    v = visual({'type': 'spring_pop', 'duration_ms': 300})
    settling = motion_state(v, 4.5, 60, 30)  # progress .5: past the 1.18 peak at .45
    assert abs(settling['scale_x'] - (1.18 + (.96-1.18)*.05/.27)) < 1e-9 and settling['scale_y'] == settling['scale_x']
    early = motion_state(v, 1, 60, 30)
    assert abs(early['scale_y'] - early['scale_x']*.92) < 1e-9 and early['opacity'] == min(1, 1/9*1.7)


def test_exit_collapse_moves_down_and_fades():
    v = visual(exit_={'type': 'collapse', 'duration_ms': 200})
    end = motion_state(v, 60, 60, 30)
    assert end['opacity'] == 0 and end['dy'] == 34 and abs(end['scale_x'] - .15*.88) < 1e-9


def test_unsupported_effects_stay_in_the_browser():
    assert native_supported(visual({'type': 'fade'}))
    assert not native_supported(visual({'type': 'type_on'}))
    assert not native_supported(visual({'type': 'letter_stagger'}))
    assert not native_supported(visual({'type': 'glitch_in'}))
    assert not native_supported(visual(exit_={'type': 'blur_out'}))
    assert not native_supported(visual({'type': 'fade'}, decorations=['corner_brackets']))
    assert not native_supported(visual({'type': 'fade'}, wordAnimation={'units': [1]}))


def test_unavailable_encoder_returns_its_window_for_browser_fallback(tmp_path):
    from twobyteasr.rendering.native_caption_motion import render_native_windows

    window = (3, 4, tmp_path / 'still.png', (1, 1, 8, 8), {}, 'caption', [(1, 10, 30)], 30)
    rendered, failed = render_native_windows([window], tmp_path / 'missing.exe', tmp_path,
                                             width=16, height=16)
    assert rendered == []
    assert len(failed) == 1 and failed[0][:2] == (3, 4)
