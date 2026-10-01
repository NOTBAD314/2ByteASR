"""One budgeted repair through the application, without exporting credentials."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    p=argparse.ArgumentParser();p.add_argument('trial',type=Path);p.add_argument('candidate');p.add_argument('output',type=Path)
    p.add_argument('--feedback')
    args=p.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('New tmp directory required')
    out.mkdir(parents=True)
    original_store=Path(os.environ['LOCALAPPDATA'])/'2ByteASR/secrets.dat'
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='offscreen')
    from twobyteasr import llm_config
    reader=llm_config._read_secrets
    llm_config._read_secrets=lambda:reader(read_only_path=original_store)
    from twobyteasr.settings import load_runtime_settings
    settings,_,_=load_runtime_settings(args.trial/'config')
    from twobyteasr.ai_design_call_budget import install_acceptance_budget
    install_acceptance_budget(root/'tmp/ai-design-quality-20260916/call-budget.json')
    from twobyteasr.caption_creative_pipeline import retry_saved_candidate
    ledger=next((args.trial/'local/2ByteASR/SubtitleStudioPreview/logs/theme-drafts').rglob('ledger.json'))
    if args.feedback:
        from twobyteasr.authored_visual_revision import revise_candidate
        result=revise_candidate(ledger,args.candidate,args.feedback,settings,ledger_root=out/'creative',request_id=out.name)
    else:result=retry_saved_candidate(ledger,args.candidate,settings,ledger_root=out/'creative',request_id=out.name)
    (out/'result.json').write_text(json.dumps(dict(concepts=[dict(id=c['id'],technical_status=c.get('technical_status','passed'),
        technical_errors=c.get('technical_errors',[])) for c in result.concepts]),ensure_ascii=False,indent=2),'utf8')
    print(json.dumps([dict(id=c['id'],status=c.get('technical_status','passed')) for c in result.concepts]))


if __name__=='__main__':main()
