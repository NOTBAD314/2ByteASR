import React from 'react';
import {interpolate} from 'remotion';
import type {Recipe} from '../SubtitleComposition';
import {OutsideStrokeText} from './OutsideStrokeText';

const KNOWN_DECORATIONS = new Set(['corner_brackets','left_bracket','right_bracket','scanline','side_line','underline','accent_line','particle_lite']);

const gradient = (recipe: Recipe): string => {
  if (recipe.fill.type === 'solid') return recipe.fill.color;
  const stops = recipe.fill.stops.map((stop) => `${stop.color} ${Math.round(stop.pos * 100)}%`).join(', ');
  return recipe.fill.kind === 'radial'
    ? `radial-gradient(circle, ${stops})`
    : `linear-gradient(${90 - recipe.fill.angle}deg, ${stops})`;
};

const numberValue = (value: unknown, fallback: number): number => typeof value === 'number' ? value : fallback;
const stringValue = (value: unknown, fallback: string): string => typeof value === 'string' ? value : fallback;
// Snapshot strokes arrive as project ARGB (`#AARRGGBB`), same as the
// visualGraph textLayer contract: convert once here at the Remotion boundary.
// Without this, `#FF000000` parses as CSS `#RRGGBBAA` → alpha 00 → the whole
// outside-stroke ring renders fully transparent (stroke "disappears").
const cssColor = (value: unknown, fallback = '#ff000000'): string => {
  const text = stringValue(value, fallback);
  if (/^#[0-9a-f]{8}$/i.test(text)) return `#${text.slice(3)}${text.slice(1, 3)}`;
  return text;
};

const textureImage = (type: string, scale: number, seed: number): string | undefined => {
  const unit = Math.max(2, Math.round(6 * scale));
  if (type === 'paper_grain' || type === 'noise') return `repeating-radial-gradient(circle at ${20 + seed % 60}% ${15 + seed % 70}%,#00000018 0 1px,transparent 1px ${unit}px)`;
  if (type === 'film_grain') return `repeating-linear-gradient(${87 + seed % 7}deg,#fff1 0 1px,#0001 1px 2px,transparent 2px ${unit}px)`;
  if (type === 'halftone') return `radial-gradient(circle,#0007 1px,transparent 1.5px)`;
  if (type === 'scanlines') return `repeating-linear-gradient(0deg,#0006 0 1px,transparent 1px ${Math.max(3, unit)}px)`;
  if (type === 'pixel_grid') return `linear-gradient(#fff2 1px,transparent 1px),linear-gradient(90deg,#fff2 1px,transparent 1px)`;
  return undefined;
};

const directionOffset = (direction: string, amount: number): [number, number] => {
  if (direction === 'right') return [amount, 0];
  if (direction === 'up') return [0, -amount];
  if (direction === 'down') return [0, amount];
  return [-amount, 0];
};

export const TrustedSubtitle: React.FC<{text: string; recipe: Recipe; frame: number; durationFrames: number; fps: number}> = ({text, recipe, frame, durationFrames, fps}) => {
  const entrance = recipe.motion.entrance ?? {};
  const hold = recipe.motion.hold ?? {};
  const exit = recipe.motion.exit ?? {};
  const entranceType = stringValue(entrance.type, recipe.motion.entry ?? 'none');
  const exitType = stringValue(exit.type, 'none');
  const holdType = stringValue(hold.type, 'none');
  const legacyMotion = entranceType !== 'none' || exitType !== 'none' || holdType !== 'none';
  const motionEnabled = recipe.motion.mode === 'explicit' || (recipe.motion.mode === undefined && legacyMotion);
  const entranceActive = motionEnabled && entranceType !== 'none';
  const exitActive = motionEnabled && exitType !== 'none';
  const holdActive = motionEnabled && holdType !== 'none';
  const entranceFrames = Math.max(1, Math.round(numberValue(entrance.duration_ms, recipe.motion.duration ?? 240) / 1000 * fps));
  const exitFrames = Math.max(1, Math.round(numberValue(exit.duration_ms, 160) / 1000 * fps));
  const entryProgress = entranceActive ? interpolate(frame, [0, entranceFrames], [0, 1], {extrapolateLeft:'clamp',extrapolateRight:'clamp'}) : 1;
  const exitProgress = exitActive ? interpolate(frame, [Math.max(0, durationFrames-exitFrames), durationFrames], [0, 1], {extrapolateLeft:'clamp',extrapolateRight:'clamp'}) : 0;
  const glitch = entranceActive && (entranceType.includes('glitch') || entranceType === 'slam');
  const punch = entranceActive && (['spring_pop','overshoot','slam','squash_stretch'].includes(entranceType) || entranceType.includes('impact') || entranceType.includes('punch') || entranceType.includes('bounce'));
  const soft = entranceActive && (['fade','slide','drop','scale','rotate','flip','wipe','mask_reveal','type_on','letter_stagger'].includes(entranceType) || entranceType.includes('neon') || entranceType.includes('fade_float') || entranceType.includes('tracking'));
  const activeGlitch = glitch && entryProgress < 1;
  const sliceCount = Math.max(2, Math.round(numberValue(entrance.slice_count, 5)));
  const chromaticOffset = numberValue(entrance.chromatic_offset, 6);
  const glitchIntensity = numberValue(entrance.glitch_intensity, 1);
  const microInterval = Math.max(300, numberValue(hold.micro_glitch_interval_ms, 1800));
  const microPhase = (frame / fps * 1000) % microInterval;
  const microGlitch = glitch && entryProgress >= 1 && microPhase < 55;
  const jitter = activeGlitch
    ? Math.sin(frame * 9.7) * (1-entryProgress) * 16 * glitchIntensity
    : microGlitch ? Math.sin(frame * 13) * 2 : 0;
  let motionScale = 1;
  if (punch) {
    motionScale = entryProgress < .45
      ? interpolate(entryProgress, [0,.45], [.70,1.18])
      : entryProgress < .72
        ? interpolate(entryProgress, [.45,.72], [1.18,.96])
        : interpolate(entryProgress, [.72,1], [.96,1]);
  }
  const direction = stringValue(entrance.direction, entranceType === 'drop' ? 'down' : 'left');
  const [entryX, entryY] = entranceActive ? directionOffset(direction, (1-entryProgress) * numberValue(entrance.amplitude, entranceType === 'slam' ? 70 : 28)) : [0, 0];
  const [exitX, exitY] = exitActive ? directionOffset(stringValue(exit.direction, 'down'), exitProgress * numberValue(exit.amplitude, 34)) : [0, 0];
  const frequency = Math.max(.1, numberValue(hold.frequency, 4));
  const amplitude = numberValue(hold.amplitude, holdType === 'handheld' ? 2.2 : 1.2);
  const wave = Math.sin(frame / fps * Math.PI * 2 * frequency);
  const holdX = holdActive && ['micro_jitter','handheld','wiggle','boil'].includes(holdType) ? wave * amplitude : 0;
  const holdY = holdActive && ['float','breath','per_letter_bounce','boil'].includes(holdType) ? wave * amplitude : 0;
  const holdScale = holdActive && ['breath','pulse'].includes(holdType) ? 1 + wave * Math.min(.08, amplitude / 100) : 1;
  const flickerOpacity = holdActive && ['flicker','film_gate'].includes(holdType) && Math.sin(frame * 2.37) > .78 ? .72 : 1;
  const rise = (soft ? entryY : 0) + holdY + exitY;
  const glowSettle = soft ? (entryProgress < .72 ? entryProgress / .72 * 1.25 : interpolate(entryProgress,[.72,1],[1.25,1])) : 1;
  const entryOpacity = entranceActive ? (soft ? entryProgress : Math.min(1,entryProgress*1.7)) : 1;
  const exitOpacity = exitActive ? 1-exitProgress : 1;
  const opacity = Math.max(0, entryOpacity * exitOpacity * flickerOpacity);
  const tracking = recipe.typography.spacing + (soft ? (1-entryProgress)*8 : 0);
  const shadow = recipe.shadow ?? {color:'#00000000',offsetX:0,offsetY:0,blur:0};
  const panel = recipe.background ?? {enabled:false,type:'none',color:'#00000000',opacity:1,gradient:{colors:[],angle:0},paddingX:0,paddingY:0,radius:0,border:{color:'#00000000',width:0},shadow:{color:'#00000055',offsetX:0,offsetY:2,blur:8},texture:{type:'none',opacity:0,scale:1,seed:0},transform:{rotation:0,scale:1,offsetX:0,offsetY:0}};
  const fillStyle: React.CSSProperties = recipe.fill.type === 'solid'
    ? {color: recipe.fill.color}
    : {
      backgroundImage: gradient(recipe), backgroundClip: 'text', WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent', color: 'transparent', backgroundRepeat: 'no-repeat',
    };
  const px = (recipe.layout.positionX ?? (recipe.layout.playResX ?? 1920)/2) / (recipe.layout.playResX ?? 1920) * 100;
  const py = (recipe.layout.positionY ?? ((recipe.layout.playResY ?? 1080)-(recipe.layout.marginV ?? 64))) / (recipe.layout.playResY ?? 1080) * 100;
  const anchorX = (recipe.layout.anchorX ?? .5) * 100;
  const anchorY = (recipe.layout.anchorY ?? 1) * 100;
  const collapse = exitType === 'collapse' ? 1-exitProgress*.85 : 1;
  const exitScale = exitActive ? 1-exitProgress*.12 : 1;
  const scaleX = (recipe.layout.scaleX ?? 1) * motionScale * holdScale * collapse * exitScale;
  const scaleY = (recipe.layout.scaleY ?? 1) * motionScale * holdScale * (punch && entryProgress < .45 ? .92 : 1) * collapse * exitScale;
  const entryRotate = ['rotate','flip'].includes(entranceType) ? (1-entryProgress) * numberValue(entrance.rotation, -8) : 0;
  const maskProgress = entranceActive && (entranceType === 'wipe' || entranceType === 'mask_reveal') ? entryProgress : 1;
  const closeProgress = exitActive && (exitType === 'wipe' || exitType === 'mask_close') ? exitProgress : 0;
  const clipProgress = Math.max(0, Math.min(1, maskProgress * (1-closeProgress)));
  const base: React.CSSProperties = {
    position:'absolute', left:`${px}%`, top:`${py}%`,
    translate:`calc(-${anchorX}% + ${jitter + entryX + holdX + exitX}px) calc(-${anchorY}% + ${rise}px)`,
    scale:`${scaleX} ${scaleY}`,
    rotate:`${(recipe.layout.rotation ?? 0) + entryRotate}deg`,
    transformOrigin:`${anchorX}% ${anchorY}%`,
    whiteSpace: 'pre-wrap', wordBreak: 'normal', overflowWrap: 'anywhere', textAlign: 'center', fontFamily: recipe.typography.fontFamily,
    fontSize: recipe.typography.fontSize, fontWeight: recipe.typography.fontWeight ?? (recipe.typography.bold ? 700 : 400),
    fontStyle: recipe.typography.italic ? 'italic' : 'normal', letterSpacing: recipe.typography.spacing,
    lineHeight: (recipe.layout as Record<string, unknown>).lineHeightPx ? `${(recipe.layout as Record<string, unknown>).lineHeightPx}px` : numberValue((recipe.layout as Record<string, unknown>).lineGap, 1.12), opacity,
    maxWidth: ((recipe.layout as Record<string, unknown>).maxWidthPx as number) ?? `${numberValue((recipe.layout as Record<string, unknown>).maxWidth, 94)}vw`,
    clipPath: clipProgress < .999 ? `inset(0 ${(1-clipProgress)*100}% 0 0)` : undefined,
    filter: `${recipe.glow.blur > 0 ? `drop-shadow(0 0 ${recipe.glow.blur*glowSettle}px ${recipe.glow.color})` : ''}${exitType === 'blur_out' ? ` blur(${exitProgress*12}px)` : ''}`.trim() || undefined,
  };
  const visibleText = entranceActive && entranceType === 'type_on' ? text.slice(0, Math.ceil(text.length * entryProgress)) : text;
  const perLetter = (entranceActive && entranceType === 'letter_stagger') || (holdActive && holdType === 'per_letter_bounce');
  const textContent = perLetter
    ? Array.from(visibleText).map((character, index) => <span key={`${character}-${index}`} style={{display:'inline-block',opacity:Math.max(0,Math.min(1,entryProgress*text.length-index)),translate:`0 ${holdType === 'per_letter_bounce' ? Math.sin(frame*.28+index*.7)*3 : (1-entryProgress)*12}px`}}>{character}</span>)
    : visibleText;
  const panelGradient = panel.gradient.colors.length >= 2
    ? `linear-gradient(${panel.gradient.angle}deg,${panel.gradient.colors.join(',')})`
    : panel.color;
  const texture = textureImage(panel.texture.type, panel.texture.scale, panel.texture.seed);
  return <div style={base}>
    {panel.enabled && <div style={{
      position:'absolute',
      left:`-${panel.paddingX}px`, right:`-${panel.paddingX}px`,
      top:`-${panel.paddingY}px`, bottom:`-${panel.paddingY}px`,
      background:panelGradient, borderRadius:panel.type === 'pixel_panel' ? 0 : panel.radius,
      opacity:panel.opacity,
      border:`${panel.border.width}px solid ${panel.border.color}`,
      boxShadow:`${panel.shadow.offsetX}px ${panel.shadow.offsetY}px ${panel.shadow.blur}px ${panel.shadow.color}${panel.type === 'neon_frame' ? ',0 0 16px currentColor' : ''}`,
      translate:`${panel.transform.offsetX}px ${panel.transform.offsetY}px`,
      scale:panel.transform.scale,
      rotate:`${panel.transform.rotation}deg`,
      clipPath:panel.type === 'speech_bubble' ? 'polygon(0 0,100% 0,100% 82%,58% 82%,50% 100%,45% 82%,0 82%)' : panel.type === 'glitch_terminal' ? 'polygon(2% 0,98% 0,100% 18%,97% 100%,3% 100%,0 80%)' : undefined,
      overflow:'hidden',
    }}><div style={{position:'absolute',inset:0,backgroundImage:texture,backgroundSize:panel.texture.type === 'halftone' || panel.texture.type === 'pixel_grid' ? `${Math.max(3,6*panel.texture.scale)}px ${Math.max(3,6*panel.texture.scale)}px` : undefined,opacity:panel.texture.opacity}}/></div>} 
    {recipe.decorations.filter((item) => KNOWN_DECORATIONS.has(item)).map((item, index) =>
      item === 'scanline' ? <div key={`${item}-${index}`} style={{position:'absolute',left:'-28px',right:'-28px',height:'3px',top:motionEnabled ? `${(frame*numberValue(hold.scan_speed,1.7))%110-5}%` : '50%',pointerEvents:'none',opacity:.32,background:'linear-gradient(90deg,transparent,#20d6e8,transparent)',boxShadow:'0 0 8px #20d6e8'}}/> :
      <div key={`${item}-${index}`} style={{position:'absolute',inset:'-10px -28px',opacity:Math.min(1,entryProgress*1.8),borderTop:'2px solid #20d6e8',borderBottom:'2px solid #ff4db8',clipPath:`inset(0 ${Math.max(0,(1-entryProgress)*50)}% 0 ${Math.max(0,(1-entryProgress)*50)}%)`}}/>
    )}
    {shadow.enabled && shadow.opacity > 0 && <span data-layer="shadow" style={{
      position:'absolute', inset:0, zIndex:1, pointerEvents:'none',
      color:shadow.color, WebkitTextFillColor:shadow.color,
      WebkitTextStroke:shadow.spread > 0 ? `${shadow.spread}px ${shadow.color}` : '0 transparent',
      opacity:shadow.opacity, translate:`${shadow.offsetX}px ${shadow.offsetY}px`,
      filter:shadow.blur > 0 ? `blur(${shadow.blur}px)` : undefined,
    }}>{textContent}</span>}
    {[...recipe.strokes].reverse().map((stroke, index) => <OutsideStrokeText key={`stroke-${index}`} radius={stroke.width} color={cssColor(stroke.color)} style={{position:'absolute',inset:0,zIndex:2}}>{textContent}</OutsideStrokeText>)}
    <span data-layer="fill" style={{...fillStyle,position:'relative',zIndex:3,display:'inline-block',backgroundSize:'100% 100%',WebkitTextStroke:'0 transparent'}}>{textContent}</span>
    {activeGlitch && <>
      {Array.from({length:sliceCount}).map((_,index) => <span key={`slice-${index}`} style={{...fillStyle,position:'absolute',inset:0,opacity:.54,transform:`translateX(${Math.sin(index*7+frame)*chromaticOffset*(1-entryProgress)}px)`,clipPath:`inset(${index/sliceCount*100}% 0 ${100-(index+1)/sliceCount*100}% 0)`,WebkitTextStroke:`1px ${index%2?'#ff4db8':'#20d6e8'}`}}>{text}</span>)}
    </>}
  </div>;
};
