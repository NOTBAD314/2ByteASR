import React, {useEffect, useState} from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig, delayRender, continueRender, cancelRender} from 'remotion';
import {TrustedSubtitle} from './components/TrustedSubtitle';
import {VisualDesignGraphSubtitle} from './components/VisualDesignGraphSubtitle';
import {WebThemeCue, WebThemeStage} from './components/WebThemeSubtitle';
import {bundledThemeFontCss} from './webThemeFonts';

export type Cue = {id: string; text: string; speaker?: string; translation?: string; startMs: number; endMs: number; styleId: string; visual?: Recipe; snapshotHash?: string};
export type Recipe = {
  name: string;
  components: string[];
  typography: {fontFamily: string; fontSize: number; fontWeight?: number; bold: boolean; italic: boolean; spacing: number};
  fill: {type: 'solid'; color: string} | {type: 'gradient'; kind?: 'linear'|'radial'; angle: number; stops: {color: string; pos: number}[]};
  strokes: {color: string; width: number}[];
  glow: {color: string; blur: number; opacity: number};
  shadow: {enabled: boolean; color: string; opacity: number; offsetX: number; offsetY: number; blur: number; spread: number};
  background: {
    enabled: boolean; type: string; color: string; opacity: number;
    gradient: {colors: string[]; angle: number};
    paddingX: number; paddingY: number; radius: number;
    border: {color: string; width: number};
    shadow: {color: string; offsetX: number; offsetY: number; blur: number};
    texture: {type: string; opacity: number; scale: number; seed: number};
    transform: {rotation: number; scale: number; offsetX: number; offsetY: number};
  };
  mask: {type: string; softness: number; direction: string};
  decorations: string[];
  motion: {mode?: 'none'|'explicit'; entrance?: Record<string, unknown>; hold?: Record<string, unknown>; exit?: Record<string, unknown>; entry?: string; duration?: number};
  layout: {alignment: number; marginV?: number; positionX?: number; positionY?: number; playResX?: number; playResY?: number; anchorX?: number; anchorY?: number; scaleX?: number; scaleY?: number; rotation?: number};
  visualGraph?: any;
  webTheme?: any;
};
export type SubtitleProps = {
  schemaVersion: number; width: number; height: number; fps: number; durationInFrames: number;
  cues: Cue[]; recipes: Record<string, Recipe>;
};

export const SubtitleComposition: React.FC<SubtitleProps> = ({cues, recipes}) => {
  const [fontGate] = useState(()=>delayRender('caption font faces'));
  useEffect(()=>{
    Promise.all(cues.map(cue=>cue.visual ?? recipes[cue.styleId]).filter(Boolean).map(recipe=>
      document.fonts.load(`${recipe.typography.fontWeight || (recipe.typography.bold?700:400)} 90px ${JSON.stringify(recipe.typography.fontFamily)}`, '字幕Aa')))
      .then(()=>document.fonts.ready).then(()=>continueRender(fontGate)).catch(cancelRender);
  }, [fontGate, cues, recipes]);
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const nowMs = frame / fps * 1000;
  // Ambient web-theme layers persist across the whole composition (contract:
  // they must stay low-presence so they never fight the video itself).
  const activeStageTheme = cues
    .map((cue) => (cue.visual ?? recipes[cue.styleId])?.webTheme)
    .find((theme) => theme);
  return <AbsoluteFill style={{backgroundColor: 'transparent'}}>
    <style>{[...new Set(cues.map(cue=>(cue.visual ?? recipes[cue.styleId])?.typography.fontFamily).filter(Boolean))].map(family=>bundledThemeFontCss(family)).join('\n')}</style>
    {activeStageTheme
      ? <WebThemeStage key="wt-stage" theme={activeStageTheme} nowMs={nowMs} width={width} height={height}/>
      : null}
    {cues.filter((cue) => nowMs >= cue.startMs && nowMs < cue.endMs).map((cue) => {
      const recipe = cue.visual ?? recipes[cue.styleId];
      if (!recipe) return null;
      const localFrame = Math.max(0, frame - Math.round(cue.startMs / 1000 * fps));
      const durationFrames = Math.max(1, Math.round((cue.endMs - cue.startMs) / 1000 * fps));
      if (recipe.webTheme) {
        return <WebThemeCue
          key={cue.id}
          theme={recipe.webTheme}
          text={cue.text}
          speaker={cue.speaker || ''}
          translation={cue.translation || ''}
          localMs={localFrame / fps * 1000}
          durationMs={durationFrames / fps * 1000}
          width={width}
          height={height}
          placement={(recipe.layout as any)?.webPlacement || {}}
          debug={Boolean(recipe.webTheme.debug)}
        />;
      }
      return recipe.visualGraph
        ? <VisualDesignGraphSubtitle key={cue.id} text={cue.text} recipe={recipe} graph={recipe.visualGraph} frame={localFrame} fps={fps}/>
        : <TrustedSubtitle key={cue.id} text={cue.text} recipe={recipe} frame={localFrame} durationFrames={durationFrames} fps={fps}/>;
    })}
  </AbsoluteFill>;
};
