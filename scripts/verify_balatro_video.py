"""Render an actual transparent MOV, decode its six frames and compare LIVE."""
import sys,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    from twobyteasr.processes import run_hidden_subprocess
    from PIL import Image
    import numpy as np
    out=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else sorted((ROOT/'tmp/balatro-frames').iterdir())[-1]
    renderer=ROOT/'renderer';mov=out/'Balatro-Dealer-Press.mov'
    command=['node',str(renderer/'node_modules/@remotion/cli/remotion-cli.js'),'render','src/index.ts',
        'SubtitleOverlay',str(mov),f'--props={out / "export-props.json"}','--codec=prores','--prores-profile=4444',
        '--pixel-format=yuva444p10le','--image-format=png','--concurrency=2',
        r'--browser-executable=C:\Program Files\Google\Chrome\Application\chrome.exe']
    start=time.perf_counter()
    result=run_hidden_subprocess(command,cwd=renderer,capture_output=True,text=True,timeout=180,check=True,
        purpose='actual Balatro ProRes export comparison')
    (out/'video-render.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    ffmpeg=ROOT/'tools/ffmpeg/bin/ffmpeg.exe';frames=[3,8,14,48,110,119]
    expression='+'.join(f'eq(n,{f})' for f in frames).replace(',',r'\,')
    run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-i',str(mov),'-vf',f'select={expression}',
        '-fps_mode','passthrough','-pix_fmt','rgba',str(out/'decoded-%02d.png')],timeout=60,check=True,
        purpose='decode actual exported six frames')
    stats=[]
    for i,frame in enumerate(frames,1):
        a=np.array(Image.open(out/f'live-{frame:03}.png').convert('RGBA')).astype(float)
        b=np.array(Image.open(out/f'decoded-{i:02}.png').convert('RGBA')).astype(float)
        a[:,:,:3]*=a[:,:,3:]/255;b[:,:,:3]*=b[:,:,3:]/255
        mask=np.maximum(a[:,:,3],b[:,:,3])>8;delta=np.abs(a-b)
        stats.append({'frame':frame,'mae_visible':float(delta[mask].mean()),
                      'different_pixels':int((delta.max(axis=2)>8).sum())})
    run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','color=c=0x38424a:s=1920x1080:r=30:d=4',
        '-i',str(mov),'-filter_complex','[0:v][1:v]overlay=format=auto:shortest=1,format=yuv420p',
        '-c:v','libx264','-crf','18','-preset','fast','-an',str(out/'Balatro-Dealer-Press.mp4')],
        timeout=60,check=True,purpose='composite review video from actual transparent export')
    (out/'actual-video-comparison.json').write_text(json.dumps({'render_seconds':time.perf_counter()-start,
        'mov_bytes':mov.stat().st_size,'frames':stats},indent=2),encoding='utf-8')
    print(out);print(json.dumps(stats))

if __name__=='__main__':main()
