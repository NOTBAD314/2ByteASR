"""Acceptance: MOSS recognition of long audio through the real queue (2026-10-13).

Runs ``service.run_media_queue`` with MOSS as the primary recognizer on one
media file, with isolated user data and no network services (timeline and text
review off, AI switches off), then reads the run's own report: the window
plan, each window's span and peak memory, the stitched speakers, review items
and the saved project. ``--max-window`` sets TWOBYTEASR_MOSS_MAX_WINDOW_SECONDS
to exercise windows on a shorter file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('media')
    parser.add_argument('--out', required=True)
    parser.add_argument('--max-window', default='')
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if 'tmp' not in {part.lower() for part in out.parts}:
        raise SystemExit('--out must be under a tmp directory')
    out.mkdir(parents=True, exist_ok=True)
    user_data = out / 'user-data'
    user_data.mkdir(exist_ok=True)
    os.environ.update({'2BYTEASR_USER_DATA_ROOT': str(user_data), 'LOCALAPPDATA': str(user_data),
                       '2BYTEASR_MODEL_ROOT': str(ROOT / 'models'), 'PYTHONIOENCODING': 'utf-8',
                       'QT_QPA_PLATFORM': os.environ.get('QT_QPA_PLATFORM', 'offscreen')})
    if args.max_window:
        os.environ['TWOBYTEASR_MOSS_MAX_WINDOW_SECONDS'] = args.max_window
    sys.path.insert(0, str(ROOT))
    import subtitle_core as legacy
    models = legacy.RUNTIME_SETTINGS.setdefault('models', {})
    switches = legacy.RUNTIME_SETTINGS.setdefault('switches', {})
    models.update(primary_asr_backend='moss', firered_asr_backend='off', qwen_asr_backend='off')
    switches.update(enable_ai_polish=False, use_ai_grouping=False, unified_glm_processing=False,
                    enable_qwen_asr_reference=False)
    legacy.configure_runtime_asr(models)
    from twobyteasr.service import RunOptions, run_media_queue
    from twobyteasr.speaker_strategy import resolve
    options = RunOptions(settings_snapshot_json=json.dumps(legacy.RUNTIME_SETTINGS, ensure_ascii=False),
                         speaker_source=resolve(legacy.RUNTIME_SETTINGS), recognition_language='zh')
    started = time.perf_counter()
    result = run_media_queue([str(Path(args.media).resolve())], options, event_sink=lambda event: None)
    elapsed = time.perf_counter() - started
    media = result.results[0]
    receipt = {'media': str(args.media), 'max_window': args.max_window or None, 'elapsed_s': round(elapsed, 1),
               'exit_code': result.exit_code, 'status': media.status, 'error': media.error}
    report = None
    txt = Path(str(media.txt_path or ''))
    candidates = sorted(txt.parent.glob('*任务报告.json')) if txt.parent.is_dir() else []
    candidates += sorted(user_data.rglob('*任务报告.json'))
    if candidates:
        report = json.loads(candidates[-1].read_text(encoding='utf-8'))
        text_report = candidates[-1].with_suffix('.txt')
        if text_report.is_file():
            receipt['report_lines'] = [line for line in text_report.read_text(encoding='utf-8').splitlines()
                                       if line.startswith(('素材时长', '- MOSS 分段', '状态', '处理结果'))]
    if isinstance(report, dict):
        execution = report.get('moss_execution') or {}
        plan = execution.get('window_plan') or {}
        receipt['window_plan'] = {key: plan.get(key) for key in ('mode', 'count', 'max_window_seconds',
                                                                 'max_window_override', 'usable_bytes')}
        receipt['windows'] = [{key: row.get(key) for key in ('index', 'start', 'end', 'input_tokens', 'generated_tokens',
                                                            'end_reason', 'peak_allocated_gb', 'segments')}
                              for row in execution.get('windows') or []]
        receipt['retries'] = execution.get('retries')
        receipt['complete'] = execution.get('complete')
        merged = [row for row in report.get('events') or [] if row.get('event') == 'moss_windows_merged']
        if merged:
            receipt['speaker_maps'] = merged[-1].get('speaker_maps')
            receipt['speaker_voice_scores'] = merged[-1].get('speaker_voice_scores')
        receipt['review_titles'] = sorted({str(item.get('title') or item.get('category') or '') for item in
                                           report.get('review_items') or []})
    project = getattr(media, 'project_path', '') or ''
    if not project and media.result_ref_json:
        project = json.loads(media.result_ref_json).get('project_path', '')
    if project and Path(project).is_file():
        from twobyteasr.studio_project import load_project
        loaded = load_project(project)
        cues = list(loaded.cues)
        receipt['project'] = {'path': project, 'cues': len(cues),
                              'speakers': sorted({cue.speaker_id for cue in cues}),
                              'last_cue_end_s': max((cue.end_ms for cue in cues), default=0) / 1000}
    (out / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if result.exit_code == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
