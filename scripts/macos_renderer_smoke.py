"""Actual packaged Remotion compositor, motion, alpha and 12-second export."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.macos_build import finder_environment
from twobyteasr.rendering.platform_browser import bundled_browser

JAVASCRIPT=r'''
const fs=require('node:fs'); const path=require('node:path');
const {createRequire}=require('node:module');
const cfg=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const requireApp=createRequire(path.join(cfg.renderer,'package.json'));
const {bundle}=requireApp('@remotion/bundler');
const {selectComposition,renderStill,renderMedia}=requireApp('@remotion/renderer');
(async()=>{
 const serveUrl=await bundle({entryPoint:path.join(cfg.renderer,'src/index.ts'),outDir:path.join(cfg.out,'bundle'),
   onProgress:()=>{},webpackOverride:(c)=>({...c,cache:false})});
 const options={serveUrl,id:'SubtitleOverlay',inputProps:cfg.props,browserExecutable:cfg.browser,
   binariesDirectory:path.join(cfg.renderer,'node_modules/@remotion/compositor-darwin-arm64'),logLevel:'error'};
 const composition=await selectComposition(options);
 for(const frame of [0,90,359]) await renderStill({...options,composition,frame,
   output:path.join(cfg.out,`frame-${frame}.png`),imageFormat:'png'});
 await renderMedia({...options,composition,outputLocation:path.join(cfg.out,'animation.mov'),
   codec:'prores',proResProfile:'4444',pixelFormat:'yuva444p10le',imageFormat:'png',concurrency:1});
})().catch(e=>{console.error(e);process.exitCode=1;});
'''


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(argv);out=args.output.resolve()
    if sys.platform!='darwin' or out.exists() or 'tmp' not in out.parts:raise SystemExit('Use a fresh native tmp output')
    out.mkdir(parents=True);resources=args.app/'Contents/Resources';renderer=resources/'renderer'
    node=resources/'tools/node/node';ffmpeg=resources/'tools/ffmpeg/bin/ffmpeg';ffprobe=resources/'tools/ffmpeg/bin/ffprobe'
    recipe=dict(name='Mac compatibility smoke',components=['fill','stroke','motion'],
        typography=dict(fontFamily='Source Han Sans SC',fontSize=36,bold=True,italic=False,spacing=0),
        fill=dict(type='solid',color='#ffffff'),strokes=[dict(color='#ff000000',width=2)],
        glow=dict(color='#ffffff',blur=0,opacity=0),
        shadow=dict(enabled=False,color='#000000',opacity=0,offsetX=0,offsetY=0,blur=0,spread=0),
        background=dict(enabled=False,type='solid',color='#000000',opacity=0,gradient=dict(colors=[],angle=0),
            paddingX=0,paddingY=0,radius=0,border=dict(color='#000000',width=0),shadow=dict(color='#000000',offsetX=0,offsetY=0,blur=0),
            texture=dict(type='none',opacity=0,scale=1,seed=0),transform=dict(rotation=0,scale=1,offsetX=0,offsetY=0)),
        mask=dict(type='none',softness=0,direction='left'),decorations=[],
        motion=dict(mode='explicit',entrance=dict(type='fade',duration_ms=600),hold=dict(type='none'),exit=dict(type='fade',duration_ms=600)),
        layout=dict(alignment=2,positionX=320,positionY=290,playResX=640,playResY=360,anchorX=.5,anchorY=1))
    props=dict(schemaVersion=1,width=640,height=360,fps=30,durationInFrames=360,
               cues=[dict(id='smoke',text='兔白字幕 · Mac 动效验证',startMs=0,endMs=12000,styleId='smoke')],recipes=dict(smoke=recipe))
    config=dict(renderer=str(renderer),browser=str(bundled_browser(renderer)),out=str(out),props=props)
    (out/'config.json').write_text(json.dumps(config,ensure_ascii=False),'utf8')
    (out/'render.cjs').write_text(JAVASCRIPT,'utf8')
    env=finder_environment(out/'profile');env['DYLD_BIND_AT_LAUNCH']='1'
    result=dict(passed=False,renderer='packaged production SubtitleOverlay',duration_s=12,frames=360)
    try:
        with (out/'render.log').open('wb') as log:
            subprocess.run([str(node),str(out/'render.cjs'),str(out/'config.json')],cwd=out,env=env,
                           stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
        movie=out/'animation.mov'
        info=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-count_frames','-show_streams','-of','json',str(movie)],env=env))
        stream=next(s for s in info['streams'] if s['codec_type']=='video')
        if int(stream['nb_read_frames'])!=360 or not stream['pix_fmt'].startswith('yuva'):raise RuntimeError('Wrong frame count or missing alpha')
        alpha=[]
        for frame in (0,90,359):
            pixels=subprocess.check_output([str(ffmpeg),'-v','error','-i',str(out/f'frame-{frame}.png'),
                '-vf','scale=64:36','-frames:v','1','-f','rawvideo','-pix_fmt','rgba','-'],env=env)
            alpha.append(sum(pixels[3::4]))
        if not (alpha[1]>0 and alpha[0]<alpha[1] and alpha[2]<alpha[1]):raise RuntimeError('Motion entrance / exit or visible text failed')
        result.update(passed=True,stream=stream,alpha_sums=alpha,all_frames_decoded=True)
    except Exception:result['error']=traceback.format_exc()
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
