"""Expose returned public API evidence, never private CLI event envelopes."""
from datetime import datetime, timezone
from urllib.parse import urlsplit

LIMIT = 8000

def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def observe(diagnostics, kind, value, *, api_key=''):
    """Called only at actual request/packet boundaries; no synthetic activity."""
    from .provider_diagnostics import redact_diagnostics
    diagnostics['last_activity_at'] = timestamp()
    if kind == 'request_started':
        diagnostics.update(request_sent=True, request_sent_at=diagnostics['last_activity_at'])
    elif kind in {'delta', 'thinking', 'reasoning_summary'}:
        text = str(value or '')
        if kind == 'delta':
            diagnostics['returned_content_chars'] = diagnostics.get('returned_content_chars', 0) + len(text)
            return
        official = (urlsplit(str(diagnostics.get('endpoint') or diagnostics.get('base_url') or '')).hostname or '').lower() == 'api.deepseek.com'
        # A CLI's internal thinking event is not public API output. For unknown
        # relays, only explicit public summary fields are displayed; count-only
        # evidence records other returned reasoning fields without assuming a
        # provider identity grants permission or support.
        if kind == 'thinking' and not official:
            diagnostics['returned_reasoning_field_chars'] = diagnostics.get('returned_reasoning_field_chars', 0) + len(text)
            return
        text = text.replace(api_key, '[REDACTED]') if api_key else text
        text = redact_diagnostics(text)
        previous = diagnostics.get('public_reasoning', '')
        diagnostics['public_reasoning'] = (previous + text)[:LIMIT]
        diagnostics['public_reasoning_chars'] = diagnostics.get('public_reasoning_chars', 0) + len(text)
        diagnostics['public_reasoning_truncated'] = diagnostics['public_reasoning_chars'] > LIMIT
        diagnostics['public_reasoning_source'] = ('DeepSeek API message.reasoning_content' if kind == 'thinking' else 'API public reasoning summary')

def summary(diagnostics):
    usage = {k: diagnostics[k] for k in ('prompt_tokens','completion_tokens','total_tokens','reasoning_tokens') if diagnostics.get(k) is not None}
    return dict(request_sent=bool(diagnostics.get('request_sent')), request_sent_at=diagnostics.get('request_sent_at'),
        last_activity_at=diagnostics.get('last_activity_at'), provider=diagnostics.get('provider'),
        model=diagnostics.get('model'), response_model=diagnostics.get('response_model'),
        endpoint=diagnostics.get('endpoint'), thinking_mode=diagnostics.get('thinking_mode','provider_default'),
        thinking_sent=diagnostics.get('thinking_sent'), reported_usage=usage or None,
        returned_content_chars=diagnostics.get('returned_content_chars',diagnostics.get('message_content_length',0)),
        public_reasoning_chars=diagnostics.get('public_reasoning_chars',0),
        public_reasoning_source=diagnostics.get('public_reasoning_source'),
        reasoning_notice=('已返回可展示的推理内容' if diagnostics.get('public_reasoning') else '此接口未返回可展示的推理内容'))

def message_evidence(packet, diagnostics, *, api_key=''):
    """A validated HTTP JSON message, separate from authored final content."""
    from .llm_adapter import _message_field_text
    message = ((packet.get('choices') or [{}])[0]).get('message') or {}
    diagnostics['response_model'] = packet.get('model')
    observe(diagnostics,'delta',_message_field_text(message,'content'),api_key=api_key)
    reasoning = _message_field_text(message,'reasoning_content') or _message_field_text(message,'reasoning')
    if reasoning: observe(diagnostics,'thinking',reasoning,api_key=api_key)
    public_summary = _message_field_text(message,'reasoning_summary')
    if public_summary: observe(diagnostics,'reasoning_summary',public_summary,api_key=api_key)
    diagnostics.update(summary(diagnostics))
