"""Byte/line/event/body boundaries for Chat Completions SSE.

Only a completed content stream reaches the structured-output validator.
Diagnostics contain identities, sizes and termination metadata, never prompts.
"""
from __future__ import annotations

from . import network_policy

import codecs
import hashlib
import json
import queue
import socket
import threading
import time


def retry_after_seconds(value):
    from email.utils import parsedate_to_datetime
    try:
        return max(0., float(value))
    except (TypeError, ValueError):
        try:return max(0., parsedate_to_datetime(value).timestamp()-time.time())
        except (TypeError, ValueError, OverflowError):return 0.


class StreamProtocolError(ValueError):
    def __init__(self, message, category='provider_protocol_error'):
        super().__init__(message)
        self.category = category


def sse_data(chunks, diagnostics, cancel_check=None):
    decoder = codecs.getincrementaldecoder('utf-8')('strict')
    pending = ''
    data = []
    total = 0
    for chunk in chunks:
        if cancel_check and cancel_check():
            raise StreamProtocolError('流式请求已取消', 'cancelled')
        if not isinstance(chunk, bytes):
            raise StreamProtocolError('SSE输入必须为原始字节')
        total += len(chunk)
        diagnostics['raw_bytes'] = total
        # Fine-grained Responses events can carry >100x framing overhead.
        # Bound wire bytes independently from the authored text body.
        if total > 32 * 1024 * 1024:
            raise StreamProtocolError('Provider流超过32MiB协议传输上限', 'response_too_large')
        try:
            pending += decoder.decode(chunk)
        except UnicodeDecodeError:
            raise StreamProtocolError('Provider流包含无效UTF-8字节', 'provider_decode_error') from None
        while '\n' in pending:
            line, pending = pending.split('\n', 1)
            line = line.rstrip('\r')
            if not line:
                if data:
                    yield '\n'.join(data)
                    data.clear()
            elif line.startswith('data:'):
                data.append(line[5:].removeprefix(' '))
            elif line.startswith(':') or line.startswith(('event:', 'id:', 'retry:')):
                continue
            else:
                raise StreamProtocolError('SSE中出现无效字段')
    try:
        pending += decoder.decode(b'', final=True)
    except UnicodeDecodeError:
        raise StreamProtocolError('Provider在UTF-8字符中间断开', 'structured_output_truncated') from None
    if pending.strip() or data:
        raise StreamProtocolError('Provider在SSE事件中间断开', 'structured_output_truncated')


