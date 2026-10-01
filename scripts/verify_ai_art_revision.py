"""One real model art revision, preserving the prior version and peer candidates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings',type=Path,required=True)
    parser.add_argument('--ledger',type=Path,required=True);parser.add_argument('--candidate',required=True)
    parser.add_argument('--feedback',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--call-budget',type=int,default=4);parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--review-with-agy',action='store_true')
    parser.add_argument('--saved-response',type=Path,help='Replay an immutable prior response; only subsequent technical repairs may call the provider')
    parser.add_argument('--saved-envelope-response',type=Path,help='Replay the already returned metadata syntax repair too')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():raise ValueError('Use a fresh repository tmp directory')
    out.mkdir(parents=True)
    from twobyteasr.settings import DEFAULT_SETTINGS,_merge_known_settings
    from twobyteasr.llm_config import endpoint_from_settings
    from twobyteasr.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.provider_service import GLOBAL_PROVIDER_SERVICE
    from twobyteasr.authored_visual_revision import redesign_candidate
    from twobyteasr.caption_creative_pipeline import ThemeLedger
    from twobyteasr.authored_preview import render_candidate_preview
    raw=args.settings.read_bytes();settings,_=_merge_known_settings(DEFAULT_SETTINGS,json.loads(raw))
    selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
    endpoint=endpoint_from_settings(settings,'polish')
    for key in ('polish_api_key','group_api_key'):settings['models'][key]=endpoint.get('api_key','')
    for key,value in [('LOCALAPPDATA','local'),('APPDATA','roaming'),('TMP','temp'),('TEMP','temp')]:
        (out/value).mkdir(exist_ok=True);os.environ[key]=str(out/value)
    settings['models']['ai_design_wait_mode']='configured';settings['models']['ai_design_cli_timeout_seconds']=1200
    prior=ThemeLedger.open(args.ledger)
    record=dict(status='running',provider=selection.provider,model=selection.model,candidate=args.candidate,
        previous_ledger=str(args.ledger.resolve()),settings_sha256=hashlib.sha256(raw).hexdigest(),
        calls=0,call_budget=args.call_budget,kind='model_art_revision')
    replay=args.saved_response.read_text('utf8') if args.saved_response else None
    envelope=args.saved_envelope_response.read_text('utf8') if args.saved_envelope_response else None
    if envelope is not None:record['envelope_replay']=dict(path=str(args.saved_envelope_response.resolve()),sha256=hashlib.sha256(args.saved_envelope_response.read_bytes()).hexdigest())
    if replay is not None:
        record.update(kind='saved_model_art_revision_replay',replay=dict(path=str(args.saved_response.resolve()),
            sha256=hashlib.sha256(args.saved_response.read_bytes()).hexdigest()))
        (out/'replayed-original.txt').write_text(replay,'utf8')
    def save():(out/'trial.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf8')
    factory=GLOBAL_PROVIDER_SERVICE.client_for_stage
    class Prepared(Exception):pass
    def client_for_stage(*a,**kw):
        client=factory(*a,**kw);complete=client.complete
        def bounded(messages,**options):
            nonlocal replay,envelope
            if replay is not None:
                value=replay;replay=None;return value
            if envelope is not None and options.get('input_scope',{}).get('kind')=='one_candidate_metadata_syntax':
                value=envelope;envelope=None;return value
            if args.prepare_only:
                (out/'external-request-preview.json').write_text(json.dumps(dict(destination=endpoint.get('base_url'),
                    provider=selection.provider,model=selection.model,messages=messages,schema=options.get('json_schema')),
                    ensure_ascii=False,indent=2),'utf8')
                raise Prepared('Exact request prepared; no network call')
            if record['calls']>=args.call_budget:raise ValueError('美术版本调用预算已用尽')
            record['calls']+=1;save();return complete(messages,**options)
        client.complete=bounded;return client
    GLOBAL_PROVIDER_SERVICE.client_for_stage=client_for_stage
    started=time.monotonic();save()
    try:
        result=redesign_candidate(args.ledger,args.candidate,args.feedback.read_text('utf8'),settings,
            ledger_root=out/'version',request_id=out.name,revision_kind='art_revision')
        if args.saved_response:
            version=ThemeLedger.open(out/'version/ledger.json');version.value['replayed_model_response']=record['replay'];version.save()
        concept=next(c for c in result.concepts if c['id']==args.candidate)
        (out/'concept.json').write_text(json.dumps(concept,ensure_ascii=False,indent=2),'utf8')
        (out/'theme.json').write_text(json.dumps(concept['authored_theme'],ensure_ascii=False,indent=2),'utf8')
        reviewer=None
        if args.review_with_agy:
            from review_theme_keyframes import agy_review
            reviewer=lambda proof:agy_review(proof,out/'agy-review')
        receipt=render_candidate_preview(concept,out/'preview',prior.value['creative_context']['subtitle_text'],
            keyframe_review=reviewer)
        record.update(status='rendered',preview=receipt['full_frame'],motion=receipt['motion']['video'],
            semantic_review=receipt.get('semantic_review','not_run'),source_hash=receipt['source_hash'])
    except Prepared:record['status']='prepared'
    except Exception as exc:record.update(status='failed',error=str(exc)[:1500],category=getattr(exc,'category','art_revision_error'))
    finally:record.update(elapsed_seconds=time.monotonic()-started,settings_unchanged=args.settings.read_bytes()==raw);save()
    print(json.dumps(record,ensure_ascii=False,indent=2));return 0 if record['status'] in {'prepared','rendered'} else 1


if __name__=='__main__':sys.exit(main())
