"""Readable Noita v10 verification: actual Chromium, production movies and PNG proxy."""
import argparse,json,os,sys,time,hashlib,copy
from pathlib import Path
from io import BytesIO

def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Use new repository tmp output')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'isolation');os.environ['QT_QPA_PLATFORM']='offscreen'
    from PIL import Image,ImageChops
    from twobyteasr.caption_components import compose
    from twobyteasr.web_theme import WebThemeDocument,theme_archive_html,export_theme_archive,import_theme_archive
    from twobyteasr.caption_creative_pipeline import ThemeLedger,canonical,digest
    from twobyteasr.authored_preview import render_candidate_preview
    from twobyteasr.renderer_service import RendererService,GLOBAL_RENDERER_SERVICE
    from twobyteasr.live_web_preview import prepare_web_configuration
    from twobyteasr.caption_proxy import CaptionProxyStore
    text='这瓶药剂，真的能喝吗？';report={'kind':'local_fixture','provider_calls':0,'modes':{}};concepts=[]
    service=RendererService()
    try:
        for mode,title in [('alchemy','炼金显形 · 像素余烬'),('mineral','格块落位 · 矿物崩解'),('sigil','符印召唤 · 魔力回收')]:
            folder=out/mode;folder.mkdir()
            theme=WebThemeDocument.from_dict(dict(name='Noita · '+title,**compose(dict(version=10,entryEffect=mode,exitEffect=mode)))).to_dict()
            ledger=ThemeLedger(folder/'source','Noita静态保护与像素动作本地验收')
            ledger.value['candidates']=[dict(id=mode,generated_source=theme,generated_source_hash=digest(canonical(theme)))];ledger.save()
            concept=dict(id=mode,name=theme['name'],composition=title,authored_theme=theme,ledger_path=str(ledger.root/'ledger.json'),creative_version='fixture',provider='local_fixture',raw_prompt_hash=ledger.value['raw_prompt_hash'],technical_status='passed')
            receipt=render_candidate_preview(concept,folder/'preview',text,progress=lambda msg:print(mode,msg,flush=True))
            # Inspect actual encoded preview PNGs as well as the 30fps proxy.
            # A 24fps short movie ends earlier and previously retained pixels.
            movie_tails={}
            for prefix in (mode,mode+'-short'):
                encoded=sorted((folder/'preview'/(prefix+'-transparent')).glob('*.png'))
                assert encoded,(mode,prefix,'missing transparent movie frames')
                assert not Image.open(encoded[-1]).convert('RGBA').getchannel('A').getbbox(),(mode,prefix,'24fps tail')
                movie_tails[prefix]=dict(frames=len(encoded),fps=24,last_alpha_clear=True)
            concept.update(motion_preview=receipt['motion'],preview_picture=receipt['picture'],preview_integrity_verified=True,preview_receipt=receipt)
            concepts.append(concept)
            exported=export_theme_archive(theme,folder/'editable',sample_text=text)
            assert canonical(import_theme_archive(exported/'theme.html'))==canonical(theme)
            service.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=6,auto_replay=False),width=960,height=540)
            # Reverse seeks must reproduce the same alpha and RGB, independent of history.
            samples={};timings=[]
            stamps=[0,50,100,150,220,400,1500,5720,5760,5800,5840,5880,5966.666667,6000]
            for ms in stamps:
                started=time.perf_counter();png=service.live_frame(cue_ms=ms,stage_ms=ms);timings.append((time.perf_counter()-started)*1000)
                samples[ms]=Image.open(BytesIO(png)).convert('RGBA');(folder/f'{ms}.png').write_bytes(png)
            for ms in reversed(stamps):
                actual=Image.open(BytesIO(service.live_frame(cue_ms=ms,stage_ms=ms))).convert('RGBA')
                assert ImageChops.difference(samples[ms],actual).getbbox(alpha_only=False) is None,('seek',mode,ms)
            assert not samples[0].getchannel('A').getbbox() and not samples[5966.666667].getchannel('A').getbbox()
            assert not samples[6000].getchannel('A').getbbox()
            base=WebThemeDocument.from_dict(dict(name='approved v8',**compose(dict(version=8)))).to_dict()
            assert all(base[k]==theme[k] for k in ('cueHtml','cueCss','stageHtml','stageCss','appearance','palette'))
            service.live_set(theme_archive_html(base,sample_text=text,duration_seconds=6,auto_replay=False),width=960,height=540)
            hold=Image.open(BytesIO(service.live_frame(cue_ms=1500,stage_ms=1500))).convert('RGBA')
            # Breath phases intentionally begin later; static source must remain exact.
            # Also compare the two no-motion static renders (same original nodes).
            settled=[]
            for value in (base,theme):
                static=copy.deepcopy(value);static.pop('motionSpec',None)
                service.live_set(theme_archive_html(static,sample_text=text,duration_seconds=6,auto_replay=False),width=960,height=540)
                settled.append(Image.open(BytesIO(service.live_frame(cue_ms=1500,stage_ms=1500))).convert('RGBA'))
            assert ImageChops.difference(*settled).getbbox(alpha_only=False) is None,('static source render changed',mode)
            # Very short cues use the original settled artwork, not particles.
            short_images=[]
            for value in (base,theme):
                service.live_set(theme_archive_html(value,sample_text='药剂 99%！',duration_seconds=.1,auto_replay=False),width=960,height=540)
                short_images.append(Image.open(BytesIO(service.live_frame(cue_ms=50,stage_ms=50))).convert('RGBA'))
            assert all(im.getchannel('A').getbbox() for im in short_images),('100ms readable hold',mode)
            # Production proxy uses the same clock with the editable source.
            prepared=prepare_web_configuration(theme,text,duration_seconds=1.5)
            store=CaptionProxyStore(folder/'proxy');key=store.ensure(prepared,960,540)
            start=time.monotonic()
            while store.status(key)=='building' and time.monotonic()-start<180:time.sleep(.1)
            assert store.status(key)=='ready',(mode,'proxy',store.metrics)
            service.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=1.5,auto_replay=False),width=960,height=540)
            for ms in [0,100,500,1400,1466.666667]:
                proxy=store.frame_at(key,ms);assert proxy
                # QImage pixels are decoded from the exact PNG manifest; compare raw files below.
                index=int(ms*30/1000)
                actual=Image.open(BytesIO(service.live_frame(cue_ms=index*1000/30,stage_ms=index*1000/30))).convert('RGBA')
                saved=Image.open(folder/'proxy'/key/f'{index:04}.png').convert('RGBA')
                assert ImageChops.difference(saved,actual).getbbox(alpha_only=False) is None,('proxy differs',mode,ms)
                if index==44:assert not saved.getchannel('A').getbbox(),('short last frame',mode)
            from twobyteasr.theme_direction_preview import render_motion_preview
            compact=render_motion_preview(service,theme_archive_html(theme,sample_text=text,duration_seconds=2.4,auto_replay=False),folder/'preview',mode+'-compact',duration_ms=2400)
            last=sorted(Path(compact['transparent_frames']).glob('*.png'))[-1]
            assert not Image.open(last).convert('RGBA').getchannel('A').getbbox(),('compact tail',mode)
            report['modes'][mode]=dict(compact_motion=compact,validation=receipt['validation'],editable=str(exported),motion=receipt['motion'],short_motion=receipt.get('short_motion'),movie_tails=movie_tails,seek_exact=True,static_source_and_render_exact=True,proxy_exact=True,live_render_ms=timings,proxy_metrics=store.metrics)
            (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
        report['passed']=True
        (out/'concepts.json').write_text(json.dumps(concepts,ensure_ascii=False,indent=2),'utf8')
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    finally:
        service.shutdown();GLOBAL_RENDERER_SERVICE.shutdown()
    print(json.dumps({'passed':True,'output':str(out)}),flush=True)
if __name__=='__main__':main()
