"""Real active-desktop title mouse input, source/frozen, isolated profile.

Run with --launch-only for interactive Computer Use. Otherwise SendInput
presses, moves, pauses, reverses and releases over the actual product title.
No SC_MOVE or SetWindowPos substitutes for title drags. Do not move the mouse
while a run owns it; an unexpected foreground change aborts the input.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class INPUTUNION(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', wintypes.DWORD), ('data', INPUTUNION)]


class Driver:
    def __init__(self, output):
        self.output = output
        self.seq = 0
        self.inputs = []
        self.rows = []
        self.origin = time.perf_counter()
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        self.u.GetForegroundWindow.restype = wintypes.HWND
        self.u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.u.SendInput.restype = wintypes.UINT
        self.u.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.u.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
        self.u.WindowFromPoint.argtypes = [wintypes.POINT]
        self.u.WindowFromPoint.restype = wintypes.HWND
        self.u.GetAncestor.argtypes = [wintypes.HWND,wintypes.UINT]
        self.u.GetAncestor.restype = wintypes.HWND
        self.u.GetWindowThreadProcessId.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        self.u.GetClassNameW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        self.u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.u.GetAsyncKeyState.restype = ctypes.c_short
        self.state = self.status(120)
        self.seq = self.state['command_id']
        self.hwnd = self.state['hwnd']
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        self.kernel.OpenProcess.restype=wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        self.kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        self.process_handle=self.kernel.OpenProcess(0x1000|0x100000,False,self.state['pid'])
        if not self.process_handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def finish(self):
        self.command('finish')
        wait=self.kernel.WaitForSingleObject(self.process_handle,40000)
        code=wintypes.DWORD()
        ok=self.kernel.GetExitCodeProcess(self.process_handle,ctypes.byref(code))
        self.kernel.CloseHandle(self.process_handle)
        result=dict(pid=self.state['pid'],wait=wait,exit_code=code.value if ok else None)
        (self.output/'gui-process-exit.json').write_text(json.dumps(result,indent=2),'utf8')
        if wait!=0 or not ok or code.value!=0:
            raise RuntimeError('Owned GUI did not exit normally: '+str(result))

    def status(self, timeout=20, command_id=None):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            try:
                files=sorted(self.output.glob('mouse-status-*.json')) if command_id is None else []
                path=files[-1] if files else self.output/f'mouse-status-{command_id or 0:04d}.json'
                row = json.loads(path.read_text('utf8'))
                if command_id is None or row['command_id'] >= command_id:
                    if row.get('error'):
                        raise RuntimeError(row['error'])
                    return row
            except (FileNotFoundError, PermissionError, json.JSONDecodeError):
                pass
            time.sleep(.05)
        raise TimeoutError('No mouse audit status/command reply')

    def command(self, action, **fields):
        self.seq += 1
        path = self.output/f'mouse-command-{self.seq:04d}.tmp'
        if action not in {'snapshot','mark'} and 'tag' not in fields:
            fields['tag'] = 'setup-' + action
        path.write_text(json.dumps(dict(id=self.seq, action=action, **fields)), 'utf8')
        path.replace(self.output/f'mouse-command-{self.seq:04d}.json')
        if action != 'finish':
            self.state = self.status(command_id=self.seq)
        return self.state

    def sample(self):
        r = wintypes.RECT()
        self.u.GetWindowRect(self.hwnd, ctypes.byref(r))
        p = wintypes.POINT()
        self.u.GetCursorPos(ctypes.byref(p))
        return dict(t=round(time.perf_counter()-self.origin, 6),
                    rect=[r.left, r.top, r.right, r.bottom], cursor=[p.x, p.y])

    def native_children(self):
        parent=self.sample()['rect']
        rows=[]
        callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        def collect(hwnd,_):
            if self.u.IsWindowVisible(hwnd):
                r=wintypes.RECT()
                self.u.GetWindowRect(hwnd,ctypes.byref(r))
                pid=wintypes.DWORD()
                self.u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                class_name=ctypes.create_unicode_buffer(256)
                self.u.GetClassNameW(hwnd,class_name,len(class_name))
                rows.append(dict(hwnd=int(hwnd),rect=[r.left,r.top,r.right,r.bottom],
                    pid=pid.value,window_class=class_name.value,
                    relative=[r.left-parent[0],r.top-parent[1],r.right-parent[0],r.bottom-parent[1]]))
            return True
        self.u.EnumChildWindows.argtypes=[wintypes.HWND,callback_type,wintypes.LPARAM]
        self.u.EnumChildWindows(self.hwnd,callback_type(collect),0)
        return rows

    def wait(self, seconds):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            self.rows.append(self.sample())
            time.sleep(.008)

    def send(self, item, label, **details):
        if int(self.u.GetForegroundWindow() or 0) != self.hwnd:
            raise RuntimeError('Foreground changed; stop input instead of targeting another app')
        if self.u.SendInput(1, ctypes.byref(item), ctypes.sizeof(item)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())
        self.inputs.append(dict(t=round(time.perf_counter()-self.origin,6), action=label, **details))

    def mouse(self, x=None, y=None, flags=0x0001):
        item = INPUT(type=0)
        if x is not None:
            vx, vy = self.u.GetSystemMetrics(76), self.u.GetSystemMetrics(77)
            vw, vh = self.u.GetSystemMetrics(78), self.u.GetSystemMetrics(79)
            item.mi.dx = round((x-vx)*65535/max(1,vw-1))
            item.mi.dy = round((y-vy)*65535/max(1,vh-1))
            flags |= 0x8000 | 0x4000  # absolute on entire virtual desktop
        item.mi.dwFlags = flags
        self.send(item, 'mouse', flags=flags, target=[x,y])

    def wait_pointer(self,x,y):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            actual=self.sample()['cursor']
            if max(abs(actual[0]-x),abs(actual[1]-y))<=3:
                return
            self.wait(.016)
        raise RuntimeError(f'Pointer delivery not confirmed: wanted {(x,y)}, observed {actual}')

    def confirm_button(self,pressed):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            if bool(self.u.GetAsyncKeyState(1)&0x8000)==pressed:
                return
            self.wait(.016)
        raise RuntimeError('OS mouse-button delivery was not confirmed')

    def key(self, key):
        for flag in (0, 2):
            item = INPUT(type=1)
            item.ki.wVk, item.ki.dwFlags = key, flag
            self.send(item, 'key', key=key, flag=flag)
        self.wait(.08)

    def chord(self, modifier,key):
        for vk,flag in ((modifier,0),(key,0),(key,2),(modifier,2)):
            item=INPUT(type=1)
            item.ki.wVk,item.ki.dwFlags=vk,flag
            self.send(item,'key',key=vk,flag=flag)
        self.wait(.15)

    def click(self,x,y,count=1):
        self.mouse(x,y)
        self.wait(.08)
        for _ in range(count):
            self.mouse(flags=0x0002)
            self.wait(.05)
            self.mouse(flags=0x0004)
            self.wait(.06)

    def title_point(self):
        self.command('snapshot')
        bar=self.state['bar']
        return bar[0]+round(bar[2]*.4),bar[1]+round(bar[3]*.64)

    def capture(self, name):
        # Capture the actual on-screen HWND bounds (including mpv), not QWidget.grab.
        from PIL import ImageGrab
        r = self.sample()['rect']
        ImageGrab.grab(bbox=tuple(r), all_screens=True).save(self.output/(name+'.png'))

    def activate(self,x,y):
        self.u.SetForegroundWindow(self.hwnd)
        self.wait(.15)
        if int(self.u.GetForegroundWindow() or 0)==self.hwnd:
            return
        # Foreground-lock can reject API activation. Raise only our HWND,
        # without moving/resizing, then verify the hit window before a real
        # activation click. Never click through an unrelated foreground app.
        self.u.SetWindowPos(self.hwnd,None,0,0,0,0,0x0001|0x0002|0x0010|0x0040)
        self.wait(.15)
        def owned_point():
            hit=self.u.WindowFromPoint(wintypes.POINT(x,y))
            return int(self.u.GetAncestor(hit,2) or 0)==self.hwnd
        if not owned_point():
            raise RuntimeError('Owned title is occluded; activation click refused')
        item=INPUT(type=0)
        vx,vy=self.u.GetSystemMetrics(76),self.u.GetSystemMetrics(77)
        vw,vh=self.u.GetSystemMetrics(78),self.u.GetSystemMetrics(79)
        item.mi=MOUSEINPUT(round((x-vx)*65535/max(1,vw-1)),round((y-vy)*65535/max(1,vh-1)),0,0xC001,0,0)
        self.u.SendInput(1,ctypes.byref(item),ctypes.sizeof(item))
        self.wait(.05)
        if not owned_point():
            raise RuntimeError('Owned title changed before activation click')
        try:
            item=INPUT(type=0)
            item.mi.dwFlags=2
            self.u.SendInput(1,ctypes.byref(item),ctypes.sizeof(item))
            self.wait(.05)
        finally:
            item.mi.dwFlags=4
            self.u.SendInput(1,ctypes.byref(item),ctypes.sizeof(item))
        self.inputs.append(dict(t=round(time.perf_counter()-self.origin,6),action='verified-title-activation',target=[x,y]))
        self.wait(.6)  # separate this activation from the tested double-click
        if int(self.u.GetForegroundWindow() or 0)!=self.hwnd:
            raise RuntimeError('Activation did not reach owned window')

    def drag(self, tag, ratio=.4, dx=0, dy=320, reverse=True, escape=False):
        self.command('snapshot', tag=tag)
        bar = self.state['bar']
        if not self.state['bar_visible']:
            raise RuntimeError('Product title bar is hidden')
        reserve = 5 if self.state.get('bar_kind') == 'studioFilename' else 160
        x = bar[0]+round(max(5,min(bar[2]-reserve, bar[2]*ratio)))
        y = bar[1]+round(bar[3]*.64)
        self.activate(x,y)
        self.mouse(x,y)
        self.wait_pointer(x,y)
        before = self.sample()
        caption_before=self.state.get('caption_presses',0)
        children_before=self.native_children()
        self.capture(tag+'-before')
        begin = len(self.rows)
        input_begin = len(self.inputs)
        self.mouse(flags=0x0002)
        self.confirm_button(True)
        if (self.state.get('state_kind')!='external_native_only' and not self.state.get('fullscreen')
                and not self.state.get('native_caption_available')):
            deadline=time.monotonic()+2
            while True:
                self.command('snapshot')
                if self.state.get('title_drag') and self.state.get('owner')!='native-pending':break
                if time.monotonic()>=deadline:raise RuntimeError('Product title gesture did not acquire movement ownership')
        for i in range(1,25):
            self.mouse(x+round(dx*i/24), y+round(dy*i/24))
            self.wait(.025)
        self.wait(.4)
        forward_end = len(self.rows)
        if reverse:
            for i in range(1,9):
                self.mouse(x+dx, y+dy-round(64*i/8))
                self.wait(.03)
        self.capture(tag+'-held')
        children_held=self.native_children()
        if escape:
            self.key(0x1B)
        self.mouse(flags=0x0004)
        release_injected=self.sample()
        self.confirm_button(False)
        if self.state.get('state_kind')!='external_native_only':
            deadline=time.monotonic()+2
            while True:
                self.command('snapshot')
                if not self.state.get('in_move') and not self.state.get('title_drag'):break
                if time.monotonic()>=deadline:raise RuntimeError('Product release was not confirmed')
        release = self.sample()
        release_idx = len(self.rows)
        self.wait(1.5)
        after = self.sample()
        children_after=self.native_children()
        self.capture(tag+'-after')
        self.command('snapshot')
        during = self.rows[begin:forward_end]
        # Unexpected reverse motion when the cursor did not move up.
        backs = [dict(a=a,b=b) for a,b in zip(during,during[1:])
                 if dy and (b['rect'][1]-a['rect'][1])*(1 if dy>0 else -1)<-3]
        late = [r for r in self.rows[release_idx:] if max(abs(a-b) for a,b in zip(r['rect'],release['rect']))>3]
        return dict(tag=tag,before=before,release=release,after=after,anomalous_reverse=len(backs),
                    first_backs=backs[:5],post_release_changed=len(late),cancel=escape,
                    release_injected=release_injected,release_confirmed=True,
                    requested_delta=[dx,dy-(64 if reverse else 0)],
                    caption_presses=self.state.get('caption_presses',0)-caption_before,
                    input_range=[input_begin,len(self.inputs)],sample_range=[begin,len(self.rows)],
                    state_after=self.state,children_before=children_before,
                    children_held=children_held,children_after=children_after)


def run_suite(driver,suite):
    scenarios=[]
    checks=[]
    driver.scenarios,driver.checks=scenarios,checks
    def check(name,condition,**evidence):
        checks.append(dict(name=name,passed=bool(condition),**evidence))
    def run_drag(tag,**options):
        row=driver.drag(tag,**options)
        scenarios.append(row)
        if tag!='true-fullscreen' and row['state_after'].get('native_caption_available'):
            check(tag+'-real-native-title-press',row['caption_presses']>=1,presses=row['caption_presses'])
        # Escape is a separate cancellation outcome, never a snap-back count.
        if not options.get('escape') and not tag.startswith('snap-'):
            check(tag+'-no-reverse',row['anomalous_reverse']==0)
            check(tag+'-release-stable',row['post_release_changed']==0)
            if not tag.startswith(('max-','cross-')) and tag!='true-fullscreen':
                actual=[row['after']['rect'][i]-row['before']['rect'][i] for i in (0,1)]
                check(tag+'-follows-terminal-cursor',max(abs(a-b) for a,b in zip(actual,row['requested_delta']))<=3,
                      actual_delta=actual,requested_delta=row['requested_delta'])
        return row
    if suite in {'basic','full'}:
        for tall in (False,True):
            driver.command('setup',tall=tall)
            driver.wait(.7)
            driver.command('snapshot')
            n=driver.state['native']
            dy=350 if tall else n['work'][3]-n['rect'][3]+120
            row=run_drag('home-tall' if tall else 'home-normal',dy=dy)
            check(row['tag']+'-bottom-beyond-work',row['after']['rect'][3]>row['state_after']['native']['work'][3])
        for ratio in (.15,.5,.8):
            driver.command('setup')
            driver.wait(.5)
            driver.command('maximize')
            driver.wait(.8)
            row=run_drag(f'max-{ratio}',ratio=ratio,dy=330,dx=50)
            check(row['tag']+'-normal-after',not row['state_after']['maximized'])
        driver.command('setup')
        driver.wait(.6)
        driver.command('snapshot')
        bar=driver.state['bar']
        dy=driver.state['native']['work'][3]-70-(bar[1]+round(bar[3]*.64))
        row=run_drag('pointer-near-taskbar',dy=dy,reverse=False)
        check('pointer-near-taskbar-kept',row['after']['rect'][1]>row['state_after']['native']['work'][3]-200)
    if suite in {'fullscreen','controls','full'}:
        driver.command('fullscreen')
        driver.wait(.8)
        row=run_drag('true-fullscreen',dy=330,reverse=False)
        check('fullscreen-remains-fixed',row['before']['rect']==row['after']['rect'] and row['state_after']['fullscreen'])
        driver.command('snapshot',tag='setup-fullscreen-exit')
        r=driver.state['buttons']['maximize']
        driver.click(r[0]+r[2]//2,r[1]+r[3]//2)
        driver.wait(.7)
        driver.command('snapshot')
        check('fullscreen-explicit-exit-to-maximized',not driver.state['fullscreen'] and driver.state['maximized'])
    if suite in {'controls','full'}:
        driver.command('setup')
        driver.wait(.8)
        x,y=driver.title_point()
        driver.click(x,y,count=2)
        driver.wait(.7)
        driver.command('snapshot')
        check('double-click-maximizes',driver.state['maximized'])
        x,y=driver.title_point()
        driver.click(x,y)
        driver.wait(.5)
        driver.command('snapshot')
        check('single-click-keeps-maximized',driver.state['maximized'])
        x,y=driver.title_point()
        driver.click(x,y,count=2)
        driver.wait(.7)
        driver.command('snapshot')
        check('double-click-restores',not driver.state['maximized'])
        driver.command('setup')
        driver.wait(.5)
        row=run_drag('escape-normal',dy=330,reverse=False,escape=True)
        check('escape-restores-start',max(abs(a-b) for a,b in zip(row['before']['rect'],row['after']['rect']))<=3)
        driver.command('maximize')
        driver.wait(.6)
        driver.command('snapshot')
        r=driver.state['buttons']['minimize']
        driver.click(r[0]+r[2]//2,r[1]+r[3]//2)
        driver.wait(.5)
        driver.command('snapshot')
        check('minimize-button',driver.state['minimized'])
        driver.command('restore')
        driver.wait(1)
        driver.command('snapshot')
        check('restore-keeps-maximized',driver.state['maximized'] and not driver.state['minimized'])
        driver.command('setup')
        driver.wait(.6)
        before=driver.sample()['rect']
        driver.chord(0x12,0x20)  # Alt+Space, then the actual system-menu Move
        driver.key(ord('M'))
        driver.key(0x28)
        for _ in range(8): driver.key(0x28)
        driver.key(0x0D)
        driver.wait(.8)
        after=driver.sample()['rect']
        check('system-menu-keyboard-move',after[1]>before[1],before=before,after=after)
        # Actual native nonclient bottom-right input, separate from title.
        driver.command('setup')
        driver.wait(.6)
        before=driver.sample()['rect']
        x,y=before[2]-3,before[3]-3
        driver.mouse(x,y)
        driver.mouse(flags=2)
        for i in range(1,16):
            driver.mouse(x+i*8,y+i*6)
            driver.wait(.03)
        driver.mouse(flags=4)
        driver.wait(.8)
        after=driver.sample()['rect']
        check('edge-resize',after[2]-before[2]>60 and after[3]-before[3]>40,before=before,after=after)
        driver.command('setup')
        driver.wait(.6)
        driver.command('snapshot')
        bar=driver.state['bar']
        row=run_drag('snap-top',dy=-(bar[1]+round(bar[3]*.64)),reverse=False)
        check('snap-top-maximizes',row['state_after']['maximized'])
    if suite in {'studio','full'}:
        driver.command('studio')
        driver.wait(8)
        for playing in (False,True):
            driver.command('play' if playing else 'pause')
            driver.command('setup',tall=True)
            driver.wait(.7)
            row=run_drag('studio-playing' if playing else 'studio-paused',dy=350)
            check(row['tag']+'-video-present',row['state_after'].get('video',{}).get('visible'))
            original={c['hwnd']:c['relative'] for c in row['children_before']}
            aligned=all(c['hwnd'] in original and max(abs(a-b) for a,b in zip(c['relative'],original[c['hwnd']]))<=3
                        for c in row['children_held']+row['children_after'])
            check(row['tag']+'-native-children-follow',aligned and bool(original))
            check(row['tag']+'-mpv-child-observed',any('mpv' in c.get('window_class','').lower()
                for c in row['children_before']))
    if suite in {'screens','full'}:
        for screen in (1,2):
            driver.command('setup',screen=screen,tall=True)
            driver.wait(1)
            row=run_drag('screen-'+str(screen),dy=250,ratio=.3)
            driver.command('maximize')
            driver.wait(.7)
            driver.command('snapshot')
            name=driver.state['screen']
            driver.command('minimize')
            driver.wait(.3)
            driver.command('restore')
            driver.wait(1)
            driver.command('snapshot')
            check('min-restore-screen-'+str(screen),driver.state['screen']==name and driver.state['maximized'])
        for tag,target in (('cross-left-125',(-1250,300)),('cross-right-100',(4400,500))):
            driver.command('setup',screen=0)
            driver.wait(.7)
            driver.command('snapshot')
            bar=driver.state['bar']
            reserve=5 if driver.state.get('bar_kind')=='studioFilename' else 160
            x=bar[0]+round(max(5,min(bar[2]-reserve,bar[2]*.4)))
            y=bar[1]+round(bar[3]*.64)
            row=run_drag(tag,dx=target[0]-x,dy=target[1]-y,reverse=False)
            expected=1.25 if '125' in tag else 1.0
            check(tag+'-target-dpi',abs(row['state_after']['dpr']-expected)<.01)
    return scenarios,checks


def observed_state_checks(output,scenarios):
    """Use product events to catch fast flips which a polling sampler can miss."""
    events=json.loads((output/'mouse-events.json').read_text('utf8'))
    checks=[]
    for scenario in scenarios:
        tag=scenario['tag']
        if tag.startswith('snap-'):
            continue  # native Snap intentionally changes state on release
        rows=[r for r in events if r['tag']==tag]
        states=[]
        for r in rows:
            state=r['qt_state'] & 7
            if not states or states[-1]!=state:states.append(state)
        expected=[2,0] if tag.startswith('max-') else [4] if tag=='true-fullscreen' else [0]
        checks.append(dict(name=tag+'-state-sequence',passed=states==expected,observed=states,expected=expected))
        writers=[r for r in rows if r['event'] in ('call.move','call.setGeometry') and r.get('owner') in {'native','native-pending'}]
        checks.append(dict(name=tag+'-native-exclusive',passed=not writers,application_writes=len(writers)))
        if tag.startswith('max-'):
            restores=[r for r in rows if r['event']=='call.showNormal'
                and any(c['function']=='advance' for c in r.get('callers',[]))]
            native=bool(scenario['state_after'].get('native_caption_available'))
            checks.append(dict(name=tag+'-one-restore',passed=states==[2,0] and len(restores)==(0 if native else 1),
                               manual_restores=len(restores),native_caption=native))
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--launch-only',action='store_true')
    parser.add_argument('--attach',action='store_true',help='Continue a launched audit after explicit activation')
    parser.add_argument('--suite',choices=['basic','full','fullscreen','controls','studio','screens'],default='basic')
    args=parser.parse_args()
    out=args.output.resolve()
    if (out.exists() and not args.attach) or not out.is_relative_to(ROOT/'tmp'):
        parser.error('Choose a fresh directory under repository tmp')
    if args.attach:
        driver=Driver(out)
        scenarios=[]
        checks=[]
        try:
            scenarios,checks=run_suite(driver,args.suite)
        finally:
            item=INPUT(type=0)
            item.mi.dwFlags=4
            driver.u.SendInput(1,ctypes.byref(item),ctypes.sizeof(item))
            (out/'input.json').write_text(json.dumps(dict(inputs=driver.inputs,trajectory=driver.rows,
                scenarios=getattr(driver,'scenarios',scenarios),checks=getattr(driver,'checks',checks)),ensure_ascii=False),'utf8')
            driver.finish()
        checks.extend(observed_state_checks(out,scenarios))
        (out/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps(dict(output=str(out),checks=checks),ensure_ascii=False),flush=True)
        return 0 if all(c['passed'] for c in checks) else 1
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project
    media=out/'mouse.mp4'
    ffmpeg=ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    if not ffmpeg.exists():
        ffmpeg=ROOT/'dist/2ByteASR/tools/ffmpeg/bin/ffmpeg.exe'
    subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=size=960x540:rate=30:duration=60',
                    '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(media)],
                    check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    save_project(SubtitleProject(media=StudioMedia(path=str(media),duration_ms=60000,width=960,height=540),
                 cues=[StudioCue(f'c{i}',i*3000,i*3000+2500,f'窗口拖动验证 {i}') for i in range(20)]),out/'project.2byteproj')
    env=os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE'):
        env.pop(key,None)
    env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO='window-title-mouse',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TWOBYTEASR_WINDOW_TRACE_SECONDS='180')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    (out/'launch.json').write_text(json.dumps(dict(command=command,exe_sha256=hashlib.sha256(args.exe.read_bytes()).hexdigest() if args.exe else None),indent=2),'utf8')
    log=(out/'process.log').open('wb')
    process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    driver=Driver(out)
    driver.command('setup')
    driver.wait(1)
    driver.command('snapshot')
    if args.launch_only:
        print(json.dumps(dict(pid=process.pid,output=str(out),hwnd=driver.hwnd)),flush=True)
        return 0
    scenarios=[]
    checks=[]
    try:
        scenarios,checks=run_suite(driver,args.suite)
    finally:
        # Never leave the global left button held on an interrupted test.
        item=INPUT(type=0)
        item.mi.dwFlags=0x0004
        driver.u.SendInput(1,ctypes.byref(item),ctypes.sizeof(item))
        (out/'input.json').write_text(json.dumps(dict(inputs=driver.inputs,trajectory=driver.rows,
            scenarios=getattr(driver,'scenarios',scenarios),checks=getattr(driver,'checks',checks)),ensure_ascii=False),'utf8')
        driver.finish()
    process.wait(timeout=40)
    checks.extend(observed_state_checks(out,scenarios))
    (out/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),'utf8')
    summary=dict(exit=process.returncode,output=str(out),checks=checks,scenarios=[dict(tag=r['tag'],reverse=r['anomalous_reverse'],
        late=r['post_release_changed'],after=r['after']['rect']) for r in scenarios])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return process.returncode or (0 if all(c['passed'] for c in checks) else 1)


if __name__=='__main__':
    raise SystemExit(main())
