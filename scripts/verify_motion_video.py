"""Actual ProRes alpha export compared with the shared LIVE GSAP frames."""
from pathlib import Path
import argparse,json,os,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);parser.add_argument('--background',type=Path)
    parser.add_argument('--name',default='snow-slope-look')
    a=parser.parse_args();out=a.folder.resolve()
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'))
    from twobyteasr.processes import run_hidden_subprocess,renderer_node_command,renderer_child_environment
    from PIL import Image
    import numpy as np
    renderer=ROOT/'renderer';mov=out/(a.name+'.mov');start=time.perf_counter()
    command=renderer_node_command(renderer,renderer/'node_modules/@remotion/cli/remotion-cli.js','render','src/index.ts',
        'SubtitleOverlay',mov,f'--props={out / "export-props.json"}','--codec=prores','--prores-profile=4444',
        '--pixel-format=yuva444p10le','--image-format=png','--concurrency=2',
        r'--browser-executable=C:\Program Files\Google\Chrome\Application\chrome.exe')
    rendered=run_hidden_subprocess(command,cwd=renderer,env=renderer_child_environment(),capture_output=True,text=True,timeout=180,check=True,purpose='actual shared GSAP ProRes alpha export')
    (out/'video-render.log').write_text(rendered.stdout+'\n'+rendered.stderr,encoding='utf8')
    frames=[3,6,15,45,87,89];ffmpeg=ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    expression='+'.join(f'eq(n,{frame})' for frame in frames).replace(',',r'\,')
    run_hidden_subprocess([ffmpeg,'-v','error','-y','-i',mov,'-vf',f'select={expression}','-fps_mode','passthrough','-pix_fmt','rgba',out/'decoded-%02d.png'],timeout=60,check=True,purpose='decode six actual exported animation frames')
    rows=[]
    for i,frame in enumerate(frames,1):
        left=np.array(Image.open(out/f'live-frame-{frame}.png').convert('RGBA')).astype(float)
        right=np.array(Image.open(out/f'decoded-{i:02}.png').convert('RGBA')).astype(float)
        left[:,:,:3]*=left[:,:,3:]/255;right[:,:,:3]*=right[:,:,3:]/255
        mask=np.maximum(left[:,:,3],right[:,:,3])>8;mae=float(np.abs(left-right)[mask].mean()) if mask.any() else 0
        rows.append(dict(frame=frame,mae_visible=mae,passed=mae<3))
    if a.background:
        run_hidden_subprocess([ffmpeg,'-v','error','-y','-loop','1','-framerate','30','-i',a.background.resolve(),'-i',mov,
            '-filter_complex','[0:v]scale=1920:1080,format=rgba[bg];[bg][1:v]overlay=format=auto:shortest=1,format=yuv420p',
            '-t','3','-c:v','libx264','-crf','18','-preset','fast','-an',out/(a.name+'-game.mp4')],timeout=60,check=True,purpose='review actual alpha export over authorized game still')
    summary=dict(render_seconds=time.perf_counter()-start,mov_bytes=mov.stat().st_size,frames=rows,passed=all(r['passed'] for r in rows))
    (out/'actual-video-comparison.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(json.dumps(summary));assert summary['passed'],summary


if __name__=='__main__':main()
