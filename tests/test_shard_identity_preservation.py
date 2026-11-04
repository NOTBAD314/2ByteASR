from types import SimpleNamespace
import copy
from twobyteasr.recognition.shard_identity import namespace_result,repair_terminal


def result(index,start):
    return SimpleNamespace(index=index,segments=[SimpleNamespace(segment_id=1,start=start,end=start+1,
        caption_arbitration={'raw_window':{'segment_id':1}})],
        cues=[SimpleNamespace(cue_id=(index+1)*1000000+1,source_spans=[{'source_id':1,'source_time':[start,start+1]}])],
        reviews=[{'segment_id':1,'timestamp':start}])


def test_editorial_local_ids_become_unique_without_altering_raw_evidence():
    first,second=result(0,1),result(1,100)
    namespace_result(first);namespace_result(second)
    assert first.segments[0].segment_id==1000001
    assert second.segments[0].segment_id==2000001
    assert second.cues[0].source_spans[0]['source_id']==2000001
    assert second.reviews[0]['segment_id']==2000001
    assert second.segments[0].caption_arbitration['raw_window']['segment_id']==1
    assert not namespace_result(second)


def test_old_terminal_checkpoint_repaired_from_known_request_ranges():
    first,second=result(0,1),result(1,100)
    assert repair_terminal(first.segments+second.segments,first.cues+second.cues,
        {'0':{'start':0,'end':50},'1':{'start':50,'end':150}})
    assert [c.source_spans[0]['source_id'] for c in first.cues+second.cues]==[1000001,2000001]


def test_cache_roundtrip_preserves_arbitration_and_measured_alignment():
    import subtitle_core as legacy
    segment=legacy.SpeechSegment(segment_id=1,start=0.,end=1.,text='文本',confidence=1.,words=[])
    segment.caption_arbitration={'word_timing':{'basis':'provider_words','measured_words':[{'text':'文本','start_ms':0,'end_ms':1000}]}}
    restored=legacy.deserialize_segments(legacy.serialize_segments([segment]))[0]
    assert restored.caption_arbitration==segment.caption_arbitration
    cue=legacy.SubtitleCue(1,0.,1.,'文本')
    cue.forced_alignment={'segments':[{'start_basis':'model','end_basis':'model'}]}
    assert legacy.deserialize_cues(legacy.serialize_cues([cue]))[0].forced_alignment==cue.forced_alignment
