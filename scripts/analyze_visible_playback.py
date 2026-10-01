"""Count decoded screen barcodes, never encoder FPS or mpv upload calls."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import av


def main():
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);a=p.parse_args()
    out=a.folder;d=json.loads((out/'result.json').read_text('utf8'))
    container=av.open(str(out/'screen.mp4'));stream=container.streams.video[0]
    sx=stream.width/d['window_geometry'][2];sy=stream.height/d['window_geometry'][3]
    x,y,w,h=d['geometry'];wx,wy,_,_=d['window_geometry']
    base=((x-wx)*sx,(y-wy)*sy,w*sx,h*sy)
    if d.get('record_crop'):base=(0,0,stream.width,stream.height)
    rects={'V1':base,'V2':(base[0]+.495*base[2],base[1]+.075*base[3],.45*base[2],.45*base[3])}
    points={key:[(round(y+d.get('barcode_y',890)/1080*h),round(x+(128+64*i)/1920*w)) for i in range(16)] for key,(x,y,w,h) in rects.items()}
    rows=[]
    for frame in container.decode(stream):
        frame=frame.reformat(format='yuv420p');plane=frame.planes[0]
        pixels=np.frombuffer(plane,dtype=np.uint8).reshape(frame.height,plane.line_size)
        row={'at':float(frame.pts*frame.time_base),'capture_ms':0}
        for key,cells in points.items():
            bits=[int(pixels[y-1:y+2,x-1:x+2].mean()>140) for y,x in cells]
            row[key]=sum(b<<i for i,b in enumerate(bits[:12])) if bits[12:]==[0,1,0,1] else None
        rows.append(row)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from twobyteasr.visible_playback_audit import summarize
    # Leave an extra .5s boundary margin for recorder startup. FPS is counted
    # within the recorded presentation timeline, with no timer extrapolation.
    start=d['play_window'][0]-d['record_started']+.5
    end=d['play_window'][1]-d['record_started']-.5
    result=summarize(rows,start,end)
    result.update(measurement=('Desktop Duplication of foreground Studio canvas' if d.get('record_crop') else 'Windows Graphics Capture of actual Studio HWND')+'; per-layer visible binary frame-code changes',
        captured_resolution=[stream.width,stream.height],video_viewport=[round(v) for v in base],
        capture_timeline=[start,end],capture_p95_ms=None,
        clock_alignment_uncertainty='Recorder startup is not wall-clock synchronized; PTS difference between layers is exact modulo 30-second fixture loop.')
    steady=[r for r in rows if start+1<=r['at']<end and r['V1'] is not None and r['V2'] is not None]
    diffs=[((r['V2']-r['V1']+900)%1800-900)*1000/60 for r in steady]
    result['V2_minus_V1_ms']={'median':float(np.median(diffs)),'p95_abs':float(np.percentile(np.abs(diffs),95)),
        'max_abs':float(max(map(abs,diffs)))} if diffs else None
    (out/'visible-content.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    (out/'wgc-barcodes.json').write_text(json.dumps(rows),encoding='utf8')
    d['screen']=result
    d['checks']['recording-covers-steady-window']=bool(rows and rows[-1]['at']>=end-.1)
    for layer in ('V1','V2'):d['checks'][layer+'-visible-30fps']=result[layer]['visible_fps']>=30 and result[layer]['valid_fraction']>.98
    (out/'result.json').write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
