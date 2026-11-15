"""Frozen, candidate-independent acoustic diagnostics. No boundary truth."""
from __future__ import annotations
import numpy as np


def occupancy(times_ms, intervals):
    """Boolean union; overlapping captions never count a frame twice."""
    covered=np.zeros(len(times_ms),dtype=bool)
    for a,b in intervals:
        if a is not None and b is not None and np.isfinite([a,b]).all() and b>a:
            covered |= (times_ms>=a)&(times_ms<b)
    return covered


def longest_run(mask, hop_ms=10):
    indices=np.flatnonzero(np.diff(np.r_[False,mask,False]))
    return int(max(indices[1::2]-indices[::2],default=0)*hop_ms)


def measure(features, intervals):
    t=np.asarray(features['time_ms']);state=np.asarray(features['state'])
    cover=occupancy(t,intervals);voice=state==1;silence=state==-1;uncertain=state==0
    def ratio(mask):return float(np.sum(mask&~cover)/max(1,np.sum(mask)))
    return dict(voice_activity_uncovered_ratio=ratio(voice),silence_occupied_ratio=float(np.sum(silence&cover)/max(1,np.sum(silence))),
        high_voice_frames=int(voice.sum()),high_silence_frames=int(silence.sum()),uncertain_frames=int(uncertain.sum()),
        uncertain_ratio=float(uncertain.mean()) if len(t) else 1.,uncertain_ms=int(uncertain.sum()*10),
        uncovered_voice_ms=int(np.sum(voice&~cover)*10),occupied_silence_ms=int(np.sum(silence&cover)*10),
        longest_uncovered_voice_ms=longest_run(voice&~cover),longest_occupied_silence_ms=longest_run(silence&cover),
        union_subtitle_ms=int(cover.sum()*10),target_speaker_uncovered_ratio=None,
        target_speaker_note='VAD does not identify the target speaker; mixed/context voice is diagnostic, not reliable per-track missing-speech punishment')


def controls():
    # Known speech anchor in [1000,2000], explicitly inserted digital silence outside.
    # This tests only known destructive relations, not arbitrary shifts of unknown truth.
    t=np.arange(12.5,4000,10);state=np.where((t>=1000)&(t<2000),1,-1)
    features=dict(time_ms=t.tolist(),state=state.tolist());good=measure(features,[(1000,2000)])
    bad={'in_inserted_silence':[(0,700)],'expanded_silence':[(0,4000)],'known_anchor_late':[(2300,3300)],
         'wrong_offset':[(101000,102000)],'destroyed_tail':[(1000,1100)],'shorten_all':[(1400,1600)],'energy_peak_only':[(1490,1510)]}
    rows=[]
    for name,intervals in bad.items():
        m=measure(features,intervals)
        detected=m['voice_activity_uncovered_ratio']>good['voice_activity_uncovered_ratio']+.1 or m['silence_occupied_ratio']>good['silence_occupied_ratio']+.1
        rows.append(dict(name=name,detected=detected,metrics=m))
    rows.append(dict(name='adjacent_sentence_text_mismatch',detected=False,reason='Acoustics alone cannot validate transcript semantics; original span/text identity controls detect pipeline mismatch, but cannot establish whether the fixed transcript is spoken.'))
    assert all(r['detected'] for r in rows[:-1])
    assert all(r['metrics']['voice_activity_uncovered_ratio']>0 or r['metrics']['silence_occupied_ratio']>0 for r in rows[:-1])
    assert measure(features,[(1000,2000),(1000,2000)])['union_subtitle_ms']==good['union_subtitle_ms']
    return dict(kind='known_control_relationships_not_human_accuracy',good=good,controls=rows,passed=True,text_semantics_unsupported=True)
