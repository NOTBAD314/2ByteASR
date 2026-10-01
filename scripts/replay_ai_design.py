"""Replay a saved AI response without contacting a provider; optionally render it."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def replay(source: Path, output: Path, *, render=False, text=None):
    from twobyteasr.caption_creative_pipeline import ThemeLedger,accept_authored_set,canonical,VERSION
    from twobyteasr.authored_repair import collect_issues
    from twobyteasr.web_theme_compiler import parse_object
    output.mkdir(parents=True,exist_ok=True)
    prior=json.loads(source.read_text('utf8'))
    raw_path=source.parent/'provider-original.txt'
    raw=raw_path.read_text('utf8')
    payload=parse_object(raw)
    ledger=ThemeLedger(output/'creative',prior['raw_user_prompt'])
    origin=prior.get('raw_response',{})
    ledger.raw_response(raw,origin.get('provider','unknown'),origin.get('model','unknown'))
    ledger.value['replay_origin']={'ledger':str(source.resolve()),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                                 'new_provider_calls':0}
    issues=collect_issues(payload,ledger)
    result=accept_authored_set(payload,ledger,origin.get('provider','unknown'),origin.get('model','unknown'),allow_partial=True)
    (output/'normalized.json').write_text(canonical(payload),'utf8')
    (output/'concepts.json').write_text(json.dumps(result.concepts,ensure_ascii=False,indent=2),'utf8')
    report={'version':VERSION,'source_sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'new_provider_calls':0,'issues':issues,'candidates':[]}
    sample=text if text is not None else prior.get('creative_context',{}).get('subtitle_text','真实字幕 ABC 123')
    for c in result.concepts:
        row={'id':c['id'],'name':c['name'],'technical':c.get('technical_status','passed')}
        report['candidates'].append(row)
        if row['technical']=='failed' or not render:continue
        from twobyteasr.renderer_service import RendererService
        from twobyteasr.web_theme import theme_archive_html
        from twobyteasr.theme_direction_preview import render_motion_preview
        from PIL import Image
        started=time.monotonic();service=RendererService()
        try:
            html=theme_archive_html(c['authored_theme'],sample_text=sample,duration_seconds=6,auto_replay=False)
            folder=output/c['id'];folder.mkdir(exist_ok=True)
            (folder/'theme.html').write_text(html,'utf8')
            service.live_set(html,width=1920,height=1080)
            frames=[]
            for ms in (0,360,1500,3500,5750,6000,6100):
                path=folder/f'{ms}.png';path.write_bytes(service.live_pause(cue_ms=ms,stage_ms=ms));frames.append(path)
            bitmap=Image.open(folder/'1500.png').convert('RGBA');box=bitmap.getchannel('A').getbbox()
            if box:
                detail=folder/'detail.png';bitmap.crop(box).save(detail);frames.append(detail)
            motion=render_motion_preview(service,html,folder,c['id'])
            frames.extend([Path(motion['video']),Path(motion['gif'])])
            ledger.record_preview(c['id'],frames)
            c['motion_preview']=motion
            row.update(render='passed',seconds=round(time.monotonic()-started,3),motion=motion,
                       detail_bounds=box,semantic_review='not_run')
        except Exception as exc:row.update(render='failed',error=str(exc),seconds=round(time.monotonic()-started,3))
        finally:service.shutdown()
        (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    (output/'concepts.json').write_text(json.dumps(result.concepts,ensure_ascii=False,indent=2),'utf8')
    (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--render',action='store_true');parser.add_argument('--text')
    args=parser.parse_args()
    report=replay(args.ledger,args.output,render=args.render,text=args.text)
    print(json.dumps([{k:v for k,v in r.items() if k!='motion'} for r in report['candidates']],ensure_ascii=False,indent=2))
    sys.exit(0 if all(r['technical']=='passed' and r.get('render','passed')=='passed' for r in report['candidates']) else 1)
