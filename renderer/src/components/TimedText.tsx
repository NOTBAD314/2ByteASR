import React from 'react';

type Loop = {type: string; offset?: number; start: number; end: number; duration?: number; strength?: string;
  i?: number; a?: number; b?: number};
export type WordAnimation = {
  mode?: string; color?: string;
  marks?: {start: number; end: number; bold?: boolean; italic?: boolean; highlight?: boolean; color?: string}[];
  spans?: {char_start: number; char_end: number; start_ms: number; end_ms: number}[];
  channels?: string[];
  units?: {char_start: number; char_end: number; frames: number[][]; shards?: {rect: number[]; x: number; y: number}[];
    sw?: number; loop?: Loop}[];
};

// Shared drawing geometry: twobyteasr/caption_style/motion_catalog.py.
const SLICE_BANDS = [[0, .36, 1], [.36, .64, -.7], [.64, 1, .55]];
const STRIP_SHIFTS = [.9, -.65, .8, -.9, .55];
const GHOST_ALPHA = [.42, .26, .13];
const RGB_COLORS = ['#FF2D55', '#19E6FF'];
const WIPE_FEATHER = .08;
const STRENGTH: Record<string, number> = {low: .72, medium: 1, high: 1.28};
/** Curated modes that own their whole glyph construction (no generic wipe). */
const GLYPH_MODES = ['word_sweep', 'word_pulse', 'word_echo'];

const pose = (frames: number[][], time: number): number[] => {
  if (time <= frames[0][0]) return frames[0].slice(1);
  for (let i=1;i<frames.length;i++) {
    const a=frames[i-1], b=frames[i];
    if (time<=b[0]) {
      const f=(time-a[0])/Math.max(.001,b[0]-a[0]);
      return a.slice(1).map((v,k)=>v+(b[k+1]-v)*f);
    }
  }
  return frames[frames.length-1].slice(1);
};

/** Mirror of motion_catalog.loop_apply: analytic, seek-safe loops. */
const applyLoop = (s: Record<string, number>, l: Loop, t: number) => {
  const period=Math.max(120,l.duration||1200);
  const ramp=Math.min(1,Math.max(0,(t-l.start)/(period*.25)),Math.max(0,(l.end-t)/(period*.25)));
  if (ramp<=0) return;
  const amount=(STRENGTH[l.strength||'medium']??1)*ramp;
  const phase=2*Math.PI*(t-l.start)/period;
  const wave=(1-Math.sin(phase+Math.PI/2))/2;
  const i=l.i??0, a=l.a??0, b=l.b??1;
  const frac=(v: number)=>((v%1)+1)%1;
  const ph=frac((t-l.start)/period);
  switch (l.type) {
    case 'loop_breathe': s.scale*=1+.065*wave*amount; break;
    case 'loop_float': s.y-=.18*wave*amount; break;
    case 'loop_sway': s.x+=.18*Math.sin(phase)*amount; break;
    case 'loop_swing': s.rotation+=5*Math.sin(phase)*amount; break;
    case 'loop_wave': s.y-=.14*Math.sin(phase-2*Math.PI*.85*(a+b)/2)*amount; break;
    case 'loop_heartbeat': {
      const beat=Math.exp(-(((ph-.08)/.045)**2))+.65*Math.exp(-(((ph-.27)/.045)**2));
      s.scale*=1+.085*beat*amount; break;
    }
    case 'loop_bounce': {
      const p=frac((t-l.start)/period-.6*(a+b)/2);
      const hop=p<.32?Math.sin(Math.PI*p/.32):0;
      s.y-=.26*hop*hop*amount; break;
    }
    case 'loop_shake': {
      const speed=1200/period;
      s.x+=.045*(Math.sin(t*.0372*speed+i*1.7)+.6*Math.sin(t*.0911*speed+i*.9))*amount;
      s.y+=.04*(Math.sin(t*.0433*speed+i*2.3)+.6*Math.sin(t*.0797*speed+i*.4))*amount; break;
    }
    case 'loop_shine':
      if (ph<.55) s.shine=(-.35+1.7*ph/.55-a)/Math.max(.001,b-a);
      break;
    case 'loop_halo': s.halo=Math.max(s.halo,(.3+.5*wave)*amount); break;
    case 'loop_flicker': {
      const dip=(ph>.62&&ph<.66)||(ph>.72&&ph<.745)?1:0;
      s.opacity*=1-.55*dip*amount;
      s.halo=Math.max(s.halo,.25*(1-dip)*amount); break;
    }
    case 'loop_glitch':
      if (ph<.14) {
        const burst=Math.sin(Math.PI*ph/.14)*amount;
        s.rgb+=.06*burst;
        s.slice+=.22*burst*(Math.floor(t/40)%2?1:-1);
        s.x+=.05*burst*Math.sin(t*.51);
      }
      break;
  }
};

