"""Fixed original response through actual headed Studio and archive renderer."""
from __future__ import annotations
import json
import os
import time
import traceback
from pathlib import Path


def start_theme_draft_acceptance(window,output):
    from PySide6.QtCore import QObject,QTimer,Qt
    from PySide6.QtWidgets import QApplication
    from .theme_draft import canonical_theme
    from .web_theme import import_theme_archive
    from .build_identity import load_build_identity
    from .studio_ai import AIWebThemeSuggestion
    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page
            self.result=dict(checks={},summary={},native_frames=[],build=str(load_build_identity()),
                provider_input='fixed original response, no network/model substitution')
            self.pending=0;self.started=time.monotonic();self.sequence=self.run()
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(20)
        def tick(self):
            try:
                timeout=420 if os.environ.get('TWOBYTEASR_ORIGINAL_VIDEO_EXPORT')=='1' else 180
                if time.monotonic()-self.started>timeout:raise TimeoutError('theme UI acceptance timeout')
                if callable(self.pending):
                    if not self.pending():return
                elif time.monotonic()<self.pending:return
                value=next(self.sequence)
                self.pending=value if callable(value) else time.monotonic()+value
            except StopIteration:self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()
        def check(self,name,condition):
            self.result['checks'][name]=bool(condition)
            if not condition:raise AssertionError(name)
        def run(self):
            page=self.page
            yield 1.
            page.video.set_paused(True)
            page.select_cue('original')
            page._open_ai_design_from_style()
            theme=json.loads((output/'theme.json').read_text(encoding='utf8'))
            drafts=page._theme_drafts()
            page._ai_request_generation+=1
            draft=drafts.begin(page._ai_request_generation,'original','fullscreen','fixed-original','unchanged response')
            page._ai_web_theme_ready(draft.generation,'original',AIWebThemeSuggestion(theme))
            yield lambda:drafts.phase in {'READY','APPLIED','FAILED'}
            self.check('original_six_frame_gate',drafts.is_valid())
            self.check('current_pending_identity',drafts.allow_pending())
            self.check('applied_exact_theme',canonical_theme(page.project.style_recipes[page.project.cues[0].style_id]['webTheme'])==drafts.current.theme_json)
            self.result['initial_validation']=drafts.evidence
            self.check('six_visible_storyboard_frames',len([l for l in page.ai_storyboard_six_labels if l.pixmap() and not l.pixmap().isNull()])==6)
            yield 4.
            self.check('actual_storyboard_animation',len(getattr(page,'_storyboard_frame_times',[]))>30)
            self.result['animation_metrics']=drafts.animation_metrics
            self.check('storyboard_30fps_p95_40ms',drafts.animation_metrics.get('fps',0)>=29
                and drafts.animation_metrics.get('p95_ms',999)<=40)
            window.grab().save(str(output/'draft-controls.png'))
            for index,seconds in enumerate((.06,.30,.72,1.74,2.49,2.91)):
                started=time.perf_counter()
                page._seek(seconds)
                def current_ack():
                    worker=page._web_live_worker
                    if worker is None:return None
                    records=list(page.video.web_publication_metrics)+list(page.video.web_initial_publication_metrics)
                    return next((r for r in reversed(records)
                        if r.get('applied') and (r.get('applied_at') or 0)>=started
                        and r.get('web_worker_id')==id(worker)
                        and r.get('web_content_key')==worker.strip_key
                        and r.get('web_generation')==worker._configuration_generation
                        and r.get('web_clock_generation')==page.video.playback_position_snapshot().playback_generation
                        and abs(r.get('web_cue_ms',-10000)-seconds*1000)<2),None)
                yield lambda:bool(current_ack()) or time.perf_counter()-started>3
                ack=current_ack()
                self.check(f'native_current_theme_time_ack_{index}',bool(ack))
                self.result.setdefault('warm_native_changes',[]).append(dict(seconds=seconds,
                    ms=(ack['applied_at']-started)*1000,ack=ack))
                self.result.setdefault('native_owners',[]).append(dict(seconds=seconds,
                    owner=page.subtitle_visibility_trace(),source=getattr(page,'_advanced_canvas_source_kind',''),
                    metrics=getattr(getattr(page,'_web_live_worker',None),'metrics',[])))
                self.check(f'native_web_owner_{index}',getattr(page,'_advanced_canvas_source_kind','')=='web_live')
                path=output/f'native-{index+1:02}.png'
                page.video.controller.screenshot_to_file(path,mode='window')
                self.result['native_frames'].append(dict(seconds=seconds,path=str(path),clock=page.video.visual_position()))
            self.check('warm_native_change_200ms',max(r['ms'] for r in self.result['warm_native_changes'])<=200)
            drafts.export(output/'archives')
            yield lambda:drafts.phase in {'EXPORTED','FAILED'}
            self.check('atomic_archive_export',drafts.phase=='EXPORTED')
            folder=Path(drafts.last_export)
            self.check('json_html_reimport_identity',canonical_theme(import_theme_archive(folder/'theme.html'))==drafts.current.theme_json
                       and canonical_theme(import_theme_archive(folder/'theme.json'))==drafts.current.theme_json)
            self.result['archive']=str(folder)
            before=drafts.current
            blocked=output/'export-path-is-a-file'
            blocked.write_text('failure injection',encoding='utf8')
            drafts.export(blocked)
            yield lambda:drafts.phase=='FAILED'
            self.check('failed_reexport_clears_old_success',drafts.last_export=='' and '档案已导出' not in page.save_state.text())
            self.check('failed_export_keeps_valid_theme',drafts.current.theme_json==before.theme_json and drafts.is_valid())
            drafts.render()
            yield lambda:drafts.phase in {'APPLIED','FAILED'}
            self.check('render_retry_restores_actions',drafts.allow_pending())
            old_operation=drafts.operation;old_evidence=drafts.evidence
            page._ai_request_generation+=1
            newer=drafts.begin(page._ai_request_generation,'original','fullscreen','fixed-original','unchanged response')
            self.check('new_request_clears_export_banner','档案已导出' not in page.save_state.text() and drafts.last_export=='')
            drafts._ready(old_operation,old_evidence)
            self.check('stale_callback_discarded',drafts.current.request_id==newer.request_id and not drafts.allow_pending())
            drafts.cancel()
            self.check('cancel_terminal_and_no_export',drafts.phase=='CANCELLED' and not page.ai_export_archive_button.isEnabled())
            self.check('cancel_preserves_applied_theme',canonical_theme(page.project.style_recipes[page.project.cues[0].style_id]['webTheme'])==before.theme_json)
            page._ai_request_generation+=1
            drafts.begin(page._ai_request_generation,'original')
            ignored_operation=drafts.operation
            page._ignore_ai_preview()
            drafts._ready(ignored_operation,old_evidence)
            self.check('ignore_invalidates_pending_completion',drafts.phase=='CANCELLED' and page._pending_web_theme is None)
            drafts.adopt(import_theme_archive(folder/'theme.json'),'original')
            yield lambda:drafts.phase in {'APPLIED','FAILED'}
            self.check('exported_archive_reimport_render_apply',drafts.is_valid() and drafts.current.theme_json==before.theme_json)
            real_apply=page._apply_web_theme
            calls=[]
            def fail_second(*args,**kwargs):
                calls.append(args)
                if len(calls)==2:raise RuntimeError('injected partial apply failure')
                return real_apply(*args,**kwargs)
            page._apply_web_theme=fail_second
            drafts.adopt(before.theme,'original')
            drafts.apply_targets=['original','original']
            yield lambda:drafts.phase in {'READY','APPLIED','FAILED'}
            page._apply_web_theme=real_apply
            self.check('partial_apply_failure_keeps_exportable_draft',drafts.phase=='READY' and drafts.allow_pending()
                and drafts.category=='apply_error')
            controller=page.style_controller
            controller_type=type(controller)
            real_scope=controller_type._ai_apply_scope_cue_ids
            real_controller_apply=controller_type._apply_web_theme
            calls=[]
            def fail_button_second(owner,*args,**kwargs):
                calls.append(args)
                if len(calls)==2:raise RuntimeError('injected button partial failure')
                return real_controller_apply(owner,*args,**kwargs)
            controller_type._ai_apply_scope_cue_ids=lambda owner:['original','original']
            controller_type._apply_web_theme=fail_button_second
            try:
                page.ai_apply_button.click()
            finally:
                controller_type._ai_apply_scope_cue_ids=real_scope
                controller_type._apply_web_theme=real_controller_apply
            self.check('actual_apply_button_partial_failure_keeps_draft',len(calls)==2 and drafts.allow_pending()
                and drafts.category=='apply_error' and drafts.current.theme_json==before.theme_json)
            scope_calls=[]
            def record_scope(owner,*args,**kwargs):
                scope_calls.append(args)
                return real_controller_apply(owner,*args,**kwargs)
            controller_type._apply_web_theme=record_scope
            try:
                page.web_adjust_apply_all.click()
            finally:
                controller_type._apply_web_theme=real_controller_apply
            self.check('actual_scope_button_preserves_draft_identity',bool(scope_calls) and drafts.allow_pending()
                and drafts.current.theme_json==before.theme_json)
            self.result['final_request']=drafts.diagnostics()
            window.grab().save(str(output/'final-controls.png'))
            if os.environ.get('TWOBYTEASR_ORIGINAL_VIDEO_EXPORT')=='1':
                # Exercise the real export workspace button and its captured
                # project/job inside this very EXE, not a source-only CLI.
                self.page._stop_storyboard_animation()
                page.studio_render_button.click()
                yield lambda:page.export_workspace is not None
                export=page.export_workspace
                # Constructor schedules its initial preset on the next turn.
                # Configure after that real UI initialization has completed.
                yield .2
                export.directory.setText(str(output))
                export.filename.setText('Death-Stranding-Frozen')
                export.encoder.setCurrentIndex(export.encoder.findData('libx264'))
                if os.environ.get('TWOBYTEASR_ORIGINAL_EXPORT_SOURCE_SIZE')!='1':
                    export.resolution.setCurrentIndex(next(i for i in range(export.resolution.count())
                        if tuple(export.resolution.itemData(i))==(1280,720)))
                    export.fps.setCurrentIndex(next(i for i in range(export.fps.count())
                        if float(export.fps.itemData(i))==30.))
                export.audio.setCurrentIndex(export.audio.findData('none'))
                export.export_range.setCurrentIndex(export.export_range.findData('in_out'))
                export.in_ms=0;export.out_ms=3000;export._update_range()
                yield .1
                self.result['video_export']=dict(button_enabled=export.export_button.isEnabled(),
                    output=str(export.export_target().full_path),events=[],
                    settings=vars(export._render_settings()),range=export._range_seconds())
                export.render_succeeded.connect(lambda path:self.result['video_export'].update(succeeded=path))
                export.render_failed.connect(lambda error:self.result['video_export'].update(error=error))
                real_trace=export._export_trace
                def observed_trace(event,*args,**kwargs):
                    real_trace(event,*args,**kwargs)
                    if event=='advanced_overlay_command':
                        command=args[0]
                        props_path=next(Path(str(part).removeprefix('--props='))
                            for part in command if str(part).startswith('--props='))
                        # Observe the exact prepared export props. Source-mode
                        # defaults may resolve FPS from ffprobe inside the job.
                        (output/'export-props.json').write_bytes(props_path.read_bytes())
                        self.result['video_export']['command']=[str(part) for part in command]
                export._export_trace=observed_trace
                started=time.perf_counter()
                export.export_button.click()
                yield lambda:not export._running
                export._export_trace=real_trace
                evidence=self.result['video_export']
                evidence.update(elapsed_ms=(time.perf_counter()-started)*1000,
                    advanced_route=export._advanced_route,
                    success_page=export.pages.currentWidget() is export.success_page,
                    failure=getattr(export,'_last_failure',''))
                path=Path(evidence['output'])
                evidence['bytes']=path.stat().st_size if path.is_file() else 0
                self.check('actual_video_export_button',bool(evidence.get('succeeded'))
                    and evidence['success_page'] and evidence['advanced_route'] and evidence['bytes']>0)
                from .advanced_renderer import _overlay_cache_path
                import shutil
                props=json.loads((output/'export-props.json').read_text(encoding='utf8'))
                cached=_overlay_cache_path(props)
                evidence['cached_overlay']=str(cached)
                self.check('actual_export_overlay_available',cached.is_file())
                shutil.copyfile(cached,output/'Death-Stranding-Original.mov')
                window.grab().save(str(output/'video-export-success.png'))
                page._close_export_workspace()
        def finish(self):
            self.timer.stop()
            self.result['native_publication_metrics']=list(self.page.video.web_publication_metrics)
            self.result['native_initial_publication_metrics']=list(self.page.video.web_initial_publication_metrics)
            drafts=self.page._theme_drafts()
            self.result['controller_at_finish']=drafts.diagnostics()
            worker=getattr(self.page,'_storyboard_live_worker',None)
            self.result['storyboard_at_finish']=dict(frames=len(getattr(self.page,'_storyboard_frame_times',[])),
                text=self.page.ai_web_theme_demo_label.text(),worker=bool(worker),
                metrics=getattr(worker,'metrics',[]),running=getattr(worker,'running',False))
            window.grab().save(str(output/'finish-controls.png'))
            self.page._stop_storyboard_animation()
            self.result['elapsed_seconds']=time.monotonic()-self.started
            (output/'theme-draft-acceptance.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf8')
            self.page.undo_stack.setClean()
            self.page.close_ready_signal.connect(self.closed)
            self.result['checks']['close_cleanup_completed']=False
            window.close()

        def closed(self, profile):
            self.result['close_profile']=dict(profile)
            self.result['checks']['close_cleanup_completed']=bool(self.page._close_complete)
            self.result['checks']['close_audio_idle']=profile.get('audio_idle') is True
            (output/'theme-draft-acceptance.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf8')
    window._theme_draft_audit=Audit()
