"""Remove the qtawesome icon-font copies that old test runs registered with
Windows for the current sign-in session (see docs/KNOWN_ISSUES.md).

Before 2026-10-10 every test process that drew an icon copied qtawesome's 12
fonts into its own temporary LOCALAPPDATA and registered them for the whole
session (AddFontResourceW). Thousands of registrations stay until sign-out,
and Qt's DirectWrite font database then spends seconds on every app start
opening them (2026-10-10: ~2.4 s of each launch on this machine).

Signing out of Windows clears them as well. This script only calls
RemoveFontResourceW for font files under the known test folders (system Temp
`2byteasr-pytest*`, the repository's `tmp/` and `.claude/worktrees/*/tmp/`);
it never touches the fonts in the real %LOCALAPPDATA%\\Microsoft\\Windows\\Fonts
or C:\\Windows\\Fonts and never deletes files.

Usage:
    python scripts/unregister_test_icon_fonts.py           # list only
    python scripts/unregister_test_icon_fonts.py --apply   # unregister
"""
from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ICON_FONTS = {
    "codicon-0.0.36.ttf", "elusiveicons-webfont-2.0.ttf", "fontawesome5-brands-webfont-5.15.4.ttf",
    "fontawesome5-regular-webfont-5.15.4.ttf", "fontawesome5-solid-webfont-5.15.4.ttf",
    "fontawesome6-brands-webfont-6.7.2.ttf", "fontawesome6-regular-webfont-6.7.2.ttf",
    "fontawesome6-solid-webfont-6.7.2.ttf", "materialdesignicons5-webfont-5.9.55.ttf",
    "materialdesignicons6-webfont-6.9.96.ttf", "phosphor-1.3.0.ttf", "remixicon-2.5.0.ttf",
}


def candidates():
    roots = [Path(tempfile.gettempdir()), ROOT / "tmp"]
    roots += [path / "tmp" for path in (ROOT / ".claude" / "worktrees").glob("*")]
    real = {os.path.normcase(str(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"))}
    for root in roots:
        if not root.is_dir():
            continue
        pattern = "2byteasr-pytest*" if root == Path(tempfile.gettempdir()) else "*"
        for base in root.glob(pattern):
            if not base.is_dir():
                continue
            for path in base.rglob("*.ttf"):
                if path.name in ICON_FONTS and os.path.normcase(str(path.parent)) not in real:
                    yield path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="unregister (otherwise only list)")
    args = parser.parse_args()
    paths = sorted(set(candidates()))
    print(f"{len(paths)} test font copies under the test folders")
    if not args.apply:
        for path in paths[:10]:
            print("  ", path)
        print("List only. Re-run with --apply to unregister them for this session (or sign out of Windows).")
        return 0
    gdi = ctypes.windll.gdi32
    removed = 0
    for path in paths:
        # A file registered several times needs one removal per registration.
        while gdi.RemoveFontResourceW(str(path)):
            removed += 1
    if removed:
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001D, 0, 0, 0x0002, 2000, None)  # WM_FONTCHANGE
    print(f"Unregistered {removed} registrations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
