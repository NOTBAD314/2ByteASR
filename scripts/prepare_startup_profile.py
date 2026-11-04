"""Build an isolated user profile that mirrors the operator's real startup state.

The real ``%LOCALAPPDATA%\\2ByteASR`` and the real QSettings are only read.
The copy holds the settings/profile JSON files, the glossary, the project
library (projects copied, recent-project paths rewritten into the copy),
Studio settings, the cache index and the window state stored in QSettings.
Models are hard-linked so model checks see the same files without copying
14 GB; nothing at startup writes to model files.

Usage: python scripts/prepare_startup_profile.py <tmp/.../profile>
Then launch with TWOBYTEASR_TEST_ROOT=<that folder>.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
JSON_FILES = (
    "2byteasr_settings.json", "content_profiles.json", "glossary-update-history.json",
    "learned_game_terms.json", "profiles.json", "profiles.v1.json",
)
COPY_DIRS = ("Projects", "SubtitleStudio", "storage", "model-readiness", "reports")


def _real_data_root() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "2ByteASR"


def _copy_qsettings(target_ini_dir: Path) -> int:
    """Copy the real registry QSettings into the isolated ini the app will open."""
    from PySide6.QtCore import QSettings

    source = QSettings("2ByteASR", "2ByteASR")
    keys = source.allKeys()
    # Same naming as twobyteasr.test_isolation.IsolatedSettings.
    import hashlib
    import re

    identity = "2ByteASR/2ByteASR"
    label = re.sub(r"[^\w.-]", "_", identity)[:90]
    digest = hashlib.sha256(identity.encode()).hexdigest()[:10]
    target_ini_dir.mkdir(parents=True, exist_ok=True)
    target = QSettings(str(target_ini_dir / f"{label}-{digest}.ini"), QSettings.IniFormat)
    for key in keys:
        target.setValue(key, source.value(key))
    target.sync()
    return len(keys)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    profile = Path(sys.argv[1]).resolve()
    if not profile.is_relative_to(ROOT / "tmp"):
        raise SystemExit("profile must live under the repository tmp/")
    if profile.exists():
        raise SystemExit(f"{profile} already exists; use a fresh folder")
    real = _real_data_root()
    data = profile / "local" / "2ByteASR"
    data.mkdir(parents=True)
    for name in JSON_FILES:
        if (real / name).is_file():
            shutil.copy2(real / name, data / name)
    for name in COPY_DIRS:
        if (real / name).is_dir():
            shutil.copytree(real / name, data / name)
    # Studio's small top-level state (settings, the project-library index that
    # drives the home/library cards, presets) with paths moved into the copy,
    # plus the card thumbnails. Its big preview/log caches are not copied.
    real_json = json.dumps(str(real))[1:-1]
    copy_json = json.dumps(str(data))[1:-1]
    studio_real = real / "SubtitleStudioPreview"
    if studio_real.is_dir():
        (data / "SubtitleStudioPreview").mkdir()
        for source in studio_real.glob("*.json"):
            text = source.read_text(encoding="utf-8-sig")
            (data / "SubtitleStudioPreview" / source.name).write_text(
                text.replace(real_json, copy_json), encoding="utf-8")
        if (studio_real / "thumbnails").is_dir():
            shutil.copytree(studio_real / "thumbnails", data / "SubtitleStudioPreview" / "thumbnails")
    registry = real / "runtimes" / "registry.json"
    if registry.is_file():
        (data / "runtimes").mkdir()
        shutil.copy2(registry, data / "runtimes" / "registry.json")
    persisted = json.loads((real / "runtime_paths.json").read_text(encoding="utf-8"))
    model_source = Path(persisted.get("model_root") or ROOT / "models")
    model_target = profile / "models"
    linked = 0
    for source in model_source.rglob("*"):
        target = model_target / source.relative_to(model_source)
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, target)
            linked += 1
    # The real profile already has qtawesome's per-user font copies. Without
    # them qtawesome copies and registers its 12 fonts for the whole sign-in
    # session on every fresh profile, which the real daily start never does.
    user_fonts = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts"
    seeded_fonts = profile / "local" / "Microsoft" / "Windows" / "Fonts"
    seeded_fonts.mkdir(parents=True)
    import qtawesome
    for source in (Path(qtawesome.__file__).parent / "fonts").iterdir():
        if source.is_file() and (user_fonts / source.name).is_file():
            shutil.copy2(source, seeded_fonts / source.name)
    keys = _copy_qsettings(profile / "qsettings")
    print(json.dumps({"profile": str(profile), "models_linked": linked, "qsettings_keys": keys},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
