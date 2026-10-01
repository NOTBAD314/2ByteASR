"""DPI-aware, content-measured speaker cells using a real visible Studio."""
import argparse,json,os,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--expected-dpr',type=float)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    assert out.is_relative_to(ROOT/'tmp')
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='windows')
    from PySide6.QtCore import Qt,QPoint,QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QStyleOptionViewItem
    from twobyteasr.studio_ui import SubtitleStudioPage
    from twobyteasr.studio_speaker_manager import SpeakerManagerDialog,_CandidateExcerptDelegate
    from twobyteasr.studio_project import load_project,save_project
    result=dict(passed=False,checks=[],cells=[])
    app=QApplication.instance() or QApplication([])
    page=SubtitleStudioPage();page.resize(1440,920);page.volume_slider.setValue(0)
    page._generate_waveform=lambda *_a,**_k:None
    project=load_project(args.project)
    baseline={s.id:s.name for s in project.speakers}
    path=save_project(project,out/'layout-project.2byteproj')
    page.winId()
    page.windowHandle().setScreen(app.primaryScreen())
    page.move(app.primaryScreen().availableGeometry().topLeft()+QPoint(30,30))
    page.show()
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
        if not value:raise AssertionError(name)
    def wait(predicate,seconds=15):
        until=time.monotonic()+seconds
        while not predicate() and time.monotonic()<until:QTest.qWait(20)
        return predicate()
    errors=[]
    try:
        page.open_project(path,skip_dirty_guard=True)
        check('media ready',wait(lambda:page.project is not None and page.video._startup_state=='READY'))
        page.video.set_paused(True);page.volume_slider.setValue(0)
        result['dpr']=page.devicePixelRatioF()
        result['screens']=[dict(name=s.name(),dpr=s.devicePixelRatio(),geometry=list(s.geometry().getRect())) for s in app.screens()]
        result['window_screen']=page.screen().name()
        if args.expected_dpr:check('actual DPR',abs(result['dpr']-args.expected_dpr)<.01)
        def inspect():
            dialog=QApplication.activeModalWidget()
            try:
                check('existing manager opened',isinstance(dialog,SpeakerManagerDialog))
                for width in (800,1040):
                    dialog.resize(width,min(900,dialog.screen().availableGeometry().height()-65))
                    QTest.qWait(180)
                    table=dialog.candidate_table
                    for row,label in enumerate(dialog._role_boxes):
                        table.scrollToItem(table.item(row,0),table.ScrollHint.PositionAtCenter)
                        QTest.qWait(30)
                        preview=dialog._preview_buttons[label]
                        role=dialog._role_boxes[label]
                        for col,control in ((4,role),(5,preview)):
                            holder=table.cellWidget(row,col)
                            pos=control.mapTo(table.viewport(),QPoint(0,0))
                            check(f'{width}/{label}/{col} entire control visible',pos.x()>=0 and pos.x()+control.width()<=table.viewport().width()+1
                                  and pos.y()>=0 and pos.y()+control.height()<=table.viewport().height()+1)
                            center=control.mapTo(holder,control.rect().center())
                            check(f'{width}/{label}/{col} centered',abs(center.x()-holder.rect().center().x())<=1 and abs(center.y()-holder.rect().center().y())<=1,
                                  dict(center=[center.x(),center.y()],holder=list(holder.rect().getRect()),control=list(control.geometry().getRect()),layout=list(holder.layout().geometry().getRect())))
                        needed=preview.fontMetrics().horizontalAdvance(preview.text())+preview.iconSize().width()+12
                        check(f'{width}/{label} icon and audition text fit',preview.width()>=needed)
                        text=table.item(row,3).text()
                        layout,height=_CandidateExcerptDelegate.text_layout(text,table.font(),table.columnWidth(3)-16)
                        check(f'{width}/{label} all wrapped lines fit',table.rowHeight(row)>=height+12)
                        result['cells'].append(dict(width=width,raw=label,preview_width=preview.width(),text_icon_width=needed,
                            row_height=table.rowHeight(row),text_height=height,line_count=layout.lineCount(),
                            alignment='center' if layout.lineCount()==1 else 'left-top'))
                    table.scrollToTop();QTest.qWait(50)
                    import ctypes
                    from ctypes import wintypes
                    user32=ctypes.windll.user32
                    user32.SetWindowPos.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint]
                    user32.SetWindowPos(int(dialog.winId()),ctypes.c_void_p(-1),0,0,0,0,0x0001|0x0002|0x0010)
                    QTest.qWait(80)
                    point=dialog.mapToGlobal(QPoint(24,24));ratio=dialog.devicePixelRatioF()
                    user32.WindowFromPoint.argtypes=[wintypes.POINT];user32.WindowFromPoint.restype=ctypes.c_void_p
                    user32.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint];user32.GetAncestor.restype=ctypes.c_void_p
                    owner=user32.WindowFromPoint(wintypes.POINT(round(point.x()*ratio),round(point.y()*ratio)))
                    check(f'{width} screenshot belongs to manager',int(user32.GetAncestor(owner,2) or 0)==int(dialog.winId()))
                    pos=dialog.mapToGlobal(QPoint(0,0))
                    # The parented modal is actually in front of its Studio.
                    dialog.screen().grabWindow(0,pos.x(),pos.y(),dialog.width(),dialog.height()).save(str(out/f'manager-{width}.png'))
                check('raw display identities unchanged',{s.id:s.name for s in page.project.speakers}==baseline)
                check('confirmed S03 stays main',dialog._role_boxes['S03'].currentData()=='main')
            except Exception:
                dialog.grab().save(str(out/'manager-failure.png'))
                errors.append(traceback.format_exc())
            finally:
                if dialog:dialog.accept()
        QTimer.singleShot(180,inspect)
        QTest.mouseClick(page.speaker_manager_button,Qt.MouseButton.LeftButton)
        if errors:raise AssertionError(errors[0])
        result['passed']=True
    except Exception:
        result['error']=traceback.format_exc()
        page.grab().save(str(out/'failure.png'))
    finally:
        page.video.set_paused(True);page.undo_stack.setClean();page.close_page();QTest.qWait(150)
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks']),'error':result.get('error'),'dpr':result.get('dpr')},ensure_ascii=False))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
