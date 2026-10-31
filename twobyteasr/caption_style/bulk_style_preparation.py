"""Bounded background preparation; one GUI publication, latest user action wins."""
import copy
import threading
from time import perf_counter
from PySide6.QtCore import QObject,Qt,Signal
from .bulk_transform_preparation import _geometry_revision


def prepare_style_job(payload,cancel_check=None):
    revision,action,scope,geometry=payload
    from ..rendering.caption_playback_cache import _caption_source_project
    from ..projects.studio_project import StudioCue
    project=_caption_source_project(revision)
    project.cues=[StudioCue(**cue.to_dict()) for cue in revision.cues]
    command=action.command(project,scope,geometry=geometry,changed=None,cancel_check=cancel_check)
    if command is None:return None
    if hasattr(command,'changed_ids'):return dict(paint_entries=command.entries)
    return dict(before=command.before,after=command.after,styles=command.after_styles,recipes=command.after_style_recipes,
        before_styles=command.before_styles,before_recipes=command.before_style_recipes,
        before_effects=command.before_effects,effects=command.after_effects,
        group_changed=getattr(command,'group_changed',False),group_before=getattr(command,'group_before',None),
        group_after=getattr(command,'group_after',None))


class BulkStylePreparation(QObject):
    ready=Signal(int,object)

    def __init__(self,controller):
        super().__init__(controller.page)
        self.controller=controller
        self.serial=0
        self.running=False
        self.pending=None
        self.cancelled=threading.Event()
        self.submitted_at=0.
        self.current_request=None
        self.ready_result=None
        self.running_token=None
        self.ready.connect(self._receive,Qt.ConnectionType.QueuedConnection)

    def cancel(self):
        self.serial+=1
        self.pending=None
        self.current_request=None
        self.ready_result=None
        self.cancelled.set()
        page=self.controller.page
        if getattr(page,'_style_application_busy',False) and page.save_state.text().startswith('正在应用样式'):
            page.save_state.setText('样式准备已取消')
        page._style_application_busy=False
        if getattr(page,'_style_deferred_geometry_preview',False):
            page._style_deferred_geometry_preview=False;page._caption_transform_preview={}

    def submit(self,action,scope,geometry):
        page=self.controller.page
        self.serial+=1
        self.cancelled.set()
        revision=_geometry_revision(page._revision_store.authoring_render())
        self.pending=(self.serial,page.project,page.session.project_path,revision,
                      copy.deepcopy(action),scope,bool(geometry))
        self.current_request=self.pending
        self.ready_result=None
        page._style_application_busy=True
        page._style_application_error=''
        self.submitted_at=perf_counter()
        page.save_state.setText(f'正在应用样式 · {len(scope.cue_ids)} 条字幕…')
        if not self.running:self._start()

    def submit_delta(self,patch,parent,scope=None):
        from ..studio.presentation_scope import capture_scope
        from .style_application import StyleApplication
        page=self.controller.page;scope=scope or capture_scope(page)
        request=self.current_request
        if request is not None and request[4].key==parent.key and request[5]==scope:
            action=copy.deepcopy(request[4]);action.extend(patch);geometry=request[6]
        else:
            action=StyleApplication(parent.key,fields=copy.deepcopy(patch.get('fields',{})),recipe=copy.deepcopy(patch.get('recipe',{})),replay=False)
            geometry=False
        self.submit(action,scope,geometry)

    def _start(self):
        request=self.pending
        if request is None:return
        self.pending=None
        self.running=True
        self.cancelled=cancelled=threading.Event()
        token,project,path,revision,action,scope,geometry=request
        self.running_token=token
        def work():
            result={}
            try:
                from ..system.resident_worker import shared_worker
                resident=shared_worker()
                payload=(revision,action,scope,geometry)
                answer=(resident.call('twobyteasr.caption_style.bulk_style_preparation:prepare_style_job',
                    payload,cancel_check=cancelled.is_set) if resident is not None else None)
                if not cancelled.is_set():
                    result['plan']=answer if answer is not None else prepare_style_job(payload,cancel_check=cancelled.is_set)
            except Exception as exc:
                result['error']=str(exc)
            finally:
                try:self.ready.emit(token,result)
                except RuntimeError:pass  # page retired during preparation
        threading.Thread(target=work,name='caption-style-prepare',daemon=True).start()

    def _receive(self,token,result):
        if token==self.running_token:self.running=False
        if token!=self.serial:
            if self.pending is not None and not self.running:self._start()
            return
        if getattr(getattr(self.controller.page,'caption_transform_panel',None),'gesture',None) is not None:
            self.ready_result=(token,result)
            return
        request=self.current_request
        if request is None:return
        page=self.controller.page
        page._style_application_busy=False
        self.current_request=None
        publish_started=perf_counter()
        _,project,path,revision,action,scope,geometry=request
        from ..studio.presentation_scope import capture_scope,report_scope
        current=page._revision_store.render if page._revision_store is not None else None
        valid=(page.project is project and page.session.project_path==path and current is not None
            and current.visual_revision==revision.visual_revision and current.mapping_revision==revision.mapping_revision
            and self.controller._current_application() is not None
            and self.controller._current_application().key==action.key
            and capture_scope(page).cue_ids==scope.cue_ids)
        if not valid:
            page._style_application_error='工程或应用目标已变化，这次样式未提交'
            page._show_studio_hint(page._style_application_error)
            page.save_state.setText(page._style_application_error)
            page._load_style_inspector()
            return
        if result.get('error'):
            page._style_application_error='样式应用失败：'+result['error']
            page._show_studio_hint(page._style_application_error)
            page.save_state.setText(page._style_application_error)
            page._load_style_inspector()
            return
        plan=result.get('plan')
        command=None
        if plan and plan.get('paint_entries'):
            from .paint_patch import PaintPatchCommand
            command=PaintPatchCommand(project,plan['paint_entries'],page._changed)
        elif plan and plan['after']:
            from .prepared_presentation import PreparedPresentationCommand
            command=PreparedPresentationCommand(project,plan,page._changed)
        from .style_application import changed_count
        count=changed_count(command)
        if count:
            page._style_publication_owned=True
            try:page.undo_stack.push(command)
            finally:page._style_publication_owned=False
            page.ensure_active_subtitle_renderer(reason='prepared_style_application')
        if getattr(page,'_style_deferred_geometry_preview',False):
            page._style_deferred_geometry_preview=False;page._caption_transform_preview={}
            page._caption_transform_preview_serial=getattr(page,'_caption_transform_preview_serial',0)+1
        page._load_style_inspector()
        message=report_scope(page,scope,applied=count)
        page.save_state.setText(message)
        if action.replay:self.controller._remember_application_result(scope,geometry)
        page._last_style_application_metrics=dict(targets=len(scope.cue_ids),applied=count,
            publish_ms=(perf_counter()-publish_started)*1000,total_ms=(perf_counter()-self.submitted_at)*1000)

    def resume_after_gesture(self):
        if self.ready_result is None:return
        token,result=self.ready_result;self.ready_result=None
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0,lambda:self._receive(token,result))

    def defer_geometry(self,ids,language,changes,*,mode,reference_id,reset,global_mode):
        request=self.current_request
        if request is None:return False
        action=copy.deepcopy(request[4]);action.replay=False
        op=dict(ids=tuple(ids),language=language,changes=dict(changes),mode=mode,
                reference_id=reference_id,reset=reset,global_mode=global_mode)
        if action.geometry_ops and all(action.geometry_ops[-1][k]==op[k] for k in op if k!='changes'):
            action.geometry_ops[-1]['changes'].update(changes)
        else:action.geometry_ops.append(op)
        page=self.controller.page
        page._style_deferred_geometry_preview=True
        self.submit(action,request[5],request[6])
        return True
