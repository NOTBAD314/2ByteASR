from types import SimpleNamespace as NS
from twobyteasr.projects.recognition_provenance import replacement_mapping


def test_overlapping_other_speaker_never_enters_replacement_mapping():
    p=NS(cues=[NS(id='a',speaker_id='merged'),NS(id='b',speaker_id='B')],generation_metadata={'segmentation_source_spans':{'cues':{
        'a':{'parts':[{'source_id':11}]},'b':{'parts':[{'source_id':22}]}}}})
    before=[{'id':'asr-stable-a','speaker_id':'A','start_ms':0,'end_ms':5000,'text':'hello'},
            {'id':'asr-stable-b','speaker_id':'B','start_ms':0,'end_ms':5000,'text':'goodbye'}]
    sources=[('segment:22',{'speaker_id':'B','start_ms':0,'end_ms':5000,'text':'goodbye'}),
             ('segment:11',{'speaker_id':'A','start_ms':0,'end_ms':5000,'text':'hello'})]
    mapping,receipts=replacement_mapping(p,before,sources)
    assert mapping=={'asr-stable-a':['a'],'asr-stable-b':['b']}
    assert receipts['asr-stable-a']['status']=='resolved'
    assert replacement_mapping(p,list(reversed(before)),list(reversed(sources)))[0]==mapping


def test_ambiguous_source_is_not_guessed_by_array_position_or_time_overlap():
    p=NS(cues=[NS(id='a')],generation_metadata={'segmentation_source_spans':{'cues':{'a':{'parts':[{'source_id':11}]}}}})
    before=[{'id':'stable','speaker_id':'A','start_ms':0,'end_ms':5000,'text':'yes'}]
    sources=[('segment:'+str(i),{'speaker_id':'A','start_ms':0,'end_ms':5000,'text':'yes'}) for i in (11,22)]
    mapping,receipts=replacement_mapping(p,before,sources)
    assert mapping['stable']==[] and receipts['stable']['status']=='needs_confirmation'


def test_saved_count_uses_committed_reference_not_generated_array_count():
    from twobyteasr.projects.recognition_provenance import committed_cue_count
    assert committed_cue_count({'result_ref_json':'{"cue_count":351}'},352)==351
    assert committed_cue_count({'result_ref_json':'{"cue_count":true}'},352)==352
    assert committed_cue_count({'result_ref_json':'invalid'},352)==352
