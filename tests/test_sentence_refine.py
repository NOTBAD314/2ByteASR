"""AI 断句/句内节奏（2026-09-18 III）：必过样例 917/919 + 护栏 + 幂等 + 撤销。"""

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.subtitle_rules.sentence_refine import (
    build_replacement_cues,
    refine_cues_with_llm,
    validate_action,
)
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _cue(cue_id, start_ms, end_ms, text):
    return StudioCue(id=cue_id, start_ms=start_ms, end_ms=end_ms, text=text)


def _with_alignment(project):
    # Explicit synthetic phrase tokens; these tests exercise UI semantics,
    # not ASR precision. Missing evidence is separately tested as a refusal.
    for cue in project.cues:
        if cue.id == 'c917':
            cue.evidence_refs = ['fixture:c917']
            middle = cue.start_ms + 1900
            project.asr_evidence['fixture:c917'] = {'words': [
                {'text': cue.text[:9], 'start_ms': cue.start_ms, 'end_ms': middle-100},
                {'text': cue.text[9:], 'start_ms': middle, 'end_ms': cue.end_ms}]}
    return project


# —— 校验器 —— (样例来自真实附件 2026-09-17 10-30-25)

def test_sample_917_split_passes_guard():
    action = validate_action(
        "这个直言不讳的说啊其实我想要的是",
        {"action": "split", "split_after_chars": [8]},
    )
    assert action is not None and action.action == "split"


def test_sample_919_space_passes_guard():
    action = validate_action(
        "啊我很喜欢这个角色",
        {"action": "space", "space_after_chars": [0]},
    )
    assert action is not None and action.action == "space"


def test_split_segments_conserve_characters_and_are_monotonic():
    cue = _cue("c917", 3408783, 3412383, "这个直言不讳的说啊其实我想要的是")
    action = validate_action(cue.text, {"action": "split", "split_after_chars": [8]})
    project = _with_alignment(SubtitleProject(media=StudioMedia(path="fixture.mp4"), cues=[cue]))
    parts = build_replacement_cues(cue, action, project=project)
    assert len(parts) == 2
    assert "".join(p.text for p in parts) == cue.text  # 字符守恒
    assert parts[0].text == "这个直言不讳的说啊"
    assert parts[1].text == "其实我想要的是"
    assert parts[0].end_ms <= parts[1].start_ms  # 时间单调
    assert parts[0].start_ms == cue.start_ms and parts[1].end_ms == cue.end_ms
    assert parts[0].speaker_id == cue.speaker_id and parts[0].style_id == cue.style_id
    assert action.estimated_timing is False  # Explicit phrase timing preserved


def test_space_uses_u0020_and_keeps_single_cue():
    cue = _cue("c919", 3416483, 3418233, "啊我很喜欢这个角色")
    action = validate_action(cue.text, {"action": "space", "space_after_chars": [0]})
    parts = build_replacement_cues(cue, action)
    assert len(parts) == 1
    assert parts[0].text == "啊 我很喜欢这个角色"
    assert parts[0].text.count(" ") == 1
    assert parts[0].id == cue.id
    assert parts[0].text.replace(" ", "") == cue.text


@pytest.mark.parametrize("text,raw", [
    # 反例保护：固定搭配不得因单字被拆/插空格
    ("好像还不错", {"action": "space", "space_after_chars": [1]}),   # “好”后插空格
    ("这个好厉害", {"action": "split", "split_after_chars": [2]}),   # “好”后切
    ("对这个角色很满意", {"action": "space", "space_after_chars": [1]}),  # “对”后
    ("队伍搭配", {"action": "split", "split_after_chars": [2]}),     # “伍”后切出2字段
    ("我喜欢这个角色啊", {"action": "split", "split_after_chars": [7]}),  # “啊”成1字段
])
def test_counterexamples_rejected(text, raw):
    assert validate_action(text, raw) is None


