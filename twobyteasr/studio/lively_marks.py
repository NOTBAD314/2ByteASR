"""AI 生动标记: the model adds Markdown marks to captions, never words (2026-11-20, user).

The user wanted captions as lively as 问问兔白's bubbles: bold key words,
==highlights==, ~~struck-out~~ jokes and ``#``–``######`` heading lines, chosen by
AI. The model receives each caption as escaped Markdown and answers the same
caption with marks added. An answer is used only when removing its marks gives
back exactly the caption's text (a Traditional/Simplified-only difference is
mapped back), so the text itself can never change. Captions that already carry
the user's own marks are not sent. Applying is one undo step.
"""
from __future__ import annotations

import json
import queue
import threading
from typing import Callable, Iterable, Mapping

from ..caption_style.text_marks import layer_marks, markdown_text, parse_markdown, remap_marks, with_marks

# Share of a batch that may be marked. The first live run (2026-11-20, DeepSeek) ignored
# "about one in three" and bolded a name in 7 of 8 captions; a concrete count per batch and
# "a plain name is not worth a mark" is what it follows.
DENSITIES = {"light": 0.2, "normal": 0.4, "lively": 0.6}

SYSTEM = (
    "你是字幕的视觉编辑，给视频字幕加 Markdown 标记，让字幕像综艺花字一样生动好看。\n"
    "只能加标记，绝对不能增加、删除或改动任何文字、标点和空格；输入里的反斜杠转义（例如 \\-\\-、\\*）要原样保留。\n"
    "可用的标记：\n"
    "- **文字**：这句话的重音落在哪几个字，就标哪几个字（结论、数字、反转的那个词）。\n"
    "- ==文字==：整句里最不能漏看的几个字，会画成黄色荧光笔。\n"
    "- ~~文字~~：自嘲、口误、说反话、立了马上就倒的 flag，会被划掉。\n"
    "- *文字*：心声、引用别人的话、小声吐槽、外语。\n"
    "- 行首写“# ”到“###### ”（井号后面有一个空格）：这一整行变成标题。# 和 ## 很大，用在开场、章节、惊呼大喊；"
    "### 和 #### 用在要强调的整句；##### 和 ###### 是小字，用在旁白、心虚和碎碎念。\n"
    "怎么选：\n"
    "- 这一批共 {total} 条，最多给 {limit} 条加标记。先挑情绪最强、最有梗、信息最关键的那几条，其余的不要标。\n"
    "- 手法要跟着内容换：喊出来的用大标题，嘀咕的用小字，被打脸的话划掉，关键信息用重点。"
    "不要整批都是同一种标记。\n"
    "- 人名、地名、游戏名只是被提到时不值得标；不要见到名字就加粗。\n"
    "- 一条字幕最多两处标记；标记必须成对，不要嵌套；不要整条都加粗；大标题（# 和 ##）整批最多一两条。\n"
    "例子：\n"
    "“这把稳了” 下一句就翻车 → ~~这把稳了~~\n"
    "“等一下等一下等一下” → # 等一下等一下等一下\n"
    "“其实我刚才是故意的” → ###### 其实我刚才是故意的\n"
    "“只剩最后一滴血了” → 只剩==最后一滴血==了\n"
    "“他说这关很简单” → 他说*这关很简单*\n"
    "只返回 JSON：{{\"cues\":[{{\"cue_id\":\"\",\"markdown\":\"\"}}]}}。只列出要加标记的字幕，"
    "不用标的字幕不要返回；markdown 是加好标记的整条字幕。"
)


def batch_limit(total: int, density: str) -> int:
    return max(1, round(total * DENSITIES.get(density, DENSITIES["normal"])))

BATCH_CUES = 30
BATCH_CHARS = 1400
PARALLEL = 3
_TRUNCATED = {"structured_output_truncated", "structured_output_truncated_before_answer"}

SCHEMA = {
    "type": "object",
    "properties": {"cues": {"type": "array", "items": {
        "type": "object",
        "properties": {"cue_id": {"type": "string"}, "markdown": {"type": "string"}},
        "required": ["cue_id", "markdown"]}}},
    "required": ["cues"],
}


class LivelyResult(dict):
    """``{cue_id: marks}`` from every finished batch plus what happened."""

    def __init__(self, marks=None, *, sent=0, rejected=0, batches=0, done=0, error=""):
        super().__init__(marks or {})
        self.sent, self.rejected, self.batches, self.done, self.error = sent, rejected, batches, done, error


def candidates(project, cue_ids: Iterable[str]) -> tuple[list[tuple[str, str]], int]:
    """``[(cue_id, text)]`` worth sending, and how many were skipped for the user's own marks."""
    wanted = {str(item) for item in cue_ids}
    rows, kept = [], 0
    for cue in project.cues:
        if cue.id not in wanted or not str(cue.text).strip():
            continue
        if layer_marks(cue):
            kept += 1
            continue
        rows.append((cue.id, str(cue.text)))
    return rows, kept


