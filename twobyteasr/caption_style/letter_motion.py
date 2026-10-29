"""Authored, deterministic Aegisub-inspired typography. All distances are ems.

The source archive is reference material, never executable input. Numeric
keyframes travel with the existing ephemeral word plan to every renderer.
"""
from __future__ import annotations

from bisect import bisect_left
from math import sin, pi

PRESETS = {
    'word_mist': ('雾字聚拢', '大字虚影向内聚焦，膨胀化雾离场', '#B9DDF6'),
    'word_sweep': ('流星点读', '整句先显，流星沿语音逐词擦亮', '#F5D69B'),
    'word_pulse': ('双翼合字', '上下半字交错合拢，分向两侧离场', '#A6EAE4'),
    'word_echo': ('空心填墨', '整句空心轮廓，逐词从下向上注墨', '#D8C2F3'),
    'word_float': ('翻页显字', '字从水平折线翻开，句尾折叠收起', '#F2C4CD'),
    'word_dust': ('星屑解构', '碎片拼成字形，读完散成星屑', '#F2D9A2'),
}
from .motion_catalog import REST, PER_CHAR_LOOPS, RICH_LOOP, char_spans, compose, geometry, loop_apply, spec, out_back, out_cubic

CHANNELS = ('opacity', 'x', 'y', 'scale', 'rotation', 'blur', 'glow', 'reveal', 'trail', 'dust',
            'split', 'sy', 'ink', 'outline', 'read', 'scatter', *REST)
FLOW_GAP_MS = 320.
#: Speech-timed word modes that animate each word at its measured onset.
BEAT_MODES = frozenset({'word_pop', 'word_current_pop', 'word_punch', 'word_ripple'})


def _clamp(v):
    return max(0., min(1., v))


def _pose(mode, incoming, outgoing, pulse, index, preface=1., read=1.):
    p = incoming*incoming*(3-2*incoming)
    q = outgoing*outgoing*(3-2*outgoing)
    a, x, y, scale, rotation, blur, glow, reveal, trail, dust = p*(1-q), 0., 0., 1., 0., 0., 0., 1., 0., 0.
    split, sy, ink, outline, scatter = 0., 1., 1., 0., 0.
    if mode == 'word_mist':
        scale = 1+.9*(1-p)+.65*q
        blur = .22*(1-p)+.2*q
        trail = .8*(1-p)+.65*q
        glow = .6*sin(pi*incoming)
    elif mode == 'word_sweep':
        a = preface*(1-q)
        ink = read
        glow = sin(pi*read)
        reveal = 1-q
    elif mode == 'word_pulse':
        split = 1.05*(1-p)+1.25*q
    elif mode == 'word_echo':
        a = preface*(1-_clamp((outgoing-.7)/.3))
        outline = 1.
        ink = p*(1-min(1,outgoing*1.5))
    elif mode == 'word_float':
        sy = max(.015,(1+2.7*(incoming-1)**3+1.7*(incoming-1)**2)*(1-q))
        y = .36*(1-sy)
        rotation = -10*(1-p)+12*q
        glow = sin(pi*incoming)*(1-q)
    elif mode == 'word_dust':
        scatter = .7*(1-incoming)**2+q
        dust = max(sin(pi*outgoing),.6*sin(pi*incoming))
    return [round(v, 5) for v in (a,x,y,scale,rotation,blur,glow,reveal,trail,dust,split,sy,ink,outline,read,scatter,
                                  *REST.values())]


def shards(index):
    """Static cells and travel vectors shared by Qt, ASS and the browser."""
    return [{'rect':[col/4,row/3,1/4,1/3],
             'x':round((col-1.5)*.65+sin(index*13+row*7+col)*.35,5),
             'y':round((row-1)*.8-.55+sin(index*5+col*3+row)*.3,5)}
            for row in range(3) for col in range(4)]


