"""Opt-in normal GUI checks; all writes live in the audit's private data root."""
import json, os, sys, time, traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .studio_find_replace import FindReplaceDialog
    from .studio_project import load_project, save_project
    from .studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions, verify_subtitle_artifact
    from .studio_runtime_state import state_for

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page
            self.result=dict(passed=False,checks=[],screenshots=[],pid=os.getpid(),executable=sys.executable,
                             identity=load_build_identity().to_dict(),fixture='generated media and captions; no ASR inference claimed')
            self.steps=self.run(); self.waiting=0; self.deadline=time.monotonic()+45; self.busy=False
            self.timer=QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(50)
        def check(self,name,value,detail=None):
            self.result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
            if not value:raise AssertionError(f'{name}: {detail}')
        def shot(self,name,surface=None):
            target=output/(name+'.png');_capture(surface or window,target)
            self.result['screenshots'].append(target.name)
        def tick(self):
            if self.busy:return
            self.busy=True
            try:
                now=time.monotonic()
                if now>self.deadline:raise TimeoutError('GUI phase timeout')
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<float(self.waiting):return
                step=next(self.steps)
                self.waiting=step if callable(step) else now+float(step)
                self.deadline=now+45
            except StopIteration:
                self.result['passed']=True;self.finish()
            except Exception:
                self.result['error']=traceback.format_exc()
                try:self.shot('failure')
                except Exception:pass
                self.finish()
            finally:
                self.busy=False
        def ready(self):
            return self.page.project is not None and self.page._readiness.ready and not self.page._readiness.active
        def run(self):
            yield .3
            from .terminology_effective_audit import run_glossary_checks
            glossary=run_glossary_checks(window,output)
            self.result['checks'].extend(glossary['checks'])
            self.result['screenshots'].extend(glossary.get('screenshots',[]))
            self.check('glossary real controls',glossary.get('passed'),glossary.get('error'))
            from scripts.verify_cli_diagnostics_runtime import run_cli_ui_checks
            cli=run_cli_ui_checks(window,output)
            self.result['checks'].extend(cli['checks'])
            self.result['screenshots'].extend(cli.get('screenshots',[]))
            self.check('CLI actual receipt replay in real UI',cli['passed'])
            fixture=output/'fixture.2byteproj'
            project=load_project(fixture)
            project.glossary_ids=[glossary['primary_id']]
            save_project(project,fixture)
            window.open_studio_project(fixture,mode='edit',source='terminology_effective_audit')
            yield self.ready
            yield .4
            p=self.page; original=[(c.text,c.start_ms,c.end_ms,c.speaker_id) for c in p.project.cues]
            QTimer.singleShot(0,lambda:QTest.mouseClick(p.studio_find_replace_button,Qt.LeftButton))
            yield lambda:isinstance(QApplication.activeModalWidget(),FindReplaceDialog)
            dialog=QApplication.activeModalWidget();dialog.tabs.setCurrentIndex(3)
            QTest.mouseClick(dialog.preview_button,Qt.LeftButton)
            yield .2
            self.check('terms preview real matches',dialog.preview.count()==3,dialog.preview.count())
            self.shot('studio-terms-preview',dialog)
            dialog.preview.item(1).setCheckState(Qt.Unchecked)
            QTest.mouseClick(dialog.all_button,Qt.LeftButton)
            yield .2
            self.check('unchecked individual preserved',p.project.cues[1].text==original[1][0])
            self.check('confirmed alias applied',p.project.cues[0].text=='BerLIN也没有接住')
            self.check('zero digit safe normalization',p.project.cues[2].text=='S0PP sopp xberlin')
            self.check('timing and speaker unchanged',[(c.start_ms,c.end_ms,c.speaker_id) for c in p.project.cues]==[r[1:] for r in original])
            dialog.reject();yield .1
            p.undo_stack.undo();yield .1
            self.check('single undo restores all',[(c.text,c.start_ms,c.end_ms,c.speaker_id) for c in p.project.cues]==original)
            p.undo_stack.redo();yield .2
            p.video.seek(.8);yield .5
            self.shot('studio-applied-preview')
            self.check('table and timeline same project',p.cue_model.project is p.project and p.timeline.project is p.project)
            QTest.mouseClick(p.save_button,Qt.LeftButton);yield .2
            reopened=load_project(p.project_path)
            self.check('saved final texts',reopened.cues[0].text=='BerLIN也没有接住' and reopened.cues[2].text=='S0PP sopp xberlin')
            artifacts=export_subtitle_artifacts(reopened,output/'exports','terms',SubtitleExportOptions(frozenset({'txt','srt','ass','json'}),'both'))
            for artifact in artifacts:
                import copy
                scoped = copy.deepcopy(reopened)
                if artifact.speaker_id:
                    scoped.cues = [c for c in scoped.cues if c.speaker_id == artifact.speaker_id]
                self.check('export '+artifact.path.name,verify_subtitle_artifact(artifact,scoped).valid)
            self.check('export final strings',all('BerLIN' in a.path.read_text('utf8') for a in artifacts if not a.speaker_id or a.speaker_id=='S01'))
            from .studio_find_replace import PreviewBinding, apply_occurrences
            from .studio_text_tools import glossary_occurrences
            binding=PreviewBinding.capture(p.project);hits=glossary_occurrences(p.project,[c.id for c in p.project.cues])
            p.cue_controller.set_text('term-b','人工已修改')
            self.check('edited text rejects stale scan',apply_occurrences(p,hits,title='terms',binding=binding)==(0,0))
            p.undo_stack.undo();QTest.mouseClick(p.save_button,Qt.LeftButton);yield .2
            saved_path=p.project_path
            QTest.mouseClick(p.studio_back_button,Qt.LeftButton);yield .2
            self.check('close saved project before reopen',p.project is None)
            window.open_studio_project(saved_path,mode='edit',source='term_reopen');yield self.ready
            yield .2
            self.check('reopen final text',p.project.cues[0].text=='BerLIN也没有接住')
            self.check('reopen creates new project object',p.project is not binding.project)
            self.check('new object rejects old scan',apply_occurrences(p,hits,title='terms',binding=binding)==(0,0))
            self.shot('studio-reopened')
        def finish(self):
            self.timer.stop();window.result_exit_code=0 if self.result['passed'] else 1
            def write(): (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),'utf8')
            write()
            def stopped():self.result['gui_shutdown']=True;write()
            QApplication.instance().aboutToQuit.connect(stopped)
            modal=QApplication.activeModalWidget()
            if modal is not None:modal.reject()
            window.close()
    window._terminology_effective_audit=Audit()


