"""Expand the numeric choreography into bounded ASS events, without Lua."""
from math import sin, cos, radians, tan

from ..caption_style.letter_motion import sample, particles
from ..caption_style.motion_catalog import (SLICE_BANDS, STRIP_SHIFTS, GHOST_ALPHA, RGB_COLORS,
                                            SHINE_SLANT, wipe_bands)
from ..caption_style.word_animation import remap_word_animation

#: Dialogue layers: trails/fringes under the glyph, flash/glint/cursor over it.
BACK, BASE, FRONT = 0, 1, 2
#: libass shears with ``x' = x + fax*y`` measured upward from the glyph origin;
#: Qt/CSS use downward y. Verified against rendered frames.
FAX_SIGN = -1.
#: Curated modes that own their whole glyph construction (no generic wipe).
GLYPH_MODES = frozenset({'word_sweep', 'word_pulse', 'word_echo'})


def compile_letter_events(cue, caption, ass_style, plan, width, height, speaker, frame_rate, effect=None):
    from PIL import ImageFont
    from ..caption_style.font_metadata import resolve_local_face
    from .ass_compiler import _dialogue_line, _style_anchor_position, escape_ass_text
    from ..caption_style.effect_dsl import _ass_color
    style = caption.style
    from ..projects.studio_revisions import thaw_json
    transform = thaw_json(getattr(cue, 'transform', {}))
    from ..caption_style.text_marks import layer_marks, remap_marks
    from .marked_glyphs import marked_ass_text
    marks = remap_marks(cue.text, caption.text, layer_marks(cue))
    face,_ = resolve_local_face(style.font_family,style.font_weight,style.font_style_name,style.bold,style.font_file,style.font_face_index)
    font = ImageFont.truetype(face.file,1000,index=face.index)
    em = style.font_size
    sy,sx = style.scale_y/100,style.scale_x/100
    measure = lambda t: font.getlength(t)/1000*em+max(0,len(t)-1)*style.spacing
    rows = caption.text.split('\n')
    widths = [measure(t) for t in rows]
    line_height = sum(font.getmetrics())/1000*em
    widest = max(widths,default=0)
    boxes = [font.getbbox(t or ' ') for t in rows]
    top = min(b[1]/1000*em+i*line_height for i,b in enumerate(boxes))
    bottom = max(b[3]/1000*em+i*line_height for i,b in enumerate(boxes))
    ax = float(transform.get('anchor_x',((style.alignment-1)%3)/2))
    ay = float(transform.get('anchor_y',(1,.5,0)[(style.alignment-1)//3]))
    px,py = _style_anchor_position(style,width,height)
    plan = remap_word_animation(plan,caption.text)
    duration = cue.end_ms-cue.start_ms
    from ..caption_style.motion_application import native_motion_graph
    graph=native_motion_graph(effect,plan.get('original_duration_ms',duration))
    offset=plan.get('clock_offset_ms',0)
    def composed(unit,t):
        state=sample(unit,t)
        group={}
        for track in graph['tracks']:
            keys=track['keyframes'];value=keys[-1]['value']
            if t+offset<=keys[0]['timeMs']:value=keys[0]['value']
            else:
                for a,b in zip(keys,keys[1:]):
                    if t+offset<=b['timeMs']:
                        f=(t+offset-a['timeMs'])/max(1,b['timeMs']-a['timeMs'])
                        value=a['value']+(b['value']-a['value'])*f;break
            group[track['property']]=value
        state['group_scale']=group.get('scale',1)
        state['group_opacity']=group.get('opacity',1)
        state['group_x']=group.get('x',0);state['group_y']=group.get('y',0)
        state['opacity']*=group.get('opacity',1)
        state['scale']*=group.get('scale',1)
        state['blur']+=group.get('blur',0)/em
        return state
    accent = _ass_color(plan.get('color','#B9DDF6'))
    rotation = float(transform.get('rotation', 0) or 0)
    if transform.get('_canvas_transform'):rotation=-rotation
    angle = radians(-rotation)
    # ASS cannot interpolate vector clips. Frame-sample moving cuts so rotated
    # half glyphs / shards retain their actual cut shape, then merge holds.
    import math
    from fractions import Fraction
    rate=Fraction(str(frame_rate or 30)).limit_denominator(100_100)
    times=sorted({Fraction(0),Fraction(duration),*(max(Fraction(0),min(Fraction(duration),Fraction(k*1000)/rate-cue.start_ms))
        for k in range(math.floor(cue.start_ms*rate/1000),math.ceil(cue.end_ms*rate/1000)+1))})
    result=[];char_offset=0
    mode=plan['mode']
    layered=bool(plan.get('layered'))
    for row_index,row in enumerate(rows):
        for index,unit in enumerate(plan['units']):
            a,b=max(char_offset,unit['char_start']),min(char_offset+len(row),unit['char_end'])
            if a>=b:continue
            content=row[a-char_offset:b-char_offset]
            content_marks=[dict(m,start=max(a,m['start'])-a,end=min(b,m['end'])-a)
                           for m in marks if m['start']<b and m['end']>a]
            if not content.strip():continue
            span_width=measure(content)
            cx=(widest-widths[row_index])*ax+measure(row[:a-char_offset])+(style.spacing if a>char_offset else 0)+span_width/2-widest*ax
            cy=row_index*line_height-top-(bottom-top)*ay+line_height/2
            bbox=font.getbbox(content)
            left,right=-span_width/2,span_width/2
            upper,lower=bbox[1]/1000*em-line_height/2,bbox[3]/1000*em-line_height/2
            middle=(upper+lower)/2
            saved={};pending=[];last=None;touched=[]
            for start,stop in zip(times,times[1:]):
                st=composed(unit,start)
                if max(st['opacity'],st['dust'],st['caret'])<.001:
                    last=None;continue
                if st==last:
                    # A still glyph: the same events simply continue. Skips
                    # rebuilding identical override strings frame by frame.
                    for index in touched:pending[index][1]=stop
                    continue
                last=st;touched=[]
                shear=FAX_SIGN*tan(radians(st['skew']))
                # Geometry is cut in glyph space, then transformed as a whole.
                def point(x,y,dx=0.,dy=0.,factor=1.):
                    ux=(x+dx*em)*st['scale']*factor*sx*st['sx']
                    v=(y-middle+dy*em)*st['scale']*factor*sy*st['sy']
                    ux+=FAX_SIGN*shear*v
                    uy=v+middle*sy*st['group_scale']
                    theta=radians(st['rotation'])
                    rx=ux*cos(theta)-uy*sin(theta)
                    ry=ux*sin(theta)+uy*cos(theta)
                    bx=(cx+st['x']*em)*sx*st['group_scale']+st['group_x']
                    by=(cy+st['y']*em)*sy*st['group_scale']+st['group_y']
                    x,y=bx+rx,by+ry
                    return px+x*cos(angle)-y*sin(angle),py+x*sin(angle)+y*cos(angle)
                def shape(pts):
                    return f'm {pts[0][0]:.2f} {pts[0][1]:.2f} l '+' '.join(f'{x:.2f} {y:.2f}' for x,y in pts[1:])
                def clip_tag(rect,dx=0.,dy=0.,factor=1.,polygon=None):
                    if polygon is None:
                        l,t,r,b=rect
                        polygon=[(l,t),(r,t),(r,b),(l,b)]
                    return r'\clip('+shape([point(x,y,dx,dy,factor) for x,y in polygon])+')'
                def emit(body,layer=BASE):
                    # Reuse an identical static event only across adjacent time.
                    previous=saved.get((layer,body))
                    if previous is not None and abs(pending[previous][1]-start)<.01:
                        pending[previous][1]=stop
                    else:
                        previous=saved[(layer,body)]=len(pending);pending.append([start,stop,body,layer])
                    touched.append(previous)
                def text(opacity=1.,dx=0.,dy=0.,rect=None,outline=False,factor=1.,color=None,
                         plain=False,layer=BASE,polygon=None,glow=0.,absolute=False):
                    alpha=max(0,min(1,opacity if absolute else st['opacity']*opacity))
                    if alpha<.001:return
                    x,y=point(0,0,dx,dy,factor)
                    tags=(rf'\an5\q2\fs{ass_style.font_size:.3f}\move({x:.3f},{y:.3f},{x:.3f},{y:.3f})'
                        rf'\alpha&H{round((1-alpha)*255):02X}&\fscx{style.scale_x*st["scale"]*st["sx"]*factor:.3f}'
                        rf'\fscy{style.scale_y*st["scale"]*st["sy"]*factor:.3f}\frz{rotation-st["rotation"]:.3f}'
                        rf'\blur{st["blur"]*em+glow:.3f}')
                    if abs(shear)>1e-4:tags+=rf'\fax{shear:.4f}'
                    if outline:tags+=rf'\1a&HFF&\3c{accent}\bord{em*.018:.3f}\shad0'
                    if plain and glow:tags+=rf'\bord{em*.035:.3f}\shad0\3c{color or accent}'
                    elif plain:tags+=r'\bord0\shad0'
                    if color:tags+=rf'\1c{color}'
                    if rect or polygon:tags+=clip_tag(rect,dx,dy,factor,polygon)
                    emit(marked_ass_text(content,content_marks,ass_style,extra_tags=tags) if content_marks else '{'+tags+'}'+escape_ass_text(content),layer)
                def vector(points,opacity,color=None,layer=BASE):
                    if opacity<.001:return
                    emit(r'{\an7\pos(0,0)\p1\fscx100\fscy100\frz0\bord0\shad0'+rf'\1c{color or accent}\alpha&H{round((1-min(1,opacity))*255):02X}&'+'}'+shape([point(x,y) for x,y in points]),layer)
                pad=em*.4
                height=lower-upper+2*pad
                # Glow, motion trails and chroma fringes sit under the glyph.
                if st['halo']>.001:
                    text(opacity=st['halo'],plain=True,color=accent,glow=em*.22,layer=BACK)
                if st['ghost']>.001:
                    for k in (3,2,1):
                        f=k/3
                        text(opacity=st['ghost']*GHOST_ALPHA[k-1],dx=st['gx']*f,dy=st['gy']*f,factor=1+st['gs']*f,layer=BACK)
                if st['rgb']>.001:
                    for color,side in zip(RGB_COLORS,(-1,1)):
                        text(opacity=.78,dx=side*st['rgb'],color=_ass_color(color),plain=True,layer=BACK)
                if st['trail']>.001 and mode not in {'word_mist'}:
                    for factor in (1,.55):text(opacity=st['trail']*.38,outline=True,factor=1+.7*st['trail']*factor,layer=BACK)
                bands=wipe_bands(st['cut'],st['reveal']) if mode not in GLYPH_MODES else None
                if bands is not None:
                    for a,b,alpha in bands:
                        text(opacity=alpha,rect=(left+span_width*a,upper-pad,left+span_width*b,lower+pad))
                elif abs(st['slice'])>.001:
                    for a,b,shift in SLICE_BANDS:
                        text(dx=st['slice']*shift,rect=(left-pad-em,upper-pad+height*a,right+pad+em,upper-pad+height*b))
                elif st['strips']>.001:
                    width=(span_width+2*pad)/len(STRIP_SHIFTS)
                    for k,shift in enumerate(STRIP_SHIFTS):
                        text(dy=st['strips']*shift,rect=(left-pad+k*width,upper-pad-em,left-pad+(k+1)*width,lower+pad+em))
                elif st['door']>.001:
                    half=span_width/2/em
                    text(dx=-st['door']*half,rect=(left-pad-em,upper-pad,(left+right)/2,lower+pad))
                    text(dx=st['door']*half,rect=((left+right)/2,upper-pad,right+pad+em,lower+pad))
                elif mode=='word_pulse':
                    text(dx=-.28*st['split'],dy=-st['split'],rect=(left-pad,upper-pad,right+pad,middle))
                    text(dx=.28*st['split'],dy=st['split'],rect=(left-pad,middle,right+pad,lower+pad))
                elif mode=='word_echo':
                    text(opacity=.85,outline=True)
                    if st['ink']>.001:text(rect=(left-pad,lower-(lower-upper)*st['ink'],right+pad,lower+pad))
                elif mode in {'karaoke_wipe', 'karaoke_highlight', 'word_current', 'word_current_pop'}:
                    text(color=_ass_color('#FFFFFF') if mode == 'karaoke_wipe' else None)
                    if st['ink'] > .001:
                        text(color=accent, rect=(left-pad, upper-pad, left+span_width*st['ink'], lower+pad))
                elif mode=='word_sweep':
                    edge=left+(span_width+pad)*st['reveal']
                    text(opacity=.25,rect=(left-pad,upper-pad,edge,lower+pad))
                    if st['ink']>.001:text(color=accent,rect=(left-pad,upper-pad,min(edge,left+span_width*st['ink']),lower+pad))
                    x=left+span_width*st['read'];y=upper-(.12+.25*sin(math.pi*st['read']))*em
                    r=em*.095
                    vector([(x-r,y),(x,y-r),(x+r,y),(x,y+r)],st['opacity']*st['glow'])
                    vector([(x-em*.42,y+em*.10),(x,y-em*.012),(x,y+em*.012)],st['opacity']*st['glow'])
                elif st['scatter']>.001 and unit.get('shards'):
                    for shard in unit['shards']:
                        l,t,w,h=shard['rect'];padding=em*.04
                        rect=(left-padding+l*(span_width+2*padding),upper-padding+t*(lower-upper+2*padding),
                              left-padding+(l+w)*(span_width+2*padding),upper-padding+(t+h)*(lower-upper+2*padding))
                        text(dx=shard['x']*st['scatter'],dy=shard['y']*st['scatter'],rect=rect)
                else:
                    if mode=='word_mist' and st['trail']>.001:
                        for factor in (1,.55):text(opacity=st['trail']*.38,outline=True,factor=1+.7*st['trail']*factor)
                    text()
                # Exposure flash, a slanted glint and the cursor sit on top.
                if st['flash']>.001:
                    text(opacity=st['flash']*.6,plain=True,color='&HFFFFFF&',glow=em*.18,layer=FRONT)
                    text(opacity=st['flash'],plain=True,color='&HFFFFFF&',layer=FRONT)
                if -.6<st['shine']<1.6:
                    half=float(unit.get('sw',.18));slant=(lower-upper)*SHINE_SLANT
                    for width,alpha in ((half*2.4,.28),(half,.85)):
                        l=left+span_width*(st['shine']-width);r=left+span_width*(st['shine']+width)
                        band=[(l+slant,upper-em),(r+slant,upper-em),(r-slant,lower+em),(l-slant,lower+em)]
                        text(opacity=alpha,plain=True,color='&HFFFFFF&',glow=em*.16,layer=FRONT,polygon=band)
                        text(opacity=alpha,plain=True,color='&HFFFFFF&',layer=FRONT,polygon=band)
                if st['caret']>.001:
                    x0=right+em*.06;x1=x0+max(1.,em*.07)
                    vector([(x0,upper-em*.04),(x1,upper-em*.04),(x1,lower+em*.04),(x0,lower+em*.04)],st['caret'],
                           color='&HFFFFFF&',layer=FRONT)
                if st['dust']>.001:
                    for k,(x,y,r,alpha) in enumerate(particles(unit['char_start'],st['dust'])):
                        x=left+span_width*(k+.5)/8+x*em;y=middle+y*em;r*=em
                        vector([(x-r,y),(x,y-r),(x+r,y),(x,y+r)],alpha*st['group_opacity'])
            for start,stop,body,layer in pending:
                result.append(_dialogue_line(start_ms=cue.start_ms+start,end_ms=cue.start_ms+stop,
                    style_id=ass_style.id,speaker=speaker,text=body,frame_rate=frame_rate,
                    layer=layer if layered else 0))
        char_offset+=len(row)+1
    return result
