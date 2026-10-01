"""Local component capability and legacy endpoint evidence, without a provider."""
import argparse
import json
from pathlib import Path
import sys
import time
from io import BytesIO

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def probe_extensions(service,out,result,check):
    """Real CSS-variable/local-mask/SVG/sequential-keyframe and fallback proof."""
    from PIL import Image
    import numpy as np
    from twobyteasr.caption_components import compose
    from twobyteasr.web_theme import WebThemeDocument,theme_archive_html
    from twobyteasr.renderer_service import RendererJob
    from twobyteasr.style_recipe import StyleRecipe
    theme=dict(name='源码能力验证',**compose(dict(version=1)))
    theme['cueHtml']=theme['cueHtml'].replace('<div class="cap-type"',
        '<svg class="proof-svg" viewBox="0 0 400 4"><path class="proof-line" d="M0 2 L400 2" fill="none" stroke="#D9CB85" stroke-width="3" stroke-dasharray="400"/></svg>'
        '<div class="proof-variable"></div><div class="proof-clip"></div><div class="cap-type"')
    theme['cueCss']+='''
.proof-svg{position:absolute;left:0;top:-.12em;width:100%;height:.05em}
.proof-variable{position:absolute;left:0;bottom:-.2em;width:40%;height:.08em;background:linear-gradient(90deg,#D9CB85,#F7F1DD);background-size:200% 100%;opacity:var(--caption-reveal);background-position-x:calc(var(--caption-sheen) * 1%)}
.proof-clip{position:absolute;right:0;bottom:-.2em;width:30%;height:.08em;background:#D9CB85}
'''
    tracks=theme['motionSpec']['tracks']
    def track(sel,start,end,before,after):
        return dict(selector=sel,phase='build',start=start,end=end,ease='none',**{'from':before,'to':after})
    tracks += [track('.proof-line',0,1,{'strokeDashoffset':400},{'strokeDashoffset':0}),
        track('.proof-clip',0,1,{'clipPath':'inset(0% 100% 0% 0%)'},{'clipPath':'inset(0% 0% 0% 0%)'}),
        track('.proof-variable',0,.5,{'--caption-reveal':0,'--caption-sheen':0},{'--caption-reveal':.5,'--caption-sheen':50}),
        track('.proof-variable',.5,1,{'--caption-reveal':.5,'--caption-sheen':50},{'--caption-reveal':1,'--caption-sheen':100})]
    theme=WebThemeDocument.from_dict(theme).to_dict();text='源码能力与中文字体'
    folder=out/'extensions';folder.mkdir(exist_ok=True)
    (folder/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),'utf8')
    service.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=3,auto_replay=False),width=1920,height=1080)
    images={};diagnostics={}
    for ms in (0,120,240,360,480):
        png=service.live_pause(cue_ms=ms,stage_ms=ms);(folder/f'{ms}.png').write_bytes(png)
        images[ms]=np.array(Image.open(BytesIO(png)))
        diagnostics[ms]=service._live_request({'type':'live_diagnostics','selectors':['.proof-variable','.proof-clip','.proof-line'],'include_fonts':True},timeout=5)['diagnostics']
    for ms,opacity in ((120,.25),(240,.5),(360,.75),(480,1)):
        root=next(r for r in diagnostics[ms]['roots'] if r['selector']=='.proof-variable')
        check(f'variables_and_sequential_keyframes_{ms}',abs(float(root['opacity'])-opacity)<.01)
    check('local_mask_changes',diagnostics[0]['roots'][-2]['clipPath']!=diagnostics[480]['roots'][-2]['clipPath'])
    box=next(r['rect'] for r in diagnostics[480]['roots'] if r['selector']=='.proof-line')
    x,y,w,h=box
    def alpha(ms):return np.count_nonzero(images[ms][max(0,int(y)-3):int(y+h)+4,max(0,int(x)):int(x+w),3])
    check('svg_line_draws',alpha(480)>alpha(120)*1.5)
    check('extensions_no_runtime_errors',all(not d['script_errors'] for d in diagnostics.values()))
    recipe=StyleRecipe(name=theme['name'],engine='remotion',web_theme=theme).to_dict()
    props=dict(schemaVersion=1,width=1920,height=1080,fps=25,durationInFrames=75,
        cues=[dict(id='fixture',text=text,startMs=0,endMs=3000,styleId='theme',visual=recipe)],recipes={'theme':recipe})
    service.render([RendererJob(str(folder/f'production-{f}.png'),props,f,job_kind='production') for f in (3,9,12)],timeout=120)
    for frame in (3,9,12):
        live=images[frame*40].astype(float);export=np.array(Image.open(folder/f'production-{frame}.png')).astype(float)
        for img in (live,export):img[:,:,:3]*=img[:,:,3:]/255
        check(f'extensions_export_parity_{frame}',np.abs(live-export).mean()<.05)
    theme['appearance']['fontFamily']='2ByteDeliberatelyMissingFont, Source Han Sans SC Heavy'
    service.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=3,auto_replay=False),width=1920,height=1080)
    service.live_pause(cue_ms=1500,stage_ms=1500)
    fallback=service._live_request({'type':'live_diagnostics','include_fonts':True},timeout=5)['diagnostics']
    fonts=[f for row in fallback.get('rendered_fonts',[]) for f in row['fonts'] if f.get('glyphCount',0)]
    check('actual_chinese_fallback',bool(fonts) and all('Source Han' in f['familyName'] for f in fonts))
    result['extensions']=dict(diagnostics=diagnostics,fallback_fonts=fonts)
    # Consecutive cues and backward project seeks use exactly one cue-relative
    # mapping, including a short settled cue between two animated cues.
    theme=dict(name='连续字幕',**compose(dict(version=1,emphasis=['重点'])))
    cues=[(0,1500,'第一句重点'),(1500,1800,'短句'),(1800,4200,'下一句继续说明')]
    service.live_set(theme_archive_html(theme,sample_text=cues[0][2],duration_seconds=1.5,auto_replay=False),width=1920,height=1080)
    current=0;sequence={};times=[0,200,900,1499,1500,1650,1800,2000,2500,4199,4200]
    for at in [*times,*reversed(times)]:
        index=next((i for i,(start,end,caption) in enumerate(cues) if start<=at<end),len(cues)-1)
        start,end,caption=cues[index]
        if current!=index:
            service.live_text(text=caption,duration_ms=end-start);current=index
        image=np.array(Image.open(BytesIO(service.live_pause(cue_ms=at-start,stage_ms=at))))
        diag=service._live_request({'type':'live_diagnostics'},timeout=5)['diagnostics']
        check(f'consecutive_text_{at}',diag['cue_text']==caption and not diag['script_errors'])
        if at in sequence:check(f'consecutive_reverse_{at}',np.array_equal(image,sequence[at]))
        sequence[at]=image
    check('consecutive_terminal_clear',not sequence[4200][:,:,3].any())
    recipe=StyleRecipe(name=theme['name'],engine='remotion',web_theme=theme).to_dict()
    props=dict(schemaVersion=1,width=1920,height=1080,fps=30,durationInFrames=126,
        cues=[dict(id=str(i),text=caption,startMs=start,endMs=end,styleId='theme',visual=recipe) for i,(start,end,caption) in enumerate(cues)],recipes={'theme':recipe})
    frames=[27,45,75]
    service.render([RendererJob(str(folder/f'consecutive-{f}.png'),props,f,job_kind='production') for f in frames],timeout=120)
    for frame in frames:
        live=sequence[frame*1000//30].astype(float);export=np.array(Image.open(folder/f'consecutive-{frame}.png')).astype(float)
        for img in (live,export):img[:,:,:3]*=img[:,:,3:]/255
        check(f'consecutive_export_{frame}',np.abs(live-export).mean()<.05)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--game-frame',type=Path);p.add_argument('--legacy-html',type=Path)
    p.add_argument('--extensions-only',action='store_true');a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if not out.is_relative_to(ROOT/'tmp'):raise ValueError('Use repository tmp')
    from PIL import Image
    import numpy as np
    from twobyteasr.caption_components import compose
    from twobyteasr.web_theme import WebThemeDocument,theme_archive_html
    from twobyteasr.renderer_service import RendererService,RendererJob
    from twobyteasr.theme_direction_preview import render_motion_preview
    from twobyteasr.style_recipe import StyleRecipe
    service=RendererService();result=dict(kind='local-fixture',external_model_calls=0,checks={},cases=[],timings={})
    started=time.monotonic()
    def check(name,passed):
        result['checks'][name]=bool(passed)
        if not passed:print('FAIL',name,flush=True)
    def save():
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    text='这种就属于是点了自动战斗'
    try:
        for i in ([] if a.extensions_only else range(3)):
            dest=out/f'variant-{i}';dest.mkdir(exist_ok=True)
            from twobyteasr.caption_surfaces import examples
            theme=dict(name=('印刷套边与压印','红蓝交接轨道','光谱折射玻璃')[i],
                **compose(dict(examples()[i],emphasis=['自动战斗'])))
            theme=WebThemeDocument.from_dict(theme).to_dict()
            (dest/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),'utf8')
            html=theme_archive_html(theme,sample_text=text,duration_seconds=3,auto_replay=False)
            (dest/'theme.html').write_text(html,'utf8');service.live_set(html,width=1920,height=1080)
            stamps=[0,120,480,1500,2800,2900,2966.6666667,2999,3000,3100]
            images={}
            for ms in stamps:
                png=service.live_pause(cue_ms=ms,stage_ms=ms);images[ms]=np.array(Image.open(BytesIO(png)))
                (dest/f'{ms:g}.png').write_bytes(png)
            check(f'{i}:hidden_start',not images[0][:,:,3].any())
            check(f'{i}:visible_hold',np.count_nonzero(images[1500][:,:,3])>1000)
            check(f'{i}:finished_before_boundary',not images[2999][:,:,3].any())
            check(f'{i}:boundary_and_after_clear',not images[3000][:,:,3].any() and not images[3100][:,:,3].any())
            for ms in reversed(stamps):
                png=service.live_pause(cue_ms=ms,stage_ms=ms);current=np.array(Image.open(BytesIO(png)))
                left=current.astype(float);right=images[ms].astype(float)
                for pixels in (left,right):pixels[:,:,:3]*=pixels[:,:,3:]/255
                difference=np.abs(left-right)
                result.setdefault('seek_pixel_error',{})[f'{i}:{ms:g}']=dict(max=float(difference.max()),mean=float(difference.mean()))
                # Chromium translucent-edge rasterization may differ by <=2/255
                # with identical computed poses. Record it, never call it exact.
                check(f'{i}:reverse_{ms:g}',difference.max()<=2 and difference.mean()<.003)
            for span,caption in [(300,'短句'),(900,'继续向前'),(3000,'第一行明确换行\n第二行继续说明'),
                (3000,'就算这句话很长也应该完整呈现每一个中文字，不应裁掉后半句，这是最后六个字')]:
                service.live_text(text=caption,duration_ms=span)
                png=service.live_pause(cue_ms=span*.5,stage_ms=span*.5)
                diag=service._live_request({'type':'live_diagnostics','selectors':['.cap-body','.wt-focus'],'include_fonts':True},timeout=5)['diagnostics']
                runs=diag['semantic_text_runs'];valid=all(r['opacity']>.5 and r['rect'][0]>=1920*.03 and r['rect'][0]+r['rect'][2]<=1920*.97+1 for r in runs)
                check(f'{i}:{span}:{len(caption)}:text_layout',valid and caption.replace('\n','') in diag['cue_text'].replace('\n',''))
                check(f'{i}:{span}:{len(caption)}:runtime',not diag['script_errors'] and diag['fonts_ready'])
                (dest/f'case-{span}-{len(caption)}.png').write_bytes(png)
                result['cases'].append(dict(variant=i,span=span,text=caption,diagnostics=diag))
            service.live_text(text=text,duration_ms=3000)
            recipe=StyleRecipe(name=theme['name'],engine='remotion',web_theme=theme).to_dict()
            props=dict(schemaVersion=1,width=1920,height=1080,fps=30,durationInFrames=90,
                cues=[dict(id='fixture',text=text,startMs=0,endMs=3000,styleId='theme',visual=recipe)],recipes=dict(theme=recipe))
            frames=[4,45,87]
            jobs=[RendererJob(str(dest/f'production-{frame}.png'),props,frame,job_kind='production') for frame in frames]
            service.render(jobs,timeout=120)
            for frame in frames:
                ms=frame*1000/30;live=np.array(Image.open(BytesIO(service.live_pause(cue_ms=ms,stage_ms=ms)))).astype(float)
                export=np.array(Image.open(dest/f'production-{frame}.png')).astype(float)
                for image in (live,export):image[:,:,:3]*=image[:,:,3:]/255
                check(f'{i}:production_parity_{frame}',np.abs(live-export).mean()<.05)
            if a.game_frame:
                background=Image.open(a.game_frame).convert('RGBA').resize((1920,1080))
                Image.alpha_composite(background,Image.fromarray(images[1500])).save(dest/'game.png')
            # Sequential display uses the same cue clock and is also retained
            # as a real playable video; snapshots alone are not rhythm evidence.
            six=theme_archive_html(theme,sample_text=text,duration_seconds=6,auto_replay=False)
            motion=render_motion_preview(service,six,dest,str(i),background_path=a.game_frame)
            result['timings'][str(i)]=dict(completed_at=time.time(),elapsed_seconds=time.monotonic()-started,motion=motion)
            save()
        probe_extensions(service,out,result,check)
        if a.legacy_html:
            dest=out/'legacy';dest.mkdir(exist_ok=True)
            legacy=a.legacy_html.read_text('utf8');service.live_set(legacy,width=1920,height=1080)
            service.live_text(text=text,duration_ms=3000)
            for ms in (0,160,1500,2966.6666667,2999,3000):
                png=service.live_pause(cue_ms=ms,stage_ms=ms);(dest/f'{ms:g}.png').write_bytes(png)
                diag=service._live_request({'type':'live_diagnostics','selectors':['.board-move','.rank']},timeout=5)['diagnostics']
                result.setdefault('legacy_frames',[]).append(dict(ms=ms,nonzero_alpha=int(np.count_nonzero(np.array(Image.open(BytesIO(png)))[:,:,3])),diagnostics=diag))
        result['passed']=all(result['checks'].values())
    finally:
        service.shutdown();result['elapsed_seconds']=time.monotonic()-started;save()
    print(json.dumps(dict(passed=result['passed'],checks=len(result['checks']),output=str(out))))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