/** Mirror of motion_catalog.wipe_bands. ``null`` = draw unclipped. */
const wipeBands = (cut: number, reveal: number): number[][] | null => {
  if (reveal>=1 && cut<=0) return null;
  const lo=cut>0?cut:-.5, hi=reveal<1?reveal:1.5;
  if (hi<=lo || hi+WIPE_FEATHER<=0 || lo-WIPE_FEATHER>=1) return [];
  const bands=[[cut>0?lo+WIPE_FEATHER:lo, reveal<1?hi-WIPE_FEATHER:hi, 1]];
  if (reveal<1) bands.push([Math.max(lo,hi-WIPE_FEATHER),hi,.55],[hi,hi+WIPE_FEATHER,.2]);
  if (cut>0) bands.push([lo,Math.min(hi,lo+WIPE_FEATHER),.55],[lo-WIPE_FEATHER,lo,.2]);
  return bands.filter(([x,y])=>y>x);
};

/** A moving word samples its original part of the full caption's gradient. */
const paintSlice = (text: string, start: number, part: string, font: React.CSSProperties = {}): React.CSSProperties => {
  const context = document.createElement('canvas').getContext('2d');
  if (!context) return {};
  const size = Number(font.fontSize) || 32;
  context.font = `${font.fontStyle || 'normal'} ${font.fontWeight || 400} ${size}px ${font.fontFamily || 'sans-serif'}`;
  const spacing = Number(font.letterSpacing) || 0;
  const measure = (value: string) => context.measureText(value).width + Array.from(value).length*spacing;
  const rows = text.split('\n');
  const before = Array.from(text).slice(0,start).join('').split('\n');
  const row = before.length-1;
  const width = Math.max(1,...rows.map(measure));
  const x = (width-measure(rows[row] || ''))/2+measure(before[before.length-1]);
  const lineHeight = typeof font.lineHeight === 'string' ? parseFloat(font.lineHeight) : (Number(font.lineHeight)||1.12)*size;
  return {backgroundSize:`${width}px ${lineHeight*rows.length}px`,backgroundPosition:`${-x}px ${-row*lineHeight}px`};
};

const plainColor = (color: string): React.CSSProperties => ({color, WebkitTextFillColor: color, backgroundImage: 'none',
  textShadow: 'none', WebkitTextStroke: '0 transparent'});

