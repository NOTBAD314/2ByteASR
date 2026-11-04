"""User-clicked AI actions without an API key explain instead of failing (2026-10-15).

Studio's AI 断句 menu and the AI 词库校对 page's 「AI 校对」 used to start and
then fail with a raw "缺少 API 密钥". With no key they now show a short note
(「API Key 是什么？」 / 「取消」) and send nothing; with a key nothing changes.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


def _settings(**models):
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["models"].update(models)
    return settings


def _keys(monkeypatch, stored=None, legacy=""):
    """Key lookups see only ``stored`` (provider → key) and ``legacy`` (Bailian env/legacy bucket)."""
    from twobyteasr.providers import llm_config
    stored = dict(stored or {})
    monkeypatch.setattr(llm_config, "read_scoped_api_key",
                        lambda provider, base_url="": (stored.get(provider, ""), "test" if provider in stored else ""))
    monkeypatch.setattr(llm_config, "resolve_api_key", lambda stage: (legacy, "env" if legacy else ""))


# ---------------------------------------------------------------- the rule

def test_default_settings_without_any_key_count_as_missing(monkeypatch):
    from twobyteasr.providers.llm_config import text_ai_key_missing
    _keys(monkeypatch)
    assert text_ai_key_missing(_settings(), "polish")
    assert text_ai_key_missing(_settings(), "group")


def test_a_saved_or_environment_key_is_not_missing(monkeypatch):
    from twobyteasr.providers.llm_config import text_ai_key_missing
    _keys(monkeypatch, {"bailian": "sk-test"})
    assert not text_ai_key_missing(_settings(), "polish")
    assert not text_ai_key_missing(_settings(), "group")
    _keys(monkeypatch, legacy="sk-from-environment")   # DASHSCOPE_API_KEY and the old Bailian bucket
    assert not text_ai_key_missing(_settings(), "group")


def test_only_the_step_without_a_key_is_missing(monkeypatch):
    from twobyteasr.providers.llm_config import text_ai_key_missing
    _keys(monkeypatch, {"deepseek": "sk-test"})
    settings = _settings(group_provider="deepseek", group_base_url="https://api.deepseek.com/v1",
                         group_model="deepseek-chat")
    settings["switches"]["unified_glm_processing"] = False
    assert not text_ai_key_missing(settings, "group")
    assert text_ai_key_missing(settings, "polish")   # still Bailian, no key


def test_a_local_loopback_service_and_cli_accounts_need_no_key(monkeypatch):
    from twobyteasr.providers.llm_config import activate_ai_service, text_ai_key_missing
    _keys(monkeypatch)
    local = dict(provider="custom", base_url="http://127.0.0.1:11434/v1", model="qwen3:8b")
    settings = _settings(**{f"{role}_{key}": value for role in ("polish", "group") for key, value in local.items()})
    assert not text_ai_key_missing(settings, "polish")
    assert not text_ai_key_missing(settings, "group")
    remote = _settings(**{f"{role}_{key}": value for role in ("polish", "group")
                          for key, value in dict(local, base_url="https://llm.example.com/v1").items()})
    assert text_ai_key_missing(remote, "group")      # a remote custom service does need one
    cli = _settings()
    activate_ai_service(cli, "grok_account", stage="polish", unified=True)
    assert not text_ai_key_missing(cli, "polish")
    assert not text_ai_key_missing(cli, "group")


def test_other_configuration_problems_are_left_to_the_request(monkeypatch):
    from twobyteasr.providers import llm_config
    _keys(monkeypatch)

    def broken(*_args, **_kwargs):
        raise ValueError("Unsupported explicitly configured ASR transport")

    monkeypatch.setattr(llm_config, "effective_ai_identity", broken)
    assert not llm_config.text_ai_key_missing(_settings(), "group")


# ---------------------------------------------------------------- the note

def _answer_note(button_name, seen):
    def answer():
        box = next((widget for widget in QApplication.topLevelWidgets()
                    if isinstance(widget, QMessageBox) and widget.objectName() == "apiKeyNeeded"
                    and widget.isVisible()), None)
        if box is None:
            QTimer.singleShot(20, answer)
            return
        seen.append((box.windowTitle(), box.text(), [button.text() for button in box.buttons()]))
        box.findChild(QWidget, button_name).click()
    QTimer.singleShot(0, answer)


def test_the_note_offers_the_explainer_or_cancel(monkeypatch):
    from twobyteasr.app import api_key_explainer
    opened = []
    monkeypatch.setattr(api_key_explainer, "open_api_key_explainer",
                        lambda window, **_kw: opened.append(window) or "setup")
    main = QWidget()
    main._open_api_setup_guide = lambda *_args: None   # what MainWindow provides
    child = QLabel(main)
    seen = []
    _answer_note("apiKeyNeededCancel", seen)
    assert api_key_explainer.offer_api_key_help(child) == "cancel"
    assert opened == []
    assert seen[0][0] == "需要 API Key" and seen[0][1] == "这个功能要用 AI，需要先填 API Key"
    assert sorted(seen[0][2]) == sorted(["API Key 是什么？", "取消"])
    _answer_note("apiKeyNeededExplain", seen)
    assert api_key_explainer.offer_api_key_help(child) == "setup"
    assert opened == [main]   # the explainer opens over the window that has 申请与设置 API
    main.deleteLater()


# ---------------------------------------------------------------- Studio AI 断句

from twobyteasr.studio.studio_sentence_refine_ui import StudioSentenceRefineMixin  # noqa: E402


class _Studio(StudioSentenceRefineMixin, QWidget):
    """The Studio page's AI 断句 part on a bare widget."""

    def __init__(self, project):
        super().__init__()
        self.project = project
        self.save_state = QLabel(self)
        self.timeline = SimpleNamespace(selected_segment_ids=())
        self.selected_cue_id = project.cues[0].id
        self.traces = []
        self.run = self.run_sentence_refine

    def _studio_trace(self, event, **fields):
        self.traces.append(event)


