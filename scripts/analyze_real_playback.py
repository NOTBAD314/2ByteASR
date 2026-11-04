"""Match actual WGC game pixels to original decoded source frames.

No diagnostic barcode, encoder FPS, or upload count stands in for displayed
frames. Text/avatar margins are excluded; video packets remain unmodified.
"""
from pathlib import Path
import argparse,json,sys
import av,numpy as np
from PIL import Image


def fingerprint(frame,rect=None):
    # Luma plane is already decoded; no full-frame RGB conversion is necessary.
    plane=frame.planes[0]
    pixels=np.frombuffer(plane,dtype=np.uint8).reshape(frame.height,plane.line_size)[:,:frame.width]
    x,y,w,h=rect or (0,0,frame.width,frame.height)
    x0,x1=round(x+w*.24),round(x+w*.80)
    y0,y1=round(y+h*.12),round(y+h*.66)
    return np.asarray(Image.fromarray(pixels[y0:y1,x0:x1]).resize((48,27),Image.Resampling.BILINEAR),dtype=np.float32).reshape(-1)


def summarize_updates(rows,start,end):
    active=[r for r in rows if start<=r['at']<end]
    changes=[];previous=None
    for row in active:
        code=row['pts_ms']
        if previous is None or code!=previous:
            changes.append(row['at']);previous=code
    intervals=np.diff(changes)*1000
    return dict(seconds=end-start,distinct_updates=len(changes),fps=len(changes)/(end-start),
        per_second=[sum(start+i<=t<min(start+i+1,end) for t in changes) for i in range(int(end-start))],
        interval_ms={str(p):round(float(np.percentile(intervals,p)),2) for p in (50,90,95,99)} if len(intervals) else {},
        longest_repeat_ms=round(float(max(np.diff([start,*changes,end]))*1000),2))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);args=parser.parse_args()
    out=args.folder;d=json.loads((out/'result.json').read_text('utf8'))
    source=Path(next(iter(d['decoder_transport_stats'].values()))['source_path'])
    cache=source.with_suffix('.fingerprints.npz')
    if cache.exists():
        a=np.load(cache);source_pts=a['pts'];images=a['images']
    else:
        c=av.open(str(source));s=c.streams.video[0];s.codec_context.thread_count=8;s.codec_context.thread_type='FRAME'
        source_pts=[];images=[]
        for frame in c.decode(s):
            source_pts.append(float(frame.pts*frame.time_base)*1000);images.append(fingerprint(frame))
        c.close();source_pts=np.array(source_pts);images=np.array(images)
        np.savez_compressed(cache,pts=source_pts,images=images)
    c=av.open(str(out/'screen.mp4'));s=c.streams.video[0];s.codec_context.thread_count=8;s.codec_context.thread_type='FRAME'
    sx,sy=s.width/d['window_geometry'][2],s.height/d['window_geometry'][3]
    x,y,w,h=d['geometry'];wx,wy,_,_=d['window_geometry']
    rect=((x-wx)*sx,(y-wy)*sy,w*sx,h*sy)
    clock=[(r['at'],r['clock']['presentation_media_ms']) for r in d['telemetry']]
    rows=[];previous=None;previous_pts=None
    for frame in c.decode(s):
        t=float(frame.pts*frame.time_base);pixels=fingerprint(frame,rect)
        delta=float(np.mean(np.abs(pixels-previous))) if previous is not None else 1000.
        expected=min(clock,key=lambda r:abs(r[0]-(d['record_started']+t)))[1]
        candidates=np.flatnonzero(np.abs(source_pts-expected)<4500)
        if not len(candidates):candidates=np.arange(len(source_pts))
        error=np.mean((images[candidates]-pixels)**2,axis=1)
        nearest=int(candidates[int(np.argmin(error))]);pts=float(source_pts[nearest]);mse=float(np.min(error))
        # Tiny compression noise is not a new image. Retain the prior source
        # identity when the screen's stable scene really repeats.
        if delta<.45 and previous_pts is not None:pts=previous_pts
        rows.append(dict(at=t,pts_ms=round(pts,3),mse=round(mse,3),delta=round(delta,3)))
        previous=pixels;previous_pts=pts
    c.close()
    start=d['play_window'][0]-d['record_started']+1
    end=d['play_window'][1]-d['record_started']-.5
    screen=summarize_updates(rows,start,end)
    steady=[r for r in rows if start<=r['at']<end]
    screen.update(measurement='WGC actual game pixels matched to original source luma fingerprints; static content gives a conservative update count',
        roi=rect,match_mse_percentiles={str(p):float(np.percentile([r['mse'] for r in steady],p)) for p in (50,95,99)},
        clock_alignment='WGC recorder startup not wall-clock synchronized; precise Clock errors below use native publication telemetry, not guessed screen wall time.')
    # Separately disclose intrinsic still holds; never call every repeated game
    # pixel a stalled decoder, nor subtract them silently from the raw result.
    source_seconds=[]
    for second in range(int(source_pts[-1]//1000)):
        frames=images[(source_pts>=second*1000)&(source_pts<(second+1)*1000)]
        if len(frames)<2:continue
        change=float(np.mean(np.abs(np.diff(frames,axis=0))))
        spread=float(np.mean(np.max(frames,axis=0)-np.min(frames,axis=0)))
        source_seconds.append(dict(source_second=second,mean_frame_change=round(change,4),pixel_range=round(spread,4),intrinsic_still=spread<.45))
    screen['source_motion_by_second']=source_seconds
    screen['intrinsic_still_seconds']=[r['source_second'] for r in source_seconds if r['intrinsic_still']]
    screen['repeat_interpretation']='Raw longest_repeat includes intrinsic source holds; source_motion_by_second is independently decoded original content, not a correction to measured FPS.'
    telemetry=[r for r in d['telemetry'] if d['play_window'][0]+1<=r['at']<d['play_window'][1] and not r['clock']['paused'] and not r['clock']['seeking']]
    errors=[];v1diff=[]
    for r in telemetry:
        for dec in r['decoders'].values():
            if dec.get('presented_pts_ms',-1)>=0:
                errors.append(dec['presented_pts_ms']-r['clock']['presentation_media_ms'])
                if r.get('native_v1_pts_ms') is not None:v1diff.append(dec['presented_pts_ms']-r['native_v1_pts_ms'])
    def stats(values):
        return dict(median_ms=float(np.median(values)),p95_abs_ms=float(np.percentile(np.abs(values),95)),max_abs_ms=float(max(map(abs,values)))) if values else None
    recover={}
    for event in d['events']:
        frames=[u for u in d['uploads'] if u.get('accepted') and u['applied_at']>=event['at'] and any(layer['pts_ms']>=event['target_ms']+(1 if event['name']=='play' else 0) for layer in u.get('layers',[]))]
        recover[event['name']+'_first_current_upload_ms']=(frames[0]['applied_at']-event['at'])*1000 if frames else None
    publications=[layer['pts_ms']-u['project_ms'] for u in d['uploads'] if u.get('accepted') and d['play_window'][0]+1<=u['applied_at']<d['play_window'][1] for layer in u.get('layers',[]) if 'pts_ms' in layer and 'project_ms' in u]
    report=dict(screen=screen,clock_error=stats(errors),V2_minus_native_V1=stats(v1diff),recovery=recover,
        clock_error_method='GUI-observed most recent V2 PTS minus canonical Clock sampled on the same GUI tick; includes observer delay',
        native_publication_clock_error=stats(publications),
        native_publication_method='Accepted native publication source PTS minus its canonical demand anchor; upload is telemetry, never counted as a displayed frame',
        audio_underruns=max((r['audio'].get('underruns',0) for r in d['telemetry']),default=0),
        audio_errors=sorted({r['audio'].get('sink_error','') for r in d['telemetry']}),
        decoder=next(iter(d['decoder_transport_stats'].values())),thumbnails=d.get('thumbnails'))
    (out/'real-visible-content.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'real-source-matches.json').write_text(json.dumps(rows),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='decoder'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
