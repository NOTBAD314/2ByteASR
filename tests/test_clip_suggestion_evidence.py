import json
from dataclasses import asdict

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, MediaAsset, VideoClip, VideoTrack
from twobyteasr.studio.studio_danmaku import DanmakuDocument, DanmakuEvent, parse_danmaku_xml
from twobyteasr.studio.studio_highlight_analyzer import LocalCandidate, analyze_highlights, discover_local_candidates
from twobyteasr.studio.highlight_evidence import prepare_evidence, local_candidate, parse_proposals, stable_id, ranked_unique
from twobyteasr.timeline.studio_edit_sequence import HighlightCandidate, sequence_of
from twobyteasr.timeline.studio_edit_commands import replace_candidates_command
from twobyteasr.media.danmaku_binding import primary_source


def project():
    return SubtitleProject(media=StudioMedia(path='recording.flv', duration_ms=900000), cues=[
        StudioCue('prior', 1000, 3000, '先正常往前走。'),
        StudioCue('setup', 200000, 205000, '如果这一次还是失败，我们就先停一下。'),
        StudioCue('core', 206000, 209000, '没想到真的成功了！'),
        StudioCue('reply', 210000, 214000, '等一下，先看看大家怎么说。'),
        StudioCue('later', 350000, 356000, '接下来我们去另一边。'),
    ])


def local_fixture():
    p = project()
    local = LocalCandidate(195000, 495000, .96, ['reaction'])
    doc = DanmakuDocument('recording.xml', [DanmakuEvent(208000+i*100, t) for i,t in enumerate(
        ['真的假的', '？？？', '哈哈哈哈', '太厉害了', '难道说'])], 209000)
    prepare_evidence(p, [local], doc)
    return p, local


def test_long_context_gets_real_dialogue_bounds_without_forced_length():
    p, local = local_fixture()
    c = local_candidate(p, local)
    assert c.clip_range == (200000, 214000)
    assert c.context_out_ms-c.context_in_ms > 300000
    assert c.key_moment_ms == 206000
    assert c.evidence_kinds == {'subtitle', 'danmaku'}
    assert not c.user_confirmed
    restored = HighlightCandidate.from_dict(c.to_dict())
    assert restored.to_dict() == c.to_dict()
    assert restored.clip_reason and restored.boundary_refs


def test_xml_only_cannot_invent_event_or_precise_cut(tmp_path):
    p = project(); p.cues = []
    xml = tmp_path/'actual.xml'
    xml.write_text('<i>'+''.join(f'<d p="{205+i/10},1">{t}</d>' for i,t in enumerate(
        ['真的假的', '？？？', '哈哈哈哈', '太厉害了', '难道说']*8))+'</i>', 'utf-8')
    result = analyze_highlights(p, mode='xml', danmaku_path=str(xml), runtime_settings={})
    assert result['candidates']
    for c in result['candidates']:
        assert c.clip_range is None
        assert c.to_dict()['recommended_range'] is None
        assert c.grade == '待确认'
        assert '抽中' not in c.title and '中计' not in c.title
        assert all(r['kind']=='danmaku' for r in c.evidence)
        assert all(r['text'] in xml.read_text('utf-8') for r in c.evidence)


def test_ai_boundaries_are_real_references_not_ambiguous_seconds():
    p, local = local_fixture()
    rows = [r for r in local.evidence_rows if r['kind']=='subtitle']
    row = dict(candidate_id=stable_id(p.media.path,local.start_ms,local.end_ms),
               title='说好失败就停，却迎来成功的回应', clip_reason='前一句准备放弃，后一句说成功了，反差有字幕依据。',
               evidence_refs=[r['id'] for r in rows[:3]],
               recommended_range=dict(start_ref=rows[0]['id'],end_ref=rows[2]['id']), key_moment_ref=rows[1]['id'])
    def parse(): return parse_proposals(json.dumps({'candidates':[row]}),p,[local])[0]
    assert parse().clip_range == (200000,214000)
    row['recommended_range']['start_ms']=200
    assert parse().clip_range is None
    row['recommended_range']={'start_ref':'made-up', 'end_ref':rows[2]['id']}
    assert parse().clip_range is None
    row['evidence_refs']=['made-up']
    c=parse()
    assert c.clip_range is None and c.origin=='local'


