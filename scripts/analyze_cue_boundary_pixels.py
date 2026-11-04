"""Decode video frame codes from the actual Studio WGC surface."""
from pathlib import Path
import argparse,json,sys,bisect
import av
import numpy as np

def main():
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);a=p.parse_args();out=a.folder
    d=json.loads((out/'result.json').read_text('utf8'))
    c=av.open(str(out/'screen.mp4'));s=c.streams.video[0]
    sx,sy=s.width/d['window_geometry'][2],s.height/d['window_geometry'][3]
    x,y,w,h=d['geometry'];wx,wy,_,_=d['window_geometry']
    # WGC captures the client surface. Locate the barcode row in the expected
    # viewport neighbourhood to account for title-bar and DPI frame offsets.
    x=(x-wx)*sx;y=(y-wy)*sy;w*=sx;h*=sy
    rows=[];offset=None
    for frame in c.decode(s):
        plane=frame.reformat(format='yuv420p').planes[0]
        pixels=np.frombuffer(plane,dtype=np.uint8).reshape(frame.height,plane.line_size)
        def decode(dy,dx):
            bits=[]
            for i in range(16):
                py=round(y+710/1080*h+dy);px=round(x+(128+64*i)/1920*w+dx)
                bits.append(int(pixels[py-1:py+2,px-1:px+2].mean()>140))
            return sum(b<<i for i,b in enumerate(bits[:12])) if bits[12:]==[0,1,0,1] else None
        if offset is None:
            for dy in range(-36,37,3):
                for dx in range(-12,13,3):
                    code=decode(dy,dx)
                    if code is not None and code<20: offset=(dy,dx);break
                if offset:break
        code=decode(*offset) if offset else None
        if code is not None and 150<=code<=152:
            frame.to_image().save(out/'screen-active.png')
        rows.append({'pts':float(frame.pts*frame.time_base),'code':code})
    starts=[250+i*225 for i in range(32)]
    changes=[];last=None
    for r in rows:
        if r['code'] is not None and r['code']!=last:
            if changes and 30<=r['code']<=440:
                prev=changes[-1];r['delta_ms']=(r['pts']-prev['pts'])*1000
                r['boundary']=bisect.bisect_right(starts,r['code']*1000/60)!=bisect.bisect_right(starts,prev['code']*1000/60)
            changes.append(r);last=r['code']
    def stats(values):
        return {'n':len(values),'p95_ms':round(float(np.percentile(values,95)),3),'max_ms':round(max(values),3)} if values else {}
    result={'measurement':'actual WGC pixels, changing 60 Hz source frame code; PTS intervals, not UI callbacks',
        'resolution':[s.width,s.height],'barcode_offset':offset,'valid_fraction':sum(r['code'] is not None for r in rows)/max(1,len(rows)),
        'boundary':stats([r['delta_ms'] for r in changes if r.get('boundary')]),
        'ordinary':stats([r['delta_ms'] for r in changes if r.get('boundary') is False]),
        'periodic_200ms_observed':any(r.get('delta_ms',0)>=180 for r in changes),
        'changes':changes}
    (out/'visible-content.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='changes'}))

if __name__=='__main__':main()
