"""PR #17 / issues #13/#14: immutable ownership, early source normalization."""
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
import subtitle_core as core
from twobyteasr.providers.asr_provider_snapshot import restore_source_text
from twobyteasr.subtitle_rules import grouping
from twobyteasr.subtitle_rules.grouping_contract import validate_grouping_result, attach_grouping_spans
from twobyteasr.subtitle_rules.cue_cleanup import drop_placeholder_source_rows
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context


def row(n, text, start, end, speaker='S01'):
    return core.SpeechSegment(n, start, end, text, .8, [], speaker=speaker)


def cue(n, text, start, end, speaker='S01'):
    return core.SubtitleCue(n, start, end, text, speaker=speaker)


def test_valid_source_contract_is_unchanged_and_idempotent():
    rows = [row(1,'啊',0,1),row(2,'<sil>',4,16.905)]
    cues = [cue(1,'啊',0,1),cue(2,'<sil>',4,16.905)]
    before=copy.deepcopy(cues)
    assert grouping._restore_grouped_source(rows,cues)
    assert grouping._restore_grouped_source(rows,cues)
    assert cues == before


@pytest.mark.parametrize('texts, output', [(['啊','<sil>'],['啊','<sil>']),
    (['Hello, ','(world!)'], ['Hello,','(world!)']), (['前一句。','「后一句」'],['前一句。','「后一句」'])])
def test_real_restore_uses_source_line_and_punctuation_boundaries(texts,output):
    rows=[row(i+1,text,i*3,i*3+2) for i,text in enumerate(texts)]
    cues=[cue(i+1,core.content_exact(text),i*3,i*3+2) for i,text in enumerate(texts)]
    assert restore_source_text(rows,cues)
    assert [c.text for c in cues] == output
    assert validate_grouping_result(rows,cues)
    assert restore_source_text(rows,cues)
    assert [c.text for c in cues] == output


def test_cleanup_cannot_remove_another_sources_overlapping_same_text():
    # The only <sil> cue belongs to S02. S01's source has no derived output:
    # incomplete/invalid provenance must not be guessed from text/time.
    rows=[row(1,'<sil>',205.06,217.965),row(2,'i',206,207,'S02')]
    cues=[cue(1,'<sil>',205.06,217.965,'S02')]
    before=copy.deepcopy((rows,cues))
    stats=drop_placeholder_source_rows(cues,rows)
    assert stats['rows']==0 and (rows,cues)==before


def test_old_placeholder_fragments_are_removed_by_exact_spans_only():
    rows=[row(1,'<sil>',205.06,217.965),row(2,'i',206,207,'S02')]
    cues=[cue(1,'<s',205.06,209.362),cue(2,'i',209.362,213.663),
          cue(3,'l>',213.663,217.965),cue(4,'i',206,207,'S02')]
    stats=drop_placeholder_source_rows(cues,rows)
    assert stats['rows']==1 and stats['cues']==3
    assert [(r.segment_id,r.text) for r in rows]==[(2,'i')]
    assert [(c.text,c.speaker) for c in cues]==[('i','S02')]
    assert validate_grouping_result(rows,cues)


@pytest.mark.parametrize('texts', [['<sil>','啊'],['啊','<sil>'],['<sil>','<blank>','啊','<unk>','正常正文'],
    ['sil','<title>','x < y','[not sil]','<sil>']])
def test_effective_source_filter_before_group_snapshot_and_cache(texts):
    from twobyteasr.subtitle_rules.cue_cleanup import prepare_effective_sources
    from twobyteasr.recognition.caption_arbitration import placeholder_transcript
    rows=[row(i+1,text,i*15,i*15+12.905) for i,text in enumerate(texts)]
    original=copy.deepcopy(rows)
    effective=prepare_effective_sources(rows,speech_regions=[])
    expected=[r for r in original if not placeholder_transcript(r.text)]
    assert [(r.segment_id,r.text) for r in effective]==[(r.segment_id,r.text) for r in expected]
    assert [r.text for r in original]==texts


@pytest.mark.parametrize('marker,speech,no_speech', [('<sil>',[],True),('<sil>',[{'start':0,'end':2}],False),
    ('<unk>',[],False),('<blank>',[],True)])
def test_all_placeholder_input_never_produces_success(marker,speech,no_speech):
    from twobyteasr.subtitle_rules.cue_cleanup import prepare_effective_sources
    from twobyteasr.recognition.transcript_delivery import NoSpeechDetected
    with pytest.raises(RuntimeError) as caught:
        prepare_effective_sources([row(1,marker,0,12.905)],speech_regions=speech)
    assert isinstance(caught.value,NoSpeechDetected)==no_speech


