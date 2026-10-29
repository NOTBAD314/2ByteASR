"""Round 15 (2026-09-02 evening): AI subtitle closure.

Covers the four user-reported defects and the new archive/refine features:
1. Stall watchdog misclassification — "AI 请求已取消。" raised by the
   provider's cancel branch must fall back to the built-in theme with a
   clear timeout message, NOT surface as a user cancellation.
2. User cancellation must still persist a trace (previously invisible).
3. refine_web_theme_design — edit roundtrip + original preserved on failure.
4. Theme archive export/import roundtrip (standalone HTML + JSON).
5. HTTP provider SSE stream with graceful fallback to the plain request.
6. Advanced export overlay stall watchdog kills a silent child process.
7. AI panel apply scope (current / speaker / all).
"""

from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
)
from twobyteasr.caption_design.web_theme import (
    builtin_web_themes,
    export_theme_archive,
    fallback_web_theme,
    import_theme_archive,
)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _to_sections(theme: dict) -> str:
    palette = " ".join(f"{key}={value}" for key, value in theme.get("palette", {}).items())
    return (
        f"===NAME===\n{theme.get('name', '')}\n"
        f"===CONCEPT===\n{theme.get('concept', '')}\n"
        f"===PALETTE===\n{palette}\n"
        f"===STAGE_HTML===\n{theme.get('stageHtml', '')}\n"
        f"===STAGE_CSS===\n{theme.get('stageCss', '')}\n"
        f"===CUE_HTML===\n{theme.get('cueHtml', '')}\n"
        f"===CUE_CSS===\n{theme.get('cueCss', '')}\n"
        f"===NOTES===\n{theme.get('notes', '')}\n"
    )


def _install_fake_provider(monkeypatch, provider):
    from twobyteasr.caption_design import studio_ai

    monkeypatch.setattr(studio_ai, "provider_for_stage", lambda *_a, **_k: provider)

    class FakeSelection:
        credential_ready = True
        provider = "fake"
        service = "fake"
        model = "m"

    class FakeRegistry:
        def settings(self):
            return {"models": {}}

        def bind(self, _settings):
            return {"models": {}}

        def selection(self, *_a, **_k):
            return FakeSelection()

    monkeypatch.setattr(studio_ai, "GLOBAL_PROVIDER_REGISTRY", FakeRegistry())
    monkeypatch.setattr(
        studio_ai, "available_font_shortlist",
        lambda **_k: {"chinese_sans": ["Microsoft YaHei UI"]},
    )
    return studio_ai


def _project() -> SubtitleProject:
    project = SubtitleProject(media=StudioMedia(path="x.mp4"))
    project.speakers.append(StudioSpeaker(id="S01", name="主播"))
    project.speakers.append(StudioSpeaker(id="S02", name="嘉宾"))
    for index in range(4):
        cue = StudioCue(
            id=f"c{index}",
            start_ms=index * 1000,
            end_ms=index * 1000 + 900,
            text=f"第{index}句字幕",
            speaker_id="S01" if index < 3 else "S02",
        )
        project.cues.append(cue)
    return project


# ---------------------------------------------------------------------------
# 1) stall watchdog classification
# ---------------------------------------------------------------------------

class _StallProvider:
    """Mimics CLIProvider.complete when the CLI hangs behind an auth wall:
    zero stream events, and the shared cancel_check trips the stall watchdog
    which the provider reports as a generic cancelled error."""

    provider_id = "fake_stall"

    def validate(self, **_kwargs):
        return None

    def complete(self, _messages, *, cancel_check=None, on_stream_event=None, **_k):
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            if cancel_check is not None and cancel_check():
                from twobyteasr.providers.ai_providers import AIProviderError

                raise AIProviderError("AI 请求已取消。", category="cancelled")
            time.sleep(0.05)
        raise AssertionError("stall watchdog never fired within test budget")


def _authored_provider(monkeypatch, provider):
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE,'client_for_stage',lambda *a,**kw:provider)
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY,'selection',lambda *a,**kw:SimpleNamespace(provider='fixture',model='fixture'))


