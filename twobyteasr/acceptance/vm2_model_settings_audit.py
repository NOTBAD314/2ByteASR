"""Explicit normal-entry checks of the cumulative model/settings delivery."""
import json,os,sys,time,traceback


def start(window, output):
    if os.environ.get('TWOBYTEASR_WORKSHOP_COLUMNS_ONLY')=='1':
        from .workshop_columns_audit import start as columns_start
        columns_start(window,output)
        return
    from PySide6.QtCore import QTimer,Qt,QPoint,QMimeData,QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication,QLabel,QPushButton,QStackedWidget,QDialog
    app=QApplication.instance()
    checks=[]
    def check(name,value,detail=None):
        checks.append(dict(name=name,passed=bool(value),detail=detail))
        if not value:raise AssertionError(name)
    def settle(seconds=.2):
        end=time.monotonic()+seconds
        while time.monotonic()<end:app.processEvents();time.sleep(.005)
    def wait(predicate,seconds=20):
        end=time.monotonic()+seconds
        while not predicate() and time.monotonic()<end:settle(.02)
        check('wait for visible complete content',predicate())
    def shot(widget,name):check('screenshot '+name,widget.grab().save(str(output/(name+'.png'))))

    def run():
        code=0
        try:
            from ..design.theme_manager import apply_theme
            from ..local_models.model_workshop import _DeferredPickerCard
            from ..local_models.model_picker_cards import PickerCard
            from ..local_models.model_picker_copy import recommended_for
            from ..app.home_script_match import open_home_script_match
            from ..app.home_script_match_ui import DropZone
            from ..app.application_settings import read_studio_preferences
            window._ensure_recognition_page();window._return_to_settings();settle(.5)
            for theme in ('warm','grape'):
                apply_theme(theme,app);settle(.3)
                from .update_window_audit import verify
                verify(window,output,theme,check,settle,shot)
                for role in ('primary','timeline','review'):
                    window._open_model_picker(role)
                    panel=getattr(window,'_model_picker_'+role+'_panel')
                    wait(lambda:panel.isVisible() and sum(isinstance(c,PickerCard) or c._card is not None for c in panel.cards.values())>=min(2,len(panel.cards)))
                    settle(.4)
                    check(theme+' '+role+' card wall',panel.cards_grid.columnCount()==2 and bool(panel.ordered_keys()))
                    viewport=panel.scroll.viewport()
                    for key in panel.ordered_keys():
                        card=panel.cards[key]
                        if card.isHidden():continue
                        left=card.mapTo(viewport,QPoint()).x()
                        check(theme+' '+role+' '+key+' fits horizontally',left>=0 and left+card.width()<=viewport.width(),dict(left=left,width=card.width(),viewport=viewport.width()))
                        actual=card._card if isinstance(card,_DeferredPickerCard) else card
                        chip=getattr(actual,'language_chip',None) if actual is not None else None
                        if chip is not None:
                            check(theme+' '+role+' '+key+' languages stay on one line',not chip.wordWrap() and chip.height()<=chip.fontMetrics().height()+16,dict(height=chip.height(),font_height=chip.fontMetrics().height()))
                            check(theme+' '+role+' '+key+' full languages retained on hover',chip.toolTip()==chip.text())
                    ordered=panel.ordered_keys();recommended=[key for key in recommended_for(role) if key in ordered]
                    check(theme+' '+role+' recommendations included',all(key in ordered for key in recommended))
                    shot(window,theme+'-picker-'+role)
                    if role=='primary':
                        before={k:id(c._card) for k,c in panel.cards.items() if isinstance(c,_DeferredPickerCard) and c._card is not None}
                        panel._set_filter('cloud');settle(.2)
                        check('cloud filter hides local cards',all(c.isHidden() for c in panel.cards.values() if not c.online))
                        card=panel.cards['qwen_cloud_filetrans'].materialize()
                        check('Qwen speakers start off',card.diarize is not None and not card.diarize.isChecked())
                        card.diarize.click();settle(.05)
                        check('Qwen speaker choice saved in isolated configuration',panel.controller.runtime_settings['models']['qwen_audio_diarize'] is True)
                        card.diarize.click();panel._set_filter('all');settle(.2)
                        check('visible cards retained across filtering',all(id(panel.cards[k]._card)==value for k,value in before.items()))
                    window._modal_host._request_close();wait(lambda:not window._modal_host.isVisible())

                callback_errors=[]
                def inspect_settings():
                    dialog=window.__dict__.get('_application_settings_dialog')
                    try:
                        check('settings visible and rounded',dialog is not None and dialog.isVisible() and bool(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint))
                        for index in range(dialog.navigation.count()):
                            dialog.navigation.setCurrentRow(index);settle(.08)
                            check('settings section built '+str(index),dialog.pages.currentWidget() is not None)
                            if index in (0,1,2):shot(dialog,theme+'-settings-'+str(index))
                        dialog.navigation.setCurrentRow(0);settle(.1)
                        check('settings retained value API',hasattr(dialog,'auto_save') and dialog.interval.count()==4)
                        shot(dialog,theme+'-settings-return')
                    except Exception:callback_errors.append(traceback.format_exc())
                    finally:
                        if dialog is not None:dialog.done(QDialog.DialogCode.Rejected)
                QTimer.singleShot(300,inspect_settings)
                window._open_application_settings()
                check('settings normal entry inspection completed',not callback_errors,callback_errors)

                window.media_paths=[]
                import wave
                media=output/'sample.wav'
                with wave.open(str(media),'wb') as stream:
                    stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000);stream.writeframes(b'\0\0'*16000)
                def inspect_wizard():
                    dialog=window._home_script_match_dialog
                    try:
                        check('script wizard rounded',dialog.isVisible() and bool(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint))
                        check('script wizard starts with media step',not dialog._state['media'] and not dialog._start.isEnabled())
                        shot(dialog,theme+'-script-media')
                        zone=dialog.findChild(DropZone)
                        mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(media))])
                        event=QDropEvent(QPoint(20,20),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
                        zone.dropEvent(event);settle(.1)
                        check('media drop chooses private sample',dialog._state['media']==str(media))
                        forward=next(b for b in dialog.findChildren(QPushButton) if b.text()=='下一步')
                        forward.click();dialog._script.setPlainText('第一行字幕\n第二行字幕');settle(.15)
                        check('script text preserved',dialog._script.toPlainText()=='第一行字幕\n第二行字幕')
                        labels=[w.text() for w in dialog.findChildren(QLabel)]
                        check('script line count shown',any('2 行' in text and '2 条字幕' in text for text in labels))
                        shot(dialog,theme+'-script-text')
                    except Exception:callback_errors.append(traceback.format_exc())
                    finally:dialog.done(QDialog.DialogCode.Rejected)
                QTimer.singleShot(300,inspect_wizard);open_home_script_match(window)
                check('script wizard inspection completed',not callback_errors,callback_errors)
                window.media_paths=[str(media)]
                def inspect_existing():
                    dialog=window._home_script_match_dialog
                    try:check('existing media starts at text step',dialog._script.isVisible())
                    except Exception:callback_errors.append(traceback.format_exc())
                    finally:dialog.done(QDialog.DialogCode.Rejected)
                QTimer.singleShot(300,inspect_existing);open_home_script_match(window)
                check('existing media inspection completed',not callback_errors,callback_errors)
                window.media_paths=[]

            window._open_model_workshop();settle(.5)
            page=window.workshop_page
            wait(lambda:page._ui_built and len(page._cards)>5)
            shot(window,'workshop')
            window._open_recognition_history();settle(.5)
            shot(window,'history')
        except Exception:
            code=1;(output/'audit-error.txt').write_text(traceback.format_exc(),'utf8')
            window.grab().save(str(output/'failure.png'))
        from ..diagnostics.build_identity import load_build_identity
        result=dict(passed=code==0 and bool(checks) and all(x['passed'] for x in checks),checks=checks,
            checks_passed=sum(x['passed'] for x in checks),executable=sys.executable,pid=os.getpid(),
            frozen=bool(getattr(sys,'frozen',False)),identity=load_build_identity().to_dict(),
            scope='Windows normal entry, private data and synthetic input. Provider calls, real recognition accuracy and physical drag/DPI are not measured.')
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        app.exit(0 if result['passed'] else 1)
    QTimer.singleShot(600,run)
