"""Input-to-native-pixels sampling. Capture completion is an upper bound."""
import time
import numpy as np


def measure(page,panel,output,count,global_mode):
    from PySide6.QtCore import Qt,QPoint,QPointF,QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    from scripts.capture_process_window import print_window
    from PySide6.QtTest import QTest
    from .studio_splitter_audit import _native_rects,_picture_box
    from ..caption_style.caption_layer_transform import resolved_values
    _,native=_native_rects(page.video)
    if not native:raise RuntimeError('native mpv surface missing')
    hwnd=_native_rects.mpv_hwnd;size=(native[2],native[3])
    def capture():
        capture_started=time.perf_counter()
        captured=print_window(hwnd,(0,0,*size))
        at=time.perf_counter()
        capture.last_cost_ms=(at-capture_started)*1000
        image=captured
        pixels=np.asarray(image.convert('RGB'))
        roi=getattr(capture,'roi',None)
        ox,oy=0,0
        if roi:
            ox,oy,right,bottom=roi
            pixels=pixels[oy:bottom,ox:right]
        mask=np.all(pixels[:,:,:3]>230,axis=2)
        ys=np.flatnonzero(mask.any(axis=1))
        if len(ys)<6:return at,None,None,image
        breaks=np.flatnonzero(np.diff(ys)>3)
        if len(breaks):
            split=ys[breaks[-1]]+1
        else:split=ys[0]
        def bbox(y0,y1):
            rows,cols=np.where(mask[y0:y1,:])
            return (float(cols.min()+ox),float(rows.min()+y0+oy),float(cols.max()+ox),float(rows.max()+y0+oy)) if len(cols)>8 else None
        return at,bbox(split,len(mask)),bbox(0,split),image
    overlay=page.position_overlay
    panel.refresh();QTest.qWait(350)
    _,initial,translation,im=capture()
    if initial is None:raise RuntimeError('native subtitle pixels not found')
    union=[initial]+([translation] if translation else [])
    capture.roi=(max(0,int(min(r[0] for r in union))-12),max(0,int(min(r[1] for r in union))-12),
        min(size[0],int(max(r[2] for r in union))+150),min(size[1],int(max(r[3] for r in union))+75))
    im.save(output/f'pixels-{count}-{global_mode}-before.png')
    rect=getattr(overlay,'_measured_bounds',None)
    point=rect.center().toPoint() if hasattr(rect.center(),'toPoint') else rect.center()
    cue=page._cue_lookup[page.selected_cue_id]
    origin=resolved_values(page.project,cue,'original')
    content=overlay._content_rect()
    sx=content.width()*page.video.devicePixelRatioF()/page.project.render_settings.get('play_res_x',1920)
    sy=content.height()*page.video.devicePixelRatioF()/page.project.render_settings.get('play_res_y',1080)
    samples=[]
    old_undo=page.undo_stack.index()
    QTest.mousePress(overlay,Qt.LeftButton,Qt.AltModifier,pos=point)
    for step in range(1,9):
        began=time.perf_counter()
        target=point+QPoint(step*8,step*3)
        QApplication.sendEvent(overlay,QMouseEvent(QEvent.MouseMove,QPointF(target),QPointF(overlay.mapToGlobal(target)),Qt.NoButton,Qt.LeftButton,Qt.AltModifier))
        handler=(time.perf_counter()-began)*1000
        dx=(overlay.position_x-origin['position_x'])*sx
        dy=(overlay.position_y-origin['position_y'])*sy
        expected=(initial[0]+dx,initial[1]+dy,initial[2]+dx,initial[3]+dy)
        matched=False;max_error=None;visible=None;upper=None
        deadline=time.monotonic()+1.5
        while time.monotonic()<deadline:
            QTest.qWait(2)
            observed,visible,upper,im=capture()
            if visible:
                max_error=max(abs(a-b) for a,b in zip(visible,expected))
                if max_error<=3.5:
                    matched=True;break
        samples.append(dict(capture_cost_ms=capture.last_cost_ms,step=step,input_to_native_pixels_ms=(observed-began)*1000,
            handler_ms=handler,matched=matched,error_px=max_error,expected=expected,observed=visible,
            translation_delta=(upper[0]-translation[0],upper[1]-translation[1]) if upper and translation else None,
            expected_delta=(dx,dy)))
        if step in (1,4,8):im.save(output/f'pixels-{count}-{global_mode}-{step}.png')
    QTest.mouseRelease(overlay,Qt.LeftButton,Qt.AltModifier,pos=point+QPoint(64,24))
    QTest.qWait(200)
    return dict(count=count,global_mode=global_mode,samples=samples,
        undo_steps=page.undo_stack.index()-old_undo,method='QTest input to first matching native mpv window capture; no profiler; capture completion upper bound')
