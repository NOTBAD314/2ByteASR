"""P1-2 回归测试：独立 ASR 证据计数（按证据来源家族计票）。

安全语义：
- 可投票：firered（FireRed-AED）、review（Qwen3-ASR / Whisper / FunASR 互斥复核后端）
- 不可投票（派生/佐证，调用方不得传入）：alternate_text（AED 派生副本）、
  firered_llm_text（FireRed-LLM，同源模型族 + 片段选择依赖主链 + 产品规则限定佐证）
- 不同家族即使文本完全相同也各计 1 票；同家族多份文本只计 1 票
"""

import pytest

import subtitle_core
from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.subtitle_rules.polishing import (
    _independent_asr_sources,
    _reference_family,
    filter_untrusted_polished_text,
)

try:
    from twobyteasr.subtitle_rules.correction_safety import count_independent_asr_supports
except ImportError:  # TDD：函数尚未实现时，纯函数用例暂缓执行
    count_independent_asr_supports = None

_PURE_FN_SKIP = pytest.mark.skipif(
    count_independent_asr_supports is None,
    reason="count_independent_asr_supports 尚未实现",
)


# ---------------------------------------------------------------- P1-2 收尾：必填参数

def test_independent_sources_is_required_keyword_only():
    """安全门函数不得静默回退旧计票：漏传 independent_sources 必须 TypeError。"""
    with pytest.raises(TypeError):
        apply_correction_edits(
            "我们进区",
            ["进曲", "", "进曲"],
            [{"from": "进区", "to": "进曲"}],
        )
    with pytest.raises(TypeError):
        apply_correction_edits(
            "我们进区",
            ["进曲", "", "进曲"],
            [{"from": "进区", "to": "进曲"}],
            allow_broad_consensus=False,  # 传了其它参数仍漏 independent_sources
        )


# ---------------------------------------------------------------- P1-2 收尾：family 按模型来源

def _segment(primary_source, firered_text="", qwen_text="", moss_text=""):
    return SpeechSegment(
        segment_id=1,
        start=0.0,
        end=1.0,
        text=moss_text or firered_text or "主稿",
        confidence=0.8,
        words=[],
        primary_source=primary_source,
        firered_text=firered_text,
        qwen_asr_text=qwen_text,
        moss_text=moss_text,
    )


def test_moss_primary_gets_zero_votes_by_itself():
    """边界 1：MOSS primary + 无其它独立 ASR → 0 票。

    MOSS 主稿路径下 first_ref 是 FireRed-AED 输出（firered_text or
    alternate_text）；MOSS 主稿文本本身（moss_text）从不进入独立票来源。
    """
    seg = _segment("moss-host", firered_text="", moss_text="音乐区域")
    # MOSS 主稿路径：first_ref = firered_text or alternate_text（均为空）
    sources = _independent_asr_sources(seg, "")
    assert count_independent_asr_supports("音乐区域", sources) == 0


def test_firered_primary_with_derived_copies_counts_at_most_one():
    """边界 2：FireRed primary + alternate/LLM 副本 → 最多 1 票。"""
    seg = _segment("moss-host", firered_text="洛克王国", qwen_text="")
    sources = _independent_asr_sources(seg, "洛克王国")
    # alternate_text 与 firered_text 同值（MOSS 主稿路径实际形态）与
    # firered_llm_text 都不在 sources 中；即使误传同家族也只计 1。
    assert count_independent_asr_supports("洛克王国", sources) == 1
    assert count_independent_asr_supports(
        "洛克王国", [("firered", "洛克王国"), ("firered", "洛克王国")] + sources
    ) == 1


def test_firered_plus_review_counts_two():
    """边界 3：FireRed + 复核 ASR → 2 票。"""
    seg = _segment("moss-host", firered_text="洛克王国", qwen_text="洛克王国")
    sources = _independent_asr_sources(seg, "洛克王国")
    assert count_independent_asr_supports("洛克王国", sources) == 2


