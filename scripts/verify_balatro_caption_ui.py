"""Real card UI pixels and production parity; local examples are not AI output."""
import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--game-frame',type=Path,required=True)
    parser.add_argument('--quick',action='store_true')
    parser.add_argument('--components-version',type=int,choices=(3,4,5),default=3)
    args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp'):
        raise ValueError('Use repository tmp')
    out.mkdir(parents=True,exist_ok=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'isolation')
    from twobyteasr.test_isolation import install
    install()
    from PIL import Image,ImageDraw
    import numpy as np
    from twobyteasr.caption_card_ui import examples
    if args.components_version==4:
        from twobyteasr.caption_type_effects import examples
    elif args.components_version==5:
        from twobyteasr.caption_living_motion import examples
    from twobyteasr.caption_components import compose
    from twobyteasr.renderer_service import RendererService,RendererJob
    from twobyteasr.web_theme import WebThemeDocument,theme_archive_html
    from twobyteasr.style_recipe import StyleRecipe
    from twobyteasr.theme_direction_preview import render_motion_preview
    from twobyteasr.authored_motion_review import capture_motion_review
    background=Image.open(args.game_frame).convert('RGBA').resize((1920,1080))
    service=RendererService()
    result=dict(provenance='local-authored-component-examples',external_model_calls=0,
                checks={},variants=[],review='actual image review required; no user approval implied')
    text='这种就属于是点了自动战斗'
    def check(name,value):
        result['checks'][name]=bool(value)
        if not value: print('FAIL',name,flush=True)
    def save():
        result['passed']=all(result['checks'].values())
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    started=time.monotonic()
    try:
        for ident,name,definition in zip('ABC',['小丑牌倍率封签','赌桌筹码压印框','稀有卡贴纸 · 传奇封牌'],examples()):
            folder=out/ident;folder.mkdir(exist_ok=True)
            theme=WebThemeDocument.from_dict(dict(name=name,**compose(dict(definition,emphasis=['自动战斗'])))).to_dict()
            (folder/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),'utf8')
            html=theme_archive_html(theme,sample_text=text,duration_seconds=6,auto_replay=False)
            (folder/'theme.html').write_text(html,'utf8')
            service.live_set(html,width=1920,height=1080)
            row=dict(id=ident,name=name,definition=definition,source='local-authored',frames=[])
            arrays={}
            for ms in ([1500] if args.quick else [0,120,320,650,1500,2800,4200,4800,5400,5600,5750,5850,5920,5970,5999,6000,6100]):
                bitmap=Image.open(BytesIO(service.live_pause(cue_ms=ms,stage_ms=ms))).convert('RGBA')
                bitmap.save(folder/f'{ms}.png');arrays[ms]=np.array(bitmap)
                Image.alpha_composite(background,bitmap).save(folder/f'game-{ms}.png')
                box=bitmap.getchannel('A').getbbox();row['frames'].append(dict(ms=ms,bbox=box))
                if ms==1500:
                    diag=service._live_request({'type':'live_diagnostics','selectors':['.bui-assembly','.bui-copy','.wt-focus'],'include_fonts':True},timeout=5)['diagnostics']
                    row['hold_diagnostics']=diag
                    check(ident+':text_and_fonts',diag['fonts_ready'] and not diag['script_errors'] and text in diag['cue_text'])
                    bitmap.crop((box[0]-12,box[1]-12,box[2]+12,box[3]+12)).save(folder/'detail.png')
                    for style,color in [('light','#DFDFD7'),('dark','#10141A')]:
                        Image.alpha_composite(Image.new('RGBA',(1920,1080),color),bitmap).save(folder/(style+'.png'))
            if not args.quick:
                if args.components_version==5:
                    for a,b in [(1500,2800),(4200,4800),(4800,5400)]:
                        check(ident+f':continuous_reading_{a}_{b}',np.count_nonzero(arrays[a]!=arrays[b])>200)
                check(ident+':entry_is_multiframe',np.count_nonzero(arrays[120][:,:,3])>100 and not np.array_equal(arrays[120],arrays[320]))
                check(ident+':exit_is_multiframe',np.count_nonzero(arrays[5850][:,:,3])>100 and not np.array_equal(arrays[5750],arrays[5850]))
                check(ident+':clear_before_boundary',not arrays[5999][:,:,3].any())
                check(ident+':clear_at_boundary',not arrays[6000][:,:,3].any() and not arrays[6100][:,:,3].any())
                for ms in reversed(list(arrays)):
                    current=np.array(Image.open(BytesIO(service.live_pause(cue_ms=ms,stage_ms=ms)))).astype(float)
                    original=arrays[ms].astype(float)
                    for im in (current,original): im[:,:,:3]*=im[:,:,3:]/255
                    err=np.abs(current-original)
                    check(ident+f':reverse_{ms}',err.max()<=2 and err.mean()<.003)
                for span,caption in [(500,'短句'),(900,'继续向前'),(1500,text),(3000,'没有重点词也完整保留背景框'),(3000,'第一行明确换行\n第二行继续说明'),(3000,'就算这句话很长也应该完整呈现每一个中文字，不应裁掉后半句，这是最后六个字')]:
                    service.live_text(text=caption,duration_ms=span)
                    png=service.live_pause(cue_ms=span*.5,stage_ms=span*.5)
                    bitmap=Image.open(BytesIO(png)).convert('RGBA');bitmap.save(folder/f'case-{span}-{len(caption)}.png')
                    diag=service._live_request({'type':'live_diagnostics','selectors':['.bui-assembly'],'include_fonts':True},timeout=5)['diagnostics']
                    runs=diag['semantic_text_runs']
                    valid=bool(runs) and all(r['opacity']>.5 and r['rect'][0]>=1920*.03 and r['rect'][0]+r['rect'][2]<=1920*.97+1 for r in runs)
                    check(ident+f':layout_{span}_{len(caption)}',valid and caption.replace('\n','') in diag['cue_text'].replace('\n','') and not diag['script_errors'])
                motion_frames,sampling=capture_motion_review(service,theme,text,folder)
                row['motion_sampling']=sampling
                six=render_motion_preview(service,html,folder,ident,background_path=args.game_frame)
                short_html=theme_archive_html(theme,sample_text=text,duration_seconds=1.5,auto_replay=False)
                short=render_motion_preview(service,short_html,folder,ident+'-short',background_path=args.game_frame,duration_ms=1500)
                row.update(motion=six,short_motion=short)
                recipe=StyleRecipe(name=theme['name'],engine='remotion',web_theme=theme).to_dict()
                props=dict(schemaVersion=1,width=1920,height=1080,fps=30,durationInFrames=180,cues=[dict(id='local',text=text,startMs=0,endMs=6000,styleId='theme',visual=recipe)],recipes={'theme':recipe})
                frames=[4,45,175]
                service.render([RendererJob(str(folder/f'production-{f}.png'),props,f,job_kind='production') for f in frames],timeout=120)
                service.live_set(html,width=1920,height=1080)
                for f in frames:
                    live=np.array(Image.open(BytesIO(service.live_pause(cue_ms=f*1000/30,stage_ms=f*1000/30)))).astype(float)
                    prod=np.array(Image.open(folder/f'production-{f}.png')).astype(float)
                    for im in (live,prod):im[:,:,:3]*=im[:,:,3:]/255
                    check(ident+f':production_parity_{f}',np.abs(live-prod).mean()<.05)
            result['variants'].append(row);save();print(ident,'complete',flush=True)
        # Same full-frame scale, same input; no giant detail crop hiding size.
        sheet=Image.new('RGB',(960,540*3),'#172329')
        for index,ident in enumerate('ABC'):
            sheet.paste(Image.open(out/ident/'game-1500.png').resize((960,540)),(0,index*540))
        sheet.save(out/'comparison.png')
    finally:
        service.shutdown();result['elapsed_seconds']=time.monotonic()-started;save()
    print(json.dumps(dict(passed=result['passed'],checks=len(result['checks']),output=str(out))))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
