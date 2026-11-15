"""Exercise the real Studio task dialog from the ordinary MainWindow entry."""
from pathlib import Path
import json,os,time,traceback

def start(window,output):
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtWidgets import QApplication,QPushButton
    from PySide6.QtTest import QTest
    def run():
        app=QApplication.instance();checks=[];page=None
        def settle(seconds=.15):
            until=time.monotonic()+seconds
            while time.monotonic()<until:app.processEvents();time.sleep(.005)
        def wait(test):
            until=time.monotonic()+35
            while not test() and time.monotonic()<until:settle(.03)
            if not test():raise TimeoutError('Studio did not become ready')
        def check(name,ok,detail=None):
            checks.append(dict(name=name,passed=bool(ok),detail=detail))
            if not ok:raise AssertionError(name+': '+str(detail))
        def click(button):QTest.mouseClick(button,Qt.LeftButton);settle()
        try:
            from twobyteasr.design.theme_manager import save_theme_key,apply_theme
            theme=os.environ.get('TWOBYTEASR_CANDY_THEME','sand');save_theme_key(theme);apply_theme(theme,app)
            window.resize(1440,900);window.open_studio_project(str(output/'fixture.2byteproj'))
            wait(lambda:window.built_page('studio') is not None and window.built_page('studio').project is not None)
            page=window.built_page('studio')
            wait(lambda:getattr(window,'_studio_loading_session',None) is None or not window._studio_loading_session.active)
            wait(lambda:getattr(page.video,'_startup_state','')=='READY')
            page.video.set_paused(True)
            cues=page.project.cues
            task=page._new_subtitle_task('AI 断句',cues[:8])
            statuses=['applied','unchanged','suggestion','review','failed','cancelled','running']
            for i,status in enumerate(statuses):
                task.update(dict(range_id=cues[i].id,cue_ids=[cues[i].id],source_rows=[i+1],start_ms=cues[i].start_ms,
                    end_ms=cues[i].end_ms,status=status,phase='等待模型返回' if status=='running' else '',
                    error='离线验收：保留原文' if status in ('review','failed') else '',
                    input_text=cues[i].text,validated_texts=[cues[i].text] if status=='applied' else [],
                    final_texts=[cues[i].text],attempts=i%2+1))
            click(page.subtitle_tasks_button);panel=page._subtitle_task_panel();settle(.4)
            check('normal Studio task toolbar opens nonmodal dialog',panel.isVisible() and not panel.isModal())
            from .candy_prompt_audit import check_chrome
            check_chrome(panel, check, settle)
            panel.resize(1100,780);panel.refresh(force=True);settle()
            check('original IDs stay the denominator',panel.fraction.text()=='5/8 条原字幕',panel.fraction.text())
            buttons=lambda name:[b for b in panel.findChildren(QPushButton,name) if b.isVisible()]
            chip=lambda prefix:next(b for b in buttons('taskChip') if b.text().startswith(prefix))
            check('all outcomes plus active are visible',len(buttons('taskChip'))==9,[b.text() for b in buttons('taskChip')])
            panel.grab().save(str(output/'01-running-all.png'))
            click(chip('失败，保留原文'))
            visible=lambda:[k for k,i in panel._row_indexes.items() if not panel.table.isRowHidden(i)]
            check('failure candy filters the actual rows',visible()==[cues[4].id],visible())
            click(chip('全部'))
            cause=buttons('taskCauseFilter')[0];click(cause)
            check('shared cause filter reaches two rows',len(visible())==2,visible())
            click(cause);check('shared cause filter clears',len(visible())==7)
            def select(i):
                idx=panel.table_model.index(panel._row_indexes[cues[i].id],0)
                panel.table.scrollTo(idx);settle()
                QTest.mouseClick(panel.table.viewport(),Qt.LeftButton,pos=panel.table.visualRect(idx).center());settle()
            select(4)
            check('running retry is explained',not panel.retry_button.isEnabled() and '任务结束后' in panel.retry_why.text())
            check('failed text retained in comparison',panel.final_card.title.text()=='实际写回 · 保留原文')
            click(panel.raw_toggle)
            check('raw record is reachable',panel.detail.currentIndex()==2 and json.loads(panel.details.toPlainText())['status']=='failed')
            back=next(b for b in panel.findChildren(QPushButton,'taskRawToggle') if b.text().startswith('‹'))
            click(back);check('comparison returns',panel.detail.currentIndex()==1)
            select(0);check('successful result comparison',panel.next_lead.text()=='搞定')
            select(4);located=[];panel.locate.connect(located.append);click(panel.locate_button)
            check('locate signal retains selected original ID',located[-1]['record']['cue_ids']==[cues[4].id])
            cancelled=[];panel.cancel.connect(cancelled.append);click(panel.cancel_button)
            check('cancel reaches actual task lifecycle',cancelled==[task.task_id] and task.cancelled)
            task.finish(cancelled=True);panel.refresh(force=True);settle()
            check('terminal dialog closes and cannot cancel again',panel.collapse_button.text()=='关闭' and not panel.cancel_button.isEnabled())
            select(4);retried=[]
            panel.retry.disconnect();panel.retry.connect(retried.append);click(panel.retry_button)
            check('retry sends only selected failure',retried[-1]['record']['cue_ids']==[cues[4].id])
            task.alignment_progress=dict(done=5,total=6,cached=3,local=2)
            panel.refresh(force=True)
            check('latest Ultra counters remain visible',all(x in panel.phase.text() for x in ('窗口 5/6','缓存 3','局部重算 2')),panel.phase.text())
            panel.grab().save(str(output/'02-complete-details.png'))
            for i in range(5):
                extra=page._new_subtitle_task('历史任务 '+str(i+1),cues[:1]);extra.finish();panel.refresh(force=True)
            check('older tasks go into an accessible menu',panel.more_tasks.isVisible() and len(panel.more_tasks.menu().actions())==2)
            panel.more_tasks.menu().actions()[-1].trigger();panel.refresh(force=True);settle()
            check('older task selection restores original rows',panel.current is task and panel.table_model.rowCount()==8)
            for width,height in ((1100,780),(760,560)):
                margin=panel.chrome.window.margin()
                panel.resize(width+2*margin,height+2*margin);settle(.25)
                relevant=buttons('taskChip')+[panel.collapse_button,panel.cancel_button,panel.retry_button]
                outside=[b.text() for b in relevant if not panel.rect().contains(b.mapTo(panel,b.rect().topLeft())) or
                    not panel.rect().contains(b.mapTo(panel,b.rect().bottomRight()))]
                check('controls fit at '+str(width),panel.chrome.root.width()==width and not outside,dict(content=panel.chrome.root.width(),outer=panel.width(),outside=outside))
                panel.grab().save(str(output/('03-width-'+str(width)+'.png')))
            click(panel.collapse_button);check('close keeps the project available',not panel.isVisible() and page.project is not None)
            click(page.subtitle_tasks_button);check('reopen preserves finished history',panel.isVisible() and panel.current is task)
            panel.hide();page.undo_stack.setClean()
            result=dict(passed=True,checks=checks,checks_passed=len(checks),theme=theme)
            code=0
        except Exception:
            result=dict(passed=False,checks=checks,error=traceback.format_exc());code=1
            for w in app.topLevelWidgets():
                if w.isVisible():w.grab().save(str(output/('failure-'+w.metaObject().className()+'.png')))
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        if page is not None:page.undo_stack.setClean()
        app.exit(code)
    QTimer.singleShot(600,run)
