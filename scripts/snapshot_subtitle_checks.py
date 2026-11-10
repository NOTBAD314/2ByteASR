"""Read one project and save rule-level counts, cue IDs and calibrated totals."""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.source.resolve()))
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output.parent / 'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine
    from twobyteasr.subtitle_rules.current_issues import current_issue_view, invalidate
    from twobyteasr.projects.subtitle_consistency import validate_export_view
    from twobyteasr.timeline.studio_edit_sequence import projected_cues
    from twobyteasr.recognition.transcript_acceptance import pending_ranges
    project = load_project(args.project.resolve())
    engine = SubtitleQCEngine()
    project._qc_result = engine.analyze(project)
    view = current_issue_view(project)
    groups = defaultdict(list)
    for row in project._qc_result.issues:
        groups[(row.issue_type, row.severity.value)].append(row)
    rules = [dict(rule_id=rule, severity=severity, hits=len(rows),
                  unique_cues=len({row.cue_id for row in rows}),
                  cue_ids=sorted({row.cue_id for row in rows}),
                  reasons=list(dict.fromkeys(row.label for row in rows))[:3])
             for (rule, severity), rows in sorted(groups.items())]
    validation = validate_export_view(project, projected_cues(project))
    payload = dict(project_id=project.project_id, cues=len(project.cues), rules=rules,
        rule_hits=sum(row['hits'] for row in rules), actionable=view.counts(),
        actionable_unique_cues=len(view.by_cue), categories=view.statistics(),
        export_errors=len(validation.errors), export_error_cues=len({row.cue_id for row in validation.errors}),
        language_recovery_ranges=len(pending_ranges(project.generation_metadata.get('transcript_acceptance'))))
    project._qc_result = engine.analyze(project)
    invalidate(project)
    repeated = current_issue_view(project)
    payload['repeat_equal'] = repeated.counts() == view.counts() and repeated.records == view.records
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in payload.items() if key not in {'rules', 'categories'}}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
