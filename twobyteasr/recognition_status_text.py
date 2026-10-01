"""Presentation of structured worker events through the shared UI catalog."""
from .i18n import tr, join_text


def recognition_event_text(kind, payload):
    if kind == 'speaker_progress':
        state = {
            'loading': '正在加载说话人模型', 'loaded': '模型已加载，开始分析',
            'analyzing': '正在分析说话人', 'analyzed': '音频分析完成',
            'merging': '正在匹配字幕标签', 'completed': '说话人结果已合并，身份待确认',
            'failed': '分析失败，文字已保留',
        }.get(payload.get('state'), '准备中')
        parts = [tr('Nemotron · {state}', state=tr(state))]
        if 'processed_end' in payload:
            parts.append(tr('已分析 {start:.1f}–{end:.1f} 秒',
                start=payload.get('processed_start', 0), end=payload['processed_end']))
        if payload.get('cache_hit'):
            parts.append(tr('复用匹配音频的缓存'))
        return join_text(parts)
    if kind == 'asr_wait':
        return tr(str(payload.get('message') or 'API请求进行中，等待真实返回'))
    if kind == 'asr_evidence_delta':
        rows = payload.get('rows') or []
        return tr('FireRed 临时证据：{done}/{total} 批 · 音频 {start:.1f}–{end:.1f} 秒 · {text}',
            done=payload.get('completed_chunks', 0), total=payload.get('total_chunks', 0),
            start=payload.get('processed_start', 0), end=payload.get('processed_end', 0),
            text=' / '.join(str(row.get('text', ''))[:100] for row in rows[-2:]))
    if kind == 'asr_progress':
        parts = [tr('API 返回：{done}/{total} 批 · 临时转写 {count} 条',
            done=payload.get('completed_batches', 0), total=payload.get('total_batches', 0),
            count=payload.get('cue_count', 0))]
        ranges = payload.get('processed_ranges_ms') or []
        if ranges:
            parts.append(tr('最近音频 {start:.1f}–{end:.1f} 秒', start=ranges[-1][0]/1000, end=ranges[-1][1]/1000))
        return join_text(parts)
    state = {'loading': '正在加载模型', 'loaded': '模型加载完成，等待推理结果',
        'model_dtype': '设备与精度已确认', 'concurrency_reduced': '已降低批次并发，重试当前批次',
    }.get(payload.get('worker_state'), '准备中')
    return tr('FireRed · {state}', state=tr(state))
