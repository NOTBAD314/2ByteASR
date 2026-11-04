import copy,json
from types import SimpleNamespace
import pytest
from twobyteasr.caption_design.caption_components import compose
from twobyteasr.caption_design.theme_motion import validate_motion_spec
from twobyteasr.caption_design.design_progress import PublicProgress,update_phase,status_text
from twobyteasr.caption_design.candidate_attempt import CandidateAttempt,primary_action,revision


def test_static_noita_source_is_byte_identical_across_six_effect_choices():
    base=compose({'version':8})
    for entry in ('alchemy','mineral','sigil'):
        for exit in ('alchemy','mineral','sigil'):
            source=compose(dict(version=9,entryEffect=entry,exitEffect=exit))
            for field in ('cueHtml','cueCss','appearance','stageHtml','stageCss'):
                assert source.get(field)==base.get(field)
            validate_motion_spec(source['motionSpec'])
            pixels=[t for t in source['motionSpec']['tracks'] if 'pixels' in t]
            assert [t['pixels']['mode'] for t in pixels]==[entry,exit]
            assert all(t['selector']=='.nt-read' for t in pixels)


@pytest.mark.parametrize('key,value',[('seed',-1),('blockSize',float('nan')),('quality','secret'),('entryEffect','wipe'),('intensity',float('inf'))])
def test_invalid_pixel_parameters_fail_closed(key,value):
    with pytest.raises(Exception):compose({'version':9,key:value})


@pytest.mark.parametrize('fps',[24,30])
def test_short_noita_finishes_before_last_encoded_frame(fps):
    # Production MotionSpec2 compresses a 1.5s cue's resolve window to 100ms.
    source=compose(dict(version=9,entryEffect='alchemy',exitEffect='sigil'))
    last_frame_ms=(int(1.5*fps)-1)*1000/fps
    for track in source['motionSpec']['tracks']:
        if track['phase']=='resolve':
            assert 1400+100*track['end']<last_frame_ms
            assert track.get('start',0)<=track['end']


def test_local_liveness_transport_and_body_are_distinct_and_saved(tmp_path):
    progress=PublicProgress('one','实现',300,path=tmp_path/'partial.txt')
    progress.stream('process_alive','');progress.emit()
    assert progress.phase['last_response_monotonic'] is None
    progress.stream('transport',{'bytes':37})
    assert progress.phase['transport_bytes']==37 and progress.phase['output_chars']==0
    progress.stream('heartbeat','')
    assert progress.phase['last_output_monotonic'] is None
    body='===HTML===\n<p>真正正文</p>\n===CSS===\np{}\n===END token===\n'
    progress.stream('delta',body);progress.finish('failed')
    assert (tmp_path/'partial.txt').read_text('utf8')==body
    assert progress.phase['complete_sections']==2 and progress.phase['artifact_revision']
    a=status_text(progress.phase,progress.phase['finished_monotonic'])
    assert a==status_text(progress.phase,progress.phase['finished_monotonic']+100)
    assert all(label in a for label in ('本地：','传输：','作品：','制作：','远端内部进度不可见'))


def test_action_uses_artifact_state_and_revision_receipts(tmp_path):
    c=dict(id='A',technical_status='failed',technical_errors=[{'category':'motion_structure'}])
    assert primary_action(c)[0]=='continue'
    c['source_recovery']={'missing_sections':['CSS']}
    assert primary_action(c)[0]=='implementation'
    c.update(authored_theme={'cueHtml':'source'},technical_errors=[{'category':'render_timeout'}])
    assert primary_action(c)[0]=='preview'
    c.update(technical_status='passed',motion_preview={'status':'motion_ready'},preview_integrity_verified=True)
    assert primary_action(c)[0]=='adopt'
    attempt=CandidateAttempt(tmp_path,'job',c,'preview');original=revision(c)
    c['authored_theme']['cueHtml']='changed'
    assert revision(c)!=original
    attempt.event('cancelled','user stopped')
    receipt=json.loads(attempt.path.read_text('utf8'))
    assert receipt['artifact_revision']==original and receipt['finished_at']>=receipt['accepted_at']


def test_track_origin_normalizes_locally_and_preserves_original(tmp_path):
    from scripts.author_balatro_candidates import candidates
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger,accept_authored_set
    from twobyteasr.caption_design.authored_repair import collect_issues
    data={'candidates':candidates()};track=data['candidates'][0]['generated_source']['motionSpec']['tracks'][0]
    track.pop('transformOrigin',None)
    track['from'].pop('transformOrigin',None);track['to'].pop('transformOrigin',None)
    track['transformOrigin']='50% 50%';original=copy.deepcopy(data)
    ledger=ThemeLedger(tmp_path,'Balatro')
    issues=collect_issues(data,ledger)
    assert any(i['path']=='candidates[0].generated_source.motionSpec' and 'transformOrigin' in str(i) for i in issues)
    def forbidden(*a,**k):raise AssertionError('exact relocation must not call model')
    result=accept_authored_set(data,ledger,'test','test',technical_repair=forbidden,candidate_regenerate=forbidden)
    assert data==original
    repaired=result.concepts[0]['authored_theme']['motionSpec']['tracks'][0]
    assert 'transformOrigin' not in repaired
    assert repaired['from']['transformOrigin']==repaired['to']['transformOrigin']=='50% 50%'


def test_late_cancelled_or_replaced_result_never_reaches_receive():
    from twobyteasr.caption_design.studio_theme_draft import StudioThemeDraftController
    import threading
    calls=[];cancel=threading.Event()
    controller=SimpleNamespace(operation='current',cancel_event=cancel,current=SimpleNamespace(generation=1,cue_id='A'),receive=lambda *args:calls.append(args))
    StudioThemeDraftController._candidate_finished(controller,'old',object())
    cancel.set();StudioThemeDraftController._candidate_finished(controller,'current',object())
    assert not calls
