"""Normal-entry checks for the merged home entry and language-recovery bar."""
from pathlib import Path
import json,os,sys,time,traceback


def start(window, output):
    from PySide6.QtCore import QPoint,QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    from ..design.theme_manager import apply_theme
    from ..test_isolation import require_isolated_paths
    require_isolated_paths('ui-daily-merge')
    output=Path(output); mode=os.environ['TWOBYTEASR_UI_MERGE_AUDIT']
    result=dict(mode=mode,passed=False,checks=[],identity=load_build_identity().to_dict(),pid=os.getpid(),executable=sys.executable)

    def write():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

    def check(name,ok,detail=None):
        result['checks'].append(dict(name=name,passed=bool(ok),detail=detail));write()
        if not ok:
            _capture(window,output/'failure.png')
            raise AssertionError(name)

    def wait_for(predicate,label):
        for _ in range(150):
            if predicate():return
            yield .1
        raise TimeoutError(label)

    def flow():
        window.showNormal()
        if mode=='home':
            window.resize(2000,1087)
            window._switch_page(0)
            yield .6
            controller=QApplication.instance()._ui_zoom_controller
            for theme in ('warm','grape'):
                apply_theme(theme)
                for zoom in (100,120):
                    window._switch_page(0)
                    yield .6
                    controller.request(zoom)
                    yield 1.
                    scroll=window.settings_scroll
                    scroll.verticalScrollBar().setValue(0)
                    yield .2
                    button=window.studio_entry_open
                    point=button.mapTo(scroll.viewport(),QPoint())
                    rect=button.rect().translated(point)
                    check(f'{theme} {zoom}: home Studio entry fits first viewport',button.isVisible()
                          and scroll.viewport().rect().contains(rect),dict(rect=rect.getRect(),viewport=scroll.viewport().size().toTuple()))
                    check(f'{theme} {zoom}: entry is in card header',button.mapTo(window.studio_entry_card,QPoint()).y()
                          < window.studio_recent_hero.y(),button.geometry().getRect())
                    _capture(window,output/f'home-{theme}-{zoom}.png')
                    QTest.mouseClick(button,Qt.MouseButton.LeftButton)
                    yield from wait_for(lambda: window.built_page('studio') is not None
                                        and window.pages.currentWidget() is window.built_page('studio'),'home Studio navigation')
                    check(f'{theme} {zoom}: real entry opens Studio',window.pages.currentWidget() is window.built_page('studio'))
                    yield 1.
        elif mode=='language':
            from ..projects.studio_project import load_project,save_project
            from ..recognition.service import MediaResult,QueueResult,RunOptions
            from ..recognition.transcript_acceptance import KEY
            project_path=output/'busy.2byteproj'
            project=load_project(project_path)
            project.generation_metadata[KEY]=dict(version=1,ranges=[dict(id='pending-language',start=0.,end=3.,
                start_sample=0,end_sample=48000,status='pending',requested_language='en',transcript_language='it',attempts=[])])
            save_project(project,project_path)
            window.resize(1460,1000)
            window._last_run_options=RunOptions()
            window._handle_result(QueueResult((MediaResult(str(output/'busy.mp4'),'success',project_path=str(project_path),
                report_json_path=str(output/'busy.json')),),1.))
            window._switch_page(2)
            for _ in range(15):
                for widget in QApplication.topLevelWidgets():
                    if type(widget).__name__=='CompletionDialog' and widget.isVisible():widget.accept()
                yield .1
            todo=window.result_todo
            check('language pending uses the new bar action',todo.retry_card.isVisible()
                  and window.retry_failed_button is todo.retry_card.action
                  and window.retry_failed_button.text()=='仅恢复语言异常范围…')
            window.pages.widget(2).ensureWidgetVisible(window.retry_failed_button)
            _capture(window,output/'language-pending-bar.png')
            QTest.mouseClick(window.retry_failed_button,Qt.MouseButton.LeftButton)
            def sheet_ready():
                page=window.built_page('studio')
                sheet=getattr(page,'_recognition_sheet',None) if page is not None else None
                return sheet is not None and sheet.isVisible()
            yield from wait_for(sheet_ready,'real language recovery sheet')
            # Allow the modal reveal and the newly opened Studio's background
            # ownership to settle before capturing and closing this short QA.
            yield 2.
            page=window.built_page('studio'); controls=page._recognition_controls
            check('bar click opens real Studio range sheet',window.pages.currentWidget() is page
                  and controls['range']['requested']==(0,3000),controls['range'])
            check('recovery keeps local models and disables review',controls['primary'].currentData()=='qwen_local'
                  and controls['timeline'].currentData()=='qwen_aligner' and controls['review'].currentData()=='off',
                  {key:controls[key].currentData() for key in ('primary','timeline','review')})
            check('only the abnormal range is selected',controls['range']['window'][1]<page.project.media.duration_ms,
                  controls['range'])
            check('no recognition started without pressing start',not getattr(page,'_recognition_running',False))
            _capture(window,output/'language-recovery-sheet.png')
            modal=getattr(window,'_modal_host',None)
            if modal is not None:
                modal.hide_content()
                yield 1.
        else:raise ValueError(mode)
        result['passed']=True
        write();window.close()

    steps=flow();state=dict(until=0.,busy=False)
    timer=QTimer(window);timer.setInterval(20)
    def tick():
        if state['busy'] or time.monotonic()<state['until']:return
        state['busy']=True
        try:state['until']=time.monotonic()+next(steps)
        except StopIteration:
            timer.stop();write();QApplication.instance().quit()
        except BaseException:
            result['error']=traceback.format_exc();timer.stop();write();QApplication.instance().quit()
        finally:state['busy']=False
    def stopped():
        result['gui_shutdown']=True;write()
    QApplication.instance().aboutToQuit.connect(stopped)
    timer.timeout.connect(tick);timer.start()