def _studio(monkeypatch, *, missing):
    from twobyteasr.app import api_key_explainer
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from twobyteasr.providers import llm_config
    from twobyteasr.storage import settings as settings_module
    from twobyteasr.studio import studio_sentence_refine_ui as refine_ui
    project = SubtitleProject(media=StudioMedia(path="", duration_ms=8000),
                              cues=[StudioCue("c1", 0, 2000, "第一句话很长"), StudioCue("c2", 2000, 4000, "第二句")])
    project.studio_state["ai_sentence_refine"] = {"failed_cue_ids": ["c2"]}
    asked, started, checked = [], [], []
    monkeypatch.setattr(settings_module, "load_runtime_settings", lambda: _settings())
    monkeypatch.setattr(llm_config, "text_ai_key_missing", lambda settings, stage: checked.append(stage) or missing)
    monkeypatch.setattr(api_key_explainer, "offer_api_key_help", lambda widget: asked.append(widget) or "cancel")

    class Worker:
        def __init__(self, cues, *_args):
            self.finished_ok = self.failed = SimpleNamespace(connect=lambda *_a: None)
            self.cues = cues

        def isRunning(self):
            return False

        def start(self):
            started.append([cue.id for cue in self.cues])

    monkeypatch.setattr(refine_ui, "SentenceRefineWorker", Worker)
    return _Studio(project), asked, started, checked


@pytest.mark.parametrize("scope", [dict(whole_project=False), dict(whole_project=True),
                                   dict(whole_project=False, retry_failed=True)])
def test_studio_ai_split_without_a_key_explains_and_sends_nothing(monkeypatch, scope):
    page, asked, started, checked = _studio(monkeypatch, missing=True)
    before = copy.deepcopy(page.project.studio_state)
    page.run(**scope)
    assert asked == [page] and started == [] and checked == ["group"]
    assert page.save_state.text() == "AI 断句没有运行：还没填 API Key"
    assert page.traces == ["SentenceRefineNeedsKey"]
    assert page.project.studio_state == before        # nothing recorded as a failed range
    assert getattr(page, "_refine_worker", None) is None
    page.deleteLater()


