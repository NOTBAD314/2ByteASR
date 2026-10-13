import json,time,traceback,copy
from pathlib import Path
from PySide6.QtCore import QObject,QTimer,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog


def start(window,out):
    class Audit(QObject):
        def __init__(self):
            super().__init__(window);self.page=window.studio_page;self.started=time.monotonic()
            self.result={'checks':{},'real_provider_calls':0,'clock_test':'synthetic 310s stage age; not a real Provider wait'}
            from .build_identity import load_build_identity
            self.result['build']=vars(load_build_identity())
            self.result['real_user_click']=False
            self.pending=0.;self.sequence=self.run();self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(25)
        def check(self,name,value):self.result['checks'][name]=bool(value)
        def tick(self):
            try:
                if time.monotonic()-self.started>160:raise TimeoutError('AI UI audit budget')
                if callable(self.pending):
                    if not self.pending():return
                elif time.monotonic()<self.pending:return
                value=next(self.sequence);self.pending=value if callable(value) else time.monotonic()+float(value)
            except StopIteration:self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()
        def run(self):
            page=self.page
            yield 1
            while page._readiness.active:yield .2
            cue=page.project.cues[0];page.select_cue(cue.id)
            page._open_ai_design_from_style();yield .5
            from twobyteasr.web_theme_compiler import choose_concept
            source=json.loads((out/'concepts.json').read_text('utf-8-sig'))
            brief,concepts,chosen=choose_concept(copy.deepcopy(source),'subtitle')
            design={'brief':brief,'concepts':concepts,'selected_concept_id':'goggle-peek'}
            page._ai_last_instruction='北极熊滑雪镜，底部透明字幕'
            page._ai_request_generation+=1
            drafts=page._theme_drafts();drafts.begin(page._ai_request_generation,cue.id,'subtitle','grok_oauth','grok-4.6')
            now=time.monotonic();operation=drafts.operation
            drafts._compiler_event(operation,dict(name='concepts',label='候选方案',request_id='fixture-concepts',started_monotonic=now-400,
                last_output_monotonic=now-310,timeout_seconds=300,status='complete',design=design))
            drafts._compiler_event(operation,dict(name='theme_code',label='编写选定主题',request_id='fixture-code-over300',started_monotonic=now-310,
                last_output_monotonic=now,timeout_seconds=900,status='running',provider_state='thinking'))
            drafts._tick();yield .3
            self.check('active_stage_310s_not_cancelled',drafts.phase=='PROVIDER' and not drafts.cancel_event.is_set())
            window.grab().save(str(out/'ai-over300-fixture-ui.png'))
            drafts._failed(operation,'Provider 已完成思考但未返回主题正文','provider_no_body');yield .3
            self.check('retry_and_local_available',page.ai_retry_theme_code_button.isEnabled() and page.ai_local_theme_button.isEnabled())
            from twobyteasr import studio_ai
            from twobyteasr.ai_providers import AIProviderError
            original=studio_ai.request_web_theme_design;calls=[]
            def no_body(*args,**kwargs):
                calls.append(kwargs['resume_design'])
                raise AIProviderError('Provider 已完成思考但未返回主题正文',category='provider_no_body')
            studio_ai.request_web_theme_design=no_body
            QTest.mouseClick(page.ai_retry_theme_code_button,Qt.LeftButton)
            yield lambda:drafts.phase=='FAILED'
            studio_ai.request_web_theme_design=original
            self.check('retry_only_preserved_concept',len(calls)==1 and calls[0]['selected_concept_id']=='goggle-peek')
            QTest.mouseClick(page.ai_local_theme_button,Qt.LeftButton)
            yield lambda:drafts.phase in ('READY','FAILED','CANCELLED')
            self.result['draft']=drafts.diagnostics()
            self.check('local_preview',drafts.phase=='READY' and drafts.is_valid())
            if not drafts.is_valid():raise RuntimeError(drafts.error)
            # Snow moving across six frames alone cannot prove the whole
            # subtitle fades. Check the actual rendered alpha at both ends.
            import numpy as np
            from PySide6.QtGui import QImage
            peaks=[]
            for frame in self.result['draft']['evidence']['frames']:
                image=QImage(frame['path']).convertToFormat(QImage.Format_RGBA8888)
                pixels=np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())
                alpha=pixels[:,:image.width()*4].reshape(image.height(),image.width(),4)[:,:,3]
                peaks.append(int(alpha.max()))
            self.result['local_frame_alpha_peaks']=peaks
            self.check('local_entrance_exit_pixels',0<peaks[0]<peaks[3]*.8 and peaks[3]>=240 and 0<peaks[-1]<peaks[3]*.8)
            yield 1.5
            window.grab().save(str(out/'ai-local-preview-ui.png'))
            QTest.mouseClick(page.ai_apply_button,Qt.LeftButton);yield 1
            self.check('applied',drafts.phase=='APPLIED' or bool(page._current_web_theme_recipe()))
            # Inspect the applied theme inside the native video surface at a
            # visible cue time, rather than at the transparent entrance t=0.
            field=page.timecode_input
            QTest.mouseClick(field,Qt.LeftButton);QTest.keyClick(field,Qt.Key_A,Qt.ControlModifier)
            QTest.keyClicks(field,'00:00:01.500');QTest.keyClick(field,Qt.Key_Return)
            yield 2
            from twobyteasr.studio_performance import performance_snapshot
            self.result['applied_runtime']=performance_snapshot(page,compact=False)
            page.video.controller.screenshot_to_file(out/'ai-applied-native.png')
            window.grab().save(str(out/'ai-applied-ui.png'))
            from twobyteasr.studio_project import save_project
            save_project(page.project,out/'applied.2byteproj')
            self.result['applied_project']=str(out/'applied.2byteproj')
            destination=out/'export';destination.mkdir(exist_ok=True)
            choose=QFileDialog.getExistingDirectory
            QFileDialog.getExistingDirectory=lambda *a,**k:str(destination)
            try:QTest.mouseClick(page.ai_export_archive_button,Qt.LeftButton)
            finally:QFileDialog.getExistingDirectory=choose
            yield lambda:drafts.phase in ('EXPORTED','FAILED','CANCELLED')
            self.check('exported',drafts.phase=='EXPORTED')
            self.result['export']=getattr(drafts,'last_export','')
            self.result['draft']=drafts.diagnostics()
            window.grab().save(str(out/'ai-local-export-ui.png'))
            yield .4
        def finish(self):
            self.timer.stop();self.result['elapsed_seconds']=time.monotonic()-self.started
            (out/'ai-ui-acceptance.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            self.page.undo_stack.setClean();window.close()
    window._recovery_audit=Audit()
