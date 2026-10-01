"""User-started, bounded application-state capture. Does not record sound."""
from collections import deque
import json
import time
from PySide6.QtCore import QObject, QTimer
from .i18n import bind_text, tr


class AudioDiagnosticMarker(QObject):
    def __init__(self,page,button):
        super().__init__(page)
        self.page=page
        self.button=button
        self.samples=deque(maxlen=120)
        self.timer=QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.sample)
        self.started=0.
        button.clicked.connect(self.activate)

    def activate(self):
        if self.timer.isActive():
            self.finish('user_marked_muffled_audio')
            return
        self.samples.clear()
        self.started=time.monotonic()
        self.timer.start()
        bind_text(self.button, '听到异常时再次点击标记；仅记录本应用状态，无录音，120 秒自动结束', property='toolTip')
        bind_text(self.button, '标记声音异常')
        self.sample()

    def sample(self):
        page=self.page
        audio=getattr(page,'audio_engine',None)
        if audio is not None:
            self.samples.append(dict(wall=time.time(),elapsed=time.monotonic()-self.started,
                playhead_ms=getattr(getattr(page,'timeline',None),'playhead_ms',None),
                audio=audio.telemetry_snapshot()))
        if time.monotonic()-self.started>=120:self.finish('capture_limit')

    def finish(self,reason):
        self.timer.stop()
        from .studio_project import studio_data_root
        from .build_identity import load_build_identity
        from .provider_diagnostics import redact_diagnostics
        root=studio_data_root()/'logs'/'audio-markers'
        root.mkdir(parents=True,exist_ok=True)
        path=root/(time.strftime('%Y%m%d-%H%M%S')+'.json')
        payload=dict(reason=reason,marked_at=time.time(),source_sha=load_build_identity().source_sha256,
            scope='last 60 seconds application state; no audio capture; no physical-output claim',samples=list(self.samples))
        path.write_text(json.dumps(redact_diagnostics(payload),ensure_ascii=False,indent=2),encoding='utf8')
        bind_text(self.button, '声音诊断')
        bind_text(self.button, '启动最多 120 秒本应用状态诊断；再次点击标记异常，不录音', property='toolTip')
        toast=getattr(self.page,'_show_toast',None)
        if callable(toast):toast(tr('声音异常标记已保存：{path}', path=path))
