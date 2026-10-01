import React, {useEffect, useLayoutEffect, useMemo, useRef} from 'react';
import {AbsoluteFill, cancelRender, continueRender, delayRender} from 'remotion';
import {gsap as themeGsap} from 'gsap';
import {bundledThemeFontCss, cssFontStack} from '../webThemeFonts';
import '../webThemeMotion.js';
import '../webThemeClock.js';
(globalThis as any).gsap=themeGsap;

declare global {
  interface Window {
    __2byteFitCueAnimations: (root: HTMLElement, durationMs: number) => void;
    __2byteDriveAnimations: (root: HTMLElement, timeMs: number) => Promise<number>;
    __2byteApplyPlacement: (root: HTMLElement | null, placement: Record<string, unknown>) => void;
    __2byteMountMotion: (root: HTMLElement, spec: Record<string, unknown>, durationMs: number) => unknown;
    __2byteUnmountMotion: (root: HTMLElement | null) => void;
  }
}

/**
 * Web visual theme runtime (2byte.web-visual-theme v1).
 *
 * Themes are declarative HTML+CSS documents authored by the AI and sanitized
 * on the Python side (tag/attribute whitelist, no external CSS references,
 * no scripts). The app owns the only executable animation runtime:
 *
 *  - substitutes {{text}} / {{words}} / {{speaker}} placeholders,
 *  - injects the project's text-appearance tokens as CSS variables,
 *  - compiles MotionSpec through the shared paused GSAP timeline and seeks
 *    it from Remotion's frame time, with the same font barrier as HTML/LIVE;
 *  - reads older CSS themes through the existing WAAPI compatibility driver.
 */

export type WebThemeAppearance = {
  fontFamily?: string;
  fontSize?: number;
  fontWeight?: number;
  bold?: boolean;
  italic?: boolean;
  color?: string;
  strokeColor?: string;
  strokeWidth?: number;
  stroke2Color?: string;
  stroke2Width?: number;
  letterSpacing?: number;
};

export type WebTheme = {
  name?: string;
  stageHtml?: string;
  stageCss?: string;
  cueHtml?: string;
  cueCss?: string;
  appearance?: WebThemeAppearance;
  motionSpec?: Record<string, unknown>;
};

const escapeHtml = (value: string): string =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

const substitutePlaceholders = (
  html: string,
  text: string,
  speaker: string,
  translation = '',
): string => {
  text=text.replace(/\r\n|[\r\u2028\u2029]/g,'\n');
  const escapedText = `<span data-caption-text="true">${escapeHtml(text)}</span>`;
  const words = '<span data-caption-text="true">'+Array.from(text)
    .map((char) => (/\s/.test(char) ? char : `<span class="wt-w">${escapeHtml(char)}</span>`))
    .join('')+'</span>';
  const escapedSpeaker = escapeHtml(speaker);
  const escapedTranslation = escapeHtml(translation);
  return html
    .replace(/\{\{\s*text\s*\}\}/g, escapedText)
    .replace(/\{\{\s*words\s*\}\}/g, words)
    .replace(/\{\{\s*speaker\s*\}\}/g, escapedSpeaker)
    .replace(/\{\{\s*translation\s*\}\}/g, escapedTranslation);
};

/**
 * Pause every CSS animation in the subtree, wait for the pause to commit
 * (`ready`), then seek to the exact frame time. Waiting matters: assigning
 * `currentTime` while the pause is still pending races with the pending-pause
 * task, which overwrites the seek with its own hold time.
 */
const driveAnimations = async (root: HTMLElement | null, timeMs: number): Promise<number> => {
  if (!root || typeof root.getAnimations !== 'function') return -1;
  if (root.classList.contains('wt-cue')) {
    const raw = getComputedStyle(root).getPropertyValue('--wt-dur').trim();
    window.__2byteFitCueAnimations(root, (parseFloat(raw) || 0) * (/ms$/.test(raw) ? 1 : 1000));
  }
  return window.__2byteDriveAnimations(root, timeMs);
};

const useAnimationClock = (ref: React.RefObject<HTMLDivElement | null>, timeMs: number, motionSpec?: Record<string, unknown>, durationMs=3000, text='', bounded=false) => {
  // Register the barrier during render, before Remotion can observe ready.
  // An effect-only barrier races consecutive frames in a real video export.
  const handle = useMemo(() => delayRender('web-theme-animation-scrub'), [timeMs,motionSpec,durationMs,text]);
  const outsideCue=bounded && (timeMs < 0 || timeMs >= durationMs);
  useLayoutEffect(()=>{const node=ref.current;return ()=>window.__2byteUnmountMotion(node);},[ref,outsideCue]);
  useLayoutEffect(() => {
    let cancelled = false;
    (async()=>{
      await (window as any).__2bytePrepareCaption(ref.current);
      if(motionSpec&&ref.current){
        ref.current.getBoundingClientRect();await document.fonts.ready;
        if(cancelled)return;
        window.__2byteMountMotion(ref.current,motionSpec,durationMs);
      }
      await driveAnimations(ref.current,timeMs);
    })().then(() => {
      if (!cancelled) continueRender(handle);
    }, error => { if (!cancelled) cancelRender(error); });
    return () => {
      cancelled = true;
      continueRender(handle);
    };
  }, [ref, timeMs, handle,motionSpec,durationMs,text]);
};

