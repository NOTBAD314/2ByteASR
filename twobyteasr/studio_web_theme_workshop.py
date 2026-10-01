"""AI 字幕工坊：对话式二修 AI 特效字幕（2026-09-02 十八轮）.

与样式面板「文字工具」（字体/字号/颜色参数式控件）完全不同的编辑面：
大幅动画演示带（当前字幕真实文本、30fps 循环）+ 对话式修改（自然语言 →
refine_web_theme_design → 范围内自动重套）+ 恢复原始主题 + 档案导出/导入。

入口：①视频画布双击（播头所在 cue 是特效字幕时）②样式面板「特效字幕调整」
卡顶部按钮 ③AI 面板档案行按钮。
"""

from __future__ import annotations

import copy
import threading
from typing import Any, Mapping

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .web_theme import export_theme_archive, import_theme_archive

from .i18n import bind_text

from .i18n import tr

# 演示带参数与 AI 面板一致（十七轮）：30fps 采样 2.4s，显示时裁掉上部空白。
_DEMO_SECONDS = 3.0
_DEMO_FPS = 30.0
_DEMO_BAND_KEEP = 1.0

_QUICK_ASKS = (
    "更醒目一点",
    "字再大一点",
    "换成像素字体",
    "红色泼溅再重一点",
    "出场再快一点",
    "对比度更强，保证任何背景下可读",
    "舞台背景改透明，露出视频画面",
)


