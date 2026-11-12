"""Opt-in full-page appearance gates, including stylesheet parser failures."""
import json,os,time,traceback
from pathlib import Path
_messages=[]
_previous=None
_handler=None


def install():
    from .blank_project_audit import install_offline_guards
    install_offline_guards()
    install_messages()


def install_messages():
    global _previous,_handler
    from PySide6.QtCore import qInstallMessageHandler
    def message(kind,context,text):
        _messages.append(str(text))
        if _previous is not None:_previous(kind,context,text)
    if _handler is None:_handler=message
    previous=qInstallMessageHandler(_handler)
    if previous is not _handler:_previous=previous


def start(window,out):
    from PySide6.QtCore import QTimer,QPoint,Qt
    from PySide6.QtWidgets import QApplication,QWidget,QLabel,QFrame,QComboBox
    from ..design import theme_manager as themes
    from ..diagnostics.build_identity import load_build_identity
    app=QApplication.instance();install_messages()
    result=dict(passed=False,checks=[],samples={},themes=[],qss_errors=[],errors=[],identity=load_build_identity().to_dict(),
                executable=__import__('sys').executable,pid=os.getpid(),dpr=window.devicePixelRatioF())
    def save():(out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf-8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));save()
        if not value:raise AssertionError(name+' '+str(detail))
    def shot(name):
        from .blank_project_audit import _capture
        _capture(window,out/(name+'.png'))
    def pixel(widget,x,y):
        image=widget.grab().toImage();dpr=image.devicePixelRatio()
        return image.pixelColor(min(image.width()-1,round(x*dpr)),min(image.height()-1,round(y*dpr))).name()
    def sample(name,widget):
        result['samples'][name]=dict(object=widget.objectName(),size=[widget.width(),widget.height()],
            pixel=pixel(widget,5,max(5,widget.height()//2)),window_colour=widget.palette().window().color().name(),
            text_colour=widget.palette().windowText().color().name(),local_sheet=widget.styleSheet())
    def ready(path=None):
        page=window.built_page('studio')
        session=window.__dict__.get('_studio_loading_session')
        if page is None:return False
        if session is not None and session.view.isVisible():return False
        if path is None:return page._project_view_state=='hub'
        gate=getattr(page,'_readiness',None)
        return bool(gate is not None and gate.ready and str(page.project_path)==str(Path(path).resolve()))
    def finish(error=None):
        if error:result['errors'].append(error)
        result['qss_errors']=[m for m in _messages if 'stylesheet' in m.lower() and ('could not parse' in m.lower() or 'parse error' in m.lower())]
        result['passed']=bool(result['checks']) and not result['errors'] and not result['qss_errors']
        if os.environ.get('STYLE_REFERENCE_ROOT'):
            # Reference-only interpreted capture: do not represent its old
            # interpreter/native teardown as a packaged-app shutdown test.
            result['reference_capture_only']=True
            save()
            import ctypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.GetCurrentProcess.argtypes=[];kernel.GetCurrentProcess.restype=ctypes.c_void_p
            kernel.TerminateProcess.argtypes=[ctypes.c_void_p,ctypes.c_uint32];kernel.TerminateProcess.restype=ctypes.c_int
            kernel.TerminateProcess(kernel.GetCurrentProcess(),0 if result['passed'] else 1)
            return
        save()
        page=window.built_page('studio')
        if page is not None and page.project is not None:page.undo_stack.setClean()
        window.close()
    def flow():
        window.resize(int(os.environ.get('STYLE_AUDIT_WIDTH','1440')),int(os.environ.get('STYLE_AUDIT_HEIGHT','900')));yield 1.0
        themes.apply_theme('graphite',app);yield .2
        for theme in ('sand','grape'):
            from ..app.home_ai_widgets import AiCardView,READY
            card=window.setting_tiles['ai'];card.set_view(AiCardView(READY,service='Local fixture',model='offline',tested_at='fixture'))
            window.home_process_card.setProperty('aiLock',False)
            window.content_profile_card.setProperty('aiLock',False)
            window.content_frost.set_active(False)
            began=time.perf_counter();themes.apply_theme(theme,app)
            yield lambda:not getattr(app,'_theme_update_pending',False)
            result['themes'].append(dict(theme=theme,apply_ms=round((time.perf_counter()-began)*1000,2)))
            yield .3
            shot(theme+'-home')
            icon=card.icon_label;t=themes.theme_definition(theme)
            actual=pixel(icon,6,icon.height()//2)
            check(theme+'_home_icon_chip',actual==t.accent,[actual,t.accent])
            sample(theme+'/home-icon',icon)
            sample(theme+'/home-content',window.content_profile_card)
            sample(theme+'/home-settings',window.home_process_card)
            window.open_studio_project()
            yield lambda:ready()
            yield lambda:len([w for w in window.built_page('studio').findChildren(QWidget)
                             if w.objectName()=='recentProjectCard' and w.isVisible()])>=2
            yield .2
            page=window.built_page('studio')
            shot(theme+'-library')
            cards=[w for w in page.findChildren(QWidget) if w.objectName()=='recentProjectCard' and w.isVisible()]
            check(theme+'_library_cards',len(cards)>=2,len(cards))
            sample(theme+'/library-card',cards[0])
            sample(theme+'/library-resume',page.resume_hero)
            if os.environ.get('STYLE_REFERENCE_ROOT'):
                window._return_to_settings();yield .3
                continue
            path=Path(json.loads((out/'fixture-path.json').read_text('utf-8'))['project'])
            window.open_studio_project(str(path))
            yield lambda:ready(path)
            yield .4
            page.select_cue('c1');page.video.set_paused(True)
            yield .2
            shot(theme+'-studio')
            from ..design.soft_qss import soft_tokens
            panels=[w for w in page.context_panel.findChildren(QComboBox) if w.isVisible()]
            check(theme+'_style_fields_visible',len(panels)>0,len(panels))
            sample(theme+'/studio-field',panels[0])
            expected=soft_tokens(t).fill
            check(theme+'_studio_field_fill',pixel(panels[0],5,panels[0].height()//2)==expected,
                  [pixel(panels[0],5,panels[0].height()//2),expected])
            from ..design.presentation import button_role
            from PySide6.QtWidgets import QPushButton
            # A real late control: native inheritance must paint it without
            # manually rewriting its stylesheet or the existing descendants.
            late=QPushButton('Late style control',page.context_panel)
            late.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
            late.setObjectName('studioPrimary');button_role(late,'primary');late.resize(180,40);late.move(20,40);late.show()
            yield .1
            check(theme+'_late_primary_background',pixel(late,8,20)==t.accent,[pixel(late,8,20),t.accent])
            late.close();late.deleteLater()
            identity=(id(page.project),page.project.project_id,len(page.project.cues))
            began=time.perf_counter();themes.apply_theme('warm' if theme=='sand' else 'graphite',app)
            yield lambda:not getattr(app,'_theme_update_pending',False)
            result['themes'].append(dict(theme='studio-'+theme,apply_ms=round((time.perf_counter()-began)*1000,2)))
            check(theme+'_theme_keeps_project',identity==(id(page.project),page.project.project_id,len(page.project.cues)))
            page.undo_stack.setClean()
            page.show_project_hub(skip_dirty_guard=True)
            yield lambda:ready()
            window._return_to_settings();yield .3
        check('no_stylesheet_parse_errors',not [m for m in _messages if 'Could not parse stylesheet' in m])
        finish()
    steps=flow()
    def drive():
        try:wanted=next(steps)
        except StopIteration:return
        except Exception:finish(traceback.format_exc());return
        if callable(wanted):
            deadline=time.monotonic()+90
            def poll():
                try:
                    if wanted():QTimer.singleShot(20,drive)
                    elif time.monotonic()>deadline:finish('Timed out waiting for actual page readiness')
                    else:QTimer.singleShot(25,poll)
                except Exception:finish(traceback.format_exc())
            QTimer.singleShot(0,poll)
        else:QTimer.singleShot(round(wanted*1000),drive)
    def shutdown():result['gui_shutdown']=True;save()
    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(800,drive)
