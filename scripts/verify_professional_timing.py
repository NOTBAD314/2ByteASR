"""Run the production source entry with an isolated profile and real local media."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(output / "profile")
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project
    media = output / "sample.mp4"
    subprocess.run([str(args.ffmpeg.resolve()), "-v", "error", "-ss", "250", "-i", str(args.media.resolve()),
                    "-t", "12", "-vf", "scale=960:-2", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", str(media)], check=True)
    measured_words = [
        dict(text="English", start_ms=2050, end_ms=2500),
        dict(text="timing", start_ms=3100, end_ms=3700),
        dict(text="sample", start_ms=4200, end_ms=4710),
    ]
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=12000, width=960, height=540),
        speakers=[StudioSpeaker("speaker", "Speaker")],
        cues=[StudioCue("sample", 2000, 5000, "English timing sample.", "speaker", evidence_refs=["sample-words"])],
        asr_evidence={"sample-words": {"speaker_id": "speaker", "words": measured_words}})
    project.generation_metadata["language"] = {"code": "en", "requested": "en"}
    fixture = output / "fixture.2byteproj"
    save_project(project, fixture)
    env = dict(os.environ, QT_QPA_PLATFORM="windows", TWOBYTEASR_ACCEPTANCE_SCENARIO="professional-timing",
        TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_STARTUP_PROJECT=str(fixture),
        TWOBYTEASR_INVOKER_CWD=str(args.workspace.resolve()), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1",
        TRANSFORMERS_OFFLINE="1", HF_HUB_OFFLINE="1", PYTHONUTF8="1")
    for key in ("TWOBYTEASR_STARTUP_OPEN_STUDIO", "TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE"):
        env.pop(key, None)
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-X", "utf8", str(ROOT / "quick_start.py")]
    from audit_launch_bridge import run_audit_on_desktop
    return run_audit_on_desktop(command, cwd=ROOT, env=env, output=output, timeout=150,
                               receipt=output / "result.json")


if __name__ == "__main__":
    raise SystemExit(main())
