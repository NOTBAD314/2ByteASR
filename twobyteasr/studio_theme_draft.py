"""GUI coordinator for one immutable, validated AI theme request."""
from __future__ import annotations
import json
import threading
import time
import uuid
import copy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtGui import QPixmap
from .theme_draft import ThemeDraft, canonical_theme, validate_draft_frames

from .i18n import bind_text

from .i18n import tr


def _render_failure_geometry(evidence):
    """Small, source-related geometry for repair; never send renderer logs."""
    result=dict(viewport=[1280,720],safe_fraction=[.03,.03,.97,.98])
    if not evidence:return {}
    result['opaque_coverage']=evidence.get('alpha_coverage')
    result['composed_text_passed']=evidence.get('composed_text',{}).get('passed')
    result['failed_text_cases']=[dict(duration_ms=c.get('duration_ms'),
        rects=[r.get('rect') for r in c.get('invalid_runs',[])][:4],
        composed_text_passed=c.get('composed_text',{}).get('passed'))
        for c in evidence.get('text_cases',[]) if not c.get('passed')][:4]
    return result


class StudioThemeDraftController(QObject):
    finished = Signal(str, object)
    failed = Signal(str, str, str)
    stage = Signal(str, str)
    exported = Signal(str, str)
    recoverable_failure = Signal(str, object, str, str)
    compiler_event = Signal(str, object)
    concepts_rendered = Signal(str, object)
    candidate_finished = Signal(str, object)

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.current = None
        self.last_valid = None
        self.evidence = None
        self.phase = 'EMPTY'
        self.operation = ''
        self.cancel_event = threading.Event()
        self.cancelled_candidates=set()
        self.user_cancelled = False
        self.started = time.monotonic()
        self.last_output = self.started
        self.error = ''
        self.category = ''
        self.detail = ''
        self.events = []
        self.animation_error = ''
        self.animation_metrics = {}
        self.design = {}
        self.concept_previews = {}
        self.output_source = 'ai'
        self.compiler_phases = {}
        self.active_stage = None
        self.generation_running = False
        self.finished.connect(self._ready)
        self.failed.connect(self._failed)
        self.stage.connect(self._stage)
        self.exported.connect(self._exported)
        self.recoverable_failure.connect(self._recoverable_failure)
        self.compiler_event.connect(self._compiler_event)
        self.concepts_rendered.connect(self._concepts_ready)
        self.candidate_finished.connect(self._candidate_finished)
        self.candidate_attempt = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        page.destroyed.connect(lambda: self.cancel_event.set())

    def begin(self, generation, cue_id, scope='subtitle', provider='', model='', *, request_id=None):
        from .studio_design_target import DesignTarget
        from .studio_project import studio_data_root
        self.cancel_event.set()
        self._finish_candidate_attempt('stale','已开始新的字幕任务；旧恢复结果保留但不替换当前候选')
        self.page._stop_storyboard_animation()
        self.cancel_event = threading.Event()
        self.cancelled_candidates=set()
        self.user_cancelled = False
        target = getattr(self.page, '_ai_click_target', None) if request_id else None
        if target is None:
            target = DesignTarget.capture(self.page, cue_id)
        if target is None or target.cue.id != cue_id or not target.matches(self.page):
            raise ValueError('设计对象已改变或删除，请重新选择字幕')
        self.target = target
        self.applied_target = None
        cue = target.cue
        speaker = next((s.name for s in self.page.project.speakers if s.id==cue.speaker_id), '')
        self.current = ThemeDraft(request_id or uuid.uuid4().hex, generation, cue_id, cue.text, speaker,
                                  scope, provider, model)
        self.project = self.page.project
        self.root = studio_data_root()/'logs/theme-drafts'/self.current.request_id
        self.operation = self.current.request_id+'/provider'
        self.provider_operation = self.operation
        self.generation_running = True
        self.staged_generation = False
        self.phase = 'PROVIDER'
        self.evidence = None
        self.error = self.category = ''
        self.events = []
        self.animation_error = ''
        self.animation_metrics = {}
        self.last_export = ''
        self.design = {}
        self.concept_previews = {}
        self.output_source = 'ai'
        self.compiler_phases = {}
        self.active_stage = None
        self.instruction = str(getattr(self.page, '_ai_last_instruction', ''))
        self.request_project = copy.deepcopy(target.project_snapshot)
        from .provider_registry import GLOBAL_PROVIDER_REGISTRY
        self.settings = copy.deepcopy(GLOBAL_PROVIDER_REGISTRY.settings())
        models=self.settings.get('models',{})
        from .theme_generation_policy import ThemeGenerationLimits
        self.provider_budget=ThemeGenerationLimits.from_settings(models).theme
        self.apply_targets = None
        self.preserve_manual_overrides = False
        self.auto_apply = False
        self.page._pending_web_theme = None
        self.page._show_studio_hint('')
        self._set_phase('PROVIDER', '等待当前模型输出')
        self.task_started=self.started
        return self.current

    def _compiler_event(self, operation, event):
        if (operation != self.provider_operation or self.cancel_event.is_set()
                or not self.generation_running or self.page.project is not self.project):return
        if not self._accept_target():return
        event = copy.deepcopy(event)
        self.compiler_phases[event['request_id']] = event
        self.active_stage = event
        if 'partial_concepts' in event:
            self.staged_generation=True
            completed=event['partial_concepts']
            old_signature=[(c['id'],c.get('technical_status'),c.get('preview_picture')) for c in self.design.get('concepts',[])]
            pending=[dict(id=r['id'],name=r['name'],composition=r['composition_family'],
                preview_picture=r.get('preview_picture'),technical_status='pending',pending=True) for r in event.get('pending_directions',[])]
            selected=self.design.get('selected_concept_id','')
            self.design=dict(schema_version=4,brief=event['brief'],concepts=completed+pending,selected_concept_id=selected)
            previews={c['id']:c['preview_picture'] for c in completed+pending if c.get('preview_picture')}
            signature=[(c['id'],c.get('technical_status'),c.get('preview_picture')) for c in self.design['concepts']]
            if not self.current.theme_json and signature!=old_signature:self._concepts_ready(self.operation,previews)
            dialog=getattr(self,'_concept_dialog',None)
            if dialog is not None:dialog.set_task_states(event.get('candidate_states',{}))
            self._save_state()
            states=event.get('candidate_states',{})
            active=next((s for s in states.values() if s.get('status') in {'running','repairing'}),{})
            if active:
                self.active_stage=dict(active.get('activity') or event,label=active.get('stage',event['label']),
                    task_budget=event.get('task_budget',{}),task_started_monotonic=event['started_monotonic'])
        self.last_output = event.get('last_output_monotonic') or self.started
        attempt=self.candidate_attempt
        dialog=getattr(self,'_concept_dialog',None)
        if attempt and dialog is not None:
            dialog.set_task_states({attempt.value['candidate_id']:dict(status='running',activity=event)})
        self.detail = event['label'] + (' · 此步骤完成' if event['status']=='complete' else '')
        if event.get('design'):
            self.design = event['design']
            self.page.ai_suggestion_card.show()
            (bind_text(self.page.ai_suggestion_title, '候选方案已保存 · 准备视觉预览') if self.design.get('schema_version') == 2 else bind_text(self.page.ai_suggestion_title, '候选方案已保存 · 正在编写主题代码'))
            self.page.ai_concept_details.setPlainText(json.dumps(self.design,ensure_ascii=False,indent=2))
            self.page.ai_concept_details.show()
            self._refresh_concept_choice()
        self._save_state()
        self._tick()

    def provider_request_current(self, operation, generation, cancel):
        """Thread-safe identity reads shared by generation and one-shot repair."""
        return bool(not cancel.is_set() and self.provider_operation == operation and self.generation_running
                    and self.current is not None and self.current.generation == generation
                    and self.page._ai_request_generation == generation
                    and self.page.project is self.project
                    and not getattr(self.page, '_close_requested', False))

    def _refresh_concept_choice(self):
        combo=getattr(self.page,'ai_concept_choice',None)
        if combo is None:return
        combo.blockSignals(True)
        try:
            combo.clear()
            for c in self.design.get('concepts',[]):
                combo.addItem(c['name']+(' · 技术未通过' if c.get('technical_status')=='failed' else ''),c['id'])
                if c.get('technical_status')=='failed':combo.model().item(combo.count()-1).setEnabled(False)
            combo.setCurrentIndex(combo.findData(self.design.get('selected_concept_id')))
            combo.setVisible(combo.count()>0)
        finally:combo.blockSignals(False)

    def select_concept(self, concept_id):
        if self.phase in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'}:return
        if any(c['id']==concept_id and c.get('technical_status')!='failed' for c in self.design.get('concepts',[])):
            self.design['selected_concept_id']=concept_id
            self._actions()
            self._save_state()

    def _render_concepts(self):
        from .theme_art_direction_v2 import preview_theme
        self.page.ai_suggestion_card.show()
        self.cancel_event=threading.Event()
        self.operation=self.current.request_id+'/concept-previews/'+uuid.uuid4().hex
        operation=self.operation;cancel=self.cancel_event
        design=copy.deepcopy(self.design);text=self.current.text
        only=self.candidate_attempt.value['candidate_id'] if self.candidate_attempt else None
        folder=self.root/'concept-previews';folder.mkdir(parents=True,exist_ok=True)
        self._set_phase('CONCEPT_PREVIEW','正在绘制候选的真实预览')
        def work():
            from .renderer_service import RendererService
            from .web_theme import theme_archive_html
            service=RendererService();previews={}
            try:
                for concept in design['concepts']:
                    if cancel.is_set():return
                    if only and concept['id']!=only:continue
                    if concept.get('technical_status') in {'failed','pending'}:continue
                    try:
                        if concept.get('creative_version'):
                            from .authored_preview import render_candidate_preview
                            receipt=render_candidate_preview(concept,folder/concept['id'],text,
                                cancel_check=cancel.is_set,progress=lambda text:self.stage.emit(operation,text))
                            previews[concept['id']]=receipt['picture']
                            previews.setdefault('_motion',{})[concept['id']]=receipt['motion']
                            previews.setdefault('_receipts',{})[concept['id']]=receipt
                            continue
                        theme=concept.get('authored_theme') or preview_theme(concept)
                        html=theme_archive_html(theme,sample_text=text,duration_seconds=6,auto_replay=False)
                        (folder/(concept['id']+'.html')).write_text(html,encoding='utf8')
                        service.live_set(html,width=1920,height=1080)
                        image=service.live_pause(cue_ms=1500,stage_ms=1500)
                        path=folder/(concept['id']+'.png');path.write_bytes(image)
                        from PIL import Image
                        bitmap=Image.open(path).convert('RGBA');bounds=bitmap.getchannel('A').getbbox()
                        detail=folder/(concept['id']+'-detail.png')
                        if bounds:
                            bitmap.crop((max(0,bounds[0]-45),max(0,bounds[1]-35),min(bitmap.width,bounds[2]+45),min(bitmap.height,bounds[3]+35))).save(detail)
                        previews[concept['id']]=str(detail if bounds else path)
                    except Exception as exc:
                        if cancel.is_set():return
                        previews.setdefault('_failures',{})[concept['id']]=dict(
                            actual=str(exc),category=getattr(exc,'category','runtime_render'),
                            geometry=_render_failure_geometry(getattr(exc,'render_evidence',{})))
                        # A broken worker is restarted for the next independent
                        # candidate; already written previews remain intact.
                        service.shutdown();service=RendererService()
                if not cancel.is_set():self.concepts_rendered.emit(operation,previews)
            except Exception as exc:
                if not cancel.is_set():self.failed.emit(operation,str(exc),'concept_preview_error')
            finally:service.shutdown()
        threading.Thread(target=work,daemon=True,name='theme-direction-previews').start()

    def _concepts_ready(self,operation,previews):
        if operation!=self.operation or self.cancel_event.is_set() or self.page.project is not self.project:return
        if not self._accept_target():return
        previews=dict(previews)
        motions=previews.pop('_motion',{})
        receipts=previews.pop('_receipts',{})
        failures=previews.pop('_failures',{})
        for concept in self.design.get('concepts',[]):
            if concept['id'] in motions:concept['motion_preview']=motions[concept['id']]
            if concept['id'] in receipts:
                receipt=receipts[concept['id']]
                concept.update(preview_picture=receipt['picture'],full_frame_preview=receipt['full_frame'],preview_receipt=receipt)
            if concept['id'] in failures:
                failure=failures[concept['id']]
                if not isinstance(failure,dict):failure=dict(actual=str(failure),category='runtime_render')
                concept.update(technical_status='failed',preview_failed=True,technical_errors=[dict(
                    path='rendered_preview',category=failure['category'],actual=failure['actual'],
                    geometry=failure.get('geometry',{}),
                    constraint='Browser must render this candidate before it can be selected')])
                if concept.get('creative_version'):
                    from .caption_creative_pipeline import ThemeLedger
                    ledger=ThemeLedger.open(concept['ledger_path'])
                    ledger.value.setdefault('candidate_failures',[]).append(dict(id=concept['id'],errors=concept['technical_errors']))
                    ledger.save()
        self.concept_previews.update(previews)
        previews=dict(self.concept_previews)
        running=self.generation_running
        self.page._ai_request_active=running
        if not running:self.page._ai_cancel_event=None
        (bind_text(self.page.ai_generate, '取消生成') if running else bind_text(self.page.ai_generate, '生成字幕设计'));self.page._show_ai_progress_bar(running)
        if any(c.get('creative_version') for c in self.design.get('concepts',[])):
            from .caption_creative_pipeline import reviewed_concepts
            for concept in self.design['concepts']:
                concept.pop('preview_integrity_error',None)
                concept.pop('preview_integrity_verified',None)
                if concept.get('technical_status') in {'failed','pending'}:continue
                try:
                    reviewed_concepts([concept],raw_user_prompt=self.page.ai_prompt.toPlainText(),allow_partial=True)
                    concept['preview_integrity_verified']=True
                except (ValueError,OSError,KeyError) as exc:
                    # A stale file for one version cannot disable healthy peers.
                    concept['preview_integrity_error']=str(exc)
            from .caption_creative_pipeline import ThemeLedger
            for concept in self.design['concepts']:
                if concept.get('technical_status') in {'failed','pending'}:continue
                ledger=ThemeLedger.open(concept['ledger_path'])
                concept['visual_review']=next(c for c in ledger.value['candidates'] if c['id']==concept['id']).get('visual_review',{})
        if self.candidate_attempt and not self.generation_running:
            from .candidate_attempt import revision,primary_action
            revised=next((c for c in self.design.get('concepts',[]) if c['id']==self.candidate_attempt.value['candidate_id']),{})
            if primary_action(revised)[0]=='adopt':
                self._finish_candidate_attempt('ready','恢复完成，已更新此候选；可查看并采用',result_revision=revision(revised))
            else:
                reason=revised.get('preview_integrity_error') or '；'.join(str(e.get('actual') or e.get('constraint','')) for e in revised.get('technical_errors',[]))
                self._finish_candidate_attempt('failed','恢复未完成：'+(reason or '尚未取得可验证的完整预览'))
        ready=sum(c.get('technical_status')!='failed' and not c.get('preview_integrity_error') and (c.get('motion_preview',{}).get('status')=='motion_ready'
                  or not c.get('creative_version') and c['id'] in previews)
                  for c in self.design.get('concepts',[]))
        total=len(self.design.get('concepts',[]))
        modern=any(c.get('creative_version') for c in self.design.get('concepts',[]))
        summary=f'{ready}/{total} 稿完整动画可预览' if modern else f'{ready}/{total} 稿旧版方向图可预览'
        (bind_text(self.page.ai_suggestion_title, summary) if ready else bind_text(self.page.ai_suggestion_title, '暂无可用预览 · 原稿已保存'))
        self.page.ai_preview.setPlainText(summary+'。'+('查看画面后可主动采用；语义视觉审查状态单独显示。' if ready
            else '请展开候选详情，修复此稿或重做该方向；已有工程样式不变。'))
        if ready:self._set_phase('CHOOSING',summary+(' · 其余方向继续生成' if running else ' · 等待选择'))
        elif running:self._set_phase('PROVIDER','候选正在生成 · 可分别取消')
        elif self.phase!='VISUAL_REVIEW':self._set_phase('VISUAL_REVIEW','候选预览未完成 · 可分别重试')
        self.page.ai_suggestion_card.show();self._refresh_concept_choice()
        from .theme_concept_dialog import ThemeConceptDialog
        old=getattr(self,'_concept_dialog',None)
        if old is not None:
            old.update_concepts(self.design['concepts'],previews)
            if not old.isVisible():old.show()
            return
        dialog=ThemeConceptDialog(self.design['concepts'],previews,self.page)
        self._concept_dialog=dialog
        dialog.retry_requested.connect(self.retry_technical_candidate)
        dialog.recovery_requested.connect(lambda key,mode:self.retry_technical_candidate(key,recovery_mode=mode))
        dialog.refine_requested.connect(self.refine_candidate)
        dialog.redo_requested.connect(self.redo_candidate)
        dialog.cancel_requested.connect(self.cancel_candidate)
        def accept():
            selected=next(c for c in self.design['concepts'] if c['id']==dialog.selected_id)
            from .candidate_attempt import revision
            if getattr(dialog,'selected_revision','')!=revision(selected):
                dialog.show_action_feedback(selected['id'],'候选版本已更新，请检查当前预览后重新采用');dialog.show();return
            if selected.get('technical_status')=='failed':return
            # Choosing a reviewed direction is the user's apply action. Keep
            # generation itself non-destructive; only this explicit click opts in.
            self.auto_apply = True
            self.apply_targets = None
            if selected.get('creative_version'):
                from .caption_creative_pipeline import ThemeLedger
                ledger=ThemeLedger.open(selected['ledger_path'])
                row=next(c for c in ledger.value['candidates'] if c['id']==selected['id'])
                row['user_selection']=dict(source_hash=row['generated_source_hash'],
                    preview_hash=row['rendered_preview_hash'],at=time.time(),action='choose_direction')
                ledger.save()
            if self.generation_running:
                # Adopt the completed immutable version without cancelling the
                # other candidate requests or changing their task generation.
                self.design['selected_concept_id']=selected['id']
                self.current=self.current.with_theme(selected['authored_theme'],selected['ledger_path'])
                self.operation=self.current.request_id+'/selected/'+uuid.uuid4().hex
                draft=self.current;operation=self.operation;cancel=self.cancel_event
                self._set_phase('RENDERING','检查所选稿件 · 其他方向继续生成')
                def validate_selected():
                    try:
                        evidence=validate_draft_frames(draft,self.root/'selected'/uuid.uuid4().hex,
                            cancel_check=cancel.is_set,deadline_seconds=90)
                        if not cancel.is_set():self.finished.emit(operation,evidence)
                    except Exception as exc:
                        if not cancel.is_set():self.failed.emit(operation,str(exc),'render_validation')
                threading.Thread(target=validate_selected,daemon=True,name='selected-candidate-validation').start()
                return
            self._set_phase('CHOOSING','已采用方向，正在应用到当前字幕')
            self.select_concept(dialog.selected_id);self._refresh_concept_choice()
            if selected.get('authored_theme'):
                self.current=self.current.with_theme(selected['authored_theme'],selected.get('ledger_path',''))
                self.render()
            else:
                self.retry_theme_code()
        dialog.accepted.connect(accept);dialog.show()

    def refine_candidate(self,candidate_id):
        from PySide6.QtWidgets import QInputDialog
        feedback,ok=QInputDialog.getMultiLineText(self.page,'美术改版字幕方向',
            '保留当前框体、角色、构图和动效，说明要增强的框体及文字表面质感（如显像、阴刻或霜面）。动作或比例需要改变时使用“重做这个方向”并写明保护项；已采用稿也可用“修复动画”。原稿保留：')
        if ok and feedback.strip():self.retry_technical_candidate(candidate_id,feedback.strip(),art_revision=True)

    def redo_candidate(self,candidate_id):
        from PySide6.QtWidgets import QInputDialog
        feedback,ok=QInputDialog.getMultiLineText(self.page,'重做这个方向',
            '说明要改变的创作方向，以及必须保留的结构和动作。默认设计有背景框、字面材质和主题动作的抽象字幕；历史角色仅按本次明确保护项保留。其他候选与原稿保留：')
        if ok and feedback.strip():self.retry_technical_candidate(candidate_id,feedback.strip(),full_redo=True)

    def retry_technical_candidate(self,candidate_id,feedback=None,*,full_redo=False,art_revision=False,recovery_mode='continue'):
        from .candidate_attempt import CandidateAttempt
        candidate=next((c for c in self.design.get('concepts',[]) if c['id']==candidate_id),None)
        def reject(reason):
            if hasattr(self,'root'):
                CandidateAttempt(self.root,self.current.request_id if self.current else '',candidate or {'id':candidate_id},recovery_mode,accepted=False,reason=reason)
            self._candidate_feedback(candidate_id,reason)
            return False
        if self.generation_running:
            return reject('已有生成/恢复任务在运行，未重复发送；可继续等待或停止并保留')
        if self.phase in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'}:
            return reject('正在进行'+self.phase+'，未重复建立任务；请等当前步骤结束')
        if not candidate:return reject('候选已不存在，请重新打开当前候选列表')
        if self.current is None or not self._target_current():return reject('字幕或工程对象已改变，请重新选择字幕')
        if recovery_mode not in {'continue','implementation','preview','rebuild'}:return reject('不支持此恢复操作')
        if recovery_mode=='continue' and candidate.get('authored_theme') and not feedback:
            from .candidate_attempt import primary_action
            if primary_action(candidate)[0]=='preview':recovery_mode='preview'
        if recovery_mode=='preview':
            from .web_theme import WebThemeDocument
            try:WebThemeDocument.from_dict(candidate.get('authored_theme',{}))
            except ValueError as exc:
                return reject('当前源码尚未通过检查，请先修复：'+str(exc))
            self.candidate_attempt=CandidateAttempt(self.root,self.current.request_id,candidate,'preview')
            self._candidate_feedback(candidate_id,'已接受：使用已保存源码重建预览，零模型调用',busy=True)
            for key in ('motion_preview','preview_integrity_error','preview_failed','technical_errors','technical_status'):
                candidate.pop(key,None)
            self._render_concepts();return True
        if recovery_mode=='continue' and candidate.get('preview_integrity_error') and not feedback:
            # Derived files/fingerprints are rebuilt from the same saved source,
            # never repaired with a model just because a GIF is absent.
            from .web_theme import WebThemeDocument
            try:WebThemeDocument.from_dict(candidate.get('authored_theme',{}))
            except ValueError as exc:
                return reject('当前源码尚未通过检查，请先修复：'+str(exc))
            candidate.pop('motion_preview',None);candidate.pop('preview_integrity_error',None)
            self.candidate_attempt=CandidateAttempt(self.root,self.current.request_id,candidate,'preview')
            self._candidate_feedback(candidate_id,'已接受：重新生成当前源码预览',busy=True)
            self._render_concepts();return True
        if candidate.get('technical_status')!='failed' and not feedback and recovery_mode not in {'implementation','rebuild'}:
            return reject('当前候选没有待修复错误；可采用，或在更多操作中重新生成')
        categories={error.get('category') for error in candidate.get('technical_errors',[])}
        if recovery_mode=='continue' and candidate.get('preview_failed') and not feedback and 'render_validation' in categories:
            feedback='仅修复这份源码已经复现的画面校验失败，保留框体、材质、字体和完整进出场，不删正文或装饰。具体错误：'+ '；'.join(
                str(error.get('actual') or error.get('constraint') or '')+'；几何：'+json.dumps(error.get('geometry',{}),ensure_ascii=False)
                for error in candidate.get('technical_errors',[]))[:3000]
        if recovery_mode=='continue' and candidate.get('preview_failed') and not feedback and categories and categories <= {'render_timeout','browser_startup','render_error'}:
            # Retry transient render failures locally only if the current
            # source passes today's preflight. Bad tracks enter scoped repair.
            from .web_theme import WebThemeDocument
            try:WebThemeDocument.from_dict(candidate.get('authored_theme',{}))
            except ValueError:pass
            else:
                candidate.pop('preview_failed',None);candidate.pop('technical_status',None);candidate.pop('technical_errors',None)
                self.candidate_attempt=CandidateAttempt(self.root,self.current.request_id,candidate,'preview')
                self._candidate_feedback(candidate_id,'已接受：本地重建预览，零模型调用',busy=True)
                self._render_concepts();return True
        self.candidate_attempt=CandidateAttempt(self.root,self.current.request_id,candidate,recovery_mode)
        self._candidate_feedback(candidate_id,'已接受恢复任务 '+self.candidate_attempt.value['attempt_id'][:8]+' · 原版本保留',busy=True)
        self.cancel_event=threading.Event();cancel=self.cancel_event
        self.operation=self.current.request_id+'/candidate-retry/'+uuid.uuid4().hex
        operation=self.operation;draft=self.current
        self.provider_operation=operation
        self.generation_running=True
        retained_concepts=copy.deepcopy(self.design.get('concepts',[]))
        self.active_stage=None;self.started=time.monotonic()
        folder=self.root/'candidate-retries'/uuid.uuid4().hex
        self.page._ai_request_active=True;self.page._ai_cancel_event=cancel
        (bind_text(self.page.ai_generate, '取消美术改版') if full_redo or art_revision else (bind_text(self.page.ai_generate, '取消局部微调') if feedback else bind_text(self.page.ai_generate, '取消局部修复')))
        self.page._show_ai_progress_bar(True)
        self._set_phase('PROVIDER',tr('{value0}候选 {value1} · 保留其他方向', value0=tr('重新创作' if full_redo else '局部修复'), value1=candidate_id))
        self.candidate_attempt.event('running','worker已提交',operation_id=operation)
        def work():
            try:
                from .caption_creative_pipeline import retry_saved_candidate
                options=dict(ledger_root=folder,request_id=draft.request_id,
                    cancel_check=lambda:not self.provider_request_current(operation,draft.generation,cancel),
                    stage_callback=lambda text:self.stage.emit(operation,text))
                if full_redo or art_revision:
                    from .authored_visual_revision import redesign_candidate
                    options['stage_event_callback']=lambda event:self.compiler_event.emit(operation,event)
                    suggestion=redesign_candidate(candidate['ledger_path'],candidate_id,feedback,self.settings,
                        revision_kind='art_revision' if art_revision else 'redo',current_theme=candidate.get('authored_theme'),**options)
                elif feedback:
                    from .authored_visual_revision import revise_candidate
                    suggestion=revise_candidate(candidate['ledger_path'],candidate_id,feedback,self.settings,**options)
                else:suggestion=retry_saved_candidate(candidate['ledger_path'],candidate_id,self.settings,
                    stage_event_callback=lambda event:self.compiler_event.emit(operation,event),recovery_mode=recovery_mode,**options)
                # A child ledger may predate completed siblings. Publish only
                # the requested candidate from that ledger, retaining the
                # current immutable versions and previews of its peers.
                revised=next(c for c in suggestion.concepts if c['id']==candidate_id)
                if full_redo or art_revision:
                    # Do not replace a usable card with a new version that
                    # loses text or breaks motion after technical validation.
                    from .authored_preview import render_candidate_preview
                    receipt=render_candidate_preview(revised,folder/'preview',draft.text,
                        cancel_check=cancel.is_set,progress=lambda text:self.stage.emit(operation,text))
                    revised.update(motion_preview=receipt['motion'],preview_picture=receipt['picture'],
                        full_frame_preview=receipt['full_frame'],preview_receipt=receipt,
                        semantic_review=receipt.get('semantic_review','not_run'))
                suggestion.concepts=[revised if c['id']==candidate_id else c for c in retained_concepts]
                if not cancel.is_set():self.candidate_finished.emit(operation,suggestion)
            except Exception as exc:
                if not cancel.is_set():self.failed.emit(operation,str(exc),getattr(exc,'category','candidate_repair_error'))
        threading.Thread(target=work,daemon=True,name='theme-candidate-repair').start()
        return True

    def _candidate_feedback(self,key,message,*,busy=False):
        self.page._show_studio_hint(message)
        if self.candidate_attempt:
            candidate=next((c for c in self.design.get('concepts',[]) if c['id']==key),None)
            if candidate is not None:candidate['latest_attempt']=dict(self.candidate_attempt.value,path=str(self.candidate_attempt.path))
        dialog=getattr(self,'_concept_dialog',None)
        if dialog is not None:dialog.show_action_feedback(key,message,busy=busy)

    def _finish_candidate_attempt(self,status,message,**fields):
        attempt=self.candidate_attempt
        if attempt is None:return
        attempt.event(status,message,**fields)
        self._candidate_feedback(attempt.value['candidate_id'],message)
        dialog=getattr(self,'_concept_dialog',None)
        if dialog is not None:dialog.set_task_states({attempt.value['candidate_id']:dict(status=status,detail=message)})
        self.candidate_attempt=None

    def _candidate_finished(self,operation,suggestion):
        if operation!=self.operation or self.cancel_event.is_set():return
        self.receive(self.current.generation,self.current.cue_id,suggestion)

    def cancel_candidate(self,key):
        if self.candidate_attempt and self.candidate_attempt.value['candidate_id']==key:
            self.cancel()
        elif self.generation_running:
            self.cancelled_candidates.add(key)
            self._candidate_feedback(key,'已接受取消；已收到内容保留，供应商端状态未知')
        else:self._candidate_feedback(key,'此候选当前没有运行中的任务')

    def use_local_template(self):
        if self.current is None or self.phase in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'}:return
        from .local_subtitle_theme import local_subtitle_theme
        try:theme=local_subtitle_theme(self.design)
        except ValueError as exc:self.page._show_studio_hint(str(exc));return
        self.output_source='local_template'
        self.current=self.current.with_theme(theme)
        bind_text(self.page.ai_suggestion_title, '本地模板降级 · {value0}', value0=theme['name'])
        self.auto_apply=False
        self.render()

    def retry_theme_code(self):
        if self.generation_running:return
        saved=getattr(self,'root',Path())/'creative'/'ledger.json'
        if self.phase=='FAILED' and not self.design and saved.is_file():
            self.continue_saved_response(saved)
            return
        if (self.current is None or not (self.design.get('concepts') or self.design.get('brief'))
                or self.phase in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW','VISUAL_REVIEW'}
                or self.page.project is not self.project):return
        from .studio_ai import request_web_theme_design
        self.cancel_event.set()
        self.cancel_event = threading.Event()
        cancel = self.cancel_event
        self.page._ai_request_generation += 1
        self.current = replace(self.current,generation=self.page._ai_request_generation)
        draft = self.current
        self.operation = draft.request_id+'/provider/'+uuid.uuid4().hex
        self.provider_operation = self.operation
        self.generation_running = True
        operation = self.operation
        design = copy.deepcopy(self.design)
        raw_user_prompt=self.page.ai_prompt.toPlainText()
        hero_pending = any(c.get('design') and not c.get('hero_theme') for c in design.get('concepts', []))
        self.active_stage = None
        self.error = self.category = ''
        self.output_source='ai'
        self.page._ai_request_active = True
        self.page._ai_cancel_event = cancel
        self.page.ai_generate.setEnabled(True)
        bind_text(self.page.ai_generate, '取消生成')
        self.page._show_ai_progress_bar(True)
        self._set_phase('PROVIDER','重试静态英雄帧 · 保留已完成方向' if hero_pending else '重试主题代码 · 保留已有候选')
        def work():
            try:
                def validate(theme, seconds):
                    return validate_draft_frames(draft.with_theme(theme),self.root/'compiler'/uuid.uuid4().hex,
                        cancel_check=cancel.is_set,deadline_seconds=seconds,
                        progress=lambda text:self.stage.emit(operation,text))
                result=request_web_theme_design(self.request_project,draft.cue_id,self.instruction,self.settings,
                    effect_scope=draft.scope,request_id=draft.request_id,render_validator=validate,
                    resume_design=design,cancel_check=lambda:not self.provider_request_current(operation,draft.generation,cancel),raw_user_prompt=raw_user_prompt,
                    concepts_only=not bool(design.get('concepts')) or hero_pending,
                    stage_callback=lambda text:self.stage.emit(operation,text),
                    stage_event_callback=lambda event:self.compiler_event.emit(operation,event),
                    on_stream_text=lambda text:self.page.ai_stream_line_signal.emit(draft.generation,text))
                if not cancel.is_set():self.page.ai_web_theme_signal.emit(draft.generation,draft.cue_id,result)
            except Exception as exc:
                if not cancel.is_set():
                    if getattr(exc,'preview_theme',None):
                        self.recoverable_failure.emit(operation,exc.preview_theme,str(exc),getattr(exc,'category','render_error'))
                    else:self.failed.emit(operation,str(exc),getattr(exc,'category','provider_error'))
        threading.Thread(target=work,daemon=True,name='theme-code-retry').start()

    def open_saved_response(self):
        if self.generation_running:
            if self.design:self._concepts_ready(self.operation,getattr(self,'concept_previews',{}))
            return
        if self.phase in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'}:return
        from .saved_theme_tasks import SavedThemeTasksDialog,saved_tasks
        from .studio_project import studio_data_root
        dialog=SavedThemeTasksDialog(saved_tasks(studio_data_root()/'logs/theme-drafts'),self.page)
        if dialog.exec() and dialog.path:
            if dialog.resume:self.continue_saved_response(dialog.path)
            else:self.restore_saved_response(dialog.path)

    def restore_saved_response(self,path):
        from .caption_creative_pipeline import ThemeLedger
        from .authored_preview import reusable_preview
        try:
            prior=ThemeLedger.open(path);cue_id=self.page.selected_cue_id
            if not cue_id:raise ValueError('请先选择字幕')
            self.page._ai_request_generation+=1
            self.page._ai_last_instruction=prior.value['raw_user_prompt']
            self.page.ai_prompt.setPlainText(prior.value['raw_user_prompt'])
            provider=prior.value.get('provider',{})
            self.begin(self.page._ai_request_generation,cue_id,provider=provider.get('provider',''),model=provider.get('model',''))
            self.generation_running=False
            concepts=copy.deepcopy(prior.value.get('partial_concepts',[]))
            for row in prior.value.get('directions',{}).get('candidates',[]):
                if not any(c['id']==row['id'] for c in concepts):
                    concepts.append(dict(id=row['id'],name=row['name'],composition='上次未完成；可继续已保存任务',
                        technical_status='pending',pending=True))
            self.design=dict(schema_version=2,concepts=concepts,selected_concept_id='',
                brief={'raw_user_prompt':prior.value['raw_user_prompt']},quality={'ledger_path':str(path)})
            self.restored_ledger=str(path)
            previews={};needs_render=False
            for c in concepts:
                if c.get('technical_status') in {'failed','pending'}:continue
                receipt=reusable_preview(c,self.current.text)
                if receipt:
                    c.update(motion_preview=receipt['motion'],preview_picture=receipt['picture']);previews[c['id']]=receipt['picture']
                else:
                    c.pop('motion_preview',None);c.pop('preview_integrity_error',None);needs_render=True
            if needs_render:self._render_concepts()
            else:self._concepts_ready(self.operation,previews)
        except Exception as exc:
            self.generation_running=False
            self.page._show_studio_hint(tr('无法读取已保存成果：{value0}', value0=str(exc)))

    def continue_saved_response(self,path):
        if self.phase in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'} or not self.page.project:return
        from .caption_creative_pipeline import ThemeLedger,resume_saved_response
        from .provider_registry import GLOBAL_PROVIDER_REGISTRY
        try:
            prior=ThemeLedger.open(path)
            cue_id=self.page.selected_cue_id
            if not cue_id:raise ValueError('请先选择要预览的字幕')
            selection=GLOBAL_PROVIDER_REGISTRY.selection(GLOBAL_PROVIDER_REGISTRY.settings(),stage='polish')
            self.page._ai_request_generation+=1
            self.page._ai_last_instruction=prior.value['raw_user_prompt']
            self.page.ai_prompt.setPlainText(prior.value['raw_user_prompt'])
            draft=self.begin(self.page._ai_request_generation,cue_id,provider=selection.provider,model=selection.model)
        except Exception as exc:
            self.page._show_studio_hint(tr('无法继续草稿：{value0}', value0=str(exc)));return
        operation,cancel=self.operation,self.cancel_event
        self.page._ai_request_active=True;self.page._ai_cancel_event=cancel
        self.page.ai_suggestion_card.show()
        bind_text(self.page.ai_generate, '取消生成');self.page._show_ai_progress_bar(True)
        self._set_phase('PROVIDER','继续保存方向 · 将发起新实现，保留原请求与恢复记录')
        def work():
            try:
                result=resume_saved_response(path,self.request_project,cue_id,self.settings,ledger_root=self.root/'creative',
                    request_id=draft.request_id,cancel_check=lambda:not self.provider_request_current(operation,draft.generation,cancel),
                    stage_callback=lambda text:self.stage.emit(operation,text))
                if not cancel.is_set():self.page.ai_web_theme_signal.emit(draft.generation,cue_id,result)
            except Exception as exc:
                if not cancel.is_set():self.failed.emit(operation,str(exc),getattr(exc,'category','provider_error'))
        threading.Thread(target=work,daemon=True,name='theme-saved-response-retry').start()

    def receive(self, generation, cue_id, suggestion):
        if (self.current is None or generation!=self.current.generation
                or cue_id!=self.current.cue_id or (self.phase!='PROVIDER' and not self.generation_running)
                or self.page.project is not self.project or self.cancel_event.is_set()):
            return
        if not self._accept_target():return
        if suggestion.source=='concepts':
            self.generation_running=False
            self.design=dict(schema_version=suggestion.quality.get('design_version',2),brief=suggestion.brief,concepts=suggestion.concepts,
                selected_concept_id=self.design.get('selected_concept_id',''))
            self._save_state()
            if self.current.theme_json and not self.candidate_attempt:
                self.page._ai_request_active=False;bind_text(self.page.ai_generate, '生成三个方向')
                self.page._show_ai_progress_bar(False);return
            if all(c.get('motion_preview') or c.get('technical_status')=='failed' for c in suggestion.concepts):
                self._concepts_ready(self.operation,{c['id']:c['preview_picture'] for c in suggestion.concepts if c.get('preview_picture')})
            else:self._render_concepts()
            return
        if suggestion.source != 'ai':
            self._failed(self.operation, suggestion.message or '模型没有返回有效主题', 'provider_error')
            return
        self.generation_running=False
        self.current = self.current.with_theme(suggestion.theme, getattr(suggestion,'trace_path',''))
        self.design = dict(brief=getattr(suggestion,'brief',{}),concepts=getattr(suggestion,'concepts',[]),
            selected_concept_id=getattr(suggestion,'selected_concept_id',''),quality=getattr(suggestion,'quality',{}),
            repair_count=getattr(suggestion,'repair_count',0))
        self.design['schema_version']=getattr(suggestion,'quality',{}).get('design_version',1)
        evidence = getattr(suggestion,'render_evidence',None)
        if evidence and evidence.get('passed') and evidence.get('request_id')==self.current.request_id:
            self._ready(self.operation,evidence)
        else:
            self.render()

    def adopt(self, theme, cue_id, *, label='导入主题', auto_apply=True):
        self.page._ai_request_generation += 1
        self.begin(self.page._ai_request_generation, cue_id, 'fullscreen', provider='import')
        self.generation_running=False
        self.current = self.current.with_theme(theme)
        self.auto_apply = auto_apply
        self.detail = label
        self.render()
        return self.current.request_id

    def _set_phase(self, phase, detail):
        self.phase, self.detail = phase, detail
        self.started = time.monotonic()
        self.last_output = self.started
        self.events.append(dict(phase=phase,at=time.time(),detail=detail,
            operation_id=self.operation,generation=self.current.generation if self.current else None))
        self._actions()
        self.timer.start() if phase in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'} or self.generation_running else self.timer.stop()
        self._tick()
        self._save_state()

    def _actions(self):
        valid = self.is_valid() and self.phase in {'READY','APPLIED','EXPORTED'}
        for name in ('ai_apply_button','ai_save_style_button','ai_export_archive_button'):
            button = getattr(self.page,name,None)
            if button is not None: button.setEnabled(valid)
        retry = getattr(self.page,'ai_retry_render_button',None)
        if retry is not None:
            retry.setEnabled(bool(self.current and (self.current.theme_json or self.design.get('concepts'))) and self.phase not in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'})
            if self.phase=='VISUAL_REVIEW':bind_text(retry, '检查视觉审核结果')
        retry_code = getattr(self.page,'ai_retry_theme_code_button',None)
        if retry_code is not None:
            only_brief=bool(self.design.get('brief')) and not self.design.get('concepts')
            hero_pending=any(c.get('design') and not c.get('hero_theme') for c in self.design.get('concepts', []))
            (bind_text(retry_code, '重试三个方向') if only_brief else (bind_text(retry_code, '重试静态英雄帧') if hero_pending else (bind_text(retry_code, '生成所选方案') if self.phase == 'CHOOSING' else bind_text(retry_code, '重试主题代码'))))
            retry_code.setEnabled((only_brief or hero_pending or bool(self.design.get('concepts')) and (self.design.get('schema_version')!=2 or bool(self.design.get('selected_concept_id')))) and self.phase not in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'})
            if self.phase=='FAILED' and not self.design and (getattr(self,'root',Path())/'creative'/'provider-original.txt').is_file():
                bind_text(retry_code, '继续修复已保存的三稿');retry_code.setEnabled(True)
        combo=getattr(self.page,'ai_concept_choice',None)
        if combo is not None:combo.setEnabled(self.phase not in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'})
        if self.phase=='VISUAL_REVIEW':
            if retry_code is not None:retry_code.setEnabled(False)
            if combo is not None:combo.setEnabled(False)
        local=getattr(self.page,'ai_local_theme_button',None)
        if local is not None:
            from .local_subtitle_theme import supports_local_theme
            local.setEnabled(bool(self.design.get('concepts')) and supports_local_theme(self.design) and self.phase not in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'})
        cancel = getattr(self.page,'ai_cancel_render_button',None)
        if cancel is not None: cancel.setEnabled(self.generation_running or self.phase in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'})
        for button in getattr(self.page,'ai_directed_repair_buttons',[]):
            button.setEnabled(bool(self.current and self.current.theme_json) and self.phase not in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'})

    def _tick(self):
        if self.current is None: return
        elapsed = time.monotonic()-self.started
        limit = {'PROVIDER':getattr(self,'provider_budget',300), 'RENDERING':40, 'CONCEPT_PREVIEW':180, 'EXPORTING':65}.get(self.phase)
        if self.phase == 'PROVIDER' and self.active_stage:
            elapsed = time.monotonic()-self.active_stage['started_monotonic']
            # The compiler owns provider cancellation and distinguishes idle
            # from total expiry. A second GUI deadline used to cancel a live
            # CLI before its more specific error could be delivered.
            limit = None
        if limit and elapsed>limit:
            category = (self.active_stage['name'] if self.phase=='PROVIDER' and self.active_stage else self.phase.lower())+'_timeout'
            self._failed(self.operation, f'{self.detail}超过{limit}秒时限', category)
            return
        state = f'{self.detail} · {elapsed:.0f}s' if limit or self.phase=='PROVIDER' else self.detail
        if self.phase=='PROVIDER' or self.generation_running:
            active=self.active_stage or {}
            from .design_progress import compact_status
            active=dict(active)
            active.setdefault('task_started_monotonic',getattr(self,'task_started',self.started))
            state+=' · '+compact_status(active,time.monotonic())
            state+='\n'+(active.get('public_summary','')[-240:] or '当前接口未提供可展示的推理摘要')
            state+=f'\n{self.current.provider} / {self.current.model} · 请求 {active.get("request_id",self.current.request_id)}'
        metrics = self.animation_metrics
        if metrics:
            state += f" · 动画 {metrics['fps']:.1f}fps / p95 {metrics['p95_ms']:.0f}ms"
        self.page.ai_confidence.setText(state)

    def _stage(self, operation, detail):
        if operation != self.operation or self.cancel_event.is_set(): return
        # Late provider "thinking" events cannot replace a completed result.
        if self.phase not in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'} and not self.generation_running:return
        # This is a local stage message, not newly received model content.
        self.detail = detail
        if self.candidate_attempt:
            self.candidate_attempt.event('running',detail)
            self._candidate_feedback(self.candidate_attempt.value['candidate_id'],detail,busy=True)
            dialog=getattr(self,'_concept_dialog',None)
            if dialog is not None:
                key=self.candidate_attempt.value['candidate_id']
                state=copy.deepcopy(dialog.task_states.get(key,{}))
                activity=state.setdefault('activity',{})
                activity.update(local_state='本地制作步骤有响应',last_local_monotonic=time.monotonic(),production_state=detail)
                state['status']='running';dialog.set_task_states({key:state})
        self._tick()

    def render(self):
        if self.generation_running:
            if getattr(self,'concept_previews',None):self._concepts_ready(self.operation,self.concept_previews)
            return
        if self.phase=='VISUAL_REVIEW':
            self._concepts_ready(self.operation,self.concept_previews);return
        if self.current is not None and not self.current.theme_json and self.design.get('schema_version') in (2,4):
            if any(c.get('design') and not c.get('hero_theme') for c in self.design.get('concepts', [])):
                self.retry_theme_code();return
            self._render_concepts();return
        if self.current is None or not self.current.theme_json: return
        self.page._stop_storyboard_animation()
        self.animation_metrics = {}
        self.cancel_event.set()
        self.cancel_event = threading.Event()
        cancel = self.cancel_event
        draft = self.current
        self.operation = draft.request_id+'/render/'+uuid.uuid4().hex
        operation = self.operation
        output = self.root/operation.rsplit('/',1)[-1]
        self._set_phase('RENDERING','校验当前主题与六帧动画')
        self.page._ai_request_active = True
        self.page.ai_generate.setEnabled(True)
        bind_text(self.page.ai_generate, '取消生成')
        self.page.ai_suggestion_card.show()
        bind_text(self.page.ai_suggestion_title, '网页主题 · {value0}', value0=str(draft.theme.get('name', '')))
        def work():
            try:
                evidence = validate_draft_frames(draft,output,
                    cancel_check=cancel.is_set,
                    progress=lambda value:self.stage.emit(operation,value))
                if not cancel.is_set(): self.finished.emit(operation,evidence)
            except Exception as exc:
                if not cancel.is_set(): self.failed.emit(operation,str(exc),getattr(exc,'category','render_error'))
        threading.Thread(target=work,daemon=True,name='theme-draft-validation').start()

    def _ready(self, operation, evidence):
        if (self.phase not in {'PROVIDER','RENDERING'} or operation!=self.operation or self.cancel_event.is_set() or getattr(self.page,'_close_requested',False) or self.page.project is not self.project
                or evidence['content_hash']!=self.current.content_hash): return
        if not self._accept_target():return
        from .style_recipe import StyleRecipe
        if not getattr(self,'staged_generation',False):self.generation_running=False
        draft = self.current
        self.evidence = evidence
        self.last_valid = draft
        self.page._pending_web_theme = SimpleNamespace(cue_id=draft.cue_id,theme=draft.theme,
            name=draft.theme.get('name',''),request_id=draft.request_id,content_hash=draft.content_hash,
            recipe=StyleRecipe(name=draft.theme.get('name',''),engine='remotion',web_theme=draft.theme))
        frozen_pending = self.page._pending_web_theme
        self.page._ai_request_active = self.generation_running
        if not self.generation_running:self.page._ai_cancel_event = None
        self.page._set_ai_input_sections_visible(True)
        (bind_text(self.page.ai_generate, '取消生成') if self.generation_running else bind_text(self.page.ai_generate, '重新生成'))
        if not self.generation_running:self.page._finish_ai_progress_bar()
        self.page.ai_refine_row.show()
        self.page.ai_web_theme_storyboard_wrap.show()
        for label, frame in zip(getattr(self.page,'ai_storyboard_six_labels',()),evidence['frames']):
            label.setPixmap(QPixmap(frame['path']).scaled(label.size(),Qt.AspectRatioMode.KeepAspectRatio,
                                                         Qt.TransformationMode.SmoothTransformation))
            label.setToolTip(f"{frame['seconds']:.2f}s · {frame['render_ms']:.0f}ms")
        self.page.ai_preview.setPlainText(str(draft.theme.get('concept',''))+'\n'+str(draft.theme.get('notes','')))
        concepts = self.design.get('concepts',[])
        self.page.ai_concept_details.setPlainText('\n\n'.join(
            ('采用 · ' if c['id']==self.design.get('selected_concept_id') else '')+
            f"{c['id']} · {c['name']}\n{c.get('subject','技术未通过，原稿保留')}\n"
            f"{c['composition']}\n性能开销：{c.get('estimated_performance','不可用')} · 风险：{'；'.join(c.get('risks',[])) or '未报告'}"
            for c in concepts) or '导入固定主题；未重新生成设计方向')
        bind_text(self.page.ai_quality_details, '校验警告：{value0}\n{value1}', value0='；'.join(evidence.get('warnings', []) + self.design.get('quality', {}).get('sanitizer_changes', [])) or tr('未发现'), value1=evidence.get('visual_review', tr('未进行视觉模型复核')))
        checks=self.design.get('quality',{}).get('visual_review',{}).get('checks',{})
        if checks:
            from .theme_art_direction_v2 import SCORE_LABELS
            self.page.ai_quality_details.setText(self.page.ai_quality_details.text()+'\n'+'\n'.join(f"{label}：{checks[key]['evidence']}" for key,label in SCORE_LABELS.items() if key in checks))
        self._set_phase('READY',('本地模板降级 · ' if self.output_source=='local_template' else '')+'六帧校验通过 · '+evidence.get('visual_review','未进行视觉模型复核'))
        QTimer.singleShot(0,lambda:self.page._scroll_ai_panel_into_view(self.page.ai_web_theme_storyboard_wrap))
        self.page._start_web_theme_storyboard(draft.theme)
        if not self.auto_apply:
            self._save_state()
            return
        # Preserve the established generate→current cue behavior, but only
        # after this exact immutable theme has produced real valid frames.
        targets = getattr(self,'apply_targets',None) or [draft.cue_id]
        self.apply_targets = None
        self._set_phase('APPLYING','正在应用到当前字幕…')
        try:
            options={'preserve_overrides':True} if self.preserve_manual_overrides else {}
            applied = sum(bool(self.page._apply_web_theme(target,draft.theme,**options)) for target in targets)
        except Exception as exc:
            self.page._pending_web_theme = frozen_pending
            self.error,self.category=str(exc),'apply_error'
            self._set_phase('READY','草稿已验证；应用失败，可重试或导出当前草稿：'+str(exc))
            self._save_state()
            return
        self.page._pending_web_theme = frozen_pending
        if applied:
            self.record_application()
            self.bind_pending()
            self._set_phase('APPLIED','已采用并应用到当前字幕 · 可撤销')
            self.page._show_studio_hint(tr('已采用并应用到当前字幕 · 拖动选框移动，拖动角点等比缩放 · Ctrl+Z 撤销'))
        else:
            self._set_phase('READY','当前字幕无法应用；请选择有效字幕后重试应用')
            self.page._show_studio_hint(tr('草稿已验证；当前字幕应用失败，可重试应用或导出当前草稿'))

    def bind_pending(self):
        pending = getattr(self.page,'_pending_web_theme',None)
        if pending and self.current and canonical_theme(pending.theme)==self.current.theme_json:
            pending.request_id = self.current.request_id
            pending.content_hash = self.current.content_hash

    def is_valid(self):
        return bool(self.current and self.evidence and self.evidence.get('passed')
                    and self.evidence['content_hash']==self.current.content_hash
                    and self.page.project is self.project
                    and self._target_current())

    def _target_current(self):
        target = getattr(self, 'target', None)
        if target is None:
            return False
        if target.matches(self.page):
            return True
        applied = getattr(self, 'applied_target', None)
        return bool(applied and applied.matches(self.page))

    def record_application(self):
        # Own style changes form an accepted post-state, independent of a
        # transient render/export phase. Later unrelated edits still invalidate.
        from .studio_design_target import DesignTarget
        self.applied_target = DesignTarget.capture(self.page, self.current.cue_id)

    def _accept_target(self):
        if self._target_current():
            return True
        self._failed(self.operation, '设计对象已改变或删除，请重新选择字幕', 'stale_target')
        self.cancel_event.set()
        return False

    def allow_pending(self):
        pending = getattr(self.page,'_pending_web_theme',None)
        valid = self.is_valid() and pending is not None and getattr(pending,'request_id',None)==self.current.request_id
        return bool(valid and canonical_theme(pending.theme)==self.current.theme_json
                    and self.phase in {'READY','APPLIED','EXPORTED'})

    def cancel(self):
        if self.phase not in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'} and not self.generation_running: return
        self.user_cancelled = True
        self._failed(self.operation,'当前请求已取消；已应用的主题保留','cancelled')

    def invalidate(self):
        self._finish_candidate_attempt('stale','当前草稿已关闭；已完成产物保留')
        self.generation_running=False
        self.cancel_event.set()
        self.operation = uuid.uuid4().hex
        self.page._stop_storyboard_animation()
        self.page._pending_web_theme = None
        self.page._ai_request_active = False
        # Dismissing a finished request must not rewrite its terminal reason.
        if self.phase not in {'FAILED', 'CANCELLED'}:
            self._set_phase('DISMISSED','已忽略当前草稿')
        else:
            self._save_state()

    def repair(self, instruction, *, theme=None, cue_id=None, targets=None,art_revision=False,locked_paths=()):
        if self.phase in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'}: return
        from .studio_ai import refine_web_theme_design
        from dataclasses import replace
        previous = self.current
        if theme is not None:
            from .studio_commands import cue_by_id
            from .provider_registry import GLOBAL_PROVIDER_REGISTRY
            import copy
            cue=cue_by_id(self.page.project,cue_id)
            settings=copy.deepcopy(GLOBAL_PROVIDER_REGISTRY.settings())
            selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
            speaker=next((s.name for s in self.page.project.speakers if s.id==cue.speaker_id),'')
            previous=ThemeDraft('',0,cue_id,cue.text,speaker,'fullscreen',selection.provider,selection.model).with_theme(theme)
        else:
            if previous is None or not previous.theme_json:return
            settings = self.settings
        baseline=previous.theme
        if theme is not None and self.last_valid and self.last_valid.theme.get('id')==baseline.get('id'):
            baseline=self.last_valid.theme
        # Adopted themes may have been edited after this draft was generated.
        # Compare only the same theme identity; never mistake another preset
        # for a manual edit of this draft.
        from .studio_commands import cue_by_id
        current_cue=cue_by_id(self.page.project,previous.cue_id)
        recipe=self.page.project.style_recipes.get(current_cue.style_id,{})
        edited=recipe.get('webTheme',{}) if isinstance(recipe,dict) else {}
        if edited and edited.get('id')==baseline.get('id'):
            previous=previous.with_theme(edited)
        design_version=2 if 'DESIGN_V2' in str(previous.theme.get('notes','')) else 1
        reference_frames=tuple((self.evidence or {}).get('review_images',())) if self.evidence and self.evidence.get('content_hash')==previous.content_hash else ()
        self.page._ai_request_generation += 1
        generation = self.page._ai_request_generation
        self.begin(generation,previous.cue_id,previous.scope,previous.provider,previous.model)
        self.settings = settings
        self.preserve_manual_overrides = True
        self.apply_targets = list(targets or [previous.cue_id])
        self.current = replace(self.current,text=previous.text,speaker=previous.speaker)
        operation,cancel = self.operation,self.cancel_event
        self.page._ai_request_active = True
        bind_text(self.page.ai_generate, '取消生成')
        self.page._show_ai_progress_bar(True)
        def work():
            try:
                result=refine_web_theme_design(previous.theme,instruction,cue_text=previous.text,
                    speaker_name=previous.speaker,runtime_settings=settings,deadline_seconds=None if art_revision else 180,
                    reference_frames=reference_frames,design_version=design_version,
                    art_revision=art_revision,baseline_theme=baseline,locked_paths=locked_paths,
                    cancel_check=cancel.is_set,stage_callback=lambda value:self.stage.emit(operation,value))
                if cancel.is_set(): return
                if result.source != 'refined': raise RuntimeError(result.message)
                result.source = 'ai'
                result.quality={'design_version':design_version}
                self.page.ai_web_theme_signal.emit(generation,previous.cue_id,result)
            except Exception as exc:
                if not cancel.is_set():self.failed.emit(operation,str(exc),getattr(exc,'category','repair_error'))
        threading.Thread(target=work,daemon=True,name='theme-directed-repair').start()
        return self.current.request_id

    def _failed(self, operation, message, category):
        if (self.current is not None and self.page.project is self.project
                and self.current.generation==self.page._ai_request_generation and self.generation_running):
            if operation==self.provider_operation and operation!=self.operation:
                # A selected version can already be playing/exporting while a
                # later independent source request reaches its deadline.
                self.generation_running=False;self.page._ai_request_active=False
                bind_text(self.page.ai_generate, '重新生成');self.page._show_ai_progress_bar(False)
                self.design['generation_failure']=dict(category=category,message=message)
                self.page._show_studio_hint(tr('其余方向已停止：{value0}；所选版本已保留', value0=message))
                self._save_state();return
            if operation==self.operation and operation!=self.provider_operation and category=='render_validation':
                self.design['selection_failure']=dict(category=category,message=message)
                self.design['selected_concept_id']=''
                self.current=replace(self.current,theme_json='',trace_path='')
                self.evidence=None;self.page._pending_web_theme=None
                self.operation=self.provider_operation
                self._concepts_ready(self.operation,getattr(self,'concept_previews',{}))
                self.page._show_studio_hint(tr('所选版本验证失败：{value0}；其他方向继续生成', value0=message))
                return
        if operation!=self.operation or (self.phase not in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW'} and not self.generation_running): return
        if self.current.generation != getattr(self.page, '_ai_request_generation', self.current.generation) or self.page.project is not self.project: return
        self.cancel_event.set()
        self.generation_running=False
        self.page._stop_storyboard_animation()
        self._finish_candidate_attempt('cancelled' if category=='cancelled' else 'failed',message)
        dialog=getattr(self,'_concept_dialog',None)
        if dialog is not None:dialog.update_concepts(self.design.get('concepts',[]),getattr(self,'concept_previews',{}))
        self.error,self.category = message,category
        self.page._ai_request_active = False
        self.page._ai_cancel_event = None
        self.page.ai_generate.setEnabled(True)
        bind_text(self.page.ai_generate, '重新生成')
        self.page._set_ai_input_sections_visible(True)
        self.page._show_ai_progress_bar(False)
        self._set_phase('CANCELLED' if category=='cancelled' else 'FAILED',tr('{value0}；已应用主题保留', value0=message))
        demo = getattr(self.page,'ai_web_theme_demo_label',None)
        if demo is not None: bind_text(demo, '{value0}\n可重试预览或复制诊断', value0=message)
        recovery = '\n候选方案已保留，可点击“重试主题代码”。' if self.design.get('concepts') else ''
        self.page.ai_preview.setPlainText(message+'\n请求：'+self.current.request_id+recovery)
        self._save_state()

    def _recoverable_failure(self, operation, theme, message, category):
        if operation!=self.operation or self.cancel_event.is_set():return
        self.current=self.current.with_theme(theme)
        self._failed(operation,message,category)

    def export(self, destination):
        if not self.allow_pending():
            self.page._show_studio_hint(tr('当前主题尚未通过渲染校验，不能导出'))
            return
        draft = self.current
        self.last_export = ''
        self.page._show_studio_hint(tr('正在验证当前导出档案'))
        self.cancel_event = threading.Event()
        cancel = self.cancel_event
        self.operation = draft.request_id+'/export/'+uuid.uuid4().hex
        operation = self.operation
        output = self.root/('export-'+uuid.uuid4().hex)
        from .web_placement import cue_placement
        cue = next((c for c in self.request_project.cues if c.id == draft.cue_id), None)
        placement = cue_placement(self.page.project, cue) if cue is not None else {}
        self._set_phase('EXPORTING','写入并重新渲染导出档案')
        def work():
            from .web_theme import export_theme_archive, import_theme_archive
            try:
                def verify(folder):
                    imported = import_theme_archive(folder/'theme.json')
                    if canonical_theme(imported)!=draft.theme_json or canonical_theme(import_theme_archive(folder/'theme.html'))!=draft.theme_json:
                        raise ValueError('导出重读的主题身份不一致')
                    validate_draft_frames(draft,output,cancel_check=cancel.is_set,
                        progress=lambda value:self.stage.emit(operation,value),exact_html_path=folder/'theme.html',placement=placement)
                folder = export_theme_archive(draft.theme,destination,sample_text=draft.text,speaker=draft.speaker,
                    validate_before_publish=verify,cancel_check=cancel.is_set,placement=placement)
                if not cancel.is_set(): self.exported.emit(operation,str(folder))
            except Exception as exc:
                if not cancel.is_set(): self.failed.emit(operation,str(exc),'export_error')
        threading.Thread(target=work,daemon=True,name='theme-draft-export').start()

    def _exported(self, operation, folder):
        if self.phase!='EXPORTING' or operation!=self.operation or self.cancel_event.is_set() or getattr(self.page,'_close_requested',False): return
        self._set_phase('EXPORTED','当前档案已重读并通过独立渲染')
        self.page._show_studio_hint(tr('档案已导出：{value0} · 请求 {value1}', value0=folder, value1=self.current.request_id[:8]))
        self.last_export = folder
        self._save_state()

    def diagnostics(self):
        return dict(request_id=self.current.request_id if self.current else '',phase=self.phase,
            provider=self.current.provider if self.current else '',model=self.current.model if self.current else '',
            scope=self.current.scope if self.current else '',content_hash=self.current.content_hash if self.current else '',
            error=self.error,category=self.category,events=self.events,evidence=self.evidence,
            animation_error=self.animation_error,animation_metrics=self.animation_metrics,
            design=self.design,compiler_phases=list(self.compiler_phases.values()),
            operation_id=self.operation,started_monotonic=self.started,last_output_monotonic=self.last_output,
            provider_operation_id=getattr(self,'provider_operation',''),
            output_source=self.output_source,cue_id=self.current.cue_id if self.current else '',
            trace_path=self.current.trace_path if self.current else '',
            generation=self.current.generation if self.current else None,
            cancellation_requested=self.user_cancelled)

    def _save_state(self):
        if not hasattr(self, 'root'): return
        self.root.mkdir(parents=True,exist_ok=True)
        from .theme_persistence import write_text_atomic
        write_text_atomic(self.root/'request.json',json.dumps(self.diagnostics(),ensure_ascii=False,indent=2))
