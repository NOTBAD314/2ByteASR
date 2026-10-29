"""Ask a text model for a game's proper nouns, for the term library.

``request_ai_game_terms`` builds the prompt and ``parse_ai_game_terms`` keeps
only short, sourced terms.  ``TermSearchWorker`` runs it off the GUI thread.
Split out of ``app/ui.py`` on 2026-10-15; ``ui`` still exports these names.
"""
from __future__ import annotations

import json

import requests
from PySide6.QtCore import QThread, Signal

from ..providers.llm_config import validate_endpoint


def parse_ai_game_terms(content: str, limit: int = 36) -> list[dict]:
    """Parse and constrain one search-enabled model response for the term library."""
    text = str(content or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI 没有返回可读取的术语 JSON。")
    payload = json.loads(text[start : end + 1])
    raw_terms = payload.get("terms", []) if isinstance(payload, dict) else []
    if not isinstance(raw_terms, list):
        raise ValueError("AI 返回结果缺少 terms 数组。")
    result = []
    seen = set()
    for item in raw_terms:
        if not isinstance(item, dict):
            continue
        term = " ".join(str(item.get("term", "") or "").split()).strip("，,。；;：:")
        if not (2 <= len(term) <= 18) or term in seen or any(char in term for char in "\r\n<>[]{}"):
            continue
        category = " ".join(str(item.get("category", "游戏术语") or "游戏术语").split())[:12]
        sources = [
            str(url).strip()
            for url in item.get("sources", ())
            if str(url).strip().lower().startswith("https://")
        ][:3]
        result.append({"term": term, "category": category, "sources": sources})
        seen.add(term)
        if len(result) >= max(1, int(limit)):
            break
    if not result:
        raise ValueError("AI 没有找到可加入词库的可靠游戏术语。")
    return result


def request_ai_game_terms(
    endpoint: dict,
    game_name: str,
    requests_module=requests,
    *,
    content_type: str = "game",
) -> list[dict]:
    """Build a bounded, reviewable lexicon with any OpenAI-compatible text model."""
    validate_endpoint(endpoint, "AI 游戏术语搜索")
    supports_forced_search = endpoint.get("provider") == "bailian"
    research_instruction = (
        "请联网检索官方资料、可信百科或大型攻略站"
        if supports_forced_search
        else "请根据你掌握的可靠游戏资料整理；不确定的词不要输出"
    )
    type_labels = {
        "game": "游戏",
        "event": "活动或嘉年华",
        "series": "系列或 IP",
        "creator": "主播或创作者",
        "other": "内容主题",
    }
    type_label = type_labels.get(str(content_type), "内容主题")
    prompt = f"""你是字幕术语资料整理员。目标类型是“{type_label}”，名称为《{game_name}》。{research_instruction}，整理适合语音识别的中文专名。

要求：
1. 优先角色名、技能名、地点、阵营、物品、机制和常用简称；不要收录普通汉语词、整句说明、版本号或未经证实的昵称。
2. 每个词必须是资料中实际出现的正式写法，2-18 个字符；同一词不要重复。
3. 每项给出 category；只有确实知道公开 HTTPS 来源时才填写 sources，禁止编造网址。
4. 最多 36 项。只返回 JSON：{{"terms":[{{"term":"三月七","category":"角色","sources":["https://example.com"]}}]}}。"""
    payload = {
        "model": endpoint["model"],
        "messages": [
            {"role": "system", "content": "只整理可信的游戏专名，不得编造；只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 4096,
    }
    if supports_forced_search:
        payload.update(
            enable_search=True,
            search_options={"forced_search": True, "search_strategy": "turbo"},
        )
    response = requests_module.post(
        endpoint["url"],
        headers={
            "Authorization": f"Bearer {endpoint['api_key']}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=(10, 180),
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return parse_ai_game_terms(content)


class TermSearchWorker(QThread):
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, legacy, endpoint: dict, game_name: str, parent=None, content_type="game"):
        super().__init__(parent)
        self.legacy = legacy
        self.endpoint = dict(endpoint)
        self.game_name = str(game_name)
        self.content_type = str(content_type)

    def run(self):
        try:
            terms = request_ai_game_terms(
                self.endpoint,
                self.game_name,
                content_type=self.content_type,
            )
            self.completed.emit(self.game_name, terms)
        except Exception as exc:  # noqa: BLE001 - thread must report a useful UI error
            self.failed.emit(self.game_name, " ".join(str(exc).split())[:240])
