"""One-shot P6.5 migration for the user's existing 未命名工程 1–4.

The migration never creates projects and never guesses a media path.  It
merges only canonical project/autosave/EditSequence/recent data, probes a real
source once when cached metadata is incomplete, persists through save_project
(therefore creating the normal backup), and builds the ordinary cover cache.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.studio_helpers import probe_media_identity
from twobyteasr.studio_project import (
    PROJECT_SUFFIX,
    library_project_snapshot,
    project_library_root,
    repair_project_library_metadata,
    studio_settings_path,
)
from twobyteasr.studio_project_controller import StudioProjectController


TARGETS = ("未命名工程", "未命名工程 2", "未命名工程 3", "未命名工程 4")


def _recent_by_path() -> dict[str, dict]:
    settings = studio_settings_path()
    try:
        payload = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    rows = payload.get("recent_projects", ()) if isinstance(payload, dict) else ()
    result: dict[str, dict] = {}
    for item in rows:
        if not isinstance(item, dict) or not str(item.get("path") or "").strip():
            continue
        result[str(Path(item["path"]).expanduser().resolve()).casefold()] = dict(item)
    return result


def repair() -> list[dict[str, object]]:
    root = project_library_root()
    recent = _recent_by_path()
    records: list[dict[str, object]] = []
    for name in TARGETS:
        path = (root / name / f"{name}{PROJECT_SUFFIX}").resolve()
        row: dict[str, object] = {"name": name, "path": str(path), "exists": path.is_file()}
        if not path.is_file():
            records.append(row)
            continue
        recent_row = recent.get(str(path).casefold(), {})
        snapshot, before, needs_repair = library_project_snapshot(path, recent_row)
        metadata = None
        media = Path(snapshot.media.path).expanduser() if snapshot.media.path else None
        if media is not None and media.is_file() and (
            not snapshot.media.duration_ms or not snapshot.media.width or not snapshot.media.height
        ):
            metadata = probe_media_identity(media)
        project, summary, changed = repair_project_library_metadata(
            path,
            recent_row,
            media_metadata=metadata,
        )
        cover = StudioProjectController._ensure_project_cover(object(), path, project)
        row.update({
            "needs_repair": needs_repair,
            "changed": changed,
            "source_media": summary.get("source_media", before.get("source_media", "")),
            "duration_ms": int(summary.get("duration_ms", 0) or 0),
            "resolution": [int(summary.get("width", 0) or 0), int(summary.get("height", 0) or 0)],
            "cue_count": int(summary.get("cue_count", 0) or 0),
            "cover_path": str(cover or ""),
            "cover_exists": bool(cover and Path(cover).is_file()),
        })
        records.append(row)
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="tmp/p65-real-runtime/library-migration.json")
    args = parser.parse_args()
    records = repair()
    target = Path(args.output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(records, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
