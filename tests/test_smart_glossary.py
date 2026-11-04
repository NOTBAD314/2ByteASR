"""智能建词 MVP 行为测试：Retrieval first, AI optional。

覆盖 DoD：
- 无 API key → builtin / 粘贴文本建词可用
- 401 → AI 增强失败但基础流程继续
- 每个检索候选保留 source
- AI-only 建议不能自动 verified；用户确认才提升
- 去重归一化、类别推断/导入、别名/纠错确认
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twobyteasr.glossary.smart_glossary import (  # noqa: E402
    STATUS_AI_SUGGESTED,
    STATUS_BUILTIN,
    STATUS_CANDIDATE,
    STATUS_USER_CONFIRMED,
    AiEnhancementError,
    BuiltinGlossarySource,
    GlossaryCandidate,
    PastedTextSource,
    StructuredWikiSource,
    ai_enhance,
    build_ai_glossary_prompt,
    build_candidates,
    classify_ai_error,
    dedupe_candidates,
    infer_category,
    normalize_term,
    parse_ai_glossary_tsv,
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 归一化与类别

def test_normalize_term_handles_whitespace_and_punctuation():
    assert normalize_term(" 芙宁娜 ") == "芙宁娜"
    assert normalize_term(" 静水流涌之辉（武器）") == "静水流涌之辉(武器)"
    assert normalize_term("A·B") == "AB"


def test_infer_category_uses_section_and_term_hints():
    assert infer_category("三月七", "角色") == "character"
    assert infer_category("抓挠", "技能图鉴") == "skill"
    assert infer_category("海渊终曲") == "other"


def test_dedupe_merges_aliases_sources_and_keeps_highest_status():
    merged = dedupe_candidates(
        [
            GlossaryCandidate("芙宁娜", "character", source="pasted", confidence=0.7),
            GlossaryCandidate(
                "芙宁娜", "character", aliases=("福宁娜",), source="ai",
                status=STATUS_AI_SUGGESTED, confidence=0.5,
            ),
        ]
    )
    assert len(merged) == 1
    assert merged[0].aliases == ("福宁娜",)
    assert merged[0].source == "ai/pasted"
    assert merged[0].status == STATUS_AI_SUGGESTED
    assert merged[0].confidence == 0.7


def test_dedupe_user_confirmed_beats_builtin():
    merged = dedupe_candidates(
        [
            GlossaryCandidate("炮米花", status=STATUS_BUILTIN),
            GlossaryCandidate("炮米花", status=STATUS_USER_CONFIRMED),
        ]
    )
    assert merged[0].status == STATUS_USER_CONFIRMED


# ---------------------------------------------------------------- Builtin 词库包

def test_builtin_source_excludes_user_profile_terms_and_extracts_lexicons():
    payload = json.loads((ROOT / "game_profiles.json").read_text(encoding="utf-8-sig"))
    source = BuiltinGlossarySource(payload, ROOT)
    candidates = source.collect("洛克王国：世界")
    assert len(candidates) > 500, "应包含只读 profile references + lexicon 文件"
    assert all(c.status == STATUS_BUILTIN for c in candidates)
    assert all(c.source == "builtin" for c in candidates)
    categories = {c.category for c in candidates}
    assert "skill" in categories


def test_builtin_source_does_not_relabel_user_owned_profile_rows(tmp_path):
    source = BuiltinGlossarySource(
        {
            "profiles": {
                "测试游戏": {
                    "terms": [
                        {"canonical": "用户整理词", "source": "user_verified"},
                        {"canonical": "只读参考词", "source": "official_wiki"},
                    ],
                    "lexicons": [],
                }
            }
        },
        tmp_path,
    )
    assert [candidate.term for candidate in source.collect("测试游戏")] == ["只读参考词"]


def test_builtin_source_returns_empty_for_unknown_game():
    payload = json.loads((ROOT / "game_profiles.json").read_text(encoding="utf-8-sig"))
    source = BuiltinGlossarySource(payload, ROOT)
    assert source.collect("不存在的游戏") == []


# ---------------------------------------------------------------- 粘贴文本

def test_pasted_text_parses_sections_brackets_and_plain_lines():
    source = PastedTextSource()
    candidates = source.collect(
        "X", "角色：芙宁娜、那维莱特\n星见雅\n技能：审判（机制）"
    )
    by_term = {c.term: c for c in candidates}
    assert by_term["芙宁娜"].category == "character"
    assert by_term["那维莱特"].category == "character"
    assert by_term["星见雅"].category == "character", "section 延续到后续行"
    assert by_term["审判"].category == "mechanic"
    assert all(c.source == "pasted" for c in candidates)
    assert all(c.status == STATUS_CANDIDATE for c in candidates)


# ---------------------------------------------------------------- Wiki / HTML

def test_wiki_source_extracts_headers_lists_and_table_first_column():
    source = StructuredWikiSource()
    html = (
        "<h2>角色</h2><ul><li>三月七</li><li>丹恒</li></ul>"
        "<table><tr><td>静水流涌之辉</td><td>武器</td></tr></table>"
    )
    candidates = source.collect("", html)
    terms = {c.term: c.category for c in candidates}
    assert terms["三月七"] == "character"
    assert terms["丹恒"] == "character"
    assert "静水流涌之辉" in terms
    assert all(c.source == "wiki" for c in candidates)


def test_wiki_source_survives_malformed_html():
    source = StructuredWikiSource()
    assert source.collect("", "<div>unclosed <table> <<<") == []


# ---------------------------------------------------------------- AI 增强

class _FakeResponse:
    def __init__(self, status=200, content="", raise_error=None):
        self.status_code = status
        self._content = content
        self._raise_error = raise_error

    def raise_for_status(self):
        if self._raise_error is not None:
            raise self._raise_error

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _sender(content="", error=None, calls=None):
    """post_chat_completion 替身：记录参数，返回正文或抛出与真实通道相同的错误。"""

    def send(messages, **kwargs):
        if calls is not None:
            calls.append(dict(kwargs, messages=messages))
        if error is not None:
            raise error
        return content

    return send


def _http_error(status, category):
    from twobyteasr.providers.llm_adapter import LLMRequestError

    return LLMRequestError(f"HTTP {status}：{{}}", category=category, diagnostics={"http_status": status})


def test_ai_enhance_401_degrades_without_losing_candidates():
    endpoint = {"url": "https://x/v1", "model": "m", "api_key": "k"}
    candidates = [GlossaryCandidate("芙宁娜", "character", source="pasted")]
    result, error = ai_enhance(endpoint, candidates, sender=_sender(error=_http_error(401, "auth_error")))
    assert error is not None
    assert error.code == "unauthorized" and error.needs_settings
    assert "基础建词仍可继续使用" in error.user_message
    assert result == candidates, "401 时候选必须原样返回"


@pytest.mark.parametrize(
    ("status", "category", "code", "needs_settings"),
    [
        (402, "transport_error", "no_balance", True),
        (429, "rate_limited", "rate_limited", False),
        (503, "server_error", "unavailable", False),
    ],
)
def test_ai_enhance_http_failures_name_their_cause(status, category, code, needs_settings):
    endpoint = {"url": "https://x/v1", "model": "m", "api_key": "k"}
    candidates = [GlossaryCandidate("芙宁娜", source="pasted")]
    result, error = ai_enhance(endpoint, candidates, sender=_sender(error=_http_error(status, category)))
    assert error.code == code
    assert error.needs_settings is needs_settings
    assert error.model == "m" and error.endpoint == "https://x/v1"
    assert result == candidates


def test_ai_enhance_without_key_returns_missing_key_error():
    endpoint = {"url": "https://x/v1", "model": "m", "api_key": ""}
    candidates = [GlossaryCandidate("三月七", source="wiki")]
    result, error = ai_enhance(endpoint, candidates)
    assert error is not None and error.code == "missing_key"
    assert result == candidates


def test_classify_ai_error_detects_401_by_status_code():
    error = classify_ai_error(
        requests.HTTPError("401 Client Error: Unauthorized", response=_FakeResponse(status=401)),
        {"url": "https://x/v1"},
    )
    assert error.code == "unauthorized"
    assert error.endpoint == "https://x/v1"


def test_ai_enhance_applies_classification_noise_and_alias_as_suggested_only():
    endpoint = {"url": "https://x/v1", "model": "m", "api_key": "k"}
    content = (
        '{"classify":[{"term":"三月七","category":"角色"}],'
        '"aliases":[{"term":"三月七","alias":"三月妻"}],'
        '"noise":["第五章"]}'
    )
    candidates = [
        GlossaryCandidate("三月七", "other", source="wiki"),
        GlossaryCandidate("第五章", source="wiki"),
    ]

    result, error = ai_enhance(endpoint, candidates, sender=_sender(content))
    assert error is None
    by_term = {c.term: c for c in result}
    assert "第五章" not in by_term, "噪音词必须被移除"
    assert by_term["三月七"].category == "character", "AI 分类可补全类别"
    assert "福宁娜" not in by_term
    # AI 别名只作为候选携带，status 仍由调用方确认流程决定；候选本身不被标记 verified
    assert by_term["三月七"].aliases == ("三月妻",)
    assert by_term["三月七"].source == "wiki/ai"
    assert by_term["三月七"].status != STATUS_USER_CONFIRMED, "AI 建议不得自动 verified"


def test_ai_enhance_garbage_response_degrades_gracefully():
    endpoint = {"url": "https://x/v1", "model": "m", "api_key": "k"}
    candidates = [GlossaryCandidate("三月七", source="wiki")]
    result, error = ai_enhance(endpoint, candidates, sender=_sender("not json at all"))
    assert error is not None
    assert error.code == "bad_response" and not error.needs_settings
    assert "密钥" not in error.user_message
    assert result == candidates


class _ChatResponse:
    """network_policy.post 的返回替身（OpenAI 兼容 chat.completions 应答）。"""

    def __init__(self, content, *, reasoning="", finish_reason="stop"):
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}
        message = {"role": "assistant", "content": content}
        if reasoning:
            message["reasoning_content"] = reasoning
        self._payload = {
            "id": "chatcmpl-test",
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 480, "completion_tokens": 4096},
        }
        self.text = json.dumps(self._payload, ensure_ascii=False)

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _capture_chat_posts(monkeypatch, responses):
    """Route both the shared network layer and plain requests.post to fakes (never the network)."""
    from twobyteasr.providers import network_policy

    bodies = []

    def post(url, **kwargs):
        bodies.append(dict(kwargs.get("json") or {}, _url=url))
        return responses[min(len(bodies), len(responses)) - 1]

    monkeypatch.setattr(network_policy, "post", post)
    monkeypatch.setattr(requests, "post", post)
    return bodies


DEEPSEEK = {
    "provider": "deepseek",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com/v1",
    "protocol": "openai_compatible_chat",
    "url": "https://api.deepseek.com/v1/chat/completions",
    "api_key": "sk-test",
    "key_source": "test",
}


def test_ai_enhance_turns_deepseek_thinking_off_and_asks_for_json(monkeypatch):
    """10-25 用户回报：DeepSeek 默认先思考，4096 额度被思考用光，正文为空。"""
    content = '{"classify":[{"term":"今汐","category":"角色"}],"aliases":[],"noise":[]}'
    bodies = _capture_chat_posts(monkeypatch, [_ChatResponse(content)])
    candidates = [GlossaryCandidate("今汐", source="pasted")]
    result, error = ai_enhance(dict(DEEPSEEK), candidates)
    assert error is None
    assert result[0].category == "character"
    assert len(bodies) == 1
    body = bodies[0]
    assert body["_url"] == DEEPSEEK["url"]
    assert body["model"] == "deepseek-flash"
    assert body.get("thinking") == {"type": "disabled"}
    assert body.get("response_format") == {"type": "json_object"}
    assert body["max_tokens"] >= 8192


def test_ai_enhance_when_thinking_used_the_whole_budget_is_not_a_key_error(monkeypatch):
    """思考用光额度、正文为空：重试加大额度一次，仍失败时说没返回完整结果，不提密钥。"""
    empty = _ChatResponse("", reasoning="思考" * 2000, finish_reason="length")
    bodies = _capture_chat_posts(monkeypatch, [empty, empty])
    candidates = [GlossaryCandidate("今汐", source="pasted")]
    result, error = ai_enhance(dict(DEEPSEEK), candidates)
    assert result == candidates
    assert error is not None and error.code == "bad_response"
    assert not error.needs_settings
    assert "密钥" not in error.user_message
    assert [body["max_tokens"] for body in bodies] == [8192, 16384]


def test_classify_ai_error_answer_without_json_is_bad_response_not_unavailable():
    from twobyteasr.providers.llm_adapter import LLMRequestError

    error = classify_ai_error(
        LLMRequestError("模型结构化响应为空。", category="structured_empty_response",
                        diagnostics={"http_status": 200}),
        {"url": "https://x/v1", "model": "m"},
    )
    assert error.code == "bad_response"
    assert not error.detail.startswith("HTTP")


# ---------------------------------------------------------------- 粘贴表格（TSV）

AI_TSV = (
    "标准词\t分类\t别名或常见错写\n"
    "玄方地界\t地点\tげんぽうちかい|玄方地界\n"
    "穗波市\t地点\tほなみし|穗波市|ホナミ市\n"
    "无冠者\t怪物/Boss\t无关者\n"
    "角\t怪物/Boss\t\n"
)


def test_pasted_table_rows_split_into_term_category_and_aliases():
    """10-25：AI 的表贴进「粘贴资料」，以前整行连同制表符成为一个词、表头也成了词。"""
    candidates = PastedTextSource().collect("鸣潮", AI_TSV)
    by_term = {c.term: c for c in candidates}
    assert set(by_term) == {"玄方地界", "穗波市", "无冠者", "角"}
    assert all("\t" not in c.term for c in candidates)
    assert by_term["玄方地界"].category == "location"
    assert by_term["玄方地界"].aliases == ("げんぽうちかい",)
    assert by_term["穗波市"].aliases == ("ほなみし", "ホナミ市")
    assert by_term["无冠者"].category == "enemy"
    assert by_term["角"].aliases == ()
    assert all(c.source == "pasted" for c in candidates)


def test_ai_glossary_tsv_header_is_recognised_even_after_a_fence():
    from twobyteasr.glossary.smart_glossary import is_ai_glossary_tsv

    assert is_ai_glossary_tsv(AI_TSV)
    fenced = "```tsv\n" + AI_TSV + "```\n"
    assert is_ai_glossary_tsv(fenced)
    assert not is_ai_glossary_tsv("今汐\n长离\n角色：椿、吟霖")
    terms = [c.term for c in parse_ai_glossary_tsv(fenced)]
    assert "标准词" not in terms and terms[:2] == ["玄方地界", "穗波市"]


# ---------------------------------------------------------------- 组合流程

def test_build_candidates_combines_sources_and_keeps_source_evidence():
    payload = json.loads((ROOT / "game_profiles.json").read_text(encoding="utf-8-sig"))
    builtin = BuiltinGlossarySource(payload, ROOT).collect("洛克王国：世界")
    pasted = PastedTextSource().collect("洛克王国：世界", "炮米花\n愿力")
    combined = build_candidates(builtin, pasted)
    by_term = {c.term: c for c in combined}
    # 重复词合并：builtin + pasted → source 保留两者证据
    assert "炮米花" in by_term
    assert "builtin" in by_term["炮米花"].source
    assert "pasted" in by_term["炮米花"].source


def test_external_ai_prompt_and_tsv_are_preview_only_candidates():
    prompt = build_ai_glossary_prompt("原神")
    assert "原神" in prompt
    assert "TSV" in prompt
    candidates = parse_ai_glossary_tsv(
        "标准词\t分类\t别名或常见错写\n"
        "芙宁娜\t角色\t芙宁那|水神\n"
        "仆人\t怪物/Boss\t阿蕾奇诺\n"
        "芙宁娜\t角色\t芙宁那\n"
    )
    assert [item.term for item in candidates] == ["芙宁娜", "仆人"]
    assert candidates[0].aliases == ("水神", "芙宁那")
    assert candidates[0].status == STATUS_AI_SUGGESTED
    assert candidates[0].source == "ai"
    assert candidates[1].category == "enemy"


# ---------------------------------------------------------------- 网页来源安全

def test_is_safe_web_url_rejects_private_and_loopback_hosts(monkeypatch):
    from twobyteasr.glossary.smart_glossary import is_safe_web_url

    # 私网/回环/链路本地 IP 字面量：确定性拒绝（不依赖 DNS）
    assert is_safe_web_url("http://127.0.0.1/x")[0] is False
    assert is_safe_web_url("http://169.254.169.254/latest/meta-data")[0] is False
    assert is_safe_web_url("http://192.168.1.1/x")[0] is False
    assert is_safe_web_url("http://10.0.0.5/x")[0] is False
    assert is_safe_web_url("file:///c:/windows/x")[0] is False
    assert is_safe_web_url("ftp://example.com/x")[0] is False
    # localhost 主机名 → 回环解析
    assert is_safe_web_url("https://localhost/x")[0] is False
    # 公网域名：注入 DNS 解析（沙箱不依赖真实网络）
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, port, **kwargs: [(2, 1, 6, "", ("93.184.216.34", port))],
    )
    ok, _reason = is_safe_web_url("https://wiki.biligame.com/rocom")
    assert ok is True
    # 公网域名解析到私网 IP 也必须拒绝
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, port, **kwargs: [(2, 1, 6, "", ("192.168.0.5", port))],
    )
    assert is_safe_web_url("https://evil.example.com/x")[0] is False


def test_safe_web_url_checks_all_dns_results_and_supports_proxy_fake_ip(monkeypatch):
    from twobyteasr.glossary.smart_glossary import is_safe_web_url

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, port, **kwargs: [
            (2, 1, 6, "", ("93.184.216.34", port)),
            (10, 1, 6, "", ("fd00::1", port, 0, 0)),
        ],
    )
    ok, reason = is_safe_web_url("https://mixed.example/x")
    assert ok is False
    assert "fd00::1" in reason

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, port, **kwargs: [(2, 1, 6, "", ("198.18.2.207", port))],
    )
    assert is_safe_web_url("https://zh.minecraft.wiki/")[0] is True
    assert is_safe_web_url("https://198.18.2.207/")[0] is False


def test_fetch_web_text_validates_each_redirect(monkeypatch):
    from twobyteasr.glossary.smart_glossary import fetch_web_text

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, port, **kwargs: [
            (2, 1, 6, "", (("127.0.0.1" if host == "private.example" else "93.184.216.34"), port))
        ],
    )

    class Response:
        def __init__(self, status_code, *, location="", text=""):
            self.status_code = status_code
            self.headers = {"Location": location} if location else {}
            self.text = text

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(str(self.status_code))

    class Requests:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response(302, location="https://private.example/secret")

    client = Requests()
    with pytest.raises(ValueError, match="非公网"):
        fetch_web_text("https://public.example/start", requests_module=client)
    assert len(client.calls) == 1
    assert client.calls[0][1]["allow_redirects"] is False
