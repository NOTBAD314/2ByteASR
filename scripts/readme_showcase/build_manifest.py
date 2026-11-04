"""Rewrite docs/assets/readme/manifest.json for a checkout of the public main branch.

Keeps the descriptive header fields, recomputes every image's size, frame count and SHA-256.
Usage: build_manifest.py <checkout root> [YYYY-MM-DD]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image

IMAGE_SUFFIXES = {".png", ".gif", ".webp", ".jpg", ".jpeg"}


def describe(path: Path, root: Path) -> dict:
    data = path.read_bytes()
    with Image.open(path) as image:
        width, height = image.size
        frames = getattr(image, "n_frames", 1)
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(data),
        "width": width,
        "height": height,
        "frames": frames,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 2
    root = Path(sys.argv[1]).resolve()
    folder = root / "docs" / "assets" / "readme"
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = [describe(p, root) for p in sorted(folder.iterdir()) if p.suffix.lower() in IMAGE_SUFFIXES]
    if len(sys.argv) == 3:
        manifest["updated"] = sys.argv[2]
    manifest["total_bytes"] = sum(item["bytes"] for item in files)
    manifest["files"] = files
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(files)} files, {manifest['total_bytes']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
