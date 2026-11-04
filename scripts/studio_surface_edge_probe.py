"""Read actual desktop edge pixels of one owned HWND; never request repaint."""
import ctypes
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    import numpy as np
    from PIL import Image
    from twobyteasr.acceptance.visible_playback_audit import ScreenPixels
    out=Path(sys.argv[1]);config=json.loads((out/'probe-config.json').read_text('utf8'));hwnd=config['hwnd']
    u=ctypes.WinDLL('user32',use_last_error=True)
    u.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p];u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    u.IsWindow.argtypes=u.IsWindowVisible.argtypes=[W.HWND]
    u.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)]
    u.WindowFromPoint.argtypes=[W.POINT];u.WindowFromPoint.restype=W.HWND
    u.GetAncestor.argtypes=[W.HWND,W.UINT];u.GetAncestor.restype=W.HWND
    rows=[];surfaces=[];prior=None;t0=time.perf_counter();phase='startup';error=''
    folder=out/'screen-edges';folder.mkdir()
    (out/'probe-ready').touch()
    try:
        while time.perf_counter()-t0<160:
            at=time.perf_counter()
            try:phase=json.loads((out/'probe-phase.json').read_text('utf8'))['phase']
            except (OSError,ValueError):pass
            visible=bool(u.IsWindowVisible(hwnd));exists=bool(u.IsWindow(hwnd))
            row=dict(at=at,phase=phase,visible=visible,exists=exists,owned=False)
            if not exists:rows.append(row);break
            if visible:
                r=W.RECT();u.GetWindowRect(hwnd,ctypes.byref(r));x,y,w,h=r.left,r.top,r.right-r.left,r.bottom-r.top
                points=[(x+1,y+h//2),(x+w-2,y+h//2),(x+w//2,y+1),(x+w//2,y+h-2)]
                owned=all(int(u.GetAncestor(u.WindowFromPoint(W.POINT(a,b)),2) or 0)==hwnd for a,b in points)
                row.update(owned=owned,rect=[x,y,w,h])
                if owned and w>32 and h>32:
                    key=(x,y,w,h)
                    if key!=prior:
                        for s in surfaces:s.close()
                        surfaces=[ScreenPixels(x,y,w,12),ScreenPixels(x,y+h-12,w,12),
                                  ScreenPixels(x,y,12,h),ScreenPixels(x+w-12,y,12,h)];prior=key
                    strips=[s.grab()[:,:,:3][:,:,::-1].copy() for s in surfaces]
                    row['white_fraction']=[round(float(np.all(a>235,axis=2).mean()),5) for a in strips]
                    canvas=np.zeros((48,max(w,h),3),dtype=np.uint8)
                    for i,s in enumerate(strips):
                        if i>=2:s=np.rot90(s)
                        canvas[i*12:(i+1)*12,:s.shape[1],:]=s
                    name=f'{len(rows):05d}.png';Image.fromarray(canvas).save(folder/name,compress_level=1)
                    row['image']=name
            row['capture_ms']=round((time.perf_counter()-at)*1000,3);rows.append(row)
            time.sleep(max(.001,1/40-(time.perf_counter()-at)))
    except Exception as exc:error=repr(exc)
    finally:
        for s in surfaces:s.close()
        valid=[r for r in rows if r.get('owned') and 'white_fraction' in r]
        gaps=[(b['at']-a['at'])*1000 for a,b in zip(valid,valid[1:])]
        white=[r for r in valid if max(r['white_fraction'])>.5]
        result=dict(source='GetDC screen + BitBlt; no PrintWindow, QWidget.grab or repaint',rows=rows,error=error,
            valid_frames=len(valid),white_frames=len(white),first_white=white[0] if white else None,
            max_gap_ms=max(gaps,default=0),window_destroyed=bool(rows and not rows[-1]['exists']))
        (out/'screen-edges.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    return 0 if not error else 1


if __name__=='__main__':raise SystemExit(main())