/** Keep the full line in layout; reveal never recenters the words already read. */
export const TimedText: React.FC<{
  text: string; plan?: WordAnimation; milliseconds: number; fill?: boolean; paint?: React.CSSProperties; paintFont?: React.CSSProperties;
}> = ({text, plan, milliseconds, fill = false, paint, paintFont}) => {
  const letters = Array.from(text);
  const marked = (a: number, b: number, tint?: string) => {
    const marks = plan?.marks || [];
    const edges = [...new Set([a,b,...marks.flatMap(m=>[Math.max(a,m.start),Math.min(b,m.end)]).filter(x=>x>a&&x<b)])].sort((x,y)=>x-y);
    return edges.slice(0,-1).map((start,i)=>{
      const end = edges[i+1];
      const attrs = Object.assign({},...marks.filter(m=>m.start<=start&&m.end>=end));
      const color = tint || attrs.color || (attrs.highlight ? '#FFD166' : undefined);
      return <span key={start} style={{fontWeight: attrs.bold===undefined ? undefined : attrs.bold?700:400,
        fontStyle: attrs.italic===undefined?undefined:attrs.italic?'italic':'normal',
        ...(fill&&color?{color,WebkitTextFillColor:color}: {})}}>{letters.slice(start,end).join('')}</span>;
    });
  };
  const raw = plan?.color || '#FFD166';
  const color = /^#[a-f0-9]{8}$/i.test(raw) ? `#${raw.slice(3)}${raw.slice(1,3)}` : raw;
  if (plan?.units?.length) return <>{plan.units.map((unit,index)=>{
    const values=pose(unit.frames,milliseconds);
    const s=Object.fromEntries((plan.channels||[]).map((name,k)=>[name,values[k]]));
    for (const [name,rest] of Object.entries({sx:1,skew:0,flash:0,halo:0,rgb:0,ghost:0,gx:0,gy:0,gs:0,
      shine:-9,slice:0,strips:0,door:0,cut:0,caret:0})) if (s[name]===undefined) s[name]=rest;
    if (unit.loop) applyLoop(s,unit.loop,milliseconds+(unit.loop.offset||0));
    const {opacity,x,y,scale,rotation,blur,glow,reveal,trail,dust,split,sy,ink,read,scatter,
      sx,skew,flash,halo,rgb,ghost,gx,gy,gs,shine,slice,strips,door,cut,caret}=s;
    const parts=letters.slice(unit.char_start,unit.char_end).join('').split('\n');
    return <React.Fragment key={index}>{parts.map((part,line)=>{
      const partStart=unit.char_start+Array.from(parts.slice(0,line).join('\n')).length+(line?1:0);
      const partEnd=partStart+Array.from(part).length;
      const slicePaint=fill&&paint?.backgroundImage?paintSlice(text,unit.char_start+
        Array.from(parts.slice(0,line).join('\n')).length+(line?1:0),part,paintFont):{};
      const tile=(extra: React.CSSProperties={},key: React.Key='body')=><span key={key} style={{
        ...(fill?paint:{}),...slicePaint,position:'absolute',inset:0,display:'block',opacity,
        filter:`blur(${blur}em)`,
        ...extra}}>{plan?.marks?.length ? marked(partStart,partEnd,typeof extra.color==='string'?extra.color:undefined) : part}</span>;
      const bands=GLYPH_MODES.includes(plan.mode||'')?null:wipeBands(cut,reveal);
      let body: React.ReactNode;
      if (bands) {
        body=bands.map(([a,b,alpha],k)=>tile({opacity:opacity*alpha,
          clipPath:`inset(-.4em ${100*(1-b)}% -.4em ${100*a}%)`},`wipe${k}`));
      } else if (Math.abs(slice)>.001) {
        body=SLICE_BANDS.map(([a,b,shift],k)=>tile({clipPath:`inset(${a*100}% -1em ${100-b*100}% -1em)`,
          transform:`translateX(${slice*shift}em)`},`slice${k}`));
      } else if (strips>.001) {
        body=STRIP_SHIFTS.map((shift,k)=>tile({clipPath:`inset(-1em ${100-(k+1)*20}% -1em ${k*20}%)`,
          transform:`translateY(${strips*shift}em)`},`strip${k}`));
      } else if (door>.001) {
        body=[tile({clipPath:'inset(-.4em 50% -.4em -1em)',transform:`translateX(${-door*50}%)`},'doorL'),
          tile({clipPath:'inset(-.4em -1em -.4em 50%)',transform:`translateX(${door*50}%)`},'doorR')];
      } else if (plan.mode==='word_pulse') {
        body=[-1,1].map(side=>tile({clipPath:side<0?'inset(-.4em -.4em 50% -.4em)':'inset(50% -.4em -.4em -.4em)',
          transform:`translate(${side*.28*split}em,${side*split}em)`},side));
      } else if (plan.mode==='word_echo') {
        body=<>{fill&&tile({color:'transparent',WebkitTextFillColor:'transparent',backgroundImage:'none',
          WebkitTextStroke:`.018em ${color}`,textShadow:'none',opacity:opacity*.85},'outline')}
          {ink>.001&&tile({clipPath:`inset(${100*(1-ink)}% -.4em -.4em -.4em)`})}</>;
      } else if (['karaoke_wipe','karaoke_highlight','word_current','word_current_pop'].includes(plan.mode||'')) {
        body=<>{tile(fill&&plan.mode==='karaoke_wipe'?{
            color:'#FFFFFF',WebkitTextFillColor:'#FFFFFF',backgroundImage:'none'}:{},'base')}
          {fill&&ink>.001&&tile({clipPath:`inset(-.4em ${100*(1-ink)}% -.4em -.4em)`,
            color,WebkitTextFillColor:color,backgroundImage:'none'},'blue')}</>;
      } else if (plan.mode==='word_sweep') {
        body=<span style={{position:'absolute',inset:0,clipPath:`inset(-1em ${100*(1-reveal)}% -1em -.4em)`}}>
          {tile({opacity:opacity*.25},'dim')}
          {tile({clipPath:`inset(-.4em ${100*(1-ink)}% -.4em -.4em)`,
            ...(fill?{color,WebkitTextFillColor:color,backgroundImage:'none'}:{})},'lit')}
          {fill&&glow>.001&&<svg viewBox='0 0 100 100' preserveAspectRatio='none' style={{position:'absolute',
            overflow:'visible',left:0,top:0,width:'100%',height:'1em',opacity:opacity*glow}}>
            <path d={`M ${read*100-35} ${-2-25*Math.sin(Math.PI*read)} L ${read*100} ${-12-25*Math.sin(Math.PI*read)}`}
              stroke={color} strokeWidth='2.5' strokeLinecap='round'/>
            <path d='M -8 0 L 0 -8 L 8 0 L 0 8 Z' fill={color}
              transform={`translate(${read*100},${-12-25*Math.sin(Math.PI*read)})`}/>
          </svg>}
        </span>;
      } else if (scatter>.001&&unit.shards?.length) {
        body=unit.shards.map((shard,k)=>tile({clipPath:`inset(${shard.rect[1]*100}% ${100*(1-shard.rect[0]-shard.rect[2])}% ${100*(1-shard.rect[1]-shard.rect[3])}% ${shard.rect[0]*100}%)`,
          transform:`translate(${shard.x*scatter}em,${shard.y*scatter}em)`},k));
      } else body=tile();
      const half=unit.sw??.18;
      return <React.Fragment key={line}>{line>0&&<br/>}
        <span style={{display:'inline-block',position:'relative',whiteSpace:'pre',
          transform:`translate(${x}em,${y}em) rotate(${rotation}deg)${Math.abs(skew)>.01?` skewX(${skew}deg)`:''} scale(${scale*sx},${scale*sy})`,
          transformOrigin:'50% 50%'}}>
          <span style={{opacity:0}}>{part}</span>
          {fill&&halo>.001&&tile({...plainColor(color),opacity:Math.min(1,opacity*halo),filter:'blur(.22em)'},'halo')}
          {fill&&ghost>.001&&[3,2,1].map(k=>tile({opacity:opacity*ghost*GHOST_ALPHA[k-1],
            transform:`translate(${gx*k/3}em,${gy*k/3}em) scale(${1+gs*k/3})`},`ghost${k}`))}
          {fill&&rgb>.001&&RGB_COLORS.map((tint,k)=>tile({...plainColor(tint),opacity:opacity*.78,
            transform:`translateX(${(k?1:-1)*rgb}em)`},`rgb${k}`))}
          {fill&&trail>.002&&[1,.55].map(factor=>tile({opacity:opacity*trail*.38,color:'transparent',
            WebkitTextFillColor:'transparent',backgroundImage:'none',WebkitTextStroke:`.014em ${color}`,textShadow:'none',
            filter:'none',transform:`scale(${1+.7*trail*factor})`},factor))}
          {fill&&plan.mode==='word_mist'&&glow>.001&&tile({color,WebkitTextFillColor:color,
            backgroundImage:'none',textShadow:'none',opacity:opacity*glow*.3,filter:'blur(.12em)'},'mist-halo')}
          {body}
          {fill&&flash>.001&&<>
            {tile({...plainColor('#FFFFFF'),opacity:Math.min(1,opacity*flash*.6),filter:'blur(.18em)'},'flash-glow')}
            {tile({...plainColor('#FFFFFF'),opacity:Math.min(1,opacity*flash)},'flash')}</>}
          {fill&&shine>-.6&&shine<1.6&&[[half*2.4,.28],[half,.85]].map(([width,alpha],k)=>{
            // White glint on white type is only visible as bloom past the edges.
            const band=`polygon(calc(${(shine-width)*100}% + .3em) -1em, calc(${(shine+width)*100}% + .3em) -1em, `+
              `calc(${(shine+width)*100}% - .3em) calc(100% + 1em), calc(${(shine-width)*100}% - .3em) calc(100% + 1em))`;
            return <React.Fragment key={`shine${k}`}>
              {tile({...plainColor('#FFFFFF'),opacity:Math.min(1,opacity*alpha),clipPath:band,filter:'blur(.16em)'},`bloom${k}`)}
              {tile({...plainColor('#FFFFFF'),opacity:opacity*alpha,clipPath:band},`glint${k}`)}
            </React.Fragment>;})}
          {fill&&caret>.001&&<span style={{position:'absolute',left:'calc(100% + .06em)',top:'-.04em',width:'.07em',
            height:'calc(100% + .08em)',background:'#FFFFFF',opacity:Math.min(1,caret)}}/>}
          {fill&&dust>.001&&Array.from({length:8},(_,k)=><span key={k} style={{position:'absolute',
            left:`calc(${(k+.5)/8*100}% + ${Math.sin((unit.char_start+1)*17+k*5)*(.3+.8*dust)}em)`,
            top:`calc(50% + ${-.3-(.3+(k%3)*.25)*dust}em)`,
            width:`${2*(.035+.015*(k%2))}em`,height:`${2*(.035+.015*(k%2))}em`,
            background:color,transform:'rotate(45deg)',opacity:dust*.75}}/>)}
        </span>
      </React.Fragment>;
    })}</React.Fragment>;
  })}</>;
  if (!plan?.spans?.length) return <>{plan?.marks?.length ? marked(0,letters.length) : text}</>;
  const lead = plan.spans[0].char_start;
  return <>{plan?.marks?.length ? marked(0,lead) : letters.slice(0,lead).join('')}{plan.spans.map((span, index) => {
    const started = milliseconds >= span.start_ms;
    const highlight = started && (plan.mode !== 'word_current' || milliseconds < span.end_ms);
    return <span key={index} style={{
      visibility: plan.mode === 'word_reveal' && !started ? 'hidden' : undefined,
      ...(fill && plan.mode !== 'word_reveal' && highlight
        ? {color, WebkitTextFillColor: color} : {}),
    }}>{plan?.marks?.length ? marked(span.char_start,span.char_end,fill&&plan.mode!=='word_reveal'&&highlight?color:undefined) : letters.slice(span.char_start, span.char_end).join('')}</span>;
  })}</>;
};
