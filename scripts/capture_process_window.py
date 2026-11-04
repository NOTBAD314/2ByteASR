"""Capture the largest visible top-level window owned by a process tree."""

from __future__ import annotations

import argparse
import ctypes
import json
from ctypes import wintypes
from pathlib import Path

import psutil
from PIL import Image, ImageGrab


class BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_ushort),
        ("biBitCount", ctypes.c_ushort),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BitmapInfo(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BitmapInfoHeader),
        ("bmiColors", ctypes.c_uint32 * 3),
    ]


def process_tree(root_pid: int) -> set[int]:
    root = psutil.Process(root_pid)
    return {root_pid, *(child.pid for child in root.children(recursive=True))}


def visible_windows(pids: set[int]) -> list[tuple[int, tuple[int, int, int, int]]]:
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    windows: list[tuple[int, tuple[int, int, int, int]]] = []

    def visit(hwnd, _lparam):
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids or not user32.IsWindowVisible(hwnd):
            return True
        rect = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            bounds = (rect.left, rect.top, rect.right, rect.bottom)
            if bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                windows.append((int(hwnd), bounds))
        return True

    user32.EnumWindows(callback_type(visit), 0)
    return windows


def print_window(hwnd: int, bounds: tuple[int, int, int, int]) -> Image.Image:
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    source_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(source_dc)
    bitmap = gdi32.CreateCompatibleBitmap(source_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(hwnd, memory_dc, 0x00000002):
            raise RuntimeError("PrintWindow failed")
        info = BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(BitmapInfoHeader)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        copied = gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            buffer,
            ctypes.byref(info),
            0,
        )
        if copied != height:
            raise RuntimeError(f"GetDIBits copied {copied}/{height} rows")
        return Image.frombuffer(
            "RGBA", (width, height), buffer, "raw", "BGRA", 0, 1
        ).convert("RGB")
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, source_dc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pid", type=int)
    parser.add_argument("output", type=Path)
    parser.add_argument("--screen", action="store_true")
    args = parser.parse_args()
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass
    candidates = visible_windows(process_tree(args.pid))
    if not candidates:
        raise RuntimeError(f"no visible window found for process tree {args.pid}")
    hwnd, bounds = max(
        candidates,
        key=lambda item: (item[1][2] - item[1][0]) * (item[1][3] - item[1][1]),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image = (
        ImageGrab.grab(bbox=bounds, all_screens=True)
        if args.screen
        else print_window(hwnd, bounds)
    )
    image.save(args.output)
    print(json.dumps({
        "pid": args.pid,
        "hwnd": hwnd,
        "bounds": list(bounds),
        "pixels": list(image.size),
        "path": str(args.output.resolve()),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