def test_same_backend_as_primary_and_review_counts_one(monkeypatch):
    """边界 4：primary 与 review 同 backend 不得因角色不同算 2 票。

    调度层 equivalent_primary 短路保证同模型不双跑（qwen 字段为空）；
    计数层把 qwen_local 与 local 归一化为同一 family 作兜底。
    """
    # primary = Qwen3-ASR 本地主力，review = local（同一模型）
    seg = _segment(
        "qwen_local-primary",
        firered_text="",
        qwen_text="洛克王国",
        moss_text="洛克王国",
    )
    monkeypatch.setattr(subtitle_core, "QWEN_ASR_BACKEND", "local")
    sources = _independent_asr_sources(seg, "洛克王国")
    assert count_independent_asr_supports("洛克王国", sources) == 1


def test_whisper_primary_and_whisper_review_merge_into_one_family(monkeypatch):
    """边界 4b：primary 与 review 同为 whisper → 1 票（配置名相同的合并）。"""
    seg = _segment(
        "whisper_turbo-primary",
        firered_text="",
        qwen_text="洛克王国",
        moss_text="洛克王国",
    )
    monkeypatch.setattr(subtitle_core, "QWEN_ASR_BACKEND", "whisper_turbo")
    sources = _independent_asr_sources(seg, "洛克王国")
    assert count_independent_asr_supports("洛克王国", sources) == 1


def test_whisper_primary_and_qwen_review_counts_two(monkeypatch):
    """边界 4c：primary 与 review 不同模型 → 2 票。"""
    seg = _segment(
        "whisper_turbo-primary",
        firered_text="",
        qwen_text="洛克王国",
        moss_text="洛克王国",
    )
    monkeypatch.setattr(subtitle_core, "QWEN_ASR_BACKEND", "local")
    sources = _independent_asr_sources(seg, "洛克王国")
    assert count_independent_asr_supports("洛克王国", sources) == 2


def test_reference_family_never_uses_generic_primary():
    """family 必须是模型来源名：已知路径下出现 firered/模型名，未知来源返回 None。"""
    assert _reference_family(_segment("moss-host")) == "firered"
    assert _reference_family(_segment("whisper_turbo-primary")) == "whisper"
    assert _reference_family(_segment("qwen_local-primary")) == "qwen3_asr"
    assert _reference_family(_segment("sensevoice-primary")) == "funasr_sensevoice"
    assert _reference_family(_segment("moss+qwen3-consensus")) is None
    assert _reference_family(_segment("unknown-future-format-primary")) is None


def test_unknown_primary_plus_qwen_review_counts_at_most_one(monkeypatch):
    """收尾：unknown primary + qwen review → 最多 1 票（fail-closed）。"""
    seg = _segment(
        "unknown-future-format-primary",
        firered_text="",
        qwen_text="洛克王国",
        moss_text="洛克王国",
    )
    monkeypatch.setattr(subtitle_core, "QWEN_ASR_BACKEND", "local")
    sources = _independent_asr_sources(seg, "洛克王国")
    assert count_independent_asr_supports("洛克王国", sources) <= 1
    assert count_independent_asr_supports("洛克王国", sources) == 1  # 仅 review 一票


def test_unknown_primary_alone_counts_zero(monkeypatch):
    """收尾：unknown primary 单独存在 → 0 票。"""
    seg = _segment(
        "unknown-future-format-primary",
        firered_text="",
        qwen_text="",
        moss_text="洛克王国",
    )
    monkeypatch.setattr(subtitle_core, "QWEN_ASR_BACKEND", "off")
    sources = _independent_asr_sources(seg, "洛克王国")
    assert count_independent_asr_supports("洛克王国", sources) == 0


