"""Zero-friction Quick Glossary Capture UI (2026-11-25).

Directly eliminates the need to call an external AI agent just to add terms:
  - Paste any messy text (wiki/patch notes/chat/``错字 -> 正字``) -> instant
    local zero-latency extraction.
  - Click 「✨ 用文字 AI 整理并补易听错别名」 -> reuses the user's single
    configured Text AI key (same ``polish`` stage as AI grouping & Bunny) on
    a background QThread.
  - Dangerous single-char / common-word aliases are highlighted and unchecked
    by default.
  - 1-click atomic write via ``quick_term_capture.commit_candidates``.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..design.theme_manager import theme_key
from ..design.typography import TITLE_FONT_STACK, UI_FONT_STACK
from ..design.ui_theme import blend_hex, theme_definition
from ..i18n import tr
from . import quick_term_capture as qtc


class _AiExtractWorker(QThread):
    finished_ok = Signal(list, str)
    failed = Signal(str)

    def __init__(self, text: str, game: str, settings: dict | None, suggest_homophones: bool, parent=None):
        super().__init__(parent)
        self.text = text
        self.game = game
        self.settings = settings
        self.suggest_homophones = suggest_homophones

    def run(self) -> None:
        try:
            rows, summary = qtc.extract_terms_with_ai(
                self.text,
                self.game,
                self.settings,
                suggest_homophones=self.suggest_homophones,
                cancel_check=self.isInterruptionRequested,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(" ".join(str(exc).split())[:260] or type(exc).__name__)
            return
        self.finished_ok.emit(rows, summary)


class QuickTermCaptureWidget(QFrame):
    """Self-contained Paste / AI / Project-Diff quick glossary capture panel."""

    committed = Signal(dict)

    def __init__(
        self,
        *,
        library_name: str,
        library_id: str = "",
        legacy: Any = None,
        settings_getter: Callable[[], dict] | None = None,
        project_pairs: Sequence[dict[str, Any]] = (),
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("quickTermCapture")
        self.library_name = str(library_name or "通用词库")
        self.library_id = str(library_id or library_name or "")
        self.legacy = legacy
        self.settings_getter = settings_getter
        self._project_pairs = list(project_pairs)
        self._candidates: list[qtc.QuickTermCandidate] = []
        self._checks: list[tuple[QCheckBox, qtc.QuickTermCandidate]] = []
        self._worker: _AiExtractWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        self.title_label = QLabel(f"随手贴快添词条 · {self.library_name}")
        self.title_label.setObjectName("quickTermTitle")
        head.addWidget(self.title_label, 1)
        if self._project_pairs:
            self.from_edits_btn = QPushButton(f"载入本片手改错字（{len(self._project_pairs)}）")
            self.from_edits_btn.setObjectName("quickTermSecondary")
            self.from_edits_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.from_edits_btn.clicked.connect(self._load_project_edits)
            head.addWidget(self.from_edits_btn)
        root.addLayout(head)

        hint = QLabel("贴上百科/更新公告/聊天记录，或直接写「错词 -> 正词」、「正词（错词1、错词2）」；本机 0 延迟拆词，也能一键用现有文字 AI 深度整理并补常见听错别名。")
        hint.setObjectName("quickTermHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        split = QHBoxLayout()
        split.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(8)
        self.input_box = QPlainTextEdit()
        self.input_box.setObjectName("quickTermInput")
        self.input_box.setPlaceholderText("例：\n杰风 -> 捷风\n欧门（欧闷、偶门）\n或直接贴整段角色/地图/技能介绍文字…")
        self.input_box.setMinimumHeight(190)
        self.input_box.textChanged.connect(self.parse_local)
        left.addWidget(self.input_box, 1)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self.homophone_check = QCheckBox("AI 补充常见易听错别名")
        self.homophone_check.setChecked(True)
        ctrl.addWidget(self.homophone_check)
        ctrl.addStretch(1)
        self.ai_button = QPushButton("✨ 用文字 AI 整理")
        self.ai_button.setObjectName("quickTermAiBtn")
        self.ai_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ai_button.clicked.connect(self.run_ai_extract)
        ctrl.addWidget(self.ai_button)
        left.addLayout(ctrl)

        self.status_label = QLabel("等待粘贴内容…")
        self.status_label.setObjectName("quickTermStatus")
        self.status_label.setWordWrap(True)
        left.addWidget(self.status_label)
        split.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(8)
        rhead = QHBoxLayout()
        self.preview_title = QLabel("待入库候选（危险单字别名已自动取消勾选）")
        self.preview_title.setObjectName("quickTermSection")
        rhead.addWidget(self.preview_title, 1)
        self.commit_button = QPushButton("确认加入词库（0）")
        self.commit_button.setObjectName("quickTermPrimary")
        self.commit_button.setEnabled(False)
        self.commit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.commit_button.clicked.connect(self.commit_selected)
        rhead.addWidget(self.commit_button)
        right.addLayout(rhead)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.viewport().setObjectName("quickTermViewport")
        self.list_host = QWidget()
        self.list_host.setObjectName("quickTermListHost")
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_host)
        right.addWidget(self.scroll, 1)
        split.addLayout(right, 1)

        root.addLayout(split, 1)
        self.refresh_theme()

    def _clear_rows(self) -> None:
        self._checks.clear()
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def set_candidates(self, rows: Sequence[qtc.QuickTermCandidate], status: str = "") -> None:
        self._candidates = list(rows)
        self._clear_rows()
        danger_count = 0
        for row in self._candidates:
            card = QFrame()
            card.setObjectName("quickTermRow")
            card.setProperty("danger", "true" if row.dangerous else "false")
            lay = QVBoxLayout(card)
            lay.setContentsMargins(10, 7, 10, 7)
            lay.setSpacing(3)

            label = (
                f"{row.source} → {row.target}  [{row.category}]"
                if row.is_alias
                else f"{row.target}（规范词）  [{row.category}]"
            )
            cb = QCheckBox(label)
            cb.setChecked(row.checked)
            cb.toggled.connect(lambda checked, r=row: self._toggle_candidate(r, checked))
            lay.addWidget(cb)
            self._checks.append((cb, row))

            if row.warnings:
                danger_count += 1
                warn = QLabel("⚠ " + "；".join(row.warnings))
                warn.setObjectName("quickTermWarn")
                warn.setWordWrap(True)
                lay.addWidget(warn)
            elif row.note:
                note = QLabel(row.note)
                note.setObjectName("quickTermHint")
                note.setWordWrap(True)
                lay.addWidget(note)
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)

        self._refresh_commit_count()
        if status:
            self.status_label.setText(status)
        elif self._candidates:
            extra = f"（已自动拦截 {danger_count} 条高风险别名）" if danger_count else ""
            self.status_label.setText(f"本机已解析 {len(self._candidates)} 条候选{extra}")
        else:
            self.status_label.setText("未识别到词条，可写「错词 -> 正词」或点击「用文字 AI 整理」")

    def _toggle_candidate(self, row: qtc.QuickTermCandidate, checked: bool) -> None:
        row.checked = bool(checked)
        self._refresh_commit_count()

    def _refresh_commit_count(self) -> None:
        count = sum(1 for c in self._candidates if c.checked)
        self.commit_button.setText(f"确认加入词库（{count}）")
        self.commit_button.setEnabled(count > 0)

    def parse_local(self) -> None:
        text = self.input_box.toPlainText()
        if not text.strip():
            self.set_candidates([], "等待粘贴内容…")
            return
        rows = qtc.parse_freeform_terms(text)
        self.set_candidates(rows)

    def _load_project_edits(self) -> None:
        rows = qtc.candidates_from_project_edits(self._project_pairs)
        self.set_candidates(rows, f"已载入本片手动反复修改的 {len(rows)} 条候选")

    def run_ai_extract(self) -> None:
        text = self.input_box.toPlainText().strip()
        if not text:
            self.status_label.setText("请先在左侧输入文字、百科内容或游戏名称")
            return
        settings = self.settings_getter() if callable(self.settings_getter) else {}
        self.ai_button.setEnabled(False)
        self.status_label.setText("正在调用已配置的文字 AI（与 AI 断句同一 Key）整理词条…")
        worker = _AiExtractWorker(text, self.library_name, settings, self.homophone_check.isChecked(), self)
        worker.finished_ok.connect(self._on_ai_done)
        worker.failed.connect(self._on_ai_failed)
        self._worker = worker
        worker.start()

    def _on_ai_done(self, rows: list, summary: str) -> None:
        self.ai_button.setEnabled(True)
        self.set_candidates(rows, f"✨ {summary}")

    def _on_ai_failed(self, reason: str) -> None:
        self.ai_button.setEnabled(True)
        self.status_label.setText(f"文字 AI 整理未完成：{reason}（本机拆词仍可直接用）")

    def commit_selected(self) -> None:
        selected = [c for c in self._candidates if c.checked]
        if not selected:
            return
        if self.legacy is None:
            result = {"added": len(selected), "skipped": 0, "library": self.library_name}
            self.status_label.setText(f"✓ 已准备好 {len(selected)} 条词条")
            self.committed.emit(result)
            return
        try:
            result = qtc.commit_candidates(self.legacy, self.library_id or self.library_name, selected)
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"写入失败：{exc}")
            return
        self.status_label.setText(
            f"✓ 已写入 {result['added']} 条到《{result['library']}》"
            + (f"（跳过已有 {result['skipped']} 条）" if result.get("skipped") else "")
        )
        self.committed.emit(result)

    def refresh_theme(self) -> None:
        t = theme_definition(theme_key())
        ai_color = t.zone_colors.get("ai", t.accent_text)
        ai_bg = blend_hex(t.surface, ai_color, 0.16)
        self.setStyleSheet(f"""
            QFrame#quickTermCapture {{
                background: {t.surface};
                border: 0;
            }}
            QFrame#quickTermCapture QLabel {{
                background: transparent;
                color: {t.text};
                font-family: {UI_FONT_STACK};
            }}
            QFrame#quickTermCapture QCheckBox {{
                background: transparent;
                color: {t.text};
                font-family: {UI_FONT_STACK};
                font-size: 14px;
                spacing: 8px;
            }}
            QFrame#quickTermCapture QScrollArea,
            QWidget#quickTermViewport,
            QWidget#quickTermListHost {{
                background: transparent;
                border: 0;
            }}
            QLabel#quickTermTitle {{
                background: transparent;
                color: {t.text};
                font-family: {TITLE_FONT_STACK};
                font-size: 17px;
                font-weight: 800;
            }}
            QLabel#quickTermSection {{
                background: transparent;
                color: {t.text};
                font-family: {TITLE_FONT_STACK};
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#quickTermHint, QLabel#quickTermStatus {{
                background: transparent;
                color: {t.text_secondary};
                font-family: {UI_FONT_STACK};
                font-size: 13px;
            }}
            QLabel#quickTermWarn {{
                background: transparent;
                color: {t.danger};
                font-family: {TITLE_FONT_STACK};
                font-size: 12px;
                font-weight: 600;
            }}
            QPlainTextEdit#quickTermInput {{
                background: {t.input_surface};
                color: {t.text};
                border: 1px solid {t.border_strong};
                border-radius: 10px;
                padding: 10px;
                font-family: {UI_FONT_STACK};
                font-size: 14px;
            }}
            QFrame#quickTermRow {{
                background: {t.surface_elevated};
                border: 1px solid {t.border};
                border-radius: 9px;
            }}
            QFrame#quickTermRow[danger="true"] {{
                background: {t.danger_soft};
                border-color: {t.danger};
            }}
            QPushButton#quickTermPrimary {{
                background: {t.accent};
                color: {t.on_vivid};
                border: 0;
                border-radius: 9px;
                padding: 8px 16px;
                font-family: {TITLE_FONT_STACK};
                font-size: 14px;
                font-weight: 700;
            }}
            QPushButton#quickTermPrimary:disabled {{
                background: {t.disabled};
                color: {t.text_muted};
            }}
            QPushButton#quickTermAiBtn {{
                background: {ai_bg};
                color: {t.text};
                border: 1px solid {ai_color};
                border-radius: 9px;
                padding: 8px 14px;
                font-family: {TITLE_FONT_STACK};
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton#quickTermSecondary {{
                background: {t.surface_elevated};
                color: {t.text};
                border: 1px solid {t.border_strong};
                border-radius: 9px;
                padding: 7px 13px;
                font-family: {UI_FONT_STACK};
                font-size: 13px;
            }}
        """)


class QuickTermCaptureDialog(QDialog):
    """Standalone modal wrapper for ``QuickTermCaptureWidget``."""

    def __init__(self, *, library_name: str, library_id: str = "", legacy: Any = None,
                 settings_getter: Callable[[], dict] | None = None,
                 project_pairs: Sequence[dict[str, Any]] = (), parent: QWidget | None = None):
        super().__init__(parent)
        self.panel = QuickTermCaptureWidget(
            library_name=library_name,
            library_id=library_id,
            legacy=legacy,
            settings_getter=settings_getter,
            project_pairs=project_pairs,
            parent=self,
        )
        # 2026-11-26 (user): not the Windows window; the rounded shell carries the title and ×.
        from ..app.rounded_dialog import RoundedDialogShell
        self.panel.title_label.hide()
        self.panel.layout().setContentsMargins(2, 4, 6, 2)
        self.shell = RoundedDialogShell(self, self.panel, title="随手贴快添词条", chip=str(library_name or ""),
                                        size=(900, 560))


__all__ = ["QuickTermCaptureDialog", "QuickTermCaptureWidget"]
