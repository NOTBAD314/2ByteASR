"""Reproduce CUDA alpha/chroma errors and verify opaque-patch composition.

This is an isolated experiment, not an export route. Canonical straight RGBA
layout/outline/shadow/glow and RGB blending remain on the production path;
CUDA receives an already opaque, even-aligned YUV patch. No subtitle alpha is
subsampled before blending. Results include local glyph/edge error, not just
a full-canvas average. Run only with no other performance workload.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        raise ValueError('Use a new tmp directory')
    out.mkdir(parents=True)
    sys.path.insert(0, str(root))
    import av
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    from twobyteasr.exports.caption_composite_region import append_region_overlay
    width, height = 640, 360
    w, h = 270, 94
    font = ImageFont.truetype(str(root/'assets/fonts/SourceHanSansSC-Medium.otf'), 39)
    results = []
    for pose, x, y, opacity in [('entry', 101, 213, .27), ('hold', 103, 209, 1.), ('exit', 109, 207, .11)]:
        mask = Image.new('L', (w,h))
        draw = ImageDraw.Draw(mask)
        draw.text((18,4), '兔白字幕 Aa', font=font, fill=255, stroke_width=2)
        alpha = np.asarray(mask)
        gradient = np.zeros((h,w,4), np.uint8)
        gradient[:,:,:3] = np.stack([np.linspace(245,45,w),np.linspace(90,210,w),np.linspace(80,250,w)],axis=1)[None,:,:]
        gradient[:,:,3] = alpha
        glyph = Image.fromarray(gradient)
        glow = Image.new('RGBA', (w,h), (30,130,220,0))
        glow.putalpha(mask.filter(ImageFilter.GaussianBlur(4)).point(lambda v:round(v*.55)))
        shadow = Image.new('RGBA', (w,h), (0,0,0,0))
        shadow.paste((0,0,0,190),(4,5,w,h), mask.crop((0,0,w-4,h-5)).filter(ImageFilter.GaussianBlur(1)))
        pixels = Image.alpha_composite(Image.alpha_composite(shadow,glow),glyph)
        pixels.putalpha(pixels.getchannel('A').point(lambda v:round(v*opacity)))
        path = out/f'{pose}.png'; pixels.save(path)
        filters = []
        label = append_region_overlay(filters,'[0:v]','[1:v]',bounds=(x,y,x+w,y+h),
            width=width,height=height,pixel_format='yuv420p',tag='reference')
        graphs = [('reference',';'.join(filters),label)]
        graphs.append(('subsampled_alpha',f'[0:v]format=yuv420p,hwupload_cuda[main];'
            f'[1:v]format=yuva420p,hwupload_cuda[pixels];'
            f'[main][pixels]overlay_cuda=x={x}:y={y},hwdownload,format=yuv420p[result]','[result]'))
        rx,ry=max(0,(x-8)//2*2),max(0,(y-8)//2*2)
        rr,rb=min(width,(x+w+9)//2*2),min(height,(y+h+9)//2*2)
        graphs.append(('opaque_patch',f'[0:v]split=2[maincpu][area];'
            f'[maincpu]format=yuv420p,hwupload_cuda[main];'
            f'[area]crop={rr-rx}:{rb-ry}:{rx}:{ry},format=rgba[rgb];'
            f'[rgb][1:v]overlay=x={x-rx}:y={y-ry}:format=auto,format=yuv420p,hwupload_cuda[patch];'
            f'[main][patch]overlay_cuda=x={rx}:y={ry},hwdownload,format=yuv420p[result]','[result]'))
        images={}
        for name,graph,label in graphs:
            command=[str(args.ffmpeg.resolve()),'-hide_banner','-loglevel','verbose','-y',
                '-init_hw_device','cuda=gpu','-filter_hw_device','gpu','-filter_complex_threads','1',
                '-f','lavfi','-i',f'testsrc2=s={width}x{height}:r=30:d=1','-i',str(path),
                '-filter_complex',graph,'-map',label,'-frames:v','1','-pix_fmt','yuv420p','-f','rawvideo','pipe:1']
            started=time.monotonic()
            process=subprocess.run(command,capture_output=True,creationflags=0x08000000)
            (out/f'{pose}-{name}.log').write_bytes(process.stderr)
            row=dict(pose=pose,route=name,command=command,seconds=time.monotonic()-started,code=process.returncode)
            if not process.returncode:
                raw=np.frombuffer(process.stdout,np.uint8).reshape(height*3//2,width)
                image=av.VideoFrame.from_ndarray(raw,format='yuv420p').to_ndarray(format='rgb24')
                images[name]=image
                Image.fromarray(image).save(out/f'{pose}-{name}.png')
                if name!='reference':
                    delta=np.abs(image.astype(int)-images['reference'].astype(int))
                    local=delta[y:y+h,x:x+w]
                    edge=(np.asarray(pixels.getchannel('A'))>0)&(np.asarray(pixels.getchannel('A'))<255)
                    row.update(canvas_mae=float(delta.mean()),subtitle_mae=float(local.mean()),
                        edge_mae=float(local[edge].mean()),subtitle_max=int(local.max()),
                        full_max=int(delta.max()),different_pixels=int(np.any(delta,axis=2).sum()))
            results.append(row)
    passed=all(r['code']==0 and r.get('full_max',0)==0 for r in results if r['route']=='opaque_patch')
    report=dict(passed=passed,results=results,production_enabled=False,
        limits='GPU composites the exact completed opaque patch; layout and straight RGBA blend stay on CPU. '
               'No scaling or HDR/10-bit claim. Extra upload is not assumed faster; production remains existing compositor.')
    (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
