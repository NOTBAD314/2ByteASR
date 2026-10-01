"""Explicit real request with a read-only snapshot of the current user's model."""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--settings',type=Path,required=True)
    parser.add_argument('--replay-trace',type=Path,help='Revalidate saved real output without another model request')
    parser.add_argument('--repair-saved',action='store_true',help='One explicit same-model correction of observed defects')
    args=parser.parse_args()
    settings=json.loads(args.settings.read_text(encoding='utf-8-sig'))
    out=ROOT/'tmp/compiler-current'/time.strftime('%Y%m%d-%H%M%S');out.mkdir(parents=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='offscreen',
        DASHSCOPE_API_KEY='sk-local-test-dummy')
    from PySide6.QtWidgets import QApplication
    app=QApplication([])
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue
    from twobyteasr.studio_ai import request_web_theme_design
    from twobyteasr.theme_draft import ThemeDraft,validate_draft_frames
    from twobyteasr.web_theme import export_theme_archive
    from twobyteasr.renderer_service import GLOBAL_RENDERER_SERVICE
    project=SubtitleProject(media=StudioMedia(path='read-only-design-context',width=1280,height=720),
        cues=[StudioCue('current-model',0,3000,'我送的不是货，是整个人类的希望')])
    request_id=uuid.uuid4().hex
    from twobyteasr.provider_registry import GLOBAL_PROVIDER_REGISTRY
    selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
    draft=ThemeDraft(request_id,1,'current-model',project.cues[0].text,scope='fullscreen',
        provider=selection.provider,model=selection.model)
    result=dict(provider=draft.provider,model=draft.model,settings_read_only=str(args.settings.resolve()),
        request_id=request_id,stages=[])
    def progress(value):
        result['stages'].append(dict(stage=value,at=time.time()))
        (out/'progress.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(value,flush=True)
    count=[0]
    def validate(theme,budget):
        count[0]+=1
        return validate_draft_frames(draft.with_theme(theme),out/f'frames-{count[0]}',cancel_check=lambda:False,
            deadline_seconds=budget,progress=progress)
    print('EVIDENCE',out,flush=True)
    try:
        if args.replay_trace:
            from types import SimpleNamespace
            from twobyteasr.web_theme_compiler import code_gate
            saved=json.loads(args.replay_trace.read_text(encoding='utf8'))
            assert saved['provider']=={'provider':selection.provider,'model':selection.model}
            raw=saved['raw_provider_responses'][-1]['response_text']
            theme,quality=code_gate(raw,saved['instruction'],saved['scope'])
            result['revalidated_saved_request_id']=saved['request_id']
            result['network_requests_this_run']=0
            if args.repair_saved:
                from twobyteasr.studio_ai import refine_web_theme_design
                progress('修复实测长中文裁切与过大金色脉冲')
                correction=refine_web_theme_design(theme,
                    '实际六帧检查发现：1) .cargo-line white-space:nowrap使40字中文越出82%容器，改为可换行，'
                    '验证无speaker和长speaker；字幕允许两行，保持完整中文。2) 1.74秒巨大的金色扫描环占半屏，'
                    '违背70/25/5和不遮挡游戏。将全画面金环的峰值透明度压至0.06，扫描只在入场出现，'
                    '保持段金色只留机械爪/状态灯/短扫描线。保留已有钢铁底板、铆钉、机械爪、时间雨黑索，'
                    '不要重新换主题或添加emoji。入场、保持、退场与--wt-dur仍须存在。',
                    cue_text=draft.text,speaker_name=draft.speaker,runtime_settings=settings,
                    deadline_seconds=180,stage_callback=progress,cancel_check=lambda:False)
                if correction.source!='refined':raise RuntimeError(correction.message)
                theme=correction.theme
                result['network_requests_this_run']=1
                result['explicit_correction_trace']=getattr(correction,'trace_path','')
            suggestion=SimpleNamespace(theme=theme,trace_path=str(args.replay_trace.resolve()),
                provider=selection.provider,model=selection.model,concepts=saved['concepts'],
                selected_concept_id=saved['selected_concept_id'],repair_count=saved['repair_count'],
                quality=quality,render_evidence=validate(theme,35))
        else:
            suggestion=request_web_theme_design(project,'current-model',
            '死亡搁浅工业货箱字幕，全画面舞台有克制的黑索与逆重力时间雨；字幕位于底部安全区。'
            '货箱有冷钢铆钉锁扣，四瓣机械侦测爪展开联动开罗尔金扫描波逐字显影；保持时轻扫，'
            '结尾机械爪回收、文字蒸散、货箱下沉。炭黑/冷钢灰/金色70/25/5，中文清晰，透明背景。',
            settings,request_id=request_id,effect_scope='fullscreen',stage_callback=progress,
                render_validator=validate)
        assert (suggestion.provider,suggestion.model)==(selection.provider,selection.model)
        result.update(passed=True,trace_path=suggestion.trace_path,theme_name=suggestion.theme['name'],
            concepts=suggestion.concepts,selected=suggestion.selected_concept_id,repair_count=suggestion.repair_count,
            quality=suggestion.quality,evidence=suggestion.render_evidence)
        (out/'theme.json').write_text(json.dumps(suggestion.theme,ensure_ascii=False,indent=2),encoding='utf8')
        verified=draft.with_theme(suggestion.theme)
        archive=export_theme_archive(suggestion.theme,out/'archives',sample_text=draft.text,
            validate_before_publish=lambda folder:validate_draft_frames(verified,out/'archive-validation',
                cancel_check=lambda:False,exact_html_path=folder/'theme.html'))
        result['archive']=str(archive)
    except Exception as exc:
        result.update(passed=False,error=f'{type(exc).__name__}: {exc}',category=getattr(exc,'category','error'),
            trace_path=getattr(exc,'trace_path',''))
        raise
    finally:
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        GLOBAL_RENDERER_SERVICE.shutdown()


if __name__=='__main__':main()
