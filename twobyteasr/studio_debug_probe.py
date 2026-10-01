#!/usr/bin/env python3
"""
2ByteASR Subtitle Studio — Render Truth Probe Dumper

Usage (from project root, while Studio is open with TWOBYTEASR_DEBUG_SUBTITLES=1):

    python -m twobyteasr.studio_debug_probe --dump

Or inside a running process (e.g. from the Python console attached to the GUI process):

    from twobyteasr.studio_debug_probe import dump_current
    dump_current()   # writes tmp/studio_debug/probe_*.json and prints path

The probe answers:
- Which Cue is selected
- What ASS Dialogue event(s) contain that text (proof the glyph is ours)
- What mpv says is the active sid + track list
- What the overlay box thinks the rect/anchor is
- Full effective style, PlayRes, video-out-params, dw/dh

This is evidence only. Do not use it to "fix numbers" until the probe shows the mismatch.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

def _ensure_tmp() -> Path:
    p = Path("tmp") / "studio_debug"
    p.mkdir(parents=True, exist_ok=True)
    return p

def dump_probe(page: Any) -> Path:
    """Given a SubtitleStudioPage instance, dump its render_truth_probe to disk and return path."""
    if page is None:
        raise RuntimeError("No SubtitleStudioPage instance provided")
    probe = page.render_truth_probe(force=True)
    out_dir = _ensure_tmp()
    ts = int(time.time() * 1000)
    out = out_dir / f"probe_{ts}.json"
    out.write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] wrote {out}")
    # Also a tiny summary line for quick eyeballing
    try:
        corr = probe.get("correspondence", {})
        print("[probe] cue_text:", (probe.get("project") or {}).get("cue_text", "")[:60])
        print("[probe] mpv_sub_text:", corr.get("mpv_sub_text"))
        print("[probe] ass_matches:", len(corr.get("ass_events_containing_text", [])))
        print("[probe] overlay_anchor:", (probe.get("overlay") or {}).get("ass_anchor"))
        print("[probe] video_content_rect:", (probe.get("overlay") or {}).get("video_content_rect"))
    except Exception:
        pass
    return out

def dump_current() -> Path | None:
    """Best-effort: walk QApplication top levels and find the first SubtitleStudioPage."""
    try:
        from PySide6.QtWidgets import QApplication
    except Exception as e:
        print("PySide6 not importable:", e)
        return None
    app = QApplication.instance()
    if not app:
        print("No QApplication instance")
        return None
    for w in app.topLevelWidgets():
        # Try direct attribute
        if hasattr(w, "render_truth_probe"):
            return dump_probe(w)
        # Common container pattern: the page may be inside a central widget or stacked
        for child in w.findChildren(object):
            if hasattr(child, "render_truth_probe"):
                return dump_probe(child)
    print("Could not locate a SubtitleStudioPage with render_truth_probe")
    return None

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="Attempt to locate running Studio page and dump probe")
    args = ap.parse_args()
    if args.dump:
        dump_current()
    else:
        print("Use --dump while Subtitle Studio is open (with TWOBYTEASR_DEBUG_SUBTITLES=1).")
