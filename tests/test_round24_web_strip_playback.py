"""第二十四轮：条带预渲染（record-once → replay）+ 时间轴硬门 + Balatro 重建。

覆盖：
- WebStripStore：帧序列查询 / 完成态 / LRU 字节预算驱逐；
- Worker v3：录制一遍后回放（暂停=同帧、seek=即查即得、node 崩溃后回放不受影响、
  回放期零页调用、warm 走 live_text 快路径）；
- 生成硬门：文字层 infinite 拒收 / .wt-cue 快循环拒收 / 缺 var(--wt-dur) 拒收；
- driver：play() 不回卷 finished 动画（endTime 钳制）、--wt-t/--wt-p token 同步；
- service.mjs：live 流量维持 idle 定时器；
- 播放链：范围套用后触发条带预热（_queue_web_strip_warm）。
"""

from __future__ import annotations

import time

import pytest

pytestqt = pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from twobyteasr.caption_design.web_theme import (
    WebThemeValidationError,
    builtin_web_themes,
    validate_generated_theme,
    _LIVE_DRIVER_SCRIPT,
)


def _app() -> QApplication:
    app = QApplication.instance()
    return app if app is not None else QApplication([])


def _balatro() -> dict:
    return builtin_web_themes()["balatro-joker"].to_dict()


# ---------------------------------------------------------------------------
# WebStripStore
# ---------------------------------------------------------------------------


def test_strip_store_frame_lookup_and_completion():
    from twobyteasr.rendering.live_web_preview import WebStripStore

    store = WebStripStore(budget_bytes=10 * 1024 * 1024)
    strip = store.create("k1", 1000.0)
    assert store.frame("k1", 0) is None  # 未完成不服务
    store.append(strip, 0.0, b"a")
    store.append(strip, 100.0, b"b")
    store.append(strip, 250.0, b"c")
    store.finish(strip)
    assert store.is_complete("k1")
    assert store.frame("k1", 0)[0] == b"a"
    assert store.frame("k1", 50.0)[0] == b"a"   # 最近的前一帧
    assert store.frame("k1", 100.0)[0] == b"b"
    assert store.frame("k1", 240.0)[0] == b"b"
    assert store.frame("k1", 999.0)[0] == b"c"
    assert store.frame("k1", -5.0)[0] == b"a"   # 起点钳制


def test_strip_store_lru_budget_eviction_protects_recording():
    from twobyteasr.rendering.live_web_preview import WebStripStore

    store = WebStripStore(budget_bytes=64)
    s1 = store.create("old", 1000.0)
    store.append(s1, 0.0, b"x" * 40)
    store.finish(s1)
    s2 = store.create("new", 1000.0)
    store.append(s2, 0.0, b"y" * 40)  # 触发超预算 → 驱逐非录制中的 old
    assert store.is_complete("old") is False
    assert store.peek("new") is not None
    store.finish(s2)
    assert store.is_complete("new")


# ---------------------------------------------------------------------------
# Worker v3：录制 → 回放（fake 渲染服务）
# ---------------------------------------------------------------------------


_TINY_PNG = __import__("base64").b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M"
    "9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class _FakeRendererService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.seq = 0
        self.fail = False

    def _check(self) -> None:
        if self.fail:
            from twobyteasr.rendering.renderer_service import RendererServiceError

            raise RendererServiceError("node is gone")

    def live_set(self, html, **_kw) -> None:
        self._check()
        self.calls.append(("live_set", None))

    def live_text(self, *, text, speaker="", **kwargs) -> None:
        self._check()
        self.calls.append(("live_text", text))

    def live_play(self, **kw) -> None:
        self._check()
        self.calls.append(("live_play", kw.get("rate")))

    def live_pause(self, *, cue_ms=0.0, stage_ms=0.0, **kwargs) -> bytes:
        self._check()
        self.seq += 1
        self.calls.append(("live_pause", cue_ms))
        return _TINY_PNG

    def live_latest(self, *, since_seq: int = 0):
        self._check()
        self.seq += 1
        return self.seq, _TINY_PNG

    def live_frame(self, *, cue_ms=0., stage_ms=0., **kwargs):
        self._check();self.calls.append(('live_frame',cue_ms));return _TINY_PNG

    def close(self):self.closed=True

    def count(self, name: str) -> int:
        return sum(1 for call, _ in self.calls if call == name)


@pytest.fixture()
def strip_env(monkeypatch):
    _app()
    from twobyteasr.rendering import live_web_preview as lwp
    from twobyteasr.rendering import renderer_service

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("TWOBYTEASR_FORCE_WEB_LIVE", "1")
    service = _FakeRendererService()
    monkeypatch.setattr(renderer_service, "GLOBAL_RENDERER_SERVICE", service)
    monkeypatch.setattr(renderer_service,"LiveRendererSession",lambda *_:service)
    store = lwp.WebStripStore(budget_bytes=64 * 1024 * 1024)
    monkeypatch.setattr(lwp, "GLOBAL_WEB_STRIP_STORE", store)
    lwp.reset_page_state()
    yield service, store, lwp
    lwp.reset_page_state()


