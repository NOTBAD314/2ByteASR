"""Offline WGC pixels -> actual source-frame PTS, without barcodes or clock inference.

The caller supplies a known unobscured normalized video ROI. Duplicate or weak
matches are explicitly ambiguous. No frame number / nominal FPS interpolation.
"""
from __future__ import annotations
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import av
import numpy as np
from PIL import Image


def feature(pixels,roi):
    h,w=pixels.shape[:2]
    x0,y0,x1,y1=roi
    crop=pixels[round(y0*h):round(y1*h),round(x0*w):round(x1*w)]
    if not crop.size:raise ValueError('Empty visible video ROI')
    return np.asarray(Image.fromarray(crop).resize((64,36),Image.Resampling.BOX),dtype=np.float32)


def coarse(features):
    return features.reshape((-1,9,4,16,4,3)).mean(axis=(2,4)).reshape((-1,432))


class SourceFrameIndex:
    def __init__(self,features,pts,*,max_mae=8.,min_margin=.25,min_ratio=1.12):
        self.features=np.asarray(features,dtype=np.float32)
        if len(self.features)!=len(pts) or len(pts)<2:raise ValueError('At least two timestamped source frames are required')
        self.pts=[str(Fraction(p)) for p in pts]
        self.coarse=coarse(self.features)
        self.max_mae=max_mae;self.min_margin=min_margin;self.min_ratio=min_ratio

    def match(self,pixels):
        # Mean absolute tile differences are lower bounds on fine pixel MAE
        # (Jensen). Evaluate every frame that could beat the current runner-up.
        lower=np.abs(self.coarse-coarse(pixels[None])[0]).mean(axis=1)
        initial=np.argsort(lower)[:min(32,len(lower))]
        errors=np.abs(self.features[initial]-pixels).mean(axis=(1,2,3))
        bound=float(np.partition(errors,1)[1])
        indices=np.flatnonzero(lower<=bound+1e-5)
        errors=np.abs(self.features[indices]-pixels).mean(axis=(1,2,3))
        order=np.argsort(errors)[:2]
        first,second=(int(indices[k]) for k in order)
        best,runner=(float(errors[k]) for k in order)
        margin=runner-best
        reliable=best<=self.max_mae and margin>=self.min_margin and runner>=best*self.min_ratio
        return dict(status='matched' if reliable else 'no_match' if best>self.max_mae else 'ambiguous',
                    source_pts=self.pts[first] if reliable else None,
                    source_pts_ms=float(Fraction(self.pts[first])*1000) if reliable else None,
                    best_source_index=first,runner_up_source_index=second,
                    best_candidate_pts=self.pts[first],runner_up_candidate_pts=self.pts[second],
                    mae=best,runner_up_mae=runner,margin=margin,evaluated_candidates=len(indices))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--route',default='native')
    parser.add_argument('--roi',type=float,nargs=4,default=(.03,.05,.97,.70))
    parser.add_argument('--max-source-frames',type=int,default=10000)
    args=parser.parse_args()
    out=args.folder.resolve();target=out/(args.route+'-source-pts.json')
    if target.exists():raise ValueError('Refusing to overwrite previous frame evidence')
    roi=tuple(args.roi)
    if not (0<=roi[0]<roi[2]<=1 and 0<=roi[1]<roi[3]<=1):raise ValueError('Invalid normalized ROI')
    matrix=json.loads((out/'matrix.json').read_text('utf8'))
    case=next(c for c in json.loads((out/'result.json').read_text('utf8'))['cases'] if c['id']==args.route)
    source=Path(matrix['media']);capture=out/(args.route+'-screen.mp4')
    features=[];pts=[]
    with av.open(str(source)) as container:
        for frame in container.decode(video=0):
            if len(features)>=args.max_source_frames:raise ValueError('Source index bound exceeded; no silent truncation')
            if frame.pts is None:raise ValueError('Source has a frame without a timestamp')
            pts.append(Fraction(frame.pts)*frame.time_base)
            features.append(feature(frame.to_ndarray(format='rgb24'),roi))
    index=SourceFrameIndex(features,pts)
    sx=case['dpr'];x,y,w,h=[round(v*sx) for v in case['viewport']]
    marker=case.get('phase_marker');rows=[]
    with av.open(str(capture)) as container:
        for frame in container.decode(video=0):
            pixels=frame.to_ndarray(format='rgb24')
            video=pixels[y:y+h,x:x+w]
            if video.shape[:2]!=(h,w):raise ValueError('Viewport outside captured frame')
            row=index.match(feature(video,roi))
            row['capture_pts']=str(Fraction(frame.pts)*frame.time_base)
            if marker:
                mx,my=[round(v*sx) for v in marker]
                color=pixels[my-2:my+3,mx-2:mx+3].mean(axis=(0,1))
                row['playback']=bool(color[1]>150 and color[0]<100)
            rows.append(row)
    counts={status:sum(row['status']==status for row in rows) for status in ('matched','ambiguous','no_match')}
    playing=[row for row in rows if row.get('playback')]
    steps=sorted({str(b-a) for a,b in zip(pts,pts[1:])})
    result=dict(source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        capture_sha256=hashlib.sha256(capture.read_bytes()).hexdigest(),source_frames=len(pts),
        source_pts_steps=steps,roi=roi,thresholds=dict(max_mae=index.max_mae,min_margin=index.min_margin,min_ratio=index.min_ratio),
        method='Full source decode PTS; screen RGB ROI exact global nearest MAE with Jensen-bound pruning. No FPS or application clock used.',
        limits=['Requires known unobscured ROI and correct viewport geometry; changes of crop/rotation/HDR need calibration.',
                'Duplicate or visually indistinguishable source frames have unknown PTS; candidate PTS is not a match.',
                'Matches the recorded compositor image, not physical display scanout time. Capture may skip source frames.'],
        counts=counts,playback_counts={status:sum(row['status']==status for row in playing) for status in counts},
        rows=rows)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))


if __name__=='__main__':main()
