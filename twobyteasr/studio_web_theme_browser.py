"""Web visual theme browser ("Motion Library" v2).

Replaces the legacy graph-motion cards: entries are web themes (built-in
golden themes + AI-generated ones persisted in the style preset store),
each card previews the REAL HTML/CSS rendering through the Remotion service,
and applying supports cue scopes (current / speaker / all).

The preview stills are rendered with the same fixed runtime the export uses
(job_kind="card_preview"), so what the user picks is what the video gets.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .web_theme import WebThemeDocument, builtin_web_themes

from .i18n import bind_text


_PREVIEW_TEXT = "字幕预览ABC123"
_PREVIEW_WIDTH, _PREVIEW_HEIGHT, _PREVIEW_FPS = 1280, 720, 30


def _saved_web_themes() -> list[dict[str, Any]]:
    """AI-persisted web theme recipes from the style preset store."""
    try:
        from .style_presets import StylePresetStore

        recipes = StylePresetStore().load_recipes()
    except Exception:
        return []
    themes: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for style_id, payload in (recipes or {}).items():
        if not isinstance(payload, Mapping):
            continue
        theme = payload.get("webTheme")
        if not isinstance(theme, Mapping) or not theme:
            continue
        try:
            document = WebThemeDocument.from_dict(dict(theme))
        except (TypeError, ValueError):
            continue
        if document.name in seen_names:
            continue
        seen_names.add(document.name)
        themes.append(document.to_dict())
    return themes


class _PreviewWorkerThread(threading.Thread):
    """Render theme stills off the UI thread; emits (key, png_path) via cb."""

    def __init__(
        self,
        jobs: Sequence[tuple[str, dict[str, Any]]],
        on_result: Callable[[str, str], None],
        on_done: Callable[[], None],
    ) -> None:
        super().__init__(daemon=True, name="web-theme-browser-preview")
        self._jobs = list(jobs)
        self._on_result = on_result
        self._on_done = on_done
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            from .renderer_service import GLOBAL_RENDERER_SERVICE, RendererJob
            from .web_theme import effective_appearance

            import tempfile

            directory = Path(tempfile.gettempdir()) / "2ByteASR-web-theme-browser"
            directory.mkdir(parents=True, exist_ok=True)
            # 十七轮：分块渲染+逐块回传——一次性整批渲染 72 帧演示带时要等
            # 30s+ 才有首帧；8 帧一批让演示带先动起来、后续帧渐进并入。
            chunk_size = 8
            for chunk_start in range(0, len(self._jobs), chunk_size):
                if self._cancelled:
                    break
                chunk = self._jobs[chunk_start:chunk_start + chunk_size]
                requests = []
                for index, job in enumerate(chunk):
                    if len(job) >= 3:
                        key, theme, frame_seconds = job[0], job[1], float(job[2])
                    else:
                        key, theme, frame_seconds = job[0], job[1], 1.2
                    sample_text = str(job[3]) if len(job) >= 4 else ""
                    payload = dict(theme)
                    payload.pop("debug", None)
                    # 十八轮：外观注入改为 theme-first——主题自带字体栈/文字色
                    # 优先（此前硬编码 YaHei，主题字体永远显示不出来）。
                    payload["appearance"] = effective_appearance(
                        payload,
                        {
                            "fontFamily": "Microsoft YaHei UI",
                            "fontSize": 44,
                            "bold": True,
                            "italic": False,
                            "color": str(dict(payload.get("palette") or {}).get("text") or "#FFFFFF"),
                            "strokeColor": "#1A0A06",
                            "strokeWidth": 3.5,
                            "stroke2Color": "",
                            "stroke2Width": 0.0,
                            "letterSpacing": 0.5,
                        },
                    )
                    props = {
                        "schemaVersion": 1,
                        "width": _PREVIEW_WIDTH,
                        "height": _PREVIEW_HEIGHT,
                        "fps": _PREVIEW_FPS,
                        # 3s window: storyboard exit samples reach 2.3s (frame 69);
                        # a 2s window made the whole batch fail on the last frames.
                        "durationInFrames": _PREVIEW_FPS * 3,
                        "cues": [{
                            "id": "preview",
                            "text": sample_text or _PREVIEW_TEXT,
                            "speaker": "",
                            "startMs": 0,
                            "endMs": 2000,
                            "styleId": "preview-style",
                            "visual": {"webTheme": payload},
                        }],
                        "recipes": {"preview-style": {"webTheme": payload}},
                    }
                    requests.append(
                        RendererJob(
                            str(directory / f"theme-{chunk_start + index}.png"),
                            props,
                            max(0, int(round(frame_seconds * _PREVIEW_FPS))),
                            job_kind="card_preview",
                            cue_id=f"browser-{chunk_start + index}",
                            project_id="web-theme-browser",
                        )
                    )
                if requests and not self._cancelled:
                    result = GLOBAL_RENDERER_SERVICE.render(
                        requests,
                        render_type="still",
                        resolution=(_PREVIEW_WIDTH, _PREVIEW_HEIGHT),
                        batch_group="web-theme-browser",
                        timeout=180.0,
                    )
                    del result
                for job, request in zip(chunk, requests):
                    if self._cancelled:
                        break
                    path = Path(request.output)
                    if path.is_file() and path.stat().st_size > 0:
                        self._on_result(str(job[0]), str(path))
        except Exception:
            pass
        finally:
            self._on_done()


class _ThemeCard(QWidget):
    chosen = Signal(str, dict)

    def __init__(self, key: str, theme: Mapping[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.theme = dict(theme)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.preview = QLabel("渲染中…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(300, 168)
        self.preview.setStyleSheet(
            "background: #101018; border-radius: 6px; color: #7f8aa0;"
        )
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.preview)
        title = QLabel(str(theme.get("name") or key))
        title.setStyleSheet("font-weight: 700;")
        layout.addWidget(title)
        concept = QPlainTextEdit(str(theme.get("concept") or ""))
        concept.setReadOnly(True)
        concept.setMaximumHeight(58)
        concept.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        layout.addWidget(concept)
        apply_button = QPushButton("应用到所选范围")
        apply_button.clicked.connect(
            lambda: self.chosen.emit(self.key, self.theme)
        )
        layout.addWidget(apply_button)

    def set_preview(self, path: str) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            bind_text(self.preview, '预览不可用')
            return
        scaled = pixmap.scaled(
            300, 168,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(scaled)


class WebThemeBrowserDialog(QDialog):
    """Browse web themes with real previews and apply them by scope."""

    theme_applied = Signal(str, dict)
    preview_ready = Signal(str, str)

    def __init__(self, page, parent=None) -> None:
        super().__init__(parent)
        bind_text(self, '特效字幕库 · Web 主题', property='windowTitle')
        self.setMinimumSize(760, 560)
        self.page = page
        self._cards: dict[str, _ThemeCard] = {}
        self._worker: _PreviewWorkerThread | None = None
        # Worker thread results must hop back to the GUI thread.
        self.preview_ready.connect(self._on_preview)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "内置金样例与 AI 生成主题（AI 面板保存后自动出现在这里）。"
            "预览为真实 HTML/CSS 渲染，与导出一致。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        controls = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItem("当前字幕", "current")
        self.scope.addItem("当前说话人", "speaker")
        self.scope.addItem("全部字幕", "all")
        controls.addWidget(QLabel("应用范围"))
        controls.addWidget(self.scope, 1)
        refresh = QPushButton("刷新预览")
        refresh.clicked.connect(self._rebuild)
        controls.addWidget(refresh)
        layout.addLayout(controls)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(10)
        scroll.setWidget(self.grid_host)
        layout.addWidget(scroll, 1)

        self._rebuild()

    def _collect_themes(self) -> dict[str, dict[str, Any]]:
        themes: dict[str, dict[str, Any]] = {}
        for key, document in builtin_web_themes().items():
            themes[f"builtin:{key}"] = document.to_dict()
        for payload in _saved_web_themes():
            name = str(payload.get("name") or "")
            if name:
                themes[f"saved:{name}"] = payload
        return themes

    def _rebuild(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()
        themes = self._collect_themes()
        for index, (key, theme) in enumerate(themes.items()):
            card = _ThemeCard(key, theme)
            card.chosen.connect(self._apply_theme)
            self.grid.addWidget(card, index // 2, index % 2)
            self._cards[key] = card
        jobs = [(key, card.theme) for key, card in self._cards.items()]
        self._worker = _PreviewWorkerThread(
            jobs,
            on_result=lambda key, path: self.preview_ready.emit(key, path),
            on_done=lambda: None,
        )
        self._worker.start()

    def _on_preview(self, key: str, path: str) -> None:
        card = self._cards.get(key)
        if card is not None:
            card.set_preview(path)

    def _apply_theme(self, key: str, theme: dict) -> None:
        apply_web = getattr(self.page, "_apply_web_theme", None)
        if not callable(apply_web):
            return
        session = getattr(self.page, "session", None)
        project = getattr(session, "project", None) if session is not None else None
        if project is None or not project.cues:
            return
        scope = str(self.scope.currentData() or "current")
        selected_id = str(getattr(session, "selected_cue_id", "") or "")
        if scope == "all":
            target_ids = [cue.id for cue in project.cues]
        elif scope == "speaker":
            current = next((cue for cue in project.cues if cue.id == selected_id), None)
            if current is None:
                target_ids = [selected_id] if selected_id else []
            else:
                target_ids = [
                    cue.id for cue in project.cues
                    if cue.speaker_id == current.speaker_id
                ]
        else:
            target_ids = [selected_id] if selected_id else []
        target_ids = [cue_id for cue_id in target_ids if cue_id]
        if not target_ids:
            return
        applied = 0
        for cue_id in target_ids:
            if apply_web(cue_id, theme):
                applied += 1
        if applied:
            self.theme_applied.emit(str(theme.get("name") or key), theme)
            self.accept()

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            self._worker.cancel()
        super().closeEvent(event)
