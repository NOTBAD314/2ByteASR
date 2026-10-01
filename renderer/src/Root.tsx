import React from 'react';
import {Composition} from 'remotion';
import {SubtitleComposition, SubtitleProps} from './SubtitleComposition';

const defaults: SubtitleProps = {
  schemaVersion: 1,
  width: 1920,
  height: 1080,
  fps: 30,
  durationInFrames: 300,
  cues: [],
  recipes: {},
};

export const RemotionRoot: React.FC = () => (
  <Composition
    id="SubtitleOverlay"
    component={SubtitleComposition}
    width={1920}
    height={1080}
    fps={30}
    durationInFrames={300}
    defaultProps={defaults}
    calculateMetadata={({props}) => ({
      width: props.width,
      height: props.height,
      fps: props.fps,
      durationInFrames: props.durationInFrames,
    })}
  />
);
