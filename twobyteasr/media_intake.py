"""Small, shared media validation boundary; no models or GUI imports."""
from __future__ import annotations
import argparse
import os
from pathlib import Path

SUPPORTED_MEDIA_SUFFIXES = frozenset({
    ".mp4", ".mov", ".mkv", ".webm", ".flv", ".avi",
    ".mp3", ".wav", ".m4a", ".flac", ".aac",
})

def parse_media_arguments(argv):
    parser = argparse.ArgumentParser(prog="2ByteASR.exe",
        description="打开 2ByteASR 并加入音视频；已运行时发送给原窗口。不会自动开始识别。")
    parser.add_argument("--import", dest="import_paths", nargs="+", default=[], metavar="FILE",
                        help="导入一个或多个音视频文件（也可直接写文件路径）")
    parser.add_argument("paths", nargs="*", metavar="FILE", help="音视频文件或现有 2ByteASR 工程")
    import sys
    if sys.stdout is None or sys.stderr is None:
        # Windowed EXEs have no console. Help and syntax errors must still be visible.
        def message(text):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, "2ByteASR 命令行", 0)
        if "--help" in argv or "-h" in argv:
            message(parser.format_help())
            raise SystemExit(0)
        def error(text):
            message(text + "\n\n" + parser.format_help())
            raise SystemExit(2)
        parser.error = error
    args = parser.parse_args(argv)
    # Resolve lexically before any launcher/GUI changes cwd; do not touch network drives here.
    return [os.path.abspath(os.path.join(os.environ.get("TWOBYTEASR_INVOKER_CWD", os.getcwd()), os.path.expanduser(p))) for p in args.paths + args.import_paths]

def validate_media_paths(paths, *, check_readable=True):
    accepted, rejected, seen = [], [], set()
    for raw in paths or ():
        try:
            path = Path(str(raw)).expanduser()
            if path.suffix.lower() not in SUPPORTED_MEDIA_SUFFIXES:
                rejected.append(f"不支持的文件类型：{path.name}")
                continue
            if not path.is_file():
                rejected.append(f"文件不存在或不是普通文件：{path}")
                continue
            resolved = str(path.resolve())
            if check_readable:
                with path.open("rb") as source:
                    if not source.read(1):
                        rejected.append(f"文件为空：{path.name}")
                        continue
            identity = os.path.normcase(resolved)
            if identity not in seen:
                accepted.append(resolved)
                seen.add(identity)
        except (OSError, ValueError) as exc:
            rejected.append(f"无法读取文件（可能被占用）：{raw}：{exc}")
    return accepted, rejected