def start_restore(window, output):
    """Second regular app process reuses only the first audit's isolated data."""
    import json, traceback
    from pathlib import Path
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .terminology import snapshot_glossaries, TermResolver
    from .studio_acceptance_audit import require
    output=Path(output)
    result=dict(passed=False, checks=[], gui_shutdown=False)
    def check(name, value):
        result['checks'].append(dict(name=name, passed=bool(value)))
        require(value,name)
    def write():
        (output/'restore-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    def run():
        try:
            expected=json.loads((output/'glossary-effective-checks.json').read_text('utf8'))
            check('fresh process restores enabled stable IDs',window._enabled_glossary_ids()==expected['library_ids'])
            check('fresh process restores enhancement switch',window.terms.isChecked())
            snapshot=snapshot_glossaries(window.legacy,window._enabled_glossary_ids())
            check('fresh process preserves canonical case and digit zero',{'BerLIN','S0PP','NovaID'}.issubset(set(snapshot.canonical_terms)))
            check('fresh process applies persisted confirmed alias offline',TermResolver(snapshot).resolve('Borlin也没有接住 s0pp sopp').text=='BerLIN也没有接住 S0PP sopp')
            window._switch_page(window.settings_scroll)
            window._refresh_glossary_chips()
            check('fresh process Home shows renamed libraries',all(name in window.batch_glossary_status.text() for name in ['验收瓦罗兰特','验收选手词库']))
            window.settings_scroll.ensureWidgetVisible(window.batch_glossary_status,0,70)
            QApplication.instance().processEvents()
            _capture(window,output/'home-after-process-restart.png')
            result['passed']=True
        except Exception:
            result['error']=traceback.format_exc()
        window.result_exit_code=0 if result['passed'] else 1
        write()
        def stopped():
            result['gui_shutdown']=True;write()
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(700,run)
