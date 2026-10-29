"""Independent-process desktop-pixel sampling for the owned audit window."""
import ctypes
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback


def main():
    from .visible_playback_audit import ScreenPixels
    from PIL import Image
    folder=Path(sys.argv[1])
    config=json.loads((folder/'pixel-config.json').read_text('utf8'))
    surfaces={name:ScreenPixels(*rect) for name,rect in config['rects'].items()}
    rows=[];error=''
    user=ctypes.windll.user32
    # Config rectangles are physical desktop pixels from the Qt GUI. Without
    # this per-thread context WindowFromPoint virtualizes them on scaled displays.
    user.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
    user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    user.GetForegroundWindow.restype=ctypes.c_void_p
    class Point(ctypes.Structure):
        _fields_=[('x',ctypes.c_long),('y',ctypes.c_long)]
    user.WindowFromPoint.argtypes=[Point];user.WindowFromPoint.restype=ctypes.c_void_p
    try:
        (folder/'pixel-ready').touch()
        while not (folder/'pixel-stop').exists():
            begin=time.perf_counter()
            pid=ctypes.c_ulong()
            user.GetWindowThreadProcessId(ctypes.c_void_p(user.GetForegroundWindow()),ctypes.byref(pid))
            row={'at':begin,'foreground_owned':pid.value==config['pid']}
            x,y,w,h=config['rects']['cursor']
            visible=True
            point_pids=[]
            for fraction in (0.02,.5,.98):
                handle=user.WindowFromPoint(Point(round(x+w*fraction),round(y+h/2)))
                user.GetWindowThreadProcessId(ctypes.c_void_p(handle),ctypes.byref(pid))
                point_pids.append(pid.value)
                visible &= pid.value==config['pid']
            row['visible_owned']=bool(visible)
            row['point_pids']=point_pids
            still=(folder/'pixel-still').exists()
            if row['visible_owned']:
                for name,surface in surfaces.items():
                    # Three desktop BitBlt calls per sample can serialize with
                    # DWM for ~50 ms and disturb the program being measured.
                    # The pacing probe is one tiny strip; large still images
                    # are requested outside measured phases and marked.
                    if name!='cursor' and not still:continue
                    pixels=surface.grab()
                    row[name]=hashlib.blake2b(pixels,digest_size=8).hexdigest()
                    if name=='cursor':
                        import numpy as np
                        target=np.array(config['bgr'],dtype='int16')
                        mask=(np.abs(pixels[:,:,:3].astype('int16')-target)<25).all(axis=2)
                        xs=np.flatnonzero(mask.sum(axis=0)>=max(1,pixels.shape[0]//2))
                        row['cursor_x']=int(np.median(xs)) if 1<=len(xs)<=8 else None
                    if still and name=='timeline':
                        Image.fromarray(pixels[:,:,[2,1,0]].copy()).save(folder/('screen-'+str(len(rows))+'.png'))
                row['large_capture']=still
            if still:(folder/'pixel-still').unlink(missing_ok=True)
            row['capture_ms']=(time.perf_counter()-begin)*1000
            rows.append(row)
            time.sleep(max(.001,1/120-(time.perf_counter()-begin)))
    except BaseException:error=traceback.format_exc()
    finally:
        for surface in surfaces.values():surface.close()
        (folder/'pixels.json').write_text(json.dumps({'rows':rows,'error':error}),'utf8')


if __name__=='__main__':main()
