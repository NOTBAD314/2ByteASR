"""Real 34s two-speaker repair, native screen evidence, undo/autosave/export."""
import argparse,copy,hashlib,json,os,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    assert out.is_relative_to(ROOT/'tmp')
    os.environ.update(QT_QPA_PLATFORM='windows',LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'))
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from twobyteasr.studio_ui import SubtitleStudioPage
    from twobyteasr.studio_project import load_project,save_project
    from twobyteasr.studio_subtitle_export import export_subtitle_artifacts,SubtitleExportOptions
    original=load_project(args.project)
    original_hash=hashlib.sha256(args.project.read_bytes()).hexdigest()
    before_content={c.id:(c.text,c.style_id,c.speaker_id,c.evidence_refs) for c in original.cues}
    old=next(c for c in original.cues if '属于天然' in c.text)
    incoming=next(c for c in original.cues if '对倒霉体质' in c.text)
    result=dict(passed=False,checks=[],frames=[],before=dict(outgoing=vars(old),incoming=vars(incoming)),audio='muted, paused seek only')
    path=save_project(original,out/'handoff-current.2byteproj')
    app=QApplication.instance() or QApplication([])
    page=SubtitleStudioPage();page.resize(1480,930);page.volume_slider.setValue(0)
    page._generate_waveform=lambda *_a,**_k:None
    page.winId();page.windowHandle().setScreen(app.primaryScreen())
    page.move(app.primaryScreen().availableGeometry().topLeft()+QPoint(30,30))
    page.show()
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
        if not value:raise AssertionError(name)
    def wait(predicate,seconds=15):
        until=time.monotonic()+seconds
        while not predicate() and time.monotonic()<until:QTest.qWait(20)
        return predicate()
    def screen(name):
        import ctypes
        from ctypes import wintypes
        user32=ctypes.windll.user32
        user32.SetWindowPos.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint]
        user32.SetWindowPos(int(page.winId()),ctypes.c_void_p(-1),0,0,0,0,0x0001|0x0002|0x0010)
        QTest.qWait(50)
        point=page.mapToGlobal(QPoint(24,24));ratio=page.devicePixelRatioF()
        user32.WindowFromPoint.argtypes=[wintypes.POINT];user32.WindowFromPoint.restype=ctypes.c_void_p
        user32.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint];user32.GetAncestor.restype=ctypes.c_void_p
        hwnd=user32.WindowFromPoint(wintypes.POINT(round(point.x()*ratio),round(point.y()*ratio)))
        check(name+' native screen owner',int(user32.GetAncestor(hwnd,2) or 0)==int(page.winId()))
        pos=page.mapToGlobal(QPoint(0,0))
        page.screen().grabWindow(0,pos.x(),pos.y(),page.width(),page.height()).save(str(out/(name+'.png')))
    def at(ms,name):
        page._seek(ms/1000);QTest.qWait(300)
        active=list(page.session.runtime.cues_at(ms))
        try:
            native_text=page.video.controller._send(['get_property','sub-text'],timeout=.5)
        except Exception as exc:native_text={'unavailable':str(exc)}
        result['frames'].append(dict(requested_ms=ms,observed_ms=page.video.playback_position_snapshot().presentation_media_ms,
            active_cues=[dict(id=c.id,text=c.text,end_ms=c.end_ms) for c in active],native_sub_text=native_text,
            renderer_kind=getattr(page,'_advanced_canvas_source_kind','native_ass'),
            web_cue_id=getattr(page,'_web_live_cue_id','')))
        screen(name)
        return active
    try:
        page.open_project(path,skip_dirty_guard=True)
        check('media ready',wait(lambda:page.project is not None and page.video._startup_state=='READY' and not getattr(getattr(page,'_readiness',None),'active',False)))
        page.video.set_paused(True);page.volume_slider.setValue(0)
        page.timeline.set_visible_window(31800,3800)
        left=next(c for c in page.project.cues if c.id==old.id)
        right=next(c for c in page.project.cues if c.id==incoming.id)
        check('opening applies same visible interval repair',left.end_ms==34033 and right.start_ms==34033,
              dict(actual=[left.start_ms,left.end_ms,right.start_ms,right.end_ms],audit=page.project.generation_metadata.get('display_overlap_audit'),undo=page.undo_stack.undoText()))
        check('repair is one undo entry',page.undo_stack.canUndo() and '交接' in page.undo_stack.undoText())
        audit=copy.deepcopy(page.project.generation_metadata['display_overlap_audit']);result['audit']=audit
        page.undo_stack.undo()
        check('undo restores old end',left.end_ms==34130)
        active=at(34050,'before-data-repair-34.050')
        check('before data contains both cues',old.id in [c.id for c in active] and incoming.id in [c.id for c in active])
        page.undo_stack.redo()
        check('redo restores handoff',left.end_ms==right.start_ms==34033)
        for ms in (34017,34033,34050,34133):
            active=at(ms,f'after-{ms}')
            check(f'{ms} no false overlap',not ({old.id,incoming.id}<={c.id for c in active}))
            if ms>=right.start_ms:check(f'{ms} outgoing completely absent',old.id not in {c.id for c in active})
        check('content styles raw labels evidence refs unchanged',{c.id:(c.text,c.style_id,c.speaker_id,c.evidence_refs) for c in page.project.cues}==before_content)
        check('raw acoustic evidence unchanged',page.project.asr_evidence==original.asr_evidence)
        autosave=page.flush_autosave()
        check('production autosave preserves repaired end',autosave is not None and next(c for c in load_project(autosave).cues if c.id==old.id).end_ms==34033)
        QTest.mouseClick(page.save_button,Qt.MouseButton.LeftButton)
        check('save button persists same bound',next(c for c in load_project(path).cues if c.id==old.id).end_ms==34033)
        artifacts=export_subtitle_artifacts(page.project,out/'subtitles','handoff',SubtitleExportOptions(frozenset({'srt','ass'}),'both'))
        check('SRT ASS exported from same project',len(artifacts)==6)
        result['after']=dict(outgoing=vars(left),incoming=vars(right))
        result['track_statistics']={s.id:dict(display=s.name,cues=sum(c.speaker_id==s.id for c in page.project.cues),duration_ms=sum(c.end_ms-c.start_ms for c in page.project.cues if c.speaker_id==s.id)) for s in page.project.speakers}
        check('source file unchanged',hashlib.sha256(args.project.read_bytes()).hexdigest()==original_hash)
        check('all test seeks paused and muted',page.video._paused and page.volume_slider.value()==0)
        result['passed']=True
    except Exception:result['error']=traceback.format_exc();page.grab().save(str(out/'failure.png'))
    finally:
        page.video.set_paused(True);page.undo_stack.setClean();page.close_page();QTest.qWait(150)
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    print(json.dumps(dict(passed=result['passed'],checks=len(result['checks']),error=result.get('error')),ensure_ascii=False))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
