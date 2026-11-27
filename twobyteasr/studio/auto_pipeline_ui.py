"""Minimal 3-switch Auto-Pipeline panel & dialog (自动开关, 2026-11-25).

Strict UX contract:
  - Only the 3 real cross-episode switches, each title <= 6 chars:
      1. 套常用词库
      2. 套常用人名
      3. 套常用样式
  - Detailed explanations live in hover ``toolTip``; zero long copy on surface.
  - One-line flow capsule showing only checked steps:
      ``识别 → 套常用词库 → 套常用人名 → 套常用样式``
  - No box-in-box: whitespace + 1px thin dividers only.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..design.soft_qss import control_icons, soft_tokens
from ..design.theme_manager import theme_key
from ..design.typography import TITLE_FONT_STACK, UI_FONT_STACK
from ..design.ui_theme import blend_hex, theme_definition
from ..i18n import tr
from ..projects.auto_pipeline import AutoPipelineConfig

SWITCH_SPECS = (
    (
        "run_glossary",
        "套常用词库",
        "挂上本方案词库预检，并仅自动改「连续 3 期干净采纳且同意」的词",
    ),
    (
        "run_speakers",
        "套常用人名",
        "按记住的说话人套用名字和颜色，绝不覆盖已手动起好的名字",
    ),
    (
        "run_style_preset",
        "套常用样式",
        "自动套用本方案记住的字幕样式预设",
    ),
)


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("autoPipeDivider")
    line.setFixedHeight(1)
    return line


class AutoPipelinePanel(QFrame):
    """Borderless 3-switch editor for a saved scheme's auto-pipeline."""

    saved_requested = Signal(object)      # AutoPipelineConfig
    run_now_requested = Signal(object)    # AutoPipelineConfig

    def __init__(
        self,
        *,
        scheme_name: str = "我的常用方案",
        config: AutoPipelineConfig | None = None,
        can_run_now: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("autoPipelinePanel")
        self.scheme_name = str(scheme_name or "我的常用方案")
        self._config = config or AutoPipelineConfig(enabled=True)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # Header row: short title + scheme chip
        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        head_row.setSpacing(8)
        head = QLabel(tr("自动开关"))
        head.setObjectName("autoPipeTitle")
        self.head_title = head
        head_row.addWidget(head)

        self.scheme_badge = QLabel(self.scheme_name)
        self.scheme_badge.setObjectName("autoPipeSchemeBadge")
        head_row.addWidget(self.scheme_badge)
        head_row.addStretch(1)
        root.addLayout(head_row)

        # Single-line borderless flow preview capsule
        self.flow_preview = QLabel("")
        self.flow_preview.setObjectName("autoPipeFlowPill")
        self.flow_preview.setWordWrap(True)
        self.flow_preview.setToolTip(tr("新片进入工作台时按此顺序自动执行已勾选项"))
        root.addWidget(self.flow_preview)

        root.addWidget(_divider())

        # Master enable toggle (<= 6 chars)
        self.cb_enabled = QCheckBox(tr("开启自动执行"))
        self.cb_enabled.setObjectName("autoPipeMasterSwitch")
        self.cb_enabled.setProperty("softSwitch", True)
        self.cb_enabled.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cb_enabled.setChecked(self._config.enabled)
        self.cb_enabled.setToolTip(tr("新识别完成或批量入队进入工作台时，按下方已勾选项自动执行一次"))
        root.addWidget(self.cb_enabled)

        root.addWidget(_divider())

        # Exactly 3 short cross-episode switches (no nested card border!)
        switches_col = QVBoxLayout()
        switches_col.setContentsMargins(2, 2, 2, 2)
        switches_col.setSpacing(12)

        self.cb_glossary = QCheckBox(tr("套常用词库"))
        self.cb_glossary.setChecked(self._config.run_glossary)
        self.cb_glossary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cb_glossary.setToolTip(tr("挂上本方案词库预检，并仅自动改「连续 3 期干净采纳且同意」的词"))
        switches_col.addWidget(self.cb_glossary)

        self.cb_speakers = QCheckBox(tr("套常用人名"))
        self.cb_speakers.setChecked(self._config.run_speakers)
        self.cb_speakers.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cb_speakers.setToolTip(tr("按记住的说话人套用名字和颜色，绝不覆盖已手动起好的名字"))
        switches_col.addWidget(self.cb_speakers)

        self.cb_style = QCheckBox(tr("套常用样式"))
        self.cb_style.setChecked(self._config.run_style_preset)
        self.cb_style.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cb_style.setToolTip(tr("自动套用本方案记住的字幕样式预设"))
        switches_col.addWidget(self.cb_style)
        root.addLayout(switches_col)

        self.status_label = QLabel("")
        self.status_label.setObjectName("autoPipeSub")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        root.addWidget(self.status_label)

        root.addStretch(1)
        root.addWidget(_divider())

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 2, 0, 0)
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        self.run_now_btn = QPushButton(tr("立即试跑"))
        self.run_now_btn.setObjectName("autoPipeSecondary")
        self.run_now_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_now_btn.setToolTip(tr("按当前勾选立即对本片执行一次"))
        self.run_now_btn.setVisible(bool(can_run_now))
        self.run_now_btn.clicked.connect(lambda: self.run_now_requested.emit(self.current_config()))
        btn_row.addWidget(self.run_now_btn)

        self.save_btn = QPushButton(tr("保存方案"))
        self.save_btn.setObjectName("autoPipePrimary")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setToolTip(tr("把以上自动开关保存到当前常用方案"))
        self.save_btn.clicked.connect(lambda: self.saved_requested.emit(self.current_config()))
        btn_row.addWidget(self.save_btn)
        root.addLayout(btn_row)

        for cb in (self.cb_enabled, self.cb_glossary, self.cb_speakers, self.cb_style):
            cb.setMinimumHeight(28)
            cb.toggled.connect(self._sync_preview)
        self._sync_preview()
        self.refresh_theme()

    def current_config(self) -> AutoPipelineConfig:
        return AutoPipelineConfig(
            enabled=self.cb_enabled.isChecked(),
            run_glossary=self.cb_glossary.isChecked(),
            auto_apply_graduated=self.cb_glossary.isChecked(),
            run_speakers=self.cb_speakers.isChecked(),
            run_style_preset=self.cb_style.isChecked(),
        )

    def _sync_preview(self) -> None:
        cfg = self.current_config()
        self.flow_preview.setText(cfg.plain_flow_preview())
        self.flow_preview.setProperty("muted", "false" if cfg.enabled else "true")
        try:
            self.flow_preview.style().unpolish(self.flow_preview)
            self.flow_preview.style().polish(self.flow_preview)
        except Exception:  # noqa: BLE001
            pass

    def set_status(self, text: str) -> None:
        clean = str(text or "").strip()
        self.status_label.setText(clean)
        self.status_label.setVisible(bool(clean))

    def refresh_theme(self) -> None:
        t = theme_definition(theme_key())
        k = soft_tokens(t)
        icon = control_icons(t)
        flow_bg = blend_hex(t.surface, t.accent, 0.12 if t.is_light else 0.22)
        badge_bg = blend_hex(t.surface, t.text, 0.06 if t.is_light else 0.10)
        self.setStyleSheet(f"""
            QFrame#autoPipelinePanel {{
                background: {t.surface};
                border: 0;
            }}
            QFrame#autoPipelinePanel QLabel {{
                background: transparent;
                color: {t.text};
                font-family: {UI_FONT_STACK};
            }}
            QFrame#autoPipelinePanel QFrame#autoPipeDivider {{
                background: {t.border};
                border: 0;
            }}
            QFrame#autoPipelinePanel QLabel#autoPipeTitle {{
                font-family: {TITLE_FONT_STACK};
                font-size: 17px;
                font-weight: 800;
            }}
            QFrame#autoPipelinePanel QLabel#autoPipeSchemeBadge {{
                background: {badge_bg};
                color: {t.text_secondary};
                border: 0;
                border-radius: 9px;
                padding: 3px 9px;
                font-family: {TITLE_FONT_STACK};
                font-size: 13px;
                font-weight: 600;
            }}
            QFrame#autoPipelinePanel QLabel#autoPipeSub {{
                color: {t.text_secondary};
                font-size: 13px;
            }}
            QFrame#autoPipelinePanel QLabel#autoPipeFlowPill {{
                background: {flow_bg};
                color: {t.accent_text};
                border: 0;
                border-radius: 10px;
                padding: 9px 13px;
                font-family: {TITLE_FONT_STACK};
                font-size: 14px;
                font-weight: 700;
            }}
            QFrame#autoPipelinePanel QLabel#autoPipeFlowPill[muted="true"] {{
                background: {k.fill};
                color: {t.text_muted};
            }}
            QFrame#autoPipelinePanel QCheckBox {{
                background: transparent;
                color: {t.text};
                font-family: {UI_FONT_STACK};
                font-size: 15px;
                spacing: 10px;
            }}
            QFrame#autoPipelinePanel QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 0;
                border-radius: 5px;
                background: {k.fill_strong};
                image: none;
            }}
            QFrame#autoPipelinePanel QCheckBox::indicator:hover {{
                background: {blend_hex(k.fill_strong, t.text, 0.08)};
            }}
            QFrame#autoPipelinePanel QCheckBox::indicator:checked {{
                background: {t.accent};
                image: url({icon['check']});
            }}
            QFrame#autoPipelinePanel QCheckBox#autoPipeMasterSwitch::indicator {{
                width: 36px;
                height: 20px;
                border: 0;
                border-radius: 0;
                background: transparent;
                image: url({icon['switch_off']});
            }}
            QFrame#autoPipelinePanel QCheckBox#autoPipeMasterSwitch::indicator:checked {{
                background: transparent;
                image: url({icon['switch_on']});
            }}
            QFrame#autoPipelinePanel QPushButton#autoPipePrimary {{
                background: {t.accent};
                color: {t.text_on_accent};
                border: 0;
                border-radius: 9px;
                padding: 8px 18px;
                font-family: {TITLE_FONT_STACK};
                font-size: 14px;
                font-weight: 700;
            }}
            QFrame#autoPipelinePanel QPushButton#autoPipePrimary:hover {{ background: {t.accent_hover}; }}
            QFrame#autoPipelinePanel QPushButton#autoPipeSecondary {{
                background: {k.fill};
                color: {t.text};
                border: 0;
                border-radius: 9px;
                padding: 8px 16px;
                font-family: {TITLE_FONT_STACK};
                font-size: 14px;
                font-weight: 600;
            }}
            QFrame#autoPipelinePanel QPushButton#autoPipeSecondary:hover {{ background: {k.fill_hover}; }}
        """)


