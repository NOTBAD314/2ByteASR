import React, {useId, useLayoutEffect, useMemo, useRef, useState} from 'react';

export type Paint = {type?: string; color?: string; angle?: number; radius?: number;
  stops?: {color: string; position?: number; pos?: number}[]};
export const paintColor = (value: string): string => /^#[0-9a-f]{8}$/i.test(value)
  ? `#${value.slice(3)}${value.slice(1, 3)}` : value;
export const paintCss = (paint: Paint): string => {
  if (!paint.type || paint.type === 'solid') return paintColor(paint.color || '#ffffffff');
  const radial = paint.type.includes('radial');
  const stops = (paint.stops || []).map(s => `${paintColor(s.color)} ${(s.position ?? s.pos ?? 0)*(radial ? paint.radius ?? 1 : 1)*100}%`).join(',');
  return radial ? `radial-gradient(circle farthest-side at center,${stops})`
    : `linear-gradient(${90-(paint.angle ?? 0)}deg,${stops})`;
};

// A gradient image is composited through the glyph's alpha mask. Dilating or
// blurring the mask never changes the authored RGB/stop-alpha values.
const paintImage = (paint: Paint, width: number, height: number, padding: number) => {
  const w = Math.max(1,width), h = Math.max(1,height), p = padding;
  const radial = paint.type?.includes('radial');
  const radians = (paint.angle || 0)*Math.PI/180, dx = Math.cos(radians), dy = -Math.sin(radians);
  const reach = (Math.abs(dx)*w+Math.abs(dy)*h)/2;
  const stops = (paint.stops || []).map(s => {
    const color = paintColor(s.color);
    const rgb = color.length === 9 ? color.slice(0,7) : color;
    const alpha = color.length === 9 ? parseInt(color.slice(7,9),16)/255 : 1;
    return `<stop offset="${(s.position ?? s.pos ?? 0)*100}%" stop-color="${rgb}" stop-opacity="${alpha}"/>`;
  }).join('');
  const definition = !paint.type || paint.type === 'solid' ? '' : radial
    ? `<radialGradient id="p" gradientUnits="userSpaceOnUse" cx="${p+w/2}" cy="${p+h/2}" r="${Math.max(w,h)/2*(paint.radius ?? 1)}">${stops}</radialGradient>`
    : `<linearGradient id="p" gradientUnits="userSpaceOnUse" x1="${p+w/2-dx*reach}" y1="${p+h/2-dy*reach}" x2="${p+w/2+dx*reach}" y2="${p+h/2+dy*reach}">${stops}</linearGradient>`;
  const fill = definition ? 'url(#p)' : paintColor(paint.color || '#ffffffff');
  return `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${w+2*p}" height="${h+2*p}" viewBox="0 0 ${w+2*p} ${h+2*p}"><defs>${definition}</defs><rect width="100%" height="100%" fill="${fill}"/></svg>`)}`;
};

type Props = {children: React.ReactNode; paint: Paint; mode: 'stroke'|'shadow'|'glow';
  radius?: number; blur?: number; opacity?: number; style?: React.CSSProperties; layer?: string};
export const PaintedTextEffect: React.FC<Props> = ({children,paint,mode,radius=0,blur=0,opacity=1,style,layer}) => {
  const id = `effect-paint-${useId().replace(/:/g,'')}`;
  const ref = useRef<HTMLSpanElement>(null);
  const [size,setSize] = useState({width:1,height:1});
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => {
      const width = element.offsetWidth, height = element.offsetHeight;
      if (width && height) setSize(old => old.width===width && old.height===height ? old : {width,height});
    };
    measure();
    const observer = new ResizeObserver(measure); observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const padding = Math.ceil(Math.max(2,radius+blur*3+2));
  const uri = useMemo(()=>paintImage(paint,size.width,size.height,padding),[paint,size,padding]);
  return <>
    <svg aria-hidden="true" width="0" height="0" style={{position:'absolute'}}><defs>
      <filter id={id} x="-100%" y="-100%" width="300%" height="300%" primitiveUnits="userSpaceOnUse" colorInterpolationFilters="sRGB">
        <feMorphology in="SourceAlpha" operator="dilate" radius={Math.max(0,radius)} result="expanded"/>
        {blur>0 ? <feGaussianBlur in="expanded" stdDeviation={blur} result="soft-mask"/> : null}
        {mode==='stroke' || mode==='glow' ? <feComposite in={blur>0?'soft-mask':'expanded'} in2="SourceAlpha" operator="out" result="mask"/> : <feColorMatrix in={blur>0?'soft-mask':'expanded'} type="matrix" values="1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 0 0 0 1 0" result="mask"/>}
        <feImage href={uri} x={-padding} y={-padding} width={size.width+2*padding} height={size.height+2*padding} preserveAspectRatio="none" result="paint"/>
        <feComposite in="paint" in2="mask" operator="in"/>
      </filter>
    </defs></svg>
    <span ref={ref} aria-hidden="true" data-layer={layer || mode} data-effect-paint={paint.type}
      style={{...style,display:'inline-block',color:'#ffffff',WebkitTextFillColor:'#ffffff',WebkitTextStroke:'0 transparent',
        filter:[`url(#${id})`,style?.filter].filter(Boolean).join(' '),opacity:Math.max(0,Math.min(1,opacity)),pointerEvents:'none'}}>{children}</span>
  </>;
};
