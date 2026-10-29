"""Claude through the Anthropic Messages API on this application's own HTTP layer (2026-10-18).

User choice: no SDK, the existing transport (``provider_stream.request_chat``: cancellation, total
deadline, wire-payload budget, TLS policy) carries ``POST /v1/messages`` with ``stream: true``. One
request per call; a partially received answer is never retried here.

* System messages become the top-level ``system``; OpenAI-style ``image_url`` parts become image
  blocks (base64 data URLs or plain URLs).
* No ``temperature``: the current Claude models reject non-default sampling parameters.
* Thinking stays adaptive (it cannot be switched off on these models); batch text stages ask for
  ``output_config.effort: "low"``, interactive design stages keep the model default.
* Opus 5.5 / Sonnet 5.5 requests carry ``fallbacks: "default"`` (beta
  ``server-side-fallback-2026-07-01``): a safety-classifier decline is retried server-side on the
  model Anthropic recommends; a final decline (``stop_reason: "refusal"``) is an error, never an
  empty answer.
* JSON is asked for in the system prompt and taken from the text (``TEXT_JSON``), not with
  ``output_config.format``: the application's schemas do not all meet its limits.
"""
from __future__ import annotations

import hashlib
import json
import time

from .api_usage import normalize_usage
from .provider_stream import StreamProtocolError, sse_data

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Server-side fallback exists for these; Haiku 5.5 has none (a declined request stays declined).
FALLBACK_MODEL_PREFIXES = ("claude-opus-5-5", "claude-sonnet-5-5")
JSON_INSTRUCTION = ("Reply with exactly one JSON object and nothing else: no Markdown fences, "
                    "no text before or after it.")
# Categories for Anthropic's error types (HTTP status alone cannot tell overload from a bad request).
ERROR_CATEGORIES = {
    "authentication_error": "auth_error",
    "permission_error": "auth_error",
    "billing_error": "quota_exhausted",
    "not_found_error": "model_not_supported",
    "request_too_large": "request_too_large",
    "rate_limit_error": "rate_limited",
    "overloaded_error": "server_error",
    "api_error": "server_error",
    "timeout_error": "server_error",
    "invalid_request_error": "request_rejected",
}


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text") or "") for part in content
                         if isinstance(part, dict) and part.get("type") in {"text", "input_text"})
    return str(content or "")


def _image_block(url: str) -> dict:
    if url.startswith("data:"):
        header, _, data = url.partition(",")
        media_type = header[5:].split(";", 1)[0] or "image/png"
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
    return {"type": "image", "source": {"type": "url", "url": url}}


def _content(content):
    if not isinstance(content, list):
        return str(content or "")
    blocks = []
    for part in content:
        if not isinstance(part, dict):
            blocks.append({"type": "text", "text": str(part)})
            continue
        kind = part.get("type")
        if kind in {"text", "input_text"}:
            if part.get("text"):
                blocks.append({"type": "text", "text": str(part["text"])})
        elif kind in {"image_url", "input_image"}:
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            if isinstance(url, str) and url:
                blocks.append(_image_block(url))
        elif kind == "image" and isinstance(part.get("source"), dict):
            blocks.append(part)  # already an Anthropic block
    return blocks or ""


def convert_messages(messages) -> tuple[str, list[dict]]:
    """(system text, Messages-API messages) from OpenAI-style chat messages."""
    system, converted = [], []
    for message in messages or ():
        role = str(message.get("role") or "user")
        if role in {"system", "developer"}:
            text = _text_of(message.get("content")).strip()
            if text:
                system.append(text)
            continue
        role = "assistant" if role == "assistant" else "user"
        content = _content(message.get("content"))
        if content == "":
            continue
        converted.append({"role": role, "content": content})
    if not converted or converted[0]["role"] != "user":
        converted.insert(0, {"role": "user", "content": "Continue."})
    if converted[-1]["role"] == "assistant":
        # These models do not take an assistant prefill: ask for the answer instead.
        converted.append({"role": "user", "content": "Continue."})
    return "\n\n".join(system), converted


def uses_fallback(model: str) -> bool:
    return str(model or "").startswith(FALLBACK_MODEL_PREFIXES)


def request_body(model, messages, *, max_tokens, json_wanted=False, effort=None, stream=True) -> dict:
    system, converted = convert_messages(messages)
    if json_wanted:
        system = f"{system}\n\n{JSON_INSTRUCTION}" if system else JSON_INSTRUCTION
    body = {"model": model, "max_tokens": int(max_tokens), "messages": converted, "stream": bool(stream)}
    if system:
        body["system"] = system
    if effort:
        body["output_config"] = {"effort": effort}
    if uses_fallback(model):
        body["fallbacks"] = "default"
    return body


def request_headers(api_key, model) -> dict:
    from .llm_config import auth_headers
    headers = {**auth_headers(api_key, "anthropic"), "Content-Type": "application/json",
               "Accept": "text/event-stream"}
    if uses_fallback(model):
        headers["anthropic-beta"] = FALLBACK_BETA
    return headers