def choreograph(plan):
    # Plans are re-choreographed after remapping/excerpting: never compose on
    # top of units baked for a previous clock.
    plan = {k: v for k, v in plan.items() if k not in ('units', 'channels', 'layered')}
    result = _choreograph(plan)
    loop_type = (plan.get('loop_effect') or {}).get('type', 'none') if plan.get('composed_loop') else 'none'
    if plan.get('rich_entry') or plan.get('rich_exit') or loop_type in PER_CHAR_LOOPS:
        result = _compose_rich(result, plan, loop_type)
    if plan.get('composed_loop'):
        loop = {**plan['loop_effect'], 'offset': plan.get('clock_offset_ms', 0),
                'start': plan.get('entry_ms', 0),
                'end': plan.get('original_duration_ms', plan['duration_ms'])-plan.get('exit_ms', 0)}
        units = result.get('units', [])
        geo = geometry(plan['text'], units)
        result['units'] = [{**unit, 'loop': {**loop, 'i': i, 'a': round(geo[i][1], 5), 'b': round(geo[i][2], 5)}}
                           for i, unit in enumerate(units)]
        if loop_type in RICH_LOOP:
            # Glints, glows and fringes need the same layer order as presets.
            result['layered'] = True
    return result


def _identity(plan):
    offset = plan.get('clock_offset_ms', 0)
    duration = plan.get('original_duration_ms', plan['duration_ms'])
    state = dict.fromkeys(CHANNELS, 0.)
    state.update(REST, opacity=1., scale=1., sy=1., reveal=1.)
    row = [state[k] for k in CHANNELS]
    return [[-offset, *row], [duration-offset, *row]]


def _compose_rich(result, plan, loop_type):
    """Entry/exit presets ride on the word units, or on per-glyph units.

    A per-character preset without speech timing staggers glyphs evenly over
    its own entry window. That is entrance art, not a speech claim: measured
    word units are kept whenever a word mode supplies them.
    """
    mode = plan.get('mode')
    units = result.get('units')
    if not units:
        units = (reading_choreography(plan)['units'] if plan.get('spans') and mode != 'line_motion'
                 else [{'char_start': 0, 'char_end': len(plan['text']), 'frames': _identity(plan)}])
    parts = [spec('entry', (plan.get('rich_entry') or {}).get('type')),
             spec('exit', (plan.get('rich_exit') or {}).get('type'))]
    per_char = any(p and p.per_char for p in parts) or loop_type in PER_CHAR_LOOPS
    if per_char and len(units) == 1 and mode not in PRESETS:
        frames = units[0]['frames']
        units = [{**unit, 'frames': frames} for unit in char_spans(plan['text'])]
    units = compose(plan, units, _sample_frames)
    return {**result, 'units': units, 'channels': list(CHANNELS), 'layered': True}


def reading_windows(spans, duration, offset=0):
    """Visual-only intervals: carry ink through brief gaps, hold real pauses.

    Neighbouring intervals share a boundary and its velocity. Harmonic slopes
    keep the cubic monotone, without easing to a stop at every glyph boundary.
    The acoustic spans themselves are never changed or serialized back.
    """
    windows = []
    for i, span in enumerate(spans):
        start = max(0., min(duration, span['start_ms']+offset))
        if windows:
            start = max(start, windows[-1][1])
        end = max(start+.001, min(duration, span['end_ms']+offset))
        if i+1 < len(spans):
            following = min(duration, max(start+.001, spans[i+1]['start_ms']+offset))
            if following-end <= FLOW_GAP_MS:
                end = following
        windows.append([start, end, 0., 0.])
    rates = [1/max(.001, b-a) for a,b,_,_ in windows]
    for i, window in enumerate(windows):
        window[2] = rates[i] if i == 0 else 0.
        window[3] = rates[i] if i == len(windows)-1 else 0.
        if i and abs(windows[i-1][1]-window[0]) < .01:
            velocity = 2*rates[i-1]*rates[i]/(rates[i-1]+rates[i])
            windows[i-1][3] = window[2] = velocity
    return windows