def test_studio_ai_split_with_a_key_runs_as_before(monkeypatch):
    page, asked, started, _checked = _studio(monkeypatch, missing=False)
    page.run(whole_project=True)
    assert asked == [] and started == [["c1", "c2"]]
    assert page.save_state.text().startswith("AI 断句中… 2 条")
    page.deleteLater()


def test_studio_ai_split_with_nothing_to_do_does_not_ask_for_a_key(monkeypatch):
    page, asked, _started, checked = _studio(monkeypatch, missing=True)
    page.project.studio_state["ai_sentence_refine"] = {"processed_cue_ids": ["c1", "c2"]}
    page.run(whole_project=True)
    assert asked == [] and checked == []
    assert page.save_state.text() == "AI 断句：没有可处理的新字幕"
    page.deleteLater()


# ---------------------------------------------------------------- AI 词库校对 「AI 校对」

def _proofread(monkeypatch, *, missing):
    from twobyteasr.app import api_key_explainer
    from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage
    from twobyteasr.providers import llm_config
    page = GlossaryProofreadPage(SimpleNamespace(studio_page=None, _prepare_glossary_for_task=lambda: True))
    asked, runs, checked = [], [], []
    monkeypatch.setattr(llm_config, "text_ai_key_missing", lambda settings, stage: checked.append(stage) or missing)
    monkeypatch.setattr(api_key_explainer, "offer_api_key_help", lambda widget: asked.append(widget) or "cancel")
    page._run = lambda use_ai, cue_ids=None: runs.append((use_ai, cue_ids))
    return page, asked, runs, checked


def _close(page):
    page.shutdown()
    page.deleteLater()
    APP.processEvents()


def test_ai_proofread_without_a_key_explains_and_sends_nothing(monkeypatch):
    page, asked, runs, checked = _proofread(monkeypatch, missing=True)
    try:
        page.ai_button.click()
        assert asked == [page] and runs == [] and checked == ["polish"]
        assert page.status_label.text() == "AI 校对没有运行：还没填 API Key"
        page.local_button.click()                     # 按词库匹配 stays local and never asks
        assert runs == [(False, None)] and asked == [page]
    finally:
        _close(page)


def test_ai_proofread_with_a_key_or_the_tutorial_stand_in_runs_as_before(monkeypatch):
    page, asked, runs, _checked = _proofread(monkeypatch, missing=False)
    try:
        page.ai_button.click()
        assert asked == [] and runs == [(True, None)]
    finally:
        _close(page)
    page, asked, runs, checked = _proofread(monkeypatch, missing=True)
    try:
        page.ai_stand_in = lambda *args, **kwargs: None    # the tutorial: offline, free, no key
        page.ai_button.click()
        assert asked == [] and checked == [] and runs == [(True, None)]
    finally:
        _close(page)


# ---------------------------------------------------------------- translations

