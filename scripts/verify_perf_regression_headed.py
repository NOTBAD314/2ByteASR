"""Rerunnable performance regression case on a private desktop (source or frozen EXE).

Usage:
    python scripts/verify_perf_regression_headed.py --project P.2byteproj --seek-cache SEEKDIR \
        --output tmp/<new dir> [--exe dist/2ByteASR/2ByteASR.exe] [--profile-from WARM_PROFILE] \
        [--phases idle,drag-repeat,...] [--profile-actions multi-press]

The project is copied (the original is only read and its SHA is checked), the
seek cache is hard-linked, all user data goes to an isolated profile. Results:
<output>/perf.json (twobyteasr.perf_regression_audit) plus process logs.
Compare runs with scripts/summarize_perf_regression.py.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=("regression", "pages"), default="regression",
                        help="regression (default): Studio editing/playback; pages: management page entries")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--seek-cache", type=Path)
    parser.add_argument("--cycles", default="3", help="pages: re-entry cycles after the first entries")
    parser.add_argument("--size", default="1600x950", help="pages: window size")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--source-entry", type=Path,
                        help="Optional source-only diagnostic wrapper (never used with --exe)")
    parser.add_argument("--profile-from", type=Path, help="copy a warmed isolated profile")
    parser.add_argument("--seed-legacy-fonts", action="store_true",
                        help="Preseed package fonts for older EXEs that register fonts in Windows")
    parser.add_argument("--phases", default="")
    parser.add_argument("--profile-actions", default="")
    parser.add_argument("--profile-phases", default="",
                        help="cProfile whole phases on the GUI thread, e.g. playback,idle")
    parser.add_argument("--drag-repeats", default="5")
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    if args.exe and args.source_entry:
        parser.error("--source-entry and --exe are mutually exclusive")
    if args.scenario == "pages":
        return _run_pages(args, parser)
    if args.project is None or args.seek_cache is None:
        parser.error("--project and --seek-cache are required for the regression scenario")
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / "tmp") or out.exists():
        raise SystemExit("Fresh repository tmp output required")
    out.mkdir(parents=True)
    data = args.project.read_bytes()
    (out / "project.2byteproj").write_bytes(data)
    for source in args.seek_cache.resolve().rglob("*"):
        if not source.is_file() or source.suffix == ".lock":
            continue
        target = out / "seek" / source.relative_to(args.seek_cache.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in {".mkv", ".mp4"}:
            os.link(source, target)
        else:
            shutil.copy2(source, target)
    if args.profile_from:
        shutil.copytree(args.profile_from, out / "profile")
    if args.seed_legacy_fonts:
        bundle = args.exe.resolve().parent if args.exe else ROOT / "dist/2ByteASR"
        if args.exe and args.exe.resolve() == ROOT / "2ByteASR.exe":
            bundle = ROOT / "dist/2ByteASR"
        source_fonts = bundle / "qtawesome/fonts"
        target_fonts = out / "profile/local/Microsoft/Windows/Fonts"
        target_fonts.mkdir(parents=True, exist_ok=True)
        for font in source_fonts.iterdir():
            if font.is_file():
                shutil.copy2(font, target_fonts / font.name)
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out / "profile"), TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", TWOBYTEASR_STARTUP_OPEN_STUDIO="1",
               TWOBYTEASR_STARTUP_SIZE="1600x950", TWOBYTEASR_STARTUP_PROJECT=str(out / "project.2byteproj"),
               TWOBYTEASR_SEEK_CACHE_ROOT=str(out / "seek"), TWOBYTEASR_ACCEPTANCE_SCENARIO="perf-regression",
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), PERF_DRAG_REPEATS=args.drag_repeats,
               PERF_TIMEOUT_S=str(max(60, args.timeout - 60)), QT_QPA_PLATFORM="windows", PYTHONUTF8="1")
    if args.phases:
        env["PERF_PHASES"] = args.phases
    if args.profile_actions:
        env["PERF_PROFILE_ACTIONS"] = args.profile_actions
    if args.profile_phases:
        env["PERF_PROFILE_PHASES"] = args.profile_phases
    for key in ("QT_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING", "QT_FONT_DPI"):
        env.pop(key, None)
    from isolated_windows_desktop import run_on_desktop
    source_entry = args.source_entry.resolve() if args.source_entry else ROOT / "quick_start.py"
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(source_entry)]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / "process", timeout=args.timeout)
    path = out / "perf.json"
    result = json.loads(path.read_text("utf8")) if path.is_file() else {}
    result.update(exit_code=code, original_unchanged=args.project.read_bytes() == data,
                  original_sha256=hashlib.sha256(data).hexdigest(), runner_exe=str(args.exe or "source"))
    result["failed_boolean_checks"] = [name for name, value in result.get("checks", {}).items()
                                       if value is False]
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")
    print(json.dumps({k: result.get(k) for k in ("exit_code", "finished", "gui_shutdown", "errors",
                                                 "original_unchanged", "cue_count")}, ensure_ascii=False)[:2000])
    return 0 if (code == 0 and result.get("finished") and result.get("gui_shutdown")
                 and result.get("original_unchanged") and not result.get("errors")
                 and not result["failed_boolean_checks"]) else 1


def _clone_profile(source: Path, target: Path) -> None:
    """Copy a prepared profile; model weights are hard-linked (never copied)."""
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        destination = target / relative
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            if relative.parts and relative.parts[0] == "models":
                os.link(item, destination)
            else:
                shutil.copy2(item, destination)
    # Studio's settings / library index / learning store name projects by
    # absolute path: point them at this copy, so a run never reads or repairs
    # (covers, metadata) the prepared profile it was cloned from.
    old_root = json.dumps(str(source / "local" / "2ByteASR"))[1:-1]
    new_root = json.dumps(str(target / "local" / "2ByteASR"))[1:-1]
    data = target / "local" / "2ByteASR"
    for path in [*data.glob("SubtitleStudioPreview/*.json"), *data.glob("cache/*.json")]:
        text = path.read_text(encoding="utf-8-sig")
        if old_root in text:
            path.write_text(text.replace(old_root, new_root), encoding="utf-8")


def _run_pages(args, parser):
    if args.profile_from is None:
        parser.error("--scenario pages needs --profile-from (scripts/prepare_startup_profile.py)")
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / "tmp") or out.exists():
        raise SystemExit("Fresh repository tmp output required")
    source = args.profile_from.resolve()
    if not source.is_relative_to(ROOT / "tmp") or not (source / "local" / "2ByteASR").is_dir():
        raise SystemExit("--profile-from must be a prepared profile under tmp/")
    out.mkdir(parents=True)
    _clone_profile(source, out / "profile")
    # The acceptance gate requires an owned file next to the output; the page
    # audit never opens it (Studio stays on its project library).
    (out / "placeholder.2byteproj").write_text("{}", "utf8")
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out / "profile"), TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", TWOBYTEASR_STARTUP_RAISE="1",
               TWOBYTEASR_STARTUP_SIZE=args.size, TWOBYTEASR_STARTUP_PROJECT=str(out / "placeholder.2byteproj"),
               TWOBYTEASR_ACCEPTANCE_SCENARIO="perf-pages", TWOBYTEASR_ACCEPTANCE_DIR=str(out),
               PAGES_CYCLES=str(args.cycles), PERF_TIMEOUT_S=str(max(60, args.timeout - 60)),
               QT_QPA_PLATFORM="windows", PYTHONUTF8="1")
    env.pop("TWOBYTEASR_STARTUP_OPEN_STUDIO", None)
    for key in ("QT_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING", "QT_FONT_DPI"):
        env.pop(key, None)
    from isolated_windows_desktop import run_on_desktop
    source_entry = args.source_entry.resolve() if args.source_entry else ROOT / "quick_start.py"
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(source_entry)]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / "process", timeout=args.timeout)
    path = out / "perf.json"
    result = json.loads(path.read_text("utf8")) if path.is_file() else {}
    result.update(exit_code=code, runner_exe=str(args.exe or "source"))
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")
    print(json.dumps({k: result.get(k) for k in ("exit_code", "finished", "gui_shutdown", "errors", "checks")},
                     ensure_ascii=False)[:2000])
    print(json.dumps(result.get("summary", {}), ensure_ascii=False)[:4000])
    return 0 if (code == 0 and result.get("finished") and result.get("gui_shutdown")
                 and not result.get("errors")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
