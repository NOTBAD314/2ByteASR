"""联网更新失败场景（受控注入，不烧真实额度）。

真实遇到的失败（超时 300s、bailian 401、无密钥、120 条无来源）见
tmp/glossary-live-round/call-ledger.jsonl 与本轮报告；这里锁定程序行为。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr.providers import ai_providers as _ai_providers
from twobyteasr.glossary import glossary_skill as gs
from twobyteasr.providers.ai_providers import AIProviderError
from twobyteasr.glossary.glossary_skill import (
    GlossarySearchError,
    SearchedTerm,
    apply_term_updates,
    diff_term_updates,
    normalize_searched_terms,
    run_term_search,
)


@pytest.fixture(autouse=True)
def _stub_url_safety(monkeypatch, tmp_path):
    monkeypatch.setattr(
        gs, "is_safe_web_url", lambda url: (str(url).startswith("https://"), "stub")
    )
    # apply/批量路径会写更新会话历史——必须落在 tmp，绝不进真实用户目录。
    monkeypatch.setattr(
        gs, "update_history_path", lambda base=None: tmp_path / "history.json"
    )


class _FakeLegacy:
    RUNTIME_GAME_NAME = ""

    def __init__(self, fail_on=None):
        self.saved = {}
        self.fail_on = set(fail_on or ())

    def load_active_game_lexicon_names(self, include_hidden=False):
        return ["既有词"], []

    def builtin_reference_terms_for_game(self, game, include_hidden=False):
        return []

    def learned_canonical_terms(self, game=None):
        return list(self.saved.keys())

    def user_confirmed_mappings_for_game(self, game):
        return [{"from": k, "to": k} for k in self.saved]

    def hidden_reference_terms_for_game(self, game):
        return set()

    def learned_content_type(self, game=None):
        return "game"

    def add_learned_mapping(self, game, source, target, *, category="其他", origin="手动", evidence_metadata=None):
        if source in self.fail_on:
            raise OSError("disk locked (injected)")
        key = (game, source, target)
        if key in self.saved:
            return False
        self.saved[key] = True
        return True

    def delete_learned_mappings(self, game, keys):
        removed = 0
        for source, target in keys:
            if self.saved.pop((game, source, target), None) is not None:
                removed += 1
        return removed


class _FakeProvider:
    def __init__(self, *, payload=None, error=None, evidence=True):
        self.payload = payload
        self.error = error
        self.evidence = evidence

    def structured_complete(self, messages, schema, **kwargs):
        if self.error is not None:
            raise self.error
        if self.evidence:
            kwargs["request_diagnostics"]["search_evidence"] = [{"tool": "web_search", "urls": []}]
        return self.payload


def _grok_settings():
    return {
        "models": {"ai_service": "grok_account"},
        "switches": {},
        "provider_profiles": {"grok_account": {"model": "grok-4.6"}},
    }


def _diff(term, **kw):
    if kw.get('sources'):
        kw.setdefault('verification','page_verified')
        kw.setdefault('category_key','character' if kw.get('category')=='角色' else 'skill')
    return diff_term_updates(
        [SearchedTerm(term=term, **kw)],
        existing_terms=[], confirmed_pairs=[], excluded_terms=[],
    )[0]


def test_structured_output_garbage_maps_to_unavailable(monkeypatch):
    fake = _FakeProvider(payload={"terms": "不是数组"})
    monkeypatch.setattr(_ai_providers, "provider_for_stage", lambda *_a, **_k: fake)
    with pytest.raises(GlossarySearchError) as exc:
        run_term_search(_FakeLegacy(), "测试游戏", _grok_settings())
    assert exc.value.code in {"unavailable", "unexpected"}


def test_rate_limit_and_auth_categories_are_not_retried_blindly(monkeypatch):
    # run_term_search 单次尝试、无自动重试：分类透传给调用方。
    fake = _FakeProvider(error=AIProviderError("429 too many", category="rate_limited"))
    monkeypatch.setattr(_ai_providers, "provider_for_stage", lambda *_a, **_k: fake)
    with pytest.raises(GlossarySearchError) as exc:
        run_term_search(_FakeLegacy(), "测试游戏", _grok_settings())
    assert exc.value.code == "rate_limited"
    assert "429" in exc.value.detail


def test_apply_survives_mid_batch_disk_error_and_keeps_partial_results():
    legacy = _FakeLegacy(fail_on={"坏词"})
    diffs = [
        _diff("好词甲", category="角色", sources=[{"url": "https://a.example/x"}]),
        _diff("坏词", category="角色", sources=[{"url": "https://a.example/y"}]),
        _diff("好词乙", category="技能", sources=[{"url": "https://a.example/z"}]),
    ]
    session = apply_term_updates(legacy, "测试游戏", diffs)
    assert session["added"] == 2
    assert session["failed"] == 1
    assert ("测试游戏", "好词甲", "好词甲") in legacy.saved
    assert ("测试游戏", "好词乙", "好词乙") in legacy.saved
    # 会话只记录实际成功的键——撤销不会碰未写入的行
    assert session["applied_keys"] == [["好词甲", "好词甲"], ["好词乙", "好词乙"]]


def test_empty_increment_reports_no_new_terms_not_failure(monkeypatch):
    fake = _FakeProvider(payload={"terms": [{"term": "既有词", "category": "角色"}]})
    monkeypatch.setattr(_ai_providers, "provider_for_stage", lambda *_a, **_k: fake)
    result = run_term_search(_FakeLegacy(), "测试游戏", _grok_settings())
    assert result["diffs"] == []  # 唯一候选已存在 → 空增量（幂等），不是失败


def test_partial_sources_split_new_and_unverifiable():
    payload = {
        "terms": [
            {"term": "有据词", "category": "角色", "sources": ["https://a.example/x"]},
            {"term": "无据词", "category": "角色"},
        ]
    }
    terms = normalize_searched_terms(payload)
    diffs = diff_term_updates(terms, existing_terms=[], confirmed_pairs=[], excluded_terms=[])
    by_term = {d.term.term: d for d in diffs}
    assert by_term["有据词"].change_type == "new"
    assert by_term["无据词"].change_type == "unverifiable"
    assert by_term["无据词"].checked_by_default is False


def test_worker_cancel_stops_and_reports_cancelled(qtbot_none=None):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.glossary import glossary_skill_ui as gsui
    from twobyteasr.glossary.glossary_skill_ui import GlossaryUpdateWorker

    app = QApplication.instance() or QApplication([])
    legacy = _FakeLegacy()

    real_run = gsui.run_term_search

    def slow_run(*args, **kwargs):
        import time as _t

        # 模拟长检索：等取消标志
        end = _t.perf_counter() + 5
        while _t.perf_counter() < end:
            if kwargs.get("cancel_check") and kwargs["cancel_check"]():
                raise GlossarySearchError("cancelled", "已取消。")
            _t.sleep(0.02)
        return real_run(*args, **kwargs)

    gsui.run_term_search = slow_run
    try:
        worker = GlossaryUpdateWorker(legacy, "测试游戏", _grok_settings())
        outcomes = []
        worker.failed.connect(lambda g, code, msg: outcomes.append(code))
        worker.start()
        _t2_wait(app, 300)
        worker.cancel()
        _t2_wait(app, 1500)
        assert outcomes == ["cancelled"]
    finally:
        gsui.run_term_search = real_run


def _t2_wait(app, ms):
    import time as _t

    end = _t.perf_counter() + ms / 1000
    while _t.perf_counter() < end:
        app.processEvents()
        _t.sleep(0.01)


def test_batch_queue_isolates_failures_and_cancel_stops_scheduling():
    from PySide6.QtWidgets import QApplication
    from twobyteasr.glossary import glossary_skill_ui as gsui
    from twobyteasr.glossary.glossary_skill_ui import BatchGlossaryUpdateWorker

    app = QApplication.instance() or QApplication([])
    legacy = _FakeLegacy()
    real_run = gsui.run_term_search
    calls: list[str] = []

    def fake_run(legacy_arg, game, settings, *, progress=None, cancel_check=None, **kw):
        calls.append(game)
        import time as _t

        _end = _t.perf_counter() + 0.15
        while _t.perf_counter() < _end:
            if cancel_check and cancel_check():
                raise GlossarySearchError("cancelled", "已取消。")
            _t.sleep(0.01)
        if game == "失败游戏":
            raise GlossarySearchError("unauthorized", "认证失败（注入）")
        # 返回一个安全项让批量自动应用路径走通
        return {
            "diffs": [
                _diff(f"{game}新词", category="角色", sources=[{"url": "https://a.example/x"}])
            ],
            "candidate_count": 1, "elapsed_seconds": 0.2, "searched": True,
            "search_evidence": True, "model": "fake", "service": "fake",
            "notes": "",
        }

    gsui.run_term_search = fake_run
    try:
        worker = BatchGlossaryUpdateWorker(
            legacy, ["游戏甲", "失败游戏", "游戏乙", "游戏丙"], _grok_settings()
        )
        results: dict[str, str] = {}
        worker.game_diff.connect(lambda game, _r: results.__setitem__(game, "ok"))
        worker.game_failed.connect(lambda game, code, _m: results.__setitem__(game, code))
        summary: dict = {}
        worker.queue_finished.connect(summary.update)
        worker.start()
        _t2_wait(app, 2500)
        assert results["游戏甲"] == "ok"
        assert results["失败游戏"] == "unauthorized"  # 单游戏失败被如实分类
        assert results["游戏乙"] == "ok"  # 失败不影响后续
        assert summary.get("done") == 3 and summary.get("failed") == 1
        assert ("游戏甲", "游戏甲新词", "游戏甲新词") in legacy.saved  # 已完成结果保留
        # 取消：跑到第三个后取消 → 游戏丙不启动
        calls.clear()
        worker2 = BatchGlossaryUpdateWorker(
            legacy, ["游戏A", "游戏B", "游戏C"], _grok_settings()
        )
        started: list[str] = []
        worker2.game_started.connect(started.append)
        worker2.start()
        _t2_wait(app, 220)
        worker2.cancel()
        _t2_wait(app, 1500)
        assert "游戏C" not in started  # 取消后不再调度后续游戏
    finally:
        gsui.run_term_search = real_run