def batches(rows: list[tuple[str, str]], *, size: int = BATCH_CUES, chars: int = BATCH_CHARS):
    result, current, length = [], [], 0
    for row in rows:
        if current and (len(current) >= size or length + len(row[1]) > chars):
            result.append(current)
            current, length = [], 0
        current.append(row)
        length += len(row[1])
    if current:
        result.append(current)
    return result


def marks_for(text: str, answer: str):
    """The marks ``answer`` puts on ``text``, or None when it changed the words."""
    shown, marks, _positions = parse_markdown(str(answer or "").strip())
    if shown == text:
        return marks
    if len(shown) == len(text):
        from ..subtitle_rules.chinese_script import fold
        if all(a == b or a.casefold() == b.casefold() or fold(a) == fold(b) for a, b in zip(shown, text)):
            return remap_marks(shown, text, marks)
    return None


def parse_answer(raw, batch: list[tuple[str, str]]) -> tuple[dict, int]:
    payload = json.loads(raw) if isinstance(raw, str) else raw
    items = payload.get("cues") if isinstance(payload, Mapping) else payload
    if not isinstance(items, list):
        raise ValueError("AI 没有返回可解析的 cues 列表")
    texts = dict(batch)
    found, rejected = {}, 0
    for item in items:
        if not isinstance(item, Mapping):
            continue
        cue_id = str(item.get("cue_id") or "")
        if cue_id not in texts:
            continue
        marks = marks_for(texts[cue_id], str(item.get("markdown") or ""))
        if marks is None:
            rejected += 1
        elif marks:
            found[cue_id] = marks
    return found, rejected


