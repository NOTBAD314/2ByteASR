"""Finite source-pixel effects; presentation only, driven by MotionSpec time."""
import math

PIXEL_SCHEMA={'type':'object','additionalProperties':False,
    'required':['mode','seed','blockSize','intensity'],
    'properties':{'mode':{'enum':['alchemy','mineral','sigil']},
        'seed':{'type':'integer','minimum':0,'maximum':2147483647},
        'blockSize':{'type':'number','minimum':6,'maximum':64},
        'intensity':{'type':'number','minimum':0,'maximum':2},
        'direction':{'enum':[-1,1]},
        'surface':{'enum':['whole','panel','text','ornament']},
        'clipToBounds':{'type':'boolean'},
        'quality':{'enum':['draft','standard','full']}}}


def validate_pixels(value):
    import jsonschema
    jsonschema.validate(value,PIXEL_SCHEMA)
    for key in ('blockSize','intensity'):
        if isinstance(value[key],bool) or not math.isfinite(value[key]):raise ValueError('pixels需要有限数值')
    return dict(value)


def noita_motion(value):
    """v9 inherits *exactly* the approved v8 markup, CSS and appearance."""
    from .caption_noita import compose
    options=dict(value)
    entry=options.pop('entryEffect','alchemy');exit=options.pop('exitEffect',entry)
    strength=options.pop('intensity',1);seed=options.pop('seed',731)
    block=options.pop('blockSize',16);quality=options.pop('quality','full')
    options['version']=8
    options.setdefault('resolveMs',300)
    theme=compose(options)
    tracks=theme['motionSpec']['tracks']
    theme['motionSpec']['tracks']=[t for t in tracks if not (
        t['selector'] in {'.nt-read','.nt-copy'} and t['phase'] in {'build','resolve'})]
    for phase,mode in [('build',entry),('resolve',exit)]:
        pixels=validate_pixels(dict(mode=mode,seed=seed,blockSize=block,intensity=strength,quality=quality,direction=1,clipToBounds=True))
        theme['motionSpec']['tracks'].append(dict(selector='.nt-read',phase=phase,start=0,end=.9 if phase=='build' else .52,
            ease='none',**{'from':{'--pixel-progress':0},'to':{'--pixel-progress':1}},pixels=pixels))
    # Leave 45ms clear in the shared clock's 100ms short-cue resolve window.
    # The last encoded 24fps frame precedes the cue end by 41.67ms; checking
    # only the 30fps proxy (33.33ms) would miss residual source/seal pixels.
    # The existing seal triggers/reclaims the surface and goes out last.
    for t in theme['motionSpec']['tracks']:
        if t['phase']=='resolve':
            t['end']=min(t['end'],.55)
            if t['selector']=='.nt-seal':t.update(start=.52,end=.55)
    return theme


def capability_text():
    return ('像素源图能力：MotionSpec2 build/resolve轨可用pixels:{mode:alchemy|mineral|sigil,seed:0..2147483647整数,'
        'blockSize:6..64设计像素,intensity:0..2,direction:1|-1,quality:draft|standard|full,clipToBounds:可选布尔}；'
        '该轨from:{"--pixel-progress":0},to:{"--pixel-progress":1},ease:none，不混用其他属性/重复/wiggle/stagger。'
        'selector定位有实际宽高的内部字框容器（不能宿主、不能SVG目标），按源图alpha切块，不复制正文。'
        'alchemy分簇成形/暖色余烬上浮，mineral格块短移归位/分批重力下坠，sigil多邻域召唤/向左右锚点回收。'
        '稳定阅读恢复原像素，短cue用阅读态。Noita组件version:9继承v8全部静态美术，新增entryEffect/exitEffect独立三选，'
        'intensity默认1、seed默认731、blockSize默认16、quality默认full；例如'
        '{"version":9,"direction":"reaction","entryEffect":"alchemy","exitEffect":"sigil","intensity":1}。'
        '当前优先version:10：同一v8静态源，分开真实底板/字面/图标像素；默认560ms入场、460ms退场，'
        'buildMs允许420..620，resolveMs允许320..500；40–55%入场主字已归位。'
        '显式timingProfile:readable-pixel按>3秒/1.8–3秒/<1.8秒分档；不改变旧v9档案。'
        '例如{"version":10,"direction":"reaction","entryEffect":"alchemy","exitEffect":"alchemy"}。')


def readable_noita_motion(value):
    """v10 preserves the v8 source, separating motion paint without text copies."""
    from .caption_noita import compose
    options=dict(value);options.pop('version')
    entry=options.pop('entryEffect','alchemy');exit=options.pop('exitEffect','alchemy')
    seed=options.pop('seed',731);intensity=options.pop('intensity',1)
    block=options.pop('blockSize',16);quality=options.pop('quality','full')
    build=options.pop('buildMs',560);resolve=options.pop('resolveMs',460)
    if not 420<=build<=620 or not 320<=resolve<=500:raise ValueError('可读像素完整入场420–620ms，退场320–500ms')
    theme=compose(dict(options,version=8))
    # Static source and original reading details are retained verbatim.
    tracks=[t for t in theme['motionSpec']['tracks'] if t['phase']=='breathe']
    def pixels(selector,surface,phase,start,end,mode,size):
        if selector=='.nt-reagent' and options.get('direction') in {'tablet','warning'}:return
        effect=validate_pixels(dict(mode=mode,seed=seed,blockSize=size,intensity=intensity,quality=quality,
                                    direction=1,clipToBounds=surface=='panel',surface=surface))
        tracks.append(dict(selector=selector,phase=phase,start=start,end=end,ease='none',
          **{'from':{'--pixel-progress':0},'to':{'--pixel-progress':1}},pixels=effect))
    # Frame, glyphs, then original flask/sigil/charge; glyphs settle by 47%.
    pixels('.nt-read','panel','build',0,.42,entry,block)
    pixels('.nt-copy','text','build',.12,.47,entry,8)
    for selector,start,end in [('.nt-reagent',.40,.82),('.nt-seal',.55,.96),('.nt-charge',.46,1)]:
        pixels(selector,'ornament','build',start,end,entry,8)
    tracks.append(dict(selector='.nt-charge',phase='build',start=0,end=1,ease='none',
      **{'from':{'opacity':.55},'to':{'opacity':.55}}))
    # Energy loss leads. Edges release later and travel independently upward.
    for selector,end in [('.nt-charge',.23),('.nt-reagent',.42),('.nt-seal',.50)]:
        pixels(selector,'ornament','resolve',0,end,exit,8)
    pixels('.nt-read','panel','resolve',.16,1,exit,block)
    pixels('.nt-copy','text','resolve',.23,.91,exit,8)
    # Keep the existing authored sparks subtle; they never replace the surface.
    for i in range(3):
        tracks.append(dict(selector=f'.nt-mote-{i}',phase='build',start=.7,end=1,ease='power2.out',
          **{'from':{'y':8,'opacity':0},'to':{'y':-8-i*3,'opacity':.75}}))
    tracks.append(dict(selector='.nt-dust',phase='resolve',start=0,end=.4,ease='power1.out',
      **{'from':{'opacity':1},'to':{'opacity':0}}))
    theme['motionSpec']=dict(version=2,runtime='gsap',timingProfile='readable-pixel',buildMs=build,resolveMs=resolve,tracks=tracks)
    return theme
