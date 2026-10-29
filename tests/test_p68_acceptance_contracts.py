from __future__ import annotations

import copy
import inspect
import json
import os
import sys
import threading
import time
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame

from twobyteasr.recognition import asr
from twobyteasr.rendering.advanced_preview import AdvancedPreviewIdentity
from twobyteasr.caption_design.studio_ai import (
    AIDesignSuggestion,
    _recipe_signature,
    _semantic_richness,
    request_style_design,
    style_recipe_for_prompt,
    visual_design_variants,
)
from twobyteasr.timeline.studio_edit_sequence import HighlightCandidate
from twobyteasr.timeline.studio_edit_sequence import ensure_edit_sequence, store_sequence
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    SubtitleStyle,
    save_project,
)
from twobyteasr.projects.studio_project_controller import StudioProjectController
from twobyteasr.design.studio_theme import build_studio_qss
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.caption_style.style_presets import BUILTIN_PRESETS, StylePresetStore
from twobyteasr.caption_style.style_recipe import FillSpec, route_recipe
from twobyteasr.design.ui_theme import theme_definition
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _page(monkeypatch, tmp_path, *, show: bool = False) -> SubtitleStudioPage:
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page._create_blank_studio()
    page.project.media = StudioMedia(
        path=str(tmp_path / "fixture.mp4"),
        duration_ms=60_000,
        width=1920,
        height=1080,
    )
    page.project.cues = [StudioCue("cue", 0, 4_000, "真实字幕", style_id="default")]
    sequence = ensure_edit_sequence(page.project)
    sequence.video_track_locked = False
    store_sequence(page.project, sequence)
    page.cue_controller.model_changed()
    page.timeline.reindex_project()
    page.timeline.set_playhead(500)
    page.select_cue("cue")
    page._media_ingest_state = "READY"
    page._empty_playback_state = False
    page.video._paused = True
    page._visibility_trace_ass_event_count = 1
    page._sync_video_empty_state()
    if show:
        page.resize(1500, 900)
        page.show()
        app.processEvents()
        page._empty_playback_state = False
        page.video._paused = True
    return page


def _advanced_page(monkeypatch, tmp_path) -> tuple[SubtitleStudioPage, object, QPixmap]:
    page = _page(monkeypatch, tmp_path, show=True)
    recipe = style_recipe_for_prompt("黄色到青色赛博渐变复杂 glitch")
    recipe.engine = "remotion"
    recipe.colors["fill"] = FillSpec.linear(
        [
            {"color": "#FFFFE45E", "position": 0.0},
            {"color": "#FF20D9FF", "position": 1.0},
        ]
    ).to_dict()
    cue = page.project.cues[0]
    cue.style_id = "gradient"
    style = copy.deepcopy(page.project.styles[0])
    style.id = "gradient"
    style.name = "Gradient"
    page.project.styles.append(style)
    page.project.style_recipes["gradient"] = recipe.to_dict()
    # A structural model notification does not publish changed style data.
    # Commit this authored fixture through the same visual revision domain
    # used by production style commands before preparing any raster.
    from twobyteasr.projects.studio_runtime_state import DirtyDomain
    with page.session.runtime.transaction(page.project, action_id="fixture_gradient_style",
            dirty=DirtyDomain.CUE_STYLE, affected_cue_ids=(cue.id,)):
        pass
    page.cue_controller.model_changed()
    page.select_cue("cue")
    snapshot = build_visual_cue_snapshot(page.project, cue.id, width=1280, height=720)
    identity = page._advanced_preview_cache.identity(
        snapshot, relative_ms=300, width=1280, height=720
    )
    page._advanced_preview_state.select(identity, cache_hit=False)
    page._advanced_preview_state.mark_live(identity)
    pixmap = QPixmap(1280, 720)
    pixmap.fill(QColor("#20D9FF"))
    page._advanced_preview_snapshot = snapshot
    page._advanced_cue_pixmap = pixmap
    page.position_overlay.sync_to_video(page.video)
    page.advanced_cue_overlay.set_base_geometry(page.position_overlay._content_rect().toRect())
    page.advanced_cue_overlay.set_visual(pixmap, snapshot)
    return page, snapshot, pixmap


