from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainterPath
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.rendering.advanced_live_renderer import outside_stroke_ring, render_live_snapshot
from twobyteasr.rendering.advanced_preview import AdvancedPreviewIdentity, AdvancedPreviewPhase, AdvancedPreviewStateMachine
from twobyteasr.providers.ai_providers import AntigravityCLIProvider, ProviderStatus
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio.studio_ui import WaveformTimeline
from tests.test_p8b_stroke_contract import _snapshot
from scripts.verify_p8c_runtime import _studio_settings_path_for_profile


def _glyph_path(text: str) -> QPainterPath:
    QApplication.instance() or QApplication([])
    font = QFont("Source Han Sans Heavy")
    font.setPixelSize(115)
    path = QPainterPath()
    path.addText(QPointF(60, 140), font, text)
    return path


def test_true_outside_ring_never_intersects_original_glyph_area():
    glyph = _glyph_path("0 8 B 中 口 回")
    ring = outside_stroke_ring(glyph, 20)

    assert not ring.isEmpty()
    assert ring.intersected(glyph).isEmpty()


def test_reopen_harness_writes_the_application_settings_path(tmp_path):
    path = _studio_settings_path_for_profile(tmp_path)

    assert path == tmp_path / "2ByteASR" / "SubtitleStudioPreview" / "settings.json"
    assert path.parent.name == "SubtitleStudioPreview"


def test_transparent_fill_keeps_live_glyph_interior_transparent():
    snapshot = replace(
        _snapshot(20),
        text="0 8 B 中 口 回",
        fill={"type": "solid", "color": "#00FFFFFF"},
    )
    image = render_live_snapshot(
        snapshot,
        width=1920,
        height=1080,
        layers=frozenset({"text"}),
    )
    font = QFont(snapshot.font_family)
    font.setPixelSize(round(snapshot.font_size))
    font.setWeight(QFont.Weight(snapshot.font_weight))
    metrics = QFontMetricsF(font)
    glyph = QPainterPath()
    glyph.addText(QPointF(0, metrics.ascent()), font, snapshot.text)
    bounds = glyph.boundingRect()
    glyph.translate(
        snapshot.position_x - bounds.left() - bounds.width() * snapshot.anchor_x,
        snapshot.position_y - bounds.top() - bounds.height() * snapshot.anchor_y,
    )
    interior_samples = []
    for y in range(max(0, int(glyph.boundingRect().top())), min(image.height(), int(glyph.boundingRect().bottom()) + 1), 2):
        for x in range(max(0, int(glyph.boundingRect().left())), min(image.width(), int(glyph.boundingRect().right()) + 1), 2):
            point = QPointF(x + 0.5, y + 0.5)
            if all(glyph.contains(point + delta) for delta in (QPointF(0, 0), QPointF(-2, 0), QPointF(2, 0), QPointF(0, -2), QPointF(0, 2))):
                interior_samples.append(image.pixelColor(x, y).alpha())

    assert interior_samples
    # Text antialiasing may leave a faint subpixel fringe even two logical
    # pixels inside the path. A centered stroke regression would make these
    # samples opaque, while the true outside ring stays effectively clear.
    assert max(interior_samples) <= 25
    assert any(image.pixelColor(x, y).alpha() > 0 for y in range(image.height()) for x in range(image.width()))


def test_remotion_uses_source_alpha_difference_instead_of_fill_overdraw():
    component = Path("renderer/src/components/OutsideStrokeText.tsx").read_text(encoding="utf-8")
    trusted = Path("renderer/src/components/TrustedSubtitle.tsx").read_text(encoding="utf-8")
    graph = Path("renderer/src/components/VisualDesignGraphSubtitle.tsx").read_text(encoding="utf-8")

    assert 'operator="dilate"' in component
    assert 'operator="out"' in component
    assert 'in2="SourceAlpha"' in component
    assert "WebkitTextStroke: '0 transparent'" in component
    assert "<OutsideStrokeText" in trusted
    assert "<OutsideStrokeText" in graph


def test_style_mutation_invalidates_old_fidelity_before_debounced_render():
    state = AdvancedPreviewStateMachine()
    old = AdvancedPreviewIdentity("cue", "s1", "g1", "m1", "r1", 0, (640, 360), 30.0, "graph-1")
    old_generation = state.select(old, cache_hit=False)

    invalidated_generation = state.invalidate_current()

    assert invalidated_generation > old_generation
    assert state.phase is AdvancedPreviewPhase.STALE
    assert state.publish_ready(old, old_generation, "stale.png") is False


