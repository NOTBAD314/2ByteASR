import type {WordAnimation} from './TimedText';

type Metrics = {
  text: string; family: string; size: number; weight: number; italic: boolean;
  spacing: number; lineHeight: number; anchorX: number; anchorY: number;
  perLetter?: boolean; plan?: WordAnimation;
};

// Glyph measurement is static work. A bounded cache is shared by the stroke,
// shadow and fill copies and by every frame of the same caption/font/layout.
const cache = new Map<string, {x: number; y: number}>();
let canvas: HTMLCanvasElement | undefined;

export const captionInkAnchor = (input: Metrics): {x: number; y: number} => {
  if (typeof document === 'undefined') return {x: 0, y: 0};
  const font = `${input.italic ? 'italic' : 'normal'} ${input.weight} ${input.size}px ${JSON.stringify(input.family)}`;
  const marks = input.plan?.marks || [];
  const units = (input.plan?.units || []).map(unit => [unit.char_start, unit.char_end]);
  // A first render may precede document.fonts.ready. Its fallback metrics may
  // never be reused once the actual face is available.
  const key = JSON.stringify([input.text, font, document.fonts.check(font), input.spacing,
    input.lineHeight, input.anchorX, input.anchorY, input.perLetter, marks, units]);
  const found = cache.get(key);
  if (found) {
    cache.delete(key); cache.set(key, found);
    return found;
  }
  canvas ??= document.createElement('canvas');
  const context = canvas.getContext('2d');
  if (!context) return {x: 0, y: 0};
  context.font = font;
  const metrics = context.measureText('Mg');
  const ascent = metrics.fontBoundingBoxAscent || metrics.actualBoundingBoxAscent;
  const descent = metrics.fontBoundingBoxDescent || metrics.actualBoundingBoxDescent;
  const baseline = (input.lineHeight-ascent-descent)/2+ascent;
  const lines = input.text.split('\n');
  const measured: {width: number; left: number; right: number; top: number; bottom: number}[] = [];
  let sourceStart = 0;
  for (let row = 0; row < lines.length; row++) {
    const characters = Array.from(lines[row]);
    const end = sourceStart+characters.length;
    const edges = new Set([sourceStart, end]);
    for (const edge of [...marks.flatMap(mark => [mark.start, mark.end]), ...units.flat()]) {
      if (edge > sourceStart && edge < end) edges.add(edge);
    }
    if (input.perLetter) for (let offset=1; offset<characters.length; offset++) edges.add(sourceStart+offset);
    const sorted = [...edges].sort((a, b) => a-b);
    let width = 0, left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity;
    for (let i=0; i+1<sorted.length; i++) {
      const a = sorted[i], b = sorted[i+1];
      const attrs = Object.assign({}, ...marks.filter(mark => mark.start <= a && mark.end >= b));
      const weight = attrs.bold === undefined ? input.weight : attrs.bold ? Math.max(700, input.weight) : 400;
      const italic = attrs.italic === undefined ? input.italic : attrs.italic;
      context.font = `${italic ? 'italic' : 'normal'} ${weight} ${input.size}px ${JSON.stringify(input.family)}`;
      const text = characters.slice(a-sourceStart, b-sourceStart).join('');
      const ink = context.measureText(text);
      if (text.trim()) {
        left = Math.min(left, width-ink.actualBoundingBoxLeft);
        right = Math.max(right, width+ink.actualBoundingBoxRight+Math.max(0, b-a-1)*input.spacing);
        top = Math.min(top, row*input.lineHeight+baseline-ink.actualBoundingBoxAscent);
        bottom = Math.max(bottom, row*input.lineHeight+baseline+ink.actualBoundingBoxDescent);
      }
      width += ink.width+(b-a)*input.spacing;
    }
    measured.push({width, left, right, top, bottom});
    sourceStart = end+1;
  }
  const width = Math.max(0, ...measured.map(row => row.width));
  const visible = measured.filter(row => Number.isFinite(row.left));
  let correction = {x: 0, y: 0};
  if (visible.length) {
    const left = Math.min(...visible.map(row => (width-row.width)*input.anchorX+row.left));
    const right = Math.max(...visible.map(row => (width-row.width)*input.anchorX+row.right));
    const top = Math.min(...visible.map(row => row.top));
    const bottom = Math.max(...visible.map(row => row.bottom));
    correction = {x: width*input.anchorX-left-(right-left)*input.anchorX,
      y: lines.length*input.lineHeight*input.anchorY-top-(bottom-top)*input.anchorY};
  }
  cache.set(key, correction);
  while (cache.size > 512) cache.delete(cache.keys().next().value!);
  return correction;
};
