"""Read-only Win32/DXGI evidence for native loading surfaces (opt-in audit)."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
from functools import wraps
import os
import time
import uuid


def existing_widget_handle(widget):
    """Observation must never promote/recreate a native widget, even at exit."""
    try:
        return int(widget.internalWinId() or 0)
    except RuntimeError:
        return 0  # The Python wrapper can outlive its C++ QWidget.


def _physical_pixels(function):
    @wraps(function)
    def read(*args,**kwargs):
        user=ctypes.WinDLL('user32',use_last_error=True)
        change=user.SetThreadDpiAwarenessContext
        change.argtypes=[W.HANDLE];change.restype=W.HANDLE
        previous=change(W.HANDLE(-4))  # PER_MONITOR_AWARE_V2, only for these reads.
        try:return function(*args,**kwargs)
        finally:
            if previous:change(previous)
    return read


class GUID(ctypes.Structure):
    _fields_=[('a',W.DWORD),('b',W.WORD),('c',W.WORD),('d',ctypes.c_ubyte*8)]


class OutputDescription(ctypes.Structure):
    _fields_=[('name',W.WCHAR*32),('rect',W.RECT),('attached',W.BOOL),
              ('rotation',W.UINT),('monitor',W.HMONITOR)]


def _com(pointer,index,restype,*argtypes):
    table=ctypes.cast(pointer,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype,ctypes.c_void_p,*argtypes)(table[index])


@_physical_pixels
def dxgi_outputs():
    """Use the same adapter/output numbering as FFmpeg's explicit D3D11 device."""
    library=ctypes.WinDLL('dxgi',use_last_error=True)
    library.CreateDXGIFactory1.argtypes=[ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)]
    library.CreateDXGIFactory1.restype=ctypes.c_long
    iid=GUID.from_buffer_copy(uuid.UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
    factory=ctypes.c_void_p()
    hr=library.CreateDXGIFactory1(ctypes.byref(iid),ctypes.byref(factory))
    if hr<0:raise OSError(f'CreateDXGIFactory1 0x{hr&0xffffffff:08x}')
    rows=[]
    try:
        for adapter_index in range(16):
            adapter=ctypes.c_void_p()
            hr=_com(factory,12,ctypes.c_long,W.UINT,ctypes.POINTER(ctypes.c_void_p))(factory,adapter_index,ctypes.byref(adapter))
            if hr&0xffffffff==0x887a0002:break
            if hr<0:raise OSError(f'EnumAdapters1 0x{hr&0xffffffff:08x}')
            try:
                for output_index in range(16):
                    output=ctypes.c_void_p()
                    hr=_com(adapter,7,ctypes.c_long,W.UINT,ctypes.POINTER(ctypes.c_void_p))(adapter,output_index,ctypes.byref(output))
                    if hr&0xffffffff==0x887a0002:break
                    if hr<0:raise OSError(f'EnumOutputs 0x{hr&0xffffffff:08x}')
                    try:
                        desc=OutputDescription()
                        hr=_com(output,7,ctypes.c_long,ctypes.POINTER(OutputDescription))(output,ctypes.byref(desc))
                        if hr<0:raise OSError(f'GetDesc 0x{hr&0xffffffff:08x}')
                        rows.append({'adapter_index':adapter_index,'output_index':output_index,
                            'name':desc.name,'rect':[desc.rect.left,desc.rect.top,desc.rect.right,desc.rect.bottom],
                            'attached':bool(desc.attached),'rotation':desc.rotation,'monitor':int(desc.monitor or 0)})
                    finally:_com(output,2,W.ULONG)(output)
            finally:_com(adapter,2,W.ULONG)(adapter)
    finally:_com(factory,2,W.ULONG)(factory)
    return rows


def select_output(outputs, bounds):
    left,top,right,bottom=bounds
    matches=[row for row in outputs if row['attached'] and row['rect'][0]<=left
             and row['rect'][1]<=top and right<=row['rect'][2] and bottom<=row['rect'][3]]
    if len(matches)!=1:raise ValueError('the audited window must fit exactly one attached DXGI output')
    output=matches[0]
    if output['rotation']!=1:raise ValueError('rotated desktop capture needs explicit coordinate calibration')
    return {**output,'crop':[left-output['rect'][0],top-output['rect'][1],right-left,bottom-top]}


class NativeLoadingProbe:
    def __init__(self):
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.gdi=ctypes.WinDLL('gdi32',use_last_error=True)
        self.dwm=ctypes.WinDLL('dwmapi',use_last_error=True)
        u,g=self.user,self.gdi
        u.GetParent.argtypes=[W.HWND];u.GetParent.restype=W.HWND
        u.GetWindow.argtypes=[W.HWND,W.UINT];u.GetWindow.restype=W.HWND
        u.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)];u.GetWindowRect.restype=W.BOOL
        u.GetClientRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)]
        u.ClientToScreen.argtypes=[W.HWND,ctypes.POINTER(W.POINT)]
        u.IsWindowVisible.argtypes=[W.HWND];u.IsWindowVisible.restype=W.BOOL
        u.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
        u.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int]
        u.GetWindowRgn.argtypes=[W.HWND,W.HRGN];u.GetWindowRgn.restype=ctypes.c_int
        u.GetForegroundWindow.restype=W.HWND
        u.WindowFromPoint.argtypes=[W.POINT];u.WindowFromPoint.restype=W.HWND
        u.GetAncestor.argtypes=[W.HWND,W.UINT];u.GetAncestor.restype=W.HWND
        self.long=getattr(u,'GetWindowLongPtrW',u.GetWindowLongW)
        self.long.argtypes=[W.HWND,ctypes.c_int];self.long.restype=ctypes.c_ssize_t
        g.CreateRectRgn.argtypes=[ctypes.c_int]*4;g.CreateRectRgn.restype=W.HRGN
        g.GetRgnBox.argtypes=[W.HRGN,ctypes.POINTER(W.RECT)];g.GetRgnBox.restype=ctypes.c_int
        g.GetRegionData.argtypes=[W.HRGN,W.DWORD,ctypes.c_void_p];g.GetRegionData.restype=W.DWORD
        g.RectInRegion.argtypes=[W.HRGN,ctypes.POINTER(W.RECT)];g.RectInRegion.restype=W.BOOL
        g.DeleteObject.argtypes=[W.HGDIOBJ];g.DeleteObject.restype=W.BOOL
        self.dwm.DwmGetWindowAttribute.argtypes=[W.HWND,W.DWORD,ctypes.c_void_p,W.DWORD]
        self.dwm.DwmGetWindowAttribute.restype=ctypes.c_long

    @_physical_pixels
    def window(self, hwnd):
        u,g=self.user,self.gdi;hwnd=int(hwnd)
        rect=W.RECT();u.GetWindowRect(hwnd,ctypes.byref(rect))
        client=W.RECT();u.GetClientRect(hwnd,ctypes.byref(client))
        origin=W.POINT();u.ClientToScreen(hwnd,ctypes.byref(origin))
        local=W.RECT(origin.x-rect.left,origin.y-rect.top,
                     origin.x-rect.left+client.right,origin.y-rect.top+client.bottom)
        pid=W.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        name=ctypes.create_unicode_buffer(128);u.GetClassNameW(hwnd,name,len(name))
        style=int(self.long(hwnd,-16))&0xffffffff
        row={'hwnd':hwnd,'parent':int(u.GetParent(hwnd) or 0),'owner':int(u.GetWindow(hwnd,4) or 0),
            'previous_z':int(u.GetWindow(hwnd,3) or 0),'next_z':int(u.GetWindow(hwnd,2) or 0),
            'pid':pid.value,'class':name.value,'visible':bool(u.IsWindowVisible(hwnd)),
            'style':hex(style),'extended_style':hex(int(self.long(hwnd,-20))&0xffffffff),
            'child':bool(style&0x40000000),'clips_children':bool(style&0x02000000),
            'clips_siblings':bool(style&0x04000000),
            'rect':[rect.left,rect.top,rect.right,rect.bottom],
            'client_screen':[origin.x,origin.y,origin.x+client.right,origin.y+client.bottom]}
        bounds=W.RECT()
        if self.dwm.DwmGetWindowAttribute(hwnd,9,ctypes.byref(bounds),ctypes.sizeof(bounds))==0:
            row['dwm_frame']=[bounds.left,bounds.top,bounds.right,bounds.bottom]
        region=g.CreateRectRgn(0,0,0,0)
        if region:
            try:
                ctypes.set_last_error(0)
                kind=u.GetWindowRgn(hwnd,region)
                region_data={'result':kind,'last_error':ctypes.get_last_error(),
                             'meaning':{0:'no explicit region or API error',1:'empty',2:'rectangle',3:'complex'}.get(kind,'unknown')}
                if kind:
                    box=W.RECT();g.GetRgnBox(region,ctypes.byref(box))
                    region_data.update(bounds=[box.left,box.top,box.right,box.bottom],
                                       intersects_client=bool(g.RectInRegion(region,ctypes.byref(local))))
                    size=g.GetRegionData(region,0,None)
                    if 32<=size<=65536:
                        data=ctypes.create_string_buffer(size);g.GetRegionData(region,size,data)
                        import struct
                        header=struct.unpack_from('<4I4i',data.raw)
                        region_data['rectangle_count']=header[2]
                        region_data['rectangles']=[list(struct.unpack_from('<4i',data.raw,32+index*16))
                                                  for index in range(min(header[2],128))]
                row['native_region']=region_data
            finally:g.DeleteObject(region)
        return row

    @_physical_pixels
    def coverage(self, root, bounds=None):
        root=int(root);rect=W.RECT();self.user.GetWindowRect(root,ctypes.byref(rect))
        if bounds is not None:rect=W.RECT(*map(int,bounds))
        points=[]
        for fy in (.1,.5,.9):
            for fx in (.1,.5,.9):
                point=W.POINT(round(rect.left+(rect.right-rect.left)*fx),
                              round(rect.top+(rect.bottom-rect.top)*fy))
                hit=int(self.user.WindowFromPoint(point) or 0)
                pid=W.DWORD();self.user.GetWindowThreadProcessId(hit,ctypes.byref(pid))
                ancestor=int(self.user.GetAncestor(hit,2) or 0)
                points.append({'point':[point.x,point.y],'hwnd':hit,'root':ancestor,'pid':pid.value,
                               'owned':ancestor==root or pid.value==os.getpid()})
        foreground=int(self.user.GetForegroundWindow() or 0)
        pid=W.DWORD();self.user.GetWindowThreadProcessId(foreground,ctypes.byref(pid))
        return {'foreground':foreground,'foreground_pid':pid.value,
                'foreground_owned':pid.value==os.getpid(),
                'all_points_owned':all(point['owned'] for point in points),
                'points':points}

    def snapshot(self, window, session, label):
        from PySide6.QtCore import Qt
        from ..studio.studio_video_canvas import MpvCanvas
        root=existing_widget_handle(window)
        if not root or not self.user.IsWindow(W.HWND(root)):
            return {'at':time.perf_counter(),'label':label,'root':root,'target_retired':True,
                    'desktop_coverage':{'foreground_owned':False,'all_points_owned':False,
                                        'reason':'target native window is retired'},
                    'native_windows':[],'widgets':[]}
        found={root};callback=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        def child(hwnd,_):found.add(int(hwnd));return True
        self.user.EnumChildWindows(W.HWND(root),callback(child),0)
        canvases=window.findChildren(MpvCanvas)
        pids={os.getpid()}
        for canvas in canvases:
            process=getattr(getattr(canvas,'controller',None),'_process',None)
            if process is not None:pids.add(process.pid)
        def owned(hwnd,_):
            pid=W.DWORD();self.user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value in pids:
                found.add(int(hwnd));self.user.EnumChildWindows(hwnd,callback(child),0)
            return True
        self.user.EnumWindows(callback(owned),0)
        rows=[self.window(hwnd) for hwnd in sorted(found)]
        widgets=[]
        for name,widget in ([('loading',session.view)] if session else []) + [('canvas',c) for c in canvases]:
            created=widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created)
            native=widget.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
            hwnd=existing_widget_handle(widget) if created and native else 0
            parent=widget.parentWidget()
            widgets.append({'role':name,'object_id':id(widget),'object_name':widget.objectName(),
                'visible':widget.isVisible(),'hidden':widget.isHidden(),'created':created,'native':native,
                'actual_qt_hwnd':hwnd,'reported_embed_hwnd':getattr(widget,'_embed_hwnd',None),
                'parent_object':id(parent) if parent else None,'mask':list(widget.mask().boundingRect().getRect()),
                'presentation_reasons':sorted(getattr(widget,'_presentation_block_reasons',())),
                'controller_pid':getattr(getattr(getattr(widget,'controller',None),'_process',None),'pid',None)})
        return {'at':time.perf_counter(),'label':label,'root':root,
                'foreground':int(self.user.GetForegroundWindow() or 0),
                'desktop_coverage':self.coverage(root),
                'generation':session.generation if session else None,'loading_state':session.state if session else None,
                'native_windows':rows,'widgets':widgets}
