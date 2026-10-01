"""Compare every decoded frame of an existing actual MOV with deterministic LIVE."""
import json
import argparse
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    import numpy as np
    from PIL import Image
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.processes import run_hidden_subprocess
    from twobyteasr.web_theme import theme_archive_html
    from fractions import Fraction
    parser=argparse.ArgumentParser()
    parser.add_argument('evidence',type=Path)
    parser.add_argument('--actual-props',action='store_true',help='Use the props captured by the real export workspace')
    args=parser.parse_args()
    evidence=args.evidence.resolve();out=evidence/'all-frames'
    out.mkdir(exist_ok=False)
    theme=json.loads((evidence/'theme.json').read_text(encoding='utf8'))
    width,height,fps,count=1280,720,30,90
    text,speaker,duration='我送的不是货，是整个人类的希望','企鹅带带北极熊',3.
    if args.actual_props:
        props=json.loads((evidence/'export-props.json').read_text(encoding='utf8'))
        assert len(props['cues'])==1, 'This verifier compares one full-canvas cue'
        cue=props['cues'][0]
        assert cue['startMs']==0
        theme=cue['visual']['webTheme']
        width,height,fps,count=props['width'],props['height'],props['fps'],props['durationInFrames']
        text,speaker,duration=cue['text'],cue.get('speaker',''),cue['endMs']/1000
    probe=run_hidden_subprocess([str(ROOT/'tools/ffmpeg/bin/ffprobe.exe'),'-v','error',
        '-select_streams','v:0','-count_frames','-show_streams','-of','json',
        str(evidence/'Death-Stranding-Original.mov')],capture_output=True,text=True,
        purpose='verify actual MOV geometry rate and frame count',timeout=120,check=True)
    metadata=json.loads(probe.stdout)
    (out/'ffprobe.json').write_text(json.dumps(metadata,indent=2),encoding='utf8')
    stream=metadata['streams'][0]
    assert (stream['width'],stream['height'])==(width,height)
    assert Fraction(stream['avg_frame_rate'])==Fraction(str(fps))
    assert int(stream['nb_read_frames'])==count
    run_hidden_subprocess([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-n','-i',
        str(evidence/'Death-Stranding-Original.mov'),'-fps_mode','passthrough','-pix_fmt','rgba',str(out/'decoded-%03d.png')],
        purpose='decode every actual MOV frame',timeout=120,check=True)
    assert len(list(out.glob('decoded-*.png')))==count
    service=RendererService();rows=[]
    try:
        service.live_set(theme_archive_html(theme,sample_text=text,
            speaker=speaker,duration_seconds=duration,auto_replay=False),width=width,height=height)
        for frame in range(count):
            png=service.live_pause(cue_ms=frame/fps*1000,stage_ms=frame/fps*1000)
            live=out/f'live-{frame:03}.png';live.write_bytes(png)
            a=np.array(Image.open(live).convert('RGBA')).astype(float)
            b=np.array(Image.open(out/f'decoded-{frame+1:03}.png').convert('RGBA')).astype(float)
            a[:,:,:3]*=a[:,:,3:]/255;b[:,:,:3]*=b[:,:,3:]/255
            mask=np.maximum(a[:,:,3],b[:,:,3])>8
            rows.append(dict(frame=frame,mae_visible=float(np.abs(a-b)[mask].mean()) if mask.any() else 0))
    finally:
        service.shutdown()
        result=dict(frames=rows,expected_frames=count,width=width,height=height,fps=fps,
            props_source='actual_export' if args.actual_props else 'original_fixture',
            passed=len(rows)==count and max(r['mae_visible'] for r in rows)<1)
        (out/'comparison.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(dict(frames=len(rows),passed=result['passed'],max_mae=max(r['mae_visible'] for r in rows))))
    assert result['passed']


if __name__=='__main__':main()
