"""Opt-in frozen/source UI audit on an explicitly owned project copy."""
from __future__ import annotations

import hashlib
import json
import sys
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import load_project, save_project
    from ..studio.studio_speaker_manager import SpeakerManagerDialog

    output = Path(output)
    project_path = output / 'project.2byteproj'
    original_hash = hashlib.sha256(project_path.read_bytes()).hexdigest()
    result = {'passed':False,'frozen':bool(getattr(sys,'frozen',False)),
              'identity':load_build_identity().to_dict(),'checks':[],
              'human_listening_verified':False,'confirmation':'simulated on isolated copy'}

    def check(name, value, detail=''):
        result['checks'].append({'name':name,'passed':bool(value),'detail':str(detail)})
        if not value:
            raise AssertionError(name+': '+str(detail))

    def wait_until(predicate, seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if predicate():
                return True
            QTest.qWait(50)
        return bool(predicate())

    def run():
        page = manager = None
        try:
            window.showMaximized()
            window.open_studio_project(str(project_path),mode='edit',source='voiceprint-audit')
            def ready():
                candidate=window.built_page('studio')
                return bool(candidate and getattr(getattr(candidate,'_readiness',None),'ready',False)
                            and getattr(getattr(candidate,'video',None),'_startup_state','')=='READY')
            check('studio ready',wait_until(ready,40))
            page=window.built_page('studio')
            page.volume_slider.setValue(0)
            before=[(c.id,c.start_ms,c.end_ms,c.text) for c in page.project.cues]
            translations=dict(page.project.generation_metadata.get('translations') or {})
            check('real project opened',len(before)==460 and len(page.project.speakers)==11)
            manager=SpeakerManagerDialog(page)
            manager.show();QTest.qWait(200)
            check('voiceprint button visible',manager.voiceprint_button.isVisible())
            QTest.mouseClick(manager.voiceprint_button,Qt.MouseButton.LeftButton)
            check('analysis started',not manager.voiceprint_button.isEnabled(),manager.status.text())
            check('analysis completed',wait_until(lambda:manager.voiceprint_button.isEnabled(),90),manager.status.text())
            report=manager._voiceprint_report
            check('eleven labels proposed together',bool(report) and len(report.get('groups',[]))==1
                  and len(report['groups'][0])==11,manager.status.text())
            check('not merged before confirmation',len(page.project.speakers)==11)
            sample=next(item for item in report['sample_intervals'] if item['label']=='R001_S00')
            card=manager.cards['R001_S00']
            check('audition uses compared audio',card.data['excerpt_range']==
                  (round(sample['start']*1000),round(sample['end']*1000)))
            QTest.mouseClick(card.play_button,Qt.MouseButton.LeftButton)
            check('muted sample audition started',manager._preview_timer.isActive() and page.volume_slider.value()==0)
            manager._stop_preview()
            manager.grab().save(str(output/'voiceprint-candidates.png'))
            def accept_question():
                box=next((w for w in QApplication.topLevelWidgets() if isinstance(w,QMessageBox) and w.isVisible()),None)
                if box is not None:
                    box.grab().save(str(output/'voiceprint-confirm.png'))
                    QTest.mouseClick(box.button(QMessageBox.StandardButton.Yes),Qt.MouseButton.LeftButton)
            QTimer.singleShot(250,accept_question)
            QTest.mouseClick(manager.voiceprint_button,Qt.MouseButton.LeftButton)
            check('one undoable correction',len(page.project.speakers)==1 and page.undo_stack.count()==1,manager.status.text())
            check('caption and translation preserved',before==[(c.id,c.start_ms,c.end_ms,c.text) for c in page.project.cues]
                  and translations==page.project.generation_metadata.get('translations'))
            page.undo_stack.undo();QTest.qWait(100)
            check('undo restores eleven labels',len(page.project.speakers)==11)
            page.undo_stack.redo();QTest.qWait(100)
            check('redo restores one label',len(page.project.speakers)==1)
            saved=save_project(page.project,output/'corrected-copy.2byteproj')
            reopened=load_project(saved)
            check('saved copy retains translations',len(reopened.speakers)==1
                  and translations==reopened.generation_metadata.get('translations'))
            receipt=reopened.generation_metadata['speaker_recovery']['voiceprint_review']
            check('saved review retains sample and score evidence',bool(receipt.get('sample_intervals'))
                  and bool(receipt.get('pair_scores')))
            check('input project copy unchanged',hashlib.sha256(project_path.read_bytes()).hexdigest()==original_hash)
            result['passed']=True
        except Exception:
            result['error']=traceback.format_exc()
        finally:
            if manager is not None:
                manager.close()
            if page is not None:
                page.undo_stack.setClean()
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            window.close()
    QTimer.singleShot(0,run)
