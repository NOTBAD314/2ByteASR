"""Continue a copied source checkpoint through production collection, no model calls."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--direct-public',action='store_true')
    args=p.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Fresh tmp output required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    import subtitle_core as legacy
    from twobyteasr import glossary_build as gb
    from twobyteasr.settings import DEFAULT_SETTINGS
    from twobyteasr.llm_config import activate_ai_service
    import copy
    settings=copy.deepcopy(DEFAULT_SETTINGS);activate_ai_service(settings,'antigravity')
    settings['models'].update(glossary_enrich_names=False,glossary_include_community=False,
        glossary_include_wordlists=False,glossary_task_budget_seconds=240)
    def forbidden(*a,**kw):raise AssertionError('This audit authorizes public HTTP only, no model request')
    gb._structured_call=forbidden
    # This option is only used by the explicitly authorized unsandboxed run.
    if args.direct_public:
        import requests
        session=requests.Session();session.trust_env=False
        requests.get=session.get
    checkpoint=json.loads(args.checkpoint.read_text('utf8'))
    events=[]
    def report(stage,note,counters):
        events.append(dict(stage=stage,note=note,**counters))
        (out/'progress.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),'utf8')
        print(stage,note,flush=True)
    result=gb.run_full_library_update(legacy,checkpoint['game'],settings,resume=checkpoint,report=report,
        checkpoint_writer=lambda data:(out/'checkpoint.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8'))
    result['diffs']=[asdict(d) for d in result['diffs']]
    result['model_calls']=0
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(candidates=result['candidate_count'],seconds=result['elapsed_seconds'],
        stats=result['build_stats'].get('category_counts'),model_calls=0),ensure_ascii=False))


if __name__=='__main__':main()