/**
 * Prefix every top-level selector with the runtime scope class so theme CSS
 * can never leak into other components. Uses plain string processing — no CSS
 * nesting / @scope dependency (the bundled headless Chromium must stay old).
 * @keyframes blocks are emitted untouched (names are namespaced by contract).
 */
const scopeCss = (css: string, scope: string): string => {
  const out: string[] = [];
  let index = 0;
  const isAtRule = (prelude: string) => prelude.trim().startsWith('@');
  const readChunks = (depth: number): string => {
    // Collect raw text for one rule/prelude region at the given brace depth.
    let start = index;
    while (index < css.length) {
      const char = css[index];
      if (char === '{') {
        const prelude = css.slice(start, index);
        index += 1;
        if (isAtRule(prelude) && /@(media|supports|container|layer)\b/.test(prelude)) {
          const inner = readChunks(depth + 1);
          out.push(`${prelude}{${inner}}`);
          skipWhitespace();
          start = index;
          continue;
        }
        // Consume the balanced block body verbatim (keyframes, font-face, or a
        // normal declaration block we keep for selector prefixing).
        let balance = 1;
        const bodyStart = index;
        while (index < css.length && balance > 0) {
          if (css[index] === '{') balance += 1;
          else if (css[index] === '}') balance -= 1;
          index += 1;
        }
        const body = css.slice(bodyStart, index - 1);
        if (isAtRule(prelude)) {
          out.push(`${prelude}{${body}}`);
        } else {
          const scoped = prelude
            .split(',')
            .map((part) => part.trim())
            .filter(Boolean)
            .map((part) => (part === ':root' || part === 'to' || part === 'from' || /^%/.test(part) || /^\d+(\.\d+)?%$/.test(part) ? part : `${scope} ${part}`))
            .join(', ');
          out.push(scoped ? `${scoped}{${body}}` : body);
        }
        skipWhitespace();
        start = index;
        continue;
      }
      if (char === '}') {
        if (depth > 0) {
          const tail = css.slice(start, index);
          index += 1;
          return tail;
        }
        index += 1;
        start = index;
        continue;
      }
      index += 1;
    }
    return css.slice(start, index);
  };
  const skipWhitespace = () => {
    while (index < css.length && /\s/.test(css[index])) index += 1;
  };
  readChunks(0);
  return out.join('\n');
};

// Font stack passthrough (十八轮): themes own their font stack — pixel
// fonts, quoted CJK names and monospace fallbacks must survive verbatim.
// Only a bare single family name gets quoted; stacks pass as-is.
const fontStackToken = (family: unknown): string => {
  const raw = String(family || '').trim();
  if (!raw) return '"Microsoft YaHei UI", "PingFang SC", sans-serif';
  return cssFontStack(raw);
};

const tokenStyle = (
  appearance: WebThemeAppearance,
  width: number,
  height: number,
  durationSeconds: number,
  cueSeconds: number,
): React.CSSProperties => ({
  '--wt-font': fontStackToken(appearance.fontFamily),
  '--wt-size': `${(Number(appearance.fontSize || 58)*height/1080).toFixed(4)}px`,
  '--wt-weight': String(appearance.fontWeight ?? (appearance.bold === false ? 400 : 700)),
  '--wt-slant': appearance.italic ? 'italic' : 'normal',
  '--wt-color': String(appearance.color || '#FFFFFF'),
  '--wt-stroke': String(appearance.strokeColor || '#000000'),
  '--wt-stroke-w': `${(Number(appearance.strokeWidth ?? 3)*height/1080).toFixed(4)}px`,
  '--wt-stroke2': String(appearance.stroke2Color || appearance.strokeColor || '#000000'),
  '--wt-stroke2-w': `${(Number(appearance.stroke2Width || 0)*height/1080).toFixed(4)}px`,
  '--wt-spacing': `${(Number(appearance.letterSpacing || 0)*height/1080).toFixed(4)}px`,
  '--wt-w': `${Math.round(width)}px`,
  '--wt-h': `${Math.round(height)}px`,
  // One design unit: 12px at the 1080p reference, scaled with stage height.
  '--wt-u': `${((height / 1080) * 12).toFixed(3)}px`,
  '--wt-dur': `${Math.max(0.05, durationSeconds).toFixed(3)}s`,
  '--wt-t': `${cueSeconds.toFixed(3)}s`,
  '--wt-at': `${Math.max(0, durationSeconds).toFixed(0)}`,
  '--wt-p': durationSeconds > 0 ? Math.min(1, cueSeconds / durationSeconds).toFixed(4) : '0',
}) as React.CSSProperties;

