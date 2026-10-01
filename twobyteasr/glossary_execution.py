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
    cached = any(e.get('stage') == '恢复检查点' and '成功缓存' in str(e.get('payload','')) for e in events)
    fresh = [e for e in events if e.get('kind') == 'page_result' and isinstance(e.get('payload'),dict)
             and e['payload'].get('status') == 200]
    methods = (['缓存复用'] if cached else []) + (['本次联网解析'] if fresh else [])
    return dict(model_calls=len(calls), methods=methods,
                actual_models=sorted({e.get('identity',{}).get('model','') for e in calls}),
                model_stages=sorted({e.get('stage','') for e in calls}))


def summary_text(result):
    value = execution_summary(result)
    calls = value.get('model_calls')
    model = '模型调用记录未知' if calls is None else ('本次未调用模型' if calls == 0 else f"本次模型调用 {calls} 次："+'、'.join(value.get('actual_models',[])))
    return ' · '.join([*value.get('methods',[]),model])


def timestamp_text(value):
    if isinstance(value,(int,float)):
        return datetime.fromtimestamp(value).isoformat(timespec='seconds')
    return str(value or '未知')
