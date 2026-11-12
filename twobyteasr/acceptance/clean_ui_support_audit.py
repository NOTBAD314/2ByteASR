"""Explicitly enabled normal-window acceptance; all data stays in its tmp profile."""
from __future__ import annotations
import copy
import ctypes
import json
import os
import time
import traceback
import zipfile
from pathlib import Path
from unittest.mock import patch


def start(window,output):
    from PySide6.QtCore import QTimer
    def guarded():
        try:run(window,output)
        except Exception:
            from PySide6.QtWidgets import QApplication
            (output/'result.json').write_text(json.dumps(dict(passed=False,error=traceback.format_exc(),pid=os.getpid())),'utf8')
            window.close();QApplication.instance().quit()
    QTimer.singleShot(200,guarded)


def run(window,output):
    from PySide6.QtCore import QCoreApplication,QEvent,QPoint,QTimer,Qt
    from PySide6.QtGui import QHelpEvent,QMovie
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QDialog,QFileDialog,QLineEdit,QMenu,QPushButton,QToolTip,QWidget
    from shiboken6 import isValid
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    from ..app.home_tour import GuidedTour,TourStep,TourAnim,tutorial_steps
    from ..i18n import tr
    from .studio_acceptance_audit import require

    app=QApplication.instance()
    checks=[];error=None;page=None;dialogs=[];movies=[]
    result=dict(identity=load_build_identity().to_dict(),pid=os.getpid(),checks=checks,
                platform=app.platformName(),dpr=window.devicePixelRatioF(),
                scope='normal MainWindow; Qt mouse/key events; real Qt save dialog; no human listening claim')
    def persist():
        result.update(passed=bool(checks) and error is None and all(c['passed'] for c in checks),error=error)
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,value,detail=None):
        checks.append(dict(name=name,passed=bool(value),detail=detail));persist();require(value,name+': '+str(detail))
    def wait(predicate,label,seconds=20):
        end=time.monotonic()+seconds
        while not predicate() and time.monotonic()<end:QTest.qWait(20)
        check(label,predicate())
    def shot(widget,name):
        QTest.qWait(60);widget.grab().save(str(output/(name+'.png')))
    def hover(widget,name):
        widget.setToolTip('hover policy acceptance')
        event=QHelpEvent(QEvent.Type.ToolTip,QPoint(8,8),widget.mapToGlobal(QPoint(8,8)))
        QCoreApplication.sendEvent(widget,event);QTest.qWait(150)
        check(name,not QToolTip.isVisible())
    def inspect(path,marker):
        with zipfile.ZipFile(path) as z:
            manifest=json.loads(z.read('manifest.json'))
            check('valid ZIP '+path.name,z.testzip() is None and manifest['report_id']==marker)
            check('environment and events '+path.name,bool(json.loads(z.read('environment.json'))['application']['build']['app_version'])
                  and bool(z.read('README.txt')) and bool(z.read('events.jsonl')))
            result.setdefault('bundles',[]).append(dict(path=str(path),manifest=manifest))
    def export_visible(view,label):
        screen=view.screen().availableGeometry()
        check(label,screen.contains(view.export.mapToGlobal(QPoint(0,0)))
              and screen.contains(view.export.mapToGlobal(view.export.rect().bottomRight())),
              dict(screen=[screen.x(),screen.y(),screen.width(),screen.height()],dialog=[view.x(),view.y(),view.width(),view.height()]))
    def save_dialog(view,target,cancel=False):
        original=QFileDialog.getSaveFileName
        observed=[]
        def choose(*args,**kwargs):
            kwargs['options']=QFileDialog.Option.DontUseNativeDialog
            def answer():
                dialog=next((w for w in app.topLevelWidgets() if isinstance(w,QFileDialog) and w.isVisible()),None)
                if dialog is None:QTimer.singleShot(30,answer);return
                observed.append(True)
                if cancel:dialog.reject()
                else:
                    dialog.setDirectory(str(target.parent))
                    def submit():
                        dialog.findChild(QLineEdit,'fileNameEdit').setText(target.name)
                        dialog.accept()
                    QTimer.singleShot(150,submit)
            QTimer.singleShot(100,answer)
            return original(*args,**kwargs)
        with patch.object(QFileDialog,'getSaveFileName',choose):
            QTest.mouseClick(view.export,Qt.MouseButton.LeftButton)
        check('save dialog opened and returned '+('cancel' if cancel else target.name),bool(observed))

    try:
        apply_theme(os.environ.get('TWOBYTEASR_ACCEPTANCE_THEME','sand'),app)
        available=window.screen().availableGeometry()
        window.showNormal();window.resize(min(1500,available.width()-40),min(930,available.height()-50));QTest.qWait(150)
        result['window_size']=[window.width(),window.height()]
        check('startup has no Studio or player',window.built_page('studio') is None)
        shot(window,'01-home')
        hover(window.app_settings_button,'home hover suppressed')
        window._open_diagnostics_dialog();view=window._support_dialog;dialogs.append(view)
        wait(lambda:not view._loading and getattr(view,'_data',None) is not None,'home report loaded')
        check('report owner is MainWindow',view.parentWidget() is window)
        export_visible(view,'report export button is inside screen')
        window._open_support();support=window._support_entry_dialog;dialogs.append(support)
        check('support entry and feedback have independent owners',support is not view and window._support_dialog is view)
        support.close();QTest.qWait(70)
        check('closing support leaves feedback usable',not view._closed and window._support_dialog is view)
        hover(view.export,'feedback hover suppressed')
        save_dialog(view,output/'cancel.zip',cancel=True)
        check('cancel restores export',view.export.isEnabled() and not view._exporting and not (output/'cancel.zip').exists())
        folder=output/'非 ASCII 用户 空格';folder.mkdir()
        target=folder/'主页诊断 中文.zip'
        heartbeat=[];pulse=QTimer(view);pulse.setInterval(10);pulse.timeout.connect(lambda:heartbeat.append(time.monotonic()));pulse.start()
        save_dialog(view,target)
        check('background export disables duplicate action',view._exporting and not view.export.isEnabled())
        wait(lambda:not view._exporting,'home export completed')
        pulse.stop()
        check('export returned requested path',view._result and view._result.get('target')==str(target),view._result)
        inspect(target,view.identity.text())
        check('export success is visible and has folder action',str(target) in view.note.text() and view.folder.isVisible() and view.folder.isEnabled())
        export_visible(view,'export result and button remain reachable')
        check('save and export flow processes GUI events',bool(heartbeat))
        check('export did not construct Studio',window.built_page('studio') is None)
        shot(view,'02-home-export-success')
        # A real Windows exclusive handle prevents os.replace of an existing target.
        from ctypes import wintypes as W
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,ctypes.c_void_p,W.DWORD,W.DWORD,W.HANDLE]
        kernel.CreateFileW.restype=W.HANDLE;kernel.CloseHandle.argtypes=[W.HANDLE]
        old=target.read_bytes();handle=kernel.CreateFileW(str(target),0x80000000,0,None,3,0,None)
        check('real target lock acquired',handle not in (None,ctypes.c_void_p(-1).value))
        try:
            view._export_to(target);wait(lambda:not view._exporting,'locked export terminated')
            check('locked failure shown with stage',view._result.get('error')=='PermissionError' and view._result.get('stage')=='atomic_publication',view._result)
            view.copy.click();check('failure is copyable','atomic_publication' in app.clipboard().text())
        finally:kernel.CloseHandle(handle)
        check('failed replacement preserves old bytes',target.read_bytes()==old and not list(folder.glob('*.tmp')))
        shot(view,'03-export-locked-failure')
        view._export_to(target);wait(lambda:not view._exporting,'retry after unlock completed');inspect(target,view.identity.text())
        previous_marker=view.identity.text()
        view.close();QTest.qWait(80)
        window._open_diagnostics_dialog();reopened=window._support_dialog;dialogs.append(reopened)
        check('reopen creates new report marker',reopened is not view and reopened.identity.text()!=previous_marker)
        reopened.close();QTest.qWait(80)

        settings_seen=[]
        def check_settings():
            dialog=next((w for w in app.topLevelWidgets() if isinstance(w,QDialog) and w.isVisible()),None)
            if dialog is None:QTimer.singleShot(40,check_settings);return
            settings_seen.append(True);hover(dialog,'settings hover suppressed')
            shot(dialog,'settings-clicked-panel');dialog.reject()
        QTimer.singleShot(200,check_settings)
        window.app_settings_button.click();QTest.qWait(350)
        check('clicked settings remain functional',bool(settings_seen))

        window.open_studio_project(str(output/'fixture.2byteproj'),mode='edit',source='clean_ui_acceptance')
        wait(lambda:window.built_page('studio') is not None,'Studio constructed')
        page=window.built_page('studio')
        wait(lambda:page.project is not None and page._readiness.ready,'Studio fixture ready')
        before=copy.deepcopy(page.project.generation_metadata)
        statuses=copy.deepcopy(page.project.studio_state.get('cue_statuses',{}))
        check('caption status container is absent',not hasattr(page,'recognition_chip') and not page.findChildren(QWidget,'speechRecoveryButton'))
        for language in ('zh','en','ja','zh'):
            window.language_combo.setCurrentIndex(window.language_combo.findData(language))
            page.project_controller._populate_speakers()
            check('speaker entry stays clean '+language,page.speaker_manager_button.text()==tr('说话人管理'),page.speaker_manager_button.text())
        page._speaker_roles_pending=True;page.project_controller._populate_speakers()
        check('pending roles do not rename entry',page.speaker_manager_button.text()==tr('说话人管理'))
        page._speaker_roles_pending=False
        page._sync_recognition_zero_state();page._refresh_review_summary_strip()
        check('refresh does not recreate status row',not hasattr(page,'recognition_chip') and not page.findChildren(QWidget,'speechRecoveryButton'))
        check('review and recovery data unchanged',page.project.generation_metadata==before and page.project.studio_state.get('cue_statuses',{})==statuses)
        from ..studio.speech_recovery_ui import add_actions
        recovery_menu=QMenu(page);add_actions(page,recovery_menu)
        check('gap listening panel remains reachable',len(recovery_menu.actions())==1)
        recovery_menu.actions()[0].trigger();gap_dialog=page._speech_recovery_dialog;dialogs.append(gap_dialog)
        jumps=gap_dialog.findChildren(QPushButton,'speechGapJump')
        check('gap listening buttons retained',len(jumps)==2)
        jumps[0].click();gap_dialog.close()
        check('listening does not confirm gaps',page.project.generation_metadata==before)
        page._recognition_running=True
        page._recognition_show_status('验收阶段','合成进度，未调用模型')
        task=page._recognition_subtitle_task
        check('recognition progress remains in task model',task is not None and any(r.get('status')=='running' for r in task.rows.values()))
        page.fail_recognition_runtime('验收失败信息')
        check('failure remains in task model',task.ended is not None and any(r.get('status')=='failed' for r in task.rows.values()))
        check('recognition does not recreate removed row',not hasattr(page,'recognition_chip'))
        hover(page.punctuation_button,'Studio punctuation hover suppressed')
        shot(window,'04-studio-clean-list')
        menu=QMenu(page);action=menu.addAction('主动菜单');triggered=[];action.triggered.connect(lambda:triggered.append(True))
        menu.popup(page.punctuation_button.mapToGlobal(QPoint(0,0)));QTest.qWait(80)
        check('clicked menus remain visible',menu.isVisible())
        action.trigger();menu.close();check('menu action still executes',bool(triggered))
        page.select_cue(page.project.cues[0].id);page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key.Key_E)
        wait(lambda:getattr(page,'_canvas_editor',None) is not None,'E editing surface preserved')
        editor=page._canvas_editor
        QTest.keyClick(editor,Qt.Key.Key_Escape);QTest.qWait(100)

        # Exercise current overlay, mascot and audio unchanged; only gestures differ.
        app.setProperty('reduceMotion',False)
        animation_map=[]
        inventory=TourAnim()
        for index,step in enumerate(tutorial_steps(window)):
            name=step.anim() if callable(step.anim) else step.anim
            if not name:continue
            check('step resource loads '+str(index)+' '+name,inventory.load(name,os.environ.get('TWOBYTEASR_ACCEPTANCE_THEME')=='sand'))
            animation_map.append(dict(index=index,name=name,source=inventory.source,
                                      file=Path(inventory._movie.fileName()).name if inventory._movie else None))
        inventory.stop();inventory.deleteLater();result['animation_map']=animation_map
        for name in ('drop','edit','speakers','punct'):
            tour=GuidedTour(window,[TourStep('兔白带你看原版演示',anim=name),TourStep('新步骤演示',anim='plan_compare')])
            dialogs.append(tour);tour.start()
            wait(lambda:tour.mode=='shown' and tour.reveal>=1,'tour shown '+name)
            check('original animation selected '+name,tour.anim.source=='original-webp')
            check('mascot and voice remain '+name,tour.bubble.mascot is not None and tour.voice is not None)
            frame=tour.anim._movie.currentFrameNumber();QTest.qWait(260)
            check('original moves '+name,tour.anim._movie.currentFrameNumber()!=frame)
            if name=='speakers':
                tour._greeted=True
                QTest.mouseClick(tour.bubble.mascot,Qt.MouseButton.LeftButton)
                QTest.qWait(100)
                check('clicked bunny speech balloon remains',tour.chat.isVisible())
                tour._hide_chat()
            shot(tour.bubble,'05-tour-'+name)
            if name in ('edit','speakers'):
                # Replay the unchanged predecessor SCENES implementation for
                # an exact same-container comparison; no product rollback.
                from ..app import home_tour
                with patch.object(home_tour,'tutorial_anim_path',return_value=None):
                    tour.anim.load(name,os.environ.get('TWOBYTEASR_ACCEPTANCE_THEME')=='sand')
                tour.anim.start();QTest.qWait(1200)
                shot(tour.bubble,'before-program-'+name)
                tour.anim.load(name,os.environ.get('TWOBYTEASR_ACCEPTANCE_THEME')=='sand');tour.anim.start();QTest.qWait(1200)
                shot(tour.bubble,'after-original-'+name)
            if name=='edit':
                from PIL import Image
                frames=[]
                for _ in range(40):
                    pix=tour.bubble.grab();path=output/f'frame-{len(frames):03d}.png';pix.save(str(path))
                    frames.append(Image.open(path).convert('RGB'));QTest.qWait(100)
                frames[0].save(output/'original-mg-with-current-bunny.gif',save_all=True,append_images=frames[1:],duration=100,loop=0)
                for image in frames:image.close()
            old_movie=tour.anim._movie
            tour.go(1);wait(lambda:tour.mode=='shown' and tour.reveal>=1,'new scene transition '+name)
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            check('previous movie released '+name,not isValid(old_movie) and tour.anim.source=='program-scene')
            tour.go(0,step=-1);wait(lambda:tour.mode=='shown' and tour.reveal>=1,'back to original '+name)
            tour.close_tour(False)
            check('close stops movie and audio '+name,tour.anim._movie is None and not tour.anim._ticker.isActive() and tour.voice._sink is None)
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.setProperty('reduceMotion',True)
        reduced=TourAnim();reduced.play('drop',False);movies.append(reduced)
        check('explicit reduced motion uses still',reduced.source=='original-still' and reduced._movie is None)
        reduced.stop();reduced.close()
        check('subtitle filters still exist',page.cue_filter_track.isVisible())
    except Exception:
        error=traceback.format_exc();(output/'error.txt').write_text(error,'utf8')
        shot(window,'failure')
    finally:
        for view in dialogs:
            if isValid(view):
                if hasattr(view,'close_tour') and view.mode!='closed':view.close_tour(False)
                else:view.close()
        for view in movies:
            if isValid(view):view.stop();view.close()
        if page is not None:
            page.undo_stack.setClean();page.project_dirty=False
        persist();window.close();app.quit()
