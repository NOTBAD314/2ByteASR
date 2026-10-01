import React from 'react';
import {useVideoConfig} from 'remotion';
import type {Recipe} from '../SubtitleComposition';
import {OutsideStrokeText} from './OutsideStrokeText';

type Keyframe = {timeMs:number; value:number; easing:string};
type MotionTrack = {target:string; property:string; keyframes:Keyframe[]; postBehavior?:'HOLD'|'RESET'};
type GraphLayer = {id:string; primitive:string; params:Record<string, unknown>; seed?:number};
type VisualGraph = {
  schema:string; version:number; name:string; seed:number;
  textLayer:{id:string; font:Record<string, unknown>; fill:Record<string, unknown>; strokes:Array<Record<string, unknown>>; shadow:Record<string, unknown>; glow:Record<string, unknown>; letterSpacing:number; lineSpacing:number; alignment:number};
  panelLayer:GraphLayer; decorationLayers:GraphLayer[]; effectLayers:GraphLayer[];
  motionGraph:{durationMs:number; staggerMs:number; tracks:MotionTrack[]};
};

const numberValue = (value:unknown, fallback:number):number => typeof value === 'number' ? value : fallback;
const stringValue = (value:unknown, fallback:string):string => typeof value === 'string' ? value : fallback;
const cssColor = (value:unknown, fallback='#ffffffff'):string => {
  const text = stringValue(value, fallback);
  if (/^#[0-9a-f]{8}$/i.test(text)) return `#${text.slice(3)}${text.slice(1,3)}`;
  return text;
};
const ease = (value:number, easing:string):number => {
  const p = Math.max(0, Math.min(1, value));
  if (easing === 'step') return p < 1 ? 0 : 1;
  if (easing === 'ease-in') return p*p;
  if (easing === 'ease-out') return 1-(1-p)*(1-p);
  if (easing === 'ease-in-out') return p < .5 ? 2*p*p : 1-Math.pow(-2*p+2,2)/2;
  if (easing === 'overshoot') return 1+2.70158*Math.pow(p-1,3)+1.70158*Math.pow(p-1,2);
  if (easing === 'ease-out-expo') return p >= 1 ? 1 : 1-Math.pow(2,-10*p);
  if (easing === 'ease-out-back' || easing === 'impact') return 1+2.70158*Math.pow(p-1,3)+1.70158*Math.pow(p-1,2);
  if (easing === 'spring' || easing === 'damped-spring') return 1-Math.exp(-6*p)*Math.cos(12*p);
  if (easing === 'ease-in-out-cubic') return p < .5 ? 4*p*p*p : 1-Math.pow(-2*p+2,3)/2;
  if (easing === 'glitch') return p < 1 ? 0 : 1;
  return p;
};
const propertyDefault = (property:string):number => ['scale','scale_x','scale_y','opacity','ray_scale','burst_scale','char_reveal','mask_reveal'].includes(property) ? 1 : 0;
const sampleTrack = (track:MotionTrack, now:number):number | null => {
  const frames = track.keyframes ?? [];
  const fallback = propertyDefault(track.property);
  if (!frames.length) return fallback;
  // Before this track's window another track sharing the same
  // (target, property) - an entrance/exit split - may already own the value.
  if (now < frames[0].timeMs) return null;
  if (now === frames[0].timeMs) return frames[0].value;
  if (now > frames[frames.length-1].timeMs) return track.postBehavior === 'RESET' ? fallback : frames[frames.length-1].value;
  if (now === frames[frames.length-1].timeMs) return frames[frames.length-1].value;
  const rightIndex = frames.findIndex((item) => now <= item.timeMs);
  const left = frames[Math.max(0,rightIndex-1)];
  const right = frames[rightIndex];
  const progress = ease((now-left.timeMs)/Math.max(1,right.timeMs-left.timeMs), right.easing);
  return left.value+(right.value-left.value)*progress;
};
const sampleGraph = (graph:VisualGraph, now:number):Record<string,Record<string,number>> => {
  const values:Record<string,Record<string,number>> = {group:{x:0,y:0,scale:1,rotation:0,opacity:1}};
  for (const track of graph.motionGraph.tracks ?? []) {
    const sampled = sampleTrack(track, now);
    if (sampled === null) continue;
    values[track.target] ??= {};
    const existing = values[track.target][track.property];
    // Overlapping entrance/hold and exit tracks combine by whichever is
    // more transparent.
    values[track.target][track.property] =
      existing !== undefined && track.property === 'opacity'
        ? Math.min(existing, sampled)
        : sampled;
  }
  for (const effect of graph.effectLayers ?? []) {
    values[effect.id] ??= {};
    if (effect.primitive === 'RGB_SPLIT') {
      const amount = numberValue(effect.params.rgbOffset,4)*numberValue(effect.params.strength,1);
      values[effect.id].rgb_offset ??= amount;
    }
    if (effect.primitive === 'IMPACT') {
      const duration = Math.max(1,numberValue(effect.params.durationMs,280));
      const decay = Math.max(0,1-now/duration);
      const shake = numberValue(effect.params.shakePx,3)*decay;
      values[effect.id].shake_x = Math.sin((now+(effect.seed ?? 0))*.21)*shake;
      values[effect.id].shake_y = Math.cos((now+(effect.seed ?? 0))*.27)*shake;
    }
    if (effect.primitive === 'GLITCH') {
      const phase = (now+(effect.seed ?? 0)*17)%1700;
      const active = phase < 150 || now < 320;
      values[effect.id].rgb_offset ??= active ? numberValue(effect.params.rgbOffset,6)*Math.abs(Math.sin((now+(effect.seed ?? 0))*.071)) : 0;
      values[effect.id].slice_offset ??= active ? numberValue(effect.params.sliceDisplacement,10)*Math.sin((now+(effect.seed ?? 0))*.071) : 0;
      values[effect.id].flicker = active ? numberValue(effect.params.flicker,.14)*Math.abs(Math.sin(now*.113)) : 0;
    }
  }
  return values;
};
const layerTransform = (values:Record<string,number>|undefined):string => {
  const item = values ?? {};
  const scale = item.scale ?? item.burst_scale ?? item.ray_scale ?? 1;
  return `translate(${item.x ?? 0}px,${item.y ?? 0}px) rotate(${item.rotation ?? 0}deg) scale(${item.scale_x ?? scale},${item.scale_y ?? scale})`;
};
const layerFilter = (values:Record<string,number>|undefined):string|undefined => {
  const blur = values?.blur ?? 0;
  return blur > .4 ? `blur(${blur}px)` : undefined;
};
const layerClip = (values:Record<string,number>|undefined):React.CSSProperties|undefined => {
  const reveal = Math.max(0,Math.min(1,values?.mask_reveal ?? 1));
  return reveal < .999 ? {clipPath:`inset(0 ${((1-reveal)*100).toFixed(2)}% 0 0)`} : undefined;
};
const burstClip = 'polygon(50% 0%,58% 22%,76% 5%,73% 29%,98% 24%,78% 43%,100% 54%,76% 58%,91% 82%,65% 70%,60% 100%,48% 76%,31% 98%,34% 70%,7% 82%,23% 58%,0% 47%,25% 42%,5% 20%,31% 29%)';
const glyphAngles = (count:number, seed:number):number[] => Array.from({length:count},(_,i)=>((seed+i*2.399)%(2*Math.PI)));

const Decoration:React.FC<{layer:GraphLayer; values?:Record<string,number>; scale:number}> = ({layer,values,scale}) => {
  const color = cssColor(layer.params.color,'#ffffff88');
  const common:React.CSSProperties = {position:'absolute',inset:`${-60*scale}px`,pointerEvents:'none',opacity:values?.opacity ?? 1,transform:layerTransform(values),filter:layerFilter(values),...layerClip(values)};
  if (layer.primitive === 'IMPACT_RAYS') return <div data-vdg-layer={layer.id} style={{...common,borderRadius:'50%',background:`repeating-conic-gradient(from 0deg,${color} 0deg 4deg,transparent 4deg 16deg)`,maskImage:'radial-gradient(circle,transparent 0 26%,#000 27% 70%,transparent 71%)'}}/>;
  if (layer.primitive === 'HALFTONE') return <div data-vdg-layer={layer.id} style={{...common,inset:`${-20*scale}px`,backgroundImage:`radial-gradient(circle,${color} ${Math.max(1,numberValue(layer.params.radius,2.2)*scale)}px,transparent ${Math.max(1.5,numberValue(layer.params.radius,2.2)*scale+1)}px)`,backgroundSize:`${Math.max(5,numberValue(layer.params.spacing,10)*scale)}px ${Math.max(5,numberValue(layer.params.spacing,10)*scale)}px`}}/>;
  if (layer.primitive === 'SCANLINES') return <div data-vdg-layer={layer.id} style={{...common,inset:`${-20*scale}px`,background:`repeating-linear-gradient(0deg,${color} 0 1px,transparent 1px ${Math.max(3,numberValue(layer.params.spacing,5)*scale)}px)`}}/>;
  if (layer.primitive === 'SPEED_LINES') return <>{Array.from({length:Math.min(16,Math.max(3,numberValue(layer.params.count,8)))}).map((_,index)=><i key={index} data-vdg-layer={layer.id} style={{position:'absolute',width:`${(24+index%4*12)*scale}px`,height:`${2*scale}px`,right:`${(index%3)*16*scale}px`,top:`${8+index*8}%`,background:color,opacity:.75,transform:layerTransform(values)}}/>)}</>;
  if (layer.primitive === 'SHARDS') return <>{Array.from({length:Math.min(12,Math.max(3,numberValue(layer.params.count,6)))}).map((_,index)=><i key={index} data-vdg-layer={layer.id} style={{position:'absolute',width:`${(5+index%3*3)*scale}px`,height:`${(10+index%4*4)*scale}px`,left:`${8+(index*17)%92}%`,top:`${5+(index*29)%88}%`,background:color,opacity:.72,clipPath:'polygon(50% 0,100% 100%,0 72%)',transform:`rotate(${index*37}deg) ${layerTransform(values)}`}}/>)}</>;
  if (layer.primitive === 'ACCENT_BARS') return <>{Array.from({length:Math.min(8,Math.max(2,numberValue(layer.params.count,3)))}).map((_,index)=><i key={index} data-vdg-layer={layer.id} style={{position:'absolute',width:`${6*scale}px`,height:`${(18+index*8)*scale}px`,left:`${(-20-index*9)*scale}px`,bottom:0,background:color,transform:`skew(-12deg) ${layerTransform(values)}`}}/>)}</>;
  if (layer.primitive === 'PIXEL_TILES') {const size=Math.max(2,numberValue(layer.params.size,4)*scale);const spacing=Math.max(size*1.6,numberValue(layer.params.spacing,16)*scale);const seed=layer.seed ?? 0;const cells:number[] = [];const rows=Math.ceil(140*scale/spacing),cols=Math.ceil(320*scale/spacing);for(let row=0;row<rows;row++)for(let col=0;col<cols;col++){if((row*7+col*13+seed)%5!==0)cells.push(row*cols+col);}return <div data-vdg-layer={layer.id} style={{...common,inset:0,position:'relative'}}>{cells.map((cell)=><i key={cell} style={{position:'absolute',width:size,height:size,left:`${(cell%cols)*spacing}px`,top:`${Math.floor(cell/cols)*spacing}px`,background:color}}/>)}</div>;}
  if (layer.primitive === 'CROSSHAIR') {const reach=Math.max(4,numberValue(layer.params.reach,22)*scale);const gap=Math.max(3,numberValue(layer.params.gap,10)*scale);return <>{[[0,0,1,1],[1,0,-1,1],[0,1,1,-1],[1,1,-1,-1]].map(([cx,cy,sx,sy],index)=><i key={index} data-vdg-layer={layer.id} style={{position:'absolute',left:`calc(${cx*100}% + ${sx*gap}px)`,top:`calc(${cy*100}% + ${sy*gap}px)`,width:reach,height:reach,borderLeft:`${Math.max(1,1.5*scale)}px solid ${color}`,borderTop:`${Math.max(1,1.5*scale)}px solid ${color}`,transform:`scaleX(${sx}) scaleY(${sy}) ${layerTransform(values)}`}}/>)}</>;}
  if (layer.primitive === 'INK_SPLAT') {const count=Math.min(12,Math.max(3,numberValue(layer.params.count,6)));const seed=layer.seed ?? 0;return <>{Array.from({length:count}).map((_,index)=>{const angle=(index+.5)*2*Math.PI/count+Math.sin((seed+index)*3.7)*.4;const distance=(0.55+0.35*Math.abs(Math.sin((seed+index)*2.1)))*120*scale;const size=(3+Math.abs(Math.sin((seed+index)*5.3))*7)*scale;return <i key={index} data-vdg-layer={layer.id} style={{position:'absolute',left:`calc(50% + ${Math.cos(angle)*distance}px)`,top:`calc(50% + ${Math.sin(angle)*distance*.8}px)`,width:size,height:size*.8,borderRadius:'50%',background:color,transform:layerTransform(values)}}/>;})}</>;}
  if (layer.primitive === 'FLOAT_GLYPHS') {const count=Math.min(10,Math.max(2,numberValue(layer.params.count,5)));const seed=layer.seed ?? 0;const symbols=stringValue(layer.params.symbols,'✦★●');return <>{glyphAngles(count,seed).map((angle,index)=>{const distance=150*scale*(0.52+0.12*Math.sin((seed+index)*1.3));const glyph=symbols[index%symbols.length] ?? '✦';const size=Math.max(8,numberValue(layer.params.size,14)*scale*(0.7+0.3*((seed+index)%3)/2));return <span key={index} data-vdg-layer={layer.id} style={{position:'absolute',left:`calc(50% + ${Math.cos(angle)*distance}px)`,top:`calc(50% + ${Math.sin(angle)*distance*.7}px)`,color,fontSize:size,lineHeight:1,transform:layerTransform(values)}}>{glyph}</span>;})}</>;}
  if (layer.primitive === 'SCAN_SWEEP') {const width=Math.max(6,numberValue(layer.params.width,26)*scale);return <div data-vdg-layer={layer.id} style={{...common,inset:0,left:'50%',width:`${width}px`,marginLeft:`${-width/2}px`,background:`linear-gradient(90deg,transparent,${color},transparent)`,transform:layerTransform(values)}}/>;}
  if (layer.primitive === 'PARTICLES') {const count=Math.min(20,Math.max(4,numberValue(layer.params.count,9)));const seed=layer.seed ?? 0;return <>{Array.from({length:count}).map((_,index)=>{const rx=((seed*13+index*37)%97)/97;const ry=((seed*29+index*61)%89)/89;const size=(1.4+Math.abs(Math.sin((seed+index)*3.3))*2.6)*scale;return <i key={index} data-vdg-layer={layer.id} style={{position:'absolute',left:`${rx*100}%`,top:`${ry*100}%`,width:size,height:size,borderRadius:'50%',background:color,transform:layerTransform(values)}}/>;})}</>;}
  if (layer.primitive === 'ARROWS') {const count=Math.min(6,Math.max(2,numberValue(layer.params.count,3)));const size=Math.max(8,numberValue(layer.params.size,18)*scale);const fromLeft=stringValue(layer.params.side,'left').toLowerCase()!=='right';const stroke=Math.max(1.2,numberValue(layer.params.width,3)*scale);const seed=layer.seed ?? 0;return <>{Array.from({length:count}).map((_,index)=>{const offset=size*(0.8+index*0.9);const y=`calc(50% + ${Math.sin((seed+index)*2.7)*22*scale}px)`;return <span key={index} data-vdg-layer={layer.id} style={{position:'absolute',[fromLeft?'right':'left']:`calc(100% + ${offset}px)`,top:y,width:size,height:size,borderLeft:`${stroke}px solid ${color}`,borderBottom:`${stroke}px solid ${color}`,transform:`rotate(${fromLeft?45:-135}deg) ${layerTransform(values)}`}}/>;})}</>;}
  if (layer.primitive === 'DATA_BARS') {const count=Math.min(9,Math.max(3,numberValue(layer.params.count,5)));const barWidth=Math.max(2,numberValue(layer.params.barWidth,4)*scale);const seed=layer.seed ?? 0;return <>{Array.from({length:count}).map((_,index)=>{const height=(12+Math.abs(Math.sin((seed+index)*2.9))*30)*scale;return <i key={index} data-vdg-layer={layer.id} style={{position:'absolute',right:`${(count-index)*barWidth*1.6}px`,bottom:0,width:barWidth,height:height,background:color,transform:layerTransform(values)}}/>;})}</>;}
  if (layer.primitive === 'GEARS') {const ring=Math.max(30,numberValue(layer.params.size,120)*scale);const stroke=Math.max(1.2,numberValue(layer.params.width,3)*scale);return <div data-vdg-layer={layer.id} style={{...common,inset:0,background:`repeating-conic-gradient(from 0deg,${color} 0deg 5deg,transparent 5deg 18deg)`,maskImage:`radial-gradient(circle,transparent 0 ${(ring*.42)|0}px,#000 ${(ring*.44)|0}px ${(ring*.6)|0}px,transparent ${(ring*.62)|0}px)`,border:`${stroke}px solid ${color}`,borderRadius:'50%'}}/>;}
  if (layer.primitive === 'RIVETS') {const size=Math.max(3,numberValue(layer.params.size,5)*scale);const count=Math.min(16,Math.max(4,numberValue(layer.params.count,6)));const spacing=Math.max(size*3,(100/(count/2+1)));return <div data-vdg-layer={layer.id} style={{...common,inset:0,backgroundImage:`radial-gradient(circle,${color} ${size*.5}px,transparent ${size*.6}px)`,backgroundSize:`${spacing}% ${size*4}px`,backgroundPosition:'top left,0 100%',maskImage:'linear-gradient(#000 0 0),linear-gradient(#000 0 0)',maskPosition:'top center,bottom center',maskSize:'100% 6px,100% 6px',maskRepeat:'no-repeat'}}/>;}
  if (layer.primitive === 'GAUGE') {const dial=Math.max(16,numberValue(layer.params.size,64)*scale);const needle=cssColor(layer.params.needleColor,'#fff3d6ff');return <><div data-vdg-layer={layer.id} style={{...common,inset:0,margin:'auto',width:dial*2,height:dial*2,border:`${Math.max(1.4,dial*.05)}px solid ${color}`,borderRadius:'50%',borderStyle:'dashed',opacity:(values?.opacity ?? 1)*.9}}/><i data-vdg-layer={layer.id} style={{position:'absolute',left:'50%',top:'50%',width:dial*.8,height:Math.max(1.6,dial*.06),background:needle,transformOrigin:'left center',transform:`rotate(${(values?.rotation ?? -38)+225}deg) ${layerTransform(values)}`,opacity:values?.opacity ?? 1}}/></>;}
  if (layer.primitive === 'PIPES') {const count=Math.min(3,Math.max(1,numberValue(layer.params.count,2)));const thickness=Math.max(2.5,numberValue(layer.params.thickness,6)*scale);const flange=cssColor(layer.params.flangeColor ?? layer.params.color,'#c9971fff');return <>{Array.from({length:count}).map((_,index)=>{const offset=(thickness*(0.8+index*1.3))|0;return <span key={index} data-vdg-layer={layer.id} style={{position:'absolute',left:`${-thickness*2}px`,right:`${-thickness*2}px`,top:`${-offset-thickness}px`,height:thickness,background:`linear-gradient(90deg,${color},${flange} 50%,${color})`,transform:layerTransform(values),opacity:values?.opacity ?? 1}}/>;})}</>;}
  if (layer.primitive === 'STEAM') {const count=Math.min(9,Math.max(3,numberValue(layer.params.count,5)));const puff=Math.max(10,numberValue(layer.params.size,26)*scale);const seed=layer.seed ?? 0;return <>{Array.from({length:count}).map((_,index)=>{const rx=((seed*17+index*31)%89)/89;const radius=puff*(.7+.5*Math.abs(Math.sin((seed+index)*2.3)));return <i key={index} data-vdg-layer={layer.id} style={{position:'absolute',left:`${rx*100}%`,bottom:`${Math.abs(Math.sin((seed+index)*1.7))*40}%`,width:radius*2,height:radius*2,borderRadius:'50%',background:`radial-gradient(circle,${color},transparent 70%)`,transform:layerTransform(values),opacity:values?.opacity ?? 1}}/>;})}</>;}
  return null;
};

export const VisualDesignGraphSubtitle:React.FC<{text:string; recipe:Recipe; graph:VisualGraph; frame:number; fps:number}> = ({text,recipe,graph,frame,fps}) => {
  const {width} = useVideoConfig();
  const scale = width/Math.max(1,recipe.layout.playResX ?? 1920);
  const now = Math.min(graph.motionGraph.durationMs,Math.max(0,frame/fps*1000));
  const values = sampleGraph(graph,now);
  const group = values.group ?? {};
  const impact = graph.effectLayers.find((item)=>item.primitive === 'IMPACT');
  const impactValues = impact ? values[impact.id] ?? {} : {};
  const glitch = graph.effectLayers.find((item)=>item.primitive === 'GLITCH');
  const glitchValues = glitch ? values[glitch.id] ?? {} : {};
  const px = (recipe.layout.positionX ?? (recipe.layout.playResX ?? 1920)/2)/(recipe.layout.playResX ?? 1920)*100;
  const py = (recipe.layout.positionY ?? (recipe.layout.playResY ?? 1080)*.82)/(recipe.layout.playResY ?? 1080)*100;
  const anchorX = (recipe.layout.anchorX ?? .5)*100;
  const anchorY = (recipe.layout.anchorY ?? 1)*100;
  const textLayer = graph.textLayer;
  const textValues = values[textLayer.id] ?? {};
  const fill = textLayer.fill ?? {};
  const shadow = textLayer.shadow ?? {};
  const stops = Array.isArray(fill.stops) ? fill.stops as Array<Record<string,unknown>> : [];
  const fillStyle:React.CSSProperties = stringValue(fill.type,'solid') === 'solid'
    ? {color:cssColor(fill.color,'#ffffffff')}
    : {color:'transparent',WebkitTextFillColor:'transparent',backgroundClip:'text',WebkitBackgroundClip:'text',backgroundImage:`linear-gradient(${90-numberValue(fill.angle,0)}deg,${stops.map((item)=>`${cssColor(item.color)} ${numberValue(item.position,0)*100}%`).join(',')})`};
  const panel = graph.panelLayer;
  const panelValues = values[panel.id] ?? {};
  const panelColor = cssColor(panel.params.color,'#000000aa');
  const panelGradient = typeof panel.params.gradient === 'object' && panel.params.gradient !== null
    ? panel.params.gradient as Record<string,unknown> : null;
  const panelStops = panelGradient && Array.isArray(panelGradient.stops)
    ? panelGradient.stops as Array<Record<string,unknown>> : [];
  const panelBackground = panelStops.length >= 2
    ? `linear-gradient(${numberValue(panelGradient?.angle,90)}deg,${panelStops.map((item)=>`${cssColor(item.color)} ${numberValue(item.position,0)*100}%`).join(',')})`
    : panelColor;
  const panelClip = panel.primitive === 'COMIC_BURST' ? burstClip
    : panel.primitive === 'RIBBON' ? 'polygon(4% 0,96% 0,100% 50%,96% 100%,4% 100%,0 50%)'
    : panel.primitive === 'CUT_CORNER' ? 'polygon(7% 0,100% 0,93% 100%,0 100%)'
    : panel.primitive === 'ANGLED_PLATE' ? 'polygon(13% 0,100% 0,92% 100%,0 100%)'
    : panel.primitive === 'COMIC_BUBBLE' ? 'polygon(0 0,100% 0,100% 82%,60% 82%,50% 100%,44% 82%,0 82%)'
    : panel.primitive === 'UNDERLINE_SLAB' ? 'polygon(4% 78%,96% 78%,100% 100%,0 100%)'
    : panel.primitive === 'MARKER' ? 'polygon(2% 12%,98% 0,100% 88%,0 100%)'
    : panel.primitive === 'TAPE' ? 'polygon(0 0,100% 3%,100% 26%,0 23%)'
    : panel.primitive === 'TORN_PAPER' ? 'polygon(0 4%,7% 0,14% 5%,23% 1%,34% 6%,45% 0,57% 5%,68% 1%,79% 6%,89% 0,95% 4%,100% 1%,100% 96%,93% 100%,85% 95%,74% 99%,63% 95%,52% 100%,41% 95%,30% 99%,19% 95%,9% 100%,3% 96%)'
    : panel.primitive === 'MECHANICAL_PLATE' ? 'polygon(1.5% 0,98.5% 0,100% 1.5%,100% 98.5%,98.5% 100%,1.5% 100%,0 98.5%,0 1.5%)'
    : panel.primitive === 'STICKER' ? 'polygon(0 3%,92% 0,88% 8%,100% 12%,100% 97%,3% 100%,0 97%)'
    : panel.primitive === 'LOWER_THIRD' ? 'polygon(3% 0,100% 0,96% 100%,0 100%)'
    : undefined;
  const framePanel = panel.primitive === 'BRACKET_FRAME' || panel.primitive === 'TECH_FRAME' || panel.primitive === 'PIXEL_FRAME';
  const glassPanel = panel.primitive === 'GLASS_PANEL';
  const panelOpacity = glassPanel ? Math.min(.85,Math.max(.25,numberValue(panel.params.opacity,.5))) : panelValues.opacity ?? 1;
  const frameColor = cssColor(panel.params.outlineColor ?? panel.params.borderColor ?? panel.params.color,'#ff111111');
  const frameStroke = Math.max(.5,numberValue(panel.params.outlineWidth,2)*scale);
  const frameCorner = 24*scale;
  const frameCorners = `linear-gradient(${frameColor},${frameColor}) left top/${frameCorner}px ${frameStroke}px no-repeat,linear-gradient(${frameColor},${frameColor}) left top/${frameStroke}px ${frameCorner}px no-repeat,linear-gradient(${frameColor},${frameColor}) right top/${frameCorner}px ${frameStroke}px no-repeat,linear-gradient(${frameColor},${frameColor}) right top/${frameStroke}px ${frameCorner}px no-repeat,linear-gradient(${frameColor},${frameColor}) left bottom/${frameCorner}px ${frameStroke}px no-repeat,linear-gradient(${frameColor},${frameColor}) left bottom/${frameStroke}px ${frameCorner}px no-repeat,linear-gradient(${frameColor},${frameColor}) right bottom/${frameCorner}px ${frameStroke}px no-repeat,linear-gradient(${frameColor},${frameColor}) right bottom/${frameStroke}px ${frameCorner}px no-repeat`;
  const techTicks = `,linear-gradient(${frameColor},${frameColor}) 36% top/${12*scale}px ${frameStroke}px no-repeat,linear-gradient(${frameColor},${frameColor}) 64% bottom/${12*scale}px ${frameStroke}px no-repeat`;
  const frameBackground = framePanel
    ? `${frameCorners}${panel.primitive === 'TECH_FRAME' ? techTicks : ''}`
    : panelBackground;
  const panelStyle:React.CSSProperties = {
    position:'absolute',left:`${-numberValue(panel.params.paddingX,28)*scale}px`,right:`${-numberValue(panel.params.paddingX,28)*scale}px`,top:`${-numberValue(panel.params.paddingY,14)*scale}px`,bottom:`${-numberValue(panel.params.paddingY,14)*scale}px`,
    background:frameBackground,border:framePanel ? undefined : `${numberValue(panel.params.outlineWidth,glassPanel?1:0)*scale}px solid ${cssColor(panel.params.outlineColor ?? panel.params.rimColor ?? (glassPanel?'#66ffffff':'#00000000'))}`,
    borderRadius:panel.primitive === 'RIBBON' || panel.primitive === 'PILL' ? `${9999}px` : `${numberValue(panel.params.radius,6)*scale}px`,
    clipPath:panelClip,
    transform:layerTransform(panelValues),opacity:panelOpacity,filter:layerFilter(panelValues),...layerClip(panelValues),
  };
  const groupTransform = `translate(calc(-${anchorX}% + ${(group.x ?? 0)+(impactValues.shake_x ?? 0)}px),calc(-${anchorY}% + ${(group.y ?? 0)+(impactValues.shake_y ?? 0)}px)) rotate(${(recipe.layout.rotation ?? 0)+(group.rotation ?? 0)}deg) scale(${(recipe.layout.scaleX ?? 1)*(group.scale_x ?? group.scale ?? 1)},${(recipe.layout.scaleY ?? 1)*(group.scale_y ?? group.scale ?? 1)})`;
  const rgbOffset = glitchValues.rgb_offset ?? 0;
  const sliceOffset = glitchValues.slice_offset ?? 0;
  const tracking = (textValues.tracking ?? 0)*scale;
  const charReveal = Math.max(0,Math.min(1,textValues.char_reveal ?? 1));
  const splitAlpha = glitch && glitch.primitive === 'RGB_SPLIT' ? .34 : .48;
  const textStyle:React.CSSProperties = {position:'absolute',left:`${px}%`,top:`${py}%`,transform:groupTransform,transformOrigin:`${anchorX}% ${anchorY}%`,opacity:Math.max(0,Math.min(1,(group.opacity ?? 1)*(1-(glitchValues.flicker ?? 0)))) ,whiteSpace:'pre-wrap',wordBreak:'normal',overflowWrap:'anywhere',width:'max-content',maxWidth:((recipe.layout as Record<string, unknown>).maxWidthPx as number ?? 1804.8)*scale,textAlign:'center',fontFamily:stringValue(textLayer.font.family,recipe.typography.fontFamily),fontSize:numberValue(textLayer.font.size,recipe.typography.fontSize)*scale,fontWeight:numberValue(textLayer.font.weight,recipe.typography.bold?800:500),letterSpacing:numberValue(textLayer.letterSpacing,recipe.typography.spacing)*scale,lineHeight:(recipe.layout as Record<string, unknown>).lineHeightPx ? `${Number((recipe.layout as Record<string, unknown>).lineHeightPx)*scale}px` : numberValue(textLayer.lineSpacing,1.08)};
  void tracking;
  const revealClip = charReveal < .999 ? {clipPath:`inset(0 ${((1-charReveal)*100).toFixed(2)}% 0 0)`} : undefined;
  const textReveal = {...revealClip, ...layerClip(textValues)};
  const textFilter = layerFilter(textValues);
  const shadowBlur = numberValue(shadow.blur_radius,numberValue(shadow.blur,0));
  const shadowFilter = [textFilter, shadowBlur > 0 ? `blur(${shadowBlur*scale}px)` : undefined].filter(Boolean).join(' ') || undefined;
  return <div data-vdg={graph.name} style={textStyle}>
    {panel.primitive !== 'NONE' && <div data-vdg-layer={panel.id} style={panelStyle}/>}
    {graph.decorationLayers.map((layer)=><Decoration key={layer.id} layer={layer} values={values[layer.id]} scale={scale}/>)}
    {Math.abs(rgbOffset)+Math.abs(sliceOffset) > .05 && <><span style={{...fillStyle,position:'absolute',inset:0,color:'#ff365f',WebkitTextFillColor:'#ff365f',opacity:splitAlpha,transform:`translateX(${rgbOffset+sliceOffset}px)`,clipPath:'inset(0 0 52% 0)',filter:textFilter}}>{text}</span><span style={{...fillStyle,position:'absolute',inset:0,color:'#20e8ff',WebkitTextFillColor:'#20e8ff',opacity:splitAlpha,transform:`translateX(${-rgbOffset-sliceOffset}px)`,clipPath:'inset(48% 0 0 0)',filter:textFilter}}>{text}</span></>}
    {Boolean(shadow.enabled) && numberValue(shadow.opacity,0) > 0 && <span data-vdg-layer="shadow" style={{position:'absolute',inset:0,color:cssColor(shadow.color,'#000000ff'),WebkitTextFillColor:cssColor(shadow.color,'#000000ff'),WebkitTextStroke:`${numberValue(shadow.spread,0)*2*scale}px ${cssColor(shadow.color,'#000000ff')}`,opacity:numberValue(shadow.opacity,0),translate:`${numberValue(shadow.offset_x,numberValue(shadow.offsetX,0))*scale}px ${numberValue(shadow.offset_y,numberValue(shadow.offsetY,0))*scale}px`,filter:shadowFilter,transform:layerTransform(textValues),pointerEvents:'none'}}>{text}</span>}
    {[...(textLayer.strokes ?? [])].reverse().map((stroke,index)=><OutsideStrokeText key={index} radius={numberValue(stroke.width,0)*scale} color={cssColor(stroke.color,'#000000ff')} opacity={numberValue(stroke.opacity,1)} style={{position:'absolute',inset:0,transform:layerTransform(textValues),filter:textFilter,...textReveal}}>{text}</OutsideStrokeText>)}
    <span style={{...fillStyle,position:'relative',display:'inline-block',transform:layerTransform(textValues),filter:textFilter,...textReveal}}>{text}</span>
  </div>;
};