def test_known_qwen_primary_plus_qwen_review_counts_one(monkeypatch):
    """收尾：已知 qwen primary + qwen review → 1 票。"""
    seg = _segment(
        "qwen_local-primary",
        firered_text="",
        qwen_text="洛克王国",
        moss_text="洛克王国",
    )
    monkeypatch.setattr(subtitle_core, "QWEN_ASR_BACKEND", "local")
    sources = _independent_asr_sources(seg, "洛克王国")
    assert count_independent_asr_supports("洛克王国", sources) == 1


def test_known_whisper_primary_plus_qwen_review_counts_two(monkeypatch):
    """收尾：已知 whisper primary + qwen review → 2 票。"""
    seg = _segment(
        "whisper_turbo-primary",
        firered_text="",
        qwen_text="洛克王国",
        moss_text="洛克王国",
    )
    monkeypatch.setattr(subtitle_core, "QWEN_ASR_BACKEND", "local")
    sources = _independent_asr_sources(seg, "洛克王国")
    assert count_independent_asr_supports("洛克王国", sources) == 2


# ---------------------------------------------------------------- 纯函数矩阵

@_PURE_FN_SKIP
def test_case_a_two_independent_sources_same_text_count_two():
    """Case A：FireRed-AED 与复核 ASR 输出完全相同 → 2 票（不得内容去重）。"""
    sources = [("firered", "洛克王国"), ("review", "洛克王国")]
    assert count_independent_asr_supports("洛克王国", sources) == 2


@_PURE_FN_SKIP
def test_case_b_firered_plus_alternate_copy_counts_one():
    """Case B：firered_text == alternate_text 时（MOSS 主稿路径实际形态）→ 1 票。

    alternate_text 是 AED 的派生副本，调用方不得作为独立来源传入。
    """
    sources = [("firered", "洛克王国")]
    assert count_independent_asr_supports("洛克王国", sources) == 1


@_PURE_FN_SKIP
def test_case_c_firered_plus_firered_llm_counts_one():
    """Case C：FireRed-LLM 不得贡献独立票 → 1 票。"""
    sources = [("firered", "洛克王国")]
    assert count_independent_asr_supports("洛克王国", sources) == 1


@_PURE_FN_SKIP
def test_case_d_three_identical_firered_family_texts_count_one():
    """Case D：firered + alternate + firered_llm 三份相同 → 1 票（不能是 2 或 3）。"""
    sources = [("firered", "洛克王国"), ("firered", "洛克王国"), ("firered", "洛克王国")]
    assert count_independent_asr_supports("洛克王国", sources) == 1


@_PURE_FN_SKIP
def test_case_e_firered_family_plus_review_counts_two():
    """Case E：firered 家族（多副本）+ 复核 ASR → 2 票。"""
    sources = [
        ("firered", "洛克王国"),
        ("firered", "洛克王国"),
        ("firered", "洛克王国"),
        ("review", "洛克王国"),
    ]
    assert count_independent_asr_supports("洛克王国", sources) == 2


@_PURE_FN_SKIP
def test_case_f_only_review_counts_one():
    """Case F：只有复核 ASR → 1 票。"""
    assert count_independent_asr_supports("洛克王国", [("review", "洛克王国")]) == 1


@_PURE_FN_SKIP
def test_case_g_only_firered_llm_counts_zero():
    """Case G：只有 FireRed-LLM（派生证据）→ 0 票。"""
    assert count_independent_asr_supports("洛克王国", []) == 0


@_PURE_FN_SKIP
def test_case_h_only_alternate_text_counts_zero():
    """Case H：只有 alternate_text（派生副本）→ 0 票。"""
    assert count_independent_asr_supports("洛克王国", []) == 0


@_PURE_FN_SKIP
def test_case_i_empty_and_none_inputs_are_safe():
    """Case I：None / 空串 / 空列表 不得抛异常、不得产生假票。"""
    assert count_independent_asr_supports("", []) == 0
    assert count_independent_asr_supports(None, []) == 0
    assert count_independent_asr_supports("洛克", None) == 0
    assert count_independent_asr_supports("洛克", [("firered", None), ("review", "")]) == 0
    assert count_independent_asr_supports("洛克", [("firered", "洛克"), ("review", None)]) == 1


