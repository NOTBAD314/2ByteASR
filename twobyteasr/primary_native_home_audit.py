"""Normal-entry Home and actual fresh-MOSS project verification."""
from __future__ import annotations
import json,os,time,traceback
from pathlib import Path

def start(window, output):
    from PySide6.QtCore import QObject,QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QLabel,QMessageBox
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .speaker_strategy import resolve
    from .studio_subtitle_export import export_subtitle_artifacts,SubtitleExportOptions
    from .studio_project import load_project
    output=Path(output)
    plan=json.loads((output/'native-plan.json').read_text('utf8'))
    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result={'passed':False,'checks':[],'screenshots':[],'identity':load_build_identity().to_dict(),'kind':'fresh MOSS result replay after actual local inference; normal Home and Studio UI; no new ASR/cloud in GUI'}
            self.steps=self.run();self.waiting=0;self.deadline=time.monotonic()+100;self.busy=False
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(50)
        def check(self,name,value,detail=None):
            self.result['checks'].append({'name':name,'passed':bool(value),'detail':detail})
            if not value:raise AssertionError(name+': '+str(detail))
        def capture(self,name):
            _capture(window,output/(name+'-native.png'))
            self.result['screenshots'].append(name+'-native.png')
        def tick(self):
            if self.busy:return
            self.busy=True
            try:
                modal=QApplication.activeModalWidget()
                if isinstance(modal,QMessageBox):
                    text=modal.text();modal.reject();raise RuntimeError(text)
                now=time.monotonic()
                if now>self.deadline:raise TimeoutError('native Home audit')
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<self.waiting:return
                item=next(self.steps);self.waiting=item if callable(item) else now+float(item);self.deadline=time.monotonic()+100
            except StopIteration:self.result['passed']=True;self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()
            finally:self.busy=False
        def choose(self,combo,value):
            index=combo.findData(value);self.check('backend present '+value,index>=0)
            combo.setFocus()
            for _ in range(abs(index-combo.currentIndex())):
                QTest.keyClick(combo,Qt.Key_Down if index>combo.currentIndex() else Qt.Key_Up)
            self.check('keyboard choice '+value,combo.currentData()==value)
        def run(self):
            window._return_to_settings();yield .5
            self.check('independent summary widget removed',not hasattr(window,'speaker_plan_summary'))
            self.check('workshop independent role removed','speaker' not in window.workshop_page.combo_model_labels)
            for lang in ('zh','en','ja'):
                window.language_combo.setCurrentIndex(window.language_combo.findData(lang));yield .3
                self.capture('home-'+lang+'-before-check')
                self.check(lang+' primary Home card MOSS','MOSS' in window.recognition_plan.cards['primary'].model_label.text(), {'card':window.recognition_plan.cards['primary'].model_label.text(),'primary':window.primary_asr_backend.currentData(),'runtime':window.legacy.RUNTIME_SETTINGS['models']['primary_asr_backend'],'profile':window.current_project_profile.asr_config})
                self.check(lang+' modified bookmark retains custom',window.current_project_profile.recognition_plan=='custom')
                expected={'zh':'自定义方案','en':'Custom plan','ja':'カスタムプラン'}[lang]
                self.check(lang+' custom bookmark is visibly localized',expected in window.project_profile_combo.currentText(),window.project_profile_combo.currentText())
                self.capture('home-'+lang)
            self.choose(window.primary_asr_backend,'api');yield .25
            self.check('other recognizer respected',window._asr_values()['primary_asr_backend']=='api')
            self.check('other recognizer native-only',window._asr_values()['speaker_source']=='native')
            self.choose(window.primary_asr_backend,'moss');yield .25
            values=window._asr_values()
            self.check('MOSS native task selection',values['speaker_source']=='moss')
            self.check('legacy override cannot disable MOSS',resolve({'models':{**values,'speaker_source':'single'}})=='moss')
            from .service import RunOptions
            options=RunOptions(speaker_source='single',settings_snapshot_json=json.dumps({'models':values}))
            self.check('queue frozen native state',options.create_runtime_context(window.legacy).speaker_source=='moss')
            window.language_combo.setCurrentIndex(window.language_combo.findData('zh'));yield .2
            for kind in ('dialogue','single'):
                ready=[];page=window.studio_page;page.undo_stack.setClean()
                page.show_project_hub(skip_dirty_guard=True)
                window.open_studio_project(plan[kind],on_ready=lambda *_:ready.append(True))
                yield lambda:bool(ready) and page._readiness.ready
                page.video.set_paused(True);yield .3
                expected=set(plan[kind+'_labels']);actual={c.speaker_id for c in page.project.cues}
                self.check(kind+' real native lanes',actual==expected,sorted(actual))
                self.check(kind+' explicit labels retained',len(page.project.speakers)==len(expected))
                self.capture('studio-'+kind)
                exports=export_subtitle_artifacts(page.project,output/(kind+'-export'),kind,SubtitleExportOptions(speaker_mode='per_speaker'))
                self.check(kind+' normal export identity',{e.speaker_id for e in exports}==expected)
                page.undo_stack.setClean()
                window._return_to_settings();yield .3
            ready=[];page.show_project_hub(skip_dirty_guard=True)
            window.open_studio_project(plan['old_edited'],on_ready=lambda *_:ready.append(True))
            yield lambda:bool(ready) and page._readiness.ready
            page.video.set_paused(True)
            self.check('old edited identities not rebuilt',[(c.id,c.text,c.speaker_id) for c in page.project.cues]==[tuple(r) for r in plan['old_edited_cues']])
            self.check('old edited speaker name retained',page.project.speakers[0].name=='人工合轨名')
            self.capture('studio-edited')
            page.undo_stack.setClean()
        def finish(self):
            self.timer.stop()
            def write(): (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),'utf8')
            write()
            def stopped():self.result['gui_shutdown']=True;write()
            QApplication.instance().aboutToQuit.connect(stopped)
            window.result_exit_code=0 if self.result['passed'] else 1
            window.studio_page.undo_stack.setClean()
            QTimer.singleShot(100,window.close)
    window._primary_native_home_audit=Audit()
