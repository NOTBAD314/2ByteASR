"""Speaker board (2026-11-12, 方案 B) in a real window: 20 speakers, screen pixels.

    python scripts/verify_speaker_board_headed.py --output tmp/speaker-board-headed/sand-100 --theme sand
    QT_SCALE_FACTOR=1.5 python scripts/verify_speaker_board_headed.py --output ... --theme grape

User settings are never touched: LOCALAPPDATA / APPDATA point into the output
folder. Writes PNG screenshots and result.json (checks with pass/fail).
"""
import argparse
import json
import os
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LINES = {  # label: (cues, seconds) like the user's 20-label Filetrans project
    "S00": (7, 11), "S01": (52, 92), "S02": (81, 143), "S03": (2, 3), "S04": (3, 3), "S05": (25, 66),
    "S06": (48, 72), "S07": (14, 24), "S08": (9, 15), "S09": (31, 58), "S10": (4, 6), "S11": (22, 41),
    "S12": (6, 9), "S13": (18, 33), "S14": (11, 19), "S15": (27, 49), "S16": (5, 7), "S17": (16, 28),
    "S18": (12, 21), "S19": (2, 2),
}


def project():
    from twobyteasr.projects.speaker_organization import apply_new_project_policy
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
    from twobyteasr.recognition.speaker_recovery import candidate_snapshot
    from twobyteasr.recognition.speaker_roles import KEY, decide
    rows, clock = [], 0.0
    for round_ in range(81):
        for label, (count, seconds) in LINES.items():
            if round_ < count:
                length = max(0.6, seconds / count)
                rows.append({"speaker": "API_" + label, "start": clock, "end": clock + length,
                             "text": f"{label} 的第 {round_ + 1} 句台词", "utterance_id": len(rows) + 1})
                clock += length + 0.2
    cues = [StudioCue(f"c{i}", round(r["start"] * 1000), round(r["end"] * 1000), r["text"], speaker_id=r["speaker"])
            for i, r in enumerate(rows)]
    result = SubtitleProject(media=StudioMedia("fixture.mp4", duration_ms=int(clock * 1000) + 1000),
                             speakers=[StudioSpeaker("API_" + label, label) for label in LINES], cues=cues)
    snapshot = candidate_snapshot(rows, source="filetrans")
    snapshot["allow_raw_recovery"] = False
    result.generation_metadata["speaker_recovery"] = snapshot
    apply_new_project_policy(result)
    result.studio_state[KEY] = decide(result, manual={}, cap=2)
    return result


def main():
    """Run the real workbench, frozen GUI or unchanged desktop launcher."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--theme', default='sand', choices=('sand', 'grape'))
    parser.add_argument('--scale', default=os.environ.get('QT_SCALE_FACTOR', '1'))
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        parser.error('fresh output under source/tmp required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out / 'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import save_project
    fixture = project()
    media = out / 'fixture.mp4'
    subprocess.run([str(ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-y',
                    '-f', 'lavfi', '-i', 'color=c=0x252131:size=960x540:rate=24:duration=2',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-shortest', str(media)], check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    fixture.media.path = str(media)
    save_project(fixture, out / 'fixture.2byteproj')
    env = dict(os.environ, QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale, QT_FONT_DPI='96',
               TWOBYTEASR_ACCEPTANCE_SCENARIO='speaker-board',
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_THEME=args.theme,
               TWOBYTEASR_STARTUP_PROJECT=str(out / 'fixture.2byteproj'),
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from audit_launch_bridge import run_audit_on_desktop
    code = run_audit_on_desktop(command, cwd=ROOT, env=env, output=out, timeout=240,
                                receipt=out / 'result.json')
    result = json.loads((out / 'result.json').read_text('utf8')) if (out / 'result.json').is_file() else {}
    print(json.dumps(dict(output=str(out), exit=code, passed=result.get('passed'),
                          checks=len(result.get('checks', [])), error=result.get('error')), ensure_ascii=False))
    return 0 if code == 0 and result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