class WebThemeWorkshopDialog(QDialog):
    """对话式精修一个 AI 特效字幕主题，并可按范围套用。"""

    # (generation, suggestion_or_exception, target_cue_ids) —— worker 线程回 GUI。
    _refine_finished = Signal(int, object, object)
    _stage_changed = Signal(int, str)

    def __init__(
        self,
        page,
        *,
        cue_id: str,
        theme: Mapping[str, Any],
        cue_text: str,
        speaker_name: str = "",
        parent=None,
        preview: bool = True,
    ) -> None:
        super().__init__(parent)
        bind_text(self, 'AI 字幕工坊 · 对话式精修', property='windowTitle')
        self.setMinimumSize(980, 660)
        self.page = page
        self._project = page.project
        self._draft_watch = None
        self.cue_id = str(cue_id)
        self.cue_text = str(cue_text or "这是字幕特效的动画演示")
        self.speaker_name = str(speaker_name or "")
        self.theme: dict[str, Any] = copy.deepcopy(dict(theme))
        self._original_theme: dict[str, Any] = copy.deepcopy(dict(theme))
        self._rounds = 0
        self._generation = 0
        self._refine_active = False
        self._frames: list[tuple[float, QPixmap]] = []
        self._cursor = 0
        self._timer: QTimer | None = None
        self._worker = None
        self._live_worker = None
        self._bridge = None
        self._stage_changed.connect(self._on_stage_changed)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        self._title = QLabel("")
        self._title.setStyleSheet("font-weight: 700; font-size: 15px;")
        header.addWidget(self._title, 1)
        self._status = QLabel("就绪")
        self._status.setObjectName("contextMeta")
        header.addWidget(self._status)
        root.addLayout(header)
        self._concept = QLabel("")
        self._concept.setObjectName("cardMeta")
        self._concept.setWordWrap(True)
        root.addWidget(self._concept)

        body = QHBoxLayout()
        body.setSpacing(10)

        # 左：大幅动画演示带（与 AI 面板同款循环，真实 HTML/CSS 帧）。
        left = QVBoxLayout()
        self._preview = QLabel("渲染中…")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumSize(460, 258)
        self._preview.setStyleSheet("background: #101018; border-radius: 6px; color: #7f8aa0;")
        self._preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left.addWidget(self._preview, 1)
        chips = QHBoxLayout()
        for ask in _QUICK_ASKS:
            chip = QPushButton(ask)
            chip.setObjectName("studioButton")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _checked=False, text=ask: self._fill_ask(text))
            chips.addWidget(chip)
        chips.addStretch(1)
        left.addLayout(chips)
        body.addLayout(left, 1)

        # 右：对话历史 + 输入 + 发送。
        right = QVBoxLayout()
        self._chat = QTextBrowser()
        self._chat.setOpenExternalLinks(False)
        self._chat.setMinimumWidth(330)
        right.addWidget(self._chat, 1)
        self._input = QPlainTextEdit()
        bind_text(self._input, '对 AI 说修改要求，例如：框换成血红色、字带金属拉丝、粒子更多……', property='placeholderText')
        self._input.setFixedHeight(74)
        right.addWidget(self._input)
        send_row = QHBoxLayout()
        self._send = QPushButton("发送给 AI")
        self._send.setObjectName("studioPrimary")
        self._send.clicked.connect(self._send_ask)
        send_row.addWidget(self._send, 1)
        right.addLayout(send_row)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        # 底：范围 + 套用/恢复/档案。
        bottom = QHBoxLayout()
        self._scope = QComboBox()
        self._scope.addItem("仅当前特效字幕", "current")
        self._scope.addItem("该说话人的特效字幕", "speaker")
        self._scope.addItem("全部特效字幕", "all")
        bottom.addWidget(QLabel("套用范围"))
        bottom.addWidget(self._scope, 1)
        self._apply_all = QPushButton("把当前主题套用到范围")
        self._apply_all.setObjectName("studioButton")
        self._apply_all.clicked.connect(self._apply_current_to_scope)
        bottom.addWidget(self._apply_all)
        self._restore = QPushButton("恢复原始主题")
        self._restore.setObjectName("studioButton")
        self._restore.clicked.connect(self._restore_original)
        bottom.addWidget(self._restore)
        self._export = QPushButton("导出档案")
        self._export.setObjectName("studioButton")
        self._export.clicked.connect(self._export_archive)
        bottom.addWidget(self._export)
        self._import = QPushButton("导入档案")
        self._import.setObjectName("studioButton")
        self._import.clicked.connect(self._import_archive)
        bottom.addWidget(self._import)
        root.addLayout(bottom)

        self._refresh_header()
        self._append_chat(
            "ai",
            "这里是 AI 字幕工坊：演示带是当前字幕的真实 HTML/CSS 渲染，"
            "直接用自然语言告诉我要怎么改（不支持参数微调，一切交给对话）。",
        )
        if preview:
            self._start_preview()

    # ------------------------------------------------------------------
    # header / chat
    # ------------------------------------------------------------------

    def _refresh_header(self) -> None:
        rounds = f" · 已修改 {self._rounds} 轮" if self._rounds else ""
        bind_text(self._title, f"{self.theme.get('name', '未命名主题')}{rounds}")
        self._concept.setText(str(self.theme.get("concept") or ""))

    def _append_chat(self, who: str, text: str) -> None:
        escaped = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        if who == "user":
            block = (
                '<div style="margin:6px 0 6px 18%; text-align:right;">'
                f'<span style="background:#3a3f4b; color:#f2f4f8; border-radius:8px;'
                f' padding:6px 10px; display:inline-block;">{escaped}</span></div>'
            )
        else:
            block = (
                '<div style="margin:6px 18% 6px 0;">'
                f'<span style="background:#22262f; color:#d6dbe6; border-radius:8px;'
                f' padding:6px 10px; display:inline-block;">{escaped}</span></div>'
            )
        self._chat.append(block)

    def _fill_ask(self, text: str) -> None:
        self._input.setPlainText(text)
        self._input.setFocus()

    def _on_stage_changed(self, generation: int, stage: str) -> None:
        if generation != self._generation:
            return
        self._status.setText(str(stage or ""))

    # ------------------------------------------------------------------
    # demo strip（与 AI 面板演示带同源：真实渲染帧循环）
    # ------------------------------------------------------------------

    def _start_preview(self):
        self._stop_preview()
        bind_text(self._preview, '加载动画…')
        from .live_web_preview import LiveWebPreviewWorker
        worker=LiveWebPreviewWorker(loop_seconds=3.,width=960,height=540,name='web-theme-workshop-live')
        self._live_worker=worker
        worker.frame_ready.connect(self._on_preview_live_frame)
        worker.failed.connect(self._on_preview_live_failed)
        worker.configure(theme=self.theme,text=self.cue_text,speaker=self.speaker_name,duration_seconds=3.)
        worker.start()
        def deadline():
            if self._live_worker is worker and not getattr(self,'_preview_received',False):
                worker.stop()
                bind_text(self._preview, '动画加载超时，可关闭后重试；原主题保留')
        self._preview_received=False
        QTimer.singleShot(6000,deadline)

    def _on_preview_live_frame(self, data, cue_ms: float, stage_ms: float) -> None:
        if getattr(data,'worker_id',None) != id(self._live_worker): return
        self._preview_received=True
        # 二十七轮：worker 发原始 PNG bytes（解码在消费方）；兼容历史
        # (QImage, bbox) 元组与 QImage 形态。
        image = data[0] if isinstance(data, tuple) else (
            data if isinstance(data, QImage) else QImage.fromData(data)
        )
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        width, height = pixmap.width(), pixmap.height()
        band = max(1, int(height * _DEMO_BAND_KEEP))
        pixmap = pixmap.copy(0, height - band, width, band)
        self._preview.setPixmap(pixmap.scaled(
            self._preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def _on_preview_live_failed(self,message):
        if self.sender() is not self._live_worker:return
        self._stop_preview()
        bind_text(self._preview, '动画预览失败：{value0}\n可关闭后重试；原主题保留', value0=message)

    def _stop_preview(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        live = getattr(self, "_live_worker", None)
        if live is not None:
            live.stop()
        self._live_worker = None

    def _on_preview_frame(self, key: str, png_path: str) -> None:
        phase, _, seconds_text = key.partition("@")
        if phase != "demo":
            return
        pixmap = QPixmap(png_path)
        if pixmap.isNull():
            return
        try:
            order = float(seconds_text)
        except ValueError:
            order = 0.0
        width, height = pixmap.width(), pixmap.height()
        band = max(1, int(height * _DEMO_BAND_KEEP))
        pixmap = pixmap.copy(0, height - band, width, band)
        self._frames.append((order, pixmap))
        self._frames.sort(key=lambda item: item[0])
        if self._timer is None and self._frames:
            timer = QTimer(self)
            timer.setInterval(int(1000 / _DEMO_FPS))
            timer.timeout.connect(self._advance_preview)
            self._timer = timer
            timer.start()
            self._advance_preview()

    def _advance_preview(self) -> None:
        if not self._frames:
            return
        self._cursor = (self._cursor + 1) % len(self._frames)
        pixmap = self._frames[self._cursor][1]
        self._preview.setPixmap(pixmap.scaled(
            self._preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    # ------------------------------------------------------------------
    # refine（对话式二修）
    # ------------------------------------------------------------------

    def _send_ask(self) -> None:
        ask = self._input.toPlainText().strip()
        if not ask:
            return
        if self._refine_active:
            return
        targets = self._target_cue_ids()
        if not targets:
            self._append_chat("ai", "所选范围内没有 AI 特效字幕，先套用一个主题再来修改。")
            return
        self._append_chat("user", ask)
        self._input.clear()
        self._refine_active = True
        self._send.setEnabled(False)
        bind_text(self._send, 'AI 修改中…')
        bind_text(self._status, '正在请求 AI…')
        self._generation += 1
        generation = self._generation
        theme_copy = copy.deepcopy(self.theme)
        cue_text = self.cue_text
        request = ask
        if len(targets) > 1:
            request += f"（该主题同时用于 {len(targets)} 条字幕，请保持整体风格统一）"

        if self.page.project is not self._project:return
        drafts=self.page._theme_drafts()
        request_id=drafts.repair(request,theme=theme_copy,cue_id=self.cue_id,targets=targets)
        if not request_id:
            self._refine_active=False;self._send.setEnabled(True);bind_text(self._send, '发送给 AI')
            bind_text(self._status, '当前请求仍在进行，请稍后修改')
            return
        self._watch_draft(request_id)

    def _watch_draft(self, request_id, export_destination=None):
        drafts=self.page._theme_drafts()
        self._owned_draft_request=request_id
        if self._draft_watch is not None:self._draft_watch.stop()
        timer=QTimer(self);self._draft_watch=timer
        def tick():
            if self.page.project is not self._project or not drafts.current or drafts.current.request_id!=request_id:
                timer.stop();self._refine_active=False;self._send.setEnabled(True)
                bind_text(self._status, '此请求已被替换');return
            self._status.setText(drafts.detail)
            if drafts.phase in {'PROVIDER','RENDERING','EXPORTING'}:return
            if drafts.is_valid() and drafts.phase in {'READY','APPLIED','EXPORTED'}:
                if export_destination and drafts.phase!='EXPORTED':
                    drafts.export(export_destination);return
                self.theme=drafts.current.theme
                self._refresh_header();self._start_preview()
                outcome = ('档案：'+drafts.last_export if export_destination else
                           '已应用。' if drafts.phase=='APPLIED' else drafts.detail)
                self._append_chat('ai','当前主题已验证。'+outcome)
            else:self._append_chat('ai',drafts.detail)
            self._refine_active=False;self._send.setEnabled(True);bind_text(self._send, '发送给 AI');timer.stop()
        timer.timeout.connect(tick);timer.start(100)

    def _target_cue_ids(self) -> list[str]:
        session = getattr(self.page, "session", None)
        project = getattr(session, "project", None) if session is not None else None
        if project is None:
            return []
        scope = str(self._scope.currentData() or "current")
        current = next((cue for cue in project.cues if cue.id == self.cue_id), None)
        if scope == "all":
            candidates = list(project.cues)
        elif scope == "speaker" and current is not None:
            candidates = [cue for cue in project.cues if cue.speaker_id == current.speaker_id]
        else:
            candidates = [current] if current is not None else []
        return [
            cue.id for cue in candidates
            if isinstance(
                (project.style_recipes.get(cue.style_id, {}) or {}).get("webTheme"), Mapping
            )
        ]

    def _adopt_current(self, theme, export_destination=None):
        if self.page.project is not self._project:return
        drafts=self.page._theme_drafts()
        request_id=drafts.adopt(theme,self.cue_id,auto_apply=not bool(export_destination))
        drafts.apply_targets=self._target_cue_ids() or [self.cue_id]
        self._watch_draft(request_id,export_destination)

    def _apply_current_to_scope(self):
        self._adopt_current(self.theme)

    def _restore_original(self):
        self._adopt_current(self._original_theme)

    def _export_archive(self):
        dest=QFileDialog.getExistingDirectory(self,tr('选择档案保存位置'))
        if dest:self._adopt_current(self.theme,dest)

    def _import_archive(self):
        path,_=QFileDialog.getOpenFileName(self,tr('导入 .2byte-theme 档案'),'','主题档案 (theme.html theme.json)')
        if not path:return
        try:self._adopt_current(import_theme_archive(path))
        except Exception as exc:self._append_chat('ai','导入失败：'+str(exc))

    # ------------------------------------------------------------------
    # lifetime
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._stop_preview()
        if self._draft_watch is not None:self._draft_watch.stop()
        drafts=self.page._theme_drafts()
        if drafts.current and drafts.current.request_id==getattr(self,'_owned_draft_request',None):drafts.cancel()
        super().closeEvent(event)