class AutoPipelineDialog(QDialog):
    """Lightweight modal wrapper for ``AutoPipelinePanel``."""

    def __init__(
        self,
        *,
        scheme_name: str = "我的常用方案",
        config: AutoPipelineConfig | None = None,
        on_save: Callable[[AutoPipelineConfig], str | None] | None = None,
        on_run_now: Callable[[AutoPipelineConfig], str | None] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.panel = AutoPipelinePanel(
            scheme_name=scheme_name,
            config=config,
            can_run_now=callable(on_run_now),
            parent=self,
        )
        # 2026-11-26 (user): not the Windows window; the rounded shell carries the title and ×.
        from ..app.rounded_dialog import RoundedDialogShell
        self.panel.head_title.hide()
        self.panel.scheme_badge.hide()
        self.panel.layout().setContentsMargins(4, 6, 6, 2)
        self.shell = RoundedDialogShell(self, self.panel, title=str(tr("自动开关")), chip=str(scheme_name or ""),
                                        size=(460, 400))

        def _do_save(cfg: AutoPipelineConfig) -> None:
            msg = on_save(cfg) if callable(on_save) else "✓ 已保存"
            if msg:
                self.panel.set_status(msg)

        def _do_run(cfg: AutoPipelineConfig) -> None:
            msg = on_run_now(cfg) if callable(on_run_now) else ""
            if msg:
                self.panel.set_status(msg)

        self.panel.saved_requested.connect(_do_save)
        self.panel.run_now_requested.connect(_do_run)


__all__ = ["AutoPipelineDialog", "AutoPipelinePanel", "SWITCH_SPECS"]
