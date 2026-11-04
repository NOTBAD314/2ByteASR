"""Record the original launcher's first timeline frames with isolated data."""
import ctypes
from ctypes import wintypes as W
import hashlib,json,os
from pathlib import Path
import shutil,subprocess,sys,time


def main():
    import psutil
    root=Path(sys.argv[1]).resolve();project=Path(sys.argv[2]).resolve();out=Path(sys.argv[3]).resolve()
    if out.exists() or not out.is_relative_to(Path(__file__).resolve().parents[1]/'tmp'):
        raise ValueError('Use a fresh source/tmp output')
    out.mkdir(parents=True);shutil.copy2(project,out/'project.2byteproj')
    original=hashlib.sha256(project.read_bytes()).hexdigest()
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_THEME='grape',
        TWOBYTEASR_STARTUP_SIZE='1600x980')
    env.pop('TWOBYTEASR_ACCEPTANCE_DIR',None)
    started=time.time();log=(out/'launcher.log').open('wb')
    launch=subprocess.Popen([str(root/'2ByteASR.exe')],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=0x08000000)
    u=ctypes.WinDLL('user32',use_last_error=True)
    u.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p];u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    u.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)]
    u.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
    u.IsWindowVisible.argtypes=[W.HWND];u.GetAncestor.argtypes=[W.HWND,W.UINT];u.GetAncestor.restype=W.HWND
    u.WindowFromPoint.argtypes=[W.POINT];u.WindowFromPoint.restype=W.HWND
    from twobyteasr.acceptance.visible_playback_audit import ScreenPixels
    from PIL import Image
    exe=(root/'dist/2ByteASR/2ByteASR.exe').resolve();hwnd=0;pid=0;rows=[];surface=None;prior=None
    CB=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    while time.time()-started<30:
        t=time.time()
        if not hwnd:
            pids=set()
            for p in psutil.process_iter(['pid','exe','create_time']):
                try:
                    if p.info['create_time']>=started-1 and p.info['exe'] and Path(p.info['exe']).resolve()==exe:pids.add(p.pid)
                except (psutil.Error,OSError):pass
            def visit(window,_):
                nonlocal hwnd,pid
                value=W.DWORD();u.GetWindowThreadProcessId(window,ctypes.byref(value))
                if value.value in pids and u.IsWindowVisible(window):hwnd=int(window);pid=value.value;return False
                return True
            u.EnumWindows(CB(visit),0)
        if hwnd:
            r=W.RECT();u.GetWindowRect(hwnd,ctypes.byref(r));w,h=r.right-r.left,r.bottom-r.top
            height=min(h,600);y=r.bottom-height
            owned=all(int(u.GetAncestor(u.WindowFromPoint(W.POINT(x,y+height//2)),2) or 0)==hwnd
                for x in (r.left+12,r.left+w//2,r.right-12))
            row=dict(at=time.time(),since_launch=time.time()-started,hwnd=hwnd,pid=pid,owned=owned,rect=[r.left,y,w,height])
            if owned and w>100 and h>100:
                key=(r.left,y,w,height)
                if key!=prior:
                    if surface:surface.close()
                    surface=ScreenPixels(*key);prior=key
                pixels=surface.grab()[:,:,:3][:,:,::-1].copy()
                file=f'{len(rows):04d}.png';Image.fromarray(pixels).save(out/file,compress_level=1);row['image']=file
            rows.append(row)
        time.sleep(max(.001,.1-(time.time()-t)))
    if surface:surface.close()
    code=None
    if hwnd:
        p=psutil.Process(pid)
        u.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM];u.PostMessageW(hwnd,0x10,0,0)
        try:code=p.wait(timeout=12)
        except psutil.TimeoutExpired:pass
    result=dict(entry=str(root/'2ByteASR.exe'),gui=str(exe),gui_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
        rows=rows,normal_close_exit=code,input_unchanged=hashlib.sha256(project.read_bytes()).hexdigest()==original,
        source='actual screen BitBlt, per-monitor-v2 physical coordinates; own window pixels only',
        limitations=['10Hz sampling, not physical input or every display refresh'])
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(dict(frames=sum('image' in r for r in rows),normal_close=code,input_unchanged=result['input_unchanged']))
    return 0 if code==0 and result['input_unchanged'] else 1


if __name__=='__main__':raise SystemExit(main())
