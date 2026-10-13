"""Opt-in compact overlap and acoustic handoff checks through normal app entry."""
import json
import time
import traceback


def start(window, out):
    from PySide6.QtCore import QTimer
    QTimer.singleShot(1800, lambda: run(out, window))


def run(out, window=None):
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from twobyteasr.studio_ui import SubtitleStudioPage
    from twobyteasr.studio_project import load_project, save_project
    from twobyteasr.blank_project_audit import _capture
    from twobyteasr.display_handoff_ui import open_handoff_preview
    from twobyteasr.subtitle_layout_ui import open_layout_preview
    from twobyteasr.visual_snapshot import build_visual_cue_snapshot
    from twobyteasr.advanced_live_renderer import render_live_snapshot
    from twobyteasr.selection_geometry import image_bounds, measure_native
    from copy import deepcopy
    from twobyteasr.style_resolution import resolve_cue_visual
    from twobyteasr.studio_subtitle_export import compile_srt
    from twobyteasr.ass_compiler import compile_ass
    from twobyteasr.display_timing import project_display_tail_plan

    app = QApplication.instance() or QApplication([])
    page = window.studio_page if window is not None else SubtitleStudioPage()
    if window is None:
        page.resize(1500, 930)
        page._generate_waveform = lambda *_a, **_k: None
        page.show()
    result = dict(passed=False, checks=[], screenshots=[], source_only=window is None)
    from .build_identity import load_build_identity
    result['build'] = load_build_identity().to_dict()
    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        if not ok: raise AssertionError(name + ': ' + str(detail))
    def pump(seconds=.25):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            app.processEvents(); time.sleep(.01)
    def wait(predicate, timeout=60):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            app.processEvents(); time.sleep(.02)
            if predicate(): return True
        return False
    def shot(name):
        pump(.4); _capture(window or page, out/(name+'.png'))
        result['screenshots'].append(name+'.png')
    def seek(ms):
        page._seek(ms/1000)
        check('seek '+str(ms), wait(lambda: abs(page.timeline.playhead_ms-ms)<45
              and not page.video.playback_position_snapshot().seeking, 20))
        pump(.4)
    def position(cue):
        s=resolve_cue_visual(page.project,cue).style
        return [s.position_x,s.position_y]
    try:
        path=out/'project.2byteproj' if window is not None else out/'repaired.2byteproj'
        if window is None: page.open_project(path, skip_dirty_guard=True)
        check('normal Studio media ready', wait(lambda: page.project is not None
            and page._readiness.ready and page.video.controller is not None
            and page.video._startup_state=='READY'))
        page.volume_slider.setValue(0); page.video.set_paused(True)
        p=page.project
        content=[(c.id,c.text,c.speaker_id,c.style_id,c.start_ms) for c in p.cues]
        evidence=json.dumps(p.asr_evidence,sort_keys=True,ensure_ascii=False)
        old_ends={c.id:c.end_ms for c in p.cues}
        ends,audit=project_display_tail_plan(p)
        result['timing_audit']=audit
        seek(4650); shot('01-before-handoff')
        dialog=open_handoff_preview(page); pump()
        check('handoff preview is read only', {c.id:c.end_ms for c in p.cues}==old_ends)
        _capture(dialog, out/'02-handoff-dialog.png')
        shot('02-handoff-preview')
        QTest.mouseClick(dialog.apply_button,Qt.LeftButton); pump()
        check('reviewed ends applied', all(c.end_ms==ends.get(c.id,old_ends[c.id]) for c in p.cues))
        check('measured wo-hui-le boundary', next(c.end_ms for c in p.cues if c.id=='2')==4540)
        page.undo_stack.undo(); pump()
        check('one undo restores ends', {c.id:c.end_ms for c in p.cues}==old_ends)
        page.undo_stack.redo(); pump()
        seek(4650); shot('03-after-handoff')
        check('finished speaker absent at 4.650', '2' not in {c.id for c in page.session.runtime.cues_at(4650)})
        # Only re-layout later captions which actually obscure their peers.
        # An already separated hand placement (the user's first image) stays.
        ordered=sorted(p.cues,key=lambda c:(c.start_ms,c.end_ms,c.id))
        bounds={}
        def box(c):
            if c.id not in bounds:
                bounds[c.id]=measure_native(deepcopy(p),c.id,1920,1080)['bounds']
            return bounds[c.id]
        targets=set()
        for i,a in enumerate(ordered):
            for b in ordered[i+1:]:
                if b.start_ms>=a.end_ms:break
                x,y,w,h=box(a); xx,yy,ww,hh=box(b)
                if (min(x+w,xx+ww)>max(x,xx) and
                        (min(y+h,yy+hh)-max(y,yy)>4 or a.id in targets)):
                    targets.add(b.id)
        before_positions={c.id:position(c) for c in p.cues}
        result['layout_targets']=sorted(targets)
        dialog=open_layout_preview(page,targets); pump()
        if dialog.reset_manual.isEnabled():
            QTest.mouseClick(dialog.reset_manual,Qt.LeftButton,pos=QPoint(10,dialog.reset_manual.height()//2)); pump()
        check('reset manual checkbox actually checked', dialog.reset_manual.isChecked())
        check('layout apply enabled', dialog.apply_button.isEnabled())
        check('layout preview is read only', {c.id:position(c) for c in p.cues}==before_positions)
        _capture(dialog, out/'04-layout-dialog.png')
        shot('04-layout-preview')
        from twobyteasr.subtitle_layout_ui import _snapshot
        (out/'layout-guard-before.json').write_text(json.dumps(dialog.before,ensure_ascii=False,default=str),'utf8')
        (out/'layout-guard-current.json').write_text(json.dumps(_snapshot(p),ensure_ascii=False,default=str),'utf8')
        QTest.mouseClick(dialog.apply_button,Qt.LeftButton); pump()
        result['layout_dialog_result']=dialog.result()
        check('layout actually changes positions', any(position(c)!=before_positions[c.id] for c in p.cues))
        check('unselected hand placements kept', all(position(c)==before_positions[c.id]
                                                     for c in p.cues if c.id not in targets))
        check('reference first image preserved', all(position(c)==before_positions[c.id]
                                                     for c in p.cues if c.id in ('13','14')))
        after_positions={c.id:position(c) for c in p.cues}
        after_bounds={}
        for key in targets:
            c=next(c for c in p.cues if c.id==key)
            box_b=measure_native(deepcopy(p),key,1920,1080)['bounds']
            for a in ordered:
                if a.start_ms>=c.start_ms or a.end_ms<=c.start_ms:continue
                box_a=measure_native(deepcopy(p),a.id,1920,1080)['bounds']
                # ADR0099 (2026-10-10): a later caption may take a free lower
                # row, so the rule is "never cover each other", not "above".
                gap=max(box_a[1]-(box_b[1]+box_b[3]), box_b[1]-(box_a[1]+box_a[3]))
                after_bounds[key]={'earlier':a.id,'gap':gap,'bounds':[box_a,box_b]}
                check('simultaneous captions do not cover each other '+key,gap>=0,after_bounds[key])
        result['native_layout_bounds']=after_bounds
        if targets:
            key=next(iter(sorted(targets,key=lambda key:next(c.start_ms for c in p.cues if c.id==key))))
            c=next(c for c in p.cues if c.id==key)
            seek(c.start_ms+5); shot('04b-automatic-overlap')
        seek(36848); shot('05-true-overlap')
        seek(37450); shot('06-upper-alone')
        check('upper stays after earlier finishes', {c.id:position(c) for c in p.cues}==after_positions)
        seek(36848)
        QTest.mouseClick(page.play_button,Qt.LeftButton); pump(.9)
        QTest.mouseClick(page.play_button,Qt.LeftButton); pump(.5)
        check('playback keeps full lifetime anchors', {c.id:position(c) for c in p.cues}==after_positions)
        check('text styles speakers starts unchanged', content==[(c.id,c.text,c.speaker_id,c.style_id,c.start_ms) for c in p.cues])
        check('original acoustic evidence unchanged', evidence==json.dumps(p.asr_evidence,sort_keys=True,ensure_ascii=False))
        save_project(p,path)
        restored=load_project(path)
        check('save reopen timing', [(c.start_ms,c.end_ms) for c in restored.cues]==[(c.start_ms,c.end_ms) for c in p.cues])
        check('save reopen positions', [c.transform for c in restored.cues]==[c.transform for c in p.cues])
        (out/'repaired.srt').write_text(compile_srt(restored.cues),'utf8')
        (out/'repaired.ass').write_text(compile_ass(restored),'utf8')
        check('SRT end 4.540', '00:00:04,540' in (out/'repaired.srt').read_text('utf8'))
        check('ASS end 4.54', ',0:00:04.54,' in (out/'repaired.ass').read_text('utf8'))
        # A real batch font edit with geometry used to flatten every cue onto
        # one baseline, disabling the generated layout via manual overrides.
        # Exercise the inspector path, then undo so delivery keeps user styles.
        before_batch=[deepcopy(c.transform) for c in p.cues]
        before_styles=deepcopy(p.styles)
        before_index=page.undo_stack.index()
        page.style_scope.setCurrentIndex(page.style_scope.findData('all'))
        page.style_apply_geometry.setChecked(True)
        font=page.style_font_size.lineEdit(); font.setFocus()
        QTest.keyClick(font,Qt.Key_A,Qt.ControlModifier)
        QTest.keyClicks(font,str(round(page.style_font_size.value())+1))
        QTest.keyClick(font,Qt.Key_Return); pump(.4)
        page._commit_style_now(); pump(.6)
        check('batch font is one undo transaction',page.undo_stack.index()==before_index+1)
        by_id={c.id:c for c in p.cues}
        check('batch geometry automatically keeps later cue above',position(by_id['2'])[1]<position(by_id['1'])[1])
        seek(36848); shot('07-batch-style-auto-layout')
        page.undo_stack.undo(); pump(.5)
        check('batch undo restores user placements',[c.transform for c in p.cues]==before_batch)
        check('batch undo restores user styles',p.styles==before_styles)
        result['after_positions']=after_positions
        result['changed_ends']=ends
        result['passed']=True
    except BaseException:
        result['error']=traceback.format_exc()
        try: shot('failure')
        except Exception: pass
    finally:
        page.undo_stack.setClean(); page.project_dirty=False
        if window is not None:
            window.close(); result['gui_shutdown']=True
            app.quit()
        else:
            page.close_page(); page.close(); pump(.4)
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    return 0 if result['passed'] else 1

