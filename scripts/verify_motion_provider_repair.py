"""One real provider repair of a fully synthetic numeric-boundary fixture.

This is a provider repair integration check, not the normal UI generation gate.
Only validator paths, numeric values and ranges leave this process.
"""
import copy,json,os
from pathlib import Path
import shutil,sys,uuid

def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('fresh tmp required')
    out.mkdir(parents=True)
    from twobyteasr import settings as sm
    from twobyteasr.llm_config import activate_ai_service,update_active_profile
    local=Path(os.environ['LOCALAPPDATA'])/'2ByteASR'
    settings,_=sm._merge_known_settings(sm.DEFAULT_SETTINGS,json.loads((local/sm.SETTINGS_FILENAME).read_text('utf8')))
    activate_ai_service(settings,'deepseek');update_active_profile(settings,model='deepseek-v4-pro')
    secret=out/'local/2ByteASR/secrets.dat';secret.parent.mkdir(parents=True)
    if (local/'secrets.dat').is_file():shutil.copyfile(local/'secrets.dat',secret)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'))
    from scripts.author_balatro_candidates import candidates
    from twobyteasr.caption_creative_pipeline import ThemeLedger,accept_authored_set,canonical
    from twobyteasr.provider_service import GLOBAL_PROVIDER_SERVICE
    rows=candidates();rows[0]['generated_source']['motionSpec']['tracks'][0]['from']['rotationY']=121
    rows[0]['generated_source']['motionSpec']['tracks'][0]['to']['rotationY']=0
    before=copy.deepcopy(rows);ledger=ThemeLedger(out/'ledger','Balatro synthetic repair integration')
    client=GLOBAL_PROVIDER_SERVICE.client_for_stage(settings,'polish');calls=[];parent=uuid.uuid4().hex
    def repair(issues,repair_id,schema):
        calls.append(repair_id)
        from twobyteasr.motion_spec_repair import request_motion_patch
        return request_motion_patch(client,issues,repair_id,schema,parent_request_id=parent)
    result=accept_authored_set({'candidates':rows},ledger,'deepseek','deepseek-v4-pro',motion_repair=repair,request_id=parent)
    record=dict(passed=len(calls)==1 and rows==before and len(result.concepts)==3,
                real_provider=True,normal_ui_generation=False,synthetic_fixture=True,calls=calls,
                parent_request_id=parent,receipts=ledger.value['motion_repairs'])
    (out/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(record,ensure_ascii=False));return 0 if record['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
