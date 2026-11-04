"""Compare held loading phases in synchronized WGC/DDA and native HWND evidence."""
from __future__ import annotations
import argparse
from bisect import bisect_right
import json
from pathlib import Path
import av
import numpy as np
from PIL import Image, ImageDraw


def frame_at(path, target):
    with av.open(str(path)) as container:
        stream=container.streams.video[0]
        container.seek(max(0,int(target/float(stream.time_base))),stream=stream,backward=True)
        previous=None;selected=None
        for frame in container.decode(stream):
            if frame.pts is None:continue
            at=float(frame.pts*frame.time_base)
            if at>target:
                selected=previous or (at,frame)
                break
            previous=(at,frame)
        selected=selected or previous
        if selected is None:raise ValueError('no decoded frame')
        at,frame=selected
        return at,frame.to_image().convert('RGB')


def transition_scan(folder, result, native):
    """Inspect every captured frame; coarse color candidates still require review."""
    def features(path):
        rows=[]
        with av.open(str(path)) as container:
            for frame in container.decode(video=0):
                if frame.pts is None:continue
                rows.append((float(frame.pts*frame.time_base),
                    frame.reformat(width=64,height=40,format='rgb24').to_ndarray()))
        return rows
    wgc=features(folder/'loading-continuous.mp4');dda=features(folder/'loading-desktop-dda.mp4')
    dda_times=[row[0] for row in dda]
    samples=result['samples'];sample_times=[row['at'] for row in samples]
    origin=result['capture_common_origin']['qpc']
    start=result['record_ready_at'];end=sample_times[-1]
    ready_video={row['generation'] for row in result['sessions'] if row['name'] in
                 {'cold-video','rapid-latest','retried-video','silent-video'}}
    first_phase=result['forensic_phases'][0]
    reference_qpc=(first_phase['start_qpc']+first_phase['end_qpc'])/2
    snapshot=min(native,key=lambda row:abs(row['at']-reference_qpc))
    lookup={row['hwnd']:row for row in snapshot['native_windows']}
    root=lookup[snapshot['root']];bounds=root.get('dwm_frame') or root['rect']
    canvas=next(w for w in snapshot['widgets'] if w['role']=='canvas' and w.get('controller_pid'))
    rect=lookup[canvas['actual_qt_hwnd']]['rect']
    width,height=bounds[2]-bounds[0],bounds[3]-bounds[1]
    crop=[round((rect[0]-bounds[0])/width*64),round((rect[1]-bounds[1])/height*40),
          round((rect[2]-bounds[0])/width*64),round((rect[3]-bounds[1])/height*40)]
    reference=min(wgc,key=lambda row:abs(origin+row[0]-reference_qpc))[1].astype(np.float32)
    panel_mask=np.zeros((40,64),dtype=bool)
    panel_mask[:26,:12]=True;panel_mask[:26,46:]=True
    transitions=[];last=None
    for sample in samples:
        signature=(sample['generation'],sample['state'],sample['current_page'])
        if signature!=last:transitions.append(sample['at']);last=signature
    rows=[];candidates=[]
    for number,(pts,pixels) in enumerate(wgc):
        at=origin+pts
        if not start<=at<=end:continue
        s=max(0,bisect_right(sample_times,at)-1);sample=samples[s]
        d=bisect_right(dda_times,pts)-1
        if d<0:continue
        x,y,right,bottom=crop
        saturation=np.ptp(pixels[y:bottom,x:right].astype(np.int16),axis=2)
        color=float((saturation>100).mean())
        timeline=float((np.ptp(pixels[33:37,8:63].astype(np.int16),axis=2)>100).mean())
        mae=float(np.abs(pixels.astype(np.float32)-dda[d][1].astype(np.float32)).mean())
        panel_mae=float(np.abs(pixels.astype(np.float32)[panel_mask]-reference[panel_mask]).mean())
        near=min((abs(at-value) for value in transitions),default=float('inf'))*1000
        flags=[]
        if sample['active'] and sample['visible'] and color>.05:
            flags.append('color_video_pixels_while_loading')
        if (sample['state']=='ready' and sample['generation'] in ready_video
                and sample['current_page']=='subtitleStudio' and color<.2):
            flags.append('workbench_drawn_but_video_region_not_video')
        if (sample['state']=='ready' and sample['generation'] in ready_video
                and sample['current_page']=='subtitleStudio' and color>.2 and panel_mae>8):
            flags.append('native_video_visible_before_surrounding_workbench')
        if mae>5 and pts-dda[d][0]<.050:
            flags.append('WGC_DDA_differ')
        row={'frame':number,'pts':pts,'qpc':at,'generation':sample['generation'],'state':sample['state'],
             'current_page':sample['current_page'],'video_color_fraction':color,
             'timeline_color_fraction':timeline,'wgc_dda_mae':mae,'dda_age_ms':(pts-dda[d][0])*1000,
             'panel_difference_from_ready_frame':panel_mae,
             'distance_to_state_transition_ms':near,'flags':flags}
        rows.append(row)
        if flags:candidates.append(row)
    # Review temporal clusters, including the closest captured state on each
    # side. Keep every flagged frame in JSON rather than cherry-picking stills.
    clusters=[]
    for candidate in candidates:
        if not clusters or candidate['pts']-clusters[-1][-1]['pts']>.12:
            clusters.append([])
        clusters[-1].append(candidate)
    boards=[]
    for index,cluster in enumerate(clusters[:20],1):
        pts=cluster[len(cluster)//2]['pts']
        panels=[]
        for offset in (-.08,0.,.08):
            _,left_image=frame_at(folder/'loading-continuous.mp4',max(0,pts+offset))
            _,right_image=frame_at(folder/'loading-desktop-dda.mp4',max(0,pts+offset))
            panels.extend((left_image,right_image))
        board=Image.new('RGB',(1680,3*525),'#111111')
        for panel,image in enumerate(panels):
            board.paste(image.resize((840,525)),((panel%2)*840,(panel//2)*525))
        filename=f'transition-review-v2-{index:02d}.png';board.save(folder/filename)
        boards.append({'file':filename,'center_pts':pts,'candidate_count':len(cluster),
                       'flags':sorted({flag for row in cluster for flag in row['flags']})})
    report={'method':'every WGC frame paired to the latest DDA frame using their shared wallclock origin; 64x40 color checks only nominate review frames',
            'review_status':'NEEDS_REVIEW','wgc_frames_total':len(wgc),'dda_frames_total':len(dda),
            'compared_frames':len(rows),'candidate_frames':len(candidates),
            'video_roi_reference_qpc':reference_qpc,'video_roi_physical':rect,'coarse_video_roi':crop,
            'native_snapshot_capacity_exhausted':len(native)>=2500,
            'limits':['State timestamps and packet delivery can differ by a frame; candidates near transitions are not automatic failures.',
                      'Color thresholds apply only to this controlled testsrc2 fixture; they do not certify arbitrary user video.',
                      'The full recordings and all candidate rows remain authoritative for visual review.'],
            'boards':boards,'frames':rows}
    (folder/'transition-scan-v2.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    return {key:report[key] for key in ('wgc_frames_total','dda_frames_total','compared_frames','candidate_frames','boards')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--scan-transitions',action='store_true')
    args=parser.parse_args();folder=args.folder.resolve()
    result=json.loads((folder/'loading.json').read_text('utf8'))
    native=json.loads((folder/'native-windows.json').read_text('utf8'))
    origin=result['capture_common_origin']['qpc']
    layout=result['dda_layout'];left=layout['rect'][0]+layout['crop'][0];top=layout['rect'][1]+layout['crop'][1]
    compared=[]
    for index,phase in enumerate(result['forensic_phases'],1):
        target=(phase['start_qpc']+phase['end_qpc'])/2
        snapshot=min(native,key=lambda item:abs(item['at']-target))
        windows={item['hwnd']:item for item in snapshot['native_windows']}
        root=windows[snapshot['root']]
        root_rect=root.get('dwm_frame') or root['rect']
        wgc_pts,wgc=frame_at(folder/'loading-continuous.mp4',target-origin)
        dda_pts,dda=frame_at(folder/'loading-desktop-dda.mp4',target-origin)
        label=f'phase-{index:02d}'
        wgc.save(folder/(label+'-wgc.png'));dda.save(folder/(label+'-dda.png'))
        primary=next((item for item in snapshot['widgets'] if item['role']=='canvas' and item.get('controller_pid')),None)
        entry={'label':phase['label'],'phase_duration_seconds':phase['end_qpc']-phase['start_qpc'],
            'sample_qpc':target,'native_sample_delta_ms':(snapshot['at']-target)*1000,
            'video_pts':{'requested':target-origin,'wgc':wgc_pts,'dda':dda_pts},
            'video_delivery_age_ms':{'wgc':(target-origin-wgc_pts)*1000,'dda':(target-origin-dda_pts)*1000},
            'root_rect':root_rect,'foreground':snapshot['foreground'],'loading_state':snapshot['loading_state']}
        coverage=snapshot.get('desktop_coverage') or {}
        entry['native_snapshot_current']=abs(snapshot['at']-target)<=.150
        entry['desktop_visibility_valid']=bool(entry['native_snapshot_current'] and coverage.get('foreground_owned') and coverage.get('all_points_owned'))
        entry['desktop_coverage']=coverage
        if not entry['desktop_visibility_valid']:
            entry['comparison_invalid_reason']='no current native foreground/occlusion snapshot; pixel images remain available but stale native state cannot certify this phase'
        panels=[('WGC application window',wgc),('DDA desktop crop',dda)]
        if primary and primary['actual_qt_hwnd'] in windows:
            canvas=windows[primary['actual_qt_hwnd']];x,y,right,bottom=canvas['rect']
            wgc_roi=wgc.crop((x-root_rect[0],y-root_rect[1],right-root_rect[0],bottom-root_rect[1]))
            dda_roi=dda.crop((x-left,y-top,right-left,bottom-top))
            entry['canvas']={'qt':primary,'native':canvas,
                'mpv_children':[item for item in snapshot['native_windows'] if item['pid']==primary['controller_pid'] and item['class']=='mpv']}
            entry['wgc_dda_canvas_mae']=float(np.abs(np.asarray(wgc_roi,dtype=np.float32)-np.asarray(dda_roi,dtype=np.float32)).mean())
            wgc_roi.save(folder/(label+'-canvas-wgc.png'));dda_roi.save(folder/(label+'-canvas-dda.png'))
            reference=next((item for item in result.get('native_frames',[]) if item['label']==phase['label'] and not item.get('error')),None)
            if reference and (folder/reference['file']).is_file():
                image=Image.open(folder/reference['file']).convert('RGB')
                if image.size==wgc_roi.size:
                    for source,value in [('wgc',wgc_roi),('dda',dda_roi)]:
                        entry[source+'_native_frame_mae']=float(np.abs(np.asarray(value,dtype=np.float32)-np.asarray(image,dtype=np.float32)).mean())
            entry['reference']=reference
        widths=[840,840];height=525
        board=Image.new('RGB',(1680,height+42),'#111111');draw=ImageDraw.Draw(board)
        for column,(caption,picture) in enumerate(panels):
            board.paste(picture.resize((840,height)),(column*840,42))
            draw.text((column*840+12,12),caption,fill='white')
        board.save(folder/(label+'-paired.png'))
        entry['paired_file']=label+'-paired.png'
        compared.append(entry)
    evidence={'method':'same wallclock packet origin; last delivered video frame at each held phase midpoint; not exact physical scanout timing',
              'phases':compared,'visual_pass':'NOT_REVIEWED' if all(row['desktop_visibility_valid'] for row in compared) else 'INVALID_DESKTOP_VISIBILITY'}
    if args.scan_transitions:
        evidence['transition_scan']=transition_scan(folder,result,native)
    (folder/'native-comparison.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps([{key:row.get(key) for key in ('label','phase_duration_seconds','loading_state','video_delivery_age_ms','wgc_dda_canvas_mae','wgc_native_frame_mae','dda_native_frame_mae')} for row in compared],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