def reading_ink(window, t):
    start, end, first, last = window
    u = _clamp((t-start)/max(.001, end-start))
    return _clamp((-2*u+3)*u*u + (u**3-2*u*u+u)*(end-start)*first
                  + (u**3-u*u)*(end-start)*last)


def _choreograph(plan):
    """No acoustic intervals are created: a missing receipt gets one line unit.

    Adjacent arrivals overlap around their measured onsets. A phrase breathes
    as a stream instead of finishing each letter before beginning the next.
    """
    mode = plan.get('mode')
    if mode == 'karaoke_wipe' or mode in BEAT_MODES or (plan.get('composed_loop') and mode not in PRESETS):
        return reading_choreography(plan)
    if mode not in PRESETS:
        return plan
    offset = plan.get('clock_offset_ms',0)
    duration = max(1, plan.get('original_duration_ms',plan['duration_ms']))
    units = []
    spans = plan.get('spans') or [{'char_start':0, 'char_end':len(plan['text']),
                                  'start_ms':-offset, 'end_ms':duration-offset}]
    n = len(spans)
    reading = reading_windows(spans, duration, offset)
    for i, span in enumerate(spans):
        onset = max(0, min(duration-1, span['start_ms']+offset))
        cadence = max(100., span['end_ms']+offset-onset)
        neighbours = []
        if i and span['start_ms']-spans[i-1]['end_ms'] <= FLOW_GAP_MS:
            neighbours.append(span['start_ms']-spans[i-1]['start_ms'])
        if i+1 < n and spans[i+1]['start_ms']-span['end_ms'] <= FLOW_GAP_MS:
            neighbours.append(spans[i+1]['start_ms']-span['start_ms'])
        if neighbours:
            cadence = max(cadence, min(neighbours))
        enter = min(900., duration*.32, max(240., cadence*1.65))
        anticipation = min(420., enter*.52)
        if i and span['start_ms']-spans[i-1]['end_ms'] > FLOW_GAP_MS:
            anticipation = min(160., anticipation)
        start = max(0., onset-anticipation)
        # A late measured word must still finish entering. A fixed 92% cap
        # can precede its own entrance and suppress the final spoken glyph.
        finish = min(duration-1, start+enter)
        # Even the last late word retains a readable interval before leaving.
        leave = max(finish, min(duration*.90, duration-min(850., duration*.25)+(i/max(1,n-1))*min(180.,duration*.06)))
        stop = duration
        pulse_end = min(leave, max(finish+1, span['end_ms']+offset))
        spoken_end = min(duration,max(onset+1,span['end_ms']+offset))
        preface_end = min(120.,duration*.08)
        read_start, read_end = reading[i][:2]
        times = {0., float(duration), start, finish, leave, pulse_end, onset, spoken_end, preface_end}
        for a,b in ((start,finish),(finish,pulse_end),(leave,stop),(read_start,read_end),(0,preface_end)):
            times.update(a+(b-a)*k/24 for k in range(25))
        frames = []
        for t in sorted(times):
            incoming = _clamp((t-start)/max(1,finish-start))
            outgoing = _clamp((t-leave)/max(1,stop-leave))
            pulse = sin(pi*_clamp((t-finish)/max(1,pulse_end-finish)))
            frames.append([round(t-offset,3), *_pose(mode,incoming,outgoing,pulse,i,
                _clamp(t/preface_end),reading_ink(reading[i],t))])
        units.append({**span, 'frames':frames, **({'shards':shards(i)} if mode=='word_dust' else {})})
    return {**plan, 'units':units, 'channels':list(CHANNELS)}