def test_antigravity_uses_installed_print_contract_and_never_login_subcommand(monkeypatch):
    provider = AntigravityCLIProvider(
        executable=str(Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe"),
        model="gemini-3.7-flash-high",
    )
    command = provider._request_command("2ByteASR_OK", None)
    assert command[1:3] == ["-p", "2ByteASR_OK"]
    assert "--model" in command
    assert "login" not in command
    # 二十八轮：模型名自带 -high/-medium/-low 推理档后缀时再传 --effort 会被
    # CLI 拒收（"invalid model selection ... conflicts with --effort"），曾被
    # 误诊成"登录失败"。
    assert "--effort" not in command, "model with -high suffix must not double-specify --effort"
    plain = AntigravityCLIProvider(
        executable=str(Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe"),
        model="gemini-3.7-flash",
    )
    assert "--effort" in plain._request_command("2ByteASR_OK", None), (
        "plain model keeps explicit --effort"
    )

    class _AliveLoginProcess:
        pid = 424242
        _stopped = False

        def poll(self):
            return 0 if self._stopped else None

        def kill(self):
            self._stopped = True

        def wait(self, timeout=None):
            return 0

    launched = []
    monkeypatch.setattr(
        provider,
        "detect_installation",
        lambda **_kwargs: ProviderStatus(True, False, "CLI 已安装"),
    )
    monkeypatch.setattr(provider, "_launch_interactive_login", lambda: launched.append([]))
    monkeypatch.setattr(
        provider, "validate", lambda **_kwargs: ProviderStatus(True, False, "CLI 尚未登录")
    )
    monkeypatch.setattr(
        provider,
        "_start_hidden_login_stream",
        lambda command: (
            _AliveLoginProcess(),
            {"url": "https://accounts.google.com/auth", "output": [], "lock": __import__("threading").Lock()},
        ),
    )
    monkeypatch.setattr(
        provider,
        "_login_probe",
        lambda **_kwargs: ProviderStatus(True, True, "ok", ("gemini-3.7-flash-high",)),
    )
    status = provider.login()
    # 新契约（2026-09 无头登录）：登录默认零窗口——隐藏流捕获 URL + 就绪
    # 轮询收尾，交互控制台只在隐藏流拿不到链接时兜底。
    assert launched == []
    assert status.available and status.authenticated
    assert "无需保持任何外部窗口" in status.message


def test_antigravity_successful_models_stdout_wins_over_stale_auth_log(monkeypatch):
    provider = AntigravityCLIProvider(executable=r"C:\tools\agy.exe")
    monkeypatch.setattr(
        provider,
        "detect_installation",
        lambda **_kwargs: ProviderStatus(True, False, "CLI 已安装"),
    )
    def run(command, **_kwargs):
        if len(command) > 1 and command[1] == "models":
            return subprocess.CompletedProcess(
                command,
                0,
                "gemini-3.7-flash-high\tGemini 3.7 Flash High\n",
                "startup cache: You are not logged into Antigravity.\n",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            '{"result":"2ByteASR_OK"}',
            "startup cache: You are not logged into Antigravity.\n",
        )

    monkeypatch.setattr(provider, "_run_cli_command", run)
    status = provider.validate(use_cache=False)
    assert status.authenticated
    assert status.models == ()  # status probing does not enumerate models
    assert provider.discover_models(refresh=True) == ("gemini-3.7-flash-high",)


def test_cli_adapter_exposes_shared_detect_auth_model_invoke_cancel_surface():
    provider = AntigravityCLIProvider(executable=r"C:\tools\agy.exe")
    # P9A provider unification renamed the shared surface; assert the current
    # AIProvider/CLIProvider contract instead of the pre-unification names.
    assert all(callable(getattr(provider, name)) for name in (
        "detect_installation", "validate", "login",
        "discover_models", "complete", "structured_complete",
        "cancel",
    ))


def _near_color_pixels(image, rect, target: QColor, tolerance: int = 28) -> int:
    total = 0
    for y in range(max(0, rect.top()), min(image.height(), rect.bottom() + 1)):
        for x in range(max(0, rect.left()), min(image.width(), rect.right() + 1)):
            color = image.pixelColor(x, y)
            if max(
                abs(color.red() - target.red()),
                abs(color.green() - target.green()),
                abs(color.blue() - target.blue()),
            ) <= tolerance:
                total += 1
    return total


def _logical_image_rect(image, rect):
    ratio = float(image.devicePixelRatio())
    return type(rect)(
        round(rect.x() * ratio),
        round(rect.y() * ratio),
        max(1, round(rect.width() * ratio)),
        max(1, round(rect.height() * ratio)),
    )


def test_timeline_header_icons_remain_visible_through_hover_partial_repaints():
    app = QApplication.instance() or QApplication([])
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=10_000),
        speakers=[StudioSpeaker("S01", "玩家")],
        cues=[StudioCue("cue", 0, 2_000, "测试", speaker_id="S01")],
    )
    project.validate()
    timeline = WaveformTimeline()
    timeline.resize(980, 360)
    timeline.set_project(project)
    timeline.show()
    app.processEvents()
    palette = timeline._timeline_palette()
    icon_color = QColor(palette.header_icon)

    video = timeline._video_track_rect("V1")
    audio = timeline._audio_track_rects()["A1"]
    speaker = timeline._track_layout()[0]["S01"]
    controls = [
        (x, video, 14) for x in (132, 156, 180, 204)
    ] + [
        (x, audio, 18) for x in (108, 136, 164)
    ] + [
        (x, speaker, 19) for x in (150, 178, 206)
    ]
    for left, track_rect, y_offset in controls:
        QTest.mouseMove(
            timeline,
            QPoint(left + 10, round(track_rect.top() + track_rect.height() / 2)),
        )
        app.processEvents()
        image = timeline.grab().toImage()
        logical_sample = timeline.rect().intersected(
            type(image.rect())(
                left + 3,
                round(track_rect.top()) + y_offset - 8,
                19,
                24,
            )
        )
        sample = image.rect().intersected(_logical_image_rect(image, logical_sample))
        assert _near_color_pixels(image, sample, icon_color) >= 2, (left, track_rect)

    timeline.close()
    timeline.deleteLater()
