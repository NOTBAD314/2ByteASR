"""One task-owned source-language choice; observations never mutate manual input."""
from __future__ import annotations
import copy
from ..subtitle_rules.language_rules import normalize_language,resolve_task_language

VERSION='manual-first-v1'


def mode_for(requested):
    return 'auto' if str(requested or '').strip().lower()=='auto' else 'manual'


def initialise(context):
    requested=normalize_language(context.requested_language)
    if requested=='auto' and mode_for(context.requested_language)=='manual':
        if str(context.requested_language or '').strip():raise ValueError('不支持的手动源语言')
        requested='zh'
    context.language_mode=mode_for(requested)
    if context.language_mode=='manual':context.task_language=requested
    context.language_decision=dict(version=VERSION,mode=context.language_mode,
        requested_language=context.requested_language or 'zh',requested_locale=str(context.requested_language or 'zh'),
        adopted_language=context.task_language or None,decision_basis='user_selection' if context.language_mode=='manual' else 'pending_evidence',
        observed_text_language=None,provider_declared_language=None,acoustic_language=None,acoustic_language_verified=False)


def bind(context,texts,*,asr_detected=None):
    language,evidence=resolve_task_language(context.requested_language,texts,asr_detected=asr_detected)
    context.task_language=language;context.language_mode=evidence['mode']
    context.language_evidence={**context.language_evidence,**evidence}
    if not context.language_evidence.get('remote_language_control'):
        from ..providers.asr_language_control import policy
        primary=(context.asr_settings_snapshot.get('models') or {}).get('primary_asr_backend')
        if primary and primary!='api':
            # The configured cloud endpoint can exist while the chosen primary
            # is local. It is not evidence that this transcript used that API.
            control=dict(version='source-control-v1',primary_backend=primary,route='local',
                user_requested_language=context.requested_language,processing_language_mode=context.language_mode,
                language_control='not_used',request_language=None,parameter_sent=False,
                remote_constraint_accepted=None,acoustic_language_verified=False,phase='no_cloud_primary')
        else:
            control={**policy(context.asr_endpoint_snapshot,context.requested_language),
                'phase':'capability_only_no_new_request_observed','parameter_sent':False}
        context.language_evidence['remote_language_control']=control
    evidence['remote_language_control']=context.language_evidence['remote_language_control']
    context.language_decision={key:copy.deepcopy(evidence.get(key)) for key in (
        'mode','requested_language','requested_locale','adopted_language','decision_basis',
        'observed_text_language','provider_declared_language','acoustic_language','acoustic_language_verified','uncertain','remote_language_control')}
    context.language_decision['version']=VERSION
    return language,context.language_evidence


def metadata(context):
    if not context.language_decision:initialise(context)
    return dict(code=context.task_language or context.language_decision.get('adopted_language'),
        requested=context.requested_language,mode=context.language_mode,decision=copy.deepcopy(context.language_decision),
        evidence=copy.deepcopy(context.language_evidence))


def validate_rows(payload,audio_seconds):
    """Language preference does not relax the parsed transcript contract."""
    import math
    from ..providers.qwen31_asr import ASRProtocolError
    rows=payload.get('segments')
    if not isinstance(rows,list):raise ASRProtocolError('主力转写候选结构损坏','parse_failed')
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('text'),str) or not row['text'].strip():
            raise ASRProtocolError('主力转写候选缺少有效文字','parse_failed')
        if any(isinstance(row.get(k),bool) or not isinstance(row.get(k),(int,float)) or not math.isfinite(row[k]) for k in ('start','end')):
            raise ASRProtocolError('主力转写候选时间戳非法','parse_failed')
        if not 0<=row['start']<row['end']<=audio_seconds+.001:
            raise ASRProtocolError('主力转写候选时间超出输入音频','parse_failed')
    return rows


def migrate_project(project):
    """A saved explicit request outranks an old overwritten adopted label."""
    value=project.generation_metadata.get('language')
    if not isinstance(value,dict) or not value.get('requested'):return
    requested=value['requested'];mode=mode_for(requested)
    if mode=='manual':
        code=normalize_language(requested)
        if code=='auto':return
        if value.get('code') not in (None,code):value.setdefault('previous_adopted_language',value.get('code'))
        value['code']=code
    value['mode']=mode
