"""AI-assisted glossary building domain for the Main UI."""

from __future__ import annotations

import json
from .glossary_write_feedback import glossary_write_errors
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .i18n import apply_ui_language, current_language, translate
from .llm_config import validate_endpoint
from .main_ui_branding import _icon
from .main_ui_popup import FramelessPopupCombo
from .ui_theme import AMBER, SURFACE
from .ui_widgets import AnimatedButton, SwitchControl

from .i18n import bind_text

from .i18n import tr


class SmartGlossaryWorker(QThread):
    """智能建词提取：Builtin / 粘贴文本 / Wiki（可选联网）+ AI 增强（可选）。"""

    completed = Signal(str, object, object)   # game, candidates, ai_error
    failed = Signal(str, str)

    def __init__(self, legacy, game_name: str, mode: str, text: str, ai_endpoint, parent=None):
        super().__init__(parent)
        self.legacy = legacy
        self.game_name = str(game_name)
        self.mode = str(mode)          # builtin / pasted / wiki
        self.text = str(text)
        self.ai_endpoint = dict(ai_endpoint) if ai_endpoint else None

    def run(self):
        from twobyteasr.smart_glossary import (
            AiEnhancementError,
            BuiltinGlossarySource,
            PastedTextSource,
            StructuredWikiSource,
            ai_enhance,
            build_candidates,
            parse_ai_glossary_tsv,
        )

        try:
            root = Path(__file__).resolve().parents[1]
            collected = []
            if self.mode == "builtin":
                payload = {}
                try:
                    payload = json.loads(
                        (root / "game_profiles.json").read_text(encoding="utf-8-sig")
                    )
                except (OSError, ValueError, TypeError):
                    pass
                collected = BuiltinGlossarySource(payload, root).collect(self.game_name)
            elif self.mode == "pasted":
                collected = PastedTextSource().collect(self.game_name, self.text)
            elif self.mode == "ai_tsv":
                collected = parse_ai_glossary_tsv(self.text)
            elif self.mode == "wiki":
                from twobyteasr.smart_glossary import fetch_web_text

                html_text = self.text
                if html_text.strip().lower().startswith("http"):
                    html_text = fetch_web_text(html_text.strip())
                collected = StructuredWikiSource().collect(self.game_name, html_text)
            candidates = build_candidates(collected)
            ai_error = None
            if self.mode == "ai_tsv":
                ai_error = None
            elif self.ai_endpoint:
                candidates, ai_error = ai_enhance(self.ai_endpoint, candidates)
            elif not self.ai_endpoint:
                ai_error = AiEnhancementError("missing_key", "未配置 API 密钥")
            self.completed.emit(self.game_name, candidates, ai_error)
        except Exception as exc:  # noqa: BLE001 - thread must report a useful UI error
            self.failed.emit(self.game_name, " ".join(str(exc).split())[:240])


