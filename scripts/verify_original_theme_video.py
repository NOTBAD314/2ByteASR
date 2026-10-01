"""Actual ProRes export of the unchanged original; decode and compare six frames."""
import argparse
import json
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('evidence',type=Path)
    parser.add_argument('--media',type=Path,required=True)
    args=parser.parse_args()
    from twobyteasr.processes import run_hidden_subprocess
    from PIL import Image
    import numpy as np
    out=args.evidence.resolve();renderer=ROOT/'renderer'
    mov=out/'Death-Stranding-Original.mov'
    if mov.exists():raise FileExistsError(mov)
    if not (out/'export-props.json').exists():
        theme=json.loads((out/'theme.json').read_text(encoding='utf8'))
        props=dict(schemaVersion=1,width=1280,height=720,fps=30,durationInFrames=90,
            cues=[dict(id='original',text='我送的不是货，是整个人类的希望',speaker='企鹅带带北极熊',
                startMs=0,endMs=3000,styleId='original',visual={'webTheme':theme})],
            recipes={'original':{'webTheme':theme}})
        (out/'export-props.json').write_text(json.dumps(props,ensure_ascii=False),encoding='utf8')
    command=['node',str(renderer/'node_modules/@remotion/cli/remotion-cli.js'),'render','src/index.ts',
        'SubtitleOverlay',str(mov),f'--props={out / "export-props.json"}','--codec=prores','--prores-profile=4444',
        '--pixel-format=yuva444p10le','--image-format=png','--concurrency=2',
        r'--browser-executable=C:\Program Files\Google\Chrome\Application\chrome.exe']
    started=time.perf_counter()
    result=run_hidden_subprocess(command,cwd=renderer,capture_output=True,text=True,timeout=240,check=False,
        purpose='original theme actual transparent export')
    (out/'video-render.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf8')
    result.check_returncode()
    ffmpeg=ROOT/'tools/ffmpeg/bin/ffmpeg.exe';frames=[1,5,12,45,84,89]
    expression='+'.join(f'eq(n,{f})' for f in frames).replace(',',r'\,')
    run_hidden_subprocess([str(ffmpeg),'-v','error','-n','-i',str(mov),'-vf',f'select={expression}',
        '-fps_mode','passthrough','-pix_fmt','rgba',str(out/'decoded-%02d.png')],timeout=60,check=True,
        purpose='decode actual exported six frames')
    stats=[]
    for index,frame in enumerate(frames,1):
        a=np.array(Image.open(out/f'live-{frame:03}.png').convert('RGBA')).astype(float)
        b=np.array(Image.open(out/f'decoded-{index:02}.png').convert('RGBA')).astype(float)
        a[:,:,:3]*=a[:,:,3:]/255;b[:,:,:3]*=b[:,:,3:]/255
        mask=np.maximum(a[:,:,3],b[:,:,3])>8;delta=np.abs(a-b)
        stats.append(dict(frame=frame,mae_visible=float(delta[mask].mean()),different_pixels=int((delta.max(axis=2)>8).sum())))
    run_hidden_subprocess([str(ffmpeg),'-v','error','-n','-t','3','-i',str(args.media.resolve()),'-i',str(mov),
        '-filter_complex','[0:v]scale=1280:720[bg];[bg][1:v]overlay=format=auto:shortest=1,format=yuv420p',
        '-c:v','libx264','-crf','18','-preset','fast','-an',str(out/'Death-Stranding-Original.mp4')],
        timeout=60,check=True,purpose='composite real recording with actual exported theme')
    evidence=dict(render_seconds=time.perf_counter()-started,mov_bytes=mov.stat().st_size,frames=stats)
    (out/'actual-video-comparison.json').write_text(json.dumps(evidence,indent=2),encoding='utf8')
    print(json.dumps(evidence),flush=True)


if __name__=='__main__':main()
