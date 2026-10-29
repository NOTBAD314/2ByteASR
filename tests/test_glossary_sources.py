"""v3 来源层：健康状态机/响应分类/分类枚举分页/词表解析/可取消等待。"""

from __future__ import annotations

import pytest

from twobyteasr.glossary import glossary_sources as gs


# ---------------------------------------------------------------- 状态机

def test_health_board_cooldown_and_recovery():
    board = gs.HealthBoard()
    health = board.for_host("wiki.example.com")
    assert board.for_host("WIKI.EXAMPLE.COM") is health  # host 归一
    first = health.record_failure("throttled")
    assert first > 0 and health.in_cooldown()
    assert board.snapshot()[0]["state"] in {"cooldown", "blocked"}
    # 冷却期内直接判不可用
    assert not board.any_available(["wiki.example.com"])
    assert board.any_available(["wiki.example.com", "other.example.com"])
    # 成功恢复
    health.cooldown_until = 0.0
    health.record_success()
    assert health.state == "ok" and not health.in_cooldown()


def test_health_failure_escalation_and_retry_after():
    board = gs.HealthBoard()
    health = board.for_host("a.com")
    d1 = health.record_failure("throttled")
    d2 = health.record_failure("throttled")
    d3 = health.record_failure("throttled")
    assert d3 >= d2 >= d1 > 0
    # Retry-After 优先且封顶；连续第 4 次失败升级 blocked
    assert health.record_failure("throttled", retry_after=9999) == gs._COOLDOWN_MAX
    assert health.consecutive_failures >= 4 and health.state == "blocked"


# ---------------------------------------------------------------- 响应分类

def test_classify_response_variants():
    assert gs.classify_response(200, "application/json", '{"query":1}') == "ok"
    assert gs.classify_response(403, "text/html", "<html>") == "blocked"
    assert gs.classify_response(429, "text/html", "") == "throttled"
    assert gs.classify_response(567, "text/html", "") == "throttled"
    # api.php 期待 JSON 却给 HTML 限流页
    assert gs.classify_response(200, "text/html", "<!doctype html>captcha verify") == "blocked"
    assert gs.classify_response(200, "text/html; charset=utf-8", "<!doctype html>" + "x" * 200) == "ok_html"
    assert gs.classify_response(200, "text/plain", "") == "bad_format"


# ---------------------------------------------------------------- 可取消等待

def test_cancellable_sleep_cancel_and_full():
    assert gs.cancellable_sleep(0.05, lambda: False) is False       # 正常睡完
    assert gs.cancellable_sleep(5.0, lambda: True) is True          # 立即取消


# ---------------------------------------------------------------- 分类枚举（伪网络）

class _FakeResponse:
    def __init__(self, status=200, content_type="application/json", text="", headers=None):
        self.status_code = status
        self.headers = {"content-type": content_type, **(headers or {})}
        self.text = text

    def iter_content(self, chunk_size=None):
        yield self.text.encode("utf-8")

    def json(self):
        import json
        return json.loads(self.text)


def test_category_members_pagination(monkeypatch):
    pages = [
        '{"query":{"categorymembers":[{"title":"安比"},{"title":"分类:导航"}]},"continue":{"cmcontinue":"NEXT"}}',
        '{"query":{"categorymembers":[{"title":"妮可"},{"title":"模板:盒子"}]},"continue":{"cmcontinue":"NEXT2"}}',
        '{"query":{"categorymembers":[{"title":"比利"}]}}',
    ]
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None, allow_redirects=False, verify=None):
        calls["n"] += 1
        assert params["action"] == "list" or params["list"] == "categorymembers"
        if calls["n"] == 2:
            assert params.get("cmcontinue") == "NEXT"
        return _FakeResponse(text=pages[min(calls["n"], 3) - 1])

    monkeypatch.setattr(gs.requests, "get", fake_get)
    site = gs.WikiSite(api_url="https://wiki.example.com/api.php", site_label="ex")
    board = gs.HealthBoard()
    names = gs.category_members(site, "Category:代理人", board=board, max_pages=5)
    # 命名空间前缀（分类/模板）被排除；三页全部走完
    assert names == ["安比", "妮可", "比利"]
    assert calls["n"] == 3


def test_category_members_blocked_returns_partial(monkeypatch):
    responses = [
        _FakeResponse(text='{"query":{"categorymembers":[{"title":"安比"}]},"continue":{"cmcontinue":"N"}}'),
        _FakeResponse(status=429, content_type="text/html", text=""),
    ]
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None, allow_redirects=False, verify=None):
        calls["n"] += 1
        return responses[min(calls["n"], 2) - 1]

    monkeypatch.setattr(gs.requests, "get", fake_get)
    site = gs.WikiSite(api_url="https://w.example/api.php")
    board = gs.HealthBoard()
    names = gs.category_members(site, "Category:角色", board=board, max_pages=3)
    # 第二次被拦：返回已拿到的部分，host 进入冷却
    assert names == ["安比"]
    assert board.for_host("w.example").in_cooldown()
    # 冷却期内再次调用：直接返回空，不再发请求
    before = calls["n"]
    assert gs.category_members(site, "Category:角色", board=board) == []
    assert calls["n"] == before


# ---------------------------------------------------------------- 词表解析

def test_parse_wordlist_text_formats():
    text_lines = "安比\n妮可,备注\t说明\n# 注释\n比利"
    assert gs.parse_wordlist_text(text_lines) == ["安比", "妮可", "比利"]
    json_list = '["艾莲", {"term": "青衣"}, {"word": "朱鸢"}]'
    assert gs.parse_wordlist_text(json_list) == ["艾莲", "青衣", "朱鸢"]


def test_fetch_text_wordlist_blocked(monkeypatch):
    board = gs.HealthBoard()
    monkeypatch.setattr(
        gs.requests, "get",
        lambda url, **kw: _FakeResponse(status=403, content_type="text/html", text=""),
    )
    assert gs.fetch_text_wordlist("https://raw.example.com/x.txt", board=board) is None
    assert board.for_host("raw.example.com").in_cooldown()


# ---------------------------------------------------------------- 站点推导

def test_guess_site_from_catalog():
    site = gs.guess_site_from_catalog("https://wiki.biligame.com/zzz/角色筛选", covers="代理人")
    assert site.api_url == "https://wiki.biligame.com/zzz/api.php"
    assert site.site_label == "wiki.biligame.com"


def test_discover_category_names_finds_native(monkeypatch):
    """站内分类发现：covers=角色 但站内叫 干员 → allcategories 找到。"""
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None, allow_redirects=False, verify=None):
        calls["n"] += 1
        assert params["list"] == "allcategories"
        if params["acprefix"] == "角色":
            return _FakeResponse(text='{"query":{"allcategories":[]}}')  # 站内没有"角色"分类
        return _FakeResponse(text='{"query":{"allcategories":[{"*":"干员"},{"*":"干员培养素材"}]}}')

    monkeypatch.setattr(gs.requests, "get", fake_get)
    site = gs.WikiSite(api_url="https://w.example/api.php")
    found = gs.discover_category_names(site, "character", board=gs.HealthBoard(), extra_hints=["角色"])
    assert found and found[0] == "干员"
    assert all("培养" not in name for name in found)  # 运营词排除
