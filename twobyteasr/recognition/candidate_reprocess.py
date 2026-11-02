"""Explicit, input-bound reuse of saved candidate text; no provider calls."""
from __future__ import annotations
import copy


def policy_for(project, region, language, *, confirmed):
    from .transcript_acceptance import digest
    from ..playback.audio_graph import capture_audio_graph
    rows = copy.deepcopy(region.get('raw_rows') or [])
    if not rows:
        state = project.generation_metadata.get('transcript_acceptance') or {}
        rows = [copy.deepcopy(r) for r in state.get('candidate_rows', [])
                if r['end'] > region['start'] and r['start'] < region['end']]
    if not rows:
        raise ValueError('没有保存此范围的候选原文；请提供原始缓存，或明确重新识别此范围。')
    state = project.generation_metadata.get('transcript_acceptance') or {}
    identity = state.get('identity') or {}
    checksum = region.get('pcm_sha256')
    if not checksum and abs(region['start']) <= .001 and abs(region['end']*16000-identity.get('samples', -1)) <= 16:
        checksum = identity.get('pcm_sha256')
    if not checksum:
        raise ValueError('此旧范围没有可核对的输入音频摘要；请提供原缓存，或重新识别此范围。')
    original_scope=[region['start'],region['end']]
    from .range_recognition import recognition_window
    a,b,_=recognition_window(project,round(region['start']*1000),round(region['end']*1000))
    scope=[a/1000,b/1000]
    expanded=any(abs(x-y)>.001 for x,y in zip(scope,original_scope))
    reference=copy.deepcopy(state.get('input_pcm') or {})
    full_checksum=reference.get('pcm_sha256') or identity.get('pcm_sha256')
    pcm_scope=list(scope);frame_tail=None
    if reference:
        pcm_start=float(reference.get('range_origin_ms') or 0)/1000
        pcm_end=pcm_start+int(reference.get('samples') or 0)/16000
        if scope[0]<pcm_start-.001:raise ValueError('恢复范围早于可核对原PCM；请重新核对范围。')
        if scope[1]>pcm_end+.001:
            # A video's last frame may extend past its last audio sample.
            # Keep the replacement clock, but never pad or invent input PCM.
            frame=1/max(1.,float(getattr(project.media,'fps',0) or 25))
            if scope[1]-pcm_end>frame+.001:raise ValueError('恢复范围超出原PCM，不能复用该范围。')
            pcm_scope[1]=pcm_end;frame_tail=frame
    if expanded:
        if not reference or not full_checksum:
            raise ValueError('字幕边界需要更宽的输入范围，但缺少可验证原PCM；请恢复原缓存或重新识别此范围。')
        rows=[copy.deepcopy(r) for r in state.get('candidate_rows',rows) if r['end']>scope[0] and r['start']<scope[1]]
    graph_digest = digest(capture_audio_graph(project))
    if state.get('audio_graph_digest') and graph_digest != state['audio_graph_digest']:
        raise ValueError('输入音轨或混音已变化，不能复用旧候选。')
    from .language_decision import mode_for
    previous=(project.generation_metadata.get('language') or {}).get('requested') or region.get('requested_language')
    from ..subtitle_rules.language_rules import normalize_language
    kept_manual=mode_for(previous)=='manual' and normalize_language(previous)==normalize_language(language)
    return dict(conflict_id=region['id'], requested_language=language,kept_manual_choice=kept_manual,
        reuse_candidates=True, explicit_range=True, confirmed_after_listening=bool(confirmed),
        candidate_rows=rows, candidate_rows_sha256=digest(rows),
        candidate_scope=scope,pcm_scope=pcm_scope,frame_tail_tolerance_seconds=frame_tail, pcm_sha256=None if expanded else checksum,full_pcm_sha256=full_checksum if expanded else None,
        audio_graph_digest=graph_digest, input_pcm=copy.deepcopy(state.get('input_pcm') or {}),
        source_identities=copy.deepcopy(state.get('source_identities') or {}),
        candidate_model=(project.generation_metadata.get('models') or {}).get('qwen_asr_api_model'))


def replay_rows(audio, context):
    from .transcript_acceptance import digest
    from .alignment_audio import pcm_digest
    policy = context.recognition_snapshot.get('language_recovery_policy') or {}
    rows = copy.deepcopy(policy.get('candidate_rows') or [])
    if not (policy.get('confirmed_after_listening') or policy.get('kept_manual_choice')) or not rows or digest(rows) != policy.get('candidate_rows_sha256'):
        raise ValueError('候选尚未明确核对，或候选内容已变化。')
    if digest(context.recognition_snapshot.get('audio_graph') or {}) != policy.get('audio_graph_digest'):
        raise ValueError('输入音轨或混音已变化，不能复用旧候选。')
    start, end = policy['candidate_scope']
    window = context.recognition_snapshot.get('range_ms') or [round(start*1000), round(end*1000)]
    if abs(window[0]/1000-start) > .001 or abs(window[1]/1000-end) > .001:
        raise ValueError('恢复范围已变化，请重新核对相应候选。')
    if policy.get('pcm_sha256') and pcm_digest(audio) != policy['pcm_sha256']:
        raise ValueError('对应输入音频已变化，不能复用旧候选。')
    for row in rows:
        row['start'], row['end'] = max(0., row['start']-start), min(len(audio)/16000, row['end']-start)
        for key in ('tokens', 'words'):
            shifted = []
            for word in row.get(key) or []:
                if not isinstance(word, dict):
                    raise ValueError('候选词时间格式无法核对，请重新识别此范围。')
                word = copy.deepcopy(word)
                if 'start_ms' in word:
                    word['start_ms'] = round(word['start_ms']-start*1000)
                    word['end_ms'] = round(word['end_ms']-start*1000)
                elif 'start' in word and 'end' in word:
                    word['start'], word['end'] = word['start']-start, word['end']-start
                shifted.append(word)
            if key in row:
                row[key] = shifted
        row.pop('asr_language_receipt', None)
        row.pop('transcript_acceptance_receipt', None)
        row['reprocessed_source'] = 'saved_original_candidate'
    from .cache import record_run_event
    record_run_event('asr_candidate_reused', reason='kept_manual_choice' if policy.get('kept_manual_choice') and not policy.get('confirmed_after_listening') else 'explicit_review_after_listening', candidate_count=len(rows),
        remote_request_started=False, remote_task_ids=list(dict.fromkeys(
            (r.get('asr_language_receipt') or {}).get('remote_task_id') for r in policy['candidate_rows']
            if (r.get('asr_language_receipt') or {}).get('remote_task_id'))))
    return rows
