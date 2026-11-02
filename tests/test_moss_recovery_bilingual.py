"""The recovered source must continue into actual bilingual metadata/export."""
from tests.test_moss_recovery_pipeline import run_fixture,legacy_quarantine,DE,EN


def test_recovered_german_candidates_continue_into_bilingual_pipeline(tmp_path,monkeypatch):
    from twobyteasr.recognition.transcript_acceptance import pending_ranges
    from twobyteasr.recognition.candidate_reprocess import policy_for
    from twobyteasr.recognition.recognition_input import capture_recognition_snapshot
    from twobyteasr.projects.studio_project import save_project,load_project
    from twobyteasr.subtitle_rules import recognition_translation
    from tests.test_subtitle_translation import FakeProvider
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    from twobyteasr.exports.srt_codec import parse_srt
    pending,report,_=run_fixture(tmp_path,monkeypatch,DE)
    pending,report=legacy_quarantine(pending,report)
    pending.generation_metadata['subtitle_output']={'mode':'bilingual','translation_script':'zh-Hans'}
    save_project(pending,tmp_path/'fixture.2byteproj')
    region=pending_ranges(pending.generation_metadata['transcript_acceptance'])[0]
    snapshot=capture_recognition_snapshot(pending,str(tmp_path/'fixture.2byteproj'),range_ms=(0,370361))
    snapshot['language_recovery_policy']=policy_for(pending,region,'de',confirmed=True)
    def answer(payload,call_no):
        return {'items':[{'id':row['id'],'translation':
            '这是新游戏，我们现在在岛上。' if row['text'].startswith('Hier') else '我拿着地图，我们乘船出发。'}
            for row in payload['lines'] if row['translate']]}
    provider=FakeProvider(answer)
    from twobyteasr.providers import ai_providers
    monkeypatch.setattr(ai_providers,'provider_for_stage',lambda *a,**kw:provider)
    original=recognition_translation.translate_runtime_cues
    def translate(cues,context,legacy,**kw):
        context.subtitle_output='bilingual';context.translation_script='zh-Hans'
        assert context.task_language=='de'
        return original(cues,context,legacy)
    monkeypatch.setattr(recognition_translation,'translate_runtime_cues',translate)
    recovered,report,_=run_fixture(tmp_path,monkeypatch,EN,language='de',snapshot=snapshot,job='bilingual-recovery')
    assert provider.calls and recovered.cues
    assert len(recovered.generation_metadata['translations'])==len(recovered.cues)
    assert not pending_ranges(recovered.generation_metadata['transcript_acceptance'])
    assert all('new game' not in c.text for c in recovered.cues)
    saved=load_project(save_project(recovered,tmp_path/'bilingual-reopened.2byteproj'))
    exports=export_language_layers(saved,tmp_path/'export','recovered')
    assert {a.layer for a in exports.artifacts}>={'original','translation','bilingual'}
    for artifact in exports.artifacts:
        rows,errors=parse_srt(artifact.path.read_text('utf8'))
        assert not errors and len(rows)==len(saved.cues)
        text='\n'.join(r.text for r in rows)
        if artifact.layer in {'original','bilingual'}:assert 'Hier ist das neue Spiel' in text
        if artifact.layer in {'translation','bilingual'}:assert '这是新游戏' in text
