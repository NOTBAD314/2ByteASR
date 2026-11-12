"""Read-only QC snapshot for the fixed handoff regression project."""
from pathlib import Path
import argparse
import json
from collections import Counter
from dataclasses import asdict


def snapshot(project_path, output, prepare=False):
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine, terminology_from_project
    from twobyteasr.subtitle_rules.current_issues import current_issue_view
    from twobyteasr.recognition.asr_source_evidence import cue_source_hypotheses
    project = load_project(project_path)
    if prepare:
        from twobyteasr.projects.project_open_preparation import prepare as prepare_project
        prepare_project(project)
    project._qc_result = SubtitleQCEngine().analyze(project, terminology=terminology_from_project(project))
    view = current_issue_view(project)
    cues = {c.id: c for c in project.cues}
    evidence = {}
    for key, cue in cues.items():
        evidence[key] = cue_source_hypotheses(project, cue)
    active = [r for r in view.records if r.disposition == 'actionable']
    payload = dict(project_id=project.project_id, cue_count=len(cues), counts=view.counts(),
        actionable_cues=len({r.cue_id for r in active}), actionable_issues=len(active),
        rules=view.statistics(), raw_rules=project._qc_result.rule_statistics(),
        records=[dict(asdict(r), action=r.action, evidence=evidence[r.cue_id]) for r in view.records],
        raw=[r.to_dict() for r in project._qc_result.issues],
        separate_project_records={k: v for k, v in project.generation_metadata.items()
                                  if k in {'speech_coverage', 'speaker_identity', 'speaker_identity_stages'}})
    for record in payload['records']:
        raw=[r for r in project._qc_result.for_cue(record['cue_id']) if r.issue_type==record['kind']]
        record['rule_id']=record['kind']
        record['effective_evidence']=[e.to_dict() for r in raw for e in r.evidence]
        record['effective_scope']=[r.fix_metadata.get('evidence_scope') for r in raw if r.fix_metadata.get('evidence_scope')]
    Path(output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: payload[k] for k in ('cue_count','counts','actionable_cues','actionable_issues','rules')},ensure_ascii=False))
    return project


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('project')
    parser.add_argument('output')
    parser.add_argument('--prepare',action='store_true')
    args = parser.parse_args()
    snapshot(args.project, args.output,args.prepare)
