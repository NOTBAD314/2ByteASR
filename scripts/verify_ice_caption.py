"""Actual renderer, material movie and transparent archive; no provider calls."""
import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--old-html',type=Path);parser.add_argument('--quick',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp'):raise ValueError('Use repository tmp')
    out.mkdir(parents=True,exist_ok=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'isolation')
    from twobyteasr.test_isolation import install
    install()
    from PIL import Image
    import numpy as np
    from twobyteasr.caption_components import compose
    from twobyteasr.web_theme import WebThemeDocument,theme_archive_html,import_theme_archive,export_theme_archive
    from twobyteasr.renderer_service import RendererService,RendererJob
    from twobyteasr.theme_direction_preview import render_motion_preview
    from twobyteasr.style_recipe import StyleRecipe
    text='这块石头这么圆 一定能推吧？'
    theme=WebThemeDocument.from_dict(dict(name='冰河世纪 · 霜脊冰刻',id='ice-age-frost-shelf',
        notes='本轮Codex原创组件重做；不是DeepSeek/Grok供应商新作。公开项目研究转译，原稿独立保留。',
        **compose(dict(version=6)))).to_dict()
    (out/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),'utf8')
    service=RendererService();result=dict(source_origin='codex_authored_redesign',external_model_calls=0,checks={},theme=theme['name'])
    def check(name,value):
        result['checks'][name]=bool(value)
        if not value:print('FAIL',name,flush=True)
    def save():
        result['passed']=all(result['checks'].values());(out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    try:
        originals={}
        if args.old_html:originals['old']=import_theme_archive(args.old_html)
        originals['new']=theme
        for label,item in originals.items():
            folder=out/label;folder.mkdir(exist_ok=True)
            html=theme_archive_html(item,sample_text=text,duration_seconds=6,auto_replay=False)
            (folder/'theme.html').write_text(html,'utf8');service.live_set(html,width=1920,height=1080)
            arrays={}
            stamps=[1500] if args.quick else [0,120,320,650,1500,2800,4200,5400,5660,5780,5890,5999,6000]
            for ms in stamps:
                bitmap=Image.open(BytesIO(service.live_pause(cue_ms=ms,stage_ms=ms))).convert('RGBA')
                bitmap.save(folder/f'{ms}.png');arrays[ms]=np.array(bitmap)
                if ms==1500:
                    bbox=bitmap.getchannel('A').getbbox();result[label+'_bbox']=bbox
                    if bbox:
                        box=(max(0,bbox[0]-24),max(0,bbox[1]-24),min(1920,bbox[2]+24),min(1080,bbox[3]+24))
                        detail=bitmap.crop(box);Image.alpha_composite(Image.new('RGBA',detail.size,'#20262e'),detail).save(folder/'subject.png')
                    diag=service._live_request({'type':'live_diagnostics','include_fonts':True},timeout=5)['diagnostics']
                    (folder/'diagnostics.json').write_text(json.dumps(diag,ensure_ascii=False,indent=2),'utf8')
                    check(label+'_readable',text in diag['cue_text'] and diag['fonts_ready'] and not diag['script_errors'])
            if args.quick:continue
            if label=='new':
                check('initial_transparent',not arrays[0][:,:,3].any());check('terminal_transparent',not arrays[6000][:,:,3].any())
                for a,b in [(120,320),(1500,2800),(4200,5400),(5780,5890)]:
                    check(f'motion_{a}_{b}',np.count_nonzero(arrays[a]!=arrays[b])>100)
                for ms in reversed(stamps):
                    got=np.array(Image.open(BytesIO(service.live_pause(cue_ms=ms,stage_ms=ms)))).astype(float)
                    expected=arrays[ms].astype(float)
                    for im in (got,expected):im[:,:,:3]*=im[:,:,3:]/255
                    err=np.abs(got-expected);check(f'reverse_seek_{ms}',err.mean()<.01 and err.max()<=3)
                for n,(span,caption) in enumerate([(500,'短句'),(1500,text),(3000,'没有重点词也完整保留冰川字幕框'),(3000,'第一行明确换行\n第二行继续说明'),(3000,'就算这句话很长也应该完整呈现每一个中文字，不应裁掉后半句，这是最后六个字')]):
                    service.live_text(text=caption,duration_ms=span)
                    bitmap=Image.open(BytesIO(service.live_pause(cue_ms=span*.5,stage_ms=span*.5))).convert('RGBA');bitmap.save(folder/f'case-{n}.png')
                    diag=service._live_request({'type':'live_diagnostics'},timeout=5)['diagnostics']
                    runs=diag['semantic_text_runs']
                    check(f'caption_case_{n}',bool(runs) and caption.replace('\n','') in diag['cue_text'].replace('\n','') and not diag['script_errors'] and all(r['opacity']>.5 and r['rect'][0]>=55 and r['rect'][0]+r['rect'][2]<=1865 for r in runs))
                recipe=StyleRecipe(name=theme['name'],engine='remotion',web_theme=theme).to_dict()
                props=dict(schemaVersion=1,width=1920,height=1080,fps=30,durationInFrames=180,cues=[dict(id='ice',text=text,startMs=0,endMs=6000,styleId='theme',visual=recipe)],recipes={'theme':recipe})
                service.render([RendererJob(str(folder/'production-45.png'),props,45,job_kind='production')],timeout=120)
                exported=np.array(Image.open(folder/'production-45.png')).astype(float);live=arrays[1500].astype(float)
                for im in (exported,live):im[:,:,:3]*=im[:,:,3:]/255
                check('live_export_same_pixels',np.abs(exported-live).mean()<.05)
            result[label+'_motion']=render_motion_preview(service,html,folder,label)
            short=theme_archive_html(item,sample_text=text,duration_seconds=1.5,auto_replay=False)
            result[label+'_short']=render_motion_preview(service,short,folder,label+'-short',duration_ms=1500)
            save()
        result['archive']=str(export_theme_archive(theme,out/'作品',sample_text=text))
    finally:
        service.shutdown();save()
    print(json.dumps(dict(passed=result['passed'],checks=len(result['checks']),archive=result.get('archive')),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
