"""Six deterministic LIVE vs production-renderer frames and short/long cues."""
import sys,json,time,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    from twobyteasr.web_theme import builtin_web_themes,theme_archive_html
    from twobyteasr.renderer_service import RendererService,RendererJob
    from PIL import Image
    import numpy as np
    out=ROOT/'tmp/balatro-frames'/time.strftime('%Y%m%d-%H%M%S');out.mkdir(parents=True)
    theme=builtin_web_themes()['balatro-joker'].to_dict()
    text='跳过几个条件';width,height,fps=1920,1080,30;duration=4
    frames=[3,8,14,48,110,119]
    props={'schemaVersion':1,'width':width,'height':height,'fps':fps,'durationInFrames':120,
        'cues':[{'id':'verify','text':text,'speaker':'','startMs':0,'endMs':4000,'styleId':'balatro',
                 'visual':{'webTheme':theme}}], 'recipes':{'balatro':{'webTheme':theme}}}
    (out/'export-props.json').write_text(json.dumps(props,ensure_ascii=False),encoding='utf-8')
    (out/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),encoding='utf-8')
    service=RendererService();results={'frames':[],'cases':[]}
    try:
        service.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=duration,auto_replay=False),width=width,height=height)
        for frame in frames:
            png=service.live_pause(cue_ms=frame/fps*1000,stage_ms=frame/fps*1000)
            (out/f'live-{frame:03}.png').write_bytes(png)
        results['diagnostics']=service._live_request({'type':'live_diagnostics',
            'selectors':['.balatro-plate','.chips-stack','.mult-flame','.joker-bell','.foil-shimmer','.card-slider','.line']},timeout=3)
        jobs=[RendererJob(str(out/f'export-{frame:03}.png'),props,frame,job_kind='production') for frame in frames]
        result=service.render(jobs,timeout=120)
        results['render_status']=result.status
        for frame in frames:
            a=np.array(Image.open(out/f'live-{frame:03}.png').convert('RGBA')).astype(float)
            b=np.array(Image.open(out/f'export-{frame:03}.png').convert('RGBA')).astype(float)
            # Compare premultiplied RGBA, excluding irrelevant RGB at alpha=0.
            a[:,:,:3]*=a[:,:,3:]/255;b[:,:,:3]*=b[:,:,3:]/255
            delta=np.abs(a-b); mask=np.maximum(a[:,:,3],b[:,:,3])>8
            results['frames'].append({'frame':frame,'mae_visible':float(delta[mask].mean()) if mask.any() else 0,
                'different_pixels':int((delta.max(axis=2)>8).sum()),
                'edge_alpha_max':float(max(a[0,:,3].max(),a[-1,:,3].max(),a[:,0,3].max(),a[:,-1,3].max()))})
        for span,words in [(100,'短句'),(300,'短句'),(500,'短句'),(4000,'就算这句话很长也应该完整呈现每一个中文字，不应裁掉后半句')]:
            service.live_text(text=words,duration_ms=span)
            for ratio in (.15,.5,.95):
                png=service.live_pause(cue_ms=span*ratio,stage_ms=span*ratio)
                (out/f'case-{span}-{int(ratio*100)}.png').write_bytes(png)
            results['cases'].append(service._live_request({'type':'live_diagnostics',
                'selectors':['.balatro-plate','.line']},timeout=3))
    finally:
        service.shutdown()
        (out/'comparison.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print('EVIDENCE',out,flush=True)
        print(json.dumps(results.get('frames',[])),flush=True)

if __name__=='__main__':main()