def test_stall_watchdog_reports_timeout_without_authored_fallback(monkeypatch, tmp_path):
    import json
    from twobyteasr.caption_design import studio_ai
    from twobyteasr.providers.ai_providers import AIProviderError
    from twobyteasr.caption_design.theme_generation_policy import ThemeGenerationLimits
    _authored_provider(monkeypatch,_StallProvider())
    monkeypatch.setattr(ThemeGenerationLimits,'from_settings',lambda *a,**kw:ThemeGenerationLimits(8,8,.2))
    with pytest.raises(AIProviderError) as failure:
        studio_ai.request_web_theme_design(_project(),'c0','测试',{'models':{}},ledger_root=tmp_path)
    assert failure.value.category=='provider_inactivity_timeout'
    ledger=json.loads(Path(failure.value.trace_path).read_text('utf8'))
    assert ledger['status']=='failed' and ledger['provider_phase']['error_category']=='provider_inactivity_timeout'
    assert not ledger.get('concepts')


def test_user_cancel_persists_trace_and_raises(monkeypatch, tmp_path):
    import json
    from twobyteasr.caption_design import studio_ai
    from twobyteasr.providers.ai_providers import AIProviderError
    _authored_provider(monkeypatch,_StallProvider())
    with pytest.raises(AIProviderError) as failure:
        studio_ai.request_web_theme_design(_project(),'c0','测试',{'models':{}},ledger_root=tmp_path,cancel_check=lambda:True)
    assert failure.value.category=='cancelled'
    ledger=json.loads(Path(failure.value.trace_path).read_text('utf8'))
    assert ledger['status']=='failed' and ledger['failure_diagnostics']['cancellation_requested']


def test_cli_stderr_surfaces_as_stream_event():
    from twobyteasr.providers.ai_providers import CLIProvider

    events: list[tuple[str, str]] = []
    state: dict = {}
    # Synthetic NDJSON lines: an auth failure writes only stderr; the pump
    # must forward it so the panel shows WHY nothing streams.
    import json as _json

    stdout_lines = [
        _json.dumps({"type": "result", "result": "ok"}) + "\n",
    ]
    stderr_lines = ["Error: Unauthorized (401): INVALID_API_KEY\n"]

    class _Proc:
        returncode = 0

        class _Stream:
            def __init__(self, lines):
                self._lines = list(lines)

            def readline(self):
                return self._lines.pop(0) if self._lines else ""

        stdout = None  # assigned below
        stderr = None

    proc = _Proc()
    proc.stdout = _Proc._Stream(stdout_lines)
    proc.stderr = _Proc._Stream(stderr_lines)
    emit = CLIProvider._consume_cli_stream_line  # parse path still works
    for line in stdout_lines:
        emit(line.strip(), state, lambda k, d: events.append((k, d)))
    assert state.get("final") == "ok"


# ---------------------------------------------------------------------------
# 2) refine_web_theme_design
# ---------------------------------------------------------------------------

class _PayloadProvider:
    provider_id = "fake_refine"

    def __init__(self, payloads):
        self.payloads = list(payloads)

    def validate(self, **_kwargs):
        return None

    def complete(self, _messages, **_kwargs):
        return self.payloads.pop(0)


def test_refine_roundtrip_applies_requested_change(monkeypatch, tmp_path):
    from twobyteasr.caption_design import studio_ai

    original = builtin_web_themes()["balatro-joker"].to_dict()
    # 二十一生成闸门：CONCEPT 需类名承诺清单。
    # Retain the current author DOM/concept and explicit GSAP contract.
    modified = dict(original, name="Balatro 改色版", palette=dict(original["palette"], text="#FF3355"))
    studio_ai = _install_fake_provider(
        monkeypatch, _PayloadProvider([__import__('json').dumps(modified,ensure_ascii=False)]),
    )
    monkeypatch.setattr(studio_ai, "_WEB_THEME_STALL_SECONDS", 1.0)
    monkeypatch.setattr(studio_ai, "_persist_ai_design_trace", lambda _t: "")
    suggestion = studio_ai.refine_web_theme_design(
        original, "把主文字颜色改成红色 #FF3355", cue_text="测试字幕",
    )
    assert suggestion.source == "refined"
    assert suggestion.theme["name"] == "Balatro 改色版"
    assert suggestion.theme["palette"]["text"] == "#FF3355"
    # Untouched sections survive (modulo validate()'s whitespace strip).
    assert suggestion.theme["cueCss"].strip() == original["cueCss"].strip()


