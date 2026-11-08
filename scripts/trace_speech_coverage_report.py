"""Read task reports without mutating their source files or user cache."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from twobyteasr.recognition.speech_coverage import subtract, union

TARGETS = {
    '82f86c11d1c448f495aa903b0ee81f41': [(7062.900, 7642.933), (16654.283, 17346.683)],
    '19fa7a07b42b4b58b1b3d04c41d27ef4': [(32257.217, 32982.483), (34482.133, 35090.135)],
}


def trace(path):
    report = json.loads(path.read_text('utf-8-sig'))
    events = report.get('events', [])
    execution = next((e for e in events if e.get('event') == 'moss_full_context_execution'), {})
    delivery = next((e for e in reversed(events) if e.get('event') == 'transcript_delivery_counts'), {})
    accepted = union(delivery.get('accepted_ranges', []))
    duration = float(report['result']['audio_seconds'])
    cues = [row for e in events if e.get('event') == 'grouping_trace' for row in e.get('cues', [])]
    selected = next((e for e in events if e.get('event') == 'MODEL_SELECTED' and e.get('model_id') == 'moss'), {})
    gaps = []
    for low, high in TARGETS.get(report['job_id'], []):
        windows = [w for w in execution.get('windows', []) if w['end'] > low and w['start'] < high]
        before = max((r for r in cues if r['end'] <= low), key=lambda r: r['end'], default=None)
        after = min((r for r in cues if r['start'] >= high), key=lambda r: r['start'], default=None)
        gaps.append(dict(start=low, end=high, blank_seconds=round(high-low, 3),
            first_observable_missing_stage='accepted_ranges',
            upstream_first_missing_stage='unknown_without_raw_worker_output',
            accepted_uncovered=subtract([(low, high)], accepted),
            windows=[{k:w.get(k) for k in ('index', 'start', 'end', 'complete', 'end_reason',
                'generated_tokens', 'max_new_tokens', 'truncation_reasons')} for w in windows],
            prior_grouped_cue=before, next_grouped_cue=after,
            speech_evidence='not_available_in_report', missing_speech_seconds=None,
            original_audio_recovered=False))
    return dict(report=str(path.resolve()), job_id=report['job_id'],
        primary_backend=report['settings']['models']['primary_asr_backend'],
        worker=selected.get('worker'), runtime=execution.get('runtime'), device=execution.get('device_name'),
        historical_build_identity='not_recorded', media=report['media'],
        audio_available=Path(report['media']['path']).is_file(), duration=duration,
        complete=execution.get('complete'), window_count=len(execution.get('windows', [])),
        pending_language_ranges=delivery.get('pending_range_count'),
        audio_windows_uncovered=subtract([(0, duration)], [(w['start'], w['end']) for w in execution.get('windows', [])], minimum=.01),
        accepted_gaps_over_five_minutes=subtract([(0, duration)], accepted, minimum=300),
        targets=gaps)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = [trace(p) for p in args.report]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps([dict(job_id=r['job_id'], window_count=r['window_count'],
                          targets=len(r['targets']), audio_available=r['audio_available']) for r in results]))


if __name__ == '__main__':
    main()