def test_out_of_range_and_short_segments_rejected():
    assert validate_action("十二三四五六七八", {"action": "split", "split_after_chars": [99]}) is None
    assert validate_action("一二三四五六", {"action": "split", "split_after_chars": [1]}) is None


def test_genuine_standalone_interjection_allowed():
    assert validate_action("嗯今天天气不错", {"action": "split", "split_after_chars": [0]}) is not None  # 真实独立"嗯"可成句
    assert validate_action("嗯今天天气不错", {"action": "space", "space_after_chars": [0]}) is not None


# —— LLM 全链（fake provider）———

class _FakeProvider:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append(messages)
        return self._responses.pop(0)


def _patch_provider(monkeypatch, responses):
    holder = {"provider": _FakeProvider(responses)}

    def fake_for_stage(settings, stage, sender=None):
        return holder["provider"]

    import twobyteasr.subtitle_rules.sentence_refine as module
    import twobyteasr.providers.ai_providers as providers
    monkeypatch.setattr(providers, "provider_for_stage", fake_for_stage)
    # refine 模块从 ai_providers 延迟 import，patch 源模块即可
    return holder


def test_refine_end_to_end_applies_split_and_space(qapp, tmp_path, monkeypatch):
    cues = [
        _cue("c916", 3405783, 3408783, "嗯那既然出了阿比我就"),
        _cue("c917", 3408783, 3412383, "这个直言不讳的说啊其实我想要的是"),
        _cue("c919", 3416483, 3418233, "啊我很喜欢这个角色"),
    ]
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / "m.flv")), cues=list(cues))
    _with_alignment(project)
    response = json.dumps({"results": [
        {"cue_id": "c917", "action": "split", "split_after_chars": [8]},
        {"cue_id": "c919", "action": "space", "space_after_chars": [0]},
        {"cue_id": "c916", "action": "split", "split_after_chars": [1], "reason": "护栏应拒绝（1字段）"},
    ]}, ensure_ascii=False)
    _patch_provider(monkeypatch, [response])
    outcome = refine_cues_with_llm(cues, project=project, runtime_settings={"models": {"polish": {}}})
    assert outcome.llm_status == "partial"  # invalid field is unfinished, not a completed cue
    actions = {a.cue_id: a for a in outcome.actions}
    assert set(actions) == {"c917", "c919"}  # c916 被 1 字段护栏拒绝
    # 端到端替换
    used = {c.id for c in project.cues}
    for cue in cues:
        action = actions.get(cue.id)
        if action is None:
            continue
        replacement = build_replacement_cues(cue, action, project=project, used_ids=used)
        index = project.cues.index(cue)
        project.cues[index:index + 1] = replacement
    texts = [cue.text for cue in project.cues]
    assert "这个直言不讳的说啊" in texts and "其实我想要的是" in texts
    assert "啊 我很喜欢这个角色" in texts
    assert "嗯那既然出了阿比我就" in texts  # 原文保留
    # 保存重开：空格守恒
    path = tmp_path / "refined.2byteproj"
    save_project(project, path)
    reloaded = __import__("twobyteasr.projects.studio_project", fromlist=["load_project"]).load_project(path)
    reloaded_texts = [cue.text for cue in reloaded.cues]
    assert "啊 我很喜欢这个角色" in reloaded_texts


def test_srt_export_keeps_intra_sentence_space(qapp, tmp_path):
    from twobyteasr.exports.studio_subtitle_export import compile_srt

    cues = [
        _cue("c919", 3416483, 3418233, "啊 我很喜欢这个角色"),
        _cue("c917", 3408783, 3411000, "这个直言不讳的说啊"),
        _cue("c917r1", 3411000, 3412383, "其实我想要的是"),
    ]
    exported = compile_srt(cues)
    assert "啊 我很喜欢这个角色" in exported
    assert "这个直言不讳的说啊" in exported
    assert "其实我想要的是" in exported


