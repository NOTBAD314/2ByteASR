"""Normal Studio UI check for a project-local human entity decision."""
from __future__ import annotations
import json
from pathlib import Path
import time
import traceback


def start(window,output):
    from PySide6.QtCore import QObject,QTimer,Qt,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .studio_find_replace import FindReplaceDialog
    from .studio_text_tools import SCOPE_SELECTED,SCOPE_ALL
    from .studio_project import load_project

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page;self.dialog=None
            self.deadline=time.monotonic()+70
            self.result={'passed':False,'checks':[],'screenshots':[],
                'source':'normal GUI argv entry and real FindReplaceDialog controls',
                'provider_calls':0,'scope':'synthetic fixture; mechanism only, no acoustic accuracy claim'}
            self.timer=QTimer(self);self.timer.setInterval(100);self.timer.timeout.connect(self.run);self.timer.start()
            QApplication.instance().aboutToQuit.connect(self.stopped)

        def check(self,value,name):
            self.result['checks'].append({'name':name,'passed':bool(value)})
            if not value:raise AssertionError(name)

        def shot(self,name):
            QTest.qWait(200)
            _capture(self.dialog or window,output/name);self.result['screenshots'].append(name)

        def stopped(self):
            self.result['gui_shutdown']=True;self.write()

        def write(self):
            (output/'entry-result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),'utf8')

        def enter(self):
            self.dialog=FindReplaceDialog(self.page);self.dialog.show();QTest.qWait(150)
            return self.dialog

        def run(self):
            gate=getattr(self.page,'_readiness',None)
            if self.page.project is None or gate is None or not gate.ready:
                if time.monotonic()>self.deadline:self.finish(TimeoutError('project not ready'))
                return
            self.timer.stop()
            try:
                p=self.page.project;original=[(c.id,c.text,c.start_ms,c.end_ms,c.speaker_id) for c in p.cues]
                raw=json.loads(json.dumps(p.asr_evidence))
                self.page.select_cue('entity-a')
                d=self.enter()
                QTest.keyClicks(d.find_edit,'So');QTest.keyClicks(d.replace_edit,'S0pp')
                d.scope_combo.setCurrentIndex(d.scope_combo.findData(SCOPE_SELECTED))
                QTest.mouseClick(d.case_box,Qt.MouseButton.LeftButton,pos=QPoint(10,d.case_box.height()//2))
                QTest.mouseClick(d.project_entity_box,Qt.MouseButton.LeftButton,pos=QPoint(10,d.project_entity_box.height()//2))
                self.check(d.project_entity_box.isChecked(),'explicit project confirmation checkbox selected')
                QTest.mouseClick(d.preview_button,Qt.MouseButton.LeftButton)
                self.check({h.cue_id for h in d._preview_hits}=={'entity-a'},'literal correction preview uses selected cue')
                self.shot('01-human-confirmation-preview.png')
                QTest.mouseClick(d.all_button,Qt.MouseButton.LeftButton)
                self.check(p.cues[0].text=='S0pp还在往里走','selected entity correction applies')
                receipt=p.generation_metadata['glossary_review_jobs'][-1]
                self.check(receipt['source']=='user_confirmed' and receipt['audio_verified_by_model'] is False,'human source and no model-hearing claim')
                self.check(p.studio_state['manual_caption_text']['entity-a']==p.cues[0].text,'confirmed spelling is protected manual text')
                self.check(p.cues[1].text=='So的反应','other occurrence is untouched until reviewed')
                d.reject();self.dialog=None
                self.page.select_cue('entity-b')
                d=self.enter();d.tabs.setCurrentIndex(3)
                d.terms_scope.setCurrentIndex(d.terms_scope.findData(SCOPE_SELECTED))
                QTest.mouseClick(d.project_entities_button,Qt.MouseButton.LeftButton)
                self.check({h.cue_id for h in d._preview_hits}=={'entity-b'},'review candidate respects selected scope')
                self.shot('02-project-entity-review.png')
                d.reject();self.dialog=None
                self.check(p.cues[1].text=='So的反应','closing candidate preview makes no change')
                d=self.enter();d.tabs.setCurrentIndex(3)
                d.terms_scope.setCurrentIndex(d.terms_scope.findData(SCOPE_ALL))
                QTest.mouseClick(d.project_entities_button,Qt.MouseButton.LeftButton)
                self.check({h.cue_id for h in d._preview_hits}=={'entity-b'},'complete handle boundary excludes So_player and Somebody')
                p.cues[1].text='人工保留So原文'
                QTest.mouseClick(d.all_button,Qt.MouseButton.LeftButton)
                self.check(p.cues[1].text=='人工保留So原文','stale manual edit rejects pending preview')
                p.cues[1].text='So的反应'
                QTest.mouseClick(d.project_entities_button,Qt.MouseButton.LeftButton)
                before=self.page.undo_stack.count()
                QTest.mouseClick(d.all_button,Qt.MouseButton.LeftButton)
                self.check(p.cues[1].text=='S0pp的反应' and self.page.undo_stack.count()==before+1,'reviewed candidates apply in one undo command')
                d.reject();self.dialog=None
                self.page.undo_stack.undo();self.check(p.cues[1].text=='So的反应','one undo restores candidate text')
                self.page.undo_stack.redo();self.check(p.cues[1].text=='S0pp的反应','redo restores confirmed spelling')
                self.page.save();saved=load_project(self.page.session.project_path)
                self.check([c.text for c in saved.cues]==[c.text for c in p.cues],'production Save preserves final subtitle text')
                self.check(saved.studio_state['manual_caption_text']==p.studio_state['manual_caption_text'],'save and readback preserve manual protection')
                self.check(saved.asr_evidence==raw,'original ASR evidence retained')
                self.check([(c.id,c.start_ms,c.end_ms,c.speaker_id) for c in p.cues]==[(a,t,e,s) for a,_,t,e,s in original],'timing and speaker identities retained')
                self.shot('03-confirmed-studio.png')
                self.result['passed']=True;self.finish()
            except Exception as exc:self.finish(exc)

        def finish(self,error=None):
            self.timer.stop()
            if error is not None:self.result['error']=traceback.format_exc()
            if self.dialog is not None:self.dialog.reject();self.dialog=None
            if error is not None:self.page.undo_stack.setClean()
            self.write();window.close()
    window._project_entity_audit=Audit()
