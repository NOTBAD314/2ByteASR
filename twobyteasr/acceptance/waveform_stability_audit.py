"""Normal-window regression for a completed audio tail in a longer timeline."""
import json
import os
from pathlib import Path
import time
import traceback


def start(window,output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QScrollBar
    from PySide6.QtTest import QTest
    app=QApplication.instance()
    result=dict(passed=False,checks={},scope='normal MainWindow, paused viewport over real decoded audio EOF')
    def receipt():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,value):
        result['checks'][name]=bool(value);receipt()
        if not value:raise AssertionError(name)
    def wait(predicate,timeout=90):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if predicate():return
            app.processEvents();time.sleep(.005)
        raise TimeoutError('waveform audit wait')
    def run():
        page=window.studio_page
        try:
            window._switch_page(page)
            page.open_project(os.environ['EDIT_SAVE_PROJECT'],skip_dirty_guard=True)
            wait(lambda:page.project is not None and page._readiness.ready)
            page.video.set_paused(True)
            timeline=page.timeline
            wait(lambda:timeline.cache is not None and not page._waveform_inflight
                 and not timeline.cache.metadata.incomplete and not timeline.cache.root.name.endswith('coarse-v1'))
            cache=timeline.cache
            result['cache']=cache.metadata.to_dict()
            result['project_duration_ms']=page.project.media.duration_ms
            check('audio EOF is shorter than timeline',cache.metadata.duration_ms<page.project.media.duration_ms)
            timeline.visible_start_ms=140000
            timeline.visible_duration_ms=300000
            timeline._manual_view_hold=True
            timeline._sync_scrollbars()
            scroll=timeline.findChild(QScrollBar,'timelineTrackScroll')
            if scroll is not None:scroll.setValue(scroll.maximum())
            timeline.update()
            def current_keys(mapping):
                return [key for key in mapping if key[0] is cache]
            wait(lambda:current_keys(getattr(timeline,'_waveform_tile_cache',{}))
                 or current_keys(getattr(timeline,'_waveform_partial_tiles',{})))
            QTest.qWait(1800)
            worker=timeline._waveform_tile_worker
            before=worker.serial
            frames=[]
            for index in range(100):
                timeline.update();QTest.qWait(20)
                frames.append(dict(serial=worker.serial,
                    complete=len(current_keys(getattr(timeline,'_waveform_tile_cache',{}))),
                    partial=len(current_keys(getattr(timeline,'_waveform_partial_tiles',{})))))
            result.update(serial_before=before,serial_after=worker.serial,frames=frames)
            timeline.grab().save(str(output/'waveform-stable.png'))
            check('completed source has terminal cached tiles',frames[-1]['complete']>0)
            check('completed source has no partial retry loop',frames[-1]['partial']==0)
            check('paused viewport does not resubmit tile work',frames[-1]['serial']==frames[0]['serial'])
            check('waveform is ready',timeline.waveform_state=='READY')
            result['passed']=all(result['checks'].values())
        except Exception:
            result['error']=traceback.format_exc()
        finally:
            receipt()
            page.undo_stack.setClean();page.project_dirty=False
            window.close()
    app.aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),receipt()))
    QTimer.singleShot(1200,run)