def chat_body(chunks, diagnostics, emit=lambda *_: None, cancel_check=None):
    parts = []
    finish = None
    done = False
    thinking = False
    count = 0
    diagnostics.update(protocol='chat_completions_sse', decoded_type='str', event_count=0, content_chars=0)
    for data in sse_data(chunks, diagnostics, cancel_check):
        if data == '[DONE]':
            done = True
            break
        count += 1
        diagnostics['event_count'] = count
        try:
            packet = json.loads(data)
        except json.JSONDecodeError:
            raise StreamProtocolError(f'$.sse[{count}]: 无效JSON协议事件') from None
        if not isinstance(packet, dict):
            raise StreamProtocolError(f'$.sse[{count}]: expected object; received {type(packet).__name__}')
        if packet.get('error'):
            raise StreamProtocolError('Provider返回错误事件', 'provider_terminal_error')
        if isinstance(packet.get('model'),str):diagnostics['response_model']=packet['model'][:160]
        if packet.get('id'):
            request_id = str(packet['id'])
            previous = diagnostics.get('request_id')
            if previous and previous != request_id:
                raise StreamProtocolError('同一响应流出现冲突请求身份', 'conflicting_final')
            diagnostics['request_id'] = request_id[:160]
        usage = packet.get('usage')
        if isinstance(usage, dict):
            for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                diagnostics[key] = usage.get(key)
            diagnostics['reasoning_tokens'] = (usage.get('completion_tokens_details') or {}).get('reasoning_tokens')
        choices = packet.get('choices')
        if not isinstance(choices, list):
            raise StreamProtocolError('SSE事件缺少choices数组')
        if not choices:  # OpenAI may send a final usage-only chunk.
            continue
        if len(choices) != 1 or not isinstance(choices[0], dict) or choices[0].get('index', 0) != 0:
            raise StreamProtocolError('单候选请求收到冲突的choice', 'conflicting_final')
        choice = choices[0]
        delta = choice.get('delta') or {}
        if not isinstance(delta, dict):
            raise StreamProtocolError('SSE delta必须为对象')
        if delta.get('tool_calls'):
            raise StreamProtocolError('主题请求返回工具调用，缺少最终正文', 'provider_tool_request')
        for field in ('content', 'reasoning_content', 'reasoning'):
            if delta.get(field) is not None and not isinstance(delta[field], str):
                raise StreamProtocolError(f'SSE delta.{field}必须为字符串')
        reasoning = delta.get('reasoning_content') or delta.get('reasoning') or ''
        text = delta.get('content') or ''
        if finish is not None and (reasoning or text or choice.get('finish_reason')):
            raise StreamProtocolError('终态之后出现第二个正文或终态', 'conflicting_final')
        if reasoning:
            thinking = True
            diagnostics['reasoning_chars'] = diagnostics.get('reasoning_chars', 0) + len(reasoning)
            emit('thinking', reasoning)
        if text:
            if thinking:
                emit('thinking_end', '')
                thinking = False
            parts.append(text)
            diagnostics['content_chars'] += len(text)
            if diagnostics['content_chars'] > 1024 * 1024:
                raise StreamProtocolError('Provider正文超过1Mi字符上限', 'response_too_large')
            emit('delta', text)
        if choice.get('finish_reason') is not None:
            finish = choice['finish_reason']
            diagnostics['finish_reason'] = finish
            if finish != 'stop':
                category = 'structured_output_truncated' if finish in {'length', 'max_tokens'} else 'provider_terminal_error'
                raise StreamProtocolError(f'Provider未完整生成正文（finish_reason={finish}，正文{diagnostics["content_chars"]}字符）', category)
    if cancel_check and cancel_check():
        raise StreamProtocolError('流式请求已取消', 'cancelled')
    if not done or finish != 'stop':
        raise StreamProtocolError('Provider连接结束但未收到完整终态', 'structured_output_truncated')
    body = ''.join(parts)
    if not body.strip():
        raise StreamProtocolError('Provider已结束但没有正文', 'provider_no_body')
    diagnostics.update(completed=True, content_sha256=hashlib.sha256(body.encode('utf-8')).hexdigest())
    emit('final', '')
    return body


def responses_final(packet, diagnostics):
    """Validate a Responses terminal object before exposing authored source."""
    if not isinstance(packet, dict):
        raise StreamProtocolError('Responses终态必须为对象')
    if isinstance(packet.get('model'),str):diagnostics['response_model']=packet['model'][:160]
    request_id = packet.get('id')
    if request_id:
        previous = diagnostics.get('request_id')
        if previous and previous != request_id:
            raise StreamProtocolError('同一响应流出现冲突请求身份', 'conflicting_final')
        diagnostics['request_id'] = str(request_id)[:160]
    usage = packet.get('usage') or {}
    for source, target in [('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens'), ('total_tokens', 'total_tokens')]:
        diagnostics[target] = usage.get(source)
    diagnostics['reasoning_tokens'] = (usage.get('output_tokens_details') or {}).get('reasoning_tokens')
    status = packet.get('status')
    diagnostics['finish_reason'] = status
    if status != 'completed' or packet.get('error'):
        reason = (packet.get('incomplete_details') or {}).get('reason')
        category = 'structured_output_truncated' if reason == 'max_output_tokens' or status == 'incomplete' else 'provider_terminal_error'
        raise StreamProtocolError(f'Responses未完整结束（status={status}, reason={reason}）', category)
    parts = []
    for item in packet.get('output') or []:
        if item.get('type') not in {'reasoning', 'message'}:
            raise StreamProtocolError('主题请求返回工具调用，缺少独立最终正文', 'provider_tool_request')
        for block in item.get('content') or []:
            if block.get('type') == 'refusal':
                raise StreamProtocolError('Provider拒绝生成', 'provider_terminal_error')
            if block.get('type') == 'output_text':
                if not isinstance(block.get('text'), str):
                    raise StreamProtocolError('Responses正文必须为字符串')
                parts.append(block['text'])
    content = ''.join(parts) or packet.get('output_text') or ''
    if not isinstance(content, str) or not content.strip():
        raise StreamProtocolError('Responses已结束但没有正文', 'provider_no_body')
    return content


