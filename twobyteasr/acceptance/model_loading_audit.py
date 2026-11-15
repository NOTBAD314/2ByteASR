"""Normal MainWindow model entry timing, native windows and repeated lifecycle."""
import json
import os
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, QObject, QEvent
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.window_lifecycle import WindowLifecycle
    from ..local_models.model_status_cache import registry_metrics
    app=QApplication.instance()
    observer=WindowLifecycle(app,output/'windows.jsonl') if os.environ.get('TWOBYTEASR_WINDOW_TRACE','1')=='1' else None
    recordings=[]
    recording=[None]
    capture=QTimer(window)
    capture.setInterval(40)
    def frame():
        if recording[0] is not None:
            recording[0]['frames'].append((time.perf_counter(),window.grab().toImage()))
    capture.timeout.connect(frame)
    def begin_recording(name):
        if os.environ.get('TWOBYTEASR_MODEL_RECORD')!='1':return
        recording[0]=dict(name=name,frames=[])
        recordings.append(recording[0])
        frame()
        capture.start()
    def end_recording():
        capture.stop()
        frame()
        recording[0]=None
    rows=[]
    checks=[]
    def check(name, condition, detail=None):
        checks.append(dict(name=name,passed=bool(condition),detail=detail))
        if not condition:raise AssertionError(name)
    def settle(duration):
        end=time.perf_counter()+duration
        while time.perf_counter()<end:
            app.processEvents()
            time.sleep(.001)
    class PaintProbe(QObject):
        def __init__(self):
            super().__init__(window)
            self.target=None
            self.started=0
            self.first=None
        def eventFilter(self,obj,event):
            if obj is self.target and event.type()==QEvent.Type.Paint and self.first is None:
                self.first=round((time.perf_counter()-self.started)*1000,3)
            return False
    paint=PaintProbe()
    app.installEventFilter(paint)
    gaps=[]
    last=[time.perf_counter()]
    beat=QTimer(window)
    beat.setInterval(8)
    def heartbeat():
        now=time.perf_counter()
        gaps.append(round((now-last[0])*1000,3))
        last[0]=now
    beat.timeout.connect(heartbeat)
    beat.start()

    def run():
        code=0
        try:
            window._ensure_recognition_page()
            window._return_to_settings()
            settle(.15)
            if os.environ.get('TWOBYTEASR_MODEL_INTERRUPT')=='1':
                window._open_model_picker('primary')
                pending=window._model_picker_primary_panel
                settle(.015)
                window._modal_host._request_close()
                settle(.02)
                window._open_model_picker('primary')
                check('in-flight reopen keeps panel',window._model_picker_primary_panel is pending)
                pending._set_filter('local')
                settle(.015)
                pending._set_filter('all')
                window._modal_host._request_close()
                settle(.02)
                window._open_model_workshop()
                settle(.015)
                window._return_to_settings()
                settle(.02)
            count=int(os.environ.get('TWOBYTEASR_MODEL_CYCLES','20'))
            for cycle in range(count):
                for kind in ('picker','workshop'):
                    if cycle==0:begin_recording(kind+'-cold')
                    gaps.clear()
                    last[0]=time.perf_counter()
                    begin=time.perf_counter()
                    paint.started=begin
                    paint.first=None
                    if kind=='picker':
                        window._open_model_picker('primary')
                        panel=window._model_picker_primary_panel
                        cards=panel.cards
                        scroll=panel.scroll
                        paint.target=panel
                    else:
                        window._open_model_workshop()
                        panel=window.workshop_page
                        cards=panel._cards
                        scroll=panel._card_viewport.scroll
                        paint.target=panel
                    returned=round((time.perf_counter()-begin)*1000,3)
                    samples=[]
                    complete=None
                    deadline=begin+8
                    while time.perf_counter()<deadline:
                        app.processEvents()
                        visible=[c for c in cards.values() if not c.isHidden()]
                        ready=sum(getattr(c,'_card',c) is not None for c in visible)
                        samples.append((round((time.perf_counter()-begin)*1000,3),ready,len(visible)))
                        reveal=getattr(panel,'_card_viewport',None)
                        if reveal is not None and hasattr(reveal,'ready'):
                            done=reveal.ready
                        else:
                            viewport=scroll.viewport()
                            from PySide6.QtCore import QRect,QPoint
                            onscreen=[c for c in visible if QRect(c.mapTo(viewport,QPoint()),c.size()).intersects(viewport.rect())]
                            done=bool(onscreen) and all(getattr(c,'_card',c) is not None for c in onscreen)
                        if done:
                            complete=round((time.perf_counter()-begin)*1000,3)
                            break
                        time.sleep(.001)
                    check(f'{kind} {cycle} complete',complete is not None)
                    if kind=='picker' and cycle==0 and os.environ.get('TWOBYTEASR_MODEL_SINGLE_SLOW')=='1':
                        registry=window.workshop_page._registry
                        check('complete list while one model is unfinished',bool(registry and registry.pending_keys and registry.records))
                    if cycle==0:
                        check(kind+' widgets owned by GUI thread',all(c.thread() is app.thread() for c in cards.values()))
                    for card in cards.values():
                        state=window.workshop_page._model_state(card.model,'primary')
                        if state in {'checking','check_failed'}:
                            check(kind+' pending or failed model cannot be selected',not card.action.isEnabled(),state)
                    settle(.2)
                    if cycle==0:check(kind+' screenshot',window.grab().save(str(output/(kind+'.png'))))
                    if cycle==0:end_recording()
                    rows.append(dict(kind=kind,cycle=cycle,request_return_ms=returned,first_paint_ms=paint.first,
                        complete_ms=complete,gui_max_gap_ms=max(gaps,default=0),samples=samples,
                        card_count=len(cards),realized=sum(getattr(c,'_card',c) is not None for c in cards.values()),
                        detection=registry_metrics(window.workshop_page.root)))
                    if kind=='picker':window._modal_host._request_close()
                    else:window._return_to_settings()
                    settle(.05)
            begin_recording('picker-quick-reopen')
            window._open_model_picker('primary')
            settle(.05)
            window._modal_host._request_close()
            settle(.03)
            window._open_model_picker('primary')
            settle(.4)
            end_recording()
            window._modal_host._request_close()
            check('quick reopen responsive',window.isVisible())
            for role in ('timeline','review'):
                window._open_model_picker(role)
                panel=getattr(window,'_model_picker_'+role+'_panel')
                deadline=time.perf_counter()+8
                while not panel._card_viewport.ready and time.perf_counter()<deadline:
                    settle(.01)
                check(role+' complete card list',panel._card_viewport.ready)
                check(role+' description owned by panel',panel.scope_note.parentWidget() is panel)
                window._modal_host._request_close()
                settle(.03)
            import threading
            check('one shared registry reader',sum(t.name=='shared-model-registry' for t in threading.enumerate())<=1)
            from ..local_models.model_status_cache import _queue
            check('bounded registry queue',_queue.qsize()<=4)
            for screen in app.screens():
                window.showNormal()
                window.windowHandle().setScreen(screen)
                area=screen.availableGeometry()
                window.setGeometry(area.adjusted(20,20,-20,-20))
                settle(.06)
                window.showMaximized()
                settle(.06)
                window.showNormal()
                settle(.06)
                check('screen restore '+screen.name(),window.isVisible() and not window.isMaximized(),
                      dict(scale=screen.devicePixelRatio(),actual_screen=window.screen().name(),
                           actual_scale=window.devicePixelRatioF(),geometry=[area.x(),area.y(),area.width(),area.height()]))
                check('landed on screen '+screen.name(),window.screen().name()==screen.name())
        except Exception:
            code=1
            (output/'error.txt').write_text(traceback.format_exc(),encoding='utf8')
        finally:
            beat.stop()
            end_recording()
            if observer is not None:
                observer.close()
                events=[json.loads(x) for x in (output/'windows.jsonl').read_text('utf8').splitlines()]
                unexpected=[e for e in events if e.get('source')=='qt' and e.get('is_window')
                    and e.get('event')=='Show' and e.get('object_type')!='MainWindow']
                checks.append(dict(name='no additional Qt top-level windows',passed=not unexpected,detail=unexpected))
                if unexpected:code=1
            app.removeEventFilter(paint)
            record_index=[]
            for record in recordings:
                folder=output/record['name']
                folder.mkdir(exist_ok=True)
                index=[]
                first=record['frames'][0][0] if record['frames'] else 0
                for i,(stamp,pixels) in enumerate(record['frames']):
                    name=f'{i:04d}.png'
                    pixels.save(str(folder/name))
                    index.append(dict(file=name,elapsed_ms=round((stamp-first)*1000,3)))
                (folder/'frames.json').write_text(json.dumps(index,indent=2),encoding='utf8')
                record_index.append(dict(name=record['name'],frames=len(index),duration_ms=index[-1]['elapsed_ms'] if index else 0))
            (output/'result.json').write_text(json.dumps(dict(passed=code==0,checks_passed=sum(x['passed'] for x in checks),
                checks=checks,measurements=rows,recordings=record_index,window_trace=observer is not None,
                physical_display_scanout=False),ensure_ascii=False,indent=2),encoding='utf8')
            QTimer.singleShot(0,lambda:app.exit(code))
    QTimer.singleShot(100,run)
