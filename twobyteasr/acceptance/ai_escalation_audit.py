"""Opt-in normal Windows entry: thinking retry settings, feed and task result."""
import copy,json,time,traceback

def start(window, output):
    from PySide6.QtCore import QTimer
    QTimer.singleShot(500, lambda: run(window, output))

def run(window, output):
    from PySide6.QtCore import Qt,QTimer,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout,QScrollArea,QLabel
    from ..design.theme_manager import apply_theme
    from ..providers.endpoint_editor_ui import EndpointEditor
    from ..storage.settings import DEFAULT_SETTINGS
    from ..recognition.service import PipelineEvent
    app=QApplication.instance();result=dict(passed=False,checks=[]);page=None;dialog=None
    def settle(seconds=.15):
        end=time.monotonic()+seconds
        while time.monotonic()<end:app.processEvents();time.sleep(.005)
    def check(name, condition):
        result['checks'].append(dict(name=name,passed=bool(condition)))
        if not condition:raise AssertionError(name)
    def wait(test):
        end=time.monotonic()+45
        while not test() and time.monotonic()<end:settle(.05)
        check('normal entry ready',test())
    try:
        window.resize(1420,940)
        for theme in ('sand','midnight'):
            apply_theme(theme,app)
            settings=copy.deepcopy(DEFAULT_SETTINGS)
            for stage in ('group','polish'):
                dialog=QDialog(window);dialog.setWindowTitle('AI高级设置 · '+stage)
                layout=QVBoxLayout(dialog);scroll=QScrollArea();scroll.setWidgetResizable(True)
                editor=EndpointEditor('断句模型' if stage=='group' else '字幕校对模型','#5378cb',stage,settings)
                scroll.setWidget(editor);layout.addWidget(scroll);dialog.resize(780,640);dialog.show()
                QTest.mouseClick(editor.advanced_toggle,Qt.LeftButton);settle()
                scroll.ensureWidgetVisible(editor.escalate_on_failure);settle()
                box=editor.escalate_on_failure
                check(theme+' '+stage+' checkbox reachable',box.isVisible() and box.isEnabled()
                      and scroll.viewport().rect().contains(box.mapTo(scroll.viewport(),box.rect().center())))
                check('default enabled and fee explained',box.isChecked() and '费用' in box.toolTip())
                QTest.mouseClick(box,Qt.LeftButton,pos=QPoint(9,box.height()//2));settle()
                values=editor.values();check('unchecked saved',values['escalate_on_failure'] is False)
                editor.restore_profile_values(values,settings);check('restore preserves off',not box.isChecked())
                QTest.mouseClick(box,Qt.LeftButton,pos=QPoint(9,box.height()//2));check('reenabled saved',editor.values()['escalate_on_failure'] is True)
                dialog.grab().save(str(output/(theme+'-'+stage+'-settings.png')))
                dialog.close();dialog=None
        window.open_studio_project(str(output/'p12/project.2byteproj'))
        wait(lambda:window.built_page('studio') is not None and window.built_page('studio').project is not None)
        page=window.built_page('studio')
        wait(lambda:getattr(window,'_studio_loading_session',None) is None or not window._studio_loading_session.active)
        page.video.set_paused(True)
        task=page._new_subtitle_task('AI补救检查',())
        task.update(dict(range_id='source',range_label='当前视频',status='running',input_text='保留原始字幕'))
        page._recognition_subtitle_task=task
        page._record_recognition_task_event('grouping_api_fallback',dict(batch_index=1,error='格式失败'))
        page._record_recognition_task_event('stage_failed',dict(stage='translation',error='独立翻译失败'))
        done=dict(stage='grouped',state='completed',thinking='high',candidate_cues=4,succeeded_cues=4,
                  failed_cues=0,resolved_batches=[1],remaining_fallback_batches=0)
        page._record_recognition_task_event('ai_escalation_round',done)
        row=task.rows['source']
        check('rescued grouping removed and independent error retained',not row['local_fallback']
              and [x['event'] for x in row['issues']]==['stage_failed'] and bool(row['error']))
        task.update(dict(range_id='source',status='review'))
        QTest.mouseClick(page.subtitle_tasks_button,Qt.LeftButton);settle(.4)
        panel=page._subtitle_task_panel();panel.refresh(force=True);settle()
        index=panel.table_model.index(panel._row_indexes['source'],0)
        panel.table.setCurrentIndex(index);panel._show_details();settle()
        check('task shows readable retry outcome','提高思考等级重试（high）' in panel.next_text.text()
              and '救回 4 条' in panel.next_text.text())
        panel.grab().save(str(output/'task-retry-outcome.png'));panel.hide()
        window.pages.setCurrentIndex(1)
        settle(.4)
        for stage in ('grouped','polished'):
            for state in ('started','completed'):
                payload=dict(done,stage=stage,state=state)
                window._handle_event(PipelineEvent('ai_escalation_round','',payload=payload))
        cards=[window.event_log.itemWidget(window.event_log.item(i)) for i in range(window.event_log.count())]
        text=' '.join(label.text() for card in cards for label in card.findChildren(QLabel))
        check('feed contains start and both results','提高思考' in text and '救回' in text and '校对' in text and '断句' in text)
        check('fully rescued grouping clears degraded badge',2 not in window._phase_degraded)
        check('feed is visible at readable width',window.event_log.isVisible() and window.event_log.width()>350)
        settle(.6)
        window.grab().save(str(output/'retry-feed.png'))
        result['passed']=True
    except Exception:result['error']=traceback.format_exc()
    finally:
        if dialog:dialog.close()
        if page:
            task=getattr(page,'_recognition_subtitle_task',None)
            if task and task.ended is None:task.finish()
            page.undo_stack.setClean()
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        window.close();QTimer.singleShot(500,app.quit)
