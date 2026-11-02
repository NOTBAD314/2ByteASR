"""Controlled progress events in the normal MainWindow, source and frozen."""
from __future__ import annotations
import json,time,traceback


def start(window,output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from ..recognition.service import PipelineEvent
    result=dict(passed=False,checks=[],scope='headed MainWindow; controlled events; no provider calls')
    def save():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    def check(name,value,**data):
        result['checks'].append(dict(name=name,passed=bool(value),**data))
        if not value:raise AssertionError(name)
    def send(kind,**payload):
        window._handle_event(PipelineEvent(kind=kind,timestamp='',job_id='parallel-progress-audit',payload=payload))
    def reset():
        window._reset_progress_presentation();window._active_job_id='parallel-progress-audit';window._recognition_terminal=''
        window._completed_stages={1,3};window._skipped_stages=set();window._failed_stages=set()
        window._active_stages={2:dict(label='在线 ASR API 主力转写（MOSS Pro 云端）',resource='网络 API',started=time.perf_counter()-50)}
        window._stage_total=11;window._current_media_total=window._current_media_index=1
        window.started_at=time.perf_counter()-60;window.pages.setCurrentIndex(1)
    def capture(name):
        if not window.grab().save(str(output/name)):raise RuntimeError('Window capture failed')
    def finish():
        save();window._recognition_terminal='success';window._active_job_id=''
        window.close();QTimer.singleShot(300,QApplication.instance().quit)
    def guarded(function):
        def run():
            try:function()
            except BaseException:
                result.update(passed=False,error=traceback.format_exc());finish()
        return run
    def tail():
        reset();window._active_stages={};window._completed_stages=set(range(1,11))
        send('pipeline_work_progress',work_id='media:final-word-alignment',label='日语最终字级对齐',state='running',done=5970,total=6963)
        send('alignment_progress',engine='MFA-ALIGNER',label='MFA 切点复核',worker_pid=12345,worker_state='progress',
             done=400,total=834,range_start_ms=120000,range_end_ms=150000)
        window._refresh_progress_cards();window._progress_motion.setCurrentTime(window._progress_motion.duration())
        title=window.progress_stage.text();details=window.active_tasks_label.text()
        check('tail names actual model', 'MFA' in title and '下一步' not in title,title=title)
        check('actual completed counts and range','400/834' in details and '02:00' in details and '02:30' in details,details=details)
        check('unsaved work stays below 100 percent',window.progress_percent.text()!='100%')
        capture('tail.png')
        send('ready_shard_queued',shard_id='r001',input_version='v2')
        send('pipeline_work_progress',work_id='old',shard_id='r001',input_version='v1',label='旧结果不应出现',state='running')
        window._refresh_progress_cards()
        check('stale input version rejected','旧结果不应出现' not in window.active_tasks_label.text())
        from ..system import task_resources
        old=task_resources._LIVE_VALUE
        try:
            task_resources._LIVE_VALUE=task_resources.task_budget(dict(available_bytes=24*1024**3,total_bytes=64*1024**3,
                process_tree_rss_bytes=8*1024**3,foreground=False))
            from ..storage.runtime_cache import RuntimeCacheManager
            budget=[50];cache=RuntimeCacheManager(memory_budget_provider=lambda:budget[0])
            for number in range(5):cache.put_memory(str(number),number,size_bytes=10)
            check('high budget retains useful results',cache.snapshot()['memory_entries']==5)
            budget[0]=20;cache.get_memory('4')
            check('pressure reclaims only rebuildable cache',cache.snapshot()['memory_entries']==2)
        finally:task_resources._LIVE_VALUE=old
        from ..diagnostics.build_identity import load_build_identity
        from dataclasses import asdict
        result.update(passed=True,build_identity=asdict(load_build_identity()))
        QTimer.singleShot(200,finish)
    def parallel():
        reset()
        send('ready_shard_queued',shard_id='r001',input_version='v1')
        send('pipeline_work_progress',work_id='r001:polished',shard_id='r001',input_version='v1',
             label='第 1/16 片 · 校对',state='running',done=3,total=9)
        send('mosi_scheduler',request_total=16,uploading=2,polling=4,queued=8)
        send('asr_progress',backend='mosi_moss_pro',completed_batches=4,total_batches=16)
        send('long_pipeline_progress',completed=18,total=96,shards=16,phase='polished',request_index=0)
        window._refresh_progress_cards();window._progress_motion.setCurrentTime(window._progress_motion.duration())
        details=window.active_tasks_label.text()
        check('concurrent stages visible',all(value in details for value in ('MOSS','4/16','校对','断句','翻译')),details=details)
        check('parallel title fits card',window.progress_stage.text()=='分片并行处理中',title=window.progress_stage.text())
        check('polish phase reflects concurrent shard work',window.phase_cards[1]._state=='active'
              and window.phase_cards[1].steps==(1,16))
        send('subtitle_translation_progress',shard_id='r001',input_version='v1',done=40,total=40)
        window._refresh_progress_cards()
        check('translation completion visible before acoustic finish','翻译 1/16' in window.active_tasks_label.text())
        send('long_pipeline_progress',completed=19,total=96,shards=16,phase='translation',request_index=0)
        window._refresh_progress_cards()
        check('translation node not counted twice','翻译 1/16' in window.active_tasks_label.text())
        def settled():
            check('parallel headline has a full text line',window.progress_stage.height()>=window.progress_stage.fontMetrics().height(),
                  height=window.progress_stage.height(),font_height=window.progress_stage.fontMetrics().height())
            capture('parallel.png');QTimer.singleShot(200,guarded(tail))
            send('ready_shard_queued',shard_id='r001',input_version='v2')
            check('new input reopens only its phase counters',
                  'r001' not in window._parallel_phase_nodes.get('translation',set()))
        QTimer.singleShot(200,guarded(settled))
    def shutdown():result['gui_shutdown']=True;save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    QTimer.singleShot(500,guarded(parallel))
