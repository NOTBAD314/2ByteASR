"""Read the owned visible button's screen pixels without requesting a repaint."""
import ctypes
from ctypes import wintypes as W


class BitmapHeader(ctypes.Structure):
    _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),
        ('bit_count',W.WORD),('compression',W.DWORD),('image_bytes',W.DWORD),
        ('xppm',W.LONG),('yppm',W.LONG),('used',W.DWORD),('important',W.DWORD)]


class ButtonPixels:
    def __init__(self,button,window):
        from PySide6.QtCore import QPoint
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.gdi=ctypes.WinDLL('gdi32',use_last_error=True)
        self.user.GetDC.argtypes=[W.HWND];self.user.GetDC.restype=W.HDC
        self.user.ReleaseDC.argtypes=[W.HWND,W.HDC]
        self.user.ClientToScreen.argtypes=[W.HWND,ctypes.POINTER(W.POINT)]
        self.user.GetForegroundWindow.restype=W.HWND
        self.gdi.CreateCompatibleDC.argtypes=[W.HDC];self.gdi.CreateCompatibleDC.restype=W.HDC
        self.gdi.CreateCompatibleBitmap.argtypes=[W.HDC,ctypes.c_int,ctypes.c_int];self.gdi.CreateCompatibleBitmap.restype=W.HBITMAP
        self.gdi.SelectObject.argtypes=[W.HDC,W.HGDIOBJ];self.gdi.SelectObject.restype=W.HGDIOBJ
        self.gdi.BitBlt.argtypes=[W.HDC,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.HDC,ctypes.c_int,ctypes.c_int,W.DWORD]
        self.gdi.GetDIBits.argtypes=[W.HDC,W.HBITMAP,W.UINT,W.UINT,ctypes.c_void_p,ctypes.POINTER(BitmapHeader),W.UINT]
        self.gdi.DeleteObject.argtypes=[W.HGDIOBJ];self.gdi.DeleteDC.argtypes=[W.HDC]
        self.hwnd=int(window.winId());origin=W.POINT()
        if not self.user.ClientToScreen(self.hwnd,ctypes.byref(origin)):raise ctypes.WinError(ctypes.get_last_error())
        ratio=window.devicePixelRatioF();point=button.mapTo(window,QPoint())
        self.x=origin.x+round(point.x()*ratio);self.y=origin.y+round(point.y()*ratio)
        self.width=max(1,round(button.width()*ratio));self.height=max(1,round(button.height()*ratio))
        self.screen=self.user.GetDC(None);self.dc=self.gdi.CreateCompatibleDC(self.screen)
        self.bitmap=self.gdi.CreateCompatibleBitmap(self.screen,self.width,self.height)
        self.previous=self.gdi.SelectObject(self.dc,self.bitmap)
        self.header=BitmapHeader(ctypes.sizeof(BitmapHeader),self.width,-self.height,1,32,0,0,0,0,0,0)
        self.buffer=ctypes.create_string_buffer(self.width*self.height*4)
        self.closed=False

    def sample(self):
        if self.user.GetForegroundWindow()!=self.hwnd:return None
        if not self.gdi.BitBlt(self.dc,0,0,self.width,self.height,self.screen,self.x,self.y,0x40CC0020):
            raise ctypes.WinError(ctypes.get_last_error())
        self.gdi.SelectObject(self.dc,self.previous)
        try:
            if not self.gdi.GetDIBits(self.dc,self.bitmap,0,self.height,self.buffer,ctypes.byref(self.header),0):
                raise ctypes.WinError(ctypes.get_last_error())
            return self.buffer.raw
        finally:self.gdi.SelectObject(self.dc,self.bitmap)

    def close(self):
        if self.closed:return
        self.closed=True
        self.gdi.SelectObject(self.dc,self.previous);self.gdi.DeleteObject(self.bitmap)
        self.gdi.DeleteDC(self.dc);self.user.ReleaseDC(None,self.screen)
