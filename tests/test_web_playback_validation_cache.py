from types import SimpleNamespace

import pytest

from twobyteasr.caption_design import web_theme


def test_identical_sections_reuse_parse_but_edited_bytes_are_validated(monkeypatch):
    web_theme._sanitize_html_text.cache_clear()
    feed = web_theme.HTMLParser.feed
    calls = []
    def counted(parser, data):
        calls.append(data)
        return feed(parser, data)
    monkeypatch.setattr(web_theme.HTMLParser, 'feed', counted)
    source = '<svg viewBox="0 0 10 10"><path id="gold" d="M0,0L1,1"/></svg>'
    clean = web_theme.sanitize_html(source, section='cue')
    for _ in range(60):
        assert web_theme.sanitize_html(source, section='cue') == clean
    assert len(calls) == 1
    with pytest.raises(web_theme.WebThemeValidationError):
        web_theme.sanitize_html(source + '<script>bad()</script>', section='cue')
    assert len(calls) == 2
    assert 'viewBox=' in clean and 'id="gold"' in clean
    css = '.gold { fill: url(#gold); }'
    assert web_theme.sanitize_css(css, section='cue') == css
    with pytest.raises(web_theme.WebThemeValidationError):
        web_theme.sanitize_css(css + '@import "https://example.invalid/a.css";', section='cue')


def test_web_provider_reads_continuous_owner_without_changing_gui_snapshot(monkeypatch):
    from twobyteasr.playback.playback_clock import PlaybackClock
    from twobyteasr.studio.studio_advanced_flow import StudioAdvancedFlowMixin
    from twobyteasr.projects.studio_project import StudioCue
    wall = [100.]
    monkeypatch.setattr('twobyteasr.playback.playback_clock.time.monotonic', lambda: wall[0])
    clock = PlaybackClock(now=wall[0])
    clock.force_position(11000, paused=False, playback_rate=2, now=wall[0])
    snapshot = clock.snapshot()
    cue = StudioCue(id='a',start_ms=10000,end_ms=14000,text='真实时钟')
    harness = SimpleNamespace(project=True,_cue_lookup={'a':cue},_web_live_cue_id='a',
        video=SimpleNamespace(_playback_clock=clock,playback_position_snapshot=clock.snapshot))
    provide = StudioAdvancedFlowMixin._web_live_time_provider(harness)
    wall[0] += .1
    assert provide()[0] == pytest.approx(1200)
    assert clock.snapshot() is snapshot
    clock.force_position(12500, paused=True)
    wall[0] += 1
    assert provide()[0] == pytest.approx(2500)
    assert provide()[2] is False


def test_same_cue_seek_during_capture_discards_old_pixels(monkeypatch):
    import threading
    from PySide6.QtCore import Qt
    from twobyteasr.rendering import renderer_service
    from twobyteasr.rendering.live_web_preview import LiveWebPreviewWorker
    state = {'cue':100., 'generation':0, 'calls':0}
    done = threading.Event()
    def provide():
        return state['cue'], state['cue']+500, True, 1.
    provide.discontinuity_generation = lambda: state['generation']
    class Session:
        def live_set(self, *args, **kwargs): pass
        def live_text(self, *args, **kwargs): pass
        def live_frame(self, **kwargs):
            state["calls"] += 1
            if state["calls"] == 1:
                state.update(cue=2600.,generation=1)
                return b"old-before-seek"
            return b"current"
        def live_play(self, **kwargs): pass
        def close(self): pass
        def live_latest(self, **kwargs):
            state['calls'] += 1
            if state['calls'] == 2:
                state.update(cue=2600., generation=1)
                return 2, b'old-before-seek'
            return state['calls'], b'current'
    monkeypatch.setattr(renderer_service, 'LiveRendererSession', lambda _: Session())
    worker = LiveWebPreviewWorker(time_provider=provide)
    frames = []
    def received(frame, cue, stage):
        frames.append((bytes(frame), cue))
        worker.stop()
        done.set()
    worker.frame_ready.connect(received, Qt.ConnectionType.DirectConnection)
    worker.configure(theme=web_theme.builtin_web_themes()['balatro-joker'].to_dict(), text='同句seek',duration_seconds=5)
    worker.start()
    try:
        assert done.wait(2)
        assert frames == [(b'current', 2600.)]
    finally:
        worker.stop()
        worker._thread.join(2)


def test_cancelled_pause_releases_only_its_request_and_page(tmp_path):
    from twobyteasr.rendering.renderer_service import RendererService, LiveRendererSession, RendererLiveRequestSuperseded
    service = RendererService(tmp_path)
    sent = []
    service._send = sent.append
    unrelated = object()
    service._pending['unrelated-export'] = unrelated
    session = LiveRendererSession(service, 'page-A')
    with pytest.raises(RendererLiveRequestSuperseded):
        session.live_pause(cue_ms=100,stage_ms=500,still_current=lambda:False)
    assert [row['type'] for row in sent] == ['live_pause','live_cancel']
    assert all(row['session_id'] == 'page-A' for row in sent)
    assert service._pending == {'unrelated-export':unrelated}
