"""Read existing Ultra proof asynchronously; never autoload models on page entry."""
from __future__ import annotations
import os


def schedule(window):
    if getattr(window,'_qwen_upgrade_started',False):return
    if os.environ.get('TWOBYTEASR_AUDIT_OWNS_QWEN_PROOF')=='1':return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO','') not in {'','ultra-upgrade','workshop-readiness'}:return
    from ..local_models.model_status_cache import request_registry
    from ..app import ui
    from PySide6.QtCore import QObject, Signal
    class Delivery(QObject):
        done=Signal(object)
    delivery=Delivery(window)
    window._qwen_upgrade_delivery=delivery
    window._qwen_upgrade_started=True
    def finish(registry):
        snapshot=getattr(registry,'alignment_readiness',{}).get('qwen_aligner',{})
        if snapshot.get('ready'):
            from ..recognition.qwen_upgrade import activate_if_ready
            if activate_if_ready(window.legacy.RUNTIME_SETTINGS):
                window._refresh_available_asr_choices()
                page=window.built_page('workshop')
                if page is not None:page.update_runtime_settings(window.legacy.RUNTIME_SETTINGS)
        window._qwen_upgrade_result=dict(ok=bool(snapshot.get('ready')),error=snapshot.get('reason'))
    delivery.done.connect(finish)
    def received(registry):
        try:delivery.done.emit(registry)
        except RuntimeError:pass
    request_registry(ui.APP_ROOT,received)
