"""Record the actual source bytes shipped in a Docker image (without Git)."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

root = Path("/app")
files = {}
for name in ("twobyteasr", "renderer", "packaging/docker"):
    for path in (root / name).rglob("*"):
        if (not path.is_file() or "node_modules" in path.parts or "__pycache__" in path.parts
                or path.suffix not in {".py", ".js", ".mjs", ".json", ".ts", ".tsx", ".txt", ".sh", ".html", ".css"}):
            continue
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
for path in list(root.glob("*.py")) + [root / "dependencies.lock.json", root / "2byteasr_version.json"]:
    files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
source = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
metadata = {
    "schema_version": 1, "app_version": "0.8.1",
    "git_sha": os.environ.get("VCS_REF", "docker-local"), "git_dirty": False,
    "build_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "build_channel": "docker-cpu", "source_sha256": hashlib.sha256(source).hexdigest(),
    "source_file_count": len(files),
    "base_release": "83f928c1aa445fd17312ffbfb30c88cf5d5027b1",
}
(root / "build").mkdir(exist_ok=True)
(root / "build/2byteasr_build.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf8")
(root / "build/docker-source-manifest.json").write_text(json.dumps(files, sort_keys=True, indent=2) + "\n", encoding="utf8")
print(json.dumps(metadata))
