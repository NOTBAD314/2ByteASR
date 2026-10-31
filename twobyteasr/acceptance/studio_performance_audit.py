"""Complete-target event-driven latency audit, with optional real-screen proof."""
import copy,json,os,time,traceback,ctypes,queue
from pathlib import Path


def start(window,output):
    from PySide6.QtCore import Qt,QTimer,QEventLoop,QObject,QEvent,QPoint
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QScrollArea
    try:page=window.studio_page
    except RuntimeError:
        QTimer.singleShot(100,lambda:start(window,output));return
    from .studio_acceptance_audit import require
    from .blank_project_audit import _capture,_provider_calls
    from ..caption_style.scoped_style import effective_layer_style
    from ..studio.presentation_scope import capture_scope
    from ..timeline.selection_scope import SelectionScope
    from ..projects.studio_runtime_state import StateTransaction
    from ..projects import studio_save
    from ..caption_style.bilingual_layout import companion_id
    out=Path(output);clock=time.perf_counter;visible=os.environ.get('STUDIO_PERF_VISIBLE')=='1'
    phase=os.environ.get('STUDIO_PERF_PHASE','batch');rounds=int(os.environ.get('STUDIO_PERF_ROUNDS','3'))
    result=dict(checks=[],operations=[],passed=False,pid=os.getpid(),visible_requested=visible,phase=phase)
    active={};events=queue.SimpleQueue()
    original_validate=StateTransaction._validate_and_commit;original_save=studio_save.save_project_revision
    def validate(transaction):
        delta=original_validate(transaction)
        if active and transaction.project is page.project:
            active.setdefault('data_commit_at',clock());active['delta_targets']=len(delta.affected_cue_ids)
        return delta
    def saved(revision,path):
        value=original_save(revision,path);events.put((clock(),value[1]));return value
    StateTransaction._validate_and_commit=validate;studio_save.save_project_revision=saved
    def receipt(): (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));receipt();require(value,name)
    def wait(predicate,seconds=90):
        if predicate():return
        loop=QEventLoop();poll=QTimer();poll.setInterval(10);limit=QTimer();limit.setSingleShot(True)
        poll.timeout.connect(lambda:loop.quit() if predicate() else None);limit.timeout.connect(loop.quit)
        poll.start();limit.start(round(seconds*1000))
        try:loop.exec()
        finally:poll.stop();limit.stop()
        require(predicate(),'performance audit timed out')
    def pause(ms):
        loop=QEventLoop();QTimer.singleShot(ms,loop.quit);loop.exec()
    class Probe(QObject):
        def eventFilter(self,obj,event):
            if active and event.type()==QEvent.Type.Paint:active.setdefault('feedback_at',clock())
            return False
    probe=Probe(window)
    def top():
        if visible:
            require(not window.isMinimized(),'visible test window was minimized; discard sample')
            from ctypes import wintypes as W
            user=ctypes.windll.user32
            user.SetWindowPos.argtypes=[W.HWND,W.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.UINT]
            require(user.SetWindowPos(int(window.winId()),ctypes.c_void_p(-1),0,0,0,0,0x53),'could not show audit window on top')
    def current_pixels():
        scene=getattr(page,'_caption_scene',None)
        if scene is None or scene.published is None or not scene.metrics:return False
        if not scene.metrics[-1].get('posted'):return False
        token=scene.last_result_token
        if token!=scene.token or token[2]!=page._revision_store.render.visual_revision:return False
        wanted=page._prepared_caption(page.selected_cue_id)
        rows=scene.metrics[-1].get('cue_pixels',())
        return bool(wanted and any(r.get('cue_id')==page.selected_cue_id and r.get('snapshot_hash')==wanted.snapshot_hash for r in rows))
    def screen_matches(color):
        if not visible:return True
        import numpy as np
        from PySide6.QtGui import QImage
        scene=page._caption_scene;expected=scene.published.image.convertToFormat(QImage.Format.Format_RGBA8888)
        raw=np.frombuffer(expected.bits(),np.uint8).reshape(expected.height(),expected.bytesPerLine())[:,:expected.width()*4].reshape(expected.height(),expected.width(),4)
        rgb=np.array(QColor(color).getRgb()[:3],dtype=np.int16)
        mask=(raw[:,:,3]>240)&(np.abs(raw[:,:,:3].astype(np.int16)-rgb).max(axis=2)<5)
        ys,xs=np.nonzero(mask)
        active['screen_color_samples']=len(xs)
        if len(xs)<12:return False
        pick=np.linspace(0,len(xs)-1,min(96,len(xs))).astype(int);xs=xs[pick];ys=ys[pick]
        screen=window.screen();image=screen.grabWindow(0).toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        actual=np.frombuffer(image.bits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*4].reshape(image.height(),image.width(),4)
        x,y,w,h=scene.last_result_token[-4:];origin=page.video.mapToGlobal(QPoint(x,y));geo=screen.geometry()
        scale=image.width()/geo.width()
        px=np.clip(((origin.x()-geo.x()+((xs+.5)/expected.width())*w)*scale).astype(int),0,image.width()-1)
        py=np.clip(((origin.y()-geo.y()+((ys+.5)/expected.height())*h)*scale).astype(int),0,image.height()-1)
        # The compositor resamples the 1280px scene into a fractional-DPI
        # viewport. Accept a one-physical-pixel neighbourhood, not nearby UI.
        matches=[]
        for dy in (-1,0,1):
            for dx in (-1,0,1):
                near=actual[np.clip(py+dy,0,image.height()-1),np.clip(px+dx,0,image.width()-1),:3]
                matches.append((np.abs(near.astype(np.int16)-rgb).max(axis=1)<30))
        fraction=float(np.any(matches,axis=0).mean())
        active['screen_match_fraction']=fraction
        active['screen_mapping']=[origin.x(),origin.y(),w,h,scale,expected.width(),expected.height()]
        return fraction>=.70
    def measure(name,control,action,*,scope=None,color=None,commit=True,pixels=True):
        top()
        parent=control.parentWidget()
        while parent is not None:
            if isinstance(parent,QScrollArea):parent.ensureWidgetVisible(control);break
            parent=parent.parentWidget()
        pause(100)
        active.clear();active.update(name=name,started=clock())
        if scope:
            active.update(scope=scope.scope,layer=scope.layer,eligible=len(scope.cue_ids),locked=len(scope.locked_ids),missing=len(scope.missing_layer_ids))
        control.installEventFilter(probe);gaps=[];last=[clock()];pulse=QTimer();pulse.setInterval(16)
        def beat():
            now=clock();gaps.append((now-last[0])*1000);last[0]=now
        pulse.timeout.connect(beat);pulse.start()
        try:
            action();active['handler_return_at']=clock()
            if name.startswith('E_'):
                wait(lambda:page.subtitle_edit_input.isVisible() and page.subtitle_edit_input.hasFocus(),10)
                active['input_ready_at']=clock()
            wait(lambda:not getattr(page,'_style_application_busy',False) and (not commit or 'data_commit_at'in active),120)
            active['all_data_done_at']=clock()
            if pixels:
                wait(current_pixels,30);active['overlay_correct_at']=clock()
                if color and visible:
                    wait(lambda:current_pixels() and screen_matches(color),15)
                    active['visible_correct_at']=clock()
            pause(35)
            pulse.stop()
            while not events.empty():
                at,phases=events.get();active['persisted_at']=at;active['save_phases']=phases
            row=dict(active);row['max_gui_gap_ms']=max(gaps,default=0)
            for key,value in list(row.items()):
                if key.endswith('_at'):row[key[:-3]+'_ms']=(value-row['started'])*1000
            row.pop('started',None)
            result['operations'].append(row);receipt()
            if color and visible:window.screen().grabWindow(0).save(str(out/(name+'-screen.png')))
            return row
        except BaseException:
            result['failed_sample']=dict(active)
            if visible:
                window.screen().grabWindow(0).save(str(out/'failed-screen.png'))
                page._caption_scene.published.image.save(str(out/'failed-overlay.png'))
            raise
        finally:
            pulse.stop();control.removeEventFilter(probe);active.clear()
    def scope_to(kind):
        button=page.style_scope._buttons[page.style_scope.findData(kind)]
        QTest.mouseClick(button,Qt.MouseButton.LeftButton,pos=QPoint(button.width()-3,button.height()//2))
        wait(lambda:not getattr(page,'_style_application_busy',False),120)
    def choose_preset():
        combo=page.style_preset;index=combo.findData('user-c969b5795c64')
        require(index>=0,'actual stored preset not loaded')
        combo.setCurrentIndex(index);combo.activated.emit(index)
    def execute():
        try:
            wait(lambda:page.project is not None and page._readiness.ready,120)
            window.showNormal();window.resize(1600,950)
            if visible:window.move(60,30)
            top();QApplication.setActiveWindow(window)
            p=page.project;page.video.set_paused(True);page._activate_filter('all')
            result['project']=dict(id=p.project_id,originals=len(p.cues),translations=len(p.generation_metadata.get('translations',{})),speakers=len(p.speakers),dpr=window.devicePixelRatioF())
            result['cold_interactive_ms']=(clock()-page._studio_startup_started_perf)*1000
            wait(lambda:hasattr(p,'_qc_result'),120)
            cue=p.cues[min(10,len(p.cues)-1)]
            page.select_cue(cue.id);page._seek((cue.start_ms+150)/1000)
            page.timeline.set_visible_window(max(0,cue.start_ms-3000),24000)
            page.context_drawer.setCurrentIndex(1);pause(500);wait(current_pixels,60)
            if phase in ('batch','all'):
                for kind_index,kind in enumerate(('all','speaker','selected')):
                    page.cue_controller.apply_selection_scope(SelectionScope.explicit([c.id for c in p.cues[5:17]],cue.id))
                    scope_to(kind)
                    for turn in range(rounds):
                        value=('#FF%02X%02X%02X'%(37+turn*41+kind_index*7,91+turn*31,179-turn*29))
                        scope=capture_scope(page);wanted=set(scope.cue_ids)
                        old={c.id:QColor(effective_layer_style(p,c,'original').outline_color).rgba() for c in p.cues}
                        translated={c.id:QColor(effective_layer_style(p,c,'translation').outline_color).rgba()for c in p.cues if p.generation_metadata.get('translations',{}).get(c.id)}
                        row=measure('color_'+kind,page.style_outline_swatch,lambda:page._set_style_color(page.style_outline_color,value),scope=scope,color=value)
                        after={c.id:QColor(effective_layer_style(p,c,'original').outline_color).rgba()for c in p.cues}
                        check('color_targets_'+kind,all(after[k]==QColor(value).rgba() if k in wanted else after[k]==v for k,v in old.items()))
                        check('translation_isolated_'+kind,translated=={c.id:QColor(effective_layer_style(p,c,'translation').outline_color).rgba()for c in p.cues if c.id in translated})
                        row['actual_color_changes']=sum(old[k]!=after[k]for k in wanted);row['project_cues']=len(p.cues)
                page.cue_controller.apply_selection_scope(SelectionScope.explicit([cue.id],cue.id))
                scope_to('current');measure('preset_current',page.style_preset,choose_preset,scope=capture_scope(page))
                button=page.style_scope._buttons[page.style_scope.findData('all')]
                measure('preset_expand_all',button,lambda:QTest.mouseClick(button,Qt.MouseButton.LeftButton),scope=capture_scope(page,scope='all'))
                for turn in range(rounds):
                    value=('#FF%02X%02X%02X'%(53+turn*31,107+turn*21,201-turn*23))
                    scope=capture_scope(page)
                    row=measure('color_after_preset',page.style_outline_swatch,lambda:page._set_style_color(page.style_outline_color,value),scope=scope,color=value)
                    check('color_after_preset_all',all(QColor(effective_layer_style(p,c,'original').outline_color)==QColor(value)for c in p.cues if c.id in scope.cue_ids))
                    row['actual_color_changes']=len(scope.cue_ids)
                measure('include_preset_geometry',page.style_apply_geometry,lambda:page.style_apply_geometry.setChecked(True),scope=capture_scope(page))
                check('full_cues_preserved',len(p.cues)==result['project']['originals'])
            if phase in ('single','all'):
                same_speaker=[c for c in p.cues if c.speaker_id==cue.speaker_id][:20]
                for target in same_speaker:
                    page.timeline.set_visible_window(max(0,target.start_ms-1000),10000);pause(120)
                    rect=page.timeline._active_cue_rect(target.id)
                    if rect.isEmpty():continue
                    measure('mouse_select',page.timeline,lambda point=rect.center().toPoint():QTest.mouseClick(page.timeline,Qt.MouseButton.LeftButton,pos=point),commit=False,pixels=False)
                    check('mouse_selected_target',page.selected_cue_id==target.id)
                for layer in ('original','translation'):
                    if layer=='translation' and not p.generation_metadata.get('translations'):continue
                    for turn in range(40):
                        target=p.cues[turn%len(p.cues)]
                        if layer=='translation' and not p.generation_metadata.get('translations',{}).get(target.id):continue
                        page.select_cue(target.id);page._seek((target.start_ms+min(150,max(1,(target.end_ms-target.start_ms)//2)))/1000)
                        if layer=='translation':page.timeline.select_translation(target.id)
                        else:page.timeline.set_subtitle_layer('original');page.timeline.explicit_subtitle_id=target.id
                        page.timeline.setFocus()
                        measure('E_'+layer,page.subtitle_edit_card,lambda:QTest.keyClick(page.timeline,Qt.Key.Key_E),commit=False,pixels=False)
                        check('edit_layer',page._caption_draft.target.layer==layer)
                        page.subtitle_edit_input.insertPlainText(' test')
                        if turn%2:
                            measure('confirm_'+layer,page.subtitle_edit_input,lambda:QTest.keyClick(page.subtitle_edit_input,Qt.Key.Key_Return))
                            page.undo_stack.undo();page.undo_stack.redo();page.undo_stack.undo()
                        else:QTest.keyClick(page.subtitle_edit_input,Qt.Key.Key_Escape)
                        check('editor_closed',page._canvas_editor is None)
            if phase in ('save','all'):
                def authored(project):
                    return copy.deepcopy(([(c.id,c.text,c.speaker_id,c.style_id,c.base_preset_id,c.effect_id,c.appearance_override,c.transform)for c in project.cues],
                        project.styles,project.style_recipes,project.generation_metadata.get('translations',{})))
                expected=authored(page.project)
                row=measure('formal_save',page.save_state,page.save,commit=False,pixels=False)
                check('durable_clean',page.undo_stack.isClean() and page.project_path.is_file())
                path=page.project_path;generation=page.session.generation
                t=clock();page._close_project_session('performance-save-reopen');page.open_project(path)
                wait(lambda:page.project is not None and page.session.generation>generation and page._readiness.ready,120)
                result['hot_reopen_ms']=(clock()-t)*1000
                check('reopened_complete',len(page.project.cues)==result['project']['originals'])
                check('reopened_exact_authored_state',authored(page.project)==expected)
            _capture(window,out/'final-window.png')
            check('no_provider_requests',not _provider_calls)
            result['passed']=True
        except BaseException:result['error']=traceback.format_exc()
        finally:
            StateTransaction._validate_and_commit=original_validate;studio_save.save_project_revision=original_save
            receipt()
            QApplication.instance().aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),receipt()))
            page.undo_stack.setClean();window.result_exit_code=0 if result['passed'] else 1;window.close()
    QTimer.singleShot(200,execute)
