"""Bounded real-model validation using the current configured application model.

Reads credentials through the application's existing read-only interface; no
key copying, model switch, auto repair or media upload. Results live under tmp.
"""
import argparse
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
PROMPT=('Balatro小丑牌视觉语言启发的中文动态字幕组件，设计三款：'
    'A小丑牌倍率封签、B赌桌筹码压印框、C稀有卡贴纸/传奇封牌。'
    '不画小人动物吉祥物，不放独立像素小卡插图；字幕本体为主角。'
    '按已取样的Balatro效果说明UI、chips/mult、稀有度封签与局部foil设计，'
    '背景框、内外边界、中文字面材质、重点字组、局部细节和完整入场/稳定阅读/退场都要成立。'
    '三稿必须不同结构、材料、关键词与动作，不能只换色。不要黑条白字黄块或抽象画。'
    '字幕原文：这种就属于是点了自动战斗。重点字组：自动战斗。'
    '使用真实打包中文字体；正常游戏叠加大小清楚。')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--full-source',action='store_true');p.add_argument('--prepare-only',action='store_true')
    args=p.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():raise ValueError('Use a fresh repository tmp directory')
    out.mkdir(parents=True)
    original_local=Path(os.environ['LOCALAPPDATA'])
    from twobyteasr.settings import SETTINGS_FILENAME,DEFAULT_SETTINGS,_merge_known_settings
    source=original_local/'2ByteASR'/SETTINGS_FILENAME;before=source.read_bytes()
    settings,_=_merge_known_settings(DEFAULT_SETTINGS,json.loads(before));settings=copy.deepcopy(settings)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'isolation')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr import llm_config
    secret_source=original_local/'2ByteASR'/'secrets.dat'
    reader=llm_config._read_secrets
    llm_config._read_secrets=lambda:reader(read_only_path=secret_source)
    settings['models'].update(ai_design_mode='full' if args.full_source else 'drafts',
        ai_design_candidate_count=3,ai_design_concurrency=2,ai_design_max_repair_calls=0)
    from twobyteasr.provider_registry import GLOBAL_PROVIDER_REGISTRY
    selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
    from twobyteasr.caption_creative_pipeline import ThemeLedger
    from twobyteasr.caption_style_reference import attach_reference
    from twobyteasr.authored_prompt import assemble
    ledger=ThemeLedger(out/'preflight',PROMPT);attach_reference(ledger)
    ledger.value.update(requested_candidates=3,component_drafts=not args.full_source,
        creative_context=dict(subtitle_text='这种就属于是点了自动战斗'))
    prompt,receipt=assemble(ledger)
    (out/'preflight-prompt.txt').write_text(prompt,'utf8')
    (out/'preflight.json').write_text(json.dumps(dict(provider=selection.provider,model=selection.model,
        mode='full-source' if args.full_source else 'model-component-definitions',
        no_media_upload=True,source_settings_sha256=hashlib.sha256(before).hexdigest(),assembly=receipt),ensure_ascii=False,indent=2),'utf8')
    if args.prepare_only:
        print(json.dumps(dict(provider=selection.provider,model=selection.model,prepared=True,external_calls=0)));return 0
    budget=out/'call-budget.json'
    budget.write_text(json.dumps(dict(limits=dict(generation=4 if args.full_source else 1,repair=0,redo=0),calls=[])), 'utf8')
    from twobyteasr.ai_design_call_budget import install_acceptance_budget
    install_acceptance_budget(budget)
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    from twobyteasr.studio_project import SubtitleProject,StudioCue,StudioMedia
    from twobyteasr.caption_creative_pipeline import request_creative_options
    project=SubtitleProject(media=StudioMedia('',duration_ms=6000,width=1920,height=1080),
        cues=[StudioCue('sample',0,6000,'这种就属于是点了自动战斗')])
    try:
        result=request_creative_options(project,'sample',PROMPT,settings,ledger_root=out/'creative',
            request_id=out.name,reference_frames=(),stage_callback=lambda label:print(label,flush=True))
        value=asdict(result)
        (out/'result.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps(dict(provider=selection.provider,model=selection.model,candidates=[dict(id=c['id'],
            status=c.get('technical_status'),origin=c.get('source_origin'),ledger=c.get('ledger_path')) for c in result.concepts]),ensure_ascii=False))
    finally:
        (out/'settings-unchanged.json').write_text(json.dumps(dict(unchanged=source.read_bytes()==before)),'utf8')
        from twobyteasr.renderer_service import GLOBAL_RENDERER_SERVICE
        GLOBAL_RENDERER_SERVICE.shutdown()
    return 0


if __name__=='__main__':raise SystemExit(main())
