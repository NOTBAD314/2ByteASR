from types import SimpleNamespace
import numpy as np
import subtitle_core
from twobyteasr.recognition.asr_schema import normalize_firered_worker_result, flatten_segment_tokens
from twobyteasr.recognition.speech_coverage import transcribe_recovery_window


def test_firered_control_windows_keep_zero_text_empty_and_preserve_literal_words():
    jobs = [dict(offset=0,duration=1), dict(offset=1,duration=1)]
    result = normalize_firered_worker_result(dict(results=[
        dict(segment_id=1,text='',timestamp=[['<sil>',0,1]],alignment_status='aligned'),
        dict(segment_id=2,text='silk<正文><sil>呀',timestamp=[['silk<正文>',0,.3],['<sil>',.3,.5],['呀',.5,.9]])]),jobs)
    assert [r['text'] for r in result['segments']] == ['silk<正文>呀']
    assert [r['text'] for r in flatten_segment_tokens(result)] == ['silk<正文>', '呀']
    assert result['metadata']['excluded_windows'][0]['segment_id'] == 1


def test_exact_recovery_cache_and_nested_time_mapping(tmp_path):
    samples = np.arange(48000,dtype=np.float32)/48000
    seen = []
    def recognize(backend,path,regions,audio,seconds):
        seen.append(audio.copy())
        assert regions == [dict(start=0.,end=1.)] and seconds==1.
        word = dict(start=.2,end=.4,text='哈')
        return [dict(word,tokens=[word],provider_source=dict(request_offset=0.,source_start=.2,
                    source_end=.4,valid_word_times=[word]))]
    legacy = SimpleNamespace(transcribe_primary_reference=recognize,build_qwen_asr_context=lambda _: '',
                             record_run_event=lambda *a,**k: None)
    owner=SimpleNamespace(media_identity={'fingerprint':'media'},asr_endpoint_snapshot={'model':'model'},
                         requested_language='zh',asr_settings_snapshot={'x':1})
    args=(dict(cache_dir=str(tmp_path)),owner,legacy)
    first=transcribe_recovery_window('api','video',samples,1,2,*args)
    again=transcribe_recovery_window('api','video',samples,1,2,*args)
    assert not first.cache_hit and again.cache_hit and len(seen)==1
    assert np.array_equal(seen[0],samples[16000:32000])
    assert first[0]['tokens'][0]['start']==first[0]['provider_source']['valid_word_times'][0]['start']==1.2
    assert first==again
