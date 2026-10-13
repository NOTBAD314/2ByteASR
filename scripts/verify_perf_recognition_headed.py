"""Rerunnable recognition performance / memory-reclaim case (source or frozen EXE).

Usage:
    python scripts/verify_perf_recognition_headed.py --media CLIP --output tmp/<new dir> \
        [--exe dist/2ByteASR/2ByteASR.exe] [--runs 2] [--ai]

The normal window adds the media with the Home file button and presses Start
(twobyteasr/perf_recognition_audit.py), repeating in one process. Model choices
(models/switches/performance) are copied from the daily settings into an
isolated profile; AI proofreading/sentence grouping stay off unless --ai, which
also borrows the existing encrypted key store read only. Interpreters, the
model folder (through a junction) and the key store are declared in a hashed
manifest and re-hashed afterwards; the daily settings file is only read.
Result: <output>/perf-recognition.json.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sentinels(model_root, limit=4):
    rows = []
    for folder in sorted(p for p in model_root.iterdir() if p.is_dir()):
        candidate = next((p for p in sorted(folder.rglob("*.json")) if p.is_file() and p.stat().st_size < 1_000_000), None)
        if candidate:
            rows.append({"path": str(candidate), "sha256": sha(candidate)})
        if len(rows) >= limit:
            break
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--ai", action="store_true")
    parser.add_argument("--ai-scope", choices=("all", "grouping"), default="all",
                        help="With --ai: 'grouping' keeps AI proofreading off and only enables AI line breaking")
    parser.add_argument("--subtitle-output", choices=("original", "translation", "bilingual"),
                        help="Subtitle output for this run (translation/bilingual call the configured text service)")
    parser.add_argument("--settings", type=Path,
                        help="Explicit non-secret settings fixture; avoids reading daily settings")
    parser.add_argument("--model-root", type=Path, default=ROOT / "models",
                        help="Explicit existing read-only model resource directory")
    parser.add_argument("--timeout", type=int, default=3000)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / "tmp") or out.exists():
        raise SystemExit("Fresh repository tmp output required")
    out.mkdir(parents=True)
    user_root = Path(os.environ["LOCALAPPDATA"]) / "2ByteASR"
    daily_settings = args.settings.resolve() if args.settings else user_root / "2byteasr_settings.json"
    secrets = user_root / "secrets.dat"
    protected = {str(daily_settings): sha(daily_settings)}
    if args.ai:
        protected[str(secrets)] = sha(secrets)
    media_dir = out / "media"
    media_dir.mkdir()
    media = media_dir / args.media.name
    shutil.copy2(args.media, media)
    protected[str(args.media.resolve())] = sha(args.media)

    daily = json.loads(daily_settings.read_text("utf-8-sig"))
    settings = {key: daily[key] for key in ("schema_version", "models", "switches", "performance") if key in daily}
    if not args.ai:
        settings.setdefault("switches", {}).update(enable_ai_polish=False, use_ai_grouping=False)
    elif args.ai_scope == "grouping":
        settings.setdefault("switches", {}).update(enable_ai_polish=False, use_ai_grouping=True)
    if args.subtitle_output:
        settings["subtitle_language"] = {"recognition_language": "auto", "output": args.subtitle_output,
                                         "translation_script": "zh-Hans"}
    # Isolated profiles read settings from <test root>/config (settings.stable_settings_root).
    config = out / "config"
    config.mkdir(parents=True)
    (config / "2byteasr_settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), "utf8")

    junction = out / "models"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(args.model_root.resolve())], check=True, capture_output=True)
    roles = {}
    for role, venv in (("main", ".venv-main"), ("moss", ".venv-moss")):
        python, config = ROOT / venv / "Scripts" / "python.exe", ROOT / venv / "pyvenv.cfg"
        roles[role] = {"python": str(python), "python_sha256": sha(python),
                       "venv_config": str(config), "venv_config_sha256": sha(config)}
    manifest = {"schema_version": 1, "roles": roles,
                "model_root": {"path": str(junction), "sentinels": sentinels(junction)}}
    if args.ai:
        manifest["secrets"] = {"path": str(secrets), "sha256": protected[str(secrets)]}
    manifest_path = out / "borrowed-resources.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf8")

    # Isolate this preparation process too, before importing product modules.
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out),
                      TWOBYTEASR_STARTUP_TRACE=str(out / "preparation-startup.jsonl"))
    from twobyteasr.test_isolation import install
    install()
    # Older frozen builds install qtawesome fonts across the Windows session.
    # Seed copies from the exact package so baseline runs do not register fonts.
    bundle = args.exe.resolve().parent if args.exe else ROOT / "dist/2ByteASR"
    if args.exe and args.exe.resolve() == ROOT / "2ByteASR.exe":
        bundle = ROOT / "dist/2ByteASR"
    fonts = bundle / "qtawesome/fonts"
    if fonts.is_dir():
        destination = out / "local/Microsoft/Windows/Fonts"
        destination.mkdir(parents=True, exist_ok=True)
        for font in fonts.iterdir():
            if font.is_file():
                shutil.copy2(font, destination / font.name)

    # The acceptance guard requires an owned project inside the output; it is
    # not opened (the audit works from Home).
    from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    startup_project = save_project(SubtitleProject(media=StudioMedia(path=str(media), duration_ms=1000),
                                                   cues=[StudioCue("c1", 0, 900, "placeholder")]),
                                   out / "startup-project.2byteproj")
    from twobyteasr.glossary_live_resources import MANIFEST_ENV
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO="perf-recognition",
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1",
               TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               PERF_RECOGNITION_MEDIA=str(media), PERF_RECOGNITION_RUNS=str(args.runs),
               TWOBYTEASR_STARTUP_PROJECT=str(startup_project),
               PERF_TIMEOUT_S=str(max(120, args.timeout - 120)), QT_QPA_PLATFORM="windows", PYTHONUTF8="1")
    env[MANIFEST_ENV] = str(manifest_path)
    for key in ("QT_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING", "QT_FONT_DPI", "TWOBYTEASR_STARTUP_OPEN_STUDIO"):
        env.pop(key, None)
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(ROOT / "quick_start.py")]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / "process", timeout=args.timeout)
    path = out / "perf-recognition.json"
    result = json.loads(path.read_text("utf8")) if path.is_file() else {}
    unchanged = {name: sha(name) == digest for name, digest in protected.items()}
    result.update(exit_code=code, runner_exe=str(args.exe or "source"), ai=args.ai,
                  user_files_unchanged=unchanged)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf8")
    print(json.dumps({"exit_code": code, "finished": result.get("finished"), "errors": result.get("errors"),
                      "runs": [{k: r.get(k) for k in ("wall_s", "statuses", "peak_main_rss_mb",
                                                         "peak_children_rss_mb")} for r in result.get("runs", [])],
                      "user_files_unchanged": unchanged}, ensure_ascii=False)[:3000])
    return 0 if code == 0 and result.get("finished") and all(unchanged.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
