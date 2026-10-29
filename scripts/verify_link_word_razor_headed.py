"""Real-window check of the razor on downloaded YouTube automatic captions (2026-10-26).

Builds a project from a real json3 automatic caption file (``--captions``) over a
generated silent black video of the same length, then runs the in-process
``link-word-razor`` scenario (twobyteasr/acceptance/link_word_razor_audit.py) on a
private Windows desktop with an isolated profile. No network, no paid AI.

    python -X utf8 scripts/verify_link_word_razor_headed.py --captions <file.json3> --output tmp/<new folder>
"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=40)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / "tmp") or out.exists():
        parser.error("Use a fresh directory under repository tmp")
    out.mkdir(parents=True)
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(out)
    from twobyteasr.test_isolation import install
    install()
    length = args.seconds * 1000
    video = out / "black.mp4"
    ffmpeg = ROOT / "tools/ffmpeg/bin/ffmpeg.exe"
    subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"color=c=black:s=640x360:d={args.seconds}", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-t", str(args.seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)],
                   check=True)
    from twobyteasr.media.link_subtitles import parse_subtitles
    from twobyteasr.media.media_ingest import MediaIngestResult
    from twobyteasr.projects.link_import import LinkImportCommand
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    parsed = parse_subtitles(args.captions.read_bytes(), expected_format="json3")
    rows = [dict(start_ms=c.start_ms, end_ms=c.end_ms, text=c.text, events=c.events, anchors=c.anchors,
                 precision=c.precision) for c in parsed.captions if c.end_ms <= length]
    track = dict(track_id="primary", platform="Youtube", video_id="audit", language="en", source="automatic")
    bundle = dict(manifest_path=str(out / "download.2byte-download.json"), media_path=str(video),
                  manifest=dict(task_id="word-razor", platform="Youtube", video_id="audit", source_url="",
                                primary_track_id="primary", translation_track_id="", subtitles=[dict(track=track)]),
                  captions={"primary": dict(parser_version=parsed.parser_version, captions=rows)})
    media = MediaIngestResult(generation=0, project_token="", source_path=str(video), duration_ms=length,
                              has_video=True, has_audio=True, width=640, height=360)
    project = SubtitleProject(media=StudioMedia(path=""))
    project.validate()
    command = LinkImportCommand(project, bundle, media)
    command.redo()
    project_path = save_project(project, out / "words.2byteproj")
    (out / "input.json").write_text(json.dumps(dict(project=str(project_path), captions=str(args.captions),
                                                    imported=command.result.get("cue_count"),
                                                    timing_counts=command.result.get("timing_counts")),
                                               ensure_ascii=False, indent=2), "utf-8")
    env = os.environ.copy()
    for key in ("TWOBYTEASR_STARTUP_OPEN_STUDIO", "TWOBYTEASR_STARTUP_RAISE", "TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE"):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO="link-word-razor", TWOBYTEASR_ACCEPTANCE_DIR=str(out),
               TWOBYTEASR_STARTUP_PROJECT=str(project_path), TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"),
               TWOBYTEASR_SEEK_CACHE_ROOT=str(out / "seek-cache"), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", QT_QPA_PLATFORM="windows", PYTHONUTF8="1",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    from isolated_windows_desktop import run_on_desktop
    command_line = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(ROOT / "quick_start.py")]
    code = run_on_desktop(command_line, cwd=ROOT, env=env, output=out / "process", timeout=600)
    path = out / "result.json"
    result = json.loads(path.read_text("utf-8")) if path.exists() else {}
    summary = dict(output=str(out), exit_code=code, passed=result.get("passed"), shutdown=result.get("gui_shutdown"),
                   checks=[(c["name"], c["passed"]) for c in result.get("checks", [])],
                   error=(result.get("error") or "")[-1500:])
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if code == 0 and result.get("passed") and result.get("gui_shutdown") else 1


if __name__ == "__main__":
    raise SystemExit(main())
