from copy import deepcopy
from types import SimpleNamespace as NS
from twobyteasr.projects.source_span_repair import repair


def project(text='ナノちゃんごめん今日はパパッと食べちゃおうか'):
    source='あもう時間ないや'+text
    p=NS(cues=[NS(id='211',text=text,speaker_id='A',evidence_refs=['segment:181'])],
        asr_evidence={'segment:181':dict(final_text=source,speaker_id='A',start_ms=1000,end_ms=6000)},
        generation_metadata={'segmentation_source_spans':{'cues':{'211':{'parts':[dict(source_id=181,char_start=8,char_end=19,raw_text=text[:11])]}}}})
    return p


def test_exact_linked_tail_mapping_is_repaired_without_text_edit():
    p=project();before=deepcopy(p.cues)
    assert repair(p)==['211']
    parts=p.generation_metadata['segmentation_source_spans']['cues']['211']['parts']
    assert parts[0]['source_id']==181 and parts[0]['raw_text']==p.cues[0].text
    assert vars(p.cues[0])==vars(before[0])
    assert repair(p)==[]


def test_wrong_speaker_or_ambiguous_text_never_gets_guessed_span():
    p=project();p.asr_evidence['segment:181']['speaker_id']='B'
    assert repair(p)==[]
    p=project('はい');p.asr_evidence['segment:181']['final_text']='はいはい'
    p.generation_metadata['segmentation_source_spans']['cues']['211']['parts'][0]['raw_text']=''
    assert repair(p)==[]


def test_unusable_optional_legacy_span_metadata_never_blocks_project():
    p=project();p.generation_metadata['segmentation_source_spans']=[]
    assert repair(p)==[]
    p=project();p.asr_evidence['segment:181']['start_ms']='unknown'
    assert repair(p)==[]


def test_missing_long_split_entry_is_recovered_only_from_exact_linked_text():
    p=project();del p.generation_metadata['segmentation_source_spans']['cues']['211']
    assert repair(p)==['211']
    assert p.generation_metadata['segmentation_source_spans']['cues']['211']['parts'][0]['raw_text']==p.cues[0].text
