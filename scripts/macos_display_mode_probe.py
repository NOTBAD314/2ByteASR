"""Set only a disposable CI display, never alter application pixels or code."""
from pathlib import Path
import ctypes as C
import json,sys,time
out=Path(sys.argv[1]).resolve()
assert 'tmp' in out.parts and not out.exists()
out.mkdir(parents=True)
cg=C.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
cf=C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
cg.CGMainDisplayID.restype=C.c_uint32
cg.CGDisplayCopyAllDisplayModes.argtypes=[C.c_uint32,C.c_void_p];cg.CGDisplayCopyAllDisplayModes.restype=C.c_void_p
cg.CGDisplayCopyDisplayMode.argtypes=[C.c_uint32];cg.CGDisplayCopyDisplayMode.restype=C.c_void_p
for name in ('CGDisplayModeGetWidth','CGDisplayModeGetHeight','CGDisplayModeGetPixelWidth','CGDisplayModeGetPixelHeight'):
    getattr(cg,name).argtypes=[C.c_void_p];getattr(cg,name).restype=C.c_size_t
cg.CGDisplaySetDisplayMode.argtypes=[C.c_uint32,C.c_void_p,C.c_void_p];cg.CGDisplaySetDisplayMode.restype=C.c_int32
cf.CFArrayGetCount.argtypes=[C.c_void_p];cf.CFArrayGetCount.restype=C.c_long
cf.CFArrayGetValueAtIndex.argtypes=[C.c_void_p,C.c_long];cf.CFArrayGetValueAtIndex.restype=C.c_void_p
display=cg.CGMainDisplayID()
def info(mode):return dict(width=cg.CGDisplayModeGetWidth(mode),height=cg.CGDisplayModeGetHeight(mode),pixel_width=cg.CGDisplayModeGetPixelWidth(mode),pixel_height=cg.CGDisplayModeGetPixelHeight(mode))
old=info(cg.CGDisplayCopyDisplayMode(display)); modes=cg.CGDisplayCopyAllDisplayModes(display,None)
values=[(cf.CFArrayGetValueAtIndex(modes,i),info(cf.CFArrayGetValueAtIndex(modes,i))) for i in range(cf.CFArrayGetCount(modes))]
result=dict(display=display,before=old,modes=[row for _,row in values],passed=False)
try:
    allowed=[(pointer,row) for pointer,row in values if row['width']>=1600 and row['height']>=1000]
    assert allowed,'Native display exposes no large desktop mode'
    pointer,selected=min(allowed,key=lambda item:(item[1]['width']!=1920 or item[1]['height']!=1080,item[1]['width']*item[1]['height']))
    result['selected']=selected;result['set_exit']=cg.CGDisplaySetDisplayMode(display,pointer,None)
    assert result['set_exit']==0,result
    time.sleep(2)
    result['after']=info(cg.CGDisplayCopyDisplayMode(display))
    assert result['after']['width']>=1600 and result['after']['height']>=1000
    result['passed']=True
finally:
    (out/'display-mode.json').write_text(json.dumps(result,indent=2),'utf8')
    print(json.dumps(result),flush=True)