def test_reanalysis_keeps_manual_ranges_but_explicit_ignore_and_remove_work():
    p, local = local_fixture()
    c=local_candidate(p,local); c.status='accepted'; c.user_adjusted=True
    c.range_status='manual'; c.source_in_ms=199000; c.source_out_ms=215000
    sequence_of(p).clip_candidates=[c]
    fresh=local_candidate(p,local)
    command=replace_candidates_command(p,[fresh],preserve_decisions=True); command.redo()
    current=sequence_of(p).clip_candidates[0]
    assert current.status=='accepted' and current.clip_range==(199000,215000)
    current=HighlightCandidate.from_dict(current.to_dict()); current.status='ignored'
    ignore=replace_candidates_command(p,[current]); ignore.redo()
    assert sequence_of(p).clip_candidates[0].status=='ignored'
    ignore.undo()
    assert sequence_of(p).clip_candidates[0].status=='accepted'
    missing=replace_candidates_command(p,[],preserve_decisions=True); missing.redo()
    assert sequence_of(p).clip_candidates[0].clip_range==(199000,215000)


def test_deleted_first_recording_is_not_analysis_source():
    p=project()
    p.media_pool=[MediaAsset('first','recording.flv',duration_ms=900000), MediaAsset('last','last.flv',duration_ms=600000)]
    p.video_tracks=[VideoTrack(id='V1',name='Video',clips=[VideoClip(id='v',asset_id='last',source_in_ms=0,source_out_ms=600000,
                                                     timeline_in_ms=0,timeline_out_ms=600000)])]
    assert primary_source(p)=='last.flv'


def test_duplicate_spam_and_empty_data_do_not_force_recommendations(tmp_path):
    p=project(); p.cues=[]
    doc=DanmakuDocument('spam.xml',[DanmakuEvent(210000+i,'？？？') for i in range(900)],211000)
    assert discover_local_candidates(p,doc)==[]
    assert analyze_highlights(p,mode='subtitles',runtime_settings={})['candidates']==[]
    bad=tmp_path/'nan.xml'; bad.write_text('<i><d p="nan">bad</d><d p="inf">bad</d></i>')
    assert parse_danmaku_xml(bad).count==0
    cancelled=tmp_path/'cancel.xml'; cancelled.write_text('<i><d p="1">hello</d></i>')
    import pytest
    with pytest.raises(RuntimeError, match='取消'):
        parse_danmaku_xml(cancelled,cancel_check=lambda:True)


def test_old_caption_overlap_cannot_become_evidence_for_a_new_recording():
    from twobyteasr.studio.highlight_evidence import source_project
    from twobyteasr.timeline.studio_edit_sequence import VideoSegment
    p=project();p.render_settings['_cue_domain']='timeline'
    p.media_pool=[MediaAsset('last','last.flv',duration_ms=600000)]
    p.video_tracks=[VideoTrack(id='V1',name='Video',clips=[VideoClip(id='v',asset_id='last',source_in_ms=0,source_out_ms=600000,
                                                       timeline_in_ms=0,timeline_out_ms=600000)])]
    sequence_of(p).segments=[VideoSegment('v','last.flv',0,600000,0,600000)]
    p.studio_state['caption_timeline']={'instances':{c.id:{'source_path':'recording.flv'} for c in p.cues}}
    assert source_project(p).cues==[]
    # A receipt for the retained source is admitted, without borrowing other speech.
    p.studio_state['caption_timeline']['instances']['core']={'source_spans':[{'source_path':'last.flv'}]}
    assert [c.id for c in source_project(p).cues]==['core']
