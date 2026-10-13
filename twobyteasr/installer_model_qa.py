"""Opt-in QA driving real workshop controls and the production installer."""
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, out):
    from PySide6.QtCore import QTimer, Qt, QProcess, QSettings
    from PySide6.QtTest import QTest
    from .build_identity import load_build_identity
    config = json.loads((out/'installer-qa.json').read_text('utf8'))
    result = dict(executable=sys.executable, build=vars(load_build_identity()),
                  started=time.time(), checks=[], models=[], status='RUNNING', paid_calls=0,
                  status_scope='GUI preparation; consult separate download/dependencies/load/inference fields')
    dialog = None
    pending = list(config.get('models', ['sensevoice']))
    current = None
    started = 0

    def save():
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')

    def check(name, value):
        result['checks'].append(dict(name=name,passed=bool(value)))
        save()
        if not value: raise AssertionError(name)

    def finish(error=None):
        result['status']='FAIL' if error or any(not m.get('prepare_ok') for m in result['models']) else 'PASS'
        if error and any(reason in str(error) for reason in ('QA dialog is not foreground', 'QA foreground changed', 'QA desktop is not input desktop', 'QA pointer target is occluded')):
            result['status']='BLOCKED'
        if error: result['error']=str(error)
        result['finished']=time.time(); save()
        window.close()

    def next_model():
        nonlocal dialog,current,started
        try:
            if not pending:
                finish();return
            key=pending.pop(0)
            page=window.workshop_page
            page._view_model(key)
            QTest.qWait(150)
            current=dict(key=key, started=time.time(),
                         phase_samples=[],
                         download='NOT VERIFIED', dependencies='NOT VERIFIED', load='NOT VERIFIED', inference='NOT VERIFIED')
            result['models'].append(current)
            action=page.detail_repair if page.detail_repair.isVisible() and page.detail_repair.isEnabled() else page.detail_action
            from PySide6.QtWidgets import QScrollArea, QApplication
            ancestor=action.parentWidget()
            while ancestor is not None:
                if isinstance(ancestor,QScrollArea):ancestor.ensureWidgetVisible(action)
                ancestor=ancestor.parentWidget()
            QTest.qWait(150)
            check('prepare button enabled '+key,action.isEnabled())
            check('prepare button reachable '+key,QApplication.widgetAt(action.mapToGlobal(action.rect().center())) is action)
            QTest.mouseClick(action, Qt.LeftButton)
            QTest.qWait(200)
            candidates=[x for x in page._download_dialogs if x.model.key==key]
            check('real workshop prepares '+key,len(candidates)==1)
            dialog=candidates[0]
            dialog.source_combo.setCurrentIndex(max(0,dialog.source_combo.findData(config.get('source','AUTO'))))
            dialog.show()
            dialog.grab().save(str(out/(key+'-before.png')))
            QTest.mouseClick(dialog.start_button,Qt.LeftButton)
            if config.get('cancel_retry'):
                first_pid=int(dialog.process.processId())
                QTest.mouseClick(dialog.start_button,Qt.LeftButton)
                check('duplicate start keeps one worker '+key,int(dialog.process.processId())==first_pid)
            started=time.monotonic()
            save(); QTimer.singleShot(1000,poll)
        except Exception:
            finish(traceback.format_exc())

    def poll():
        try:
            log=dialog.log.toPlainText()
            (out/(current['key']+'-prepare.log')).write_text(log,'utf8')
            current['elapsed_s']=round(time.monotonic()-started,3)
            current['phase']=getattr(dialog,'_phase','unknown')
            phases=current['phase_samples']
            if not phases or phases[-1]['phase']!=current['phase']:
                phases.append(dict(phase=current['phase'],elapsed_s=current['elapsed_s']))
            if dialog.process.state()!=QProcess.NotRunning:
                if config.get('cancel_retry') and not current.get('cancel_requested') and dialog._last_bytes>=16*1024**2:
                    import psutil
                    owner=psutil.Process(int(dialog.process.processId()))
                    current['cancel_pids']=[owner.pid,*[p.pid for p in owner.children(recursive=True)]]
                    current['cancel_requested']=True
                    current['bytes_before_cancel']=dialog._last_bytes
                    dialog.grab().save(str(out/(current['key']+'-downloading.png')))
                    QTest.mouseClick(dialog.pause_button,Qt.LeftButton)
                if time.monotonic()-started>config.get('timeout_s',7200):
                    dialog._request_pause();raise TimeoutError('QA model preparation deadline')
                save();QTimer.singleShot(1000,poll);return
            if current.get('cancel_requested') and not current.get('retry_clicked'):
                import psutil
                check('cancel stops owned descendants '+current['key'],not any(psutil.pid_exists(pid) for pid in current['cancel_pids']))
                check('cancel is not installation success '+current['key'],dialog._paused and not dialog._finished_ok)
                from .runtime_paths import get_runtime_paths
                model_root=get_runtime_paths().model_root
                partials={str(p.relative_to(model_root)):p.stat().st_size for p in (model_root/'.downloads').rglob('*.part.*') if p.is_file()}
                check('cancel retains actual network partials '+current['key'],sum(partials.values())>0)
                current['cancelled_partials']=partials
                dialog.grab().save(str(out/(current['key']+'-cancelled.png')))
                current['retry_clicked']=True
                QTest.mouseClick(dialog.start_button,Qt.LeftButton)
                save();QTimer.singleShot(1000,poll);return
            current['prepare_ok']=dialog._finished_ok
            current['download']='PASS' if dialog._finished_ok else 'FAIL'
            current['dependencies']='PASS' if 'runtime_ready' in log else 'NOT VERIFIED'
            from .runtime_paths import user_data_root
            receipt=user_data_root()/'model-readiness'/(str(dialog.model.download_key)+'.json')
            if receipt.is_file() and (dialog._finished_ok or receipt.stat().st_mtime>=current['started']):
                proof=json.loads(receipt.read_text('utf8'))
                current.update(download='PASS' if proof.get('files_verified') else current['download'],
                    dependencies='PASS' if proof.get('runtime_ready') else current['dependencies'],
                    load='PASS' if proof.get('model_loaded') else proof.get('status','NOT VERIFIED'),
                    inference='PASS' if proof.get('inference_verified') else proof.get('status','NOT VERIFIED'),
                    readiness_receipt=str(receipt))
            elif not dialog.model.runtime_available:
                current.update(dependencies='BLOCKED',load='BLOCKED',inference='BLOCKED',
                    limitation='Windows inference adapter unavailable; validated weights only')
            current['summary']=dialog.progress_status.text()
            dialog.grab().save(str(out/(current['key']+'-after.png')))
            dialog.hide();save()
            if dialog._finished_ok and (out/'sample.wav').is_file() and current['key'] in {'sensevoice','paraformer','funasr_nano'}:
                verify_inference()
            else:
                QTimer.singleShot(100,next_model)
        except Exception:
            finish(traceback.format_exc())

    def run():
        try:
            check('isolated QSettings',Path(QSettings('2ByteASR','2ByteASR').fileName()).resolve().is_relative_to(out))
            screen=window.screen(); geometry=screen.availableGeometry()
            result['display']=dict(qt_available=[geometry.x(),geometry.y(),geometry.width(),geometry.height()],
                                   qt_dpr=screen.devicePixelRatio(),logical_dpi=screen.logicalDotsPerInch(),simulation=os.environ.get('QT_SCALE_FACTOR',''),
                                   qt_geometry=list(screen.geometry().getRect()),
                                   physical_size=[round(screen.geometry().width()*screen.devicePixelRatio()),round(screen.geometry().height()*screen.devicePixelRatio())])
            if config.get('project_only'):
                verify_project();finish();return
            window._open_model_workshop()
            QTest.qWait(800)
            window.grab().save(str(out/'workshop.png'))
            if config.get('diagnostic_only'):
                verify_download_diagnostic();return
            if config.get('native_ui'):
                verify_native_windows()
                finish()
                return
            if config.get('ui_only'):
                verify_windows()
                verify_dialog_semantics()
                finish()
                return
            next_model()
        except Exception:
            finish(traceback.format_exc())
    QTimer.singleShot(500,run)

    def verify_download_diagnostic():
        nonlocal dialog
        from .model_workshop import ModelDownloadDialog,MODELS
        from PySide6.QtWidgets import QApplication
        dialog=ModelDownloadDialog(window.workshop_page.root,next(m for m in MODELS if m.key==pending[0]),window)
        dialog.show();dialog.raise_();QTest.qWait(300)
        for width,height in ((900,620),(640,480)):
            dialog.resize(width,height);QTest.qWait(200)
            check('download check button reachable '+str(width),QApplication.widgetAt(dialog.check_download_button.mapToGlobal(dialog.check_download_button.rect().center())) is dialog.check_download_button)
            dialog.grab().save(str(out/f'download-diagnostic-{width}.png'))
        QTest.mouseClick(dialog.check_download_button,Qt.LeftButton)
        began=time.monotonic()
        def completed():
            try:
                if dialog._diagnostic_report is None:
                    if time.monotonic()-began>300:raise TimeoutError('light diagnostic deadline')
                    QTimer.singleShot(200,completed);return
                report=dialog._diagnostic_report
                check('diagnostic did not launch installer',dialog.process.state()==QProcess.NotRunning)
                check('diagnostic did not upload',report.get('upload') is False)
                check('diagnostic body bounded',report.get('total_consumed_bytes',10**9)<=2*1024**2)
                check('diagnostic contains models and runtime probes',bool(report.get('models')) and len(report.get('bootstrap',[]))>=4)
                QTest.mouseClick(dialog.copy_diagnostic_button,Qt.LeftButton)
                copied=json.loads(QApplication.clipboard().text())
                check('copy diagnostic retains exact sanitized report',copied==report)
                (out/'copied-diagnostic.json').write_text(json.dumps(copied,ensure_ascii=False,indent=2),'utf8')
                dialog.grab().save(str(out/'download-diagnostic-completed.png'))
                dialog.close();finish()
            except Exception:finish(traceback.format_exc())
        QTimer.singleShot(200,completed)

    def verify_project():
        from PySide6.QtWidgets import QApplication
        from .studio_project import load_project
        studio=window.studio_page
        window._switch_page(studio)
        ready=[]
        studio.open_project(out/'empty.2byteproj',on_ready=lambda *a:ready.append(True))
        deadline=time.monotonic()+30
        while not ready and time.monotonic()<deadline:QTest.qWait(100)
        check('real project loaded',studio.project is not None and Path(studio.project_path).resolve().is_relative_to(out))
        marker=out/'project-verified.json'
        if marker.is_file():
            check('restart restores saved media',Path(studio.project.media.path).resolve()==(out/'sample.wav').resolve())
            check('restart restores saved captions',len(studio.project.cues)==2 and studio.project.cues[0].text=='Hello this is a local speech recognition test.')
        else:
            studio._begin_media_ingest(out/'sample.wav')
            deadline=time.monotonic()+30
            while not studio.project.media.path and time.monotonic()<deadline:QTest.qWait(100)
            check('media import resolves real WAV',Path(studio.project.media.path).resolve()==(out/'sample.wav').resolve())
            subtitle=out/'fixture.srt'
            subtitle.write_text('1\n00:00:00,000 --> 00:00:03,500\nHello this is a local speech recognition test.\n\n2\n00:00:03,600 --> 00:00:05,970\nThe weather is sunny today.\n','utf8')
            studio._import_subtitle_file(subtitle);QTest.qWait(500)
            check('subtitle import creates timeline cues',len(studio.project.cues)==2)
            check('project save button is reachable',QApplication.widgetAt(studio.save_button.mapToGlobal(studio.save_button.rect().center())) is studio.save_button)
            QTest.mouseClick(studio.save_button,Qt.LeftButton);QTest.qWait(600)
            stored=load_project(studio.project_path)
            check('save persists media and captions',len(stored.cues)==2 and stored.media.path==studio.project.media.path)
            marker.write_text(json.dumps(dict(project=str(studio.project_path),captions=2,media=stored.media.path)),'utf8')
        window.grab().save(str(out/'project-editor.png'))
        studio.show_project_hub();QTest.qWait(500)
        window.resize(900,540);QTest.qWait(300)
        window.grab().save(str(out/'project-library-small.png'))
        check('project library stays within available screen',window.screen().availableGeometry().contains(window.frameGeometry()))

    def verify_inference():
        import threading
        completion={}
        def task():
            try:
                import wave
                import numpy as np
                from .runtime_registry import reset_runtime_registry_cache
                from .asr import _transcribe_funasr_worker
                reset_runtime_registry_cache()
                with wave.open(str(out/'sample.wav'),'rb') as audio:
                    assert audio.getsampwidth()==2 and audio.getnchannels()==1
                    sample_rate=audio.getframerate()
                    samples=np.frombuffer(audio.readframes(audio.getnframes()),dtype='<i2').astype(np.float32)/32768
                began=time.monotonic()
                output=_transcribe_funasr_worker(current['key'],[dict(audio=(samples,sample_rate),start=0.0,end=len(samples)/sample_rate)])
                if not output or not any(item.get('text','').strip() for item in output):
                    raise RuntimeError('正式 adapter 返回空文本')
                completion.update(load='PASS',inference='PASS',inference_s=round(time.monotonic()-began,3),asr_output=output)
            except Exception:
                completion.update(load='NOT VERIFIED',inference='FAIL',inference_error=traceback.format_exc())
            finally:completion['done']=True
        threading.Thread(target=task,daemon=True,name='installer-qa-inference').start()
        def poll_inference():
            if not completion.get('done'):
                QTimer.singleShot(500,poll_inference);return
            current.update(completion);save();QTimer.singleShot(100,next_model)
        poll_inference()

    def verify_windows():
        from PySide6.QtWidgets import QDialogButtonBox, QApplication, QPushButton
        from PySide6.QtCore import QPoint
        from .application_settings_ui import ApplicationSettingsDialog
        from .model_workshop import ModelDownloadDialog, MODELS
        # Actual Windows windows; widths/heights here are logical, not physical
        # display mode changes. QT_SCALE_FACTOR, if used, is explicitly recorded.
        for width,height in ((1200,680),(900,540),(720,460),(640,400)):
            window.resize(width,height);QTest.qWait(200)
            window.grab().save(str(out/f'workshop-{width}x{height}.png'))
            for iteration in range(10):
                settings=ApplicationSettingsDialog(window,{},out/'projects',browse=lambda *a:None,
                    clear_recent=lambda:None,reset_layout=lambda:None)
                settings.show();settings.raise_();settings.activateWindow();QTest.qWait(350)
                save_button=settings.buttons.button(QDialogButtonBox.Save)
                point=save_button.mapToGlobal(save_button.rect().center())
                hit=QApplication.widgetAt(point)
                result.setdefault('window_samples',[]).append(dict(width=width,iteration=iteration,
                    parent=list(window.frameGeometry().getRect()),dialog=list(settings.frameGeometry().getRect()),
                    save_rect=list(save_button.rect().getRect()),save_global=[point.x(),point.y()],
                    hit_type=type(hit).__name__,hit_name=hit.objectName() if hit else '',
                    active=type(QApplication.activeWindow()).__name__))
                if iteration==0 or hit is not save_button:
                    settings.grab().save(str(out/f'settings-{width}x{height}.png'))
                    window.screen().grabWindow(0).save(str(out/f'desktop-settings-{width}x{height}.png'))
                check(f'settings footer hit {width}/{iteration}',QApplication.widgetAt(point) is save_button)
                check(f'settings correct title {width}/{iteration}',settings.windowTitle()=='应用设置')
                close=next(b for b in settings.findChildren(QPushButton) if b.toolTip()=='关闭设置')
                check(f'settings X reachable {width}/{iteration}',close.text()=='×' and QApplication.widgetAt(close.mapToGlobal(close.rect().center())) is close)
                check(f'settings parent containment {width}/{iteration}',
                    window.frameGeometry().contains(settings.frameGeometry()))
                if iteration==0:settings.grab().save(str(out/f'settings-{width}x{height}.png'))
                QTest.mouseClick(save_button,Qt.LeftButton);QTest.qWait(180)
                check(f'settings save click closed {width}/{iteration}',not settings.isVisible())
                settings.deleteLater()
                download=ModelDownloadDialog(window.workshop_page.root,next(x for x in MODELS if x.key=='sensevoice'),window)
                download.show();download.raise_();download.activateWindow();QTest.qWait(350)
                check(f'download footer hit {width}/{iteration}',QApplication.widgetAt(download.close_button.mapToGlobal(download.close_button.rect().center())) is download.close_button)
                if iteration==0:download.grab().save(str(out/f'download-{width}x{height}.png'))
                QTest.keyClick(download,Qt.Key_Escape);QTest.qWait(80)
                check(f'download Esc closed {width}/{iteration}',not download.isVisible())
                download.deleteLater()

    def verify_native_windows():
        """Windows pointer input is confined to the verified foreground QA HWND."""
        import ctypes
        import threading
        from ctypes import wintypes
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFrame
        from .application_settings_ui import ApplicationSettingsDialog
        user32=ctypes.windll.user32
        user32.GetForegroundWindow.restype=wintypes.HWND
        user32.SetForegroundWindow.argtypes=[wintypes.HWND]
        user32.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        user32.AttachThreadInput.argtypes=[wintypes.DWORD,wintypes.DWORD,wintypes.BOOL]
        user32.GetThreadDesktop.argtypes=[wintypes.DWORD]
        user32.GetThreadDesktop.restype=wintypes.HANDLE
        user32.OpenInputDesktop.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        user32.OpenInputDesktop.restype=wintypes.HANDLE
        user32.GetUserObjectInformationW.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
        user32.CloseDesktop.argtypes=[wintypes.HANDLE]
        user32.WindowFromPoint.argtypes=[wintypes.POINT]
        user32.WindowFromPoint.restype=wintypes.HWND
        failures=[]
        window.resize(1000,550);window.raise_();window.activateWindow();QTest.qWait(250)

        def activate_qa(dialog):
            hwnd=int(dialog.winId())
            owner=wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
            if owner.value!=os.getpid():raise RuntimeError('Activation target is not this QA process')
            dialog.raise_();dialog.activateWindow();user32.SetForegroundWindow(hwnd)
            QTest.qWait(150)
            if user32.GetForegroundWindow()!=hwnd:
                foreground=user32.GetForegroundWindow()
                foreground_thread=user32.GetWindowThreadProcessId(foreground,None)
                current_thread=ctypes.windll.kernel32.GetCurrentThreadId()
                attached=bool(user32.AttachThreadInput(current_thread,foreground_thread,True))
                try:user32.SetForegroundWindow(hwnd)
                finally:
                    if attached:user32.AttachThreadInput(current_thread,foreground_thread,False)
                QTest.qWait(150)
            foreground=user32.GetForegroundWindow()
            foreground_owner=wintypes.DWORD()
            user32.GetWindowThreadProcessId(foreground,ctypes.byref(foreground_owner))
            result.setdefault('native_activation',[]).append(dict(target=hwnd,
                foreground=foreground,foreground_pid=foreground_owner.value,qa_pid=os.getpid()))
            dialog.screen().grabWindow(0).save(str(out/'native-activation-desktop.png'))

        def gesture(dialog, local, delta=QPoint()):
            hwnd=int(dialog.winId())
            def desktop_name(handle):
                name=ctypes.create_unicode_buffer(256);needed=wintypes.DWORD()
                if not handle or not user32.GetUserObjectInformationW(handle,2,name,ctypes.sizeof(name),ctypes.byref(needed)):return ''
                return name.value
            input_desktop=user32.OpenInputDesktop(0,False,1)
            try:
                input_name=desktop_name(input_desktop)
                own_name=desktop_name(user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId()))
                result['native_desktop_guard']=dict(input=input_name,qa=own_name)
                if not input_name or input_name!=own_name:
                    raise RuntimeError('Native QA input refused: QA desktop is not input desktop')
            finally:
                if input_desktop:user32.CloseDesktop(input_desktop)
            if user32.GetForegroundWindow()!=hwnd:
                raise RuntimeError('Native QA input refused: QA dialog is not foreground')
            rect=wintypes.RECT();user32.GetWindowRect(hwnd,ctypes.byref(rect))
            scale=dialog.devicePixelRatioF()
            start=(rect.left+round(local.x()*scale),rect.top+round(local.y()*scale))
            end=(start[0]+round(delta.x()*scale),start[1]+round(delta.y()*scale))
            owner=wintypes.DWORD()
            user32.GetWindowThreadProcessId(user32.WindowFromPoint(wintypes.POINT(*start)),ctypes.byref(owner))
            if owner.value!=os.getpid():raise RuntimeError('Native QA input refused: QA pointer target is occluded')
            result.setdefault('native_pointer',[]).append(dict(hwnd=hwnd,start=start,end=end,dpr=scale))
            errors=[]
            def input_thread():
                pressed=False
                try:
                    if user32.GetForegroundWindow()!=hwnd:
                        raise RuntimeError('QA foreground changed before pointer input')
                    user32.SetCursorPos(*start);user32.mouse_event(2,0,0,0,0);pressed=True
                    for i in range(1,7):
                        time.sleep(.04)
                        foreground_owner=wintypes.DWORD()
                        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(),ctypes.byref(foreground_owner))
                        if foreground_owner.value!=os.getpid():raise RuntimeError('QA foreground changed during pointer input')
                        user32.SetCursorPos(round(start[0]+(end[0]-start[0])*i/6),round(start[1]+(end[1]-start[1])*i/6))
                except Exception as exc:errors.append(str(exc))
                finally:
                    if pressed:user32.mouse_event(4,0,0,0,0)
            worker=threading.Thread(target=input_thread,daemon=True);worker.start()
            QTest.qWait(700);worker.join(1)
            if errors:raise RuntimeError(errors[0])

        def exercise():
            settings=next((w for w in QApplication.topLevelWidgets() if isinstance(w,ApplicationSettingsDialog) and w.isVisible()),None)
            try:
                check('native real application settings entry',isinstance(settings,ApplicationSettingsDialog))
                settings.resize(min(620,window.width()-120),max(300,min(360,window.height()-100)))
                settings.move(window.pos()+QPoint(45,30));QTest.qWait(200)
                activate_qa(settings)
                header=settings.findChild(QFrame,'settingsHeader')
                initial=QPoint(settings.pos())
                gesture(settings,header.mapTo(settings,QPoint(150,20)),QPoint(28,18))
                check('native title drag moved dialog',(settings.pos()-initial).manhattanLength()>15)
                before=settings.size()
                gesture(settings,QPoint(settings.width()-8,settings.height()-8),QPoint(48,30))
                check('native corner resize changed layout',settings.width()>before.width()+15 and settings.height()>before.height()+10)
                save_button=settings.buttons.button(QDialogButtonBox.Save)
                check('native resized footer reachable',QApplication.widgetAt(save_button.mapToGlobal(save_button.rect().center())) is save_button)
                settings.grab().save(str(out/'native-settings-after-drag-resize.png'))
                settings.screen().grabWindow(0).save(str(out/'native-desktop-settings.png'))
                gesture(settings,save_button.mapTo(settings,save_button.rect().center()))
                check('native pointer save closed settings',not settings.isVisible())
            except Exception:
                failures.append(traceback.format_exc())
                if isinstance(settings,ApplicationSettingsDialog):settings.reject()
        QTimer.singleShot(400,exercise)
        window._open_application_settings()
        if failures:raise RuntimeError(failures[0])

        def keyboard_and_outside():
            settings=next((w for w in QApplication.topLevelWidgets() if isinstance(w,ApplicationSettingsDialog) and w.isVisible()),None)
            try:
                check('native settings reopened',isinstance(settings,ApplicationSettingsDialog))
                settings.resize(600,380);settings.move(window.pos()+QPoint(150,70));QTest.qWait(250)
                settings.root_edit.setFocus();QTest.keyClick(settings.root_edit,Qt.Key_Tab)
                forward=QApplication.focusWidget()
                check('Tab moves focus',forward is not settings.root_edit)
                QTest.keyClick(forward,Qt.Key_Tab,Qt.ShiftModifier)
                check('Shift Tab restores focus',QApplication.focusWidget() is settings.root_edit)
                QTest.keyClick(settings,Qt.Key_Escape);QTest.qWait(250)
                check('production modal Esc closes',not settings.isVisible())
            except Exception:
                failures.append(traceback.format_exc())
                if isinstance(settings,ApplicationSettingsDialog):settings.reject()
        QTimer.singleShot(400,keyboard_and_outside)
        window._open_application_settings()
        if failures:raise RuntimeError(failures[0])
        def outside():
            settings=next((w for w in QApplication.topLevelWidgets() if isinstance(w,ApplicationSettingsDialog) and w.isVisible()),None)
            try:
                check('native outside target is settings',isinstance(settings,ApplicationSettingsDialog))
                settings.resize(500,300);settings.move(window.pos()+QPoint(75,55));QTest.qWait(250)
                activate_qa(settings)
                # Ten logical pixels inside the parent is outside this dialog.
                local=settings.mapFromGlobal(window.mapToGlobal(QPoint(10,10)))
                gesture(settings,local)
                check('native backdrop click closes production modal',not settings.isVisible())
            except Exception:
                failures.append(traceback.format_exc())
                if isinstance(settings,ApplicationSettingsDialog):settings.reject()
        QTimer.singleShot(400,outside)
        window._open_application_settings()
        if failures:raise RuntimeError(failures[0])
        result['native_ui']='PASS'

    def verify_dialog_semantics():
        from PySide6.QtWidgets import QApplication,QMessageBox,QComboBox,QPushButton,QFrame
        from PySide6.QtCore import QPoint
        from .application_settings_ui import ApplicationSettingsDialog
        window.resize(900,540);QTest.qWait(150)
        for choice in (QMessageBox.Cancel,QMessageBox.Discard,QMessageBox.Save):
            settings=ApplicationSettingsDialog(window,{},out/'projects',browse=lambda *a:None,
                clear_recent=lambda:None,reset_layout=lambda:None)
            failures=[]
            def exercise():
                try:
                    settings.root_edit.setText(str(out/'changed-projects'))
                    def answer():
                        message=QApplication.activeModalWidget()
                        if not isinstance(message,QMessageBox):
                            failures.append('Unsaved confirmation was not shown');return
                        QTest.mouseClick(message.button(choice),Qt.LeftButton)
                    QTimer.singleShot(120,answer)
                    QTest.keyClick(settings,Qt.Key_Escape);QTest.qWait(250)
                    if choice==QMessageBox.Cancel:
                        check('unsaved cancel keeps editing',settings.isVisible())
                        settings._saved_values=settings._values()
                        QTest.mouseClick(settings._modal_backdrop,Qt.LeftButton,pos=QPoint(2,2));QTest.qWait(200)
                        check('backdrop closes after continuing edit',not settings.isVisible())
                except Exception:
                    failures.append(traceback.format_exc())
                    settings._saved_values=settings._values();settings.reject()
            QTimer.singleShot(180,exercise)
            outcome=settings.exec()
            check('unsaved choice result '+str(choice),outcome==(1 if choice==QMessageBox.Save else 0))
            if failures:raise RuntimeError('\n'.join(failures))
            settings.deleteLater();QTest.qWait(100)
        window.resize(900,540)
        for iteration in range(10):
            window._open_model_picker('primary');QTest.qWait(180)
            host=window._modal_host
            initial=QPoint(host.card.pos());main_pos=QPoint(window.pos())
            QTest.mousePress(host.header,Qt.LeftButton,pos=QPoint(100,20))
            QTest.mouseMove(host.header,QPoint(120,30),delay=30)
            QTest.mouseRelease(host.header,Qt.LeftButton,pos=QPoint(120,30))
            check('embedded header keeps main position '+str(iteration),window.pos()==main_pos)
            check('embedded header moves card '+str(iteration),host.card.pos()!=initial)
            check('embedded card stays in parent '+str(iteration),host.rect().contains(host.card.geometry()))
            check('embedded X reachable '+str(iteration),QApplication.widgetAt(host.xbtn.mapToGlobal(host.xbtn.rect().center())) is host.xbtn)
            if iteration%2:
                QTest.mouseClick(host.backdrop,Qt.LeftButton,pos=QPoint(2,2))
            else:QTest.mouseClick(host.xbtn,Qt.LeftButton)
            QTest.qWait(100)
            check('embedded cross-open closes '+str(iteration),not host.isVisible())
        check('no visible residual backdrop',not any(w.isVisible() for w in window.findChildren(QFrame) if w.objectName()=='modalBackdrop'))
