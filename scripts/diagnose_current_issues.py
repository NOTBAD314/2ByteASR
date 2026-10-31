"""Explain old risk groups and current actionable issues without editing input."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-qc',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        parser.error('Fresh repository tmp directory required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install;install()
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine,terminology_from_project
    from twobyteasr.subtitle_rules.studio_review import review_risks_from_qc
    from twobyteasr.subtitle_rules.current_issues import current_issue_view
    raw=args.project.read_bytes();p=load_project(args.project)
    p._qc_result=SubtitleQCEngine().analyze(p,terminology=terminology_from_project(p))
    old=review_risks_from_qc(p._qc_result);view=current_issue_view(p)
    baseline=json.loads(args.baseline_qc.read_text(encoding='utf8')) if args.baseline_qc else None
    if baseline:
        assert baseline['project_id']==p.project_id and baseline['cues']==len(p.cues)
    old_levels={key:row['level'] for key,row in baseline['risks'].items()} if baseline else {key:row.level for key,row in old.items()}
    old_suggested={key for key,level in old_levels.items() if level=='suggested'}
    old_critical={key for key,level in old_levels.items() if level=='high'}
    raw_rows=baseline['issues'] if baseline else [r.to_dict() for r in p._qc_result.issues]
    reasons=defaultdict(list)
    for issue in raw_rows:reasons[issue['issue_type']].append(issue)
    input_stats={kind:dict(raw=len(rows),unique_cues=len({r['cue_id'] for r in rows}),
        duplicate_ids=len(rows)-len({r['id'] for r in rows}),
        old_suggested_records=sum(r['cue_id'] in old_suggested for r in rows),
        old_suggested_unique=len({r['cue_id'] for r in rows if r['cue_id'] in old_suggested}))
        for kind,rows in reasons.items()}
    examples=[]
    cues={c.id:c for c in p.cues}
    for key in ('1','27','42','65','182','333','544','811','818','872'):
        cue=cues.get(key)
        if cue is None:continue
        examples.append(dict(cue=key,text=cue.text,start_ms=cue.start_ms,end_ms=cue.end_ms,speaker=cue.speaker_id,
            old_level=old_levels[key],new_level=view.level(key),
            current=[asdict(r) for r in view.for_cue(key)],
            diagnostics=[asdict(r) for r in view.diagnostics.get(key,())]))
    summary=dict(project_id=p.project_id,sha256=hashlib.sha256(raw).hexdigest(),originals=len(p.cues),
        translations=len(p.generation_metadata.get('translations',{})),
        old_counts=dict(suggested=len(old_suggested),critical=len(old_critical),
                        priority_filter_members=len(old_suggested|old_critical)),
        old_suggested_reclassified=dict(Counter(view.level(k) for k in old_suggested)),
        old_critical_reclassified=dict(Counter(view.level(k) for k in old_critical)),
        raw_source_rules=input_stats,current_rules=view.statistics(),new_counts=view.counts(),
        final_unique_groups=len(view.levels),final_issue_count=sum(len(v)for v in view.by_cue.values()),
        dispositions=dict(Counter(r.disposition for r in view.records)),
        examples=examples,original_unchanged=args.project.read_bytes()==raw)
    (out/'classification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'current-records.json').write_text(json.dumps([asdict(r)for r in view.records],ensure_ascii=False,indent=2),encoding='utf8')
    (out/'raw-qc.json').write_text(json.dumps(raw_rows,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:summary[k]for k in ('old_counts','old_suggested_reclassified','new_counts','final_unique_groups','final_issue_count','dispositions','original_unchanged')},ensure_ascii=False))

if __name__=='__main__':main()
