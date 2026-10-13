# SPDX-License-Identifier: GPL-3.0-only
"""Studio editing smoothness and export speed on a Mac (2026-10-14).

Answers "is editing and exporting smooth on this Mac" with numbers, using the
installed app and a synthetic project (no private media):

1. fixture: a 10-minute 1920x1080 30 fps H.264/AAC test video made with the
   app's own ffmpeg, plus a project with 1000 cues, 4 speakers (overlapping
   speech) and 4 styles;
2. studio: the installed app opens the project in the normal window and the
   existing ``perf-regression`` acceptance audit drives selection, dragging,
   select-all drag, undo/redo, delete, ripple trim, text edits, playback,
   save/reopen and close-while-busy (per action: handler / next frame / idle);
3. export: the production export path (``run_render_job`` with the app's
   ffmpeg) renders 60 seconds at 1080p30 with burned-in subtitles; reports the
   encoder actually used and the speed relative to real time.

    python scripts/macos_studio_perf.py --app /Applications/2ByteASR.app --output "$RUNNER_TEMP/tmp/x/studio-perf"

The output must be a new folder below a ``tmp`` directory (the app's
acceptance guard requires it). ``result.json`` holds the summary.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LINES = ("这波团战打得太漂亮了", "先别急，等技能好了再上", "左边有人，注意一下",
         "我觉得这个装备不太适合现在出", "好的好的，我去拿龙", "这个操作我给满分",
         "等一下等一下，他们还有两个人没出现", "稳住我们能赢", "大招交了，快撤",
         "今天状态不错啊", "这局经济领先五千", "对面打野在下路蹲了很久了")


def _dist(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    pick = lambda q: values[min(len(values) - 1, int(round((len(values) - 1) * q)))]
    return {"n": len(values), "p50": round(pick(.5), 1), "p95": round(pick(.95), 1), "max": round(values[-1], 1)}


def _machine() -> dict:
    info = {"platform": platform.platform(), "machine": platform.machine(), "cpu_count": os.cpu_count()}
    if sys.platform == "darwin":
        for key in ("hw.model", "machdep.cpu.brand_string", "hw.memsize", "hw.perflevel0.physicalcpu",
                    "hw.perflevel1.physicalcpu"):
            try:
                info[key] = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True,
                                           timeout=10).stdout.strip()
            except Exception:
                pass
        try:
            displays = subprocess.run(["system_profiler", "SPDisplaysDataType", "-json"], capture_output=True,
                                      text=True, timeout=60).stdout
            gpus = json.loads(displays).get("SPDisplaysDataType", [])
            info["gpus"] = [{k: g.get(k) for k in ("sppci_model", "sppci_cores", "spdisplays_mtlgpufamilysupport",
                                                   "spdisplays_vendor") if g.get(k)} for g in gpus]
        except Exception as exc:
            info["gpus"] = repr(exc)
    return info


def _app_ffmpeg(app: Path) -> Path:
    for candidate in (app / "Contents/Resources/tools/ffmpeg/bin/ffmpeg",
                      app / "Contents/Frameworks/tools/ffmpeg/bin/ffmpeg",
                      app.parent / "tools/ffmpeg/bin/ffmpeg.exe"):
        if candidate.is_file():
            return candidate
    raise SystemExit(f"No bundled ffmpeg in {app}")


def make_fixture(ffmpeg: Path, out: Path, *, minutes: float, cues: int) -> dict:
    video = out / "工作台效能 测试.mp4"
    seconds = int(minutes * 60)
    started = time.perf_counter()
    with (out / "fixture-ffmpeg.log").open("wb") as log:
        subprocess.run([str(ffmpeg), "-v", "warning", "-f", "lavfi", "-i", f"testsrc2=s=1920x1080:r=30:d={seconds}",
                        "-f", "lavfi", "-i", f"sine=frequency=330:sample_rate=48000:duration={seconds}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-g", "60", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "128k", "-shortest", str(video)],
                       check=True, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    encode_s = time.perf_counter() - started
    from dataclasses import replace
    from twobyteasr.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
                                           default_style, save_project)
    duration_ms = seconds * 1000
    base = default_style()
    styles = [base] + [replace(base, id=f"perf-style-{i}", name=f"效能 {i}", font_size=float(base.font_size) + 6 * i,
                               primary_color=("#F2C14E", "#7FB3D5", "#82E0AA")[i - 1]) for i in (1, 2, 3)]
    speakers = [StudioSpeaker(id=f"S{i:02d}", name=f"说话人 {i + 1}", color=c)
                for i, c in enumerate(("#F2C14E", "#7FB3D5", "#E59866", "#82E0AA"))]
    rows = []
    step = (duration_ms - 4000) / cues
    for index in range(cues):
        start = int(500 + index * step)
        # Every third line overlaps the next speakers (talking over each other) and
        # is long enough (~4 s) to stay grabbable in a 120 s view on a small screen.
        length = int(step * 1.6) + 3000 if index % 3 == 0 else int(step * 0.9) + 400
        text = LINES[index % len(LINES)]
        rows.append(StudioCue(id=f"perf{index:05d}", start_ms=start, end_ms=min(duration_ms - 1, start + length),
                              text=text, speaker_id=speakers[index % 4].id, style_id=styles[index % 4].id))
    project = SubtitleProject(media=StudioMedia(path=str(video.resolve()), display_name=video.name,
                                                duration_ms=duration_ms, width=1920, height=1080),
                              cues=rows, speakers=speakers, styles=styles)
    project.validate()
    path = save_project(project, out / "project.2byteproj")
    return {"video": str(video), "video_bytes": video.stat().st_size, "fixture_encode_s": round(encode_s, 1),
            "minutes": minutes, "cues": cues, "speakers": len(speakers), "styles": len(styles), "project": str(path)}


def run_studio(app: Path, out: Path, *, timeout: int) -> dict:
    parts = [p.casefold() for p in out.parts]
    tmp_index = len(parts) - 1 - parts[::-1].index("tmp")
    invoker = Path(*out.parts[:tmp_index])
    for folder in ("local", "roaming", "temp", "seek"):
        (out / folder).mkdir(exist_ok=True)
    if sys.platform == "win32":
        # Windows baseline: same audit on a private desktop (never the user's).
        env = os.environ.copy()
        env.update(QT_QPA_PLATFORM="windows", PYTHONUTF8="1")
        for key in ("QT_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING", "QT_FONT_DPI"):
            env.pop(key, None)
    else:
        env = {key: os.environ[key] for key in ("HOME", "LANG", "LC_ALL", "TMPDIR", "DISPLAY") if key in os.environ}
        env.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", PYTHONNOUSERSITE="1")
    env.update(TWOBYTEASR_TEST_ROOT=str(out), **{"2BYTEASR_USER_DATA_ROOT": str(out / "local")},
               TWOBYTEASR_INVOKER_CWD=str(invoker), TWOBYTEASR_ACCEPTANCE_DIR=str(out),
               TWOBYTEASR_ACCEPTANCE_SCENARIO="perf-regression", TWOBYTEASR_STARTUP_PROJECT=str(out / "project.2byteproj"),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", TWOBYTEASR_STARTUP_OPEN_STUDIO="1",
               TWOBYTEASR_STARTUP_SIZE=os.environ.get("STUDIO_PERF_SIZE", "1600x950"),
               TWOBYTEASR_SEEK_CACHE_ROOT=str(out / "seek"),
               TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"), PERF_DRAG_REPEATS="5",
               PERF_TIMEOUT_S=str(max(60, timeout - 60)), LOCALAPPDATA=str(out / "local"),
               APPDATA=str(out / "roaming"), TEMP=str(out / "temp"), TMP=str(out / "temp"))
    if app.suffix == ".app":
        command = [str(app / "Contents/MacOS/2ByteASR")]
    elif app.suffix == ".py":
        command = [sys.executable, "-B", str(app)]
    else:
        command = [str(app)]
    started = time.perf_counter()
    if sys.platform == "win32":
        sys.path.insert(0, str(ROOT / "scripts"))
        from isolated_windows_desktop import run_on_desktop
        code = run_on_desktop(command, cwd=invoker, env=env, output=out / "process", timeout=timeout)
    else:
        try:
            with (out / "studio.log").open("wb") as log:
                code = subprocess.run(command, env=env, cwd=invoker, stdout=log, stderr=subprocess.STDOUT,
                                      timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
    wall = time.perf_counter() - started
    path = out / "perf.json"
    perf = json.loads(path.read_text("utf8")) if path.is_file() else {}
    actions = {name: {metric: _dist(values.get(metric, [])) for metric in ("handler_ms", "frame_ms", "idle_ms")}
               for name, values in (perf.get("actions") or {}).items()}
    gestures = {}
    for name, repeats in (perf.get("gestures") or {}).items():
        gestures[name] = {
            "press_frame_ms": _dist([g.get("press_frame_ms") for g in repeats]),
            "move_frame_ms_p95_by_repeat": [(g.get("move_frame_ms") or {}).get("p95") for g in repeats],
            "frame_interval_ms_p95_by_repeat": [(g.get("frame_interval_ms") or {}).get("p95") for g in repeats],
        }
    checks = perf.get("checks") or {}
    return {"exit_code": code, "wall_s": round(wall, 1), "finished": perf.get("finished"),
            "gui_shutdown": perf.get("gui_shutdown"), "open_ready_s": perf.get("open_ready_s"),
            "errors": perf.get("errors"), "failed_checks": [k for k, v in checks.items() if v is False],
            "checks": checks, "actions": actions, "gestures": gestures,
            "gui_stall_stats": perf.get("gui_stall_stats"),
            "passed": code == 0 and bool(perf.get("finished")) and not perf.get("errors")
            and not [k for k, v in checks.items() if v is False]}


def run_export(ffmpeg: Path, out: Path, *, start: float, seconds: float) -> dict:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from twobyteasr.export_timeline import write_export_ass
    from twobyteasr.studio_project import load_project
    from twobyteasr.studio_render import RenderJob, RenderSettings, run_render_job
    from twobyteasr.video_export import capture_video_graph
    export = out / "export"
    export.mkdir()
    project = load_project(out / "project.2byteproj")
    import unicodedata
    sources = [{"path": asset.canonical_source, "exists": os.path.exists(asset.canonical_source),
                "nfc": unicodedata.is_normalized("NFC", asset.canonical_source),
                "nfd": unicodedata.is_normalized("NFD", asset.canonical_source)} for asset in project.media_pool]
    write_export_ass(project, export / "export.ass", fps=30)
    settings = RenderSettings(encoder="auto", quality_mode="crf", quality=20, preset="medium",
                              width=1920, height=1080, fps=30, audio_codec="aac")
    job = RenderJob(project.media.path, str(export / "export.ass"), str(export / "output.mp4"), settings,
                    start_seconds=start, duration_seconds=seconds, video_graph=capture_video_graph(project))
    progress_rows = []
    started = time.perf_counter()
    error = None
    try:
        run_render_job(ffmpeg, job, progress=lambda v: progress_rows.append((round(time.perf_counter() - started, 2), v)))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - started
    output = export / "output.mp4"
    probe = {}
    if output.is_file():
        ffprobe = ffmpeg.with_name("ffprobe")
        try:
            probe = json.loads(subprocess.run([str(ffprobe), "-v", "error", "-show_format", "-show_streams", "-of",
                                               "json", str(output)], capture_output=True, text=True,
                                              timeout=60).stdout)
        except Exception as exc:
            probe = {"error": repr(exc)}
    metadata = dict(job.completion_metadata or {})
    duration = float((probe.get("format") or {}).get("duration") or 0)
    return {"error": error, "media_sources": sources, "wall_s": round(wall, 2), "seconds": seconds,
            "speed_x_realtime": round(seconds / wall, 2) if wall and not error else None,
            "output_duration_s": round(duration, 3), "output_bytes": output.stat().st_size if output.is_file() else 0,
            "encoder": metadata.get("actual_encoder"), "rate_control": metadata.get("actual_rate_control"),
            "completion_metadata": {k: v for k, v in metadata.items() if isinstance(v, (str, int, float, bool))},
            "streams": [{k: s.get(k) for k in ("codec_type", "codec_name", "width", "height", "avg_frame_rate")}
                        for s in probe.get("streams", [])],
            "progress_samples": len(progress_rows),
            "passed": error is None and abs(duration - seconds) < 0.5}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--app", type=Path, required=True,
                        help="installed 2ByteASR.app, the app executable, or quick_start.py (source)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minutes", type=float, default=10)
    parser.add_argument("--cues", type=int, default=1000)
    parser.add_argument("--export-start", type=float, default=120)
    parser.add_argument("--export-seconds", type=float, default=60)
    parser.add_argument("--studio-timeout", type=int, default=1500)
    parser.add_argument("--skip-studio", action="store_true")
    parser.add_argument("--ffmpeg", type=Path, help="default: the app's bundled ffmpeg")
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or "tmp" not in {p.casefold() for p in out.parts}:
        raise SystemExit("Choose a new output folder below a tmp directory")
    out.mkdir(parents=True)
    app = args.app.resolve()
    ffmpeg = args.ffmpeg.resolve() if args.ffmpeg else _app_ffmpeg(app)
    # The export's media check probes in a spawned child that finds ffprobe under
    # the install root; a CI checkout has no tools/ffmpeg, so use the app's (the
    # missing ffprobe was reported as "文件不存在" for the media, 2026-10-14).
    tool_root = ffmpeg.parent.parent.parent.parent
    if (tool_root / "tools" / "ffmpeg" / "bin" / ffmpeg.name) == ffmpeg:
        os.environ["2BYTEASR_INSTALL_ROOT"] = str(tool_root)
    # This process (fixture, export) writes app data only below the output;
    # the app process gets its own isolated profile in run_studio().
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(out / "inproc")
    from twobyteasr.test_isolation import install
    install()
    result = {"machine": _machine(), "app": str(app), "ffmpeg": str(ffmpeg)}

    def save():
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")

    result["fixture"] = make_fixture(ffmpeg, out, minutes=args.minutes, cues=args.cues)
    save()
    if not args.skip_studio:
        result["studio"] = run_studio(app, out, timeout=args.studio_timeout)
        # Diagnostics: the fixture must still be there for the export (2026-10-14).
        video = Path(result["fixture"]["video"])
        result["studio"]["fixture_exists_after"] = video.is_file()
        result["studio"]["output_names_after"] = sorted(p.name for p in out.iterdir())[:40]
        save()
    result["export"] = run_export(ffmpeg, out, start=args.export_start, seconds=args.export_seconds)
    result["passed"] = bool(result["export"]["passed"] and (args.skip_studio or result["studio"]["passed"]))
    save()
    print(json.dumps({"studio": {k: (result.get("studio") or {}).get(k) for k in
                                 ("exit_code", "finished", "failed_checks", "open_ready_s")},
                      "export": {k: result["export"].get(k) for k in ("encoder", "wall_s", "speed_x_realtime", "error")},
                      "passed": result["passed"]}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
