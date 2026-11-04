"""Copy the README animation project into a per-language render folder.

index.html carries every text set (zh, en, ja, ko); the <html lang> attribute picks one.
Usage: build_anim_variant.py <project_dir> <en|ja|ko|zh-CN> <out_dir>
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

FILES = ("hyperframes.json", "meta.json", "package.json")


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    src, lang, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    if lang not in ("en", "ja", "ko", "zh-CN"):
        raise SystemExit(f"unsupported language: {lang}")
    html = (src / "index.html").read_text(encoding="utf-8")
    marker = '<html lang="zh-CN">'
    if html.count(marker) != 1:
        raise SystemExit("index.html must start with exactly one <html lang=\"zh-CN\">")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html.replace(marker, f'<html lang="{lang}">'), encoding="utf-8")
    for name in FILES:
        if (src / name).exists():
            shutil.copy2(src / name, out / name)
    for folder in ("assets", "compositions"):
        if (src / folder).exists():
            shutil.copytree(src / folder, out / folder, dirs_exist_ok=True)
    print(f"{lang}: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
