"""Opt-in tutorial acceptance through the normal production MainWindow."""
import json, os, time
from pathlib import Path


def run(window, output, check):
    from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QSize, QTimer, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    from ..app import onboarding, newbie_tasks, tutorial_chapters
    from ..app.help_menu import CuteMenu
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
    def wheel_rows(timeline):
        bar = timeline.vertical_scrollbar
        check('tutorial track rows overflow', bar.maximum() > bar.minimum())
        start = timeline.visible_start_ms
        for name, x, delta, modifiers in (
            ('track names', timeline.TRACK_HEADER_WIDTH // 2, 120, Qt.NoModifier),
            ('time area with Shift', timeline.TRACK_HEADER_WIDTH + 40, -120, Qt.ShiftModifier),
        ):
            local = QPointF(x, timeline._track_viewport().center().y())
            global_pos = QPointF(timeline.mapToGlobal(local.toPoint()))
            previous = bar.value()
            event = QWheelEvent(local, global_pos, QPoint(), QPoint(0, delta),
                                Qt.NoButton, modifiers, Qt.NoScrollPhase, False)
            app.sendEvent(timeline, event)
            check('vertical wheel over ' + name, event.isAccepted()
                  and (previous - bar.value()) * delta > 0
                  and timeline.visible_start_ms == start)
        bar.setValue(bar.minimum())
    # All files and settings belong to the launcher's isolated acceptance profile.
    state=onboarding.load_state();onboarding.save_state(dict(state,chapters_done=[],tasks_done=[]))
    window._first_run_downloads=None;window._tutorial_plan_chosen=True
    set_language('zh')
    entry = {}
    def visit_help():
        centre = next((dialog for dialog in window.findChildren(TutorialCentre) if dialog.isVisible()), None)
        if centre is not None:
            entry['cards'] = len(centre.cards)
            centre.reject()
            entry_timer.stop()
            return
        menu = next((popup for popup in window.findChildren(CuteMenu) if popup.isVisible()), None)
        if menu is None:
            return
        action = next((item for item in menu.actions() if item.text() == '新手教学'), None)
        entry['caption'] = getattr(action, 'caption', '')
        if action is not None:
            action.trigger()
        menu.close()
    entry_timer = QTimer(window)
    entry_timer.timeout.connect(visit_help)
    entry_timer.start(50)
    window.help_button.click()
    check('Help describes the tutorial question cards', entry.get('caption') == '搜索问题，跟着示范练习')
    until(lambda: 'cards' in entry, 10)
    check('Help opens the production tutorial centre', entry['cards'] == 6)
    until(lambda: not any(dialog.isVisible() for dialog in window.findChildren(TutorialCentre)), 5)
    entry_timer.deleteLater()

    original_geometry = window.geometry()
    room = window.screen().availableGeometry().size()
    window.resize(QSize(2190, 1200).boundedTo(room))
    settle(.25)
    wide = TutorialCentre(window)
    wide.show()
    settle(.45)
    bounds = TutorialCentre.open_size(window)
    check('wide tutorial uses the main window width and fits its content',
          wide.width() == bounds.width()
          and wide.minimumHeight() <= wide.height() <= bounds.height())
    card = wide.cards['timeline']
    tallest = max(item.heightForWidth(item.width()) for item in wide.cards.values())
    check('wide question card follows its content height',
          card.height() <= tallest + 2 and not hasattr(card, 'learn_label'))
    if wide._fitted_height(bounds) < bounds.height():
        holder, viewport = wide.scroll.widget(), wide.scroll.viewport()
        check('wide tutorial fits its pills without excess space',
              holder.height() <= viewport.height() + 1
              and viewport.height() - wide._flow.parentWidget().geometry().bottom() <= wide._px(24))
    shot(wide, 'centre-wide')
    wide.search.setText('红线')
    settle(.2)
    check('wide search returns only the compact timeline card',
          [key for key, item in {**wide.cards, **wide.pills}.items() if item.isVisibleTo(wide)] == ['timeline']
          and card.height() <= card.heightForWidth(card.width()) + 2)
    shot(wide, 'centre-wide-search')
    wide.reject()
    until(lambda: not wide.isVisible())
    wide.deleteLater()
    window.setGeometry(original_geometry)
    settle(.25)

    for theme in ('sand','midnight'):
        apply_theme(theme,app);set_language('zh');settle(.35)
        centre=TutorialCentre(window);centre.resize(1100,760);centre.show();settle(.3)
        # 2026-11-27 (draft B 「我想…」): every chapter is one question, six cards and the rest pills.
        keys=[chapter.id for chapter in tutorial_chapters.CATALOG]
        check('every chapter is one question '+theme,sorted([*centre.cards,*centre.pills])==sorted(keys)
              and len(centre.cards)==6 and not any(c.soon for c in tutorial_chapters.CATALOG))
        shot(centre,'centre-'+theme)
        entrance = getattr(centre, '_entrance_motion', None)
        until(lambda: entrance is None or entrance.currentTime() >= entrance.duration(), 5)
        QApplication.setActiveWindow(centre)
        card = centre.cards['timeline']
        QTest.mouseClick(card, Qt.LeftButton, pos=card.rect().center(), delay=50)
        (output/f'card-click-{theme}.json').write_text(json.dumps(dict(
            active=centre.isActiveWindow(), visible=card.isVisible(), enabled=card.isEnabled(),
            selected=centre.pick, detail_visible=centre.detail_page.isVisible(),
            detail_x=centre.detail_page.pos().x())), 'utf8')
        check('actual card click opens its details '+theme,
              centre.detail_page.isVisible() and centre.pick=='timeline')
        until(lambda: centre.detail_page.pos().x()==0, 5)
        check('details slide reaches its final position '+theme,centre.detail_page.pos().x()==0)
        shot(centre,'centre-detail-'+theme);centre.close_detail()
        if os.environ.get('TWOBYTEASR_ROUND_REGION') == '1':
            check('native Windows rounded tutorial ' + theme, _has_rounded_region(centre))
        for key in keys:
            centre.open_detail(key);settle(.02)
            check('chapter opens and can start '+theme+' '+key,centre.start_button.isEnabled() and centre.pick==key)
            centre.close_detail()
        centre.search.setText('红线');settle(.15)
        check('search finds by everyday words '+theme,[k for k,w in {**centre.cards,**centre.pills}.items() if w.isVisibleTo(centre)]==['timeline'])
        shot(centre,'search-'+theme);centre.search.clear()
        centre.reject();until(lambda:not centre.isVisible());centre.deleteLater();settle()
    set_language('en');centre=TutorialCentre(window);centre.resize(1100,760);centre.show();settle(.2)
    shot(centre,'centre-english');centre.open_detail('render');settle(.6);shot(centre,'centre-detail-english')
    centre.reject();until(lambda:not centre.isVisible());centre.deleteLater();set_language('zh');settle()
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
            state.update(stuck=current._stuck,floating=current.floating,ready=current._is_ready(current.index),covered=current._covered(current.index),
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
                if key=='speakers' and index==2 and not tour.floating:
                    manager=window.__dict__.get('_tutorial_speakers')
                    target=tour._raw_target(index)
                    widget=target[0] if isinstance(target,tuple) else target
                    check('speaker practice shares the child overlay window',manager is not None
                          and not manager.isWindow() and widget is not None and widget.window() is window)
                (output/'tutorial-steps.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),'utf8')
                if index in (0,len(tour.steps)//2,len(tour.steps)-1):
                    shot(window,f'chapter-{key}-{index:02}-target');shot(tour,f'chapter-{key}-{index:02}')
                check(f'chapter {key} step {index} bubble',tour.bubble.isVisible() and tour.skip.isVisible())
                check(f'chapter {key} practice excluded {index}',not newbie_tasks.mark('cut'))
                if key == 'timeline' and '往上滑==看看' in tour._text_source:
                    wheel_rows(window.built_page('studio').timeline)
                    continue
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
