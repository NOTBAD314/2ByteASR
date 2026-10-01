"""Align independently sampled screen codes with Clock and decoder/upload evidence."""
from bisect import bisect_right
import json
from pathlib import Path
import statistics
import sys


def percentiles(values):
    if not values:return None
    values=sorted(values)
    return dict(median=statistics.median(values),p95=values[round((len(values)-1)*.95)],max=max(values))


def main():
    out=Path(sys.argv[1]);d=json.loads((out/'result.json').read_text('utf8'))
    import av
    project=json.loads((out/'imported.2byteproj').read_text('utf8'))
    source_times={}
    for asset in project.get('media_pool',[]):
        source=asset.get('canonical_source','')
        layer='V1' if Path(source).name.startswith('V1-') else 'V2' if Path(source).name.startswith('V2-') else ''
        if not layer:continue
        with av.open(source) as container:
            stream=container.streams.video[0];origin=(container.start_time or 0)/1000
            times=sorted(float(packet.pts*packet.time_base)*1000-origin for packet in container.demux(stream) if packet.pts is not None)
        source_times[layer]={code:[times[i] for i in range(code,len(times),1800)] for code in range(1800)}
    rows=[json.loads(line) for line in (out/'screen-samples.jsonl').read_text('utf8').splitlines()]
    start,end=d['play_window'];states=[r for r in d['telemetry'] if start+1<=r['at']<end]
    times=[r['at'] for r in states];errors={'V1':[],'V2':[]};aligned=[]
    uploads=[r for r in d['uploads'] if r.get('accepted') and r.get('layers') and start<=r.get('applied_at',0)<end]
    visible_keys=set();pipeline=[]
    for row in rows:
        if not times or not start+1<=row['at']<end:continue
        index=max(0,min(len(times)-1,bisect_right(times,row['at'])-1));state=states[index]
        clock=state['clock'];sample=row['at']-row['capture_ms']/2000
        position=clock['presentation_media_ms']+(sample-clock['presentation_monotonic_ts'])*clock['playback_rate']*1000
        record={'capture_at':row['at'],'capture_ms':row['capture_ms'],'clock_ms':position}
        for layer in errors:
            code=row[layer]
            if code is None:continue
            pts=min(source_times[layer].get(code,[]),key=lambda value:abs(value-position))
            record[layer+'_pts_ms']=pts;record[layer+'_clock_error_ms']=pts-position
            errors[layer].append(pts-position)
        if row['V2'] is not None and record['V2_pts_ms'] not in visible_keys:
            visible_keys.add(record['V2_pts_ms'])
            candidates=[u for u in uploads if u['applied_at']<=row['at'] and any(abs(f['pts_ms']-record['V2_pts_ms'])<2 for f in u['layers'])]
            if candidates:
                u=candidates[-1];f=u['layers'][-1]
                pipeline.append(dict(screen_at=row['at'],decoded_at=f['decoded_at'],received_at=f['received_at'],
                    compose_start=u['compose_start'],compose_end=u['compose_end'],upload_start=u['started'],
                    upload_ack=u['applied_at'],source_pts_ms=f['pts_ms'],
                    decode_to_screen_upper_ms=(row['at']-f['decoded_at'])*1000))
        aligned.append(record)
    report=dict(source=dict(width=1920,height=1080,fps=60,tracks=2,rate=states[0]['clock']['playback_rate'] if states else None),
        screen=d.get('screen'),clock_errors={key:dict(signed=percentiles(value),absolute=percentiles([abs(x) for x in value])) for key,value in errors.items()},
        capture_timing_uncertainty='Capture time is midpoint of BitBlt start/end; uncertainty is half capture duration, scaled by playback rate in media time.',
        matched_pipeline_frames=len(pipeline),decode_to_screen_upper_ms=percentiles([p['decode_to_screen_upper_ms'] for p in pipeline]),
        audio=dict(endpoint_pids=sorted({r['audio'].get('endpoint_pid') for r in states if r['audio'].get('endpoint_pid')}),
            underruns=max([r['audio'].get('underruns',0) for r in states] or [0]),
            sink_states=sorted({r['audio'].get('sink_state','') for r in states}),silent_fixture=True),
        limitations=['Screen counts are conservative at the observed capture sampling rate; unsampled DWM frames cannot be assigned as compositor drops.',
            'Decode timestamp is worker pre-conversion completion marker, not codec packet DTS.', 'No speaker or human acceptance claim.'])
    (out/'presentation-pipeline.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    (out/'aligned-presentations.json').write_text(json.dumps(dict(aligned=aligned,pipeline=pipeline)),encoding='utf8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