def _wait_until(predicate, timeout_ms: int = 1500) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000.0
    app = _app()
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        QTest.qWait(10)
    return bool(predicate())


def test_project_open_does_not_spawn_visible_helper(monkeypatch, tmp_path):
    app = _app()
    media = tmp_path / "media.mp4"
    media.write_bytes(b"fixture")
    project_path = tmp_path / "open.2byteproj"
    save_project(
        SubtitleProject(
            media=StudioMedia(path=str(media), duration_ms=8_000, width=1280, height=720),
            cues=[StudioCue("open-cue", 0, 2_000, "打开即见")],
        ),
        project_path,
    )
    page = _page(monkeypatch, tmp_path, show=True)
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_reload_edit_playback", lambda: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda _path: None)
    before = {(type(item).__name__, item.objectName()) for item in app.topLevelWidgets() if item.isVisible()}
    page.open_project(project_path)
    app.processEvents()
    after = {(type(item).__name__, item.objectName()) for item in app.topLevelWidgets() if item.isVisible()}
    assert after == before
    assert not page.advanced_cue_overlay.isWindow()
    assert not page.position_overlay.isWindow()
    page.close_page()


def test_project_open_waveform_async(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    media = tmp_path / "waveform.mp4"
    media.write_bytes(b"fixture")
    started: list[str] = []

    class FakeThread:
        def __init__(self, *, target, daemon, name):
            self.target = target
            self.daemon = daemon
            self.name = name

        def start(self):
            started.append(self.name)

    monkeypatch.setattr("twobyteasr.studio.studio_ui.threading.Thread", FakeThread)
    page._generate_waveform(str(media))
    assert started == ["studio-waveform"]
    assert str(media.resolve()) in page._waveform_inflight
    assert page.timeline.waveform_state == "LOADING"
    page.close_page()


def test_project_open_does_not_regenerate_thumbnail():
    # 2026-09-07：open_project 拆为薄包装（入场动效），实际装载在
    # _open_project_contents——缩略图门控行随迁。
    source = inspect.getsource(StudioProjectController.open_project) + inspect.getsource(
        StudioProjectController._open_project_steps
    )
    assert "thumbnail_requests_enabled = False" in source
    assert "_ensure_project_cover" not in source
    assert "generate_thumbnail" not in source


def test_existing_cue_visible_after_open(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path, show=True)
    trace = page.ensure_active_subtitle_renderer(reason="test_open")
    assert trace["cue_id"] == "cue"
    assert trace["visible"] is True
    assert trace["native_overlay_visible"] is True
    page.close_page()


def test_advanced_failure_never_reintroduces_native_foreground(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path, show=True)
    recipe = style_recipe_for_prompt("复杂 glitch")
    page.project.style_recipes["default"] = recipe.to_dict()
    identity = AdvancedPreviewIdentity("cue", "snap", "glyph", "motion", "request", 300, (640, 360), 30.0)
    generation = page._advanced_preview_state.select(identity, cache_hit=False)
    page._advanced_preview_failed(identity, generation, "renderer fixture failure")
    trace = page.ensure_active_subtitle_renderer(reason="test_failed")
    assert trace["visible"] is False
    assert trace["foreground_owner"] == "none"
    assert trace["foreground_owner_count"] == 0
    assert trace["native_overlay_visible"] is False
    assert trace["native_track_visible"] is False
    assert trace["advanced_canvas_visible"] is False
    page.close_page()


def test_restore_plain_retires_live_canvas_before_native_handoff(monkeypatch, tmp_path):
    page, _snapshot, _pixmap = _advanced_page(monkeypatch, tmp_path)
    monkeypatch.setattr(page,'_caption_sample_ms',lambda:500)
    monkeypatch.setattr(page,'_renderer_cue_at_playhead',lambda:page.project.cues[0])
    page.ensure_active_subtitle_renderer(reason='fixture_advanced')
    canvas=page.advanced_cue_overlay
    assert canvas.isVisible()
    canvas.set_overlay_lifecycle_context(reason='fixture_active',cue_active=True)
    slot=page.video.ADVANCED_OVERLAY_ID
    page.video._active_compositor_overlays.add(slot)
    page.video._compositor_overlay_contexts[slot]=canvas._overlay_context('fixture_active')
    # A same-cue text refresh may already hide the Qt widget while the active
    # cue guard keeps its mpv slot alive. A second hide emits no hideEvent.
    canvas.hide()
    assert slot in page.video.active_compositor_overlay_ids()
    stopped=[]
    worker=types.SimpleNamespace(stop=lambda:stopped.append(True),strip_key='old',_configuration_generation=1)
    page._web_live_worker=worker
    page._web_live_snapshot=_snapshot
    page._web_live_pending_frame=('old',500,500,_snapshot,canvas)
    late_frame=types.SimpleNamespace(worker_id=id(worker),content_key='old',generation=1)
    assert page._web_frame_is_current(late_frame)
    errors=list(page.session.runtime.subscriber_errors)
    try:
        page._clear_advanced_style()
        assert page.session.runtime.subscriber_errors==errors
        trace=page.ensure_active_subtitle_renderer(reason='restored_plain')
        assert trace['foreground_owner']=='native',trace
        assert not canvas.isVisible()
        assert slot not in page.video.active_compositor_overlay_ids()
        assert page.video._native_subtitle_visible
        assert stopped and page._web_live_pending_frame is None
        assert not page._web_frame_is_current(late_frame)
    finally:
        page.close_page()


def test_transform_visible_when_paused_selected(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path, show=True)
    page.position_edit_button.setChecked(True)
    page._empty_playback_state = False
    trace = page.ensure_active_subtitle_renderer(reason="test_transform")
    assert trace["transform_visible"] is True, (
        trace,
        page.isVisible(),
        page._selected_cue_is_at_playhead(page.project.cues[0]),
        page.video._paused,
        page.position_edit_button.isChecked(),
        getattr(page, "_canvas_editor", None),
        page._empty_playback_state,
    )
    assert trace["transform_is_window"] is False
    assert trace["transform_native"] is False
    page.close_page()


def test_transform_overlay_above_advanced_canvas(monkeypatch, tmp_path):
    page, _snapshot, _pixmap = _advanced_page(monkeypatch, tmp_path)
    page.position_edit_button.setChecked(True)
    page._empty_playback_state = False
    trace = page.ensure_active_subtitle_renderer(reason="test_stack")
    assert trace["advanced_canvas_visible"] is True, (
        trace,
        page.isVisible(),
        page._selected_cue_is_at_playhead(page.project.cues[0]),
        page.advanced_cue_overlay._base_rect.getRect(),
        page.advanced_cue_overlay._source.isNull(),
        getattr(page.advanced_cue_overlay._snapshot, "cue_id", None),
    )
    assert trace["transform_visible"] is True
    assert trace["z_order"] == "mpv V1 < bitmap V2+ < subtitle foreground < transform"
    assert page.video.ADVANCED_OVERLAY_ID < page.video.TRANSFORM_OVERLAY_ID
    assert page.advanced_cue_overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert not page.position_overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    page.close_page()


def test_transform_mouse_drag_moves_subtitle(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path, show=True)
    page.position_edit_button.setChecked(True)
    page._empty_playback_state = False
    page.ensure_active_subtitle_renderer(reason="test_mouse_drag")
    overlay = page.position_overlay
    from PySide6.QtCore import QRectF
    # This command test supplies a measured-box fixture; headed tests verify real glyph bounds.
    overlay.set_measured_bounds(QRectF(120,80,220,70))
    rect = overlay._subtitle_rect()
    start = rect.center().toPoint()
    before = (overlay.position_x, overlay.position_y)
    undo_count = page.undo_stack.count()
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(start),
        QPointF(overlay.mapToGlobal(start)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    overlay.mousePressEvent(press)
    assert overlay._dragging is True
    target = start + QPoint(90, -70)
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(target),
        QPointF(overlay.mapToGlobal(target)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    overlay.mouseMoveEvent(move)
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(target),
        QPointF(overlay.mapToGlobal(target)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    overlay.mouseReleaseEvent(release)
    _app().processEvents()
    after = (overlay.position_x, overlay.position_y)
    style = next(item for item in page.project.styles if item.id == page.project.cues[0].style_id)
    assert after != before
    cue = page.project.cues[0]
    from twobyteasr.caption_style.style_resolution import resolve_cue_visual
    resolved = resolve_cue_visual(page.project, cue).style
    assert (round(cue.transform['position_x']), round(cue.transform['position_y'])) == after
    assert (round(resolved.position_x), round(resolved.position_y)) == after
    assert (style.position_x, style.position_y) == (None, None)
    assert page.undo_stack.count() == undo_count + 1
    page.close_page()


def test_clip_assistant_defaults_settings_without_candidates(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    page.highlight_panel.reload_candidates([])
    assert page.highlight_panel.active_stage() == "settings"
    # 三十一轮：候选区常驻（无候选显示占位），设置区折叠钮是唯一入口
    # 2026-10-24 (clip evidence ADR, Codex): this fixture sets project.media without a clip of it in the
    # video graph, so there is no retained recording to analyse and the panel shows its setup guidance
    # (empty_setup) instead of the empty candidate list. Either way an empty state is shown.
    panel = page.highlight_panel
    assert panel.candidates_empty.isVisibleTo(panel) or panel.empty_setup.isVisibleTo(panel)
    page.close_page()


def test_clip_assistant_opens_candidates_after_analysis(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    candidate = HighlightCandidate("candidate", "高能反转", 1_000, 7_000, score=0.92)
    page.highlight_panel.reload_candidates([candidate])
    assert page.highlight_panel.active_stage() == "candidates"
    assert page.highlight_panel.results.count() == 1
    assert not page.highlight_panel.candidates_empty.isVisibleTo(page.highlight_panel)
    page.close_page()


def _open_recognition(page: SubtitleStudioPage, tmp_path: Path) -> dict:
    media = tmp_path / "recognition.flv"
    media.write_bytes(b"fixture")
    page.project.media.path = str(media)
    page.project.glossary_ids = ["洛克王国", "绝区零"]
    page.project_path = tmp_path / "recognition.2byteproj"
    page._open_recognition_sheet()
    return page._recognition_controls


def test_recognition_dialog_theme_tokens(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    _open_recognition(page, tmp_path)
    sheet = page._recognition_sheet
    plum = theme_definition("plum")
    qss = build_studio_qss(plum).lower()
    assert sheet.objectName() == "studioRecognitionSheet"
    # 2026-10-23 layout C: three model-role rows on the left, one 「这次识别」 panel on the right.
    assert len(sheet.findChildren(QFrame, "sheetRoleRow")) == 3
    assert len(sheet.findChildren(QFrame, "recognitionSummary")) == 1
    assert plum.text.lower() in qss
    assert plum.surface.lower() in qss
    page.close_page()


def test_recognition_dialog_supports_profile_models_termbases(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    controls = _open_recognition(page, tmp_path)
    # 方案与主页 plan_options() 对齐 + "当前主页方案"（2026-10-22：删去四项、加云端方案）。
    plan_keys = {controls["plan"].itemData(i) for i in range(controls["plan"].count())}
    assert plan_keys == {"quality", "japanese", "english", "moss_pro_qwen", "home"}
    assert all(controls[key].count() >= 3 for key in ("primary", "timeline", "review"))
    # 四十三轮：词库是常驻勾选 chips（QCheckBox 网格，不再走下拉 popup）。
    chips_host = controls["glossaries"]
    from PySide6.QtWidgets import QCheckBox

    boxes = chips_host.findChildren(QCheckBox)
    assert {box.text() for box in boxes} == {"洛克王国", "绝区零"}
    # 三十一轮：默认不选任何词库（不再沿用主页全局记忆的默认勾选）
    assert all(not box.isChecked() for box in boxes)
    # 2026-09-07（双轨反馈）：快速分析用途已删——识别弹窗恒为最终字幕。
    assert "analysis" not in controls
    assert controls["start"].text() in ("识别字幕", "识别并替换当前字幕")
    sheet = page._recognition_sheet
    from PySide6.QtWidgets import QRadioButton

    assert not sheet.findChildren(QRadioButton)
    page.close_page()


def test_analysis_worker_warm_reuse(monkeypatch):
    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False, empty_cache=lambda: None)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    asr.end_local_asr_session(force=True)
    marker = object()
    asr.begin_local_asr_session(persistent=True)
    try:
        asr._reuse_or_remember_qwen_model(marker)
        before = asr.local_asr_session_state()["warm_reuses"].get("qwen3-asr", 0)
        assert asr._session_qwen_model() is marker
        state = asr.local_asr_session_state()
        assert state["persistent"] is True
        assert state["warm_reuses"].get("qwen3-asr", 0) == before + 1
    finally:
        asr.end_local_asr_session(force=True)


def test_analysis_purpose_skips_expensive_final_stages():
    source = (Path(__file__).resolve().parents[1] / "moss_firered_pipeline.py").read_text(encoding="utf-8")
    assert '== "analysis"' in source
    assert "stage_total = 8 if analysis_transcript else 11" in source
    assert 'skips=["review_asr", "firered_llm", "cloud_polish", "ai_grouping"]' in source
    import moss_firered_pipeline as pipeline
    events = []
    legacy = types.SimpleNamespace(record_run_event=lambda event, **data: events.append((event, data)))
    def forbidden_runner():
        raise AssertionError('analysis must not invoke the skipped model')
    assert pipeline._run_audited_model_stage(legacy, model_id='qwen3-asr',
        role='text_verification', backend='local', media_path='not-opened.wav',
        worker='', runtime='', runner=forbidden_runner, selected=False,
        skip_reason='analysis_transcript') == []
    assert [event for event, _ in events] == ['MODEL_SKIPPED']
    assert events[0][1]['failure_reason'] == 'analysis_transcript'
    assert "if not analysis_transcript:" in source
    assert "not analysis_transcript\n        and legacy.RUNTIME_SETTINGS" in source
    assert "analysis_transcript_pipeline" in source


def test_ai_preview_centered(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    visual = visual_design_variants("1930s 橡皮管胶片动画风")[0]
    snapshot = page._ai_variant_snapshot(visual, 0)
    assert snapshot.resolution == (640, 240)
    assert (snapshot.position_x, snapshot.position_y, snapshot.alignment) == (960.0, 540.0, 5)
    assert snapshot.font_size >= 88
    assert snapshot.text == "精彩操作 Aa 123\n第二行测试字幕"
    page.close_page()


def test_ai_preview_real_motion(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    image = QPixmap(640, 240)
    image.fill(QColor("#FFE45E"))
    target = tmp_path / "motion.png"
    assert image.save(str(target), "PNG")
    def render_batch(requests, **_kwargs):
        return [(f'card-{relative_ms}',target,False) for _snapshot,relative_ms,_w,_h in requests]
    monkeypatch.setattr(page._advanced_preview_cache,'render_snapshot_batch',render_batch)
    import hashlib
    from twobyteasr.studio import studio_ai_flow
    composite=studio_ai_flow.composite_live_scene_layers
    samples=[]
    def measured(layers,scene,relative_ms,**kwargs):
        image,state=composite(layers,scene,relative_ms,**kwargs)
        samples.append((relative_ms,hashlib.sha256(image.constBits()).hexdigest()))
        return image,state
    monkeypatch.setattr(studio_ai_flow,'composite_live_scene_layers',measured)
    variants=tuple(visual_design_variants('1930s 橡皮管胶片动画风'))
    page._ai_ready(AIDesignSuggestion('cue',variants[0].to_style_recipe(),variants=variants))
    assert _wait_until(lambda:len(page._ai_variant_preview_labels)==3)
    page._play_ai_variant_motion(0,variants[0])
    assert 0 in page._ai_variant_motion_timers
    assert page._ai_variant_motion_timers[0].interval()==33
    assert _wait_until(lambda:0 not in page._ai_variant_motion_timers,timeout_ms=4000)
    assert len({digest for _,digest in samples})>3
    assert any(t<250 for t,_ in samples) and any(600<t<1800 for t,_ in samples) and any(t>2200 for t,_ in samples)
    page._play_ai_variant_motion(0,variants[0])
    timer=page._ai_variant_motion_timers[0]
    page._ai_variant_preview_generation+=1
    assert _wait_until(lambda:not timer.isActive())
    page.close_page()


def test_ai_recipe_supports_background_card():
    recipe = style_recipe_for_prompt("1930s 橡皮管胶片动画风")
    assert route_recipe(recipe).engine == "remotion"
    assert recipe.background["enabled"] is True
    assert recipe.background["type"] == "film_card"
    assert recipe.background["border"]["width"] > 0
    assert recipe.background["texture"]["type"] == "film_grain"


def test_ai_recipe_semantic_richness_retry(monkeypatch):
    monkeypatch.setattr('twobyteasr.caption_design.studio_ai.available_font_shortlist',lambda **_: {'serif':['SimSun'],'handwriting':['KaiTi'],'chinese_sans':['Microsoft YaHei UI']})
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=4_000, width=1280, height=720),
        cues=[StudioCue("cue", 0, 2_400, "精彩操作")],
    )
    instruction = "1930s 橡皮管胶片动画风"
    from twobyteasr.caption_design.visual_design_graph import VisualDesignGraph, validate_structural_variants, style_recipe_from_graph
    from twobyteasr.caption_design.art_direction import score_visual_graph
    valid = json.loads((Path(__file__).parent/'fixtures/retro_native_variants.json').read_text(encoding='utf8'))
    graphs = [VisualDesignGraph.from_dict(item) for item in valid]
    validate_structural_variants(graphs)
    for graph in graphs:
        quality = score_visual_graph(graph)
        assert quality.accepted, quality.to_dict()
        assert _semantic_richness(style_recipe_from_graph(graph), instruction)[0] >= 3
    responses = [
        {"design_intent": "generic", "visual_changes": [], "motion_reason": "", "variants": []},
        {
            "design_intent": "三套复古动态方向",
            "visual_changes": ["字体", "色彩", "描边"],
            "motion_reason": "真实入口、保持与退出",
            "variants": valid,
        },
    ]

    class Provider:
        provider_id = "fixture"

        def structured_complete(self, *_args, **_kwargs):
            return copy.deepcopy(responses.pop(0))

    monkeypatch.setattr("twobyteasr.caption_design.studio_ai.provider_for_stage", lambda *_a, **_k: Provider())
    result = request_style_design(project, "cue", instruction, {"models": {"polish": "fixture"}})
    score, _hits = _semantic_richness(result.recipe, instruction)
    assert result.provider_succeeded, result.rationale
    assert len(result.variants) == 3
    assert score >= 3
    assert result.provider_succeeded and result.repair_attempted
    assert responses == []


def test_ai_variant_diversity(monkeypatch):
    monkeypatch.setattr(
        "twobyteasr.caption_design.studio_ai.available_font_shortlist",
        lambda *_a, **_k: {
            "serif": ["SimSun"],
            "handwriting": ["KaiTi"],
            "chinese_sans": ["Microsoft YaHei UI"],
            "chinese_display": ["SimHei"],
            "pixel_game": ["Consolas"],
            "cartoon": ["KaiTi"],
        },
    )
    variants = visual_design_variants("1930s 橡皮管胶片动画风")
    signatures = [_recipe_signature(item.to_style_recipe()) for item in variants]
    varying_dimensions = sum(1 for values in zip(*signatures) if len(set(values)) > 1)
    assert len(variants) == 3
    assert varying_dimensions >= 3


def test_gradient_visible_in_studio_integration(monkeypatch, tmp_path):
    page, snapshot, _pixmap = _advanced_page(monkeypatch, tmp_path)
    published: list[tuple[int, object, object]] = []
    monkeypatch.setattr(
        page.video,
        "publish_compositor_overlay",
        lambda overlay_id, image, rect, **_kwargs: published.append((overlay_id, image, rect)) or True,
    )
    page.advanced_cue_overlay._last_mpv_publish_signature = None
    page._empty_playback_state = False
    trace = page.ensure_active_subtitle_renderer(reason="gradient_integration")
    assert _wait_until(lambda: any(item[0] == page.video.ADVANCED_OVERLAY_ID for item in published))
    fill = FillSpec.from_value(snapshot.fill).to_dict()
    assert [stop["color"] for stop in fill["stops"]] == ["#FFFFE45E", "#FF20D9FF"]
    assert trace["renderer_route"] == "advanced"
    assert trace["advanced_canvas_visible"] is True
    page.close_page()


def test_preset_manager_bulk_delete_ai(tmp_path):
    store = StylePresetStore(tmp_path / "presets")
    store.upsert(SubtitleStyle("ai-a", "AI A"), source="ai")
    store.upsert(SubtitleStyle("ai-b", "AI B"), source="ai")
    store.upsert(SubtitleStyle("custom", "Custom"), source="custom")
    assert store.delete_all_ai(keep_favorites=False) == 2
    assert set(store.load_user()) == {"custom"}
    assert set(BUILTIN_PRESETS).issubset(store.all())


def test_native_cue_after_web_cue_stays_visible_without_selection_follow(
    monkeypatch, tmp_path,
):
    """二十八轮回归：web cue 放完→衔接的普通字幕必须可见。

    用户实测：特效字幕结束后，下一条普通字幕直接消失。根因是
    ensure_active_subtitle_renderer 的 NATIVE 分支用 cue_inside（选中 cue
    在播头）做门——手动选择锁让选择钉在已放完的 web cue 上，每个位置
    tick 都重复 set_native_subtitle_visible(False)。修复后以
    audio_cue_inside（播头确实在 cue 内）为准。
    """
    page = _page(monkeypatch, tmp_path, show=True)
    project = page.project
    project.cues = [
        StudioCue("web", 0, 4_000, "特效字幕", style_id="default"),
        StudioCue("native", 4_000, 8_000, "衔接的普通字幕", style_id="default"),
    ]
    sequence = ensure_edit_sequence(project)
    store_sequence(project, sequence)
    page.cue_controller.model_changed()
    page.timeline.reindex_project()
    # 选择钉在 web cue（模拟手动选择锁），播头已进入后一条普通 cue。
    page.select_cue("web")
    page.timeline.set_playhead(5_000)
    calls: list[bool] = []
    original = page.video.set_native_subtitle_visible

    def _record(visible: bool) -> None:
        calls.append(bool(visible))
        original(visible)

    page.video.set_native_subtitle_visible = _record
    trace = page.ensure_active_subtitle_renderer(reason="playhead")
    assert trace["cue_id"] == "native"
    assert trace["visible"] is True, trace
    assert trace["native_track_visible"] is True, trace
    assert calls and calls[-1] is True, (
        "native visibility must be restored when the playhead sits in a "
        f"native cue even though selection stayed behind (calls={calls})"
    )
    page.close_page()
