"""Derive larger performance-test projects from a real project (read-only input).

Usage:
    python scripts/make_perf_projects.py --base <project.2byteproj> --output tmp/<dir>

Writes into a fresh tmp directory:
  base.2byteproj        unchanged copy of the base project
  mix1000.2byteproj     ~1000 cues, 4 speakers, overlapping speech, 4 styles
  dense3000.2byteproj   ~3000 cues, 6 speakers, overlapping speech, 4 styles

Cue text, timing shape and source evidence come from the base project, so QC,
caption rendering and evidence lookups run on realistic data. Cues stay inside
the media duration; the same media and seek cache as the base project apply.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _speaker_palette():
    return ["#F2C14E", "#7FB3D5", "#E59866", "#82E0AA", "#C39BD3", "#F1948A"]


def derive(project, *, target: int, speakers: int, seed: int, name: str):
    from twobyteasr.studio_project import StudioSpeaker
    rng = random.Random(seed)
    derived = copy.deepcopy(project)
    duration = int(getattr(derived.media, "duration_ms", 0) or max(c.end_ms for c in derived.cues) + 1000)
    base_ids = [s.id for s in derived.speakers]
    palette = _speaker_palette()
    for index in range(len(derived.speakers), speakers):
        derived.speakers.append(StudioSpeaker(id=f"S{index + 1:02d}", name=f"S{index:02d}",
                                              color=palette[index % len(palette)]))
    speaker_ids = [s.id for s in derived.speakers][:speakers]
    style_ids = [s.id for s in derived.styles]
    # Four styles in use: the project's own plus derived size/colour variants.
    from twobyteasr.studio_project import SubtitleStyle
    while len(style_ids) < 4:
        source = derived.styles[len(style_ids) % len(derived.styles)]
        variant = replace(copy.deepcopy(source), id=f"perf-style-{len(style_ids)}",
                          name=f"perf {len(style_ids)}", font_size=float(source.font_size) + 6 * len(style_ids),
                          primary_color=palette[len(style_ids) % len(palette)])
        derived.styles.append(variant)
        style_ids.append(variant.id)
    used_styles = style_ids[:4]
    originals = sorted(derived.cues, key=lambda c: (c.start_ms, c.id))
    if target < 1 or not originals:
        raise ValueError("A positive target and a non-empty base project are required")
    cues = []
    copies = math.ceil(target / len(originals))
    for copy_index in range(copies):
        offset = rng.randint(0, max(1, duration // copies)) if copy_index else 0
        for cue in originals:
            start = (cue.start_ms + offset + copy_index * 997) % max(1, duration - 5000)
            length = max(400, cue.end_ms - cue.start_ms)
            item = copy.deepcopy(cue)
            item.id = hashlib.sha1(f"{name}:{copy_index}:{cue.id}".encode()).hexdigest()[:16]
            item.start_ms = int(start)
            item.end_ms = int(min(duration - 1, start + length))
            # Overlap: other speakers talk over the original line.
            item.speaker_id = speaker_ids[(copy_index + speaker_ids.index(cue.speaker_id)
                                           if cue.speaker_id in speaker_ids else copy_index) % len(speaker_ids)]
            item.style_id = used_styles[(copy_index + len(cue.text)) % len(used_styles)]
            cues.append(item)
            if len(cues) >= target:
                break
        if len(cues) >= target:
            break
    derived.cues = sorted(cues, key=lambda c: (c.start_ms, c.end_ms, c.id))
    derived.project_id = hashlib.sha1(f"{project.project_id}:{name}".encode()).hexdigest()[:32]
    derived.validate()
    return derived


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--counts", type=int, nargs="+", default=[1000, 3000],
                        help="Exact positive cue counts (for example: 100 1000 10000)")
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / "tmp") or out.exists():
        raise SystemExit("Choose a fresh output directory under repository tmp")
    out.mkdir(parents=True)
    from twobyteasr.studio_project import load_project, save_project
    base_bytes = args.base.read_bytes()
    (out / "base.2byteproj").write_bytes(base_bytes)
    project = load_project(args.base)
    summary = {"base": {"cues": len(project.cues), "speakers": len(project.speakers)}}
    if any(count < 1 for count in args.counts):
        raise SystemExit("Cue counts must be positive")
    for seed, target in enumerate(dict.fromkeys(args.counts), 1):
        name = ("mix" if target <= 1000 else "dense") + str(target)
        speakers = 4 if target <= 1000 else 6
        derived = derive(project, target=target, speakers=speakers, seed=seed, name=name)
        if len(derived.cues) != target:
            raise RuntimeError(f"Fixture {name} has {len(derived.cues)} cues, expected {target}")
        path = save_project(derived, out / f"{name}.2byteproj")
        summary[name] = {"cues": len(derived.cues), "speakers": len({c.speaker_id for c in derived.cues}),
                         "styles": len({c.style_id for c in derived.cues}), "bytes": path.stat().st_size}
    (out / "projects.json").write_text(json.dumps(summary, indent=2), "utf8")
    print(json.dumps(summary))
    if args.base.read_bytes() != base_bytes:
        raise SystemExit("base project changed during generation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