export type WebThemeStageProps = {
  theme: WebTheme;
  nowMs: number;
  width: number;
  height: number;
};

/** Ambient layer — persists across the whole composition. */
export const WebThemeStage: React.FC<WebThemeStageProps> = ({theme, nowMs, width, height}) => {
  const ref = useRef<HTMLDivElement>(null);
  useAnimationClock(ref, nowMs);
  const css = useMemo(() => scopeCss(String(theme.stageCss || ''), '.wt-scope'), [theme.stageCss]);
  const tokens = useMemo(
    () =>
      tokenStyle(theme.appearance || {}, width, height, nowMs / 1000, nowMs / 1000),
    [theme.appearance, width, height, nowMs],
  );
  return (
    <div className="wt-scope" style={{position: 'absolute', inset: 0, ...tokens}}>
      <style>{css + '\n.wt-scope, .wt-scope * { animation-play-state: paused !important; }'}</style>
      <div ref={ref} className="wt-stage" style={{position: 'absolute', inset: 0}}
        dangerouslySetInnerHTML={{__html: String(theme.stageHtml || '')}} />
    </div>
  );
};

export type WebThemeCueProps = {
  theme: WebTheme;
  text: string;
  speaker?: string;
  translation?: string;
  localMs: number;
  durationMs: number;
  width: number;
  height: number;
  debug?: boolean;
  placement?: Record<string, unknown>;
};

/** Per-cue layer — animations scrub with cue-relative time. */
export const WebThemeCue: React.FC<WebThemeCueProps> = ({
  theme,
  text,
  speaker = '',
  translation = '',
  localMs,
  durationMs,
  width,
  height,
  debug = false,
  placement = {},
}) => {
  const placementRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { window.__2byteApplyPlacement(placementRef.current, placement); }, [placement]);
  const ref = useRef<HTMLDivElement>(null);
  const [state, setState] = React.useState({animations: -1, time: -1, cardAnim: -1, scopeOk: -1});
  useAnimationClock(ref, localMs,theme.motionSpec,durationMs,text,true);
  useEffect(() => {
    if (!debug) return;
    let cancelled = false;
    driveAnimations(ref.current, Math.max(0, localMs)).then((found) => {
      if (cancelled) return;
      const spans = ref.current?.querySelectorAll('.wt-w');
      const first = spans && spans.length ? (spans[0] as HTMLElement) : null;
      let fontSize = -1;
      let rectSum = -1;
      if (first) {
        const computed = getComputedStyle(first);
        const size = parseFloat(computed.fontSize);
        fontSize = Number.isFinite(size) ? Math.min(250, Math.round(size)) : -2;
        const rect = first.getBoundingClientRect();
        rectSum = Math.min(250, Math.round(rect.width + rect.height));
      }
      setState({animations: found, time: Math.max(0, localMs), cardAnim: fontSize, scopeOk: rectSum});
    });
    return () => {
      cancelled = true;
    };
  }, [ref, localMs, debug]);
  const css = useMemo(() => scopeCss(String(theme.cueCss || ''), '.wt-scope'), [theme.cueCss]);
  const tokens = useMemo(
    () =>
      tokenStyle(
        theme.appearance || {},
        width,
        height,
        Math.max(0.05, durationMs / 1000),
        Math.max(0, localMs) / 1000,
      ),
    [theme.appearance, width, height, durationMs, localMs],
  );
  const html = useMemo(
    () => substitutePlaceholders(String(theme.cueHtml || ''), text, speaker, translation),
    [theme.cueHtml, text, speaker],
  );
  if (localMs < 0 || localMs >= durationMs) return null;
  return (
    <AbsoluteFill ref={placementRef} className="subtitle-placement">
    <AbsoluteFill className="theme-motion">
    <AbsoluteFill className="wt-scope" style={tokens}>
      {/* The runtime owns a video-sized containing block. Authored theme CSS
          follows this default, so legacy themes can still style their root. */}
      <style>{bundledThemeFontCss(theme.appearance?.fontFamily)+'.wt-scope > .wt-cue {position:absolute;inset:0;}\n'+css + '\n.wt-scope, .wt-scope * { animation-play-state: paused !important; }'}</style>
      <div ref={ref} className="wt-cue" style={{position:'absolute'}}
        dangerouslySetInnerHTML={{__html: html}} />
      {debug
        ? <React.Fragment>
            <div style={{position: 'absolute', left: 0, top: 0, width: 30, height: 30,
              background: `rgb(${Math.max(0, state.animations) & 255}, ${Math.max(0, state.time) & 255}, 0)`}} />
            <div style={{position: 'absolute', left: 40, top: 0, width: 30, height: 30,
              background: `rgb(${Math.max(0, state.cardAnim) & 255}, ${Math.max(0, state.scopeOk) & 255}, 0)`}} />
          </React.Fragment>
        : null}
    </AbsoluteFill>
    </AbsoluteFill>
    </AbsoluteFill>
  );
};
