"""Read-only decoder/transport audit on a real source; no GUI clock claims."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from twobyteasr.video_decode_pipe import VideoDecodePipe


def main():
    args = argparse.ArgumentParser()
    args.add_argument('media')
    args.add_argument('--seconds', type=float, default=6)
    args.add_argument('--count', type=int, default=2)
    args.add_argument('--output', default='tmp/follower-process.json')
    args.add_argument('--cold-warm',action='store_true')
    args.add_argument('--targets-ms',default='0,611234,5080167')
    options = args.parse_args()
    pipes = [VideoDecodePipe() for _ in range(options.count)]
    rows, phases = [], []
    try:
        for generation, start_ms in enumerate(map(int,options.targets_ms.split(','))):
            if options.cold_warm:
                for pipe in pipes:pipe.close()
                pipes=[VideoDecodePipe() for _ in range(options.count)]
            start = time.perf_counter()
            epochs=[pipe.request(options.media,start_ms,generation,True,1.) for pipe in pipes]
            first = {}
            while time.perf_counter()-start < 5 and len(first) != len(pipes):
                for i, pipe in enumerate(pipes):
                    frame = pipe.take_frame()
                    if (frame and i not in first and frame.epoch==epochs[i] and frame.generation==generation
                            and abs(frame.pts_ms-start_ms)<=34):
                        first[i] = dict(ms=(time.perf_counter()-start)*1000, pts=frame.pts_ms,
                                        raw_pts=frame.raw_pts, dts=frame.raw_dts, time_base=frame.time_base)
                time.sleep(.002)
            phases.append(dict(seek=start_ms,first=first,kind='process-cold' if options.cold_warm else 'seek',
                stats=[p.snapshot() for p in pipes],os_file_cache='not cleared'))
            if options.cold_warm:
                for target,kind in ((start_ms+3000,'warm-away'),(start_ms,'process-warm')):
                    started=time.perf_counter();epochs=[p.request(options.media,target,generation+100,True,1.) for p in pipes]
                    first={}
                    while time.perf_counter()-started<3 and len(first)<len(pipes):
                        for i,pipe in enumerate(pipes):
                            frame=pipe.take_frame()
                            if frame and frame.epoch==epochs[i] and abs(frame.pts_ms-target)<=34 and i not in first:
                                first[i]=dict(ms=(time.perf_counter()-started)*1000,pts=frame.pts_ms,
                                    raw_pts=frame.raw_pts,dts=frame.raw_dts,time_base=frame.time_base,epoch=frame.epoch)
                        time.sleep(.002)
                    phases.append(dict(seek=target,first=first,kind=kind,stats=[p.snapshot() for p in pipes]))
                generation+=100
            current = start_ms
            for rate in (1., 2., 3., 4.):
                phase = f'{start_ms}-{rate:g}x'
                started = time.perf_counter()
                while time.perf_counter()-started < options.seconds:
                    target = current+round((time.perf_counter()-started)*1000*rate)
                    for i, pipe in enumerate(pipes):
                        pipe.request(options.media, target, generation, False, rate)
                        frame = pipe.take_frame()
                        if frame:
                            rows.append(dict(phase=phase, pipe=i, at=time.perf_counter(), pts=frame.pts_ms,
                                demand=target, raw_pts=frame.raw_pts, dts=frame.raw_dts))
                    time.sleep(.004)
                current = target
                phases.append(dict(phase=phase, stats=[p.snapshot() for p in pipes]))
        result = dict(phases=phases, frames=rows)
        for phase in phases:
            if 'phase' not in phase: print(phase, flush=True); continue
            for i in range(len(pipes)):
                frames=[r for r in rows if r['phase']==phase['phase'] and r['pipe']==i]
                gaps=sorted((b['at']-a['at'])*1000 for a,b in zip(frames,frames[1:]))
                fps=(len(frames)-1)/(frames[-1]['at']-frames[0]['at']) if len(frames)>1 else 0
                print(phase['phase'], i, round(fps,2), round(gaps[int(len(gaps)*.95)],2) if gaps else None,
                      'lag',max((r['demand']-r['pts'] for r in frames),default=None), flush=True)
        Path(options.output).write_text(json.dumps(result, indent=2), encoding='utf8')
    finally:
        for pipe in pipes: pipe.close()


if __name__ == '__main__': main()