def reading_choreography(plan):
    """Static white base with a continuous, evidence-anchored ink trajectory.

    Classic word modes use the same units only when combined with a loop, so
    native ASS and advanced rendering share the whole-line motion clock.
    """
    mode = plan['mode']
    offset = plan.get('clock_offset_ms', 0)
    duration = plan.get('original_duration_ms', plan['duration_ms'])
    measured = bool(plan.get('spans'))
    spans = plan.get('spans') if measured and mode != 'line_motion' else [
        {'char_start': 0, 'char_end': len(plan['text']), 'start_ms': -offset, 'end_ms': duration-offset}]
    units = []
    reading = reading_windows(spans, duration, offset)
    for i, span in enumerate(spans):
        start, end = span['start_ms'], max(span['start_ms']+.001, span['end_ms'])
        times = {-offset, duration-offset, start, end}
        if mode == 'karaoke_wipe':
            a, b = reading[i][:2]
            times.update(a+(b-a)*k/24-offset for k in range(25))
        else:
            times.update((start-.001, end-.001))
        if measured and mode in BEAT_MODES:
            times.update(start+BEAT_MS*k/20 for k in range(21))
            if mode == 'word_current_pop':
                times.update(end+120*k/8 for k in range(9))
        frames = []
        for t in sorted(times):
            state = dict.fromkeys(CHANNELS, 0.)
            state.update(REST, opacity=1., scale=1., sy=1., reveal=1.)
            if measured:
                state['ink'] = (reading_ink(reading[i], t+offset) if mode == 'karaoke_wipe'
                                else float(t >= start and (mode not in {'word_current', 'word_current_pop'} or t < end)))
                if mode == 'word_reveal':
                    state['opacity'] = float(t >= start)
                if mode in BEAT_MODES:
                    _beat(mode, state, t-start, t-end)
            frames.append([t, *(state[k] for k in CHANNELS)])
        units.append({**span, 'frames': frames})
    return {**plan, 'units': units, 'channels': list(CHANNELS)}


BEAT_MS = 460.


def _beat(mode, state, since, after_end):
    """Word-onset accents. ``since`` is time from the measured onset."""
    u = max(0., min(1., since/BEAT_MS))
    if mode == 'word_pop':
        if since < 0:
            state['opacity'] = 0.
        else:
            state['opacity'] = min(1., since/70)
            state['scale'] = max(0., out_back(min(1., since/300), 2.6))*.6+.4 if since < 300 else 1.
    elif mode == 'word_current_pop':
        rise = max(0., min(1., since/110))
        fall = max(0., min(1., after_end/120)) if after_end >= 0 else 0.
        lift = out_cubic(rise)*(1-out_cubic(fall)) if since >= 0 else 0.
        state['scale'] = 1+.18*lift
        state['y'] = -.06*lift
    elif mode == 'word_punch' and since >= 0:
        state['scale'] = 1+.32*(1-out_cubic(min(1., since/260)))
        state['flash'] = max(0., 1-since/280)**1.5
        state['halo'] = .9*(1-u)**2
    elif mode == 'word_ripple' and since >= 0:
        state['ghost'] = .9*(1-u)
        state['gs'] = .9*out_cubic(u)
        state['flash'] = .6*max(0., 1-since/220)


def sample(unit, milliseconds):
    state = _sample_frames(unit, milliseconds)
    loop = unit.get('loop')
    if loop:
        loop_apply(state, loop, milliseconds+loop.get('offset', 0))
    return state


def _sample_frames(unit, milliseconds):
    frames = unit['frames']
    milliseconds = float(milliseconds)
    if milliseconds <= frames[0][0]:
        return dict(zip(CHANNELS,frames[0][1:]))
    # First frame at or after the instant (same choice as a forward scan).
    k = bisect_left(frames, milliseconds, 1, key=_frame_time)
    if k < len(frames):
        a, b = frames[k-1], frames[k]
        f = (milliseconds-a[0])/max(.001,b[0]-a[0])
        return dict(zip(CHANNELS,(x+(y-x)*f for x,y in zip(a[1:],b[1:]))))
    return dict(zip(CHANNELS,frames[-1][1:]))


def _frame_time(frame):
    return frame[0]


def particles(index, amount):
    """Eight visible diamond specks; the glyph itself also breaks into cells."""
    return [(sin((index+1)*17+k*5)*(.3+.8*amount),
             -.3-(.3+(k%3)*.25)*amount,
             (.035+.015*(k%2)), max(0.,amount*.75)) for k in range(8)]