def responses_body(chunks, diagnostics, emit=lambda *_: None, cancel_check=None):
    parts = []
    summary_received=False
    diagnostics.update(protocol='responses_sse', event_count=0, content_chars=0)
    for data in sse_data(chunks, diagnostics, cancel_check):
        diagnostics['event_count'] += 1
        try:
            packet = json.loads(data)
        except json.JSONDecodeError:
            raise StreamProtocolError('无效Responses SSE事件') from None
        if not isinstance(packet, dict):
            raise StreamProtocolError('Responses SSE事件必须为对象')
        kind = packet.get('type')
        response = packet.get('response') or {}
        request_id = response.get('id')
        if request_id:
            previous = diagnostics.get('request_id')
            if previous and previous != request_id:
                raise StreamProtocolError('同一响应流出现冲突请求身份', 'conflicting_final')
            diagnostics['request_id'] = str(request_id)[:160]
        if kind == 'response.output_text.delta':
            delta = packet.get('delta')
            if not isinstance(delta, str):
                raise StreamProtocolError('Responses delta必须为字符串')
            parts.append(delta)
            diagnostics['content_chars'] += len(delta)
            if diagnostics['content_chars'] > 1024 * 1024:
                raise StreamProtocolError('Provider正文超过1Mi字符上限', 'response_too_large')
            emit('delta', delta)
        elif kind == 'response.reasoning_summary_text.delta':
            summary = packet.get('delta')
            if not isinstance(summary, str):
                raise StreamProtocolError('公开推理摘要必须为字符串')
            emit('reasoning_summary', summary)
            summary_received=True
        elif kind in {'response.completed', 'response.incomplete', 'response.failed'}:
            if not summary_received:
                emit_public_summaries(response,emit)
            content = responses_final(response, diagnostics)
            if parts and content != ''.join(parts):
                raise StreamProtocolError('Responses终态与流式正文不一致', 'conflicting_final')
            if not parts:
                emit('delta', content)
            if cancel_check and cancel_check():
                raise StreamProtocolError('流式请求已取消', 'cancelled')
            diagnostics.update(completed=True, content_chars=len(content), content_sha256=hashlib.sha256(content.encode('utf-8')).hexdigest())
            emit('final', '')
            return content
        elif kind == 'error':
            raise StreamProtocolError('Responses返回错误事件', 'provider_terminal_error')
        elif kind == 'response.output_item.added' and (packet.get('item') or {}).get('type') not in {'reasoning', 'message'}:
            raise StreamProtocolError('主题请求返回工具调用', 'provider_tool_request')
        else:
            # Only actual provider packets report activity; never manufacture
            # keep-alives or expose private reasoning content in the UI.
            emit('provider_event', str(kind))
    raise StreamProtocolError('Responses连接结束但未收到完整终态', 'structured_output_truncated')


