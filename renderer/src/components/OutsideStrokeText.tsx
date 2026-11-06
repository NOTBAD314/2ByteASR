import React, {useId} from 'react';
import {PaintedTextEffect, type Paint} from './EffectPaint';

type OutsideStrokeTextProps = {
  children: React.ReactNode;
  radius: number;
  color: string;
  paint?: Paint;
  opacity?: number;
  style?: React.CSSProperties;
  layer?: string;
};

export const OutsideStrokeText: React.FC<OutsideStrokeTextProps> = ({
  children,
  radius,
  color,
  opacity = 1,
  style,
  layer = 'outside-stroke',
  paint,
}) => {
  const filterId = `outside-stroke-${useId().replace(/:/g, '')}`;
  const safeRadius = Math.max(0, radius);
  if (safeRadius <= 0) return null;
  if (paint) return <PaintedTextEffect mode="stroke" paint={paint} radius={safeRadius} opacity={opacity} style={style} layer={layer}>{children}</PaintedTextEffect>;

  return <>
    <svg aria-hidden="true" width="0" height="0" style={{position: 'absolute'}}>
      <defs>
        <filter
          id={filterId}
          x="-100%"
          y="-100%"
          width="300%"
          height="300%"
          primitiveUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feMorphology in="SourceAlpha" operator="dilate" radius={safeRadius} result="expanded" />
          <feComposite in="expanded" in2="SourceAlpha" operator="out" result="outside-ring" />
          <feFlood floodColor={color} floodOpacity={Math.max(0, Math.min(1, opacity))} result="stroke-color" />
          <feComposite in="stroke-color" in2="outside-ring" operator="in" />
        </filter>
      </defs>
    </svg>
    <span
      aria-hidden="true"
      data-layer={layer}
      data-stroke-alignment="OUTSIDE"
      style={{
        ...style,
        color: '#ffffffff',
        WebkitTextFillColor: '#ffffffff',
        WebkitTextStroke: '0 transparent',
        filter: `url(#${filterId})`,
        pointerEvents: 'none',
      }}
    >{children}</span>
  </>;
};