@_PURE_FN_SKIP
def test_case_j_different_texts_vote_for_their_own_target():
    """Case J：不同来源文本不同时，各 target 只得到自己的票。"""
    sources = [("firered", "洛克王国"), ("review", "洛克帝国")]
    assert count_independent_asr_supports("洛克王国", sources) == 1
    assert count_independent_asr_supports("洛克帝国", sources) == 1


@_PURE_FN_SKIP
def test_threshold_mode_uses_best_similarity_per_family():
    """相似度模式：每家族取最高相似度计票。"""
    # "洛克王国开始了" 与 "洛克王国" 的相似度约为 0.73；threshold=0.7 时
    # firered 家族（两副本取最高分）与 review 家族各 1 票。
    sources = [("firered", "洛克王国开始了"), ("firered", "洛克王国"), ("review", "洛克王国")]
    assert count_independent_asr_supports("洛克王国", sources, threshold=0.7) == 2
    sources2 = [("firered", "洛克王国开始了"), ("review", "完全不同的文本内容")]
    assert count_independent_asr_supports("洛克王国", sources2, threshold=0.7) == 1


# ---------------------------------------------------------------- apply_correction_edits 集成

def _two_char_edit_run(alternates, independent_sources):
    """双字补丁 "进区"→"进曲"（走单字差异门，真正由独立票数裁决）。"""
    text, applied = apply_correction_edits(
        "我们进区",
        alternates,
        [{"from": "进区", "to": "进曲", "basis": "test"}],
        independent_sources=independent_sources,
    )
    return text, applied


def test_integration_firered_plus_llm_copy_does_not_reach_two_votes():
    """Case C 集成：firered 与 FireRed-LLM 同写"进曲" → 只有 1 路独立证据 → 拦截。"""
    text, applied = _two_char_edit_run(
        alternates=["进曲", "", "进曲"],  # firered, qwen(空), firered_llm
        independent_sources=[("firered", "进曲"), ("review", "")],
    )
    assert applied == [], "单路独立证据 + FireRed-LLM 副本不得凑满两套支持"
    assert text == "我们进区"


def test_integration_two_truly_independent_sources_allow_edit():
    """Case A 集成：firered 与复核 ASR 都支持"进曲" → 2 票 → 放行。"""
    text, applied = _two_char_edit_run(
        alternates=["进曲", "进曲", ""],
        independent_sources=[("firered", "进曲"), ("review", "进曲")],
    )
    assert applied != [], "两路真正独立的 ASR 应允许双字修正"
    assert text == "我们进曲"


# ---------------------------------------------------------------- filter_untrusted 集成

def test_filter_untrusted_derived_copies_do_not_count_as_independent():
    """filter_untrusted 只接收独立证据：alternate/LLM 副本不再凑票。"""
    baseline = "我们进入音乐区"
    candidate = "我们进入音乐曲"
    # 独立证据调用方只传 [firered_text, qwen_asr_text]；
    # alternate_text 与 firered_text 同值、firered_llm_text 同值均不得传入。
    alternates = ["音乐曲", ""]  # firered, qwen（无）
    result = filter_untrusted_polished_text(baseline, candidate, alternates, [])
    assert result == baseline, "单路独立证据不得放行替换"


def test_filter_untrusted_two_independent_sources_allow_edit():
    """filter_untrusted：firered 与复核 ASR 都支持 → 放行。"""
    baseline = "我们进入音乐区"
    candidate = "我们进入音乐曲"
    alternates = ["音乐曲", "音乐曲"]
    result = filter_untrusted_polished_text(baseline, candidate, alternates, [])
    assert result == candidate, "两路独立证据应放行"
