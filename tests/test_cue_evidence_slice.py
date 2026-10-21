from types import SimpleNamespace
from twobyteasr.recognition.cue_evidence_slice import slice_evidence


def test_cue_slice_does_not_send_full_neighbor_dialogue():
    row = dict(start_ms=0, end_ms=3000, moss_text='所以感觉有点失去比赛感觉了',
        words=[dict(start_ms=i*200, end_ms=(i+1)*200, text=c)
               for i,c in enumerate('所以感觉有点失去比赛感觉了')])
    cue = SimpleNamespace(start_ms=0, end_ms=1600)
    assert slice_evidence(row, cue, 'moss_text') == '所以感觉有点失去'
    assert row['moss_text'] == '所以感觉有点失去比赛感觉了'


def test_short_overlap_from_other_speaker_is_unavailable():
    row = dict(start_ms=13670, end_ms=14210, moss_text='满血',
               words=[dict(start_ms=13670,end_ms=13860,text='满'),
                      dict(start_ms=13860,end_ms=14210,text='血')])
    assert slice_evidence(row, SimpleNamespace(start_ms=12417,end_ms=13817), 'moss_text') == ''


def test_latin_token_is_never_cut_at_letter_boundary():
    row = dict(start_ms=0,end_ms=1000,moss_text='S0pp往里走',
        words=[dict(start_ms=i*100,end_ms=(i+1)*100,text=c)
               for i,c in enumerate('S0pp往里走')])
    assert slice_evidence(row, SimpleNamespace(start_ms=200,end_ms=1000), 'moss_text') == 'S0pp往里走'


def test_no_word_times_means_partial_segment_cannot_claim_aligned_evidence():
    row = dict(start_ms=0,end_ms=3000,firered_text='前半句后半句')
    assert slice_evidence(row,SimpleNamespace(start_ms=0,end_ms=1500),'firered_text') == ''
    assert slice_evidence(row,SimpleNamespace(start_ms=0,end_ms=3000),'firered_text') == '前半句后半句'
