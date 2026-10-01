"""Stream screen recording; retain 13 boundary thumbnails, never decoded-frame folders."""
import argparse, collections, json
from bisect import bisect_right
from fractions import Fraction
from pathlib import Path
import av
import numpy as np
from PIL import Image,ImageDraw


def classify_caption_mask(mask, references):
    """Recognize a union only when both captions have distinct visible pixels."""
    count=int(mask.sum())
    distances={key:float(np.logical_xor(mask,ref).sum()/max(1,np.logical_or(mask,ref).sum())) for key,ref in references.items()}
    support={}
    if set(references)=={'A','B'}:
        union=np.logical_or(references['A'],references['B'])
        distances['A+B']=float(np.logical_xor(mask,union).sum()/max(1,np.logical_or(mask,union).sum()))
        for key,other in (('A','B'),('B','A')):
            unique=np.logical_and(references[key],~references[other])
            support[key]=float(np.logical_and(mask,unique).sum()/max(1,unique.sum()))
        if min(support.values())<.85 or any(np.logical_and(references[key],~references[other]).sum()<100 for key,other in (('A','B'),('B','A'))):
            distances.pop('A+B')
    identity='None' if count<100 else min(distances,key=distances.get) if distances else 'Unknown'
    if identity not in ('None','Unknown') and distances[identity]>.4:identity='Unknown'
    return identity,distances,support


