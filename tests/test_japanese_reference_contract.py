from types import SimpleNamespace
from twobyteasr.recognition.qwen_generation import generation_measure,retry_token_budget
from twobyteasr.recognition.reference_projection import project_reference_windows
from twobyteasr.subtitle_rules.japanese_correction import assess_patch

def segment(i,start,text,speaker='S1',end=None):
    return SimpleNamespace(segment_id=i,start=start,end=end or start+1,text=text,speaker=speaker)

def test_generation_eos_limit_and_other_stop_are_distinct():
    assert generation_measure([1,2,99,0],eos_ids=99,limit=4,input_tokens=200)['stop_reason']=='eos'
    hit=generation_measure([1,2,3,4],eos_ids=[99,100],limit=4,input_tokens=200)
    assert hit['token_limit_reached'] and hit['output_tokens']==4
    assert generation_measure([1],eos_ids=None,limit=4,input_tokens=200)['stop_reason']=='other_stop'
    assert retry_token_budget(25,160)==332 and retry_token_budget(400,512)==1024

def test_local_japanese_reference_is_slice_not_whole_twenty_second_window():
    rows=[segment(1,0,'お昼だー'),segment(2,2,'いやしかし珍しいこともあるもんだね'),segment(3,5,'奇跡ですよ奇跡')]
    windows=[{'start':0,'end':20,'text':'お昼だいやしかし珍しいこともあるもんだね奇跡ですよ奇跡'}]
    result=project_reference_windows(rows,windows)
    assert result[1]['text']=='お昼だ'
    assert result[2]['text']==rows[1].text and result[3]['text']==rows[2].text
    assert all(not span['acoustic_alignment'] for r in result.values() for span in r['spans'])

def test_overlapping_people_conflicting_windows_and_truncation_never_vote():
    rows=[segment(1,0,'これは甲の声','A',2),segment(2,1,'これは乙の声','B',3)]
    w={'start':0,'end':4,'text':'これは甲の声これは乙の声'}
    result=project_reference_windows(rows,[w])
    assert not any(r['text'] for r in result.values())
    rows=[segment(1,0,'カイロショートくん')]
    windows=[dict(w,text='回路ショートくん'),dict(w,text='懐炉ショートくん')]
    assert project_reference_windows(rows,windows)[1]['status']=='cross_window_disagreement'
    assert not project_reference_windows(rows,[dict(w,generation={'token_limit_reached':True})])[1]['text']

def test_japanese_notation_and_semantic_difference_do_not_use_chinese_length_gate():
    assert assess_patch('カイロショートくん','回路ショートくん',[('qwen','回路ショートくん')])[0]=='review'
    assert assess_patch('10年','十年',[])[0]=='keep'
    assert assess_patch('ショート','しょーと',[])[0]=='keep'
    assert assess_patch('死にたくないよ','仕方がないよ',[('qwen','仕方がないよ')])[0]=='review'
    assert assess_patch('古代兵器','巨大兵器',[('qwen','巨大兵器'),('qwen','巨大兵器')])[0]=='review'
    assert assess_patch('カイロ','回路',[('qwen','回路'),('firered','回路')])[0]=='accept'
    assert assess_patch('そうだね','そうだ',[('qwen','そうだ'),('firered','そうだ')])[0]=='review'
    assert assess_patch('カイロ','回路',[('qwen','回路'),('qwen3-asr','回路'),('qwen_forced_aligner','回路')])[0]=='review'

def test_main_correction_path_routes_japanese_without_chinese_length_rules():
    import subtitle_core
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    context=RuntimeContext(task_language='ja');decisions=[]
    with activate_runtime_context(context):
        result,applied=apply_correction_edits('カイロショートくん',['回路ショートくん'],
            [{'from':'カイロ','to':'回路','start':0,'end':3,'type':'asr_correction'}],
            independent_sources=[('review','回路ショートくん')],decisions=decisions)
    assert result=='カイロショートくん' and not applied
    assert decisions[0]['rule_id']=='japanese_semantic_needs_listening'

def test_unassociated_reference_without_native_probability_is_unknown_not_low_text_confidence():
    import moss_firered_pipeline as pipeline
    events=[]
    legacy=SimpleNamespace(record_run_event=lambda event,**data:events.append((event,data)))
    row=SimpleNamespace(firered_text='',qwen_text='',firered_alignment_confidence=0,
        qwen_confidence=0,qwen_confidence_available=False,caption_arbitration={})
    pipeline._record_fused_review_classification(legacy,[row],firered_selected=False,firered_failed=False,
        qwen_selected=True,qwen_failed=False)
    counts=events[-1][1]['counts']
    assert counts['TEXT_CONFIDENCE_UNKNOWN']==1 and counts['TEXT_LOW_CONFIDENCE']==0
    assert events[-1][1]['non_exclusive_dimensions']

def test_saved_mosi_default_score_does_not_become_native_probability():
    from twobyteasr.recognition.asr_source_evidence import _confidence
    from twobyteasr.subtitle_rules.studio_qc import _confidence_values
    model='asr-api:moss-transcribe-diarize-pro'
    row={'confidence':.78,'primary_source':'api-primary'}
    p=SimpleNamespace(generation_metadata={'models':{'primary_asr_backend':'api',
        'qwen_asr_api_protocol':'mosi_transcriptions','qwen_asr_api_model':'moss-transcribe-diarize-pro'}},asr_evidence={'x':row})
    assert _confidence(row,model) is None and _confidence_values(p,SimpleNamespace(evidence_refs=['x']))==[]
    row['provider_source']={'confidence_available':True}
    assert _confidence(row,model)==.78 and _confidence_values(p,SimpleNamespace(evidence_refs=['x']))==[.78]
