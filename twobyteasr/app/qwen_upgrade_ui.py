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
                retire_official_aligner_later(window)
        window._qwen_upgrade_result=dict(ok=bool(snapshot.get('ready')),error=snapshot.get('reason'))
    delivery.done.connect(finish)
    def received(registry):
        try:delivery.done.emit(registry)
        except RuntimeError:pass
    request_registry(ui.APP_ROOT,received)


def retire_official_aligner_later(window):
    """Delete the old official aligner off the GUI thread once Ultra is verified (2026-11-22)."""
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO',''):return  # audits own their model folders
    if getattr(window,'_official_aligner_retirement',None) is not None:return
    import copy
    import threading
    settings=copy.deepcopy({'models':window.legacy.RUNTIME_SETTINGS.get('models') or {}})
    def busy():
        try:
            worker=getattr(window,'worker',None)
            return bool(getattr(window,'_run_in_progress',False) or (worker is not None and worker.isRunning()))
        except RuntimeError:
            return True  # window already gone: never delete under a closing app
    def work():
        from ..local_models.official_aligner_retirement import retire_official_aligner
        try:result=retire_official_aligner(settings,busy_check=busy)
        except Exception as exc:result=dict(status='error',error=f'{type(exc).__name__}: {exc}')
        window._official_aligner_retirement=result
    window._official_aligner_retirement={}
    threading.Thread(target=work,name='official-aligner-retirement',daemon=True).start()