def analyze(out, *, calibrated=False):
    destination=out/"analysis-calibrated" if calibrated else out
    if calibrated:destination.mkdir(exist_ok=False)
    result=json.loads((out/'result.json').read_text('utf8'))
    config=json.loads((out/'matrix.json').read_text('utf8'))
    fps=Fraction(config['fps']);reports=[]
    for case in result['cases']:
        cues=case.get('cues',[dict(id='A',start=0,end=1000,pixels='A'),dict(id='B',start=1000+config['gap'],end=2000,pixels='B')])
        starts=[cue['start'] for cue in cues];max_ends=[]
        for cue in cues:max_ends.append(max(cue['end'],max_ends[-1] if max_ends else 0))
        rows=[];references={};thumbnails={};playing=False;seen_b=False;previous_number=None;stable_frames=0
        reference_candidates={"A":[],"B":[]};clock_offset=None;reference_times={}
        phase_times={p["name"]:p["at"] for p in case.get("phases",[])}
        container=av.open(str(out/(case['id']+'-screen.mp4')))
        stream=container.streams.video[0]
        sx=sy=case['dpr']
        x,y,w,h=case['viewport'];x,y,w,h=map(round,(x*sx,y*sy,w*sx,h*sy))
        # GfxCapture includes the visible client, as does QWidget width/height.
        for frame in container.decode(stream):
            pixels=frame.to_ndarray(format='rgb24')
            phase_playing=None
            if case.get('phase_marker'):
                mx,my=[round(value*case['dpr']) for value in case['phase_marker']]
                color=pixels[my-2:my+3,mx-2:mx+3].mean(axis=(0,1))
                phase_playing=bool(color[1]>150 and color[0]<100)
            video=pixels[y:y+h,x:x+w]
            if video.shape[:2]!=(h,w):raise ValueError('capture viewport mismatch')
            bits=[]
            for i in range(16):
                px=round((64+64*i)/1280*w);py=round(70/720*h)
                bits.append(int(video[py-2:py+3,px-2:px+3].mean()>155))
            number=sum(b<<i for i,b in enumerate(bits[:12])) if bits[12:]==[0,1,0,1] else None
            # Fractional-DPI rounding can include the QWidget's one-pixel
            # white right border. This centered fixture has a 3% safe margin;
            # exclude two edge pixels of UI chrome, not subtitle content.
            caption=video[round(h*.52):round(h*.98),2:-2]
            mask=caption.min(axis=2)>190
            count=int(mask.sum())
            stable_frames=stable_frames+1 if number==previous_number else 1
            previous_number=number
            if number is not None:
                if number>=round(float(fps)*1.4):seen_b=True
                if seen_b and number<round(float(fps)*.3):playing=True
                if stable_frames>=20 and count>100:
                    if number==round(float(fps)*.5) and not seen_b and 'A' not in references:references['A']=mask.copy()
                    if number==round(float(fps)*1.5) and not playing and 'B' not in references:references['B']=mask.copy()
            if calibrated and clock_offset is None:
                for name,target in (("A",round(float(fps)*.5)),("B",round(float(fps)*1.5))):
                    if number==target and stable_frames>=5 and count>100:
                        reference_candidates[name].append((float(frame.pts*frame.time_base),mask.copy()))
                if phase_playing and 'play' in phase_times:
                    # Align capture PTS to the visible green transition; choose the
                    # middle of the explicit settled-reference plateau, not the
                    # first stale image after an asynchronous seek.
                    clock_offset=phase_times['play']-float(frame.pts*frame.time_base)
                    for name in ('A','B'):
                        target=phase_times[name+'-reference']-clock_offset+.2
                        if not reference_candidates[name]:raise ValueError('missing settled '+name+' reference')
                        stamp,reference=min(reference_candidates[name],key=lambda item:abs(item[0]-target))
                        if abs(stamp-target)>.15:raise ValueError('settled reference outside recorded phase')
                        references[name]=reference
                        reference_times[name]=dict(capture_pts=stamp,target_pts=target)
                    reference_candidates.clear()
            if phase_playing is not None:playing=phase_playing
            identity,distances,support=classify_caption_mask(mask,references)
            pts=Fraction(number,1)/fps*1000 if number is not None else None
            active=[];index=bisect_right(starts,pts)-1 if pts is not None else -1
            while index>=0 and max_ends[index]>pts:
                if cues[index]['end']>pts:active.append(cues[index])
                index-=1
            active.reverse()
            expected='+'.join(cue['pixels'] for cue in active) or 'None'
            row=dict(capture_pts=float(frame.pts*frame.time_base),media_frame=number,media_pts_ms=float(pts) if pts is not None else None,
                media_pts_rational=str(pts) if pts is not None else None,published_pixels_identity=identity,
                white_glyph_pixels=count,expected_cue=expected,expected_cue_ids=[cue['id'] for cue in active],distances=distances,distinct_cue_support=support,playback=playing)
            rows.append(row)
            boundary=round(float(fps))
            if playing and number is not None and boundary-6<=number<=boundary+6 and number not in thumbnails:
                im=Image.fromarray(video);im.thumbnail((420,236));thumbnails[number]=im.copy()
        container.close()
        playback=[row for row in rows if row['playback'] and row['media_frame'] is not None]
        # The exact seek follows the monotone playback. Stop before its backwards jump.
        end=next((i for i in range(1,len(playback)) if playback[i]['media_frame']+2<playback[i-1]['media_frame']),len(playback))
        after_play=(rows[next((i for i,row in enumerate(rows) if row is playback[-1]),len(rows))+1:] if case.get('phase_marker') and playback else playback[end:])
        playback=playback[:end]
        boundary=round(float(fps))
        boundary_rows=[row for row in playback if boundary-6<=row['media_frame']<=boundary+6]
        report=dict(route=case['id'],fps=str(fps),viewport=[x,y,w,h],frames=len(rows),
            barcode_valid_fraction=sum(row['media_frame'] is not None for row in rows)/max(1,len(rows)),
            references={k:int(v.sum()) for k,v in references.items()},boundary_rows=boundary_rows,
            failures=[row for row in boundary_rows if row['published_pixels_identity']!=row['expected_cue']],
            continuous_failures=[row for row in playback if row['published_pixels_identity']!=row['expected_cue']],
            seen_cue_ids=sorted({cue_id for row in playback for cue_id in row['expected_cue_ids']}),
            content_identity='White glyph masks matched against actual paused A/B WGC reference pixels; threshold IoU distance <=0.4',
            ui_border_excluded_pixels=2,
            pts_source='Embedded media frame barcode; exact rational PTS from fixture FPS, independent of Clock')
        report['valid']=bool(references.keys()=={'A','B'} and len(boundary_rows)>=12)
        report['overlap_policy']='Union IoU distance <=0.4 AND >=85% distinct white pixels for each cue; >=100 distinct reference pixels required. Occlusion/identical glyphs remain unverified.'
        report['content_failure_counts']=dict(collections.Counter('blank' if row['published_pixels_identity']=='None' else 'unknown_or_mixed' if row['published_pixels_identity']=='Unknown' else 'wrong_cue_set' for row in report['continuous_failures']))
        first_rows={}
        for row in playback:
            for cue_id in row['expected_cue_ids']:first_rows.setdefault(cue_id,row)
        report['first_visible_frame_checks']=[dict(cue_id=cue_id,media_pts_ms=row['media_pts_ms'],expected=row['expected_cue'],actual=row['published_pixels_identity'],nonblank=row['white_glyph_pixels']>=100,correct=row['published_pixels_identity']==row['expected_cue']) for cue_id,row in first_rows.items()]
        report['all_active_frames_nonblank']=all(row['white_glyph_pixels']>=100 for row in playback if row['expected_cue_ids'])
        report['all_cue_first_frames_correct']=bool(first_rows) and all(row['correct'] for row in report['first_visible_frame_checks'])
        report['passed']=report['valid'] and not report['failures']
        report['continuous_passed']=report['valid'] and not report['continuous_failures'] and len(report['seen_cue_ids'])==config.get('count',2)
        exact=[row for row in after_play if row['media_frame']==boundary]
        if calibrated:
            if clock_offset is None:raise ValueError('missing visible playback marker')
            start=phase_times['exact-seek-1000']-clock_offset
            exact=[row for row in rows if start<=row['capture_pts']<=start+.3 and row['media_frame']==boundary and not row['playback']]
            release=phase_times['rapid-scrub-release']-clock_offset
            scrub=[row for row in rows if release-.1<=row['capture_pts']<=release+.2 and not row['playback']]
            report.update(reference_calibration=reference_times,clock_offset=clock_offset,
                capture_alignment_note="Visible marker alignment; one capture frame plus unmeasured click/display delay. Settled windows exclude scrub.",
                exact_window_capture_pts=[start,start+.3],scrub_last_frames=scrub,
                scrub_passed=bool(len(scrub)>=12 and all(row['published_pixels_identity']==row['expected_cue'] for row in scrub)))
        report['exact_seek_last_frames']=exact[-12:]
        report['exact_seek_passed']=bool(len(exact)>=12 and all(row['published_pixels_identity']==row['expected_cue'] for row in exact[-12:]))
        sheet=Image.new('RGB',(420*4,260*4),'#101018');draw=ImageDraw.Draw(sheet)
        for i,(number,im) in enumerate(sorted(thumbnails.items())):
            xx=i%4*420;yy=i//4*260;sheet.paste(im,(xx,yy+23))
            row=next((r for r in boundary_rows if r['media_frame']==number),None)
            draw.text((xx+5,yy+5),f"frame {number}  {float(Fraction(number)/fps):.6f}s  {row['published_pixels_identity'] if row else '?'}",fill='white')
        sheet.save(destination/(case['id']+'-boundary-contact.jpg'),quality=93)
        (destination/(case['id']+'-frames.json')).write_text(json.dumps(rows,separators=(',',':')),'utf8')
        reports.append(report)
    (destination/'boundary-pixels.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps([{k:v for k,v in r.items() if k not in ('boundary_rows','failures','continuous_failures','seen_cue_ids','exact_seek_last_frames','scrub_last_frames')}|{'failures':len(r['failures']),
        'continuous_failures':len(r['continuous_failures']),'seen_cues':len(r['seen_cue_ids']),
        'boundary':[(row['media_frame'],row['published_pixels_identity']) for row in r['boundary_rows']]} for r in reports],ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);parser.add_argument('--calibrated',action='store_true');args=parser.parse_args();analyze(args.folder,calibrated=args.calibrated)
