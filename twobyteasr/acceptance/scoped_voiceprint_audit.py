"""Opt-in frozen/source UI audit on an explicitly owned project copy.

``TWOBYTEASR_VOICEPRINT_EXPECT`` (JSON) selects the case; the default is the
2026-10-27 DaVinci copy (460 captions, 11 labels compared into one):
  {"mode": "compare", "cues": 460, "speakers": 11, "after": 1}
  {"mode": "recognized", "cues": 86, "speakers": 5, "split": "API_S05", "after": 4}
"recognized" opens a project a recognition already merged by voiceprint: the
merged label is split back with its 主要 button and undone, then the remaining
candidates are confirmed.
  {"mode": "review", "cues": 86, "speakers": 5, "listed": 15}
"review" counts the 「需要检查」 list and reads the review headline of merged
captions, then of every caption after grouping all speakers into 统一字幕.
"""
from __future__ import annotations

import hashlib
import json
import os
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
    expect = {'mode':'compare','cues':460,'speakers':11,'after':1}
    expect.update(json.loads(os.environ.get('TWOBYTEASR_VOICEPRINT_EXPECT') or '{}'))
    original_hash = hashlib.sha256(project_path.read_bytes()).hexdigest()
    result = {'passed':False,'frozen':bool(getattr(sys,'frozen',False)),
              'identity':load_build_identity().to_dict(),'checks':[],
              'human_listening_verified':False,'confirmation':'simulated on isolated copy','expect':expect}

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
            speakers=int(expect['speakers'])
            check('real project opened',len(before)==int(expect['cues']) and len(page.project.speakers)==speakers,
                  (len(before),len(page.project.speakers)))
            if expect['mode']=='review':
                review_audit(page,check,output,result,expect)
                result['passed']=True
                return
            manager=SpeakerManagerDialog(page)
            manager.show();QTest.qWait(200)
            check('voiceprint button visible',manager.voiceprint_button.isVisible())
            if expect['mode']=='recognized':
                split=str(expect['split'])
                card=manager.cards[split]
                check('banner says labels were merged by voiceprint','已自动并入' in manager.banner_text.text(),
                      manager.banner_text.text())
                names=[c.name_edit.text() for c in manager.cards.values()]
                check('every card has its own name',len(names)==len(set(names)),names)
                check('merged label shown as merged',card.status_label.isVisible()
                      and '已并入' in card.status_label.text(),card.status_label.text())
                manager.grab().save(str(output/'voiceprint-merged.png'))
                QTest.mouseClick(card.roles.buttons['main'],Qt.MouseButton.LeftButton);QTest.qWait(150)
                check('split back with 主要',len(page.project.speakers)==speakers+1
                      and any(c.speaker_id==split for c in page.project.cues),manager.status.text())
                check('split keeps captions',before==[(c.id,c.start_ms,c.end_ms,c.text) for c in page.project.cues])
                names=[c.name_edit.text() for c in manager.cards.values()]
                check('names stay distinct after the split',len(names)==len(set(names)),names)
                manager.grab().save(str(output/'voiceprint-split.png'))
                page.undo_stack.undo();QTest.qWait(150)
                check('undo merges it again',len(page.project.speakers)==speakers
                      and not any(c.speaker_id==split for c in page.project.cues))
                manager.close();manager=SpeakerManagerDialog(page);manager.show();QTest.qWait(200)
                check('remaining candidates offered',manager.voiceprint_button.text()=='查看声纹候选',
                      manager.voiceprint_button.text())
                report=manager._voiceprint_report
            else:
                QTest.mouseClick(manager.voiceprint_button,Qt.MouseButton.LeftButton)
                check('analysis started',not manager.voiceprint_button.isEnabled(),manager.status.text())
                check('analysis completed',wait_until(lambda:manager.voiceprint_button.isEnabled(),90),manager.status.text())
                report=manager._voiceprint_report
                check('candidates proposed',bool(report) and bool(report.get('groups')),manager.status.text())
            groups=report['groups']
            result['groups']=groups
            check('candidates merge to the expected count',
                  speakers-sum(len(g)-1 for g in groups)==int(expect['after']),groups)
            check('not merged before confirmation',len(page.project.speakers)==speakers)
            label=groups[0][-1]
            sample=next(item for item in report['sample_intervals'] if item['label']==label)
            card=manager.cards[label]
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
            undo_before=page.undo_stack.index()
            QTest.mouseClick(manager.voiceprint_button,Qt.MouseButton.LeftButton)
            check('one undoable correction',len(page.project.speakers)==int(expect['after'])
                  and page.undo_stack.index()==undo_before+1,manager.status.text())
            check('captions preserved',before==[(c.id,c.start_ms,c.end_ms,c.text) for c in page.project.cues])
            check('translations preserved',translations==dict(page.project.generation_metadata.get('translations') or {}))
            page.undo_stack.undo();QTest.qWait(100)
            check('undo restores the labels',len(page.project.speakers)==speakers)
            page.undo_stack.redo();QTest.qWait(100)
            check('redo merges again',len(page.project.speakers)==int(expect['after']))
            saved=save_project(page.project,output/'corrected-copy.2byteproj')
            reopened=load_project(saved)
            check('saved copy retains translations',len(reopened.speakers)==int(expect['after'])
                  and translations==dict(reopened.generation_metadata.get('translations') or {}))
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


def review_audit(page, check, output, result, expect):
    """The 「需要检查」 list and headlines after merges (2026-10-28 user report:
    「说话人候选：R001_S01 / SUBTITLES」 on captions nothing disagreed about)."""
    from PySide6.QtTest import QTest
    from ..projects.speaker_organization import organization_command
    page.cue_model.set_filter('priority');QTest.qWait(200)
    listed=page.cue_model.rowCount()
    result['listed']=listed
    check('需要检查 holds only real issues',listed==int(expect['listed']),listed)
    page.window().grab().save(str(output/'review-list.png'))
    page.cue_model.set_filter('all');QTest.qWait(100)
    state=page.project.generation_metadata['speaker_recovery']
    merged=[label for group in state['voiceprint_automatic']['groups'] for label in group[1:]]
    cue_ids=[row['id'] for label in merged for row in state['cue_cache'][label]][:3]
    page._set_review_mode(True);QTest.qWait(150)

    def headlines(name, ids):
        rows=[]
        for cue_id in ids:
            page.select_cue(cue_id);page._refresh_review_summary_strip();QTest.qWait(120)
            rows.append((cue_id,page.review_summary_text.text(),page.review_reason_label.text()))
        result.setdefault('headlines',{})[name]=rows
        page.window().grab().save(str(output/f'review-{name}.png'))
        return rows
    rows=headlines('merged',cue_ids)
    check('merged captions are not 说话人候选不同',bool(rows) and not any('说话人候选不同' in h for _,h,_ in rows),rows)
    check('no empty-side model disagreement',not any('「- /' in r for _,_,r in rows),rows)
    page.undo_stack.push(organization_command(page.project,[s.id for s in page.project.speakers],'single',
                                              changed=page._speaker_structure_changed));QTest.qWait(300)
    check('grouped into 统一字幕',{c.speaker_id for c in page.project.cues}=={'SUBTITLES'})
    rows=headlines('subtitles',[c.id for c in page.project.cues][:3]+cue_ids[:1])
    check('统一字幕 captions are not 说话人候选不同',not any('说话人候选不同' in h for _,h,_ in rows),rows)
    page.undo_stack.undo();QTest.qWait(200)
    page._set_review_mode(False)

