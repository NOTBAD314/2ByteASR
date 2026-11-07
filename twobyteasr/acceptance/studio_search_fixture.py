"""Deterministic, anonymous report-scale input. Never reads user projects."""
from ..projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from ..subtitle_rules import subtitle_translation as st


def make_project(count=5555, terms=300, evidence_words=24, term_shape='disjoint'):
    p = SubtitleProject(StudioMedia('anonymous-1080p60-vp9.webm', duration_ms=18325000),
        speakers=[StudioSpeaker(f'S{i:02}', f'说话人{i+1}') for i in range(19)],
        cues=[StudioCue(str(i), i*3300, i*3300+2800,
            f'匿名の字幕 {i} 勇者が町へ戻ります', speaker_id=f'S{i%19:02}') for i in range(count)])
    p.validate()
    p.generation_metadata['language'] = {'code': 'ja'}
    policy = dict(enabled=True, selected_ids=['sample'], libraries=[dict(id='sample', name='脱敏词库',
        source_language='ja', target_language='zh-Hans', terms=[dict(source=f'用語{i:05}', target=f'译名{i}', aliases=[]) for i in range(terms)])])
    p.generation_metadata['translation_terminology'] = policy
    if term_shape=='shared-alias':
        for term in policy['libraries'][0]['terms']:term['aliases']=['勇者']
    records, render = {}, {}
    for i, cue in enumerate(p.cues[:-2]):
        text = ('待替换名' if i in (400,2777) else '翻译')+f' {i} 勇者返回城镇'
        record = st._record(text, cue.text if i%11 and i not in (400,2777) else '更早的原文',
            origin=st.ORIGIN_MANUAL if i%7==0 else st.ORIGIN_AI,
            terminology_version='old-policy' if i%13==0 else '')
        records[cue.id], render[cue.id] = record, text
    for i in range(8):
        records[f'orphan-{i}'] = st._record('已删除字幕的旧译文', '旧原文', origin=st.ORIGIN_AI)
    p.generation_metadata.update(translation_records=dict(version=1,target='zh-Hans',records=records,history=[]),translations=render)
    # Independent dictionaries model real word evidence, without repeated refs.
    p.asr_evidence = {f'segment:{i}': dict(text='脱敏识别证据', words=[dict(text='ことば', start=i*3.3+j*.04,
        end=i*3.3+j*.04+.03, probability=.96) for j in range(evidence_words)]) for i in range(count)}
    return p
