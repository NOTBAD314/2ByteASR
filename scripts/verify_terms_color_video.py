"""Decode the whole delivered movie and measure both subtitle fill colors."""
import argparse,json
from pathlib import Path
import av
import numpy as np


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    args=parser.parse_args();folder=args.directory.resolve()
    expected=json.loads((folder/'expected-colors.json').read_text('utf8'))
    colors={key:np.array([int(value['color'][-6:][i:i+2],16) for i in (0,2,4)],dtype=int)
            for key,value in expected.items() if key in ('source-1','source-1#tr')}
    count=0;selected=None;last_time=0
    with av.open(str(folder/'verified.mp4')) as video:
        fps=float(video.streams.video[0].average_rate)
        for frame in video.decode(video=0):
            count+=1;last_time=float(frame.time)
            if selected is None and .8<=frame.time<=1.1:selected=frame.to_ndarray(format='rgb24')
    if selected is None:raise RuntimeError('No active subtitle frame')
    bottom=selected[int(selected.shape[0]*.48):].astype(int)
    pixels={key:int((np.max(np.abs(bottom-color),axis=2)<=24).sum()) for key,color in colors.items()}
    from PIL import Image
    Image.fromarray(selected).save(folder/'exported-caption-frame.png')
    result=dict(decoded_frames=count,fps=fps,last_frame_seconds=last_time,
        subtitle_color_pixels=pixels,expected_fill_colors=expected,
        passed=count==round(8*fps) and all(n>50 for n in pixels.values()))
    (folder/'video-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({key:result[key] for key in ('passed','decoded_frames','fps','subtitle_color_pixels')},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
