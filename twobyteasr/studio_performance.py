"""User-visible, bounded diagnostics over existing playback telemetry."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                              QPlainTextEdit, QPushButton, QVBoxLayout)

from .i18n import bind_text


def performance_snapshot(page, *, compact=False) -> dict:
    canvas = getattr(page, "video", None)
    clock = getattr(canvas, "_playback_clock", None)
    scene = getattr(page, "video_compositor", None)
    layers = {str(x.get("clip_id")): x for x in getattr(scene, "_layers", ())}
    decoders = {key: {"track": layers.get(key, {}).get("track_name") or layers.get(key, {}).get("track_id"),
                     "source_name": Path(source.path).name, **source.performance_snapshot()}
                for key, source in getattr(scene, "_players", {}).items()}
    if compact:
        for row in decoders.values():
            for key in ('recent_requests','samples','callback_gaps_ms'):row.pop(key,None)
    engine=getattr(page,'audio_engine',None)
    decision=getattr(page,'_audio_playback_decision',None)
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "clock": asdict(clock.snapshot()) if clock else None,
        "compositor": scene.performance_snapshot() if scene else None,
        "decoders": decoders,
        "audio": engine.telemetry_snapshot() if engine else None,
        "audio_request": dict(getattr(engine,'_last_payload',{})),
        "audio_routing": asdict(decision) if decision else None,
        "preview_key": getattr(page,'_active_video_preview_key',''),
        "preview_source": getattr(page,'_active_video_preview_source_path',''),
        "playback_mode": getattr(page,'_playback_mode',''),
        "tracks": [{'id':t.id,'enabled':getattr(t,'enabled',True),'muted':getattr(t,'muted',False)}
                   for t in getattr(getattr(page,'project',None),'audio_tracks',())],
        "autosave": list(getattr(page, "_autosave_profile", ()))[-8:],
    }


class StudioPerformanceDialog(QDialog):
    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setObjectName("studioPerformance")
        bind_text(self, '播放性能 · Ctrl+Shift+P', property='windowTitle')
        self.resize(760, 600)
        layout = QVBoxLayout(self)
        title = QLabel("播放性能", self)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        note = QLabel("每 0.5 秒更新，发布帧率取最近 2 秒。耗时为有限样本的 P95；解码时差是帧与请求源时间之差。", self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setObjectName("performanceDetails")
        layout.addWidget(self.details, 1)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton("复制诊断数据", self)
        self.copy_button.setObjectName("studioPrimary")
        self.copy_button.clicked.connect(self.copy_snapshot)
        buttons.addWidget(self.copy_button)
        buttons.addStretch()
        close = QPushButton("关闭", self)
        close.setObjectName("studioButton")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._snapshot = {}
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)

    def showEvent(self, event):
        from .studio_theme import build_studio_qss
        self.setStyleSheet(build_studio_qss())
        self.refresh()
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def refresh(self):
        self._snapshot = performance_snapshot(self.page)
        comp = self._snapshot["compositor"] or {}
        clock = self._snapshot["clock"] or {}
        state = "定位中" if clock.get("seeking") else "暂停" if clock.get("paused", True) else "播放中"
        def number(key):
            value = comp.get(key)
            return "—" if value is None else f"{value:.1f}"
        bind_text(self.summary, '{state}  ·  {value1:g}×  ·  {value2} 个解码器\n发布 {value3} fps    合成 P95 {value4} ms    发布 P95 {value5} ms', state=state, value1=clock.get('playback_rate', 1), value2=len(self._snapshot['decoders']), value3=number('native_publish_fps'), value4=number('render_p95_ms'), value5=number('native_publish_p95_ms'))
        scroll = self.details.verticalScrollBar().value()
        # Keep selection stable so the user can inspect/copy a specific value.
        if not self.details.textCursor().hasSelection():
            self.details.setPlainText(json.dumps(self._snapshot, ensure_ascii=False, indent=2, allow_nan=False))
            self.details.verticalScrollBar().setValue(scroll)

    def copy_snapshot(self):
        self.refresh()
        QApplication.clipboard().setText(json.dumps(self._snapshot, ensure_ascii=False, indent=2, allow_nan=False))
        bind_text(self.copy_button, '已复制诊断数据')