def test_page_apply_undo_and_idempotency(qapp, tmp_path, monkeypatch):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    cues = [
        _cue("c917", 3408783, 3412383, "这个直言不讳的说啊其实我想要的是"),
        _cue("c919", 3416483, 3418233, "啊我很喜欢这个角色"),
    ]
    path = tmp_path / "refine-page.2byteproj"
    save_project(_with_alignment(SubtitleProject(media=StudioMedia(path=str(tmp_path / "m.flv")), cues=list(cues))), path)
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *a, **k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *a, **k: None)
    page.open_project(path)
    try:
        response = json.dumps({"results": [
            {"cue_id": "c917", "action": "split", "split_after_chars": [8]},
            {"cue_id": "c919", "action": "space", "space_after_chars": [0]},
        ]}, ensure_ascii=False)
        _patch_provider(monkeypatch, [response])

        from twobyteasr.studio.studio_sentence_refine_ui import refine_cues_with_llm as _unused  # noqa: F401
        from twobyteasr.subtitle_rules import sentence_refine as engine
        # 直接走页面应用路径（绕过 QThread，结果等价）
        outcome = engine.refine_cues_with_llm(
            list(page.project.cues), project=page.project,
            runtime_settings={"models": {"polish": {}}})
        assert len(outcome.actions) == 2
        page._apply_sentence_refine(outcome, list(page.project.cues))

        texts = [cue.text for cue in page.project.cues]
        assert "这个直言不讳的说啊" in texts and "其实我想要的是" in texts
        assert "啊 我很喜欢这个角色" in texts
        assert page.undo_stack.canUndo()

        # 幂等：已处理 cue 被跳过
        scoped = page._collect_refine_scope(whole_project=True)
        assert scoped == [], [c.id for c in scoped]

        # 撤销宏：一步恢复全部
        page.undo_stack.undo()
        restored = [cue.text for cue in page.project.cues]
        assert restored == ["这个直言不讳的说啊其实我想要的是", "啊我很喜欢这个角色"]
    finally:
        page.close_page()


# —— 2026-09-18 VIII：三类句内空格位 + 停顿证据 + 护栏硬化 ——

def test_canonical_repeated_response_example_spaces():
    """「对对很不错啊嗯」→「对 对 很不错啊 嗯」：重复应答+句末独立语气词。"""
    text = "对对很不错啊嗯"
    action = validate_action(text, {"action": "space", "space_after_chars": [0, 1, 5]})
    assert action is not None and action.action == "space"
    cue = _cue("canon", 1000, 4200, text)
    parts = build_replacement_cues(cue, action)
    assert len(parts) == 1
    assert parts[0].text == "对 对 很不错啊 嗯"
    # 除空白外不增删改任何字符。
    assert parts[0].text.replace(" ", "") == text


def test_clause_particle_is_a_valid_space_anchor():
    """句末助词（吧/呢/啦…）后的节奏空格放行；非锚字处仍拒绝。"""
    assert validate_action("我们走吧然后呢", {"action": "space", "space_after_chars": [3]}) is not None
    assert validate_action("这个机制我觉得挺好", {"action": "space", "space_after_chars": [3]}) is None


def test_space_guard_keeps_existing_space_and_rejects_trailing():
    # 已有空格处不再插（规则 5 本地强制，重复处理不叠加）。
    assert validate_action("啊 好", {"action": "space", "space_after_chars": [0]}).action == 'keep'
    # 尾字符后不允许尾随空格。
    assert validate_action("很好嗯", {"action": "space", "space_after_chars": [2]}) is None


