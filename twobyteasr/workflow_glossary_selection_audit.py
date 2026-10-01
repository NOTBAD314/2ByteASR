"""Mouse/key verification of the production review widget on an isolated desktop."""
import json
import os
import sys
import time
import traceback


def start(window,output):
    from PySide6.QtCore import QTimer,Qt,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QPushButton
    from .glossary_skill import SearchedTerm,TermDiff
    from .glossary_skill_ui import GlossaryUpdateReviewDialog
    from .build_identity import load_build_identity
    from .studio_acceptance_audit import require
    result=dict(build=vars(load_build_identity()),executable=sys.executable,checks=[],
        environment='Windows separate desktop; actual Qt mouse/key events; no human desktop acceptance')
    def run():
        dlg=None
        try:
            choices={}
            diffs=[TermDiff('new',SearchedTerm(term=f'候选{i:04d}',
                category=('角色','技能','装备')[i%3],category_key=('character','skill','equipment')[i%3],
                priority='core' if i%3==0 else 'optional',verification='catalog_verified',
                sources=({'url':'https://example.com/roster'},)),checked_by_default=False) for i in range(1200)]
            dlg=GlossaryUpdateReviewDialog(window,'批量交互验证',dict(diffs=diffs,review_choices=choices,candidate_count=1200))
            dlg.setWindowFlag(Qt.WindowType.Window,True);dlg.resize(1200,850);dlg.show();QApplication.processEvents()
            view=dlg.table;model=dlg.model
            def check(name,value):
                result['checks'].append(dict(name=name,passed=bool(value)));require(value,name)
            def click(row,column=1,mods=Qt.KeyboardModifier.NoModifier):
                index=model.index(row,column);view.scrollTo(index);QApplication.processEvents()
                QTest.mouseClick(view.viewport(),Qt.MouseButton.LeftButton,mods,view.visualRect(index).center())
                QApplication.processEvents()
            click(0);check('row click checks once',model.checked_count()==1)
            click(0);check('row click again clears once',model.checked_count()==0)
            click(0,0);check('checkbox checks once',model.checked_count()==1)
            click(0,0);check('checkbox clears once',model.checked_count()==0)
            index=model.index(0,1);point=view.visualRect(index).center()
            QTest.mousePress(view.viewport(),Qt.LeftButton,pos=point)
            QTest.mouseMove(view.viewport(),point+QPoint(30,0))
            QTest.mouseRelease(view.viewport(),Qt.LeftButton,pos=point+QPoint(30,0))
            check('drag does not toggle',model.checked_count()==0)
            button=QPushButton('查看来源');view.setIndexWidget(model.index(0,5),button)
            hits=[];button.clicked.connect(lambda:hits.append(True));QTest.mouseClick(button,Qt.LeftButton)
            check('interactive source control does not toggle',hits and model.checked_count()==0)
            view.setIndexWidget(model.index(0,5),None)
            QTest.mouseClick(dlg.detail_toggle,Qt.LeftButton)
            QApplication.processEvents()
            check('bounded detail opens without toggling',dlg.detail.isVisible() and model.checked_count()==0)
            QTest.mouseClick(dlg.copy_detail,Qt.LeftButton)
            check('full plaintext source copied without toggling',
                'https://example.com/roster' in QApplication.clipboard().text() and model.checked_count()==0)
            QTest.mouseClick(dlg.detail_toggle,Qt.LeftButton)
            click(1,mods=Qt.ControlModifier);click(5,mods=Qt.ShiftModifier)
            check('modifiers only highlight',model.checked_count()==0)
            QTest.keyClick(view,Qt.Key_Space)
            check('Space checks highlighted range',model.checked_count()==len(view.selectionModel().selectedRows()))
            QTest.keyClick(view,Qt.Key_Space);check('Space clears fully checked range',model.checked_count()==0)
            dlg.category_filter.setCurrentIndex(dlg.category_filter.findData('技能'))
            model.check_filtered(True);skill_ids=set(model._checked)
            dlg.category_filter.setCurrentIndex(dlg.category_filter.findData('角色'))
            began=time.perf_counter();model.check_filtered(True);model.check_filtered(False);model.check_filtered(None)
            result['1200_candidate_bulk_ms']=(time.perf_counter()-began)*1000
            check('filtered scope keeps hidden skill choices',skill_ids.issubset(model._checked) and model.checked_count()==800)
            before=set(model._checked);model.sort(1,Qt.DescendingOrder)
            check('sorting preserves every checked identity',before==model._checked)
            view.setFocus();QTest.keyClick(view,Qt.Key_A,Qt.ControlModifier);QTest.keyClick(view,Qt.Key_Space)
            check('Ctrl+A Space affects all filtered rows only',model._checked==skill_ids)
            dlg.search_box.setText('候选');dlg.search_box.setFocus();QTest.keyClick(dlg.search_box,Qt.Key_A,Qt.ControlModifier)
            check('search Ctrl+A selects text only',dlg.search_box.selectedText()=='候选' and model._checked==skill_ids)
            model.check_none();check('global clear includes hidden choices',not model._checked and all(v is False for v in choices.values()))
            model.check_core_verified();check('restore all reliable core',model.checked_count()==400)
            chosen=next(d for d in diffs if d.term.category=='装备');identity=model.identity(chosen)
            choices[identity]=True
            upgraded=TermDiff('new',SearchedTerm(chosen.term.term,category='装备',category_key='equipment',
                sources=chosen.term.sources,verification='page_verified'),checked_by_default=False)
            added=TermDiff('new',SearchedTerm('新增核心',category='角色',category_key='character'),checked_by_default=True)
            dlg.hide()
            other=GlossaryUpdateReviewDialog(window,'续跑验证',dict(diffs=[upgraded,added,*[d for d in diffs if d.term.term!=chosen.term.term]],review_choices=choices))
            check('continued task restores choices and new defaults',identity in other.model._checked and other.model.identity(added) in other.model._checked)
            other.hide();other.deleteLater()
            dlg.search_box.clear();dlg.category_filter.setCurrentIndex(0);dlg.show();QApplication.processEvents()
            dlg.grab().save(str(output/'selection-1200.png'))
            real=os.environ.get('TWOBYTEASR_GLOSSARY_RESULT')
            if real:
                from pathlib import Path
                data=json.loads(Path(real).read_text('utf8'));rows=[]
                for d in data['diffs']:
                    d=dict(d);d['term']=SearchedTerm(**d['term']);rows.append(TermDiff(**d))
                real_dlg=GlossaryUpdateReviewDialog(window,'异环',dict(data,diffs=rows));real_dlg.setWindowFlag(Qt.WindowType.Window,True)
                real_dlg.resize(1280,900);real_dlg.show();QApplication.processEvents()
                result['real_candidates']=len(rows);result['real_default_checked']=real_dlg.model.checked_count()
                check('real default selections are reliable core',all(d.term.priority in {'core','recommended'} and d.term.verification in {'page_verified','catalog_verified'} for d in real_dlg.model.checked_diffs()))
                real_dlg.grab().save(str(output/'real-candidates.png'));real_dlg.hide();real_dlg.deleteLater()
            result['completed']=True
        except Exception:result['error']=traceback.format_exc();result['completed']=False
        finally:
            if dlg:dlg.hide();dlg.deleteLater()
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
            window.studio_page.undo_stack.setClean();window.close()
    QTimer.singleShot(1200,run)