def _wait_for(predicate, timeout: float = 12.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class _Clock:
    """播放时钟：playing 时按墙钟推进 cue_ms；manual=冻结在指定毫秒。"""

    def __init__(self, span_ms: float = 1000.0) -> None:
        self.span = span_ms
        self.playing = True
        self.manual = None
        self._t0 = time.monotonic()

    def freeze(self, cue_ms: float, playing: bool = False) -> None:
        self.manual = float(cue_ms)
        self.playing = playing

    def provide(self):
        if self.manual is not None:
            return self.manual, 8000.0 + self.manual, self.playing, 1.0
        if self.playing:
            cue = min(self.span + 400.0, (time.monotonic() - self._t0) * 1000.0)
            return cue, 8000.0 + cue, True, 1.0
        return 0.0, 8000.0, False, 1.0


def test_worker_streams_exact_paused_times_without_recording_strips(strip_env):
    service,store,lwp=strip_env;clock=_Clock();clock.freeze(200)
    frames=[];worker=lwp.LiveWebPreviewWorker(time_provider=clock.provide)
    worker.frame_ready.connect(lambda frame,*_:frames.append(frame),Qt.DirectConnection)
    worker.configure(theme=_balatro(),text='时钟测试',duration_seconds=.6);worker.start()
    try:
        assert _wait_for(lambda:len(frames)==1)
        assert store.peek(worker.strip_key) is None and service.count('live_set')==1
        time.sleep(.1);assert len(frames)==1
        clock.freeze(450);assert _wait_for(lambda:len(frames)==2)
        clock.freeze(200);assert _wait_for(lambda:len(frames)==3)
        assert bytes(frames[0])==bytes(frames[2])
        assert [value for name,value in service.calls if name=='live_pause']==[200,450,200]
    finally:worker.stop();worker._thread.join(1)


def test_worker_reports_node_failure_without_stale_strip_replay(strip_env):
    service,store,lwp=strip_env;clock=_Clock();clock.freeze(100)
    frames=[];errors=[];worker=lwp.LiveWebPreviewWorker(time_provider=clock.provide)
    worker.frame_ready.connect(lambda frame,*_:frames.append(frame),Qt.DirectConnection)
    worker.failed.connect(errors.append,Qt.DirectConnection)
    worker.configure(theme=_balatro(),text='失败可见',duration_seconds=.5);worker.start()
    try:
        assert _wait_for(lambda:len(frames)==1)
        service.fail=True;clock.freeze(250)
        assert _wait_for(lambda:bool(errors),3)
        assert 'node is gone' in errors[-1] and len(frames)==1
        assert store.peek(worker.strip_key) is None
    finally:worker.stop();worker._thread.join(1)


def test_worker_warm_reuses_page_when_next_content_activates(strip_env):
    service,store,lwp=strip_env;clock=_Clock();clock.freeze(100)
    frames=[];worker=lwp.LiveWebPreviewWorker(time_provider=clock.provide)
    worker.frame_ready.connect(lambda frame,*_:frames.append(frame),Qt.DirectConnection)
    worker.configure(theme=_balatro(),text='当前句',duration_seconds=.5);worker.start()
    try:
        assert _wait_for(lambda:bool(frames))
        worker.warm(theme=_balatro(),text='下一句',duration_seconds=.5)
        worker.configure(theme=_balatro(),text='下一句',duration_seconds=.5)
        assert _wait_for(lambda:any(name=='live_text' and value=='下一句' for name,value in service.calls))
        assert service.count('live_set')==1
    finally:worker.stop();worker._thread.join(1)


def test_worker_stays_idle_through_gap_until_explicit_stop(strip_env):
    service,store,lwp=strip_env;alive={'value':True};frames=[];exited=[]
    worker=lwp.LiveWebPreviewWorker(time_provider=lambda:(100,8100,True,1) if alive['value'] else None)
    worker.frame_ready.connect(lambda frame,*_:frames.append(frame),Qt.DirectConnection)
    worker.exited.connect(lambda:exited.append(True),Qt.DirectConnection)
    worker.configure(theme=_balatro(),text='间隙',duration_seconds=.4);worker.start()
    try:
        assert _wait_for(lambda:bool(frames))
        alive['value']=False;time.sleep(.1);count=len(frames);time.sleep(.1)
        assert worker.running and not exited and len(frames)==count
    finally:worker.stop();worker._thread.join(1)
    assert not worker.running and service.closed


# ---------------------------------------------------------------------------
# 生成硬门（二十四轮时间轴铁律）
# ---------------------------------------------------------------------------


def test_gate_rejects_infinite_on_text_layers():
    payload = _balatro()
    payload["cueCss"] += "\n.wt-text .wt-w { animation: wt-bad 1s infinite; }\n"
    from twobyteasr.caption_design.web_theme import WebThemeDocument

    doc = WebThemeDocument.from_dict(payload)
    with pytest.raises(WebThemeValidationError, match="文字层"):
        validate_generated_theme(doc)


def test_gate_rejects_fast_infinite_on_cue_plate():
    payload = _balatro()
    payload["cueCss"] += "\n.wt-cue { animation: wt-bounce 1.2s infinite; }\n"
    from twobyteasr.caption_design.web_theme import WebThemeDocument

    doc = WebThemeDocument.from_dict(payload)
    with pytest.raises(WebThemeValidationError, match="慢周期"):
        validate_generated_theme(doc)


def test_gate_allows_slow_plate_breathe():
    payload = _balatro()
    payload["cueCss"] += "\n.wt-cue { animation: wt-breathe 3.2s ease-in-out infinite; }\n"
    from twobyteasr.caption_design.web_theme import WebThemeDocument

    validate_generated_theme(WebThemeDocument.from_dict(payload))


def test_gate_requires_dur_anchored_exit():
    payload = _balatro()
    payload["cueCss"] = payload["cueCss"].replace("var(--wt-dur)", "var(--wt-duration)")
    from twobyteasr.caption_design.web_theme import WebThemeDocument

    doc = WebThemeDocument.from_dict(payload)
    with pytest.raises(WebThemeValidationError, match="--wt-dur"):
        validate_generated_theme(doc)


def test_builtin_balatro_passes_generation_gates():
    from twobyteasr.caption_design.web_theme import WebThemeDocument

    validate_generated_theme(WebThemeDocument.from_dict(_balatro()))


# ---------------------------------------------------------------------------
# driver / node service 契约
# ---------------------------------------------------------------------------


def test_driver_does_not_rewind_finished_animations():
    assert "getComputedTiming" in _LIVE_DRIVER_SCRIPT
    assert "endTime" in _LIVE_DRIVER_SCRIPT
    assert "a.currentTime = end" in _LIVE_DRIVER_SCRIPT
    # token 同步（与 TSX 运行时对齐）
    assert "--wt-t" in _LIVE_DRIVER_SCRIPT and "--wt-p" in _LIVE_DRIVER_SCRIPT


def test_node_service_live_traffic_keeps_idle_timer():
    from pathlib import Path

    src = Path("renderer/service.mjs").read_text(encoding="utf-8")
    assert "const touchLiveIdle" in src
    for handler in ("handleLiveSet", "handleLivePlay", "handleLivePause"):
        block = src.split(f"const {handler}", 1)[1].split("\n};", 1)[0]
        assert "touchLiveIdle()" in block, handler
    # live_latest 是高频轮询，不应触碰 idle 定时器。
    latest_block = src.split("const handleLiveLatest", 1)[1].split("\n};", 1)[0]
    assert "touchLiveIdle" not in latest_block


# ---------------------------------------------------------------------------
# 播放链：范围套用后触发条带预热
# ---------------------------------------------------------------------------


def test_scope_apply_queues_strip_warm():
    _app()
    from twobyteasr.studio import studio_advanced_flow
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from twobyteasr.caption_design.web_theme import builtin_web_themes

    project = SubtitleProject(media=StudioMedia(path="x.mp4"))
    style_id = project.styles[0].id
    from twobyteasr.caption_style.style_recipe import StyleRecipe

    recipe = StyleRecipe(
        name="BJ", engine="remotion",
        typography={"fontFamily": "Microsoft YaHei UI", "fontSize": 58},
        colors={"fill": "#FFE9B8", "outline": "#10181E"},
        web_theme=builtin_web_themes()["balatro-joker"].to_dict(),
    )
    project.style_recipes[style_id] = recipe.to_dict()
    project.cues.append(StudioCue(id="w1", start_ms=0, end_ms=1200, text="甲"))
    project.cues[0].style_id = style_id

    warmed: list[dict] = []

    class _StubWorker:
        running = True

        def warm(self, **kwargs) -> None:
            warmed.append(kwargs)

    class _Harness(studio_advanced_flow.StudioAdvancedFlowMixin):
        def __init__(self) -> None:
            self.project = project
            self._cue_lookup = {cue.id: cue for cue in project.cues}
            self._web_live_worker = _StubWorker()

    harness = _Harness()
    harness._queue_web_strip_warm(["w1"])
    assert len(warmed) == 1
    assert warmed[0]["text"] == "甲"
    assert warmed[0]["duration_seconds"] == pytest.approx(1.2)
    assert warmed[0]["theme"]["name"] == builtin_web_themes()["balatro-joker"].name