def test_refine_failure_keeps_original_theme(monkeypatch, tmp_path):
    from twobyteasr.caption_design import studio_ai
    from twobyteasr.caption_design.web_theme import WebThemeDocument

    original = fallback_web_theme("原主题").to_dict()
    studio_ai = _install_fake_provider(
        monkeypatch, _PayloadProvider(["完全不是主题格式的输出", "还是不行"]),
    )
    monkeypatch.setattr(studio_ai, "_WEB_THEME_STALL_SECONDS", 1.0)
    monkeypatch.setattr(studio_ai, "_persist_ai_design_trace", lambda _t: "")
    suggestion = studio_ai.refine_web_theme_design(original, "改成蓝色")
    assert suggestion.source == "refine_failed"
    # The ORIGINAL theme is returned unchanged (normalized through validate).
    assert suggestion.theme == WebThemeDocument.from_dict(original).to_dict()
    assert "已保留原主题" in suggestion.message


# ---------------------------------------------------------------------------
# 3) theme archive
# ---------------------------------------------------------------------------

def test_theme_archive_export_import_roundtrip(tmp_path):
    from twobyteasr.caption_design.web_theme import WebThemeDocument

    theme = builtin_web_themes()["balatro-joker"].to_dict()
    folder = export_theme_archive(theme, tmp_path, sample_text="归档测试字幕")
    assert folder.name.endswith(".2byte-theme")
    html = (folder / "theme.html").read_text(encoding="utf-8")
    assert "wt-theme-data" in html and "setTimeout(replay" in html
    # Roundtrip normalizes via validate(); compare equally-normalized forms
    # (the archive side re-validates once more than the in-memory theme).
    back = import_theme_archive(folder)
    expected = WebThemeDocument.from_dict(
        WebThemeDocument.from_dict(theme).to_dict()
    ).to_dict()
    assert back == expected
    assert import_theme_archive(folder / "theme.html") == back
    with pytest.raises(Exception):
        import_theme_archive(tmp_path)


# ---------------------------------------------------------------------------
# 4) HTTP provider SSE + fallback
# ---------------------------------------------------------------------------

def test_http_provider_streams_then_falls_back(monkeypatch):
    from twobyteasr.providers.ai_providers import OpenAICompatibleProvider
    from twobyteasr.providers import ai_providers
    from twobyteasr.providers.llm_adapter import LLMRequestError

    endpoint = {
        "provider": "deepseek", "model": "m1", "api_key": "k", "url": "http://x/v1",
        "base_url": "http://x", "protocol": "openai_compatible_chat",
    }
    calls: list[str] = []
    stream_results = ["", "streamed-ok"]

    def fake_stream(*_a, **_k):
        calls.append("stream")
        result = stream_results.pop(0)
        if result == "":
            raise LLMRequestError("HTTP 500：boom", category="server_error")
        on_event = _k.get("on_stream_event")
        if on_event:
            on_event("delta", "streamed-")
        return result

    def fake_sender(*_a, **_k):
        calls.append("sender")
        return "plain-ok"

    provider = OpenAICompatibleProvider(endpoint, sender=fake_sender)
    import twobyteasr.providers.llm_adapter as llm_adapter

    monkeypatch.setattr(llm_adapter, "post_chat_completion_stream", fake_stream)
    events: list[tuple[str, str]] = []

    # First: stream raises server error → falls back to the plain sender.
    assert provider.complete([{"role": "user", "content": "hi"}], on_stream_event=lambda k, d: events.append((k, d))) == "plain-ok"
    assert calls == ["stream", "sender"]
    # Fallback note surfaced as a stage event.
    assert any(kind == "stage" and "整段" in detail for kind, detail in events)

    # Second: stream returns text → used directly, deltas forwarded.
    calls.clear(); events.clear()
    assert provider.complete([{"role": "user", "content": "hi"}], on_stream_event=lambda k, d: events.append((k, d))) == "streamed-ok"
    assert calls == ["stream"]
    assert ("delta", "streamed-") in events


# ---------------------------------------------------------------------------
# 5) overlay stall watchdog
# ---------------------------------------------------------------------------

def test_run_streaming_process_stall_watchdog():
    from twobyteasr.rendering.advanced_renderer import _run_streaming_process

    code = (
        "import sys, time\n"
        "print('first line', flush=True)\n"
        "time.sleep(60)\n"
    )
    command = [sys.executable.replace("/", os.sep), "-c", code]
    started = time.monotonic()
    with pytest.raises(RuntimeError) as excinfo:
        _run_streaming_process(command, on_line=None, cancelled=None, stall_timeout=2.0)
    assert "无输出" in str(excinfo.value)
    assert time.monotonic() - started < 30


# ---------------------------------------------------------------------------
# 6) AI panel apply scope
# ---------------------------------------------------------------------------

