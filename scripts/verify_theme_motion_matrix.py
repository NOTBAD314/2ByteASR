"""Render an existing source at real cue durations using the production clock."""
import argparse
from io import BytesIO
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--theme',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--text',required=True)
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp'):raise ValueError('Use repository tmp')
    out.mkdir(parents=True,exist_ok=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'isolation')
    from twobyteasr.test_isolation import install
    install()
    from PIL import Image
    from twobyteasr.web_theme import WebThemeDocument,theme_archive_html,export_theme_archive
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.theme_direction_preview import render_motion_preview
    from twobyteasr.web_theme_fonts import font_use_receipt
    theme=WebThemeDocument.from_dict(json.loads(args.theme.read_text('utf8'))).to_dict()
    (out/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),'utf8')
    result=dict(source=str(args.theme.resolve()),provider_calls=0,checks={},durations={})
    service=RendererService()
    try:
        for duration in (1400,2000,6000):
            folder=out/str(duration);folder.mkdir(exist_ok=True)
            html=theme_archive_html(theme,sample_text=args.text,duration_seconds=duration/1000,auto_replay=False)
            service.live_set(html,width=960,height=540)
            last_encoded=(math.ceil(duration*24/1000)-1)*1000/24
            stamps=[0,80,160,300,500,duration/2,duration-200,duration-80,last_encoded,duration]
            frames={};cost=[]
            for stamp in stamps:
                started=time.perf_counter()
                png=service.live_pause(cue_ms=stamp,stage_ms=stamp)
                cost.append((time.perf_counter()-started)*1000)
                im=Image.open(BytesIO(png)).convert('RGBA');frames[stamp]=im
                im.save(folder/f'{round(stamp)}.png')
            hero=frames[duration/2]
            Image.alpha_composite(Image.new('RGBA',hero.size,'#20262e'),hero).convert('RGB').save(folder/'hero.png')
            # Check state after seeking both forwards and backwards, including replay.
            first=service.live_pause(cue_ms=300,stage_ms=300)
            service.live_pause(cue_ms=duration-60,stage_ms=duration-60)
            second=service.live_pause(cue_ms=300,stage_ms=300)
            service.live_pause(cue_ms=0,stage_ms=0)
            third=service.live_pause(cue_ms=300,stage_ms=300)
            service.live_pause(cue_ms=duration/2,stage_ms=duration/2)
            diag=service._live_request({'type':'live_diagnostics','include_fonts':True},timeout=15)['diagnostics']
            fonts=font_use_receipt(theme.get('appearance',{}).get('fontFamily',''),diag)
            checks=dict(start_clear=not frames[0].getchannel('A').getbbox(),
                end_clear=not frames[duration].getchannel('A').getbbox(),
                last_encoded_clear=not frames[last_encoded].getchannel('A').getbbox(),
                hero_visible=bool(hero.getchannel('A').getbbox()),seek_repeat_equal=first==second==third,
                fonts_ready=diag.get('fonts_ready') and not diag.get('script_errors'),
                caption_fits=not diag.get('caption_layout',{}).get('overflow'))
            movie=render_motion_preview(service,html,folder,'preview',duration_ms=duration,progress=print)
            result['durations'][str(duration)]=dict(checks=checks,font_use=fonts,movie=movie,
                capture_ms=dict(median=statistics.median(cost),p95=sorted(cost)[int((len(cost)-1)*.95)],maximum=max(cost)))
            result['checks'].update({str(duration)+'_'+k:bool(v) for k,v in checks.items()})
            (folder/'diagnostics.json').write_text(json.dumps(diag,ensure_ascii=False,indent=2),'utf8')
        result['archive']=str(export_theme_archive(theme,out/'archives'))
        result['passed']=all(result['checks'].values())
    finally:
        service.shutdown()
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result['passed'],checks=result['checks'],archive=result['archive'])))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