def output_budget(requested: int) -> int:
    """Room for adaptive thinking on top of the answer the caller sized ``max_tokens`` for."""
    requested = max(1, int(requested or 1))
    return min(64_000, max(1_024, requested * 2, requested + 2_048))


def refine_error_category(category: str, error_type: str, status: int | None) -> str:
    if error_type in ERROR_CATEGORIES:
        return ERROR_CATEGORIES[error_type]
    if status is not None and (status >= 500 or status == 529):
        return "server_error"
    return category


def _usage(diagnostics, usage):
    if not isinstance(usage, dict):
        return
    merged = dict(diagnostics.get("_anthropic_usage") or {})
    merged.update({key: value for key, value in usage.items() if value is not None})
    diagnostics["_anthropic_usage"] = merged
    prompt = sum(int(merged.get(key) or 0) for key in
                 ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    completion = int(merged.get("output_tokens") or 0)
    diagnostics.update(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion,
                       usage=normalize_usage(merged))


def _finish(diagnostics, stop_reason, stop_details=None):
    diagnostics["finish_reason"] = stop_reason
    if stop_reason in {"end_turn", "stop_sequence"}:
        return
    chars = diagnostics.get("content_chars", 0)
    if stop_reason == "refusal":
        category = (stop_details or {}).get("category") if isinstance(stop_details, dict) else None
        diagnostics["refusal_category"] = category
        raise StreamProtocolError(f"Claude 拒绝了这次请求（安全分类：{category or '未说明'}）", "provider_refusal")
    if stop_reason == "max_tokens":
        raise StreamProtocolError(f"Claude 输出达到长度上限（正文{chars}字符）", "structured_output_truncated")
    if stop_reason in {"tool_use", "pause_turn"}:
        raise StreamProtocolError(f"Claude 没有给出最终正文（stop_reason={stop_reason}）", "provider_tool_request")
    raise StreamProtocolError(f"Claude 未完整结束（stop_reason={stop_reason}）", "provider_terminal_error")


def messages_body(chunks, diagnostics, emit=lambda *_: None, cancel_check=None):
    """The answer text of one Messages SSE stream, validated to its ``message_stop``."""
    parts = []
    stop_reason = stop_details = None
    stopped = False
    diagnostics.update(protocol="anthropic_messages_sse", event_count=0, content_chars=0)
    for data in sse_data(chunks, diagnostics, cancel_check):
        diagnostics["event_count"] += 1
        try:
            packet = json.loads(data)
        except json.JSONDecodeError:
            raise StreamProtocolError(f"$.sse[{diagnostics['event_count']}]: 无效JSON协议事件") from None
        if not isinstance(packet, dict):
            raise StreamProtocolError("Messages SSE事件必须为对象")
        kind = packet.get("type")
        if kind == "message_start":
            message = packet.get("message") or {}
            if message.get("id"):
                diagnostics["request_id"] = str(message["id"])[:160]
            if isinstance(message.get("model"), str):
                diagnostics["response_model"] = message["model"][:160]
            _usage(diagnostics, message.get("usage"))
        elif kind == "content_block_delta":
            delta = packet.get("delta") or {}
            if delta.get("type") == "text_delta":
                text = delta.get("text")
                if not isinstance(text, str):
                    raise StreamProtocolError("Messages text_delta必须为字符串")
                parts.append(text)
                diagnostics["content_chars"] += len(text)
                if diagnostics["content_chars"] > 1024 * 1024:
                    raise StreamProtocolError("Provider正文超过1Mi字符上限", "response_too_large")
                emit("delta", text)
            elif delta.get("type") == "thinking_delta":
                diagnostics["reasoning_chars"] = diagnostics.get("reasoning_chars", 0) + len(delta.get("thinking") or "")
                emit("provider_event", "thinking")
            elif delta.get("type") == "input_json_delta":
                raise StreamProtocolError("Claude 返回了工具调用，缺少最终正文", "provider_tool_request")
        elif kind == "content_block_start":
            block = packet.get("content_block") or {}
            if block.get("type") == "fallback":
                diagnostics["fallback"] = {"from": (block.get("from") or {}).get("model"),
                                           "to": (block.get("to") or {}).get("model")}
            elif block.get("type") == "tool_use":
                raise StreamProtocolError("Claude 返回了工具调用，缺少最终正文", "provider_tool_request")
            emit("provider_event", str(block.get("type") or "content_block"))
        elif kind == "message_delta":
            delta = packet.get("delta") or {}
            if delta.get("stop_reason"):
                stop_reason, stop_details = delta["stop_reason"], delta.get("stop_details")
            _usage(diagnostics, packet.get("usage"))
        elif kind == "message_stop":
            stopped = True
            break
        elif kind == "error":
            error = packet.get("error") or {}
            diagnostics["provider_error"] = {"type": error.get("type")}
            raise StreamProtocolError(f"Claude 流中返回错误（{error.get('type') or '未知'}）：{str(error.get('message') or '')[:300]}",
                                      refine_error_category("provider_terminal_error", str(error.get("type") or ""), None))
        else:
            emit("provider_event", str(kind))  # ping, content_block_stop
    if cancel_check and cancel_check():
        raise StreamProtocolError("流式请求已取消", "cancelled")
    if not stopped:
        raise StreamProtocolError("Provider连接结束但未收到完整终态", "structured_output_truncated")
    _finish(diagnostics, stop_reason, stop_details)
    body = "".join(parts)
    if not body.strip():
        raise StreamProtocolError("Claude 已结束但没有正文", "provider_no_body")
    diagnostics.update(completed=True, content_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest())
    emit("final", "")
    return body


def messages_final(packet, diagnostics):
    """A whole (non-streamed) Messages response, e.g. from a proxy that ignored ``stream``."""
    if not isinstance(packet, dict) or packet.get("type") == "error":
        raise StreamProtocolError("Claude 返回的不是消息对象", "provider_terminal_error")
    if packet.get("id"):
        diagnostics["request_id"] = str(packet["id"])[:160]
    if isinstance(packet.get("model"), str):
        diagnostics["response_model"] = packet["model"][:160]
    _usage(diagnostics, packet.get("usage"))
    text = "".join(block.get("text") or "" for block in packet.get("content") or []
                   if isinstance(block, dict) and block.get("type") == "text")
    diagnostics["content_chars"] = len(text)
    _finish(diagnostics, packet.get("stop_reason"), packet.get("stop_details"))
    if not text.strip():
        raise StreamProtocolError("Claude 已结束但没有正文", "provider_no_body")
    return text


def complete(endpoint, messages, *, max_tokens, timeout, stage="", cancel_check=None, json_wanted=False,
             effort=None, on_stream_event=None, request_diagnostics=None, total_deadline=None, input_budget=None):
    """One Messages request; returns the answer text or raises ``LLMRequestError`` (category set)."""
    import requests
    from .llm_adapter import (LLMRequestError, _DIAGNOSTIC_LOCAL, _record_answered_call, _redact,
                              record_llm_invocation)
    from .provider_stream import request_chat
    model, api_key, url = str(endpoint.get("model") or ""), str(endpoint.get("api_key") or ""), str(endpoint.get("url") or "")
    if not api_key:
        raise LLMRequestError("Claude 缺少 API Key：请在设置里填写 Anthropic Console 的 API Key。", category="auth_config")
    body = request_body(model, messages, max_tokens=output_budget(max_tokens), json_wanted=json_wanted, effort=effort)
    headers = request_headers(api_key, model)
    diagnostics = dict(provider="anthropic", model=model, endpoint=url, base_url=endpoint.get("base_url", ""),
                       stream=True, max_tokens=body["max_tokens"], effort=effort or "model_default",
                       fallbacks=body.get("fallbacks"), thinking_mode="adaptive")
    _DIAGNOSTIC_LOCAL.value = diagnostics
    started = time.perf_counter()

    def emit(kind, value):
        if kind == "request_started":
            diagnostics.setdefault("first_activity_ms", None)
        elif kind in {"transport", "delta"} and diagnostics.get("first_activity_ms") is None:
            diagnostics["first_activity_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        if on_stream_event is not None and kind not in {"thinking_end"}:
            on_stream_event(kind, value)

    failure = "incomplete"
    try:
        value = request_chat(url, headers, body, timeout, diagnostics, emit, cancel_check, protocol="anthropic",
                             total_deadline=total_deadline, input_budget=input_budget)
        failure = ""
        return value
    except (StreamProtocolError, requests.RequestException) as exc:
        category = getattr(exc, "category", "transport_error")
        diagnostics["failure_category"] = failure = str(category)
        error = LLMRequestError(_redact(str(exc), api_key), category=category, diagnostics=diagnostics)
        for name in ("report", "retry_after_seconds"):
            if hasattr(exc, name):
                setattr(error, name, getattr(exc, name))
        raise error from exc
    except BaseException as exc:
        failure = str(getattr(exc, "category", type(exc).__name__))
        raise
    finally:
        diagnostics.pop("_anthropic_usage", None)
        _DIAGNOSTIC_LOCAL.value = dict(diagnostics)
        if request_diagnostics is not None:
            request_diagnostics.update(
                http_status=diagnostics.get("http_status"), http_request_id=diagnostics.get("request_id"),
                first_activity_ms=diagnostics.get("first_activity_ms"), prompt_tokens=diagnostics.get("prompt_tokens"),
                completion_tokens=diagnostics.get("completion_tokens"), usage=diagnostics.get("usage"),
                finish_reason=diagnostics.get("finish_reason"), response_model=diagnostics.get("response_model"))
        record_llm_invocation(stage=stage, provider="anthropic", model=model, base_url=endpoint.get("base_url", ""),
                              url=url, request_mode="anthropic.messages_stream",
                              key_source=str(endpoint.get("key_source") or ""), key_present=bool(api_key),
                              status_code=diagnostics.get("http_status"), ok=False if failure else None,
                              error=failure, duration_ms=(time.perf_counter() - started) * 1000.0)
        _record_answered_call(diagnostics, stage=stage, provider="anthropic", model=model,
                              request_mode="anthropic.messages_stream")