class SmartGlossaryDialog(QWidget):
    """智能建词（D 轮）：来源选择 → 候选提取 → 勾选审核 → 添加到词库。

    Hosted inside MainWindow ModalHost (no new native top-level window).
    Card shows at final size immediately; only backdrop fades.
    Retrieval first, AI optional.
    """

    def __init__(self, owner: "MainWindow", game_name: str, container: QWidget | None = None):
        parent = container if container is not None else owner
        super().__init__(parent)
        self.owner = owner
        self.legacy = owner.legacy
        self.game_name = str(game_name)
        self._candidates = []
        self._worker = None
        # Content only — host provides title/X/backdrop/Esc.
        self._build()
        apply_ui_language(self, current_language())

    # ------------------------------------------------------------ build

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        heading = QHBoxLayout()
        heading_text = QVBoxLayout()
        heading_text.setSpacing(2)
        breadcrumb = QLabel(
            f"{self.game_name} · {translate('独立词库', current_language())}"
        )
        breadcrumb.setObjectName("smartBreadcrumb")
        heading_text.addWidget(breadcrumb)
        title = QLabel("智能建词")
        title.setObjectName("smartDialogTitle")
        heading_text.addWidget(title)
        subtitle = QLabel("优先使用本地或公开资料；AI 只作为可选增强。")
        subtitle.setObjectName("pageSubtitle")
        heading_text.addWidget(subtitle)
        heading.addLayout(heading_text)
        heading.addStretch(1)
        self.progress_badge = QLabel()
        self.progress_badge.setObjectName("termLibraryBadge")
        self.progress_badge.hide()
        heading.addWidget(self.progress_badge)
        layout.addLayout(heading)

        stepper_frame = QFrame()
        stepper_frame.setObjectName("smartStepper")
        stepper = QHBoxLayout(stepper_frame)
        stepper.setContentsMargins(12, 8, 12, 8)
        stepper.setSpacing(6)
        self._step_labels = []
        self._step_dots = []
        for index, caption in enumerate(("1 选择来源", "2 提取预览", "3 确认添加")):
            if index:
                line = QFrame()
                line.setObjectName("smartStepLine")
                line.setFixedHeight(2)
                line.setFixedWidth(24)
                stepper.addWidget(line, 0, Qt.AlignmentFlag.AlignVCenter)
            group = QHBoxLayout()
            group.setContentsMargins(0, 0, 0, 0)
            group.setSpacing(6)
            dot = QFrame()
            dot.setObjectName("smartStepDot")
            dot.setFixedSize(18, 18)
            dot.setProperty("active", index == 0)
            label = QLabel(caption)
            label.setObjectName("smartStep")
            label.setProperty("active", index == 0)
            group.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
            group.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
            stepper.addLayout(group)
            self._step_dots.append(dot)
            self._step_labels.append(label)
        stepper.addStretch(1)
        layout.addWidget(stepper_frame)

        # 来源选择（审核态整体隐藏，避免与候选列表争高度）
        self.source_section = QWidget()
        self.source_section.setMinimumHeight(440)
        source_layout = QVBoxLayout(self.source_section)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(8)
        # 三个来源卡同一行、同一高度（批准图 #7）
        source_cards = QHBoxLayout()
        source_cards.setSpacing(10)
        self.source_group = QButtonGroup(self)
        self.source_group.setExclusive(True)
        self._source_cards: dict[str, QFrame] = {}
        self._source_subtitles: dict[str, QLabel] = {}

        def make_source_card(key: str, title: str, subtitle: str, badge: str = ""):
            card = QFrame()
            card.setObjectName("smartSourceCard")
            card.setProperty("selected", False)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setMinimumHeight(116)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(4)
            title_row = QHBoxLayout()
            title_label = QLabel(title)
            title_label.setObjectName("smartSourceTitle")
            title_row.addWidget(title_label)
            if badge:
                badge_label = QLabel(badge)
                badge_label.setObjectName("smartSourceBadge")
                title_row.addWidget(badge_label)
            title_row.addStretch(1)
            card_layout.addLayout(title_row)
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("muted")
            subtitle_label.setWordWrap(True)
            card_layout.addWidget(subtitle_label)
            self._source_subtitles[key] = subtitle_label
            card_layout.addStretch(1)
            card.mousePressEvent = (
                lambda event, key=key: self._select_source_card(key)
                if event.button() == Qt.MouseButton.LeftButton
                else None
            )
            card.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            card.keyPressEvent = (
                lambda event, key=key: self._select_source_card(key)
                if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Space)
                else QFrame.keyPressEvent(card, event)
            )
            self._source_cards[key] = card
            return card

        source_cards.addWidget(
            make_source_card("builtin", "2ByteASR 内置参考", "本地已有只读参考，最快", "推荐"), 1
        )
        source_cards.addWidget(
            make_source_card("wiki", "Wiki / 网页", "输入 URL 或粘贴网页内容"), 1
        )
        source_cards.addWidget(
            make_source_card("pasted", "粘贴资料", "直接粘贴角色/技能文本"), 1
        )
        source_layout.addLayout(source_cards)
        # Registry strip（官方 source 选中时显示匹配状态）
        self.registry_strip = QFrame()
        self.registry_strip.setObjectName("registryStrip")
        registry_layout = QHBoxLayout(self.registry_strip)
        registry_layout.setContentsMargins(10, 6, 10, 6)
        self.registry_label = QLabel()
        self.registry_label.setObjectName("muted")
        registry_layout.addWidget(self.registry_label, 1)
        self.registry_refresh = AnimatedButton("刷新状态")
        self.registry_refresh.setObjectName("flat")
        self.registry_refresh.clicked.connect(self._refresh_builtin_hint)
        registry_layout.addWidget(self.registry_refresh)
        source_layout.addWidget(self.registry_strip)
        self.registry_strip.hide()
        self.builtin_hint = QLabel()
        self.builtin_hint.setObjectName("muted")
        self.builtin_hint.setWordWrap(True)
        source_layout.addWidget(self.builtin_hint)
        self.pasted_editor = QPlainTextEdit()
        bind_text(self.pasted_editor, '粘贴角色名 / 技能名 / 物品名等，每行一个；\n支持「角色：A、B」分节，或「名称（类别）」。', property='placeholderText')
        self.pasted_editor.hide()
        self.pasted_editor.setMaximumHeight(150)
        source_layout.addWidget(self.pasted_editor)
        wiki_row = QHBoxLayout()
        self.wiki_url = QLineEdit()
        bind_text(self.wiki_url, '输入 Wiki / 网页 URL（如 wiki.biligame.com/…）', property='placeholderText')
        self.wiki_url.setClearButtonEnabled(True)
        self.wiki_url.returnPressed.connect(self.start_extraction)
        wiki_row.addWidget(self.wiki_url, 1)
        self.wiki_fetch_hint = QLabel("会联网获取该页面")
        self.wiki_fetch_hint.setObjectName("muted")
        wiki_row.addWidget(self.wiki_fetch_hint)
        source_layout.addLayout(wiki_row)
        self.wiki_url.hide()

        # AI 增强（可选）独立卡
        self.ai_card = QFrame()
        self.ai_card.setObjectName("smartAiCard")
        self.ai_card.setMinimumHeight(148)
        self.ai_card.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        ai_card_layout = QVBoxLayout(self.ai_card)
        ai_card_layout.setContentsMargins(12, 10, 12, 10)
        ai_card_layout.setSpacing(8)
        ai_header = QHBoxLayout()
        ai_title = QLabel("AI 增强（可选）")
        ai_title.setObjectName("smartSourceTitle")
        ai_header.addWidget(ai_title)
        ai_header.addStretch(1)
        self.copy_ai_prompt_button = AnimatedButton("复制 AI 建词提示词")
        self.copy_ai_prompt_button.setObjectName("flat")
        self.copy_ai_prompt_button.setIcon(_icon("fa5s.copy"))
        self.copy_ai_prompt_button.clicked.connect(self._copy_ai_glossary_prompt)
        ai_header.addWidget(self.copy_ai_prompt_button)
        self.ai_check = SwitchControl("")
        bind_text(self.ai_check, 'AI 增强', property='accessibleName')
        bind_text(self.ai_check, '使用 AI 增强（分类 / 去重 / 别名建议）', property='toolTip')
        ai_header.addWidget(self.ai_check)
        ai_card_layout.addLayout(ai_header)
        ai_pills = QHBoxLayout()
        ai_pills.setSpacing(6)
        for caption in ("自动分类", "去重", "别名建议", "结构化补全"):
            pill = QLabel(caption)
            pill.setObjectName("smartAiPill")
            pill.setFixedHeight(28)
            ai_pills.addWidget(pill)
        ai_pills.addStretch(1)
        ai_card_layout.addLayout(ai_pills)
        ai_description = QLabel(
            "用于候选分类、去重和别名建议；关闭后仍可继续使用基础提取。"
        )
        ai_description.setObjectName("muted")
        ai_description.setWordWrap(True)
        ai_card_layout.addWidget(ai_description)
        self.ai_warn = QFrame()
        self.ai_warn.setObjectName("smartAiWarn")
        warn_layout = QHBoxLayout(self.ai_warn)
        warn_layout.setContentsMargins(8, 6, 8, 6)
        warn_layout.setSpacing(8)
        self.ai_status = QLabel("尚未配置 AI 模型与密钥")
        self.ai_status.setObjectName("muted")
        self.ai_status.setWordWrap(True)
        warn_layout.addWidget(self.ai_status, 1)
        self.ai_config_button = AnimatedButton("前往配置")
        self.ai_config_button.setObjectName("linkButton")
        self.ai_config_button.clicked.connect(self._goto_ai_config)
        warn_layout.addWidget(self.ai_config_button)
        ai_card_layout.addWidget(self.ai_warn)
        source_layout.addWidget(self.ai_card)
        layout.addWidget(self.source_section, 1)

        # 候选 review 区
        self.review_panel = QFrame()
        self.review_panel.setObjectName("endpointCard")
        review_layout = QVBoxLayout(self.review_panel)
        review_layout.setContentsMargins(12, 10, 12, 10)
        review_layout.setSpacing(6)
        review_top = QHBoxLayout()
        self.review_count = QLabel("发现 0 个候选")
        self.review_count.setStyleSheet("font-weight: 600;")
        review_top.addWidget(self.review_count)
        review_top.addStretch(1)
        self.category_filter = FramelessPopupCombo()
        self.category_filter.addItem("全部分类", "")
        self.category_filter.currentIndexChanged.connect(self.apply_review_filter)
        review_top.addWidget(self.category_filter)
        self.source_filter = FramelessPopupCombo()
        self.source_filter.addItem("全部来源", "")
        self.source_filter.currentIndexChanged.connect(self.apply_review_filter)
        review_top.addWidget(self.source_filter)
        self.select_all_button = AnimatedButton("全选")
        self.select_all_button.setObjectName("flat")
        self.select_all_button.clicked.connect(self.toggle_select_all)
        review_top.addWidget(self.select_all_button)
        review_layout.addLayout(review_top)
        self.candidate_list = QListWidget()
        self.candidate_list.setObjectName("smartCandidateList")
        self.candidate_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.candidate_list.setSpacing(2)
        review_layout.addWidget(self.candidate_list, 1)
        self.review_panel.hide()
        layout.addWidget(self.review_panel, 1)

        # Footer remains visually anchored like the rest of the application.
        layout.addStretch(1)
        footer = QFrame()
        footer.setObjectName("modalFooter")
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(14, 10, 14, 10)
        actions.setSpacing(10)
        self.back_button = AnimatedButton("返回")
        self.back_button.setObjectName("outline")
        self.back_button.clicked.connect(self._back_to_sources)
        self.back_button.hide()
        actions.addWidget(self.back_button)
        actions.addStretch(1)
        self.extract_button = AnimatedButton("开始提取")
        self.extract_button.setObjectName("primary")
        self.extract_button.setIcon(_icon("fa5s.search"))
        self.extract_button.clicked.connect(self.start_extraction)
        actions.addWidget(self.extract_button)
        self.add_button = AnimatedButton("添加 0 条到词库")
        self.add_button.setObjectName("primary")
        self.add_button.setIcon(_icon("fa5s.check", SURFACE))
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self.add_selected)
        self.add_button.hide()
        actions.addWidget(self.add_button)
        self.source_summary = QLabel("已选择：2ByteASR 官方词库")
        self.source_summary.setObjectName("muted")
        actions.addWidget(self.source_summary)
        close = AnimatedButton("关闭")
        close.setObjectName("outline")
        close.clicked.connect(self._request_host_close)
        actions.addWidget(close)
        layout.addWidget(footer)

        self._refresh_ai_state()
        self._refresh_builtin_hint()
        self._select_source_card("builtin")

    def _set_smart_step(self, step: int):
        for index, label in enumerate(self._step_labels):
            active = index == step
            label.setProperty("active", active)
            label.style().unpolish(label)
            label.style().polish(label)
            dot = self._step_dots[index]
            dot.setProperty("active", active)
            dot.style().unpolish(dot)
            dot.style().polish(dot)

    def _select_source_card(self, key: str):
        """三 source 卡单选：选中绿框 + 输入区按 mode 显隐 + Registry 条。"""
        for card_key, card in self._source_cards.items():
            selected = card_key == key
            card.setProperty("selected", selected)
            card.style().unpolish(card)
            card.style().polish(card)
        self._mode_key = key
        self.pasted_editor.setVisible(key == "pasted")
        self.wiki_url.setVisible(key == "wiki")
        self.wiki_fetch_hint.setVisible(key == "wiki")
        self.registry_strip.setVisible(key == "builtin")
        self.builtin_hint.hide()
        titles = {
            "builtin": "2ByteASR 内置参考",
            "wiki": "Wiki / 网页",
            "pasted": "粘贴资料",
        }
        bind_text(self.source_summary, f"{translate('已选择：', current_language())}{translate(titles.get(key, ''), current_language())}")
        bind_text(self.extract_button, translate('开始提取', current_language()))

    def _copy_ai_glossary_prompt(self):
        from twobyteasr.smart_glossary import build_ai_glossary_prompt

        QApplication.clipboard().setText(build_ai_glossary_prompt(self.game_name))
        self._select_source_card("pasted")
        self._mode_key = "ai_tsv"
        bind_text(self.pasted_editor, '将 ChatGPT / DeepSeek / Gemini 返回的 TSV 粘贴到这里。\n列顺序：标准词  分类  别名或常见错写', property='placeholderText')
        bind_text(self.source_summary, '已选择：AI 建词 TSV')
        bind_text(self.extract_button, '解析并预览')
        self.pasted_editor.setFocus()
        self._toast("提示词已复制。将 AI 返回的 TSV 粘贴到此处后解析预览。", 2200)

    def _mode(self):
        return str(getattr(self, "_mode_key", "builtin"))

    def _refresh_builtin_hint(self):
        from twobyteasr.smart_glossary import BuiltinGlossarySource, build_candidates

        root = Path(__file__).resolve().parents[1]
        payload = {}
        try:
            payload = json.loads(
                (root / "game_profiles.json").read_text(encoding="utf-8-sig")
            )
        except (OSError, ValueError, TypeError):
            pass
        source = BuiltinGlossarySource(payload, root)
        raw_count = len(source.collect(self.game_name))
        # 统一口径：词条数按去重后计（与术语库主列表一致），
        # 原始资料记录数另行标注，不与词条数混淆。
        count = len(build_candidates(source.collect(self.game_name)))
        version = "v1"
        found = source._profile_for(self.game_name)
        if found:
            _name, profile = found
            updated = str(profile.get("updated", "") or "").strip()
            if updated:
                version = updated if updated.lower().startswith("v") else f"v{updated}"
        if current_language() == "en":
            subtitle = (
                f"{count} terms · {version} · verified"
                if count
                else "No built-in references"
            )
            if count and raw_count != count:
                subtitle += f" ({raw_count} raw records, deduplicated)"
        else:
            subtitle = f"{count} 词条 · {version} · 已校验" if count else "暂无内置参考"
            if count and raw_count != count:
                subtitle += f"（原始资料 {raw_count} 条，去重后 {count} 词条）"
        label = self._source_subtitles.get("builtin")
        if label is not None:
            label.setText(subtitle)
        (bind_text(self.builtin_hint, f'This game has {count} built-in reference terms') if current_language() == 'en' else bind_text(self.builtin_hint, '该游戏已有 {value0} 个内置参考词', value0=count))
        self.builtin_hint.hide()
        if count:
            (bind_text(self.registry_label, f'Built-in references matched · {count} reference terms') if current_language() == 'en' else bind_text(self.registry_label, '已匹配内置参考 · {value0} 条参考词', value0=count))
        else:
            bind_text(self.registry_label, translate('未找到该游戏的官方词库包', current_language()))

    def _refresh_ai_state(self):
        try:
            endpoint = self.legacy.polish_llm_settings()
            validate_endpoint(endpoint, "智能建词 AI 增强")
            has_key = True
        except Exception:
            endpoint = None
            has_key = False
        self._ai_endpoint = endpoint
        self.ai_check.setEnabled(has_key)
        self.ai_warn.setVisible(not has_key)
        self.ai_config_button.setVisible(not has_key)
        if has_key:
            bind_text(self.ai_status, '已配置，可增强')
        else:
            bind_text(self.ai_status, '尚未配置 AI 模型与密钥（未配置 API）')

    def _goto_ai_config(self):
        self.owner.ai_panel.set_expanded(True)
        try:
            self.owner.polish_editor.key.setFocus()
        except Exception:
            pass

    # ------------------------------------------------------------ 提取

    def start_extraction(self):
        if self._worker is not None and self._worker.isRunning():
            return
        mode = self._mode()
        text = ""
        if mode in {"pasted", "ai_tsv"}:
            text = self.pasted_editor.toPlainText().strip()
            if not text:
                self._toast("请先粘贴资料文本。")
                return
        elif mode == "wiki":
            url = self.wiki_url.text().strip()
            if not url:
                self._toast("请先输入网页 URL。")
                return
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            text = url
        ai_endpoint = self._ai_endpoint if self.ai_check.isEnabled() and self.ai_check.isChecked() else None
        bind_text(self.progress_badge, '正在提取…')
        self.progress_badge.show()
        self.extract_button.setEnabled(False)
        self._worker = SmartGlossaryWorker(
            self.legacy, self.game_name, mode, text, ai_endpoint, self
        )
        self._worker.completed.connect(self._extraction_completed)
        self._worker.failed.connect(self._extraction_failed)
        self._worker.start()

    def _extraction_completed(self, _game, candidates, ai_error):
        self.progress_badge.setText("")
        self.progress_badge.hide()
        self.extract_button.setEnabled(True)
        if ai_error is not None and ai_error.code != "missing_key":
            self._show_ai_error(ai_error)
        if not candidates:
            self._toast("没有提取到候选词。请换一个来源或粘贴更多资料。")
            return
        self._candidates = candidates
        self._populate_review()

    def _extraction_failed(self, _game, message):
        self.progress_badge.setText("")
        self.progress_badge.hide()
        self.extract_button.setEnabled(True)
        self._toast(f"智能建词失败：{message}")

    def _toast(self, text: str, ms: int = 1600):
        try:
            t = QLabel(text, self)
            t.setObjectName("smartToast")
            t.setStyleSheet("background:#fffefa; color:#292a27; border:1px solid #e6e0d4; border-radius:10px; padding:8px 12px;")
            t.setWordWrap(True)
            t.adjustSize()
            pr = self.rect()
            tw, th = t.sizeHint().width(), t.sizeHint().height()
            t.setGeometry((pr.width() - tw)//2, pr.height() - th - 18, tw, th)
            t.show()
            t.raise_()
            QTimer.singleShot(ms, lambda: (t.hide(), t.deleteLater()))
        except Exception:
            pass

    # ------------------------------------------------------------ 401 友好 UI

    def _exec_dialog(self, dialog):
        """模态执行（可被测试/截图替换为 show 以非阻塞渲染）。"""
        dialog.exec()

    def _show_ai_error(self, error):
        from twobyteasr.smart_glossary import AiEnhancementError

        message = QMessageBox(self)
        from .studio_theme import apply_secondary_surface_theme

        apply_secondary_surface_theme(message)
        bind_text(message, 'AI 增强不可用', property='windowTitle')
        message.setIcon(QMessageBox.Icon.Warning)
        message.setIconPixmap(_icon("fa5s.exclamation-triangle", AMBER).pixmap(QSize(40, 40)))
        bind_text(message, 'AI 增强不可用')
        bind_text(message, '当前 API 密钥无效或未授权。\n基础建词仍可继续使用，结果已保留。', property='informativeText')
        continue_button = message.addButton(
            "继续无 AI 建词", QMessageBox.ButtonRole.AcceptRole
        )
        config_button = message.addButton(
            "配置 API", QMessageBox.ButtonRole.ActionRole
        )
        message.addButton("查看详情", QMessageBox.ButtonRole.ActionRole)
        message.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        self._exec_dialog(message)
        clicked = message.clickedButton()
        if clicked is None:
            return message  # 非模态展示（截图/预览）时不处理按钮
        if clicked is config_button:
            self.owner.ai_panel.set_expanded(True)
            self.owner.polish_editor.key.setFocus()
        elif clicked == continue_button:
            pass  # 基础流程继续
        else:
            detail = f"错误码：{error.code}\nendpoint：{error.endpoint or '未记录'}\n{error.detail}"
            QMessageBox.information(self, tr('AI 增强详情'), detail)
        return message

    # ------------------------------------------------------------ review

    def _populate_review(self):
        from twobyteasr.smart_glossary import CATEGORY_LABELS

        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem(
            translate("全部分类", current_language()), ""
        )
        for key, label in CATEGORY_LABELS.items():
            self.category_filter.addItem(
                translate(label, current_language()), key
            )
        self.category_filter.blockSignals(False)
        self.source_filter.blockSignals(True)
        self.source_filter.clear()
        self.source_filter.addItem(
            translate("全部来源", current_language()), ""
        )
        seen_sources = []
        for candidate in self._candidates:
            for source in candidate.source.split("/"):
                if source and source not in seen_sources:
                    seen_sources.append(source)
        for source in seen_sources:
            source_label = {
                "builtin": "2ByteASR 词库",
                "pasted": "粘贴资料",
                "wiki": "网页资料",
                "ai": "AI 增强",
            }.get(source, source)
            self.source_filter.addItem(
                translate(source_label, current_language()), source
            )
        self.source_filter.blockSignals(False)
        self._render_candidates()
        self.review_panel.show()
        self.source_section.hide()
        self.back_button.show()
        self.extract_button.hide()
        self.source_summary.hide()
        self.add_button.show()
        self._set_smart_step(1)
        self._update_add_count()

    def _render_candidates(self):
        from twobyteasr.smart_glossary import (
            CATEGORY_LABELS,
            STATUS_AI_SUGGESTED,
        )

        source_labels = {
            "builtin": "2ByteASR 词库",
            "pasted": "粘贴资料",
            "wiki": "网页资料",
            "ai": "AI 增强",
        }
        self.candidate_list.clear()
        category = self.category_filter.currentData() or ""
        source = self.source_filter.currentData() or ""
        for candidate in self._candidates:
            if category and candidate.category != category:
                continue
            if source and source not in candidate.source.split("/"):
                continue
            label = translate(
                CATEGORY_LABELS.get(candidate.category, "其它"),
                current_language(),
            )
            separator = ", " if current_language() == "en" else "、"
            sources = separator.join(
                translate(source_labels.get(part, part), current_language())
                for part in candidate.source.split("/")
                if part
            ) or ("Not recorded" if current_language() == "en" else "未记录")
            source_prefix = "Source: " if current_language() == "en" else "来源："
            item = QListWidgetItem(
                f"{candidate.term}    [{label}]    {source_prefix}{sources}"
            )
            item.setData(Qt.ItemDataRole.UserRole, candidate)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # D6：AI 建议默认不勾选，用户主动勾选 + 添加才是确认。
            item.setCheckState(
                Qt.CheckState.Unchecked
                if candidate.status == STATUS_AI_SUGGESTED
                else Qt.CheckState.Checked
            )
            if candidate.aliases:
                bind_text(item, ('Aliases: ' if current_language() == 'en' else '别名： ') + separator.join(candidate.aliases) + (' (AI suggestion; confirm it before adding a correction mapping)' if current_language() == 'en' and candidate.status == STATUS_AI_SUGGESTED else '（AI 建议，确认后才会写入纠错映射）' if candidate.status == STATUS_AI_SUGGESTED else ''), property='toolTip')
            self.candidate_list.addItem(item)
        (bind_text(self.review_count, f'Found {len(self._candidates)} candidates ({self.candidate_list.count()} shown)') if current_language() == 'en' else bind_text(self.review_count, '发现 {value0} 个候选（当前显示 {value1}）', value0=len(self._candidates), value1=self.candidate_list.count()))

    def apply_review_filter(self, _index=0):
        self._render_candidates()

    def toggle_select_all(self):
        all_checked = all(
            self.candidate_list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self.candidate_list.count())
        )
        new_state = Qt.CheckState.Unchecked if all_checked else Qt.CheckState.Checked
        for i in range(self.candidate_list.count()):
            self.candidate_list.item(i).setCheckState(new_state)
        self._update_add_count()

    def _update_add_count(self):
        count = sum(
            1
            for i in range(self.candidate_list.count())
            if self.candidate_list.item(i).checkState() == Qt.CheckState.Checked
        )
        (bind_text(self.add_button, f'Add {count} to library') if current_language() == 'en' else bind_text(self.add_button, '添加 {value0} 条到词库', value0=count))
        self.add_button.setEnabled(count > 0)

    def _back_to_sources(self):
        self.review_panel.hide()
        self.source_section.show()
        self.back_button.hide()
        self.extract_button.show()
        self.add_button.hide()

    @glossary_write_errors
    def add_selected(self):
        added_terms = 0
        added_aliases = 0
        for index in range(self.candidate_list.count()):
            item = self.candidate_list.item(index)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            candidate = item.data(Qt.ItemDataRole.UserRole)
            from twobyteasr.ui_widgets import category_label

            origin = "AI 学习" if "ai" in str(candidate.source).casefold() else "用户确认"
            category = category_label(candidate.category)
            if self.legacy.add_learned_mapping(
                self.game_name,
                candidate.term,
                candidate.term,
                category=category,
                origin=origin,
            ):
                added_terms += 1
            for alias in candidate.aliases:
                if self.legacy.add_learned_mapping(
                    self.game_name,
                    alias,
                    candidate.term,
                    category=category,
                    origin=origin,
                ):
                    added_aliases += 1
        message = f"已添加 {added_terms} 条术语"
        if added_aliases:
            message += f"、{added_aliases} 条纠错映射"
        message += f" 到《{self.game_name}》"
        self.owner.term_hint.setText(message)
        # Warm hosted close (no native dialog). Show a small toast in content if possible.
        try:
            self._show_inline_toast(message, 1400)
        except Exception:
            pass
        self._request_host_close()  # hosted path (ModalHost)

    def _show_inline_toast(self, text: str, ms: int = 1400):
        t = QLabel(text, self)
        t.setObjectName("smartToast")
        t.setStyleSheet("background:#fffefa; color:#292a27; border:1px solid #e6e0d4; border-radius:10px; padding:8px 12px;")
        t.setWordWrap(True)
        t.adjustSize()
        pr = self.rect()
        tw, th = t.sizeHint().width(), t.sizeHint().height()
        t.setGeometry((pr.width() - tw)//2, pr.height() - th - 20, tw, th)
        t.show()
        t.raise_()
        QTimer.singleShot(ms, lambda: (t.hide(), t.deleteLater()))

    def _request_host_close(self):
        # If hosted by ModalHost, traverse all ancestors before using a local fallback.
        containing_dialog = None
        p = self.parentWidget()
        while p:
            request_close = getattr(p, "_request_close", None)
            if callable(request_close):
                try:
                    request_close()
                    return
                except Exception:
                    pass
            if containing_dialog is None and isinstance(p, QDialog):
                containing_dialog = p
            p = p.parentWidget()
        if containing_dialog is not None:
            containing_dialog.reject()
            return
        self.hide()
