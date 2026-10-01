"""Shared GSAP seek, boundaries, short cues, fonts and production frame parity."""
from pathlib import Path
import argparse,json,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    from twobyteasr.web_theme import WebThemeDocument,theme_archive_html
    from twobyteasr.renderer_service import RendererService,RendererJob
    from PIL import Image
    import numpy as np
    p=argparse.ArgumentParser();p.add_argument('--theme',type=Path);p.add_argument('--output',type=Path);p.add_argument('--text',default='啊感觉他就是你看');a=p.parse_args()
    out=(a.output or ROOT/'tmp/progressive-v2-theme/motion-runtime'/time.strftime('%H%M%S')).resolve();out.mkdir(parents=True,exist_ok=True)
    theme=json.loads(a.theme.read_text('utf8')) if a.theme else dict(name='Determinism fixture',concept='测试文字 .lettering 与雪痕 .snow-edge',
        palette=dict(primary='#F2EDE4',text='#F2EDE4'),appearance=dict(fontFamily='Smiley Sans, Source Han Sans SC',fontSize=86,bold=False),
        stageHtml='',stageCss='',cueHtml='<div class="slope"><div class="lettering">{{words}}</div><div class="snow-edge"></div></div>',
        cueCss='.wt-cue{position:absolute;inset:0}.slope{position:absolute;bottom:9%;left:20%;width:60%}.lettering{font-family:var(--wt-font);font-size:var(--wt-size);color:#F2EDE4;display:flex;justify-content:center}.snow-edge{height:4px;background:#85ACBC}',
        motionSpec=dict(version=1,runtime='gsap',buildMs=320,resolveMs=180,tracks=[
            dict(selector='.slope',phase='build',start=0,end=1,ease='power2.out',**{'from':dict(x=90,opacity=0),'to':dict(x=0,opacity=1)}),
            dict(selector='.snow-edge',phase='breathe',start=0,end=.15,ease='sine.out',**{'from':dict(scaleX=.7),'to':dict(scaleX=1)}),
            dict(selector='.slope',phase='resolve',start=0,end=1,ease='power2.in',**{'from':dict(x=0,opacity=1),'to':dict(x=120,opacity=0)})]))
    theme=WebThemeDocument.from_dict(theme).to_dict();text=a.text
    service=RendererService();checks={};results={}
    try:
        html=theme_archive_html(theme,sample_text=text,duration_seconds=3,auto_replay=False)
        (out/'theme.html').write_text(html,encoding='utf8');(out/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),encoding='utf8')
        service.live_set(html,width=1920,height=1080)
        forward={}
        for ms in (0,100,200,500,1500,2850,2970,3000):
            png=service.live_pause(cue_ms=ms,stage_ms=ms);(out/f'live-{ms}.png').write_bytes(png)
            forward[ms]=np.array(Image.open(out/f'live-{ms}.png').convert('RGBA'))
        for ms in (1500,200,0,2970,3000):
            png=service.live_pause(cue_ms=ms,stage_ms=ms)
            from io import BytesIO
            reverse=np.array(Image.open(BytesIO(png)).convert('RGBA'))
            diff=np.abs(forward[ms].astype(int)-reverse.astype(int))
            left=forward[ms].astype(float);right=reverse.astype(float)
            left[:,:,:3]*=left[:,:,3:]/255;right[:,:,:3]*=right[:,:,3:]/255
            visible_diff=np.abs(left-right)
            results.setdefault('reverse_differences',[]).append(dict(ms=ms,exact=bool(np.array_equal(forward[ms],reverse)),max_channel=int(diff.max()),alpha_max=int(diff[:,:,3].max()),mean=float(diff.mean()),visible_max=float(visible_diff.max()),visible_mean=float(visible_diff.mean())))
            # Fractional GPU rasterization can change a few edge RGB values;
            # retain exact differences, constrain both mass and coverage, and
            # independently compare six production frames (MAE < 2).
            changed=int(np.count_nonzero(visible_diff.max(axis=2)>1))
            results['reverse_differences'][-1]['pixels_changed_over_one']=changed
            checks[f'reverse_seek_{ms}']=(float(visible_diff.max())<=16 and float(visible_diff.mean())<.001
                and int(diff[:,:,3].max())<=1 and changed<forward[ms].shape[0]*forward[ms].shape[1]*.001)
        checks['hard_end_clear']=not bool(forward[3000][:,:,3].any())
        checks['visible_hold']=int(np.count_nonzero(forward[1500][:,:,3]))>1000
        results['diagnostics']=service._live_request({'type':'live_diagnostics','selectors':['.slope','.lettering','.bear','.snow-edge']},timeout=5)
        diag=results['diagnostics']['diagnostics']
        checks['single_paused_timeline']=len(diag['timelines'])==1 and diag['timelines'][0]['paused']
        checks['no_css_animations']=not diag['animations'];checks['no_script_errors']=not diag['script_errors']
        # Delayed starts previously showed the settled hero before jumping to
        # the declared FROM pose. Correct reverse equality alone missed that.
        for index,track in enumerate(theme['motionSpec']['tracks']):
            if track['phase']!='build' or track['start']<=0:continue
            before_ms=track['start']*min(theme['motionSpec']['buildMs'],600)*.5
            service.live_pause(cue_ms=before_ms,stage_ms=before_ms)
            roots=service._live_request({'type':'live_diagnostics','selectors':[track['selector']]},timeout=5)['diagnostics']['roots']
            node=next(x for x in roots if x['selector']==track['selector'])
            values={k:v for k,v in track['from'].items() if k in ('rotation','xPercent','yPercent')}
            if values:checks[f'delayed_from_pose_{index}']=all(abs(float(node['gsap'][k])-float(v))<.1 for k,v in values.items())
        results['short_cues']=[]
        for span in (100,300,500):
            service.live_text(text='先看这里',duration_ms=span)
            service.live_pause(cue_ms=span*.5,stage_ms=span*.5)
            d=service._live_request({'type':'live_diagnostics','selectors':['.lettering']},timeout=5)['diagnostics']
            tracks=d['motion_map'];build=max((t['end'] for t in tracks if t['phase']=='build'),default=0)
            resolve=min((t['start'] for t in tracks if t['phase']=='resolve'),default=span/1000)
            checks[f'short_{span}_reading']=resolve-build>=span/1000*.65-1e-6 and all(w['opacity']>.9 for w in d['words'])
            results['short_cues'].append(dict(ms=span,map=tracks,words=d['words']))
        long_text='这一手先结算蓝色筹码再叠红色倍率最后抽到稀有牌稳稳拿下整局'
        service.live_text(text=long_text,duration_ms=6000)
        (out/'long-text.png').write_bytes(service.live_pause(cue_ms=1500,stage_ms=1500))
        long_diag=service._live_request({'type':'live_diagnostics','selectors':['.lettering','.bear']},timeout=5)['diagnostics']
        text_nodes=long_diag['words'] or [r for r in long_diag['text_runs'] if r['text']==long_text]
        checks['long_text_intact']=(''.join(w['text'] for w in long_diag['words'])==long_text if long_diag['words'] else len(text_nodes)>=1)
        boxes=[w['rect'] for w in text_nodes]
        checks['long_text_in_frame']=bool(boxes) and all(x>=0 and y>=0 and x+w<=1921 and y+h<=1081 for x,y,w,h in boxes)
        results['long_text']=dict(text=long_text,words=long_diag['words'])
        from twobyteasr.style_recipe import StyleRecipe
        recipe=StyleRecipe(name=theme['name'],engine='remotion',web_theme=theme).to_dict()
        props=dict(schemaVersion=1,width=1920,height=1080,fps=30,durationInFrames=90,
            cues=[dict(id='test',text=text,startMs=0,endMs=3000,styleId='theme',visual=recipe)],recipes=dict(theme=recipe))
        (out/'export-props.json').write_text(json.dumps(props,ensure_ascii=False),encoding='utf8')
        frame_times=[100,200,500,1500,2900,2966.6666666666665]
        service.live_text(text=text,duration_ms=3000)
        for ms in frame_times:(out/f'live-frame-{round(ms*30/1000)}.png').write_bytes(service.live_pause(cue_ms=ms,stage_ms=ms))
        jobs=[RendererJob(str(out/f'export-{round(ms*30/1000)}.png'),props,round(ms*30/1000),job_kind='production') for ms in frame_times]
        rendered=service.render(jobs,timeout=120);results['render_status']=rendered.status;comparisons=[]
        for ms in frame_times:
            frame=round(ms*30/1000);left=np.array(Image.open(out/f'live-frame-{frame}.png').convert('RGBA')).astype(float);right=np.array(Image.open(out/f'export-{frame}.png').convert('RGBA')).astype(float)
            left[:,:,:3]*=left[:,:,3:]/255;right[:,:,:3]*=right[:,:,3:]/255
            mask=np.maximum(left[:,:,3],right[:,:,3])>8;mae=float(np.abs(left-right)[mask].mean()) if mask.any() else 0
            comparisons.append(dict(frame=frame,mae=mae));checks[f'export_parity_{frame}']=mae<2
        results['frames']=comparisons
    finally:
        service.shutdown();results['checks']=checks
        (out/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    print(out);print(json.dumps(checks));assert checks and all(checks.values()),checks


if __name__=='__main__':main()
