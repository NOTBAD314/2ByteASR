"""User-authorized Grok 4.6 design stages; necessary text/brief only."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--resume',type=Path);parser.add_argument('--selected')
    args=parser.parse_args()
    out=root/'tmp/visible-playback-v2/provider'/time.strftime('%Y%m%d-%H%M%S');out.mkdir(parents=True)
    settings=json.loads((root/'2byteasr_settings.json').read_text('utf8'))
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),TMP=str(out/'temp'),TEMP=str(out/'temp'),QT_QPA_PLATFORM='offscreen')
    (out/'temp').mkdir()
    from twobyteasr.llm_config import activate_ai_service,update_active_profile
    activate_ai_service(settings,'grok_account');update_active_profile(settings,model='grok-4.6')
    from twobyteasr.provider_registry import GLOBAL_PROVIDER_REGISTRY
    selected=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
    assert selected.model=='grok-4.6',selected.model
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue
    project=SubtitleProject(media=StudioMedia(path='',width=1920,height=1080,duration_ms=3000),
        cues=[StudioCue('design-cue',0,3000,'啊感觉他就是你看')])
    instruction='为中文游戏实况设计北极熊滑雪主题字幕：圆润白熊戴滑雪镜，文字优先，字幕附近一处主符号。透明画布，默认底部安全区。不要普通黑条、廉价霓虹、emoji、随机装饰或密集粒子。字体、绒毛/冰晶/镜片材质和动作统一，入场有主题语义，保持克制、出场干净。给出三个构图、字体、符号和材质真正不同的方向供人选择。'
    design=json.loads(args.resume.read_text('utf8')) if args.resume else None
    if design and args.selected:design['selected_concept_id']=args.selected
    payload=dict(text=project.cues[0].text,instruction=instruction,scope='subtitle',model=selected.model,
                 selected_concept_id=design.get('selected_concept_id') if design else None)
    (out/'necessary-input.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    def event(value):
        with (out/'stages.jsonl').open('a',encoding='utf8') as stream:stream.write(json.dumps(value,ensure_ascii=False,default=str)+'\n')
        if value.get('design'):(out/'design-checkpoint.json').write_text(json.dumps(value['design'],ensure_ascii=False,indent=2),encoding='utf8')
    from twobyteasr.studio_ai import request_web_theme_design
    print('EVIDENCE',out,flush=True)
    start=time.monotonic()
    try:
        result=request_web_theme_design(project,'design-cue',instruction,settings,concepts_only=not bool(args.selected),
            resume_design=design,stage_event_callback=event,stage_callback=lambda text:print(text,flush=True))
        data=asdict(result)
        (out/'result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
        if result.source=='concepts':
            design=dict(schema_version=2,brief=result.brief,concepts=result.concepts,selected_concept_id='')
            (out/'art-direction.json').write_text(json.dumps(design,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(dict(source=result.source,seconds=time.monotonic()-start,concepts=[c['name'] for c in result.concepts],theme=result.theme.get('name')),ensure_ascii=False),flush=True)
    except Exception as exc:
        (out/'failure.json').write_text(json.dumps(dict(error=str(exc),category=getattr(exc,'category',''),seconds=time.monotonic()-start,
            trace=getattr(exc,'trace_path','')),ensure_ascii=False,indent=2),encoding='utf8')
        raise


if __name__=='__main__':main()
