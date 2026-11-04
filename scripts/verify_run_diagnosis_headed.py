"""Real window: 排查原因 on the completion page and in recognition history (2026-10-23).

Prepares task reports in an isolated profile — a failed one (by default the
10-23 user report: SenseVoice, no timeline, Japanese chosen for Chinese audio,
字幕保真检查未通过), a cloud recognition failure and a degraded success — and
runs ``twobyteasr/acceptance/run_diagnosis_audit.py`` inside the real app on a
private desktop. No key comes from the environment; only loopback
connections are allowed; the AI answer comes from a local stand-in.

usage: python scripts/verify_run_diagnosis_headed.py --output tmp/<new dir>
           [--failed-report <report json>] [--degraded-report <report json>]
           [--theme grape|warm] [--language zh|en|ja|...] [--scale 1.75] [--window 1536x824] [--exe <frozen>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

CLOUD_FAILURE = {
    "schema_version": 1, "status": "failed",
    "settings": {"models": {"primary_asr_backend": "api", "firered_asr_backend": "local", "qwen_asr_backend": "off",
                            "qwen_asr_api_provider": "mosi_moss_pro", "polish_provider": "disabled",
                            "group_provider": "disabled"},
                 "switches": {"enable_ai_polish": False, "use_ai_grouping": False}},
    "stages": [{"index": 1, "label": "统一 16k 音频采样时钟", "status": "completed", "elapsed_seconds": 2.1},
               {"index": 2, "label": "在线 ASR API 主力转写（MOSS Pro）", "status": "failed",
                "error": '[2BYTEASR_API_ERROR] {"category": "key", "message": "MOSI 拒绝了这个 API Key（HTTP 401）"} '
                         "MOSI 拒绝了这个 API Key（HTTP 401）：可能填错、已删除，或账户没有该模型权限。"}],
    "events": [], "review_items": [],
    "result": {"elapsed_seconds": 6.0,
               "error": "MOSI 拒绝了这个 API Key（HTTP 401）：可能填错、已删除，或账户没有该模型权限。请到 MOSI 控制台的 API Key 页面重新复制。"},
}


def place_report(report_root: Path, media: Path, job_id: str, report: dict) -> Path:
    """As reporting.py names it; media.path points at this run's (absent) media."""
    report = dict(report)
    report["media"] = dict(report.get("media") or {}, path=str(media), name=media.name)
    report_root.mkdir(parents=True, exist_ok=True)
    path = report_root / f"{media.stem}__{job_id}_1_字幕任务报告.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--failed-report', type=Path,
                        default=ROOT / 'tmp' / 'fidelity-number-hardsplit-20261023' / 'user-log' / '日志文件.txt')
    parser.add_argument('--degraded-report', type=Path,
                        default=ROOT / 'tmp' / 'open-followup-20261020' / 'timing' / 'original-report.json')
    parser.add_argument('--theme', default='grape', choices=('grape', 'warm'))
    parser.add_argument('--language', default='zh')
    parser.add_argument('--scale', default='1', help='Qt scale factor, e.g. 1.75 for a 175%% display')
    parser.add_argument('--window', default='1536x824', help='main window size in logical pixels')
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    for source in (args.failed_report, args.degraded_report):
        if not source.is_file():
            parser.error(f'missing report: {source}')
    output.mkdir(parents=True)
    for key in [key for key in os.environ if re.search(r'(API_?KEY|_TOKEN|ACCESS_?KEY)', key, re.IGNORECASE)]:
        os.environ.pop(key)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.recognition.reporting import REPORT_ROOT
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project

    media_root = output / 'media'
    cases = []
    failed = json.loads(args.failed_report.read_text('utf-8-sig'))
    media = media_root / '2026-10-21 16-39-40.mp4'
    path = place_report(Path(REPORT_ROOT), media, 'diagfailed', failed)
    cases.append(dict(label='fidelity', media=str(media), status='failed', job_id='diagfailed',
                      error=str((failed.get('result') or {}).get('error') or ''), expect_top='fidelity_numbers',
                      report_path=str(path)))
    media = media_root / '云端识别.mp4'
    path = place_report(Path(REPORT_ROOT), media, 'diagcloud', CLOUD_FAILURE)
    cases.append(dict(label='cloud-auth', media=str(media), status='failed', job_id='diagcloud',
                      error=CLOUD_FAILURE['result']['error'], expect_top='cloud_asr_auth', report_path=str(path)))
    degraded = json.loads(args.degraded_report.read_text('utf-8-sig'))
    media = media_root / '部分完成.mp4'
    path = place_report(Path(REPORT_ROOT), media, 'diagpartial', degraded)
    cases.append(dict(label='degraded', media=str(media), status='degraded_success', job_id='diagpartial',
                      report_json_path=str(path), expect_top='primary_incomplete', report_path=str(path)))
    width, height = (int(value) for value in args.window.lower().split('x'))
    (output / 'delivery.json').write_text(json.dumps(dict(cases=cases, theme=args.theme, language=args.language,
                                                          window=[width, height], scale=args.scale),
                                                     ensure_ascii=False, indent=2), 'utf-8')
    entry = save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)), output / 'entry.2byteproj')
    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE',
                'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='run-diagnosis',
               TWOBYTEASR_STARTUP_PROJECT=str(entry), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows', PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    if args.scale != '1':
        env.update(QT_SCALE_FACTOR=args.scale, QT_ENABLE_HIGHDPI_SCALING='0', QT_FONT_DPI='96',
                   QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=420)
    result_path = output / 'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.is_file() else {}
    passed = bool(code == 0 and result.get('passed') and result.get('gui_shutdown'))
    print(json.dumps(dict(passed=passed, exit_code=code, output=str(output), error=result.get('error'),
                          failed=[c['name'] for c in result.get('checks', []) if not c['passed']],
                          checks=len(result.get('checks', []))), ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
