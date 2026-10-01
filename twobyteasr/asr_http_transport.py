"""Bounded HTTP execution for snapshot-bound ASR requests only.

No retries or transport fallback here. Each grouping attempt owns one request.
Requests combines connect/response-header timing, so connect_ms remains unknown.
"""
from __future__ import annotations

import json
import socket
import threading
import time


def complete(messages, *, model, api_key, url, max_tokens, temperature=0,
             timeout=(10, 120), provider="custom", base_url="", enable_thinking=False,
             response_format=None, request_diagnostics=None, cancel_check=None,
             _total_deadline=None, protocol="chat", json_schema=None, extra_body=None, **ignored):
    import requests
    from .llm_adapter import LLMRequestError, extract_chat_message_text, llm_provider_capabilities
    from .asr_provider_snapshot import classify_request_error

    diag = request_diagnostics if request_diagnostics is not None else {}
    started = time.monotonic()
    activity_started = time.perf_counter()
    deadline = _total_deadline or started + (max(timeout) if isinstance(timeout, tuple) else timeout)
    from .llm_config import endpoint_requires_key, auth_headers
    if not api_key and endpoint_requires_key(dict(provider=provider, base_url=base_url or url)):
        raise LLMRequestError("HTTP Provider缺少凭据。", category="auth_config")
    if protocol == "responses":
        body = {"model": model, "input": list(messages), "max_output_tokens": max_tokens}
        if json_schema:
            body["text"] = {"format": {"type": "json_schema", "name": "asr", "schema": json_schema, "strict": True}}
    else:
        body = {"model": model, "messages": list(messages), "max_tokens": max_tokens, "temperature": temperature}
        caps = llm_provider_capabilities(provider, base_url)
        if caps["supports_deepseek_thinking"] and enable_thinking is not None:
            body["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
        elif caps["supports_enable_thinking"] and enable_thinking is not None:
            body["enable_thinking"] = bool(enable_thinking)
        if response_format is not None:
            body["response_format"] = response_format
    dashscope_search=bool(provider=='bailian' and (extra_body or {}).get('enable_search'))
    if dashscope_search:
        from urllib.parse import urlsplit,urlunsplit
        endpoint=urlsplit(url)
        suffix='/compatible-mode/v1/chat/completions'
        if (endpoint.scheme!='https' or not (endpoint.hostname or '').endswith('.aliyuncs.com')
                or not endpoint.path.endswith(suffix) or protocol=='responses'):
            raise LLMRequestError('该端点未验证可返回检索来源的百炼协议。',category='unsupported_search')
        # Source metadata is only supported by the official DashScope API,
        # not its Chat Completions compatibility endpoint. Same host/account,
        # same model and the same bounded HTTP transport own this request.
        url=urlunsplit(endpoint._replace(path=endpoint.path[:-len(suffix)]+
            '/api/v1/services/aigc/text-generation/generation'))
        parameters={k:v for k,v in body.items() if k not in {'model','messages'}}
        parameters.update(enable_search=True,result_format='message',search_options={
            'forced_search':True,'search_strategy':'turbo','enable_source':True})
        body={'model':model,'input':{'messages':list(messages)},'parameters':parameters}
        diag['search_protocol']='dashscope_with_sources'
    elif extra_body:
        # Preserve supported caller options without allowing an extra-body
        # object to replace the immutable model or target text.
        body.update({k:v for k,v in extra_body.items() if k not in body})

    done = threading.Event()
    stop = threading.Event()
    state = {}

    def read_response():
        response = None
        try:
            if stop.is_set():
                return
            response = requests.post(url, headers={**auth_headers(api_key), "Content-Type": "application/json"},
                                     json=body, timeout=timeout, stream=True)
            state["response"] = response
            diag["http_status"] = response.status_code
            headers = response.headers
            # Request IDs are metadata; do not accept arbitrary server content.
            request_id = headers.get("x-request-id") or headers.get("request-id")
            if request_id:
                import re
                diag["http_request_id"] = request_id[:160] if re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", request_id) else "[redacted]"
            diag["headers_received_ms"] = round((time.perf_counter()-activity_started)*1000, 3)
            chunks=[]
            length=0
            for chunk in response.iter_content(chunk_size=1):
                if stop.is_set():
                    return
                if not chunk:
                    continue
                now=round((time.perf_counter()-activity_started)*1000, 3)
                if diag.get("first_activity_ms") is None:
                    diag["first_activity_ms"] = now
                if chunk.strip() and diag.get("first_body_byte_ms") is None:
                    diag["first_body_byte_ms"] = now
                diag["last_activity_ms"] = now
                chunks.append(chunk)
                length += len(chunk)
                if length > 4*1024*1024:
                    raise LLMRequestError("HTTP响应超过ASR响应上限。", category="format_mismatch")
            state["body"] = b"".join(chunks)
        except BaseException as exc:
            state["error"] = exc
        finally:
            try:
                if response is not None:response.close()
            except Exception as exc:
                # Cleanup must never suppress completion or replace the
                # original transport error/complete response body.
                diag['transport_cleanup_error']=type(exc).__name__
            finally:
                done.set()

    worker=threading.Thread(target=read_response, name="asr-http-request", daemon=True)
    worker.start()
    while not done.wait(.02):
        cancelled=bool(cancel_check and cancel_check())
        if cancelled or time.monotonic() >= deadline:
            stop.set()
            response=state.get("response")
            if response is not None:
                # Interrupt a blocking socket read before Response.close can wait
                # on its buffered reader. No unrelated process/session is touched.
                try:
                    sock=response.raw._fp.fp.raw._sock
                    sock.shutdown(socket.SHUT_RDWR)
                except (AttributeError, OSError):
                    pass
            worker.join(.2)
            diag["transport_cleanup_pending"] = worker.is_alive()
            raise LLMRequestError("HTTP请求已取消。" if cancelled else "HTTP请求总时限已到。",
                                  category="cancelled" if cancelled else "total_timeout")
    if "error" in state:
        exc=state["error"]
        category=classify_request_error(exc)
        # urllib3 can wrap its socket read timeout in requests.ConnectionError.
        if category=="connection_error" and "read timed out" in str(exc).lower():
            category="read_idle_timeout"
        raise LLMRequestError("HTTP传输失败："+category, category=category) from exc
    raw=state.get("body",b"")
    diag["http_body_bytes"] = len(raw)
    status=diag.get("http_status")
    if status is not None and status >= 400:
        category="rate_limited" if status==429 else "server_error" if status>=500 else "auth_error" if status in (401,403) else "configuration_error"
        try:
            error = json.loads(raw).get('error', {})
            code = str(error.get('code') or error.get('type') or '').casefold() if isinstance(error, dict) else ''
        except (ValueError, UnicodeError, AttributeError):
            code = ''
        if code in {'model_not_found','model_not_supported','unsupported_model'}:
            category = 'model_not_supported'
        elif code in {'unsupported_parameter','unsupported_parameters'}:
            category = 'unsupported_parameters'
        elif code in {'content_policy_violation','content_filter','provider_refusal'}:
            category = 'provider_refusal'
        raise LLMRequestError(f"HTTP {status}：{category}", category=category, response=state.get("response"))
    if not raw.strip():
        raise LLMRequestError("HTTP响应为空。", category="empty_response")
    try:
        payload=json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise LLMRequestError("HTTP响应不是合法JSON。", category="parse_failure") from exc
    if isinstance(payload.get('model'), str):
        diag['response_model'] = payload['model'][:160]
    if isinstance(payload.get('usage'),dict):
        diag['reported_usage']=[{k:v for k,v in payload['usage'].items()
            if isinstance(v,(int,float)) and not isinstance(v,bool)}]
    if dashscope_search:
        output=payload.get('output',{})
        urls=[row['url'] for row in output.get('search_info',{}).get('search_results',[])
              if isinstance(row,dict) and str(row.get('url','')).startswith('https://')]
        diag['search_evidence']=([{'tool':'dashscope_web_search','urls':list(dict.fromkeys(urls))}] if urls else [])
        payload=output
    try:
        if protocol=="responses":
            content="".join(part.get("text", "") for item in payload.get("output", []) for part in item.get("content", []) if part.get("type")=="output_text")
        else:
            choice=payload["choices"][0]
            if choice.get('finish_reason') == 'content_filter' or choice.get('message', {}).get('refusal'):
                raise LLMRequestError("服务商明确拒绝此请求。", category="provider_refusal")
            if choice.get("finish_reason")=="length":
                diag['finish_reason']='length'
                before_answer=not str(choice.get('message',{}).get('content') or '').strip()
                category='structured_output_truncated_before_answer' if before_answer else 'structured_output_truncated'
                # Preserve the actionable error so the caller's bounded
                # batch splitter can run; the transport itself never retries.
                raise LLMRequestError("HTTP正文因长度限制被截断。",category=category)
            content=extract_chat_message_text(choice["message"], prefer_structured=True)
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMRequestError("HTTP响应缺少正文结构。", category="format_mismatch") from exc
    diag["raw_response_length"]=len(content)
    diag["timing_observation"] = "first_activity_is_http_body_byte; connect_and_model_ttft_unavailable_nonstreaming"
    if not content.strip():
        raise LLMRequestError("HTTP正文为空。", category="empty_response")
    return content
