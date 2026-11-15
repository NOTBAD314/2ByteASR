"""Pinned Local Head adapter; the base forward belongs to the caller."""
from __future__ import annotations
import math
import sys
from pathlib import Path


def safe_boundaries(base, candidate, duration_ms):
    """Fall back by window instead of fabricating short/refitted intervals."""
    if len(base) != len(candidate) or len(base) % 2:
        return list(base), 'slot_count'
    if any(not math.isfinite(float(x)) for x in candidate):
        return list(base), 'nonfinite'
    if any(float(x) < 0 or float(x) > duration_ms for x in candidate):
        return list(base), 'outside_window'
    out = [float(x) for x in candidate]
    if any(out[i+1] - out[i] < 10 for i in range(0, len(out), 2)):
        return list(base), 'degenerate_duration'
    # One continuous speaker sequence only; other speakers are separate jobs.
    for index in range(1, len(out)-1, 2):
        if out[index] > out[index+1]:
            cut = (out[index] + out[index+1]) / 2
            if cut <= out[index-1] or cut >= out[index+2]:
                return list(base), 'overlap_projection'
            out[index] = out[index+1] = cut
    if out and out[-1] < float(base[-1]) - 20:
        return list(base), 'possible_tail_shortening'
    return out, None


class LocalHead:
    def __init__(self, directory, *, torch):
        from ..model_integrity import verify_model_files
        from .alignment_backend import COMPANION_WHEEL
        directory = verify_model_files('qwen_ultra_head', directory)
        wheel = str((directory / COMPANION_WHEEL).resolve())
        loaded = sys.modules.get('qwen_fa_ultra')
        if loaded is not None and not str(getattr(loaded, '__file__', '')).startswith(wheel):
            raise RuntimeError('Local Head companion loaded from a different location')
        sys.path.insert(0, wheel)
        from qwen_fa_ultra.head import load_local_head, decode_offsets
        from qwen_fa_ultra.features import extract_fixed_center_features
        from qwen_fa_ultra.runtime import _context_for_sample
        self.head, self.normalizer, self.metadata = load_local_head(Path(directory) / 'local_head', device='cpu')
        self.head.eval()
        self.torch = torch
        self.decode = decode_offsets
        self.features = extract_fixed_center_features
        self.context_for_sample = _context_for_sample

    def capture(self, hidden, inputs, unit_lists, token_id):
        contexts = []
        if hidden.ndim != 3 or hidden.shape[:2] != inputs['input_ids'].shape:
            raise RuntimeError('Local Head hidden/input shape mismatch')
        for row, units in enumerate(unit_lists):
            positions = (inputs['input_ids'][row] == token_id).nonzero().flatten()
            if positions.numel() != 2 * len(units):
                raise RuntimeError('Local Head slot count mismatch')
            context, mask, endpoints = self.context_for_sample(hidden[row], positions,
                [unit.text for unit in units], qwen_dim=int(self.head.config.qwen_dim))
            contexts.append((context.detach().to('cpu'), mask.detach().to('cpu'),
                             endpoints.detach().to('cpu'), positions.detach().to('cpu').tolist()))
        return contexts

    def refine(self, audio, units, fixed, captured, *, sample_id, pass_id):
        torch = self.torch
        context, mask, endpoints, positions = captured
        if len(fixed) != context.shape[0] or len(fixed) != 2 * len(units):
            raise RuntimeError('Local Head context belongs to another unit list')
        if any(not math.isfinite(float(x)) for x in fixed):
            raise RuntimeError('Local Head base timestamp is nonfinite')
        features = self.features(audio, tuple(float(x) for x in fixed), batch_size=128, normalizer=self.normalizer)
        corrections = []
        with torch.inference_mode():
            for start in range(0, len(fixed), 128):
                stop = start + 128
                output = self.head(torch.from_numpy(features[start:stop]), context[start:stop], mask[start:stop], endpoints[start:stop])
                corrections.extend(self.decode(output['boundary_logits']).cpu().tolist())
        candidate = [float(x) + float(delta) for x, delta in zip(fixed, corrections)]
        refined, reason = safe_boundaries(fixed, candidate, len(audio) / 16)
        return refined, dict(status='base_fallback' if reason else 'refined', reason=reason,
            sample_id=str(sample_id), pass_id=pass_id, base_fixed_ms=list(fixed), refined_ms=refined, candidate_ms=candidate,
            slots=[dict(unit_id=i//2, endpoint='START' if i%2 == 0 else 'END', input_position=position)
                   for i, position in enumerate(positions)], extra_base_forwards=0)