def test_pause_hints_from_word_evidence():
    """词级证据的词间停顿 → after_chars 提示；无证据为空不臆造。"""
    from twobyteasr.subtitle_rules.sentence_refine import pause_hints_for_cue

    cue = _cue("p1", 0, 6000, "对对很不错啊嗯")
    words = [
        ("对", 0, 400), ("对", 400, 900),
        ("很不错啊", 2600, 4200),   # 与"对"间真实停顿 1700ms
        ("嗯", 5100, 5900),        # 停顿 900ms
    ]
    hints = pause_hints_for_cue(cue, words)
    assert {"after_chars": 1, "gap_ms": 1700} in hints
    assert {"after_chars": 5, "gap_ms": 900} in hints
    # 短停顿（<150ms）不出现在提示里。
    assert pause_hints_for_cue(cue, [("对", 0, 400), ("对", 450, 900)]) == []
    assert pause_hints_for_cue(cue, []) == []


def test_refine_payload_carries_pause_evidence_and_cue_gap():
    from twobyteasr.subtitle_rules.sentence_refine import refine_payload

    project = SubtitleProject(
        media=StudioMedia(path="x.flv", duration_ms=10_000),
    )
    project.asr_evidence = {
        "segment:1": {
            "start_ms": 0, "end_ms": 6000, "text": "对对很不错啊嗯",
            "words": [
                {"text": "对", "start_ms": 0, "end_ms": 400},
                {"text": "对", "start_ms": 400, "end_ms": 900},
                {"text": "很不错啊", "start_ms": 2600, "end_ms": 4200},
                {"text": "嗯", "start_ms": 5100, "end_ms": 5900},
            ],
        },
    }
    cues = [_cue("a", 0, 6000, "对对很不错啊嗯"), _cue("b", 7000, 9000, "下一句")]
    payload = refine_payload(
        cues,
        neighbors={"a": ("", "下一句"), "b": ("对对很不错啊嗯", "")},
        project=project,
        following_gaps={"a": 1000},
    )
    first = payload["cues"][0]
    assert first["gap_to_next_cue_ms"] == 1000
    assert {"after_chars": 1, "gap_ms": 1700} in first["pause_hints"]
    assert {"after_chars": 5, "gap_ms": 900} in first["pause_hints"]
    assert "pause_hints" not in payload["cues"][1]  # 无证据不臆造


def test_create_studio_outputs_persists_word_evidence_in_ms(tmp_path):
    """词级时间戳写入 evidence（AI 断句停顿证据/词级时间分配的数据源）。

    WordUnit 秒 → evidence words 毫秒（start_ms/end_ms 显式键）。
    """
    from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
    from twobyteasr.projects.studio_project import create_studio_outputs

    segment = SpeechSegment(
        segment_id=1, start=0.0, end=5.0, text="对对很不错啊嗯", confidence=0.9,
        words=[WordUnit(0.0, 0.4, "对", 0.9), WordUnit(0.4, 0.9, "对", 0.9),
               WordUnit(2.6, 4.2, "很不错啊", 0.9), WordUnit(5.1, 5.9, "嗯", 0.9)],
    )
    txt = tmp_path / "t.txt"
    txt.write_text("对对很不错啊嗯", encoding="utf-8")
    project_path = tmp_path / "p.2byteproj"
    create_studio_outputs(
        "media.flv", [], txt_path=str(txt), segments=[segment],
        target_project_path=str(project_path),
    )
    project = SubtitleProject(media=StudioMedia(path="media.flv", duration_ms=6000))
    from twobyteasr.projects.studio_project import load_project
    loaded = load_project(project_path)
    row = loaded.asr_evidence.get("segment:1") or {}
    words = row.get("words") or []
    assert [(w["text"], w["start_ms"], w["end_ms"]) for w in words] == [
        ("对", 0, 400), ("对", 400, 900),
        ("很不错啊", 2600, 4200), ("嗯", 5100, 5900),
    ]
    # 读取端（停顿证据/词级时间分配）吃到同一口径。
    cue = _cue("w1", 0, 6000, "对对很不错啊嗯")
    evidence_words = __import__(
        "twobyteasr.subtitle_rules.sentence_refine", fromlist=["_word_evidence_for_cue"]
    )._word_evidence_for_cue(loaded, cue)
    assert len(evidence_words) == 4
