"""Real alpha-proxy build/reopen/play and original-source comparison."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from io import BytesIO

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def stats(values):
    values=sorted(values)
    return dict(count=len(values),median=values[len(values)//2],p95=values[min(len(values)-1,int(len(values)*.95))],max=max(values)) if values else {}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp'):raise ValueError('tmp only')
    out.mkdir(parents=True,exist_ok=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'isolation');os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from PIL import Image
    import numpy as np
    from twobyteasr.caption_noita import compose
    from twobyteasr.web_theme import WebThemeDocument,theme_archive_html
    from twobyteasr.live_web_preview import prepare_web_configuration,LiveWebPreviewWorker
    from twobyteasr.caption_proxy import proxy_store,with_quality,CaptionProxyStore
    from twobyteasr.renderer_service import RendererService,GLOBAL_RENDERER_SERVICE
    app=QApplication.instance() or QApplication([])
    theme=WebThemeDocument.from_dict(dict(name='Noita代理验证',id='noita-proxy-audit',**compose(dict(version=8)))).to_dict()
    prepared=prepare_web_configuration(theme,'这瓶药剂，真的能喝吗？',duration_seconds=6)
    store=proxy_store();key=store.ensure(with_quality(prepared,'standard'),960,540)
    end=time.monotonic()+90
    while store.status(key)=='building' and time.monotonic()<end:time.sleep(.1)
    if store.status(key)!='ready':raise AssertionError(store._failed or store.status(key))
    result=dict(checks={},build=store.metrics,alpha_sequence=str(store.root/key),external_model_calls=0)
    service=RendererService()
    try:
        service.live_set(with_quality(prepared,'standard').html,width=960,height=540)
        service.live_text(text=prepared.text,speaker='',duration_ms=6000,placement=prepared.placement)
        differences=[]
        for ms in (0,100,300,1000,3000,5900,5966.6667):
            cached,at=store.frame_at(key,ms)
            source=service.live_frame(cue_ms=at,stage_ms=at)
            a=np.asarray(Image.open(BytesIO(cached))).astype(int);b=np.asarray(Image.open(BytesIO(source))).astype(int)
            differences.append(dict(ms=ms,sampled_ms=at,max=int(np.abs(a-b).max())))
        result['proxy_vs_source']=differences
        result['checks']['proxy_source_max_channel_difference_at_most_one']=all(r['max']<=1 for r in differences)
        fresh=CaptionProxyStore(store.root)
        result['checks']['disk_reopen_same_frame']=fresh.frame_at(key,3000)==store.frame_at(key,3000)
        readings=[]
        for i in range(180):
            start=time.perf_counter();fresh.frame_at(key,i*1000/30);readings.append((time.perf_counter()-start)*1000)
        result['disk_read_ms']=stats(readings)
        times=[];cue_times=[];clock={'start':time.perf_counter(),'paused':False}
        def now():
            ms=(time.perf_counter()-clock['start'])*1000
            return (min(ms,5990),min(ms,5990)+250,not clock['paused'],1)
        worker=LiveWebPreviewWorker(time_provider=now,width=960,height=540,proxy_cache=True,quality='standard')
        worker.frame_ready.connect(lambda frame,cue,stage:(times.append(time.perf_counter()),cue_times.append(cue)),Qt.DirectConnection)
        worker.configure_prepared(prepared);worker.start()
        until=time.monotonic()+5.5
        while time.monotonic()<until:app.processEvents();time.sleep(.004)
        worker.stop();worker._thread.join(timeout=5)
        result['worker_update_interval_ms']=stats([(b-a)*1000 for a,b in zip(times,times[1:])])
        result['worker_metrics']=worker.metrics
        result['checks']['worker_uses_proxy']=len([r for r in worker.metrics if r['phase']=='proxy_frame'])>=140
        result['checks']['ready_playback_does_not_request_browser_frames']=not any(r['phase']=='motion_clock_frame' for r in worker.metrics)
        result['checks']['ordered_cue_frames']=cue_times==sorted(set(cue_times))
        result['quality_tiers']={}
        for quality,width,height in [('draft',640,360),('standard',960,540),('full',1280,720)]:
            derived=with_quality(prepared,quality)
            service.live_set(derived.html,width=width,height=height)
            service.live_text(text=prepared.text,speaker='',duration_ms=6000,placement=prepared.placement)
            png=service.live_frame(cue_ms=900,stage_ms=900)
            (out/f'quality-{quality}.png').write_bytes(png)
            result['quality_tiers'][quality]=dict(width=width,height=height,source_unchanged=prepared.html==with_quality(prepared,'full').html)
        samples=['药！','这瓶药剂，真的能喝吗？','法杖还剩 100 Mana，别乱喝！','先把不稳定药剂倒进去，再换一把法杖，试试看这次炼金反应会不会把整个洞穴炸掉。','没有重点词也要完整保留框和字\n第二行测试中文 ABC 123']
        for index,text in enumerate(samples):
            service.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=1.5,auto_replay=False),width=1920,height=1080)
            png=service.live_frame(cue_ms=700,stage_ms=700)
            (out/f'text-{index}.png').write_bytes(png)
            diagnostics=service._live_request({'type':'live_diagnostics','selectors':['.nt-body','.nt-copy','.nt-runes','.nt-script'],'include_fonts':True},timeout=10)
            (out/f'text-{index}-diagnostics.json').write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2),'utf8')
            image=Image.open(BytesIO(png)).convert('RGBA');box=image.getbbox()
            result['checks']['text_in_stage_'+str(index)]=bool(box and box[0]>0 and box[1]>0 and box[2]<1920 and box[3]<1080)
            Image.alpha_composite(Image.new('RGBA',image.size,'#24272B'),image).convert('RGB').save(out/f'text-{index}.jpg')
        # Same machine / viewport / warm sequential requests: old failed ice vs Noita.
        from twobyteasr.caption_components import compose as any_compose
        result['comparison']={}
        for name,definition in [('ice-v7',dict(version=7)),('noita',dict(version=8))]:
            t=WebThemeDocument.from_dict(dict(name=name,id=name,**any_compose(definition))).to_dict()
            service.live_set(theme_archive_html(t,sample_text=prepared.text,duration_seconds=6,auto_replay=False),width=960,height=540)
            durations=[]
            for i in range(32):
                started=time.perf_counter();service.live_frame(cue_ms=800+i*100,stage_ms=800+i*100)
                if i>=2:durations.append((time.perf_counter()-started)*1000)
            result['comparison'][name]=stats(durations)
            service.live_set(theme_archive_html(t,sample_text=prepared.text,duration_seconds=6,auto_replay=False),width=1920,height=1080)
            rgba=Image.open(BytesIO(service.live_frame(cue_ms=900,stage_ms=900))).convert('RGBA')
            background=Image.open(ROOT/'tmp/noita-20260926/noita-reference-010.jpg').convert('RGBA').resize((1920,1080))
            Image.alpha_composite(background,rgba).convert('RGB').save(out/f'comparison-{name}.jpg')
        result['passed']=all(result['checks'].values())
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps({k:v for k,v in result.items() if k not in ('worker_metrics','build')},ensure_ascii=True),flush=True)
    finally:
        service.shutdown();GLOBAL_RENDERER_SERVICE.shutdown()


if __name__=='__main__':main()
