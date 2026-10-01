# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang)

import enum
import logging
from collections import deque

import numpy as np

from .constants import FRAME_LENGTH_MS, FRAME_SHIFT_MS, FRAME_LENGTH_S, FRAME_SHIFT_S

logger = logging.getLogger(__name__)


@enum.unique
class VadState(enum.Enum):
    SILENCE = 0
    POSSIBLE_SPEECH = 1
    SPEECH = 2
    POSSIBLE_SILENCE = 3


class VadPostprocessor:
    def __init__(self, smooth_window_size,
                 prob_threshold,
                 min_speech_frame,
                 max_speech_frame,
                 min_silence_frame,
                 merge_silence_frame,
                 extend_speech_frame):
        self.smooth_window_size = max(1, smooth_window_size)
        self.prob_threshold = prob_threshold
        self.min_speech_frame = min_speech_frame
        self.max_speech_frame = max_speech_frame
        self.min_silence_frame = min_silence_frame
        self.merge_silence_frame = merge_silence_frame
        self.extend_speech_frame = extend_speech_frame

    def process(self, raw_probs):
        if not raw_probs:
            return []

        smoothed_probs = self._smooth_prob(raw_probs)

        binary_preds = self._apply_threshold(smoothed_probs)

        # decision: 0 means silence, 1 means speech
        decisions = self._smooth_preds_with_state_machine(binary_preds)

        fixed_decisions = self._fix_smooth_window_start(decisions)
        smoothed_decisions = self._merge_short_silence_segments(fixed_decisions)
        extend_decisions = self._extend_speech_segments(smoothed_decisions)
        final_decisions = self._split_long_speech_segments(extend_decisions, raw_probs)
        # don't call _merge_short_silence_segments after _split_long_speech_segments

        return final_decisions

    def decision_to_segment(self, decisions, wav_dur=None):
        segments = []
        speech_start = None
        for t, decision in enumerate(decisions):
            if decision == 1 and speech_start is None:
                speech_start = t
            elif decision == 0 and speech_start is not None:
                if (t - speech_start) < self.min_speech_frame:
                    logger.warning("Unexpected short speech segment, check vad_postprocessor.py")
                segments.append((speech_start * FRAME_SHIFT_S,
                                 t * FRAME_SHIFT_S))
                speech_start = None
        if speech_start is not None:
            t = len(decisions) - 1
            if (t - speech_start) < self.min_speech_frame:
                logger.warning("Unexpected short speech segment, check vad_postprocessor.py")
            end_time = len(decisions) * FRAME_SHIFT_S + FRAME_LENGTH_S
            if wav_dur is not None:
                end_time = min(end_time, wav_dur)
            segments.append((speech_start * FRAME_SHIFT_S,
                             end_time))
        segments = [(round(s, 3), round(e, 3)) for s, e in segments]
        return segments

    def _smooth_prob_simple(self, probs):
        if self.smooth_window_size <= 1:
            return probs
        smoothed_probs = probs.copy()
        window = deque()
        window_sum = 0.0
        for i, p in enumerate(probs):
            window.append(p)
            window_sum += p
            if len(window) > self.smooth_window_size:
                left = window.popleft()
                window_sum -= left
            window_avg = window_sum / len(window)
            smoothed_probs[i] = window_avg
        return smoothed_probs

    def _smooth_prob(self, probs):
        if self.smooth_window_size <= 1:
            return np.asarray(probs)
        probs_np = np.array(probs)
        kernel = np.ones(self.smooth_window_size) / self.smooth_window_size
        # mode='same' 保持长度，'valid' 会变短
        smoothed = np.convolve(probs_np, kernel, mode='full')[:len(probs)]
        # 处理边界：前几帧用累积平均
        for i in range(min(self.smooth_window_size - 1, len(probs))):
            smoothed[i] = np.mean(probs_np[:i+1])
        return smoothed #.tolist()

    def _apply_threshold_simple(self, probs):
        return [int(p >= self.prob_threshold) for p in probs]

    def _apply_threshold(self, probs):
        probs_np = np.asarray(probs)
        return (probs_np >= self.prob_threshold).astype(int).tolist()

    def _smooth_preds_with_state_machine(self, binary_preds):
        """
        state transition is constrained by min_speech_frame & min_silence_frame
        """
        if self.min_speech_frame <= 0 and self.min_silence_frame <= 0:
            return binary_preds
        decisions = [0] * len(binary_preds)
        state = VadState.SILENCE
        speech_start = -1
        silence_start = -1
        for t, is_speech in enumerate(binary_preds):
            # State transition
            if state == VadState.SILENCE:
                if is_speech:
                    state = VadState.POSSIBLE_SPEECH
                    speech_start = t

            elif state == VadState.POSSIBLE_SPEECH:
                if is_speech:
                    assert speech_start != -1
                    if t - speech_start >= self.min_speech_frame:
                        state = VadState.SPEECH
                        decisions[speech_start:t] = [1] * (t - speech_start)
                else:
                    state = VadState.SILENCE
                    speech_start = -1

            elif state == VadState.SPEECH:
                if not is_speech:
                    state = VadState.POSSIBLE_SILENCE
                    silence_start = t

            elif state == VadState.POSSIBLE_SILENCE:
                if not is_speech:
                    assert silence_start != -1
                    if t - silence_start >= self.min_silence_frame:
                        state = VadState.SILENCE
                        speech_start = -1
                else:
                    state = VadState.SPEECH
                    silence_start = -1

            # current frame's decision
            if state == VadState.SPEECH or state == VadState.POSSIBLE_SILENCE:
                decision = 1
            elif state == VadState.SILENCE or state == VadState.POSSIBLE_SPEECH:
                decision = 0
            else:
                raise ValueError("Impossible VAD state")

            decisions[t] = decision
        return decisions

    def _fix_smooth_window_start(self, decisions):
        new_decisions = decisions.copy()
        for t, decision in enumerate(decisions):
            if t > 0 and decisions[t-1] == 0 and decision == 1:
                start = max(0, t-self.smooth_window_size)
                new_decisions[start:t] = [1] * (t - start)
        return new_decisions

    def _merge_short_silence_segments(self, decisions):
        if self.merge_silence_frame <= 0:
            return decisions
        new_decisions = decisions.copy()
        silence_start = None
        for t, decision in enumerate(decisions):
            if t > 0 and decisions[t-1] == 1 and decision == 0 and silence_start is None:
                silence_start = t
            elif t > 0 and decisions[t-1] == 0 and decision == 1 and silence_start is not None:
                silence_frame = t - silence_start
                if silence_frame < self.merge_silence_frame:
                    new_decisions[silence_start:t] = [1] * silence_frame
                silence_start = None
        return new_decisions

    def _extend_speech_segments_simple(self, decisions):
        """
        extend N frames before & after speech segments
        """
        if self.extend_speech_frame <= 0:
            return decisions
        new_decisions = decisions.copy()
        for t, decision in enumerate(decisions):
            if decision == 1:
                start = max(0, t - self.extend_speech_frame)
                end = min(len(decisions), t + self.extend_speech_frame + 1)
                new_decisions[start:end] = [1] * (end - start)
        return new_decisions

    def _extend_speech_segments(self, decisions):
        """
        extend N frames before & after speech segments
        """
        if self.extend_speech_frame <= 0:
            return decisions
        decisions_np = np.array(decisions)
        kernel = np.ones(2 * self.extend_speech_frame + 1)
        extended = np.convolve(decisions_np, kernel, mode='same')
        return (extended > 0).astype(int).tolist()

    def _split_long_speech_segments(self, decisions, probs):
        new_decisions = decisions.copy()
        segments = self.decision_to_segment(decisions)
        for start_s, end_s in segments:
            start_frame = int(start_s / FRAME_SHIFT_S)
            end_frame = int(end_s / FRAME_SHIFT_S)
            dur_frames = end_frame - start_frame
            if dur_frames > self.max_speech_frame:
                segment_probs = probs[start_frame:end_frame]
                split_points = self._find_split_points(segment_probs)
                for split_point in split_points:
                    split_frame = start_frame + split_point
                    new_decisions[split_frame] = 0
        return new_decisions

    def _find_split_points(self, probs):
        split_points = []
        length = len(probs)
        start = 0
        while start < length:
            if (length - start) <= self.max_speech_frame:
                break
            window_start = int(start + self.max_speech_frame / 2)
            window_end = int(start + self.max_speech_frame)
            window_probs = probs[window_start:window_end]

            min_index = window_start + np.argmin(window_probs)
            split_points.append(min_index)

            start = min_index + 1
        return split_points
