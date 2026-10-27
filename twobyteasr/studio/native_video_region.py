"""A region gate for the actual mpv child HWND; no Qt visibility or transport."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W


class Win32RegionApi:
    def __init__(self):
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.gdi=ctypes.WinDLL('gdi32',use_last_error=True)
        self.user.IsWindow.argtypes=[W.HWND];self.user.IsWindow.restype=W.BOOL
        self.user.FindWindowExW.argtypes=[W.HWND,W.HWND,W.LPCWSTR,W.LPCWSTR]
        self.user.FindWindowExW.restype=W.HWND
        self.user.GetParent.argtypes=[W.HWND];self.user.GetParent.restype=W.HWND
        self.user.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
        self.user.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int]
        self.user.GetWindowRgn.argtypes=[W.HWND,W.HRGN];self.user.GetWindowRgn.restype=ctypes.c_int
        self.user.SetWindowRgn.argtypes=[W.HWND,W.HRGN,W.BOOL];self.user.SetWindowRgn.restype=ctypes.c_int
        self.gdi.CreateRectRgn.argtypes=[ctypes.c_int]*4;self.gdi.CreateRectRgn.restype=W.HRGN
        self.gdi.DeleteObject.argtypes=[W.HGDIOBJ];self.gdi.DeleteObject.restype=W.BOOL

    def matches(self, host, child, pid):
        if not self.user.IsWindow(host) or not self.user.IsWindow(child):return False
        owner=W.DWORD();self.user.GetWindowThreadProcessId(child,ctypes.byref(owner))
        name=ctypes.create_unicode_buffer(32);self.user.GetClassNameW(child,name,len(name))
        return int(self.user.GetParent(child) or 0)==host and owner.value==pid and name.value=='mpv'

    def find_child(self, host, pid):
        if not self.user.IsWindow(host):return 0
        found=[];previous=0
        while True:
            child=int(self.user.FindWindowExW(host,previous,'mpv',None) or 0)
            if not child:break
            if self.matches(host,child,pid):found.append(child)
            previous=child
        if len(found)>1:raise RuntimeError('multiple mpv children for one controller/host')
        return found[0] if found else 0

    def empty(self):
        region=int(self.gdi.CreateRectRgn(0,0,0,0) or 0)
        if not region:raise OSError('CreateRectRgn failed')
        return region

    def delete(self, region):
        if region:self.gdi.DeleteObject(region)

    def capture(self, child):
        region=self.empty()
        ctypes.set_last_error(0)
        kind=self.user.GetWindowRgn(child,region)
        if kind==0:
            error=ctypes.get_last_error();self.delete(region)
            if error:raise OSError(error,'GetWindowRgn failed')
            return 0,0  # No explicit region, only after a validated live HWND.
        return region,kind

    def region_kind(self, child):
        region,kind=self.capture(child)
        self.delete(region)
        return kind

    def transfer(self, child, region):
        # Success transfers HRGN ownership to Windows; the caller must neither
        # read nor delete that handle afterwards. Failure leaves it with us.
        return bool(self.user.SetWindowRgn(child,region or None,True))


class NativeVideoRegionGate:
    """One live controller/process/host/child owns each saved region."""
    def __init__(self, api=None):
        self.api=api
        self.binding=None
        self.child=0
        self.saved=0
        self.saved_kind=0
        self.saved_captured=False
        self.applied=False
        self.empty_verified=False
        self.closed=False

    def reset(self):
        # Detachment never restores a dying or replaced foreign window.
        if self.saved and self.api is not None:self.api.delete(self.saved)
        self.binding=None;self.child=0;self.saved=0;self.saved_kind=0;self.saved_captured=False;self.applied=False
        self.empty_verified=False

    def close(self,*_):
        self.closed=True
        self.reset()

    def _live(self):
        if self.binding is None:return False
        controller,process,pid,host=self.binding
        try:
            return (getattr(controller,'_process',None) is process and process.poll() is None
                    and process.pid==pid and self.api.matches(host,self.child,pid))
        except (OSError,RuntimeError):return False

    def _result(self,status,*,retry=False,**extra):
        return dict(status=status,retry=retry,child_hwnd=self.child,
                    host_hwnd=self.binding[3] if self.binding else 0,
                    controller_pid=self.binding[2] if self.binding else None,
                    applied=self.applied,empty_verified=self.empty_verified,**extra)

    def owns_empty(self,controller,host):
        """A live verified clip, never a claim based on a previous result dict."""
        if (self.closed or not self.applied or not self.empty_verified or self.binding is None
                or self.binding[0] is not controller or self.binding[3]!=host
                or getattr(controller,'backend','mpv')!='mpv' or not self._live()):
            return False
        try:self.empty_verified=self.api.region_kind(self.child)==1
        except (OSError,RuntimeError):self.empty_verified=False
        return self.empty_verified

    def sync(self,controller,host,blocked):
        if self.closed:return self._result('retired')
        self.empty_verified=False
        if getattr(controller,'backend','mpv')!='mpv':
            self.reset();return self._result('unsupported_backend')
        process=getattr(controller,'_process',None)
        try:alive=process is not None and process.poll() is None
        except (OSError,RuntimeError):alive=False
        if not alive:
            self.reset();return self._result('no_live_process')
        if not host:
            self.reset();return self._result('waiting_host',retry=True)
        binding=(controller,process,int(process.pid),int(host))
        if self.binding is not None and any(a is not b for a,b in zip(self.binding[:2],binding[:2])):
            self.reset()
        elif self.binding is not None and self.binding[2:]!=binding[2:]:self.reset()
        try:
            if self.api is None:self.api=Win32RegionApi()
            if self.binding is not None and not self._live():self.reset()
            if self.binding is None:
                child=self.api.find_child(int(host),int(process.pid))
                if not child:return self._result('waiting_child',retry=True)
                self.binding=binding;self.child=child
            if not self._live():
                self.reset();return self._result('retired_child',retry=True)
            if blocked:
                if self.applied and self.api.region_kind(self.child)==1:
                    self.empty_verified=True
                    return self._result('blocked',region_kind=1)
                if not self.saved_captured:
                    self.saved,self.saved_kind=self.api.capture(self.child)
                    self.saved_captured=True
                region=self.api.empty()
                if not self._live():
                    self.api.delete(region);self.reset();return self._result('retired_child',retry=True)
                if not self.api.transfer(self.child,region):
                    self.api.delete(region)
                    raise OSError('SetWindowRgn(empty) failed')
                self.applied=True
                # Read a new copied region, never the transferred HRGN.
                kind=self.api.region_kind(self.child)
                if kind!=1:raise RuntimeError('mpv child did not retain the empty region')
                self.empty_verified=True
                return self._result('blocked',region_kind=kind)
            if self.applied:
                if not self._live():
                    self.reset();return self._result('retired_child',retry=True)
                if not self.api.transfer(self.child,self.saved):
                    raise OSError('SetWindowRgn(restore) failed')
                self.saved=0;self.saved_captured=False;self.applied=False
                kind=self.api.region_kind(self.child)
                return self._result('released',region_kind=kind,restored_kind=self.saved_kind)
            return self._result('bound')
        except (OSError,RuntimeError) as error:
            return self._result('error',error=str(error))
