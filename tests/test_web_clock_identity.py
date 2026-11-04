from types import SimpleNamespace
from twobyteasr.rendering.live_web_preview import LiveWebPreviewWorker, WebFrame
from twobyteasr.caption_design.web_theme import builtin_web_themes, theme_archive_html
from twobyteasr.studio.studio_advanced_flow import StudioAdvancedFlowMixin


def test_duration_and_speaker_changes_keep_page_but_invalidate_frame():
    worker = LiveWebPreviewWorker()
    theme = builtin_web_themes()['balatro-joker'].to_dict()
    key = worker.configure(theme=theme,text='之前',speaker='A',duration_seconds=3)
    frame = WebFrame(b'png',id(worker),worker.strip_key,worker._configuration_generation)
    page = SimpleNamespace(_web_live_worker=worker)
    assert StudioAdvancedFlowMixin._web_frame_is_current(page,frame)
    assert worker.configure(theme=theme,text='之后',speaker='B',duration_seconds=.1)==key
    assert not StudioAdvancedFlowMixin._web_frame_is_current(page,frame)
    fresh = WebFrame(b'png',id(worker),worker.strip_key,worker._configuration_generation)
    assert StudioAdvancedFlowMixin._web_frame_is_current(page,fresh)
    page._web_live_worker=LiveWebPreviewWorker()
    assert not StudioAdvancedFlowMixin._web_frame_is_current(page,fresh)


def test_production_contains_no_demo_and_no_per_animation_await():
    html=theme_archive_html(builtin_web_themes()['balatro-joker'].to_dict(),auto_replay=False)
    assert 'cloneNode' not in html and 'setInterval' not in html and 'replay' not in html
    # Geometry awaits fonts; deterministic CSS pause awaits all animations
    # concurrently behind its existing timeout. A serial per-animation wait
    # would reintroduce the old latency proportional to character count.
    assert 'await capped' not in html
    assert 'await animation.ready' not in html
    assert 'await Promise.all(animations.map(animation=>animation.ready.catch' in html
    assert '.wt-cue { position: absolute; inset: 0; }' in html


def test_web_fidelity_does_not_take_live_owner():
    page=SimpleNamespace()
    snapshot=SimpleNamespace(style_recipe={'webTheme':{'name':'test'}})
    assert not StudioAdvancedFlowMixin._fidelity_can_replace_live(page,snapshot)
