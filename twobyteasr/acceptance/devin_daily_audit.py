"""Opt-in normal-entry integration audit; all data and providers are isolated."""
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel
    from ..app.help_menu import CuteMenu, CuteMenuAction
    from ..app.home_tour import GuidedTour
    from ..app.quick_setup import QuickSetupDialog
    from ..design.theme_manager import apply_theme, save_theme_key
    from ..diagnostics.build_identity import load_build_identity

    app=QApplication.instance()
    result=dict(passed=False,checks=[],identity=load_build_identity().to_dict(),
                executable=sys.executable,pid=os.getpid(),dpr=window.devicePixelRatioF(),errors=[])
    original_exec=CuteMenu.exec
    patches=[]

    def persist():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf-8')

    def check(name, value, detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));persist()
        if not value:raise AssertionError(name+' '+str(detail))

    def shot(name, widget=None):
        if widget is not None:
            check('screenshot_'+name,widget.grab().save(str(output/(name+'.png'))))
            return
        base=window.grab();painter=QPainter(base)
        origin=window.mapToGlobal(QPoint(0,0))
        for top in QApplication.topLevelWidgets():
            if top is not window and top.isVisible() and top.width()>2:
                painter.drawPixmap(top.mapToGlobal(QPoint(0,0))-origin,top.grab())
        painter.end()
        check('screenshot_'+name,base.save(str(output/(name+'.png'))))

    def tour():
        t=window.findChild(GuidedTour)
        return t if t is not None and getattr(t,'mode','')!='closed' else None

    def compare():
        return next((t for t in QApplication.topLevelWidgets() if isinstance(t,QuickSetupDialog)
                     and t.isVisible() and getattr(t,'compare',False)),None)

    def finish(error=None):
        CuteMenu.exec=original_exec
        for patch in reversed(patches):patch.stop()
        if error:result['errors'].append(error)
        from . import blank_project_audit as guards
        result['provider_calls']=guards._provider_calls
        result['blocked_external_connections']=guards._blocked_external_connections
        result['passed']=bool(result['checks']) and all(c['passed'] for c in result['checks']) and not result['errors']
        persist()
        page=getattr(window,'_studio_page_instance',None)
        if page and page.project:page.undo_stack.setClean()
        for top in QApplication.topLevelWidgets():
            if top is not window and top.isVisible():top.close()
        window.close()

    def sequence():
        window.resize(1440,900)
        save_theme_key('sand');apply_theme('sand',app)
        yield 1.0
        menus=[]
        def popup(menu,position,*args,**kwargs):
            menus.append(menu);menu.popup(position)
        CuteMenu.exec=popup
        QTimer.singleShot(0,window._show_help_menu)
        yield lambda:bool(menus) and menus[0].isVisible()
        menu=menus[0]
        rows=[a.text() for a in menu.actions() if isinstance(a,CuteMenuAction)]
        check('help_five_rows',rows==['新手教学','打开范例工程','选择识别方式…','回报问题／导出诊断…','重新显示工作台操作提示'],rows)
        check('rounded_help',menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        shot('01-help-menu');shot('01-help-card',menu)
        entry=next(a for a in menu.actions() if isinstance(a,CuteMenuAction) and a.text()=='新手教学')
        menu.close();QTimer.singleShot(0,entry.trigger)
        yield lambda:compare() is not None
        check('comparison_before_tour',tour() is None)
        shot('02-comparison-first')
        QTest.mouseClick(compare().later_button,Qt.MouseButton.LeftButton)
        yield lambda:tour() is not None and tour().mode=='shown' and tour().bubble.isVisible()
        t=tour()
        check('first_step',t.index==0)
        check('typewriter_active',t._typer.running and 'transparent' in t.text.text())
        check('bunny_and_voice_visible',t.bubble.mascot.isVisible() and t.voice_button.isVisible())
        shot('03-typing')
        yield 1.6
        check('comparison_not_reopened',compare() is None)
        yield lambda:not t._typer.running
        check('bright_marker','#ffe27a' in t.text.text() or '#f7cf4a' in t.text.text())
        shot('04-first-step')
        t._greeted=True
        QTest.mouseClick(t.bubble.mascot,Qt.MouseButton.LeftButton)
        yield .2
        shot('05-hop')
        yield .8
        check('bunny_chat',t.chat.isVisible(),t.chat.text())
        shot('06-chat')
        QTest.mouseClick(t.next,Qt.MouseButton.LeftButton)
        yield lambda:t.index==1 and t.mode=='shown' and t.bubble.isVisible()
        shot('07-second-step')
        QTest.mouseClick(t.skip,Qt.MouseButton.LeftButton)
        yield lambda:tour() is None
        CuteMenu.exec=original_exec

        window.open_studio_project(output/'input.2byteproj')
        yield lambda:getattr(window,'_studio_page_instance',None) is not None and window._studio_page_instance.project is not None
        page=window._studio_page_instance
        yield lambda:not getattr(window,'_studio_loading_session',None) or not window._studio_loading_session.active
        check('normal_studio_project',page.project.project_id==result_project_id(output))
        page.select_cue('c1')
        yield .2
        from unittest.mock import patch
        from ..subtitle_rules import subtitle_translation as st
        class Offline:
            provider_id='offline-integration';model='offline-integration'
            def structured_complete(self,messages,schema,**kwargs):
                payload=json.loads(messages[-1]['content'])
                result.setdefault('offline_requests',[]).append(payload)
                time.sleep(.3)
                return {'items':[{'id':r['id'],'translation':'这是第'+r['text'].split()[-1]+'句测试译文'}
                                 for r in payload['lines'] if r['translate']]}
        for key,value in [('twobyteasr.providers.llm_config.text_ai_key_missing',lambda *a,**k:False),
                          ('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:Offline())]:
            p=patch(key,value);p.start();patches.append(p)
        for theme in ('grape','warm'):
            save_theme_key(theme);apply_theme(theme,app)
            yield .3
            page._open_translation_dialog(scope='all')
            yield lambda:getattr(page,'_translation_dialog',None) is not None and page._translation_dialog.isVisible()
            d=page._translation_dialog
            badges=[w for w in d.findChildren(QLabel) if w.objectName()=='translationStep']
            xs={w.mapTo(d,QPoint(0,0)).x() for w in badges}
            check(theme+'_three_steps_aligned',len(badges)==3 and len(xs)==1,list(xs))
            check(theme+'_scope_counts',d.scope_buttons['all'].count()==6 and d.scope_buttons['selected'].count()==1)
            for name,colour in [('pending',d._theme.danger),('all',d._theme.success),('selected',d._theme.accent)]:
                d.scope_buttons[name].setChecked(True)
                yield .08
                image=d.scope_buttons[name].grab().toImage()
                pixel=image.pixelColor(image.width()//2,int(image.devicePixelRatio()))
                expected=QColor(colour)
                check(theme+'_'+name+'_colour',all(abs(getattr(pixel,c)()-getattr(expected,c)())<24 for c in ('red','green','blue')),[pixel.name(),expected.name()])
            d.scope_buttons['all'].setChecked(True)
            yield .2
            cards={name:[card.height(),card.sizeHint().height()] for name,card in d.scope_buttons.items()}
            check(theme+'_scope_cards_compact',len({h for h,_ in cards.values()})==1 and max(h for h,_ in cards.values())==max(hint for _,hint in cards.values()),cards)
            shot('08-'+theme+'-translation',d)
            d.advanced_toggle.click();yield .1
            check(theme+'_context_available',d.context.isVisible() and d.glossary.isVisible())
            shot('09-'+theme+'-advanced',d)
            d.advanced_toggle.click()
            if theme=='warm':
                d.start_button.setEnabled(True)
                QTest.mouseClick(d.start_button,Qt.MouseButton.LeftButton)
                yield lambda:d._thread is not None
                check('translation_real_thread_and_run',d._phase=='run')
                shot('10-translation-running',d)
                yield lambda:d._thread is None
                check('translation_result_applied',st.status_counts(page.project,target='zh-Hans').get('done')==6,st.status_counts(page.project,target='zh-Hans'))
                check('translation_real_undo',page.undo_stack.canUndo())
                shot('11-translation-result',d)
                # Existing normal entry also records its bilingual display toggle.
                # Preserve and verify that separate command instead of assuming
                # the top command is the translation snapshot.
                undo_labels=[]
                while st.status_counts(page.project,target='zh-Hans').get('done',0) and len(undo_labels)<3:
                    undo_labels.append(page.undo_stack.undoText())
                    page.undo_stack.undo();yield .1
                check('translation_undo',st.status_counts(page.project,target='zh-Hans').get('done',0)==0,undo_labels)
                for _ in undo_labels:
                    page.undo_stack.redo();yield .1
                check('translation_redo',st.status_counts(page.project,target='zh-Hans').get('done')==6)
                from ..projects.studio_project import save_project,load_project
                save_project(page.project,output/'translated.2byteproj')
                reopened=load_project(output/'translated.2byteproj')
                check('translation_save_reopen',st.status_counts(reopened,target='zh-Hans').get('done')==6)
            d.close();yield .2
        check('external_provider_calls_zero',not result.get('provider_calls') and bool(result.get('offline_requests')))
        finish()

    steps=sequence()
    def drive():
        try:wanted=next(steps)
        except StopIteration:return
        except Exception:finish(traceback.format_exc());return
        if callable(wanted):
            deadline=time.monotonic()+60
            def wait():
                try:
                    if wanted():QTimer.singleShot(20,drive)
                    elif time.monotonic()>deadline:finish('Timed out waiting for normal UI state')
                    else:QTimer.singleShot(30,wait)
                except Exception:finish(traceback.format_exc())
            QTimer.singleShot(0,wait)
        else:QTimer.singleShot(int(wanted*1000),drive)
    def shutdown():
        result['gui_shutdown']=True;persist()
    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(1500,drive)


def result_project_id(output):
    from ..projects.studio_project import load_project
    return load_project(output/'input.2byteproj').project_id
