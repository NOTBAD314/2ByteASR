"""Same-machine HTML/proxy playback and a real transparent ProRes comparison."""
import argparse,json,os,sys,time,statistics,hashlib,subprocess
from pathlib import Path
from io import BytesIO
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def stats(values):
    values=sorted(values)
    return dict(n=len(values),median=statistics.median(values),p95=values[int((len(values)-1)*.95)],maximum=max(values)) if values else {}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--theme',type=Path,required=True)
    parser.add_argument('--original',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp'):raise ValueError('Use workspace tmp')
    out.mkdir(parents=True,exist_ok=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'isolation')
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PIL import Image
    import numpy as np
    from twobyteasr.live_web_preview import prepare_web_configuration,LiveWebPreviewWorker
    from twobyteasr.caption_proxy import proxy_store
    from twobyteasr.renderer_service import RendererService,GLOBAL_RENDERER_SERVICE
    from twobyteasr.processes import run_hidden_subprocess
    app=QApplication.instance() or QApplication([]);result=dict(checks={},provider_calls=0,playback={})
    theme=json.loads(args.theme.read_text('utf8'));original=json.loads(args.original.read_text('utf8'))
    prepared=prepare_web_configuration(theme,'我很喜欢她这一套衣服',duration_seconds=6)
    store=proxy_store();key=store.ensure(prepared,960,540)
    end=time.monotonic()+100
    while store.status(key)=='building' and time.monotonic()<end:time.sleep(.05)
    if store.status(key)!='ready':raise AssertionError(store._failed or store.status(key))
    result['proxy_build']=store.metrics;sequence=store.root/key
    result['proxy_bytes']=sum(p.stat().st_size for p in sequence.glob('*.png'))
    result['alpha_sequence']=str(sequence)
    service=RendererService()
    try:
        service.live_set(prepared.html,width=960,height=540)
        service.live_text(text=prepared.text,speaker='',duration_ms=6000,placement=prepared.placement)
        differences=[]
        for ms in [0,100,300,1000,3000,5966.667,0,300,1000,100]:
            png,at=store.frame_at(key,ms)
            actual=service.live_frame(cue_ms=at,stage_ms=at)
            a=np.asarray(Image.open(BytesIO(png))).astype(int);b=np.asarray(Image.open(BytesIO(actual))).astype(int)
            delta=np.max(np.abs(a-b),axis=2)
            box_a=Image.open(BytesIO(png)).getchannel('A').getbbox()
            box_b=Image.open(BytesIO(actual)).getchannel('A').getbbox()
            box_delta=max(abs(x-y) for x,y in zip(box_a,box_b)) if box_a and box_b else 0 if box_a==box_b else 999
            differences.append(dict(ms=ms,max=int(delta.max()),changed_over_3=int((delta>3).sum()),
                canvas_fraction=float((delta>3).mean()),bounds_delta=box_delta))
        result['proxy_source_differences']=differences
        result['strict_pixel_equality']=all(x['max']==0 for x in differences)
        # Chromium's clipped subpixel edges can rasterize differently after a
        # jump despite identical DOM. Record the strict failure and separately
        # check pose/coverage; do not label this bit-identical rendering.
        result['checks']['proxy_and_live_pose_and_coverage_match']=all(x['bounds_delta']<=1 and x['canvas_fraction']<.002 for x in differences)
        for label,source,cache in [('before-original-html',original,False),('same-artwork-html',theme,False),('after-editable-proxy',theme,True)]:
            config=prepare_web_configuration(source,prepared.text,duration_seconds=6)
            captured=[];clock=dict(playing=False,start=0);configured=[]
            def now():
                ms=(time.perf_counter()-clock['start'])*1000 if clock['playing'] else 0
                return (min(ms,5999),min(ms,5999)+250,clock['playing'],1)
            worker=LiveWebPreviewWorker(time_provider=now,width=960,height=540,proxy_cache=cache,quality='full')
            worker.configured.connect(lambda _:configured.append(True),Qt.DirectConnection)
            worker.frame_ready.connect(lambda data,cue,stage:captured.append((time.perf_counter(),cue,bytes(data))),Qt.DirectConnection)
            worker.configure_prepared(config);worker.start()
            until=time.monotonic()+15
            while not captured and time.monotonic()<until:app.processEvents();time.sleep(.002)
            captured.clear();clock['start']=time.perf_counter();clock['playing']=True
            until=clock['start']+6.05
            while time.perf_counter()<until:app.processEvents();time.sleep(.002)
            worker.stop();worker._thread.join(timeout=5)
            result['playback'][label]=dict(frames=len(captured),update_ms=stats([(b[0]-a[0])*1000 for a,b in zip(captured,captured[1:])]),
                cue_ms=[round(r[1],2) for r in captured],metrics=worker.metrics,
                first_frame_ms=(captured[0][0]-clock['start'])*1000 if captured else None)
            folder=out/label;folder.mkdir(exist_ok=True)
            # Reconstruct actual delivered samples at normal speed; repeated
            # output frames expose stalls, instead of smoothing them away.
            cursor=0
            for index in range(180):
                target=clock['start']+index/30
                while cursor+1<len(captured) and captured[cursor+1][0]<=target:cursor+=1
                foreground=Image.open(BytesIO(captured[cursor][2])).convert('RGBA')
                Image.alpha_composite(Image.new('RGBA',foreground.size,'#20272e'),foreground).convert('RGB').save(folder/f'{index:04}.png')
            run_hidden_subprocess([ROOT/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-y','-framerate','30','-i',folder/'%04d.png',
                '-c:v','libx264','-preset','fast','-crf','16','-pix_fmt','yuv420p',out/(label+'.mp4')],capture_output=True,check=True,timeout=30,purpose='normal-speed measured caption replay')
        before=result['playback']['same-artwork-html'];after=result['playback']['after-editable-proxy']
        result['checks']['proxy_delivers_more_frames']=after['frames']>before['frames']*1.3
        result['checks']['proxy_intervals_improve']=after['update_ms']['p95']<before['update_ms']['p95']
        ffmpeg=ROOT/'tools/ffmpeg/bin/ffmpeg.exe';mov=out/'transparent-prores4444.mov'
        started=time.perf_counter()
        run_hidden_subprocess([ffmpeg,'-v','error','-y','-framerate','30','-i',sequence/'%04d.png','-c:v','prores_ks',
            '-profile:v','4','-pix_fmt','yuva444p10le','-alpha_bits','16',mov],capture_output=True,check=True,timeout=60,purpose='real transparent MOV comparison')
        result['mov']=dict(path=str(mov),bytes=mov.stat().st_size,encode_seconds=time.perf_counter()-started,
            render_first_required=True,editable_text=False)
        alpha=out/'mov-alpha.png'
        run_hidden_subprocess([ffmpeg,'-v','error','-y','-ss','3','-i',mov,'-vf','alphaextract','-frames:v','1',alpha],capture_output=True,check=True,timeout=20,purpose='verify actual MOV alpha')
        extrema=Image.open(alpha).convert('L').getextrema()
        result['checks']['mov_alpha_contains_clear_and_opaque']=extrema==(0,255)
        started=time.perf_counter()
        run_hidden_subprocess([ffmpeg,'-v','error','-i',mov,'-f','null','-'],capture_output=True,check=True,timeout=30,purpose='full transparent MOV decode')
        result['mov']['full_decode_seconds']=time.perf_counter()-started
        result['passed']=all(result['checks'].values())
    finally:
        service.shutdown();GLOBAL_RENDERER_SERVICE.shutdown()
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'playback'}},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