def test_long_silence_group_timing_save_reopen_export(tmp_path):
    from twobyteasr.subtitle_rules.cue_cleanup import prepare_effective_sources
    from twobyteasr.subtitle_rules.timing import build_local_source_cues, repair_overlong_cues_from_source
    from twobyteasr.projects.studio_project import create_studio_outputs,load_project
    from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts,SubtitleExportOptions
    rows=[row(1,'啊',203,204),row(2,'<sil>',205.06,217.965),row(3,'继续正常讲话',219,221)]
    with activate_runtime_context(RuntimeContext(),legacy=core):
        effective=prepare_effective_sources(rows,speech_regions=[{'start':203,'end':204},{'start':219,'end':221}])
        cues=build_local_source_cues(effective)
        cues=repair_overlong_cues_from_source(cues,effective)
        assert validate_grouping_result(effective,cues)
        media=tmp_path/'media.mp4';media.write_bytes(b'fixture')
        outputs=create_studio_outputs(str(media),cues,txt_path='',segments=effective,
            target_project_path=tmp_path/'saved/project.2byteproj')
    reopened=load_project(outputs['project'])
    artifacts=export_subtitle_artifacts(reopened,tmp_path/'export','subtitles',SubtitleExportOptions(frozenset({'srt','ass','txt','json'})))
    assert len(artifacts)==4
    for artifact in artifacts:
        text=artifact.path.read_text('utf8')
        assert '<sil>' not in text and '<s' not in text and 'l>' not in text
        assert '继续正常讲话' in text


@pytest.mark.parametrize('text',['<sil>','<unk>','<sil> 是用户的正文','x < y','<code>'])
def test_existing_manual_placeholder_is_preserved_by_project_roundtrip(tmp_path,text):
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project,load_project
    project=SubtitleProject(media=StudioMedia(path='fixture.mp4'),cues=[StudioCue('manual',0,1000,text)])
    target=save_project(project,tmp_path/'manual.2byteproj')
    reopened=load_project(target)
    assert reopened.cues[0].text==text
    from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts,SubtitleExportOptions
    artifact=export_subtitle_artifacts(reopened,tmp_path/'exports','manual',SubtitleExportOptions())[0]
    assert text in artifact.path.read_text('utf8')


def test_local_no_key_and_cloud_failure_use_the_same_effective_sources(monkeypatch):
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    rows=[row(1,'先看左边，再看右边然后继续向前',0,4),row(2,'<sil>',205.06,217.965)]
    context=RuntimeContext();context.task_language='zh';context.requested_language='zh'
    with activate_runtime_context(context,legacy=core):
        local=grouping.group_subtitles(rows,use_ai=False)
        assert all('<' not in c.text for c in local)
        calls=[]
        def fail(*a,**k):
            calls.append(True)
            raise RuntimeError('controlled cloud connection failure')
        monkeypatch.setattr(grouping,'provider_for_stage',lambda *a,**k:SimpleNamespace(complete=fail))
        monkeypatch.setattr(grouping,'GROUPING_API_RETRIES',1)
        monkeypatch.setattr(grouping,'SECOND_PASS_GROUP_VALIDATION',False)
        snapshot=resolve_provider_snapshot({'models':{'ai_service':'custom','provider_profiles':{
            'custom':{'base_url':'http://127.0.0.1:1/v1','model':'offline-test'}}}})
        fallback=grouping.call_grouping_api(rows,provider_snapshot=snapshot,_packed=True)
        assert calls and fallback.origin=='fallback'
        assert ''.join(c.text for c in fallback)==rows[0].text
        assert validate_grouping_result(rows[:1],fallback)
    assert rows[1].text=='<sil>'  # raw recognition evidence was not mutated


@pytest.mark.parametrize('text,reuse',[('<sil>',False),('<unk>',False),('正常正文',True)])
def test_only_polluted_terminal_checkpoints_are_rejected(text,reuse,monkeypatch):
    from twobyteasr.recognition import delivery_checkpoint
    payload={'arguments':{'segments':[{'text':text}]}}
    context=RuntimeContext();context.resume=True
    context.task_journal=SimpleNamespace(load_artifact=lambda *a:payload)
    monkeypatch.setattr(delivery_checkpoint,'dependency',lambda context:{'fixture':True})
    assert (delivery_checkpoint.load(context) is payload)==reuse


def test_restoration_keeps_opening_punctuation_inside_one_source_row():
    rows=[row(1,'你好， “世界”',0,2)]
    cues=[cue(1,'你好',0,1),cue(2,'世界',1,2)]
    assert restore_source_text(rows,cues)
    assert [c.text for c in cues]==['你好，','“世界”']
    assert validate_grouping_result(rows,cues)
