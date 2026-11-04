"""A single visible caption must never satisfy a two-cue overlap check."""
import numpy as np
from scripts.analyze_caption_boundary import classify_caption_mask


def test_overlap_requires_evidence_for_each_distinct_caption():
    a=np.zeros((40,60),dtype=bool);a[5:25,5:25]=True
    b=np.zeros_like(a);b[15:35,20:40]=True
    refs={'A':a,'B':b}
    assert classify_caption_mask(a,refs)[0]=='A'
    assert classify_caption_mask(b,refs)[0]=='B'
    assert classify_caption_mask(a|b,refs)[0]=='A+B'
    assert classify_caption_mask(np.zeros_like(a),refs)[0]=='None'


def test_identical_captions_cannot_prove_two_owners():
    a=np.zeros((40,60),dtype=bool);a[5:25,5:25]=True
    assert classify_caption_mask(a,{'A':a,'B':a.copy()})[0]!='A+B'


def test_partial_second_caption_is_not_complete_overlap():
    a=np.zeros((40,60),dtype=bool);a[5:25,5:25]=True
    b=np.zeros_like(a);b[15:35,30:50]=True
    partial=a.copy();partial[15:20,30:50]=True
    assert classify_caption_mask(partial,{'A':a,'B':b})[0]!='A+B'
