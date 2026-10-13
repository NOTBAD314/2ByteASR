"""Opt-in normal-window measurements of current-frame capture and cue edits."""
import cProfile
import json
import os
from pathlib import Path
import pstats
import time
import traceback


def start(window, out):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity

    def run():
        page = window.studio_page
        result = dict(passed=False, checks=[], measurements={}, build=load_build_identity().to_dict())
        def save():
            (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        def check(name, value, detail=None):
            result['checks'].append(dict(name=name, passed=bool(value), detail=detail)); save()
            if not value: raise AssertionError(name + ': ' + str(detail))
        def pump(seconds=.15):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                QApplication.processEvents(); time.sleep(.004)
        def wait(test, seconds=45):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                pump(.02)
                if test(): return True
            return False
        def measure(name, action):
            samples=[]
            for i in range(4):
                t=time.perf_counter(); action(i); samples.append((time.perf_counter()-t)*1000)
                pump(.4)
            result['measurements'][name]=samples; save()
        try:
            check('media ready', wait(lambda: page.project and page._readiness.ready
                  and page.video._startup_state=='READY', 90))
            page.volume_slider.setValue(0); page.video.set_paused(True)
            point=int(os.environ.get('TWOBYTEASR_COVER_EDIT_MS','330740'))
            page._seek(point/1000)
            check('seek settled', wait(lambda: abs(page.timeline.playhead_ms-point)<45
                  and not page.video.playback_position_snapshot().seeking))
            pump(.5)
            cue=next((c for c in page.project.cues if c.start_ms<=point<c.end_ms),page.project.cues[0])
            page.cue_controller.select_cue(cue.id); pump(.4)
            page.style_scope.setCurrentIndex(page.style_scope.findData(
                os.environ.get('TWOBYTEASR_COVER_EDIT_SCOPE','current')))
            original_text=cue.text; original_transform=dict(cue.transform or {})
            _capture(window,out/'before.png')
            profiler=cProfile.Profile(); profiler.enable()
            measure('text_commit_ms',lambda i: page.cue_controller.set_text(cue.id,original_text+str(i)))
            profiler.disable(); profiler.dump_stats(str(out/'edit.prof'))
            with (out/'edit-profile.txt').open('w',encoding='utf8') as stream:
                pstats.Stats(profiler,stream=stream).strip_dirs().sort_stats('cumtime').print_stats(65)
            # Measure without cProfile, whose tracing changes absolute timings.
            measure('text_ms',lambda i: page.cue_controller.set_text(cue.id,original_text+str(i+5)))
            from .studio_commands import SetCueFieldsCommand
            measure('move_ms',lambda i: page.undo_stack.push(SetCueFieldsCommand(page.project,cue.id,
                {'transform':dict(original_transform,position_x=950+i*5)},'audit move')))
            before_undo=dict(cue.transform); page.undo_stack.undo(); pump(); page.undo_stack.redo(); pump()
            check('move undo redo',cue.transform==before_undo)
            size=page.style_font_size.value()
            def edit_style(i):
                page.style_font_size.setValue(size+i+1)
                QTest.keyClick(page.style_font_size,Qt.Key_Return)
            measure('style_ms',edit_style)
            from .style_resolution import resolve_cue_visual
            check('style changes the cue',resolve_cue_visual(page.project,cue).style.font_size==size+4)
            profile=cProfile.Profile();profile.enable();edit_style(5);profile.disable()
            profile.dump_stats(str(out/'style.prof'))
            with (out/'style-profile.txt').open('w',encoding='utf8') as stream:
                pstats.Stats(profile,stream=stream).strip_dirs().sort_stats('cumtime').print_stats(60)
            _capture(window,out/'edited.png')
            # Restore all audit edits before comparing the real video frame.
            while page.undo_stack.canUndo(): page.undo_stack.undo()
            pump(.7)
            check('text and transform restored',cue.text==original_text and dict(cue.transform or {})==original_transform)
            page._seek(point/1000); check('capture seek settled', wait(lambda:
                abs(page.timeline.playhead_ms-point)<45 and not page.video.playback_position_snapshot().seeking))
            pump(.3)
            page.video.controller.screenshot_to_file(out/'preview-video.png',mode='video')
            check('preview pixels saved',wait(lambda:(out/'preview-video.png').is_file(),10))
            controller=page.cover_controller; controller.settings.setValue('cover/subtitles',False)
            t=time.perf_counter()
            # Actual menu action, with QTest invoking its owning tool button.
            QTimer.singleShot(60,lambda: page.make_cover_button.menu().actions()[0].trigger())
            QTimer.singleShot(80,page.make_cover_button.menu().hide)
            QTest.mouseClick(page.make_cover_button,Qt.LeftButton)
            check('cover opened',wait(lambda:controller.editor is not None and not controller.busy,180),page.save_state.text())
            result['measurements']['cover_seconds']=time.perf_counter()-t
            result['capture_receipt']=controller.last_receipt
            editor=controller.editor
            from .cover_render import CoverRenderer
            CoverRenderer().render(editor.session.document).save(str(out/'cover.png'))
            _capture(editor,out/'cover-editor.png')
            from PIL import Image
            import numpy as np
            a=np.array(Image.open(out/'preview-video.png').convert('RGB').resize((640,360)),dtype=float)
            b=np.array(Image.open(out/'cover.png').convert('RGB').resize((640,360)),dtype=float)
            result['measurements']['frame_rgb_mae']=float(np.abs(a-b).mean())
            # Baseline records the mismatch; the final run enforces it.
            if os.environ.get('TWOBYTEASR_COVER_EDIT_BASELINE')!='1':
                check('cover matches preview',result['measurements']['frame_rgb_mae']<8,
                      result['measurements']['frame_rgb_mae'])
                check('cover latency under 5s',result['measurements']['cover_seconds']<5)
            check('frozen playhead',abs(editor.session.document.source['milliseconds']-point)<45)
            # Capture the default subtitle-inclusive route as well.
            caption_ms=cue.start_ms+min(400,(cue.end_ms-cue.start_ms)//2)
            page._seek(caption_ms/1000)
            check('caption time settled',wait(lambda:abs(page.timeline.playhead_ms-caption_ms)<45
                  and not page.video.playback_position_snapshot().seeking))
            pump(.3)
            page.video.controller.screenshot_to_file(out/'caption-time-video.png',mode='video')
            check('caption time video saved',wait(lambda:(out/'caption-time-video.png').is_file(),10))
            controller.settings.setValue('cover/subtitles',True)
            prior=controller.editor;start=time.perf_counter();controller.create()
            check('captioned cover opened',wait(lambda:controller.editor is not prior and not controller.busy,90))
            result['measurements']['captioned_cover_seconds']=time.perf_counter()-start
            CoverRenderer().render(controller.editor.session.document).save(str(out/'cover-with-captions.png'))
            base=np.array(Image.open(out/'caption-time-video.png').convert('RGB').resize((640,360)),dtype=float)
            caption=np.array(Image.open(out/'cover-with-captions.png').convert('RGB').resize((640,360)),dtype=float)
            check('captioned cover preserves video',float(np.abs(base-caption).mean())<12)
            result['passed']=True
        except BaseException:
            result['error']=traceback.format_exc()
        finally:
            for editor in list(page.cover_controller.editors):
                editor.session.saved_signature=editor.session.document.signature(); editor.close()
            page.project_dirty=False; page.undo_stack.setClean(); save()
            window.close(); result['gui_shutdown']=True; save(); QApplication.quit()
    QTimer.singleShot(1800,run)
