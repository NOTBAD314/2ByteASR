"""Execution provenance, independent from the configured model identity."""
from datetime import datetime
import json


def latest_checkpoint(game):
    from .glossary_build import build_task_checkpoint_path
    folder = build_task_checkpoint_path('unused').parent
    for path in sorted(folder.glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True):
        try:
            value = json.loads(path.read_text('utf8'))
            if str(value.get('game','')).casefold() == str(game).casefold():
                value.setdefault('origin_task_id', path.stem)
                return value
        except (OSError, ValueError, TypeError):
            continue
    return None


def execution_summary(result):
    explicit = result.get('execution')
    if explicit:
        return explicit
    # Historical task events are authoritative. Absence of events is unknown,
    # never a fabricated zero-call receipt.
    events = result.get('execution_events') or []
    if not events:
        return dict(model_calls=None, methods=['历史任务：执行来源记录不完整'])
    calls = [e for e in events if e.get('kind') == 'request_started']
    attempts = [e for e in events if e.get('kind') == 'request_attempt' or
                (e.get('kind') == 'request_started' and e.get('source') != 'provider')]
    sent = [e for e in events if (e.get('kind') == 'request_started' and e.get('source') == 'provider')
            or e.get('kind') in {'cli_process_started', 'request_dispatched'}]
    cached = any(e.get('stage') == '恢复检查点' and '成功缓存' in str(e.get('payload','')) for e in events)
    fresh = [e for e in events if e.get('kind') == 'page_result' and isinstance(e.get('payload'),dict)
             and e['payload'].get('status') == 200]
    methods = (['缓存复用'] if cached else []) + (['本次联网解析'] if fresh else [])
    return dict(model_calls=len(attempts), model_attempts=len(attempts), model_requests_sent=len(sent),
                model_success=sum(e.get('kind') == 'model_result' for e in events), methods=methods,
                actual_models=sorted({e.get('identity',{}).get('model','') for e in sent}),
                model_stages=sorted({e.get('stage','') for e in attempts}))


def summary_text(result):
    value = execution_summary(result)
    if 'model_attempts' in value:
        model = f"模型尝试 {value['model_attempts']} 次 · 实际发送 {value.get('model_requests_sent', 0)} 次 · 成功返回 {value.get('model_success', 0)} 次"
        names = value.get('actual_models') or []
        if names:
            model += '：' + '、'.join(names)
        elif value.get('model_attempts'):
            model += '；未取得实际发送回执'
        return ' · '.join([*value.get('methods', []), model])
    calls = value.get('model_calls')
    model = '模型调用记录未知' if calls is None else ('本次未调用模型' if calls == 0 else f"模型调用记录 {calls} 次（实际发送与完成回执未记录）："+'、'.join(value.get('actual_models',[])))
    return ' · '.join([*value.get('methods',[]),model])


def timestamp_text(value):
    if isinstance(value,(int,float)):
        return datetime.fromtimestamp(value).isoformat(timespec='seconds')
    return str(value or '未知')
