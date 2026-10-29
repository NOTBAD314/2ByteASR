"""Shared P9A presentation helpers. No runtime algorithms live here."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .theme_manager import theme_key
from .ui_theme import theme_definition

_MODEL_ALIASES = (
    ("MOSS", ("moss",)),
    ("FireRed", ("firered", "fire-red", "fire_red", "fire red")),
    ("Qwen3", ("qwen3", "qwen")),
)


def _classify_model(name: str) -> str | None:
    raw = str(name or "").strip()
    if not raw:
        return None
    folded = raw.casefold()
    if folded in {"current", "当前", "当前字幕"}:
        return "Current"
    for label, keys in _MODEL_ALIASES:
        if any(key in folded for key in keys):
            return label
    return None


def format_model_evidence_coverage(hypotheses: Iterable[Any] | None) -> dict[str, Any]:
    """Describe independent sources separately from agreement and coverage."""
    from ..recognition.asr_source_evidence import coverage_summary, independent_model
    rows, unknown = [], []
    for row in hypotheses or ():
        if isinstance(row, Mapping):
            item = dict(row)
            name = str(row.get('model') or row.get('source') or row.get('label') or '')
        else:
            name = str(getattr(row, 'model', '') or getattr(row, 'source', '') or
                       getattr(row, 'label', '') or row)
            item = dict(text=getattr(row, 'text', ''))
        item['model'] = name
        if _classify_model(name) == 'Current':
            continue
        if not independent_model(name):
            if name.strip():
                unknown.append(name.strip())
            continue
        rows.append(item)
    summary = coverage_summary(rows)
    present = set(summary['models'])
    marks = {model: '✓' if model in present else '—'
             for model in ('moss', 'firered', 'qwen3-asr')}
    if summary['missing']:
        headline = '来源信息缺失／待恢复'
    elif summary['coverage_unknown']:
        headline = '原始来源已保留 · 字级覆盖待核验'
    elif summary['partial']:
        headline = (f"分段来源覆盖 · 各段 {summary['minimum_count']} 路"
            if summary['minimum_count'] == summary['maximum_count'] else
            f"局部来源覆盖 · {summary['minimum_count']}–{summary['maximum_count']} 路")
    elif summary['conflict']:
        headline = f"{summary['known_count']} 路来源 · 文本存在分歧"
    elif summary['single_source']:
        headline = '单来源 无冲突证据'
    elif summary['agreement']:
        headline = f"{summary['known_count']} 路独立来源 · 文本一致"
    else:
        headline = f"{summary['known_count']} 路独立来源 · 一致性未提供"
    extra = sorted(present.difference({'moss', 'firered', 'qwen3-asr'}))
    display = f"MOSS {marks['moss']}    FireRed {marks['firered']}    Qwen3 {marks['qwen3-asr']}"
    if extra:
        display += '    ' + '    '.join(model.removeprefix('asr-api:') + ' ✓' for model in extra)
    return dict(summary, headline=headline, moss=marks['moss'], firered=marks['firered'],
        qwen=marks['qwen3-asr'], unknown=tuple(unknown),
        display=display)


def map_provider_ui_state(state: str, message: str = "") -> str:
    """Frontend mapping only. Does not change provider transport.

    BACKEND FOLLOW-UP: distinct TIMEOUT / SCHEMA ERROR / QUALITY LOW
    payloads if the adapter still emits a generic ERROR.
    """
    raw = str(state or "").strip().upper()
    text = f"{state} {message}".casefold()
    if raw in {"READY", "SUCCESS", "OK", "SESSION READY"}:
        return "SESSION READY" if raw == "SESSION READY" else "READY"
    if raw in {"REQUESTING", "CHECKING", "DETECTING"} or "正在检测" in str(state):
        return "REQUESTING"
    if raw in {"TIMEOUT", "OFFLINE"} or "timeout" in text or "timed out" in text:
        return "TIMEOUT"
    if raw in {"SCHEMA", "SCHEMA ERROR"} or "schema" in text:
        return "SCHEMA ERROR"
    if raw in {"QUALITY", "QUALITY LOW"} or "quality" in text:
        return "QUALITY LOW"
    if raw in {"ERROR", "FAILURE", "FAILED"}:
        return "FAILURE"
    return raw or "READY"


class StatusBadge(QLabel):
    """Provider / review status chip. Distinct from recognition StatusBadge."""

    _STATES = {
        "READY": "checkPass",
        "SESSION READY": "checkPass",
        "REQUESTING": "checkWarning",
        "TIMEOUT": "checkWarning",
        "SCHEMA ERROR": "checkBlocking",
        "QUALITY LOW": "checkWarning",
        "FAILURE": "checkBlocking",
        "SUCCESS": "checkPass",
    }

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("designStatusBadge")
        self.set_state(text or "READY")

    def set_state(self, state: str) -> None:
        label = str(state or "READY").strip() or "READY"
        self.setText(label)
        self.setObjectName(self._STATES.get(label.upper(), "checkWarning"))
        self.style().unpolish(self)
        self.style().polish(self)


class EmptyState(QFrame):
    """Compact contextual empty state. Does not fill the parent panel."""

    def __init__(
        self,
        title: str,
        body: str,
        parent: QWidget | None = None,
        *,
        primary: str = "",
        secondary: str = "",
        summary: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("designEmptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        hint = QLabel(body)
        hint.setObjectName("contextEmpty")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.primary_button = QPushButton(primary or "")
        self.primary_button.setObjectName("studioPrimary")
        self.secondary_button = QPushButton(secondary or "")
        self.secondary_button.setObjectName("studioButton")
        self.primary_button.setVisible(bool(primary))
        self.secondary_button.setVisible(bool(secondary))
        actions.addWidget(self.secondary_button)
        actions.addWidget(self.primary_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.summary = QLabel(summary)
        self.summary.setObjectName("cardMeta")
        self.summary.setWordWrap(True)
        self.summary.setVisible(bool(summary))
        layout.addWidget(self.summary)

    def apply_theme(self) -> None:
        theme_definition(theme_key())
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
