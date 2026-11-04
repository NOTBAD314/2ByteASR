"""Minimal live DeepSeek thinking-mode wire verification (never prints secrets)."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

import subtitle_core  # noqa: E402


FIXTURE = {
    "cues": [
        {"id": 1, "primary": "英角嘉年华结束了", "firered": "鹰角嘉年华结束了", "qwen": "鹰角嘉年华结束了"},
        {"id": 2, "primary": "末影隆飞过来了", "firered": "末影龙飞过来了", "qwen": "末影龙飞过来了"},
        {"id": 3, "primary": "这个伤害很高", "firered": "这个伤害很高", "qwen": "这个伤害很高"},
        {"id": 4, "primary": "他也发波然后闪了", "firered": "他也发波然后闪了", "qwen": "他也发波然后闪了"},
    ],
    "glossary": ["鹰角嘉年华", "末影龙"],
}


def run_mode(endpoint: dict, enabled: bool) -> dict:
    captured = {}
    original_post = requests.post

    def recording_post(url, **kwargs):
        body = dict(kwargs.get("json") or {})
        captured.update(
            endpoint=url,
            model=body.get("model"),
            max_tokens=body.get("max_tokens"),
            thinking=body.get("thinking"),
            enable_thinking_present="enable_thinking" in body,
            response_format=body.get("response_format"),
        )
        return original_post(url, **kwargs)

    requests.post = recording_post
    try:
        content = subtitle_core.post_chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是受限式 ASR 校对员。只返回 JSON 对象："
                        '{"cues":[{"id":1,"corrected":"文本"}]}。'
                        "逐条保留原意；FireRed 与 Qwen 一致且命中 glossary 时可修正专名。"
                    ),
                },
                {"role": "user", "content": json.dumps(FIXTURE, ensure_ascii=False)},
            ],
            model=endpoint["model"],
            api_key=endpoint["api_key"],
            url=endpoint["url"],
            base_url=endpoint["base_url"],
            provider=endpoint["provider"],
            max_tokens=4096,
            temperature=0.0,
            enable_thinking=enabled,
            response_format={"type": "json_object"},
            timeout=(10, 120),
        )
    finally:
        requests.post = original_post
    parsed = json.loads(content)
    diagnostics = subtitle_core.get_last_llm_response_diagnostics()
    return {
        "mode": "enabled" if enabled else "disabled",
        "wire": captured,
        "reasoning_content_length": diagnostics.get("reasoning_content_length"),
        "content_length": diagnostics.get("message_content_length"),
        "completion_tokens": diagnostics.get("completion_tokens"),
        "reasoning_tokens": diagnostics.get("reasoning_tokens"),
        "finish_reason": diagnostics.get("finish_reason"),
        "json_success": isinstance(parsed, dict) and isinstance(parsed.get("cues"), list),
        "request_id": diagnostics.get("request_id"),
    }


def main() -> int:
    endpoint = subtitle_core.group_llm_settings()
    if "api.deepseek.com" not in str(endpoint.get("base_url", "")):
        raise RuntimeError("当前 Group LLM 不是 DeepSeek 官方地址，停止真实对照测试。")
    if not endpoint.get("api_key"):
        raise RuntimeError("当前 DeepSeek 官方地址没有可用的 provider-scoped API Key。")
    print(json.dumps([run_mode(endpoint, True), run_mode(endpoint, False)], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