def test_new_strings_have_english_japanese_korean_and_traditional_chinese():
    texts = ["需要 API Key", "这个功能要用 AI，需要先填 API Key", "AI 断句没有运行：还没填 API Key",
             "AI 校对没有运行：还没填 API Key", "API Key 是什么？", "取消"]
    for language in ("en", "ja", "ko", "zh-Hant"):
        catalog = json.loads((ROOT / "twobyteasr" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        assert [text for text in texts if not catalog.get(text)] == [], language


# ================================================================ the other AI actions (same evening)

def _guard(monkeypatch, *, missing):
    """``text_ai_key_missing`` answers ``missing``; the note is recorded instead of shown."""
    from twobyteasr.app import api_key_explainer
    from twobyteasr.providers import llm_config
    asked, checked = [], []
    monkeypatch.setattr(llm_config, "text_ai_key_missing", lambda settings, stage: checked.append(stage) or missing)
    monkeypatch.setattr(api_key_explainer, "offer_api_key_help", lambda widget: asked.append(widget) or "cancel")
    return asked, checked


def _project():
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    return SubtitleProject(media=StudioMedia(path="", duration_ms=8000),
                           cues=[StudioCue("c1", 0, 2000, "第一句话"), StudioCue("c2", 2000, 4000, "第二句")])


def test_ask_for_key_if_missing_checks_once_leaves_a_status_and_asks(monkeypatch):
    from twobyteasr.app.api_key_explainer import ask_for_key_if_missing
    asked, checked = _guard(monkeypatch, missing=True)
    lines = []
    assert ask_for_key_if_missing("w", {}, "polish", status=lambda: lines.append("status"))
    assert asked == ["w"] and checked == ["polish"] and lines == ["status"]
    asked, checked = _guard(monkeypatch, missing=False)
    assert not ask_for_key_if_missing("w", {}, "group", status=lambda: lines.append("again"))
    assert asked == [] and checked == ["group"] and lines == ["status"]


from twobyteasr.studio.studio_ai_flow import StudioAIFlowMixin  # noqa: E402


class _Design(StudioAIFlowMixin):
    """The AI 设计 drawer's request methods on a bare object."""

    def __init__(self):
        self.project = _project()
        self.selected_cue_id = "c1"
        self._ai_request_active = False
        self._ai_preparing_request = None
        self._ai_revision_active = False
        self.hints, self.traces, self.started, self.repairs = [], [], [], []

    def _refresh_ai_design_target(self):
        pass

    def _show_studio_hint(self, text):
        self.hints.append(str(text))

    def _studio_trace(self, event, **fields):
        self.traces.append(event)

    def _ai_start_feedback(self, context, status, message):
        self.started.append(status)

    def _current_web_theme_recipe(self):
        return {"id": "theme"}

    def _assemble_web_adjust_opinion(self):
        return "字号大一点"

    def _web_adjust_target_cue_ids(self):
        return ["c1"]

    def _theme_drafts(self):
        return SimpleNamespace(repair=lambda request, **kw: self.repairs.append(request))


@pytest.mark.parametrize("missing", [True, False])
def test_ai_design_generate_revise_and_adjust(monkeypatch, missing):
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.studio import studio_ai_flow
    asked, checked = _guard(monkeypatch, missing=missing)
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY, "settings", lambda: _settings())
    dialogs = []
    monkeypatch.setattr(studio_ai_flow, "_revision_feedback_dialog",
                        lambda parent, index: dialogs.append(index) or ("", False))
    page = _Design()
    page._request_ai_suggestion()             # 生成字幕设计
    page._request_ai_revision(0, None, None)  # 微调设计
    page._send_web_adjust_request()           # 特效字幕调整：发送修改意见
    assert checked == ["polish"] * 3
    if missing:
        assert len(asked) == 3 and page.started == [] and dialogs == [] and page.repairs == []
        assert page._ai_preparing_request is None
        assert page.hints == ["AI 设计没有运行：还没填 API Key"] * 3
    else:
        assert asked == [] and page.started == ["preparing"] and dialogs == [0] and page.repairs
        page._ai_preparing_request = None    # the queued preparation is not run here


def _find_replace(project, **extra):
    page = SimpleNamespace(session=SimpleNamespace(project=project),
                           window=lambda: SimpleNamespace(_prepare_glossary_for_task=lambda: True))
    return SimpleNamespace(_page=page, ai_option_boxes={}, status_label=QLabel(), _current_scope=lambda: "all",
                           _glossary_review_worker=None, **extra)


@pytest.mark.parametrize("missing", [True, False])
def test_find_replace_ai_cleanup(monkeypatch, missing):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    from twobyteasr.studio import link_caption_cleanup
    from twobyteasr.studio.ai_cleanup_dialog import AiCleanupDialog
    app = QApplication.instance() or QApplication([])
    asked, checked = _guard(monkeypatch, missing=missing)
    calls = []
    monkeypatch.setattr(link_caption_cleanup, "request_text_cleanup", lambda *a, **kw: calls.append(a) or [])
    page = QWidget()
    page.session = SimpleNamespace(project=_project(), selected_cue_id="c1")
    page.selected_cue_ids = lambda: ["c1"]
    dialog = AiCleanupDialog(page, page)
    try:
        dialog._do_ai_preview()
        for _ in range(500):
            if not dialog._cleanup_running:
                break
            QTest.qWait(20)
        assert checked == ["polish"]
        if missing:
            assert len(asked) == 1 and calls == [] and not dialog._cleanup_running
            assert dialog.status_label.text() == "AI 清理没有运行：还没填 API Key"
        else:
            assert asked == [] and len(calls) == 1 and dialog.status_label.text() == "没有需要整理的地方。"
    finally:
        dialog.reject()
        page.deleteLater()
        app.processEvents()


def test_find_replace_glossary_ai_preview_without_a_key(monkeypatch):
    from twobyteasr.studio import studio_find_replace
    asked, checked = _guard(monkeypatch, missing=True)
    started = []
    monkeypatch.setattr(studio_find_replace, "_GlossaryReviewThread", lambda *a, **kw: started.append(a))
    dialog = _find_replace(_project(), _fill_preview=lambda *a: None,
                           _read_selected_snapshot=lambda: ((), SimpleNamespace(canonical_terms=("芙宁娜",))))
    studio_find_replace.GlossaryReviewDialog._do_terms_ai_preview(dialog)
    assert len(asked) == 1 and checked == ["polish"] and started == []
    assert dialog.status_label.text() == "AI 校对没有运行：还没填 API Key"


def test_translation_without_a_key_explains_instead_of_a_grey_button(monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.app import api_key_explainer
    from twobyteasr.caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.studio.studio_translation_dialog import SubtitleTranslationDialog
    asked = []
    monkeypatch.setattr(api_key_explainer, "offer_api_key_help", lambda widget: asked.append(widget) or "cancel")
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY, "settings", lambda: _settings())
    dialog = SimpleNamespace(service=QLabel(), start_button=QPushButton(), status=QLabel(), _scope_ids=lambda: None)
    _keys(monkeypatch)
    assert SubtitleTranslationDialog._describe_service(dialog)
    assert dialog.service.text() == "这个功能要用 AI，需要先填 API Key" and dialog.start_button.isEnabled()
    SubtitleTranslationDialog._start(dialog)           # stops before touching the project
    assert len(asked) == 1 and dialog.status.text() == "翻译没有运行：还没填 API Key"
    _keys(monkeypatch, {"bailian": "sk-test"})
    assert SubtitleTranslationDialog._describe_service(dialog)
    assert dialog.service.text().startswith("使用已配置的 AI 文字服务") and dialog.start_button.isEnabled()


def test_translation_other_configuration_problems_keep_the_grey_button(monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.studio.studio_translation_dialog import SubtitleTranslationDialog

    def broken():
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY, "settings", broken)
    dialog = SimpleNamespace(service=QLabel(), start_button=QPushButton())
    assert not SubtitleTranslationDialog._describe_service(dialog)
    assert dialog.service.text().startswith("还没有配置 AI 文字服务") and not dialog.start_button.isEnabled()


def _term_page(settings):
    from twobyteasr.glossary.main_ui_glossary import TermLibraryDialog
    page = SimpleNamespace(state={"game": "原神"}, ai_update_status=QLabel(), toasts=[], managers=[],
                           _ai_update_settings=lambda: settings)
    page._show_toast = page.toasts.append

    def manager():
        page.managers.append(1)
        raise LookupError("queued")    # the run would continue here

    page._ensure_task_manager = manager
    page._ai_update_needs_key = TermLibraryDialog._ai_update_needs_key.__get__(page)
    return page


@pytest.mark.parametrize("missing", [True, False])
def test_term_library_ai_build_and_resume(monkeypatch, missing):
    from twobyteasr.glossary.main_ui_glossary import TermLibraryDialog
    asked, checked = _guard(monkeypatch, missing=missing)
    page = _term_page(_settings())
    for mode in ("full", "incremental"):
        if missing:
            TermLibraryDialog._start_ai_update(page, mode)
        else:
            with pytest.raises(LookupError):
                TermLibraryDialog._start_ai_update(page, mode)
    if missing:
        assert len(asked) == 2 and page.managers == [] and not page.ai_update_status.isHidden()
        assert page.ai_update_status.text() == "AI 建库没有运行：还没填 API Key"
        # 「继续」 on a stopped task asks the same before queueing again.
        manager = SimpleNamespace(get=lambda task_id: SimpleNamespace(game="原神", library_id="lib"),
                                  submit=lambda *a, **kw: page.managers.append("submit") or ("t2", True))
        page._ensure_task_manager = lambda: manager
        TermLibraryDialog._on_task_resume(page, "t1")
        assert page.managers == [] and len(asked) == 3
    else:
        assert asked == [] and page.managers == [1, 1]
    assert set(checked) == {"polish"}


def test_batch_glossary_update_without_a_key(monkeypatch):
    from twobyteasr.glossary import glossary_skill_ui
    asked, checked = _guard(monkeypatch, missing=True)
    workers = []
    monkeypatch.setattr(glossary_skill_ui, "BatchGlossaryUpdateWorker", lambda *a, **kw: workers.append(a))
    dialog = SimpleNamespace(_selected_games=lambda: ["原神"], settings_factory=lambda: _settings(), status=QLabel())
    glossary_skill_ui.BatchUpdateDialog._start(dialog)
    assert len(asked) == 1 and workers == [] and checked == ["polish"]
    assert dialog.status.text() == "AI 建库没有运行：还没填 API Key"


def test_highlights_without_a_key_keep_the_local_result_and_send_nothing(monkeypatch):
    from twobyteasr.studio import studio_highlight_analyzer as analyzer
    _guard(monkeypatch, missing=True)
    calls = []

    def provider(*args, **kwargs):
        calls.append(kwargs.get("sender"))
        raise LookupError("the request would be sent here")

    monkeypatch.setattr(analyzer, "provider_for_stage", provider)
    # 2026-10-24 (Codex clip suggestions): no local candidate means nothing to rank or send.
    assert analyzer.rank_candidates_with_llm(_project(), [], runtime_settings=_settings()) == [] and calls == []
    local = lambda: [analyzer.LocalCandidate(0, 4000, 0.9, ["字幕"], quotes=["第一句话"])]
    with pytest.raises(RuntimeError, match="没填 API Key"):
        analyzer.rank_candidates_with_llm(_project(), local(), runtime_settings=_settings())
    assert calls == []
    # Only found moments go to the AI; give the two-line project one.
    monkeypatch.setattr(analyzer, "discover_local_candidates", lambda project, danmaku: local())
    result = analyzer.analyze_highlights(_project(), mode="subtitles", runtime_settings=_settings())
    assert result["llm_status"] == "local_fallback" and result["llm_error"] == "没填 API Key" and calls == []
    # An injected sender (tests, fixtures) and a configured key still reach the provider.
    with pytest.raises(LookupError):
        analyzer.rank_candidates_with_llm(_project(), local(), runtime_settings=_settings(), post=lambda *a, **k: "{}")
    _guard(monkeypatch, missing=False)
    with pytest.raises(LookupError):
        analyzer.rank_candidates_with_llm(_project(), local(), runtime_settings=_settings())
    assert len(calls) == 2


def test_new_status_lines_have_every_translation():
    texts = ["AI 设计没有运行：还没填 API Key", "AI 清理没有运行：还没填 API Key", "翻译没有运行：还没填 API Key",
             "AI 建库没有运行：还没填 API Key"]
    for language in ("en", "ja", "ko", "zh-Hant"):
        catalog = json.loads((ROOT / "twobyteasr" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        assert [text for text in texts if not catalog.get(text)] == [], language
