"""Independently decode the headed source-monitor audit's known test fixture."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import av
import numpy as np


def verify(path):
    frames=list(av.open(str(path)).decode(video=0))
    visual=[]
    for second in (1,4.8,5,7,9.8,10,12,14.8,15,17,19.8):
        rgb=frames[min(len(frames)-1,round(second*25))].to_ndarray(format='rgb24')
        visual.append({'second':second,'rgb':rgb[30:150,40:280].mean(axis=(0,1)).tolist()})
    container=av.open(str(path)); rate=container.streams.audio[0].rate
    audio=np.concatenate([frame.to_ndarray().reshape(frame.layout.nb_channels,-1).mean(axis=0)
                          for frame in container.decode(audio=0)])
    sonic=[]
    for start,end in ((1,4),(6,9),(11,14),(16,19)):
        window=audio[start*rate:end*rate]
        power=np.abs(np.fft.rfft(window*np.hanning(len(window))))
        sonic.append({'range':[start,end],'rms':float(np.sqrt(np.mean(window**2))),
                      'hz':float(np.fft.rfftfreq(len(window),1/rate)[power.argmax()])})
    checks={'500 frames / 20 seconds':len(frames)==500,
        'AV and video-only use selected green source range':all(v['rgb'][1]>v['rgb'][0]+60 and v['rgb'][1]>v['rgb'][2]+60 for v in visual if v['second']<10),
        'audio-only retains sequence gray':all(max(v['rgb'])-min(v['rgb'])<10 for v in visual if 10<=v['second']<15),
        'second source range is blue':all(v['rgb'][2]>v['rgb'][0]+100 and v['rgb'][2]>v['rgb'][1]+100 for v in visual if v['second']>=15),
        'AV uses stream 2 1760 Hz':abs(sonic[0]['hz']-1760)<2 and sonic[0]['rms']>.04,
        'video-only has no source sound':sonic[1]['rms']<.0001,
        'audio-only uses stream 2':abs(sonic[2]['hz']-1760)<2 and sonic[2]['rms']>.04,
        'second video-only range stays silent':sonic[3]['rms']<.0001}
    return {'checks':checks,'visual':visual,'audio':sonic,'frames':len(frames),'sample_rate':rate}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video',type=Path)
    parser.add_argument('--json',type=Path,required=True)
    args=parser.parse_args(); result=verify(args.video)
    args.json.write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result['checks'],indent=2))
    return 0 if all(result['checks'].values()) else 1


if __name__=='__main__':
    raise SystemExit(main())
