"""Opt-in isolated headed audit of the real Studio/template/frozen-frame path."""
import hashlib,json,os,time,traceback
from dataclasses import asdict
from pathlib import Path
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication,QDialog,QPushButton
from PySide6.QtTest import QTest
from .studio_acceptance_audit import require


def start(window,out):
    def run():
        from .cover_templates_ui import TemplatePicker
        from .cover_document import CoverDocument
        from .cover_local_library import LocalCoverLibrary
        from .cover_render import CoverRenderer
        from .cover_psd import psd_metadata
        from .build_identity import load_build_identity
        report=dict(passed=False,checks={},build=load_build_identity().to_dict())
        page=window.studio_page;controller=page.cover_controller;editor=None
        def pump(seconds=.05):
            until=time.monotonic()+seconds
            while time.monotonic()<until:QApplication.processEvents();time.sleep(.004)
        def wait(predicate,label,seconds=40):
            until=time.monotonic()+seconds
            while not predicate() and time.monotonic()<until:pump()
            require(predicate(),label)
        def check(name,value):
            report['checks'][name]=bool(value)
            (out/'cover-frame-progress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
            require(value,name)
        def menu(index):
            QTimer.singleShot(60,lambda:page.make_cover_button.menu().actions()[index].trigger())
            QTimer.singleShot(80,page.make_cover_button.menu().hide)
            QTest.mouseClick(page.make_cover_button,Qt.LeftButton);pump()
        def foreground(doc):return [asdict(x) for x in doc.layers if x.id!=doc.background_id]
        try:
            wait(lambda:page.project is not None and page.video.controller.observed_property('time-pos',None) is not None,'Studio media ready')
            page.video.set_paused(True);page._seek(1);pump(.4)
            library=LocalCoverLibrary();entry=next(e for e in library.entries() if e['name']=='我的封面模板2')
            master=library.asset(entry,'cover');before=hashlib.sha256(master.read_bytes()).hexdigest()
            master_doc=library.load_copy(entry)
            report['master_sha256']=before
            phase=os.environ.get('TWOBYTEASR_COVER_FRAME_PHASE','create')
            if phase=='reopen':
                editor=controller.new_cover();editor.open_document(out/'saved.2bytecover')
                wait(lambda:not editor.busy,'reopened cover')
                expected=json.loads((out/'expected.json').read_text('utf8'))
                doc=editor.session.document
                check('reopen self-contained frame and layers',doc.signature()==expected['signature'])
                editor.export_document(out/'reopened.png');wait(lambda:not editor.busy,'reopen export')
                check('reopen pixels equal',QImage(str(out/'reopened.png'))==QImage(str(out/'updated.png')))
                editor.grab().save(str(out/'reopened-headed.png'))
            else:
                controller.settings.setValue('cover/subtitles',False)
                original_project=page.project.to_dict()
                # The modal picker remains open while the audit moves Studio's
                # playback head, proving that its earlier frame is immutable.
                picker_timer=QTimer(window);picker_timer.setInterval(50)
                def choose():
                    picker=QApplication.activeModalWidget()
                    if not isinstance(picker,TemplatePicker):return
                    picker_timer.stop()
                    report['frozen_time_ms']=controller.last_receipt['milliseconds']
                    check('default replace frame enabled',picker.replace.isChecked())
                    page._seek(4)
                    check('head moved while chooser open',page.timeline.playhead_ms>=3900)
                    for index in range(picker.cards.count()):
                        if picker.cards.item(index).data(Qt.UserRole)['id']==entry['id']:
                            picker.cards.setCurrentRow(index);break
                    picker.grab().save(str(out/'template-picker-headed.png'))
                    QTest.mouseClick(next(b for b in picker.findChildren(QPushButton) if b.text()=='使用模板'),Qt.LeftButton)
                picker_timer.timeout.connect(choose);picker_timer.start();menu(2)
                wait(lambda:controller.editor is not None and not controller.editor.busy,'template applied')
                editor=controller.editor;doc=editor.session.document
                check('frozen source did not follow new head',900<=doc.source['milliseconds']<=1100)
                check('template canvas preserved',(doc.width,doc.height)==(2560,1440))
                check('template title and stickers preserved',foreground(doc)==foreground(master_doc))
                check('explicit bottom background',doc.layers[0].id==doc.background_id and len(doc.layers)==len(master_doc.layers)+1)
                first=doc.signature();first_bg=doc.background_id
                editor.export_document(out/'frozen.png');wait(lambda:not editor.busy,'frozen export')
                editor.grab().save(str(out/'frozen-headed.png'))
                # Use the editor's own update entry, then the Studio screenshot action.
                action=next(a for a in editor.toolbar.actions() if a.text()=='使用 / 更新当前帧')
                QTest.mouseClick(editor.toolbar.widgetForAction(action),Qt.LeftButton)
                page._seek(4);pump(.3);menu(0)
                wait(lambda:not controller.busy and editor.isVisible(),'updated frame')
                doc=editor.session.document
                check('active update uses new time',3900<=doc.source['milliseconds']<=4100)
                check('update never stacks backgrounds',doc.background_id==first_bg and len(doc.layers)==len(master_doc.layers)+1)
                check('update preserves foreground',foreground(doc)==foreground(master_doc))
                updated=doc.signature();editor.undo();check('frame undo exact',editor.session.document.signature()==first)
                editor.redo();check('frame redo exact',editor.session.document.signature()==updated)
                editor.export_document(out/'updated.png');wait(lambda:not editor.busy,'updated export')
                check('actual video pixels changed',QImage(str(out/'frozen.png'))!=QImage(str(out/'updated.png')))
                editor.save_document(out/'saved.2bytecover');wait(lambda:not editor.busy,'cover save')
                editor.save_document(out/'saved.psd');wait(lambda:not editor.busy,'PSD save')
                metadata=psd_metadata(out/'saved.psd')
                check('PSD preserves editable title',any((x.get('text') or {}).get('text')=='在这里输入标题' for x in metadata['layers']))
                check('PSD carries frame and two stickers',sum(x.get('kind')!='text' for x in metadata['layers'])>=3)
                editor.grab().save(str(out/'updated-headed.png'))
                (out/'expected.json').write_text(json.dumps(dict(signature=editor.session.document.signature()),ensure_ascii=False),'utf8')
                check('Studio project unchanged',page.project.to_dict()==original_project)
            check('isolated master bytes unchanged',hashlib.sha256(master.read_bytes()).hexdigest()==before)
            report['passed']=True
        except Exception as exc:
            report.update(error=str(exc),traceback=traceback.format_exc())
            if editor is not None:editor.grab().save(str(out/'failure-headed.png'))
        finally:
            phase=os.environ.get('TWOBYTEASR_COVER_FRAME_PHASE','create')
            (out/(phase+'-cover-frame.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
            for opened in list(controller.editors):
                opened.session.saved_signature=opened.session.document.signature();opened.close()
            page.project_dirty=False
            window.close();QApplication.quit()
    QTimer.singleShot(1800,run)
