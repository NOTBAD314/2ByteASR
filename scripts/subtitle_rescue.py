"""Standalone entry for source and frozen rescue builds (no quick_start)."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description="读取保存的工程，安全导出当前时间轴字幕。")
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", type=Path, metavar="NEW_DIRECTORY")
    parser.add_argument("--ui-audit", type=Path, metavar="NEW_DIRECTORY")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    from twobyteasr.exports.subtitle_rescue import BUILD_ID, rescue_subtitles
    if args.version:
        print(json.dumps({"build_id": BUILD_ID, "frozen": bool(getattr(sys, "frozen", False)),
                          "executable": sys.executable}, ensure_ascii=False))
        return 0
    if args.self_test or args.ui_audit:
        from twobyteasr.acceptance.subtitle_rescue_audit import run
        return run(args.self_test or args.ui_audit, gui=bool(args.ui_audit))
    if args.source and args.output:
        try:
            path = rescue_subtitles(args.source, args.output)
            print(str(path))
            return 0
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
    from PySide6.QtWidgets import QApplication
    from twobyteasr.exports.subtitle_rescue_ui import SubtitleRescueDialog
    app = QApplication([])
    window = SubtitleRescueDialog(str(args.source) if args.source else "")
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