def emit_public_summaries(packet,emit):
    for item in packet.get('output') or []:
        if item.get('type')=='reasoning':
            for block in item.get('summary') or []:
                if block.get('type')=='summary_text' and isinstance(block.get('text'),str):
                    emit('reasoning_summary',block['text'])


def request_chat(url, headers, body, timeout, diagnostics, emit, cancel_check=None, *, protocol='chat', total_deadline=None, input_budget=None):
    """One cancellable request; never retries a partially received response."""
    import requests
    # Match requests' JSON encoding at the final transport boundary. Only
    # byte count, digest and public parameters are retained, never auth headers.
    encoded=requests.Request('POST',url,json=body).prepare().body
    diagnostics['wire_payload']=dict(bytes=len(encoded),sha256=hashlib.sha256(encoded).hexdigest(),
        encoding='requests JSON, UTF-8 (ASCII escapes included)',
        parameters={key:body[key] for key in ('model','max_tokens','max_output_tokens','temperature','stream',
                    'thinking','enable_thinking','response_format') if key in body})
    if input_budget is not None:
        limit=input_budget['policy']['payload_bytes']
        input_budget['wire_payload_bytes']=len(encoded)
        input_budget['wire_payload_limit']=limit
        input_budget['wire_payload_passed']=len(encoded)<=limit
        diagnostics['wire_payload'].update(limit=limit,passed=len(encoded)<=limit)
        if len(encoded)>limit:
            input_budget.update(passed=False,dispatched=False)
            error=StreamProtocolError('最终序列化请求体超过本操作字节限额；请求未发送。','request_too_large')
            error.report=input_budget
            raise error
    events = queue.Queue(maxsize=128)
    stop = threading.Event()
    holder = {}
    seconds = float(max(timeout) if isinstance(timeout, tuple) else timeout or 120)
    deadline = total_deadline if total_deadline is not None else time.monotonic() + seconds
    network_timeout = timeout if isinstance(timeout,tuple) else (min(10.,seconds),seconds)
    diagnostics['timeout_policy'] = dict(connect_seconds=network_timeout[0],read_idle_seconds=network_timeout[1],
                                       total_remaining_seconds=max(0.,deadline-time.monotonic()))

    def send(kind, value):
        while not stop.is_set():
            try:
                events.put((kind, value), timeout=.025)
                return
            except queue.Full:
                pass

    def work():
        response = None
        try:
            if input_budget is not None:input_budget['dispatched']=True
            response = network_policy.post(url, headers=headers, json=body, stream=True, timeout=network_timeout)
            holder['response'] = response
            diagnostics['http_status'] = response.status_code
            diagnostics['content_type'] = str(response.headers.get('Content-Type', ''))
            send('transport', {'connected': True, 'bytes': 0})
            def chunks(size):
                for chunk in response.iter_content(chunk_size=size):
                    if chunk:send('transport', {'bytes': len(chunk)})
                    yield chunk
            if stop.is_set():
                return
            if response.status_code != 200:
                category = 'auth_error' if response.status_code in (401, 403) else 'rate_limited' if response.status_code == 429 else 'request_rejected' if response.status_code in (400, 404, 422) else 'transport_error'
                # Read only a bounded error body, without retaining headers or
                # echoing arbitrary request content returned by a proxy.
                from .provider_diagnostics import redact_diagnostics
                error_bytes = bytearray()
                for chunk in response.iter_content(chunk_size=1024):
                    if stop.is_set(): return
                    error_bytes.extend(chunk[:8192-len(error_bytes)])
                    if len(error_bytes) >= 8192: break
                message = ''
                try:
                    packet = json.loads(error_bytes.decode('utf-8'))
                    error = packet.get('error', {}) if isinstance(packet, dict) else {}
                    if isinstance(error, dict):
                        message = str(redact_diagnostics(error.get('message', '')))[:500]
                        diagnostics['provider_error'] = {key: redact_diagnostics(error[key])
                            for key in ('type', 'code', 'param') if key in error}
                except (ValueError, UnicodeError): pass
                diagnostics['provider_error_message'] = message
                if diagnostics.get('provider_error', {}).get('code') in {'insufficient_quota', 'billing_hard_limit_reached', 'quota_exceeded'}:
                    category = 'quota_exhausted'
                error = StreamProtocolError(f'Provider HTTP {response.status_code}' + (': '+message if message else ''), category)
                error.retry_after_seconds = retry_after_seconds(response.headers.get('Retry-After'))
                diagnostics['retry_after_seconds'] = error.retry_after_seconds
                raise error
            if 'event-stream' not in diagnostics['content_type'].lower():
                # Some proxies legitimately ignore stream:true. Consume this
                # same response, never issue a second paid request.
                if 'json' not in diagnostics['content_type'].lower():
                    raise StreamProtocolError('Provider没有返回JSON或SSE', 'configuration_error')
                raw = bytearray()
                for chunk in chunks(4096):
                    if stop.is_set():
                        return
                    raw.extend(chunk)
                    if len(raw) > 4 * 1024 * 1024:
                        raise StreamProtocolError('Provider响应超过4MiB上限', 'response_too_large')
                diagnostics.update(raw_bytes=len(raw), protocol='chat_completions_json')
                try:
                    packet = json.loads(raw.decode('utf-8'))
                    if protocol == 'responses':
                        emit_public_summaries(packet,send)
                        content = responses_final(packet, diagnostics)
                        reason = 'stop'
                        choices = None
                    else:
                        choices = packet['choices']
                    if choices is None:
                        pass
                    elif len(choices) != 1:
                        raise StreamProtocolError('单候选请求收到多个choice', 'conflicting_final')
                    else:
                        choice = choices[0]
                        content = choice['message']['content']
                        reason = choice['finish_reason']
                except (UnicodeError, ValueError, KeyError, TypeError) as exc:
                    if isinstance(exc, StreamProtocolError):
                        raise
                    raise StreamProtocolError('Provider返回无效的JSON协议对象') from None
                diagnostics.update(protocol=f'{"responses" if protocol == "responses" else "chat_completions"}_json', finish_reason=reason, request_id=packet.get('id'), content_chars=len(content) if isinstance(content, str) else 0)
                if reason != 'stop':
                    raise StreamProtocolError(f'Provider未完整生成正文（finish_reason={reason}）', 'structured_output_truncated' if reason == 'length' else 'provider_terminal_error')
                if not isinstance(content, str) or not content.strip():
                    raise StreamProtocolError('Provider没有字符串正文', 'provider_no_body')
                diagnostics.update(completed=True, content_sha256=hashlib.sha256(content.encode('utf-8')).hexdigest())
                send('delta', content)
            else:
                parser = responses_body if protocol == 'responses' else chat_body
                content = parser(chunks(1024), diagnostics, send, stop.is_set)
            send('complete', content)
        except BaseException as exc:
            send('error', exc)
        finally:
            if response is not None:
                response.close()

    worker = threading.Thread(target=work, name='provider-sse-reader', daemon=True)
    worker.start()
    try:
        while True:
            if cancel_check and cancel_check():
                raise StreamProtocolError('Provider请求已取消', 'cancelled')
            if time.monotonic() >= deadline:
                raise StreamProtocolError('Provider请求达到总时限', 'provider_total_timeout')
            try:
                kind, value = events.get(timeout=.025)
            except queue.Empty:
                continue
            if kind == 'error':
                raise value
            if kind == 'complete':
                return value
            emit(kind, value)
    finally:
        stop.set()
        response = holder.get('response')
        if response is not None and worker.is_alive():
            try:
                response.raw._fp.fp.raw._sock.shutdown(socket.SHUT_RDWR)
            except (AttributeError, OSError):
                pass
        worker.join(.2)
        diagnostics['transport_cleanup_pending'] = worker.is_alive()
