"""Motion time ownership: integer microseconds and half-open intervals.

The browser's __2byteMotionSchedule implements this same contract. Repeat
subdivides the declared total window; it never extends it into another phase.
"""
import math
from .theme_dom import ThemeDOM

TICKS_PER_MS=1000


def ticks(value):
    return math.floor(value*TICKS_PER_MS+.5)


def motion_schedule(spec, duration_ms):
    # Extreme short cues use a settled pose. Still validate the authored
    # ownership on a normal cue so a short sample cannot hide bad tracks.
    readable=spec.get('timingProfile')=='readable-pixel'
    short=duration_ms<=(260 if readable else 700 if spec.get('version')==2 else 100)
    duration=ticks(max(50,1000 if short else duration_ms))
    build=min(ticks(spec['buildMs']),math.floor(duration*.20+.5))
    resolve=min(ticks(spec['resolveMs']),math.floor(duration*.15+.5))
    if spec.get('version')==2 and not short and duration_ms<1600:
        build=min(build,ticks(160));resolve=min(resolve,ticks(100))
    boundaries={'build':(0,build),'breathe':(build,duration-resolve),'resolve':(duration-resolve,duration)}
    if spec.get('version')==2 and not short:
        clear=min(ticks(45),math.floor(resolve*.45+.5))
        boundaries['resolve']=(duration-resolve,duration-clear)
    tier='full' if duration_ms>3000 else 'compact' if duration_ms>=1800 else 'short'
    if readable:
        build=ticks(min(spec['buildMs'],620 if tier=='full' else 320 if tier=='compact' else 110,duration_ms*.3))
        resolve=ticks(min(spec['resolveMs'],500 if tier=='full' else 280 if tier=='compact' else 110,duration_ms*.25))
        # Reserve an actual encoded-frame interval, not an arbitrary fraction.
        clear=min(ticks(45),math.floor(resolve*.45+.5))
        boundaries={'build':(0,build),'breathe':(build,duration-resolve),'resolve':(duration-resolve,duration-clear)}
    rows=[]
    for index,track in enumerate(spec['tracks']):
        begin,finish=boundaries[track['phase']];span=finish-begin
        start=begin+math.floor(track['start']*span+.5)
        end=begin+math.floor(track['end']*span+.5)
        cycle_ms=track.get('durationMs')
        repeat=track.get('repeat',0) if cycle_ms is not None else min(track.get('repeat',0),max(0,(end-start)//120000-1))
        if track.get('sustain'):
            repeat=max(0,math.ceil((end-start)/ticks(cycle_ms))-1)
        elif cycle_ms is not None:end=min(end,start+ticks(cycle_ms)*(repeat+1))
        row=dict(track_index=index,selector=track['selector'],phase=track['phase'],
            start_tick=start,end_tick=end,start_ms=start/1000,end_ms=end/1000,
            repeat=repeat,requested_repeat=track.get('repeat',0),yoyo=track.get('yoyo',False),
            properties=list(track['to']),source='authored',short_cue_settled=short)
        if cycle_ms is not None:row['cycle_ms']=cycle_ms
        if track.get('sustain'):row['sustain']=True
        if 'minCueMs' in track:
            row['min_cue_ms']=track['minCueMs']
            row['omitted_for_duration']=duration_ms<track['minCueMs']
        if 'wiggle' in track:row['procedural']='wiggle'
        if readable:row['cue_tier']=tier
        rows.append(row)
    return rows


def motion_ownership_issues(spec, cue_html=None, duration_ms=3000):
    rows=motion_schedule(spec,duration_ms);dom=ThemeDOM(cue_html) if cue_html is not None else None
    ownership={};issues=[]
    for row in rows:
        targets=dom.targets(row['selector']) if dom else {row['selector']}
        # {{words}} expands only when actual text is known. The real DOM check
        # remains mandatory for those dynamic nodes; don't invent word counts.
        track=spec['tracks'][row['track_index']]
        if not targets and track.get('optional'):continue
        if dom and not targets and '{{words}}' in cue_html and '.wt-w' in row['selector']:
            targets={row['selector']}
        if not targets:
            issues.append(dict(category='motion_target',path=f"motionSpec.tracks[{row['track_index']}].selector",
                track_indices=[row['track_index']],selector=row['selector'],actual='selector匹配0个实际节点',
                expected='定位cueHtml中真实存在的内容节点',duration_ms=duration_ms))
            continue
        if row['end_tick']==row['start_tick']:
            # Zero build/resolve is a deterministic instantaneous pose. It
            # owns no time interval, but its ordering remains phase/track order.
            continue
        for node in sorted(targets,key=str):
            for prop in row['properties']:
                key=(node,prop)
                for prior in ownership.get(key,[]):
                    if row['start_tick']<prior['end_tick'] and row['end_tick']>prior['start_tick']:
                        node_info=dict(index=node,tag=dom.rows[node]['tag'],classes=sorted(dom.rows[node]['classes'])) if dom and isinstance(node,int) else dict(selector=str(node))
                        issues.append(dict(category='motion_conflict',path=f"motionSpec.tracks[{row['track_index']}]",
                            track_indices=[prior['track_index'],row['track_index']],node=node_info,property=prop,
                            intervals=[prior,row],duration_ms=duration_ms,
                            actual=f"节点{node}的{prop}由tracks[{prior['track_index']}]和tracks[{row['track_index']}]在重叠时间写入",
                            expected='半开区间不得重叠；顺序入场/保持/出场合法。保留动作意图，调整相关窗口或正确目标层，不删除track。'))
                ownership.setdefault(key,[]).append(row)
    return issues


class MotionOwnershipError(ValueError):
    def __init__(self, issues):
        self.issues=issues
        super().__init__('；'.join(f"{x['path']}: {x['actual']}" for x in issues))
