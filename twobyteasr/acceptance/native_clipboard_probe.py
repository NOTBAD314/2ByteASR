"""Independent Windows CF_UNICODETEXT reader for clipboard acceptance."""
def main():
    import ctypes
    from ctypes import wintypes as W
    import json
    from pathlib import Path
    import sys
    import time
    user, kernel = ctypes.windll.user32, ctypes.windll.kernel32
    user.OpenClipboard.argtypes = [W.HWND]
    user.GetClipboardData.argtypes = [W.UINT]
    user.GetClipboardData.restype = W.HANDLE
    kernel.GlobalLock.argtypes = [W.HANDLE]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [W.HANDLE]
    value = None
    for _ in range(30):
        if user.OpenClipboard(None):
            try:
                handle = user.GetClipboardData(13)
                address = kernel.GlobalLock(handle) if handle else None
                if address:
                    try:
                        value = ctypes.wstring_at(address)
                    finally:
                        kernel.GlobalUnlock(handle)
            finally:
                user.CloseClipboard()
            break
        time.sleep(.05)
    Path(sys.argv[1]).write_text(json.dumps({"format": "CF_UNICODETEXT", "text": value}, ensure_ascii=False), encoding="utf-8")
    return 0 if value is not None else 1

if __name__ == "__main__":
    raise SystemExit(main())