def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _page(tmp_path):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    os.environ["LOCALAPPDATA"] = str(tmp_path / "local")
    page = SubtitleStudioPage()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"v")
    project = SubtitleProject(
        media=StudioMedia(path=str(video), duration_ms=60_000, width=1920, height=1080),
    )
    project.speakers.append(StudioSpeaker(id="S01", name="主播"))
    project.speakers.append(StudioSpeaker(id="S02", name="嘉宾"))
    for index in range(4):
        project.cues.append(StudioCue(
            f"c{index}", index * 1000, index * 1000 + 900, f"第{index}句",
            speaker_id="S01" if index < 3 else "S02",
        ))
    project.validate()
    page.project = project
    page.project_path = tmp_path / "round15.2byteproj"
    page._cue_lookup = {cue.id: cue for cue in project.cues}
    page._manual_text_baselines = {cue.id: cue.text for cue in project.cues}
    page.cue_model.set_project(project)
    page.timeline.set_project(project)
    page._populate_speakers()
    page.undo_stack.clear()
    page.undo_stack.setClean()
    return page


def _web_theme_cue_count(page) -> int:
    return sum(
        1 for cue in page.project.cues
        if isinstance(page.project.style_recipes.get(cue.style_id, {}).get("webTheme"), dict)
    )


def test_apply_scope_combo_exists_with_three_targets(tmp_path):
    _app()
    page = _page(tmp_path)
    combo = getattr(page, "ai_apply_scope", None)
    assert combo is not None
    assert [combo.itemData(i) for i in range(combo.count())] == ["current", "speaker", "all"]


def test_apply_scope_all_web_themes_every_cue(tmp_path):
    _app()
    page = _page(tmp_path)
    theme = builtin_web_themes()["clean-glass"].to_dict()
    page._pending_web_theme = SimpleNamespace(
        cue_id="c0", theme=dict(theme), name=theme["name"], recipe=None,
    )
    page.select_cue("c0")
    from tests.theme_fixture import bind_ready_draft
    bind_ready_draft(page,theme,'c0')
    page.ai_apply_scope.setCurrentIndex(page.ai_apply_scope.findData("all"))
    page._apply_ai_preview()
    assert _web_theme_cue_count(page) == 4, "scope=all must web-theme every cue"


def test_apply_scope_speaker_targets_same_speaker(tmp_path):
    _app()
    page = _page(tmp_path)
    theme = builtin_web_themes()["clean-glass"].to_dict()
    page._pending_web_theme = SimpleNamespace(
        cue_id="c0", theme=dict(theme), name=theme["name"], recipe=None,
    )
    # select the S02 cue: speaker scope must touch only that one cue
    page.select_cue("c3")
    from tests.theme_fixture import bind_ready_draft
    bind_ready_draft(page,theme,'c3')
    page.ai_apply_scope.setCurrentIndex(page.ai_apply_scope.findData("speaker"))
    page._apply_ai_preview()
    assert _web_theme_cue_count(page) == 1
    themed = [
        cue.id for cue in page.project.cues
        if isinstance(page.project.style_recipes.get(cue.style_id, {}).get("webTheme"), dict)
    ]
    assert themed == ["c3"]


# ---------------------------------------------------------------------------
# 7) storyboard animation structure
# ---------------------------------------------------------------------------

def test_storyboard_timeline_drives_continuous_animation(tmp_path):
    _app()
    page = _page(tmp_path)
    # 十七轮：30fps × 2.4s = 72 帧循环（0.1s 步长曾让演示一卡一卡）。
    assert page._STORYBOARD_LOOP_SECONDS == pytest.approx(3.0)
    assert page._STORYBOARD_BAND_KEEP == 1.0
    # Actual frames now arrive from a LIVE browser worker, not a still timer.
    assert not hasattr(page,'_STORYBOARD_DEMO_FPS')
    # widget contract (round 16): single demo band, hidden initially
    assert page.ai_web_theme_demo_label is not None
    assert len(page.ai_web_theme_storyboard_labels) == 1
    assert page.ai_web_theme_storyboard_wrap.isHidden()
    # archive/refine controls exist; refine input now lives in the style panel
    assert page.ai_refine_row.isHidden()
    assert page.ai_export_archive_button is not None
    assert page.ai_import_archive_button is not None
    assert getattr(page, "web_adjust_host", None) is not None
    # cycling with empty frame sets must be a safe no-op
    page._stop_storyboard_animation()
    assert getattr(page,"_storyboard_live_worker",None) is None