def _request(batch, density, provider, cancel_check):
    system = SYSTEM.format(total=len(batch), limit=batch_limit(len(batch), density))
    user = {"cues": [{"cue_id": cue_id, "text": markdown_text(text, [])} for cue_id, text in batch]}
    raw = provider.complete(
        [{"role": "system", "content": system},
         {"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
        max_tokens=3000, temperature=0.6, timeout=(10, 90), enable_thinking=False,
        response_format={"type": "json_object"}, stage="studio_lively_marks",
        structured_retry_system_prompt=system, json_schema=SCHEMA, cancel_check=cancel_check)
    return parse_answer(raw, batch)


def _batch(batch, density, provider, cancel_check):
    """Halve a batch while its answer overflows; one caption that still overflows is left plain."""
    try:
        return _request(batch, density, provider, cancel_check)
    except Exception as exc:
        if getattr(exc, "category", "") not in _TRUNCATED or len(batch) == 1:
            if len(batch) == 1 and getattr(exc, "category", "") in _TRUNCATED:
                return {}, 0
            raise
        middle = len(batch) // 2
        a, ra = _batch(batch[:middle], density, provider, cancel_check)
        b, rb = _batch(batch[middle:], density, provider, cancel_check)
        return {**a, **b}, ra + rb


def request_lively_marks(rows: list[tuple[str, str]], *, density: str = "normal", provider=None,
                         runtime_settings: dict | None = None,
                         cancel_check: Callable[[], bool] | None = None,
                         progress: Callable[[dict], None] | None = None,
                         parallel: int = PARALLEL) -> LivelyResult:
    """Marks for ``rows`` (``[(cue_id, text)]``), batch by batch. Plain data in, plain data out:
    safe to run off the GUI thread. A failed batch stops the run and keeps what was found."""
    groups = batches(rows)
    if not groups:
        return LivelyResult()
    if provider is None:
        settings = runtime_settings if isinstance(runtime_settings, dict) else {}
        if not settings.get("models"):
            from ..storage.settings import load_runtime_settings
            loaded = load_runtime_settings()
            settings = loaded[0] if isinstance(loaded, tuple) else loaded
        from ..providers.ai_providers import provider_for_stage
        provider = provider_for_stage(settings, "polish")
    found, done, rejected, error = {}, 0, 0, ""

    def cancelled():
        return bool(cancel_check and cancel_check())

    def run(index):
        if cancelled():
            return {}, 0
        return _batch(groups[index], density, provider, cancel_check)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max(1, min(int(parallel), len(groups)))) as pool:
        pending = [pool.submit(run, index) for index in range(len(groups))]
        for future in as_completed(pending):
            try:
                marks, bad = future.result()
            except Exception as exc:
                error = error or str(exc) or type(exc).__name__
                for other in pending:
                    other.cancel()
                continue
            found.update(marks)
            rejected += bad
            done += 1
            if progress is not None:
                progress(dict(done=done, total=len(groups), found=len(found)))
    if cancelled() and not error:
        error = "已取消"
    return LivelyResult(found, sent=len(rows), rejected=rejected, batches=len(groups), done=done, error=error)


def overrides_for(project, result: Mapping[str, list], sent: Mapping[str, str]) -> dict:
    """New ``appearance_override`` per cue; a caption edited or marked meanwhile is left alone."""
    lookup = {cue.id: cue for cue in project.cues}
    overrides = {}
    for cue_id, marks in result.items():
        cue = lookup.get(cue_id)
        if cue is None or str(cue.text) != sent.get(cue_id) or layer_marks(cue):
            continue
        overrides[cue_id] = with_marks(cue, marks)
    return overrides


def web_theme_cue_ids(project, cue_ids: Iterable[str]) -> list[str]:
    """Captions drawn by an AI-designed web theme. Since 2026-11-20 the theme shows the
    caption's marks in its own design language (caption_design/web_theme_marks.py), so the
    result message no longer warns about them."""
    from ..caption_style.style_recipe import recipe_payload_for_style
    wanted = {str(item) for item in cue_ids}
    found = []
    for cue in project.cues:
        if cue.id in wanted:
            payload = recipe_payload_for_style(project.style_recipes, cue.style_id)
            if isinstance(payload, Mapping) and payload.get("webTheme"):
                found.append(cue.id)
    return found


def run_lively_marks(page, *, selected: bool = False, scope: str | None = None, density: str = "normal") -> None:
    """Mark captions in the background: the whole project, the selected captions, or the
    AI 设计 panel's apply range (``scope``: current / speaker / all)."""
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QMessageBox, QProgressDialog
    from ..design.studio_theme import studio_message_box
    from ..i18n import tr
    title = tr("AI 生动标记")
    project = getattr(page, "project", None)
    if project is None:
        studio_message_box(page, QMessageBox.Icon.Information, title, tr("请先打开字幕工程。"))
        return
    from .studio_text_tools import SCOPE_ALL, SCOPE_CURRENT, SCOPE_SELECTED, SCOPE_SPEAKER, scope_cue_ids
    wanted = {"current": SCOPE_CURRENT, "speaker": SCOPE_SPEAKER, "all": SCOPE_ALL}.get(
        str(scope or ""), SCOPE_SELECTED if selected else SCOPE_ALL)
    ids = scope_cue_ids(page, wanted)
    rows, kept = candidates(project, ids)
    if not rows:
        studio_message_box(page, QMessageBox.Icon.Information, title,
                           tr("没有可以加标记的字幕；已有标记的字幕会保留原样。") if kept else tr("请先选中字幕。"))
        return
    from ..caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
    from ..providers.llm_config import text_ai_key_missing
    settings = GLOBAL_PROVIDER_REGISTRY.settings()
    if text_ai_key_missing(settings, "polish"):
        studio_message_box(page, QMessageBox.Icon.Information, title,
                           tr("还没有设置文字 AI 的 API Key。请先在设置的 AI 服务里填写，再使用 AI 生动标记。"))
        return
    sent = dict(rows)
    dialog = QProgressDialog(tr("AI 正在给 {count} 条字幕挑选标记…", count=len(rows)), tr("取消"), 0, 0, page)
    dialog.setWindowTitle(title)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    cancel = threading.Event()
    mailbox: queue.Queue = queue.Queue()
    dialog.canceled.connect(cancel.set)

    def work():
        try:
            mailbox.put(("done", request_lively_marks(
                rows, density=density, runtime_settings=settings, cancel_check=cancel.is_set,
                progress=lambda state: mailbox.put(("progress", state)))))
        except Exception as exc:  # noqa: BLE001 - reported in the window, never raised into Qt
            mailbox.put(("failed", str(exc) or type(exc).__name__))

    timer = QTimer(dialog)
    timer.setInterval(120)

    def finish(result: LivelyResult | None, error: str = ""):
        timer.stop()
        dialog.close()
        applied = 0
        if result:
            overrides = overrides_for(page.project, result, sent) if page.project is project else {}
            if overrides:
                from ..timeline.studio_commands import SetCuesAppearanceCommand
                page.session.undo_stack.push(SetCuesAppearanceCommand(
                    project, overrides, tr("AI 生动标记"), getattr(page, "_changed", None)))
                applied = len(overrides)
        lines = []
        if applied:
            lines.append(tr("已为 {count} 条字幕加上标记，可以一步撤销。", count=applied))
        elif not error:
            lines.append(tr("AI 觉得这些字幕不需要加标记。"))
        if kept:
            lines.append(tr("{count} 条字幕已有你加的标记，保持原样。", count=kept))
        if result is not None and result.rejected:
            lines.append(tr("{count} 条回答改动了文字，已丢弃。", count=result.rejected))
        if error:
            from ..media.link_download import redact
            lines.append(tr("没有全部完成：{error}", error=redact(error)))
        studio_message_box(page, QMessageBox.Icon.Warning if error and not applied else QMessageBox.Icon.Information,
                           title, "\n".join(lines))

    def poll():
        while True:
            try:
                kind, value = mailbox.get_nowait()
            except queue.Empty:
                return
            if kind == "progress":
                dialog.setMaximum(int(value["total"]))
                dialog.setValue(int(value["done"]))
                dialog.setLabelText(tr("AI 正在挑选标记… {done}/{total} 批，已标 {found} 条",
                                       done=value["done"], total=value["total"], found=value["found"]))
            elif kind == "done":
                finish(value, value.error)
                return
            else:
                finish(None, value)
                return

    timer.timeout.connect(poll)
    timer.start()
    threading.Thread(target=work, daemon=True, name="caption-lively-marks").start()
    dialog.show()
