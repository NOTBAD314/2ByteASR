"""Opt-in tutorial acceptance through the normal production MainWindow."""
import json, os, time
from pathlib import Path


def run(window, output, check):
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    from ..app import onboarding, newbie_tasks, tutorial_chapters
    from ..app.home_tour import GuidedTour, TourStep
    from ..app.tutorial_centre import TutorialCentre
    from ..design.theme_manager import apply_theme
    from ..i18n import save_language as set_language
    app=QApplication.instance(); output=Path(output)
    records=[]
    def settle(seconds=.12):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            app.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);time.sleep(.005)
    def until(predicate, seconds=45):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if predicate():return
            app.processEvents();time.sleep(.005)
        raise TimeoutError('tutorial audit wait')
    def active():
        return next((t for t in window.findChildren(GuidedTour) if t.mode!='closed'),None)
    def shot(widget,name):
        if isinstance(widget,GuidedTour) and widget.bubble.isVisible():
            until(lambda:not widget._typer.running,12)
        check('screenshot '+name,widget.grab().save(str(output/(name+'.png'))))
    # All files and settings belong to the launcher's isolated acceptance profile.
    state=onboarding.load_state();onboarding.save_state(dict(state,chapters_done=[],tasks_done=[]))
    window._first_run_downloads=None;window._tutorial_plan_chosen=True
    for theme in ('sand','midnight'):
        apply_theme(theme,app);set_language('zh');settle(.35)
        centre=TutorialCentre(window);centre.resize(1100,760);centre.show();settle(.3)
        check('eleven available chapters '+theme,len(centre.rows)==11 and not any(c.soon for c in tutorial_chapters.CATALOG))
        if os.environ.get('TWOBYTEASR_TUTORIAL_LEARNING_PATH_AUDIT') == '1':
            from ..app.tutorial_centre import recommended
            keys = [chapter.id for chapter in tutorial_chapters.CATALOG]
            check('numbered learning path ' + theme,
                  [key for _node, key in centre.path.nodes] == keys
                  and [centre.nodes[key].text() for key in keys] == [str(i) for i in range(1, 12)])
            check('recommended chapter highlighted ' + theme,
                  centre.path.next_up == recommended(set()) == centre.pick
                  and centre.nodes[centre.pick].property('picked'))
            until(lambda: centre.windowOpacity() >= .99)
            QTest.mouseClick(centre.rows[keys[1]], Qt.LeftButton)
            check('actual chapter click updates path and preview ' + theme,
                  centre.pick == centre.path.picked == keys[1]
                  and centre.nodes[keys[1]].property('picked')
                  and '1.</span>' in centre.preview_learn.text())
            if os.environ.get('TWOBYTEASR_ROUND_REGION') == '1':
                check('native Windows rounded tutorial ' + theme, _has_rounded_region(centre))
        for key in centre.rows:
            centre.select(key);settle(.02)
            check('chapter selectable '+theme+' '+key,centre.start_button.isEnabled() and centre.pick==key)
        centre.select('render');shot(centre,'centre-'+theme)
        centre.show_tab('tasks');settle(.15)
        check('thirteen tasks '+theme,len(centre.task_cards)==13)
        shot(centre,'tasks-'+theme)
        centre.reject();until(lambda:not centre.isVisible());centre.deleteLater();settle()
    set_language('en');centre=TutorialCentre(window);centre.resize(1100,760);centre.show();settle(.2)
    centre.select('render');settle(.2);shot(centre,'centre-english');centre.reject();until(lambda:not centre.isVisible());centre.deleteLater();set_language('zh');settle()
    # A missing step returns the window; the real escape route works for required teaching.
    t=GuidedTour(window,[TourStep('等待一张不会出现的页面',lambda:None,ready=lambda:False)])
    t.set_required(True);t.start();until(lambda:t.mode=='away',8)
    check('missing page releases shaded window',t._stuck and t.chip_end.isVisible() and t.chip_next.isVisible() and not t.bubble.isVisible())
    shot(window,'missing-page-released');t.chip_end.click();settle()
    check('required stuck tutorial can end',t.mode=='closed' and GuidedTour.live==0)
    t=GuidedTour(window,[TourStep('Esc可以退出')])
    t.set_required(True);t.start();until(lambda:t.mode=='shown')
    QApplication.setActiveWindow(window);window.setFocus();QTest.keyClick(window,Qt.Key_Escape);settle()
    check('required visible tutorial Escape exits',t.mode=='closed' and GuidedTour.live==0)
    def dismiss_completed_centre():
        for centre in window.findChildren(TutorialCentre):
            if centre.isVisible():
                shot(centre,'after-first-centre');centre.reject()
    centre_watcher=QTimer(window);centre_watcher.timeout.connect(dismiss_completed_centre);centre_watcher.start(80)
    def observe():
        page=window.built_page('studio');editor=getattr(page,'subtitle_edit_input',None);draft=getattr(page,'_caption_draft',None)
        current=active()
        state=dict(mode=getattr(current,'mode',None),index=getattr(current,'index',None),
            windows=[dict(type=type(w).__name__,title=w.windowTitle(),name=w.objectName()) for w in app.topLevelWidgets() if w.isVisible()],
            cue_ids=[c.id for c in getattr(getattr(page,'project',None),'cues',())],text=editor.toPlainText() if editor else None,
            cursor=editor.textCursor().position() if editor else None,draft_id=getattr(getattr(draft,'target',None),'cue_id',None))
        if current is not None:
            target=current._raw_target(current.index);widget=target[0] if isinstance(target,tuple) else target
            state.update(stuck=current._stuck,ready=current._is_ready(current.index),covered=current._covered(current.index),
                target_type=type(widget).__name__,target_visible=widget.isVisible() if widget is not None else None,
                project_path=str(getattr(page,'project_path','')),current_page=type(window.pages.currentWidget()).__name__)
            if widget is not None:
                point=target[1].center().toPoint() if isinstance(target,tuple) else widget.rect().center()
                top=widget.window();hit=top.childAt(top.mapFromGlobal(widget.mapToGlobal(point)))
                state.update(target_rect=str(target[1] if isinstance(target,tuple) else widget.rect()),hit_type=type(hit).__name__,hit_name=hit.objectName() if hit else None)
            if os.environ.get('TWOBYTEASR_TUTORIAL_DEBUG')=='1':
                window.grab().save(str(output/'tutorial-current-window.png'))
                current.grab().save(str(output/'tutorial-current-overlay.png'))
        (output/'tutorial-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),'utf8')
    observer=QTimer(window);observer.timeout.connect(observe);observer.start(1000)
    for chapter in tutorial_chapters.CATALOG:
        key=chapter.id
        if os.environ.get('TWOBYTEASR_TUTORIAL_ONLY') and key!=os.environ['TWOBYTEASR_TUTORIAL_ONLY']:continue
        if key=='first':
            # Completion opens the real centre asynchronously; dismiss it after capturing it.
            pass
        window._start_home_tour(key);until(lambda:active() is not None)
        tour=active();tour.voice.set_muted(True) if hasattr(tour.voice,'set_muted') else None
        seen=set();actions=set();deadline=time.monotonic()+200
        while tour.mode!='closed' and time.monotonic()<deadline:
            app.processEvents();time.sleep(.008)
            if tour.mode=='away' and getattr(tour,'_stuck',False):
                step=tour._step()
                if step.optional:
                    records.append(dict(chapter=key,index=tour.index,optional_unavailable=True));tour.chip_next.click();continue
                raise AssertionError(f'{key} step {tour.index}: page did not appear')
            if tour.mode!='shown' or not tour.bubble.isVisible() or not tour.skip.isVisible():continue
            index=tour.index;step=tour._step()
            if index not in seen:
                seen.add(index);records.append(dict(chapter=key,index=index,text=tour._text_source))
                (output/'tutorial-steps.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),'utf8')
                if index in (0,len(tour.steps)//2,len(tour.steps)-1):
                    shot(window,f'chapter-{key}-{index:02}-target');shot(tour,f'chapter-{key}-{index:02}')
                check(f'chapter {key} step {index} bubble',tour.bubble.isVisible() and tour.skip.isVisible())
                check(f'chapter {key} practice excluded {index}',not newbie_tasks.mark('cut'))
            if step.show_next:
                QTest.mouseClick(tour.next,Qt.LeftButton);settle(.05)
            elif index not in actions and tour.action_buttons:
                actions.add(index);settle(.25)
                button=next((b for b in tour.action_buttons if any(label in b.text() for label in ('先不设置','先不开','先跳过'))),tour.action_buttons[0])
                QTest.mouseClick(button,Qt.LeftButton);settle(.15)
                page=window.built_page('studio');editor=getattr(page,'subtitle_edit_input',None);draft=getattr(page,'_caption_draft',None)
                records.append(dict(chapter=key,action=index,cue_ids=[c.id for c in getattr(getattr(page,'project',None),'cues',())],
                    text=editor.toPlainText() if editor is not None else None,cursor=editor.textCursor().position() if editor is not None else None,
                    draft_id=getattr(getattr(draft,'target',None),'cue_id',None),split_status=getattr(getattr(page,'subtitle_edit_card',None),'split_status',None).text() if getattr(page,'subtitle_edit_card',None) is not None else None))
                (output/'tutorial-steps.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),'utf8')
        check('chapter finished '+key,tour.mode=='closed')
        check('chapter completion recorded '+key,key in onboarding.load_state().get('chapters_done',[]))
        check('tutorial live count released '+key,GuidedTour.live==0)
        settle(.9)
        for centre in window.findChildren(TutorialCentre):
            if centre.isVisible():shot(centre,'after-first-centre');centre.reject()
        settle()
    centre_watcher.stop();centre_watcher.deleteLater()
    observer.stop();observer.deleteLater()
    expected={os.environ['TWOBYTEASR_TUTORIAL_ONLY']} if os.environ.get('TWOBYTEASR_TUTORIAL_ONLY') else set(tutorial_chapters.BY_ID)
    check('requested chapter completions persisted',set(onboarding.load_state().get('chapters_done',[]))==expected)
    check('practice did not tick tasks',onboarding.load_state().get('tasks_done',[])==[])
    check('throwaway glossary removed','_tutorial_terms_library' not in window.__dict__)
    check('demo chat removed','_tutorial_bunny' not in window.__dict__)
    check('real action records once',newbie_tasks.mark('review') and not newbie_tasks.mark('review'))
    centre=TutorialCentre(window,tab='tasks');centre.resize(1100,760);centre.show();settle(.2)
    check('task progress reloads',centre.tasks_done=={'review'})
    shot(centre,'tasks-completed');centre.reject();until(lambda:not centre.isVisible());centre.deleteLater()
    (output/'tutorial-steps.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),'utf8')


def _has_rounded_region(widget):
    """Check the actual Windows window shape when the Windows 10 fallback is forced."""
    import ctypes
    from ctypes import wintypes

    user = ctypes.windll.user32
    gdi = ctypes.windll.gdi32
    gdi.CreateRectRgn.restype = wintypes.HRGN
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.PtInRegion.argtypes = [wintypes.HRGN, ctypes.c_int, ctypes.c_int]
    user.GetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN]
    region = gdi.CreateRectRgn(0, 0, 0, 0)
    if not region:
        return False
    try:
        return (user.GetWindowRgn(widget.winId(), region) > 0
                and not gdi.PtInRegion(region, 0, 0)
                and bool(gdi.PtInRegion(region, 40, 40)))
    finally:
        gdi.DeleteObject(region)
