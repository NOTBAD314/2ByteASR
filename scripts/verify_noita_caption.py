"""Produce inspectable source/pixels through the real renderer, without provider calls."""
import argparse
import json
import os
from pathlib import Path
import sys
from io import BytesIO
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--movies', action='store_true')
    args = p.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp'):
        raise ValueError('Output must be under tmp')
    out.mkdir(parents=True, exist_ok=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out/'isolation')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PIL import Image, ImageDraw
    from twobyteasr.caption_noita import compose, DIRECTIONS
    from twobyteasr.web_theme import WebThemeDocument, theme_archive_html, export_theme_archive
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.theme_direction_preview import render_motion_preview
    text = '这瓶药剂，真的能喝吗？'
    result = dict(origin='Codex original component implementation', external_model_calls=0, directions={}, checks={})
    service = RendererService()
    try:
        for direction in DIRECTIONS:
            theme = WebThemeDocument.from_dict(dict(id='noita-'+direction+'-v1', name='Noita · '+direction, notes='原创像素炼金字幕；无游戏美术资源', **compose(dict(version=8,direction=direction,emphasis=['药剂'])))).to_dict()
            folder = out/direction
            folder.mkdir(exist_ok=True)
            (folder/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),'utf8')
            export_theme_archive(theme, folder/'archive',sample_text=text)
            page = theme_archive_html(theme,sample_text=text,duration_seconds=6,auto_replay=False)
            service.live_set(page,width=1920,height=1080)
            png = service.live_frame(cue_ms=900,stage_ms=900)
            (folder/'transparent.png').write_bytes(png)
            im = Image.open(BytesIO(png)).convert('RGBA')
            bbox = im.getbbox()
            for name,color in [('neutral','#24272B'),('light','#D7D8CD'),('dark','#07090A')]:
                Image.alpha_composite(Image.new('RGBA',im.size,color),im).convert('RGB').save(folder/(name+'.jpg'))
            if bbox:
                box=(max(0,bbox[0]-24),max(0,bbox[1]-24),min(1920,bbox[2]+24),min(1080,bbox[3]+24))
                Image.alpha_composite(Image.new('RGBA',im.size,'#24272B'),im).crop(box).save(folder/'detail.png')
            result['directions'][direction]=dict(bbox=bbox,html_bytes=len(theme['cueHtml'].encode()),tracks=len(theme['motionSpec']['tracks']))
            print(direction,bbox,flush=True)
            if direction == 'reaction':
                if args.movies:
                    for duration in (6000,1500):
                        page=theme_archive_html(theme,sample_text=text,duration_seconds=duration/1000,auto_replay=False)
                        result[str(duration)]=render_motion_preview(service,page,folder,'reaction-'+str(duration),duration_ms=duration)
                service.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=6,auto_replay=False),width=960,height=540)
                reference={}
                for ms in (0,100,300,900,3000,5700,5966.667,6000):
                    reference[ms]=service.live_frame(cue_ms=ms,stage_ms=ms)
                result['checks']['first_last_clear']=all(Image.open(BytesIO(reference[ms])).getchannel('A').getbbox() is None for ms in (0,5966.667,6000))
                for ms in (3000,100,5700,900,0,6000,300):
                    other=service.live_frame(cue_ms=ms,stage_ms=ms)
                    result['checks']['seek_'+str(ms)]=Image.open(BytesIO(other)).tobytes()==Image.open(BytesIO(reference[ms])).tobytes()
                    import numpy as np
                    delta=np.abs(np.asarray(Image.open(BytesIO(other))).astype(int)-np.asarray(Image.open(BytesIO(reference[ms]))).astype(int))
                    result.setdefault('seek_difference',{})[str(ms)]=dict(max=int(delta.max()),pixels=int(np.count_nonzero(delta.max(axis=2))))
                    (folder/('seek-'+str(ms)+'-a.png')).write_bytes(reference[ms])
                    (folder/('seek-'+str(ms)+'-b.png')).write_bytes(other)
                durations=[]
                for i in range(24):
                    start=time.perf_counter(); service.live_frame(cue_ms=1000+i*40,stage_ms=1000+i*40); durations.append((time.perf_counter()-start)*1000)
                result['live_frame_ms']=dict(samples=durations,median=sorted(durations)[12],p95=sorted(durations)[22],max=max(durations))
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    finally:
        service.shutdown()


if __name__=='__main__':
    main()
