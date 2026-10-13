"""Actual Qt/renderer geometry, independent screenshots and interaction checks."""
import copy,json,time,traceback
from PySide6.QtCore import QTimer,Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

def start(window,out):
    p=window.studio_page;config=json.loads((out/'matrix.json').read_text('utf8'))
    result=dict(passed=False,cases=[],checks=[],real_user_click=False)
    def pump(seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:QApplication.processEvents();time.sleep(.005)
    def wait(test,seconds=15):
        deadline=time.monotonic()+seconds
        while not test() and time.monotonic()<deadline:pump(.05)
        if not test():raise AssertionError('geometry/readiness timeout')
    def check(name,value):
        result['checks'].append(dict(name=name,passed=bool(value)))
        if not value:raise AssertionError(name)
    def capture(case,phase,selected='sample'):
        p.ensure_active_subtitle_renderer(reason='selection_audit')
        wait(lambda:p.position_overlay._measured_bounds is not None,25)
        pump(.25)
        diag=copy.deepcopy(p.position_overlay.geometry_diagnostics)
        diag['mpv']={key:p.video.controller.get_property(key) for key in ('sub-scale','sub-scale-by-window','sub-use-margins','sub-ass-force-margins','osd-dimensions')}
        diag.update(case=case['id'],phase=phase,selected=p.selected_cue_id,visible=p.position_overlay.isVisible())
        result['last_geometry']={**diag,'actual_dpr':p.video.devicePixelRatioF(),'target_dpr':config['dpi'],
            'screen':window.screen().name() if window.screen() else None}
        check(case['id']+' '+phase+' actual DPI',abs(p.video.devicePixelRatioF()-config['dpi'])<.02)
        check(case['id']+' '+phase+' selected visible',p.selected_cue_id==selected and p.position_overlay.isVisible())
        box=p.position_overlay._measured_bounds;outer=p.position_overlay._subtitle_rect()
        check(case['id']+' '+phase+' four-pixel padding',all(abs(v-4)<.01 for v in
            (box.left()-outer.left(),box.top()-outer.top(),outer.right()-box.right(),outer.bottom()-box.bottom())))
        if case['route']=='html':check(case['id']+' fonts loaded',diag.get('fonts_ready') is True)
        window.grab().save(str(out/(case['id']+'-'+phase+'-window.png')))
        p.video.controller.screenshot_to_file(out/(case['id']+'-'+phase+'-native.png'))
        path=out/(case['id']+'-'+phase+'-native.png')
        wait(lambda:path.is_file() and path.stat().st_size>0,4)
        # Independent actual mpv pixels: this synthetic test pattern has no
        # white text in the caption region. Never infer containment merely
        # from the box setter's own geometry.
        from PIL import Image
        import numpy as np
        pixels=np.array(Image.open(path).convert('RGB'))
        content=p.position_overlay._content_rect();dpr=p.video.devicePixelRatioF()
        yy,xx=np.indices(pixels.shape[:2])
        in_content=(yy>content.top()*dpr+2)&(yy<(content.bottom()*dpr-2))
        white=((pixels.min(axis=2)>205)&((pixels.max(axis=2).astype(int)-pixels.min(axis=2))<18))
        white|=(pixels.max(axis=2)<35)&in_content
        ys,xs=np.where(white)
        if len(xs):
            ink=(int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1))
            frame=(outer.left()*dpr,outer.top()*dpr,outer.right()*dpr,outer.bottom()*dpr)
            diag['independent_visible_glyph_bbox']=ink
            diag['physical_selection_rect']=frame
            result['cases'].append(diag)
            check(case['id']+' '+phase+' actual white glyph contained',
                  ink[0]>=frame[0]-2 and ink[1]>=frame[1]-2 and ink[2]<=frame[2]+2 and ink[3]<=frame[3]+2)
        else:check(case['id']+' '+phase+' actual visible white glyphs',False)
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    def run():
        try:
            from .build_identity import load_build_identity
            result['identity']=load_build_identity().to_dict()
            for case in config['cases']:
                p.undo_stack.setClean();p.open_project(out/(case['id']+'.2byteproj'))
                wait(lambda:not p._readiness.active and p.video.controller and p.video.controller.running)
                window.showNormal();window.resize(1400,900);window.raise_();window.activateWindow()
                screen=QApplication.primaryScreen()
                if screen is not None:
                    window.windowHandle().setScreen(screen)
                    window.move(screen.availableGeometry().topLeft()+QPoint(12,12))
                    pump(.3)
                p.volume_slider.setValue(0);p.video.set_paused(True);p._set_review_mode(False)
                p.select_cue('sample');p._seek(1.5);pump(.4)
                p.position_edit_button.setChecked(True)
                capture(case,'wide')
                window.resize(1100,760);pump(.45);capture(case,'resized')
                # Real inspector event: make a visible style revision and invalidate geometry.
                if case['route']!='html':
                    p.style_font_size.setValue(74);p.style_outline_width.setValue(7)
                    p.style_spacing.setValue(3);p.style_bold.setChecked(not p.style_bold.isChecked())
                    p._apply_style();pump(.5)
                    capture(case,'style-change')
                    p._position_overlay_interaction_started();p._position_overlay_font_preview(90)
                    p._flush_transform_preview();pump(.6);capture(case,'scale-preview')
                    p._position_overlay_font_committed(90);pump(.5)
                p.select_cue('second');p._seek(4.8);pump(.6);capture(case,'switch-cue','second')
                before=p._selection_geometry.measurements
                p.video.set_paused(False);pump(1.1)
                check(case['id']+' no handles during playback',not p.position_overlay.isVisible())
                check(case['id']+' no measurements during playback',p._selection_geometry.measurements==before)
                p.video.set_paused(True);p._seek(4.8);pump(.5)
                p.select_cue(None);p.ensure_active_subtitle_renderer(reason='deselect_audit');pump(.2)
                result.setdefault('deselected_states',[]).append(dict(id=p.selected_cue_id,visible=p.position_overlay.isVisible()))
                check(case['id']+' null selected hides handles',not p.selected_cue_id and not p.position_overlay.isVisible())
                p.video.controller.screenshot_to_file(out/(case['id']+'-deselected.png'))
            result['passed']=True
        except Exception:result['error']=traceback.format_exc()
        finally:
            result['counts']={k:sum(c['passed']==v for c in result['checks']) for k,v in [('passed',True),('failed',False)]}
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            p.video.set_paused(True);p.undo_stack.setClean();QTimer.singleShot(150,window.close)
    QTimer.singleShot(400,run)
