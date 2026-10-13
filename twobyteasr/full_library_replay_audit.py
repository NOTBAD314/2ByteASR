"""Normal-window audit using real public source cache with zero model dispatch.

This is explicitly offline replay/pre-submit rejection, not a fresh AI run.
TWOBYTEASR_GLOSSARY_REPLAY_SOURCE identifies the prior real audit directory.
"""
from __future__ import annotations
import copy
import json
import os
import socket
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path


def start(owner, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from . import ai_providers, glossary_build as gb, glossary_fullflow as ff
    from .blank_project_audit import _capture
    from .glossary_skill import GlossarySearchError
    from .glossary_skill_ui import GlossaryUpdateReviewDialog
    from .studio_acceptance_audit import require
    from .theme_manager import apply_theme
    app = QApplication.instance(); app.setQuitOnLastWindowClosed(False)
    output = Path(output)
    result = dict(passed=False, replay=True, real_network=False, checks=[], network_dispatches=0)
    state = dict(phase='start', busy=False, task=None, payload=None, started=time.monotonic())
    saved = dict(structured=gb._structured_call, fetch=gb._try_fetch,
                 provider=ai_providers.provider_for_stage, connect=socket.socket.connect,
                 connection=socket.create_connection)
    def blocked_network(*a, **kw):
        raise OSError('offline glossary replay blocks all sockets')
    socket.socket.connect = blocked_network; socket.create_connection = blocked_network
    # A real production task reaches the adapter boundary and is rejected
    # before any provider/CLI dispatch. No model response is manufactured.
    def reject_model(*a, **kw):
        raise GlossarySearchError('offline_replay_pre_dispatch', '离线回放：模型请求在发送前被审计阻止；本次没有调用网络模型。')
    gb._structured_call = reject_model
    gb._try_fetch = lambda *a, **kw: None
    ai_providers.provider_for_stage = lambda *a, **kw: object()
    def check(name, passed, detail=None):
        result['checks'].append(dict(name=name, passed=bool(passed), detail=detail)); require(passed, name)
    def write():
        (output/'full-library-replay-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,
            default=lambda value:asdict(value) if is_dataclass(value) else str(value)), encoding='utf8')
    def finish(error=None):
        timer.stop()
        if error: result['error']=str(error)
        result['passed']=error is None
        result['elapsed_seconds']=round(time.monotonic()-state['started'],3)
        write()
        # Keep the socket guard through shutdown; restore only task hooks.
        gb._structured_call=saved['structured']; gb._try_fetch=saved['fetch']
        ai_providers.provider_for_stage=saved['provider']
        def after_close():
            result['gui_shutdown']=not owner.isVisible(); write()
        app.aboutToQuit.connect(after_close)
        owner.close()
    def tick():
        if state['busy']: return
        state['busy']=True
        try:
            if time.monotonic()-state['started'] > 45: raise TimeoutError('offline complete button audit timed out')
            if state['phase']=='start':
                source=Path(os.environ['TWOBYTEASR_GLOSSARY_REPLAY_SOURCE'])
                cache=source/'local/2ByteASR/glossary-document-cache'
                all_docs=[row for path in cache.glob('*.json') for row in json.loads(path.read_text('utf8')).get('documents',[])]
                relevant=[row for row in all_docs if ff.source_relevance('瓦罗兰特',row)[0]]
                rejected=[row for row in all_docs if not ff.source_relevance('瓦罗兰特',row)[0]]
                check('real cache keeps official game docs and rejects both roof-tile docs',len(relevant)==2 and len(rejected)==2,
                    dict(kept=[r['url'] for r in relevant],rejected=[r['url'] for r in rejected]))
                # These are cached receipts already; do not relabel them as
                # fresh fetches or refresh their original cache timestamps.
                from .cache import atomic_write_json
                cache_path=ff._cache_path('瓦罗兰特')
                cache_path.parent.mkdir(parents=True,exist_ok=True)
                atomic_write_json(str(cache_path),dict(documents=relevant))
                check('real cache copied with original timestamps into isolated data',len(ff.load_document_cache('瓦罗兰特'))==2,
                    dict(path=str(cache_path),cached_at=[row.get('cached_at') for row in relevant]))
                apply_theme('grape',app)
                owner._manage_terms(); app.processEvents()
                page=owner.term_library_page._ensure_library(); state['page']=page
                for i in range(page.game_list.count()):
                    item=page.game_list.item(i)
                    if str(item.data(Qt.ItemDataRole.UserRole + 1))=='瓦罗兰特':page.game_list.setCurrentItem(item);break
                check('actual user library selected',page._library_key()=='瓦罗兰特',page._library_key())
                manager=page._ensure_task_manager();state['manager']=manager
                manager.task_finished.connect(lambda tid,game,payload:state.update(task=tid,payload=payload))
                check('one direct visible button',page.ai_full_button.menu() is None and page.ai_full_button.isVisible() and page.ai_full_button.isEnabled())
                _capture(owner,output/'full-replay-before.png')
                QTest.mouseClick(page.ai_full_button,Qt.MouseButton.LeftButton)
                state['phase']='waiting'
            elif state['phase']=='waiting':
                if state['payload'] is None:return
                payload=state['payload']; result['result']=copy.deepcopy(payload)
                execution=payload['execution']
                check('real adapter attempt with zero provider dispatch',execution['model_attempts']==1 and execution['model_requests_sent']==0 and execution['model_success']==0,execution)
                check('failed terminal with explicit offline reason',payload['outcome']['status']=='failed' and payload['build_stats']['failure']=='offline_replay_pre_dispatch',payload['outcome'])
                check('fresh app sources not claimed in replay',execution['http_requests']==0 and payload['build_stats']['cached_documents']==2)
                task=state['manager'].get(state['task'])
                check('task terminal and waiting note cleared',task.status=='failed' and not task.waiting_note)
                app.processEvents()
                reviews=[widget for widget in owner.findChildren(GlossaryUpdateReviewDialog) if widget.isVisible()]
                require(reviews,'final review visible')
                review=reviews[-1]
                check('zero changes empty table and apply disabled',review.model.rowCount()==0 and not review.apply_button.isEnabled()
                    and review.apply_button.property('zeroApplicable') is True,review.summary_label.text())
                check('zero-change footer does not mislabel processed names', '待审阅变化 0' in review.summary_label.text() and '候选 38' not in review.summary_label.text())
                from .glossary_execution import summary_text
                check('summary shows attempts sent successful separately','模型尝试 1 次' in summary_text(payload)
                    and '实际发送 0 次' in summary_text(payload) and '成功返回 0 次' in summary_text(payload),summary_text(payload))
                _capture(owner,output/'full-replay-terminal.png')
                result['task_id']=state['task']; finish()
        except BaseException as exc: finish(exc)
        finally:state['busy']=False
    timer=QTimer(owner);timer.setInterval(50);timer.timeout.connect(tick);timer.start()
    owner._full_library_replay_timer=timer
