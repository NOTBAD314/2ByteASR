from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioSpeaker, StudioCue
from twobyteasr.projects.low_share_speakers import apply_low_share_policy
from twobyteasr.recognition.speaker_recovery import candidate_snapshot, apply_candidate_role


def project(count=2000):
    cues = [StudioCue(str(i), i*1500, i*1500+1000, '字幕', speaker_id='minor' if i<3 else 'major') for i in range(count)]
    p = SubtitleProject(StudioMedia('fixture.mp4', duration_ms=count*1500), cues=cues,
                        speakers=[StudioSpeaker('major'), StudioSpeaker('minor')])
    p.generation_metadata['speaker_recovery'] = candidate_snapshot([
        dict(speaker=c.speaker_id, start=c.start_ms/1000, end=c.end_ms/1000, text=c.text) for c in cues], source='filetrans')
    return p


def test_joint_thresholds_and_recovery_respect_manual_choice():
    p = project()
    q = apply_low_share_policy(p)
    assert len(p.cues) == 2000 and len(q.cues) == 1997
    assert q.generation_metadata['speaker_recovery']['roles']['minor'] == 'ignore'
    restored = apply_candidate_role(q, q.generation_metadata['speaker_recovery'], 'minor', 'unconfirmed')
    assert len(restored.cues) == 2000
    assert apply_low_share_policy(restored) is None
    assert restored.generation_metadata['speaker_recovery']['role_decisions']['minor'] == 'manual'


def test_short_video_or_confirmed_speaker_or_duration_does_not_auto_ignore():
    short, host, manual = project(30), project(), project()
    host.speakers[1].is_host = True
    manual.generation_metadata['speaker_recovery']['role_decisions'] = {'minor': 'manual'}
    for p in [short, host, manual]:
        assert not apply_low_share_policy(p).generation_metadata['speaker_organization']['low_share_policy']['ignored']
    p = project()
    for c in p.cues[:3]: c.end_ms = c.start_ms+8000
    assert not apply_low_share_policy(p).generation_metadata['speaker_organization']['low_share_policy']['ignored']


def test_final_merged_speaker_is_counted_as_one_logical_identity():
    p = project()
    # Many original labels can refer to one already unified logical speaker.
    for c in p.cues: c.speaker_id = 'major'
    assert not apply_low_share_policy(p).generation_metadata['speaker_organization']['low_share_policy']['ignored']
