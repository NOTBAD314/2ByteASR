"""Build a disposable Studio project around a real recording for P6.4 checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.studio_danmaku import parse_danmaku_xml
from twobyteasr.studio_edit_sequence import sequence_of, store_sequence
from twobyteasr.studio_helpers import probe_media_identity
from twobyteasr.studio_highlight_analyzer import (
    candidates_from_local,
    discover_local_candidates,
)
from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    save_project,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("media", type=Path)
    parser.add_argument("xml", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    media = args.media.resolve()
    xml = args.xml.resolve()
    output = args.output.resolve()
    identity = probe_media_identity(media)
    duration_ms = int(identity["duration_ms"])
    project = SubtitleProject(
        media=StudioMedia(
            path=str(media),
            display_name=media.stem,
            duration_ms=duration_ms,
            fingerprint=str(identity.get("fingerprint") or ""),
            width=int(identity.get("width") or 0),
            height=int(identity.get("height") or 0),
        ),
        cues=[
            StudioCue("p64-1", 414_000, 421_000, "怎么会这样？！突然就翻车了。"),
            StudioCue("p64-2", 421_000, 427_000, "哈哈哈哈，这也能过不去。"),
            StudioCue("p64-3", 427_000, 434_000, "这一段可以留作剪辑高能。"),
        ],
    )
    document = parse_danmaku_xml(xml)
    local = discover_local_candidates(project, document, top_k=20)
    candidates = candidates_from_local(project, local, limit=20, max_seconds=180)
    sequence = sequence_of(project)
    sequence.danmaku_path = str(xml)
    sequence.clip_candidates = candidates
    store_sequence(project, sequence)
    project.studio_state["media_xml_match"] = "automatic"
    project.studio_state["media_xml_candidates"] = [str(xml)]
    save_project(project, output)
    print(json.dumps({
        "project": str(output),
        "media": str(media),
        "duration_ms": duration_ms,
        "resolution": [project.media.width, project.media.height],
        "candidate_count": len(candidates),
        "cue_count": len(project.cues),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
