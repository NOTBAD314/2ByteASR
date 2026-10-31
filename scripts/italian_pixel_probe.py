"""Independent physical desktop pixel observer; samples only verified owned video."""
from pathlib import Path
import ctypes
import hashlib
import json
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from twobyteasr.acceptance.visible_playback_audit import ScreenPixels
    folder = Path(sys.argv[1])
    cfg = json.loads((folder/'config.json').read_text(encoding='utf8'))
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    user.WindowFromPoint.restype = ctypes.c_void_p
    class Point(ctypes.Structure):
        _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]
    user.WindowFromPoint.argtypes = [Point]
    user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    surface = ScreenPixels(*cfg['rect'])
    rows = []
    error = ''
    started = time.perf_counter()
    multimedia = ctypes.WinDLL('winmm')
    timer_acquired = multimedia.timeBeginPeriod(1) == 0
    try:
        (folder/'ready').touch()
        while not (folder/'stop').exists() and time.perf_counter()-started < 40:
            t = time.perf_counter()
            x, y, w, h = cfg['rect']
            owners = []
            for fraction in (.05, .5, .95):
                hwnd = user.WindowFromPoint(Point(round(x+w*fraction), round(y+h/2)))
                pid = ctypes.c_ulong()
                user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                owners.append(pid.value)
            valid = all(pid in cfg['pids'] for pid in owners)
            row = {'at': t, 'owned': valid, 'pids': owners}
            if valid:
                row['hash'] = hashlib.blake2b(surface.grab(), digest_size=12).hexdigest()
            row['capture_ms'] = (time.perf_counter()-t)*1000
            rows.append(row)
            time.sleep(max(.001, 1/120-(time.perf_counter()-t)))
    except BaseException:
        error = traceback.format_exc()
    finally:
        surface.close()
        if timer_acquired:
            multimedia.timeEndPeriod(1)
        (folder/'pixels.json').write_text(json.dumps({'rows': rows, 'error': error}), encoding='utf8')


if __name__ == '__main__':
    main()
