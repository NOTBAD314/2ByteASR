"""What the recognition-history details view says about a failed task (2026-11-11).

User request (details design A): the details window should lead with *why*
the task failed and *what to do*, not a list of empty status rows. The view
shows one diagnosis card with a fixed shape:

    结论 · 把握度 · 为什么这么判断 · 关键日志 · 按这个顺序解决 · 还是不行？

It is filled first from the local check (``run_diagnosis``: the known-problem
catalog, nothing sent anywhere) and, when the user asks, from the text AI they
configured. The AI receives the same request the 排查原因 window sends
(``diagnosis_prompt.build_request``) plus an instruction to answer in JSON, so
its answer lands in the same card. Pure: no Qt, no network.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .diagnosis_catalog import ACTION_LABELS

# Actions a step button may carry in the history view. "resume" re-runs the
# unfinished part of this very task; the catalog's task-page actions map to it.
HISTORY_ACTIONS = tuple(action for action in ACTION_LABELS
                        if action not in {"retry", "recover", "studio", "glossary_proofread", "mosi_resplit"})
RESUME_ACTION = "resume"
_RESUME_ALIASES = {"retry", "recover", "resume", "mosi_resplit"}
CONFIDENCE_LEVELS = {"high": ("高", 88), "medium": ("中", 62), "low": ("低", 35)}
_LOCAL_CONFIDENCE = {"certain": "high", "likely": "medium", "possible": "low"}


@dataclass(frozen=True)
class DiagnosisStep:
    title: str
    detail: str = ""
    action: str = ""


@dataclass(frozen=True)
class DiagnosisView:
    """Everything the diagnosis card shows; ``source`` is 'local' or 'ai'."""

    source: str
    conclusion: str
    confidence: str = "medium"
    reasons: tuple[str, ...] = ()
    log_lines: tuple[str, ...] = ()
    steps: tuple[DiagnosisStep, ...] = ()
    fallback: str = ""
    matched: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def confidence_label(self) -> str:
        return CONFIDENCE_LEVELS.get(self.confidence, CONFIDENCE_LEVELS["medium"])[0]

    @property
    def confidence_percent(self) -> int:
        return CONFIDENCE_LEVELS.get(self.confidence, CONFIDENCE_LEVELS["medium"])[1]


def normalize_action(action: Any) -> str:
    value = str(action or "").strip()
    if value in _RESUME_ALIASES:
        return RESUME_ACTION
    if value in HISTORY_ACTIONS or value.startswith("repair_runtime_"):
        return value
    return ""


def _sentences(text: str, limit: int = 3) -> list[str]:
    parts = [part.strip(" ；;。.") for part in re.split(r"[；;。\n]+", str(text or "")) if part.strip(" ；;。.")]
    return parts[:limit]


def local_view(diagnosis, *, language: str = "zh") -> DiagnosisView:
    """The local check as a diagnosis card (top finding first)."""
    from ..i18n import translate
    from .run_diagnosis import specific_text

    top = diagnosis.top if diagnosis is not None else None
    if top is None:
        return DiagnosisView(
            source="local", matched=False, confidence="low",
            conclusion=translate("本地检查没有在已知问题清单里找到原因。", language),
            reasons=tuple(translate(error, language) for error in getattr(diagnosis.facts, "errors", ())[:2])
            if diagnosis is not None else (),
            fallback=translate("可以让 AI 读完整日志再判断一次，或用「回报问题」把诊断包发给开发者。", language),
        )
    issue = top.issue
    specific = specific_text(top, language)
    conclusion = translate(issue.title, language)
    if specific:
        conclusion = f"{conclusion}：{specific}"
    reasons = [translate(issue.cause, language)]
    if issue.symptom:
        reasons.append(translate(issue.symptom, language))
    for other in diagnosis.findings[1:3]:
        reasons.append(translate(other.issue.title, language))
    advice = _sentences(translate(issue.advice, language), 4)
    actions = [normalize_action(action) for action in issue.actions]
    actions = [action for action in actions if action]
    steps: list[DiagnosisStep] = []
    for index, sentence in enumerate(advice):
        steps.append(DiagnosisStep(title=sentence, action=actions[index] if index < len(actions) else ""))
    for action in actions[len(steps):]:
        steps.append(DiagnosisStep(title=translate(ACTION_LABELS.get(action, ""), language) or action, action=action))
    return DiagnosisView(
        source="local",
        conclusion=conclusion,
        confidence=_LOCAL_CONFIDENCE.get(top.confidence, "medium"),
        reasons=tuple(reason for reason in dict.fromkeys(reasons) if reason)[:4],
        log_lines=tuple(top.evidence[:4]),
        steps=tuple(steps[:4]),
        fallback=translate("如果按上面做了还是失败，用「回报问题」把这次的诊断包发给开发者。", language),
    )


STRUCTURED_INSTRUCTION = (
    "这次请不要用 Markdown 回答，只输出一个 JSON 对象（不要代码块），字段如下：\n"
    '{"conclusion": "一两句：最可能的原因", '
    '"confidence": "high | medium | low（你对结论有多大把握）", '
    '"reasons": ["为什么这么判断，最多 4 条，每条一句"], '
    '"log_lines": ["报告里支撑结论的原文行或字段值，最多 4 条，原样摘录"], '
    '"steps": [{"title": "要做的事（短句）", "detail": "一句说明", "action": "按钮代号或空字符串"}], '
    '"fallback": "如果按步骤做了还不行该怎么办，一句"}\n'
    "steps 按顺序最多 4 步。action 只能从这些代号里选，没有合适的就写空字符串：{actions}；"
    "resume 表示「重试这次任务没完成的部分」。"
)


def structured_messages(messages: list[dict]) -> list[dict]:
    """The 排查原因 request with the JSON answer shape appended."""
    copied = [dict(message) for message in messages]
    instruction = STRUCTURED_INSTRUCTION.replace(
        "{actions}", ", ".join([RESUME_ACTION, *HISTORY_ACTIONS]))
    if copied and copied[-1].get("role") == "user":
        copied[-1]["content"] = f"{copied[-1].get('content', '')}\n\n{instruction}"
    else:
        copied.append({"role": "user", "content": instruction})
    return copied


def _json_object(text: str) -> dict | None:
    value = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", value, re.S)
    if fenced:
        value = fenced.group(1)
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(value[start:end + 1])
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _texts(value: Any, limit: int, size: int = 240) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ()
    texts = [" ".join(str(item).split())[:size] for item in value if str(item or "").strip()]
    return tuple(texts[:limit])


def ai_view(answer: str) -> DiagnosisView | None:
    """The AI's JSON answer as a diagnosis card, or None when it is not JSON."""
    data = _json_object(answer)
    if data is None or not str(data.get("conclusion") or "").strip():
        return None
    steps = []
    for item in data.get("steps") if isinstance(data.get("steps"), list) else []:
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            continue
        steps.append(DiagnosisStep(
            title=" ".join(str(item["title"]).split())[:120],
            detail=" ".join(str(item.get("detail") or "").split())[:240],
            action=normalize_action(item.get("action")),
        ))
    confidence = str(data.get("confidence") or "medium").strip().lower()
    return DiagnosisView(
        source="ai",
        conclusion=" ".join(str(data["conclusion"]).split())[:400],
        confidence=confidence if confidence in CONFIDENCE_LEVELS else "medium",
        reasons=_texts(data.get("reasons"), 4),
        log_lines=_texts(data.get("log_lines"), 4, 200),
        steps=tuple(steps[:4]),
        fallback=" ".join(str(data.get("fallback") or "").split())[:240],
    )


def view_text(view: DiagnosisView) -> str:
    """Plain text of a card, for 复制分析."""
    lines = [view.conclusion, ""]
    if view.reasons:
        lines += ["为什么这么判断："] + [f"- {reason}" for reason in view.reasons] + [""]
    if view.log_lines:
        lines += ["关键日志："] + [f"  {line}" for line in view.log_lines] + [""]
    if view.steps:
        lines.append("怎么做：")
        for index, step in enumerate(view.steps, 1):
            lines.append(f"{index}. {step.title}" + (f" — {step.detail}" if step.detail else ""))
        lines.append("")
    if view.fallback:
        lines.append(view.fallback)
    return "\n".join(lines).strip()
