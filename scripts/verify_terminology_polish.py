"""Normal GUI -> real configured Grok search/polish -> saved project reopening.

ASR output is synthetic; recognition models and audio upload are not exercised.
Uses the already authorized failing task's grok_account/grok-4.6 profile in an
isolated settings copy. No credential is read, copied, or changed.
"""
from __future__ import annotations
import argparse
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--run-prepared',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp'):raise ValueError('Output must be under repository tmp')
    if not args.run_prepared and out.exists():raise ValueError('Use a fresh output directory')
    out.mkdir(parents=True,exist_ok=args.run_prepared)
    if args.run_prepared and (out/'run-result.json').is_file():
        import shutil
        attempts=out/'attempts';attempts.mkdir(exist_ok=True)
        archived=attempts/f'run-{len(list(attempts.iterdir()))+1:03d}';archived.mkdir()
        for name in ('run-result.json','run-process.log','result.json','completion-qt.png','enabled-glossary-qt.png',
                     'input-scope.json','task-states.json','polished-rows.json'):
            if (out/name).is_file():shutil.copy2(out/name,archived/name)
    source=Path(os.environ['LOCALAPPDATA'])/'2ByteASR'/'2byteasr_settings.json'
    original=source.read_bytes()
    env=os.environ.copy()
    env.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),TEMP=str(out/'temp'),TMP=str(out/'temp'),
        PYTHONUTF8='1',PYTHONIOENCODING='utf-8',QT_QPA_PLATFORM='windows',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='terminology-polish',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'))
    for name in ('local','roaming','temp','config'):(out/name).mkdir(exist_ok=True)
    os.environ.update({k:env[k] for k in ('LOCALAPPDATA','APPDATA','TEMP','TMP')})
    from twobyteasr import settings as settings_module
    from twobyteasr.llm_config import activate_ai_service,update_active_profile
    from twobyteasr.processes import run_hidden_subprocess
    from twobyteasr.models import SpeechSegment
    if not args.run_prepared:
        settings,_=settings_module._merge_known_settings(settings_module.DEFAULT_SETTINGS,json.loads(original))
        settings=copy.deepcopy(settings)
        activate_ai_service(settings,'grok_account');update_active_profile(settings,model='grok-4.6')
        def clear(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    if any(part in k.lower() for part in ('api_key','access_token','refresh_token')):value[k]=''
                    else:clear(v)
            elif isinstance(value,list):
                for item in value:clear(item)
        clear(settings)
        settings['glossary'].update(content_name='原神',enable_domain_terms=False,enabled_glossary_ids=[])
        settings['cache'].update(force_refresh_polish=False,force_refresh_group=False)
        settings['performance'].update(cloud_batch_workers=4,parallel_cloud_batches=True)
        settings['switches'].update(enable_qwen_asr_reference=False,use_ai_grouping=False,
            output_jianying_txt=False,output_speaker_tracks=False,unified_glm_processing=False)
        settings_module.save_runtime_settings(settings,out/'config')
        names=['阿雷奇诺','洛琪娜','枫原万叶','艾尔海森','神里绫华','珊瑚宫心海','雷电将军','迪卢克',
               '凯亚','丽莎','琴','温迪','可莉','莫娜','迪奥娜','砂糖','班尼特','菲谢尔','诺艾尔','雷泽',
               '钟离','甘雨','刻晴','凝光','北斗','行秋','重云','香菱','辛焱','七七','胡桃','魈',
               '烟绯','云堇','申鹤','夜兰','瑶瑶','神里绫人','宵宫','早柚','九条裟罗','荒泷一斗',
               '五郎','八重神子','久岐忍','鹿野院平藏','纳西妲','提纳里']
        observations=['开元素战技后再切换角色','先观察敌人移动再决定方向','等队友讲完再说明配装思路',
            '沿山路走到河边采集材料','把未确认的情报留到后面讨论','比较两种队伍的出招顺序',
            '记录护盾持续时间和体力消耗','看看地图标记有没有遗漏']
        fillers=['我们这次一起看原神前瞻，屏幕上的演示还没有结束，先把目前能看清的动作记下来。',
            '我觉得这段讨论需要结合实际游戏画面，口头叫法可能不准确，所以听不清的名字先保留。',
            '队友刚才提到了武器和圣遗物，不过这只是玩家自己的体验，不代表已经确定的官方结论。',
            '接着沿着任务指引往前走，遇到新的机制先观察提示，然后再讨论怎样安排下一轮操作。']
        rows=[]
        for i in range(96):
            name=names[i%len(names)]
            opening=(f'本段讨论{name}，我们先{observations[i%8]}。')
            if i in (1,49):opening='我刚才听到玩家昵称洛琪娜，但没有任何官方资料可以确认这是不是角色名。'
            text=opening+''.join(fillers[(i+j)%4] for j in range(7))
            text=text[:298-len(str(i+1))]+str(i+1)
            # Bounded read-only ASR neighbors, matching production evidence density.
            context='只读邻句：'+''.join(fillers[(i+j)%4] for j in range(3))[:130]
            reference=text.replace('阿雷奇诺','阿蕾奇诺')
            rows.append(SpeechSegment(i+1,i*30,(i+1)*30-.1,text,.88,[],speaker='S01' if i%2==0 else 'S02',
                moss_text=text,moss_context=context,firered_text=reference,qwen_asr_text=reference,qwen_asr_context=context,
                reference_consensus=.95))
        (out/'synthetic-asr.json').write_text(json.dumps([asdict(x) for x in rows],ensure_ascii=False,indent=2),'utf8')
        media=out/'synthetic.mp4'
        run_hidden_subprocess([root/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-f','lavfi','-i',
            'color=c=0x18212a:s=320x180:r=1','-t','2880','-c:v','libx264','-preset','ultrafast',
            '-pix_fmt','yuv420p','-an',media],check=True,timeout=90,capture_output=True,purpose='one small synthetic ASR audit media')
        from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioSpeaker,save_project,hydrate_media_contract
        from twobyteasr.studio_helpers import probe_media_identity
        project=SubtitleProject(media=StudioMedia(str(media),duration_ms=2880000,width=320,height=180),
            speakers=[StudioSpeaker('S01'),StudioSpeaker('S02')],cues=[])
        hydrate_media_contract(project,probe_media_identity(str(media)))
        save_project(project,out/'fixture.2byteproj')
        (out/'prepared.json').write_text(json.dumps(dict(source_settings_sha256=hashlib.sha256(original).hexdigest(),
            configured_profile='grok_account',model='grok-4.6',original_settings_changed=False,
            synthetic=True,source_cues=96,outer_batches=6,video_bytes=media.stat().st_size,
            credentials_copied=False),indent=2),'utf8')
    if args.prepare_only:
        print(json.dumps({'prepared':True,'provider_calls':0,'output':str(out)}));return 0
    combined=dict(passed=False,phases=[])
    for phase in ('run','reopen'):
        env['TWOBYTEASR_TERMINOLOGY_PHASE']=phase
        with (out/(phase+'-process.log')).open('w',encoding='utf8') as log:
            child=run_hidden_subprocess([sys.executable,str(root/'quick_start.py')],cwd=root,env=env,
                stdout=log,stderr=subprocess.STDOUT,timeout=1300 if phase=='run' else 120,purpose='normal ASR UI '+phase+' audit')
        path=out/(phase+'-result.json')
        result=json.loads(path.read_text('utf8')) if path.is_file() else {}
        combined['phases'].append(dict(phase=phase,exit_code=child.returncode,result=result))
        if child.returncode or not result.get('passed'):break
    combined['settings_unchanged']=source.read_bytes()==original
    combined['passed']=len(combined['phases'])==2 and all(x['result'].get('passed') for x in combined['phases']) and combined['settings_unchanged']
    (out/'result.json').write_text(json.dumps(combined,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=combined['passed'],output=str(out)),ensure_ascii=False))
    return 0 if combined['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
