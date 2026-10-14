"""AI glossary proofreading workspace (2026-10-09 M14; reworked 2026-10-10).

2026-10-10 (user report on project 0852f218, 193 captions): the page opened
empty until a library was ticked, previews played unrelated audio, every
correction had to go through the vocabulary column, one caption could fill
the list with several cards, and ordinary words (刚刚, 学聪明了) were treated
as game names.

Now the page is a reading/editing workspace over *every* caption of the
current document (Studio's in-memory project when it is open):

* one row per caption, keyed by its stable id; issues of that caption are
  lines inside the row and are accepted or ignored individually;
* any caption can be edited in place; a manual edit is a pending change of
  its own, independent of adding an alias to a library (offered separately);
* glossary libraries are inherited from the project (id + revision of the
  recognition snapshot); only the local match runs on entry — the paid model
  runs only from its button, with progress and cancel;
* stammer cleanup is a separate, switchable source of deletions;
* audio comes from ``cue_audio_preview`` (the export/recognition mixer at the
  caption's timeline range), never from a private time conversion.

Pending changes stay on this page until 应用, which writes the confirmed
texts as one undo step to the same project Studio, previews and exports
read, then saves. Late results are dropped by generation, project identity
and per-caption text.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import time
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPolygonF, QUndoStack
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
                               QScrollArea, QScrollBar, QSizePolicy, QVBoxLayout, QWidget)

import bisect

from .i18n import bind_text, tr
from .typography import MONO_FONT_STACK
from .studio_find_replace import PreviewBinding
from .theme_manager import theme_key
from .ui_theme import blend_hex, theme_definition
from .lazy_pages import existing_page

# 2026-10-10: no imports inside paint/scroll paths. PySide's import hook
# re-reads the importing module's source for every executed import
# statement; next to a busy review thread each file access waits for the
# interpreter lock, and a scroll could stall for over a second.


class _TextReviewBinding(PreviewBinding):
    @staticmethod
    def _document_payload(project):
        payload = PreviewBinding._document_payload(project)
        # mpv refreshes cached source durations during page transitions. Text
        # review neither reads nor writes these metadata values. Actual cue
        # timing, media identity, edits, locks and evidence remain fenced.
        payload['media'].pop('duration_ms', None)
        for asset in payload.get('media_pool', ()):
            asset.pop('duration_ms', None)
        return payload


CATEGORIES = ("选手 ID", "人物", "角色", "Boss", "物品", "方块", "阵营", "地点", "模型", "技能", "事件", "其他")
_SPLIT_ITEMS = re.compile(r"[\n、，,；;]+")
_SPLIT_ALIAS = re.compile(r"\s*(?:→|->|=>|=)\s*")
_REPEAT_HINT = re.compile(r"([一-鿿]{1,4})[ ，,、]?\1")

# Issue kinds: where a proposal came from (never a claim that it is right).
KIND_LABELS = {
    "term": "词库写法",       # confirmed alias in a chosen library
    "near": "词库近音",       # near spelling/sound of a library term
    "ai": "AI 校对",          # accepted by the proofreading model + safety gate
    "ai_review": "AI 建议",   # model proposal that needs a decision
    "association": "词库候选",  # suspected name with a library candidate (default on)
    "stutter": "口吃整理",
    "consistency": "统一写法",
    "evidence": "两路识别",
    "merge": "疑似重复",       # repeat no recognizer heard; data issue
    "suspect": "疑似专名",      # no candidate: shown, never auto-changed
}
KIND_TIPS = {
    "term": "按所选词库里已确认的写法匹配；没有核对原音，可试听后决定",
    "near": "读音或写法接近词库里的词；只是候选，默认不采用",
    "ai": "校对模型结合词库和上下文给出，并通过了安全检查；没有核对原音",
    "ai_review": "校对模型的提议，需要你确认",
    "association": "疑似专有名词，词库里有候选写法；默认采用，不对就取消勾选",
    "stutter": "同一人起句重来或卡顿造成的重复；只改显示文字，不删音频",
    "evidence": "FireRed 和 Qwen 两个识别模型在这里听到的和字幕不一样；两者一致时默认采用，不一致时列出两种，先听原声再选",
    "consistency": "同一个读音在全片写成了不同的字；统一成一种写法，方便以后查找和批量替换（不代表这种写法正确）",
    "merge": "各路识别原文都没有这段重复或字级时间重叠，可能是数据合并问题；默认不改",
    "suspect": "可能是专有名词，词库里没有对应写法；可以直接改这句字幕",
}
PRIORITY = {"term": 0, "association": 1, "evidence": 1, "ai": 2, "consistency": 2, "stutter": 3, "ai_review": 4, "near": 5, "merge": 6, "suspect": 9}


def _theme():
    return theme_definition(theme_key())


# --------------------------------------------------------------------------
# Colors that stay readable on every theme
# --------------------------------------------------------------------------

def _luminance(value):
    color = QColor(value)
    channels = []
    for channel in (color.redF(), color.greenF(), color.blueF()):
        channels.append(channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(foreground, background):
    a, b = _luminance(foreground), _luminance(background)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def legible(foreground, background, theme, ratio=4.5):
    """``foreground`` moved toward the theme's text color until it reads."""
    if contrast(foreground, background) >= ratio:
        return foreground
    for amount in (0.25, 0.45, 0.65, 0.85, 1.0):
        candidate = blend_hex(foreground, theme.text, amount)
        if contrast(candidate, background) >= ratio:
            return candidate
    return theme.text


def mark_colors(theme):
    """Error (what is wrong), fix (the proposed replacement) and applied."""
    error_fill = blend_hex(theme.surface, theme.danger, 0.32)
    fix_fill = blend_hex(theme.surface, theme.success, 0.30)
    applied_fill = blend_hex(theme.surface, theme.success, 0.20)
    return {
        "error_fill": error_fill,
        "error_text": legible(theme.text, error_fill, theme, 7.0),
        "error_line": legible(theme.danger, theme.surface, theme, 3.0),
        "fix_fill": fix_fill,
        "fix_line": legible(theme.success, theme.surface, theme, 3.0),
        "fix_text": legible(blend_hex(theme.success, theme.text, 0.35), fix_fill, theme, 4.5),
        "applied_fill": applied_fill,
        "applied_text": legible(theme.text, applied_fill, theme, 7.0),
        "applied_line": legible(theme.success, theme.surface, theme, 3.0),
    }


# --------------------------------------------------------------------------
# Glossary input: "古龙 - 骨龙", "古龙 骨龙", Tab columns, arrows, one word
# --------------------------------------------------------------------------

_ITEM_SPLIT = re.compile(r"[\n、，,；;]+")
_ARROW = re.compile(r"\s*(?:→|->|=>|＝|=)\s*")
_DASH = re.compile(r"\s+[-–—－]+\s+")
_CJK = re.compile(r"[㐀-鿿豈-﫿]")


def parse_term_entry(item):
    """One typed entry → dict(alias, canonical, how, ambiguous).

    Left is the wrong spelling / alias, right the standard spelling. Names
    keep their own hyphens and inner spaces ("Spider-Man", "Lord of Fire")."""
    item = str(item or "").strip()
    if not item:
        return None
    if "\t" in item:
        parts = [part.strip() for part in item.split("\t") if part.strip()]
        how = "tab"
    elif _ARROW.search(item):
        parts = [part.strip() for part in _ARROW.split(item) if part.strip()]
        how = "arrow"
    elif _DASH.search(item):
        parts = [part.strip() for part in _DASH.split(item) if part.strip()]
        how = "dash"
    else:
        words = item.split()
        if len(words) == 2 and (_CJK.search(words[0]) or _CJK.search(words[1])
                                or words[0].casefold() == words[1].casefold()):
            parts, how = words, "space"
        elif len(words) >= 2 and all(_CJK.search(word) for word in words):
            parts, how = words, "space"
        elif len(words) >= 2:
            # Latin words with spaces are usually one name; ask, never guess.
            return dict(alias=None, canonical=item, how="name", ambiguous=True, pair=(words[0], words[-1]))
        else:
            parts, how = [item], "single"
    if not parts:
        return None
    canonical = parts[-1]
    aliases = [part for part in parts[:-1] if part != canonical]
    if how == "tab" and len(parts) > 2:
        canonical, aliases = parts[1], [parts[0]] if parts[0] != parts[1] else []
    return dict(alias=aliases[0] if aliases else None, aliases=tuple(aliases), canonical=canonical, how=how,
                ambiguous=False)


def parse_term_input(text, overrides=None):
    """Entries in input order without duplicates; ``overrides`` flips
    ambiguous lines ({line: "pair"|"name"})."""
    overrides = dict(overrides or {})
    entries, seen = [], set()
    for line in str(text or "").splitlines():
        items = [line] if "\t" in line else _ITEM_SPLIT.split(line)
        for item in items:
            entry = parse_term_entry(item)
            if entry is None:
                continue
            key = item.strip()
            if entry.get("ambiguous") and overrides.get(key) == "pair":
                alias, canonical = entry["pair"]
                entry = dict(alias=alias, aliases=(alias,), canonical=canonical, how="space", ambiguous=False,
                             flipped=True)
            elif entry.get("ambiguous") and overrides.get(key) == "name":
                entry = dict(entry, ambiguous=False, confirmed=True)
            entry["source"] = key
            pairs = [(alias, entry["canonical"]) for alias in entry.get("aliases") or ()] or [(None, entry["canonical"])]
            for pair in pairs:
                if pair in seen:
                    continue
                seen.add(pair)
                entries.append(dict(entry, alias=pair[0]))
    return entries


def parse_term_lines(text):
    """[(alias_or_None, canonical)] — kept for callers of the old format."""
    return [(entry["alias"], entry["canonical"]) for entry in parse_term_input(text)]


def _occurs(key, texts):
    """Cues containing ``key`` with the resolver's ASCII word edges."""
    edge = r"(?<![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", key[:1]) else ""
    tail = r"(?![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", key[-1:]) else ""
    pattern = re.compile(edge + re.escape(key) + tail, re.I | re.ASCII)
    return sum(1 for text in texts if pattern.search(str(text or "")))


def spelling_conflicts(snapshot, texts):
    """Ambiguous spellings among the chosen libraries that occur in ``texts``."""
    from .terminology import TermResolver
    if snapshot is None:
        return []
    names = {library.id: library.name for library in snapshot.libraries}
    rows = []
    for conflict in TermResolver(snapshot).conflicts:
        if conflict.reason != "ambiguous_mapping" or len(conflict.targets) < 2:
            continue
        count = _occurs(conflict.key, texts)
        if not count:
            continue
        options = []
        for target in conflict.targets:
            libraries = []
            for library in snapshot.libraries:
                for term in library.terms:
                    sources = {source.casefold() for source in (term.canonical, *term.aliases) if source}
                    if term.confirmed and term.canonical == target and conflict.key in sources:
                        libraries.append(library.id)
                        break
            options.append(dict(target=target, library_ids=tuple(libraries),
                                names=tuple(names.get(identity, identity) for identity in libraries)))
        rows.append(dict(key=conflict.key, count=count, options=options))
    return rows


def prefer_spellings(snapshot, choices):
    """A copy of ``snapshot`` where each chosen claim outranks its tie."""
    from dataclasses import replace
    from .terminology import GlossarySnapshot
    if not choices:
        return snapshot
    libraries = []
    for library in snapshot.libraries:
        terms = []
        for term in library.terms:
            sources = {source.casefold() for source in (term.canonical, *term.aliases) if source}
            boost = any(key in sources and library.id == identity and term.canonical == target
                        for key, (identity, target) in choices.items())
            terms.append(replace(term, priority=term.priority + 100) if boost else term)
        libraries.append(replace(library, terms=tuple(terms)))
    return GlossarySnapshot(tuple(libraries))


def window_text(text, start, end, metrics, width):
    """(prefix, middle, suffix) of ``text`` fitting ``width``, keeping the
    span [start, end) visible; trimmed sides get an ellipsis."""
    prefix, middle, suffix = text[:start], text[start:end], text[end:]
    full = metrics.horizontalAdvance(text)
    if full <= width:
        return prefix, middle, suffix
    room = max(0, width - metrics.horizontalAdvance(middle) - metrics.horizontalAdvance("……"))
    left_room = room // 2
    while prefix and metrics.horizontalAdvance(prefix) > left_room:
        prefix = prefix[1:]
    if prefix != text[:start]:
        prefix = "…" + prefix
    right_room = max(0, width - metrics.horizontalAdvance(prefix + middle) - metrics.horizontalAdvance("…"))
    while suffix and metrics.horizontalAdvance(suffix) > right_room:
        suffix = suffix[:-1]
    if suffix != text[end:]:
        suffix += "…"
    return prefix, middle, suffix


def inherited_library_ids(project):
    """Libraries this project actually used, as (ids, origin).

    An explicit project choice wins; otherwise the libraries recorded in the
    recognition snapshot. Never another project's or game's selection."""
    explicit = [str(x) for x in (getattr(project, "glossary_ids", None) or ()) if str(x)]
    if explicit:
        return tuple(dict.fromkeys(explicit)), "project"
    snapshot = (getattr(project, "generation_metadata", None) or {}).get("terminology_snapshot") or {}
    recorded = [str(row.get("id") or "") for row in snapshot.get("libraries", ()) if isinstance(row, dict)]
    recorded = [identity for identity in recorded if identity]
    if recorded:
        return tuple(dict.fromkeys(recorded)), "recognition"
    return (), ""


def recorded_revisions(project):
    snapshot = (getattr(project, "generation_metadata", None) or {}).get("terminology_snapshot") or {}
    return {str(row.get("id")): str(row.get("revision") or "") for row in snapshot.get("libraries", ())
            if isinstance(row, dict) and row.get("id")}


def single_replacement(before, after):
    """(old, new) when ``after`` changes exactly one contiguous span, else None."""
    if before == after:
        return None
    changes = [op for op in SequenceMatcher(None, before, after, autojunk=False).get_opcodes() if op[0] != "equal"]
    if len(changes) != 1:
        return None
    _tag, a, b, c, d = changes[0]
    if _tag == "delete" and re.fullmatch(r"[\u4e00-\u9fff ]+", before[a:b]):
        return None  # removing a repeat (这这次 → 这次) is not a spelling to remember
    # Remember whole words (古龙 → 骨龙), not the one differing character.
    from .stutter_cleanup import word_span
    for _ in range(3):
        wa, wb = word_span(before, a, b)
        left, right = a - wa, wb - b
        xa, xb = word_span(after, c - left, d + right)
        left, right = max(left, c - xa), max(right, xb - d)
        if (a - left, b + right) == (a, b):
            break
        a, b, c, d = a - left, b + right, c - left, d + right
    old, new = before[a:b].strip(), after[c:d].strip()
    if not old or not new or len(old) > 16 or len(new) > 24:
        return None
    if changes[0][0] == "delete" and re.fullmatch(r"[一-鿿 ]+", old):
        return None  # removing a repeat (这这次 → 这次) is not a spelling to remember
    return old, new


# --------------------------------------------------------------------------
# Audio of one caption
# --------------------------------------------------------------------------

class _PreviewThread(QThread):
    decoded = Signal(str, bytes)
    failed = Signal(str, str)

    def __init__(self, request_id, plan, parent=None):
        super().__init__(parent)
        self.request_id, self.plan = request_id, plan
        self._process = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    def run(self):
        from .cue_audio_preview import PreviewUnavailable, preview_command, record_preview
        from .studio_video_track import ffmpeg_executable
        started = time.perf_counter()
        row = {"event": "proofread_preview", **self.plan.diagnostic()}
        try:
            command, receipts = preview_command(self.plan, ffmpeg_executable(), cancelled=lambda: self._cancelled)
            row.update(layers=self.plan.diagnostic()["layers"],
                       source_clocks={k: {"kind": v.get("kind"), "path": v.get("path")} for k, v in receipts.items()},
                       command=command)
            if self._cancelled:
                raise InterruptedError("superseded")
            self._process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                             creationflags=0x08000000 if os.name == "nt" else 0)
            payload, errors = self._process.communicate(timeout=60)
            if self._cancelled:
                raise InterruptedError("superseded")
            if self._process.returncode != 0 or not payload:
                raise RuntimeError(errors.decode("utf-8", "replace").strip()[-200:] or "ffmpeg")
            row.update(outcome="decoded", pcm_bytes=len(payload),
                       decoded_ms=round(len(payload) / 4 / 48), elapsed_ms=round((time.perf_counter() - started) * 1000))
            record_preview(row)
            self.decoded.emit(self.request_id, bytes(payload))
        except InterruptedError:
            row.update(outcome="superseded", elapsed_ms=round((time.perf_counter() - started) * 1000))
            record_preview(row)
        except PreviewUnavailable as exc:
            row.update(outcome="unavailable", error=str(exc))
            record_preview(row)
            self.failed.emit(self.request_id, str(exc))
        except Exception as exc:  # reported in the page, never raised
            row.update(outcome="failed", error=str(exc)[:400])
            record_preview(row)
            self.failed.emit(self.request_id, tr("这一句的音频无法读取：{reason}", reason=str(exc)[:160]))


class CuePlayer(QObject):
    """Plays one caption's audio as export hears it; newest request wins."""

    state_changed = Signal(str, str)  # cue_id, 'loading' | 'playing' | ''
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sink = None
        self._buffer = None
        self._thread = None
        self._threads = set()
        self.request_id = ""
        self.cue_id = ""
        self.last_plan = None
        self.volume = 1.0
        self._expected_ms = 0
        self._extensions = 0
        # QAudioSink.stateChanged cannot be delivered to Python here
        # ("Cannot call meta function _sink_state(QAudio::State)"), so the
        # old player never noticed the end of a clip. The decoded length
        # and the device's own progress decide when playback is over.
        self._end_timer = QTimer(self)
        self._end_timer.setSingleShot(True)
        self._end_timer.timeout.connect(self._check_finished)

    def play(self, project, cue_id):
        from .cue_audio_preview import PreviewUnavailable, plan_cue_preview, record_preview
        self.stop()
        try:
            plan = plan_cue_preview(project, cue_id)
        except PreviewUnavailable as exc:
            record_preview({"event": "proofread_preview", "cue_id": str(cue_id),
                            "project_id": str(getattr(project, "project_id", "")), "outcome": "unavailable",
                            "error": str(exc)})
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(tr("这一句的音频无法读取：{reason}", reason=str(exc)[:160]))
            return
        self.last_plan = plan
        self.request_id, self.cue_id = plan.request_id, str(cue_id)
        self.state_changed.emit(self.cue_id, "loading")
        thread = _PreviewThread(plan.request_id, plan, self)
        thread.decoded.connect(self._start)
        thread.failed.connect(self._decode_failed)
        thread.finished.connect(lambda done=thread: self._thread_finished(done))
        self._thread = thread
        self._threads.add(thread)
        thread.start()

    def _thread_finished(self, thread):
        self._threads.discard(thread)
        if self._thread is thread:
            self._thread = None
        thread.deleteLater()

    def _decode_failed(self, request_id, message):
        if request_id == self.request_id:
            cue_id, self.cue_id, self.request_id = self.cue_id, "", ""
            self.state_changed.emit(cue_id, "")
            self.failed.emit(message)

    def _ensure_sink(self):
        if self._sink is None:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
            fmt = QAudioFormat()
            fmt.setSampleRate(48000)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            # One sink for the page's lifetime; clips only swap its buffer.
            self._sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self)
        return self._sink

    def _start(self, request_id, payload):
        if request_id != self.request_id:
            return  # an older click; a newer request owns the player
        sink = self._ensure_sink()
        sink.stop()
        previous, self._buffer = self._buffer, QBuffer(self)
        self._buffer.setData(QByteArray(payload))
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        if previous is not None:
            previous.close()
            previous.deleteLater()
        sink.setVolume(float(self.volume))
        sink.start(self._buffer)
        self._expected_ms = int(len(payload) / 4 / 48)
        self._extensions = 0
        self._end_timer.start(self._expected_ms + 150)
        self.state_changed.emit(self.cue_id, "playing")

    def _check_finished(self):
        if not self.cue_id or self._sink is None:
            return
        played = int(self._sink.processedUSecs() / 1000)
        if played + 60 < self._expected_ms and self._extensions < 3:
            # The device started late; wait for what it has not played yet.
            self._extensions += 1
            self._end_timer.start(max(80, self._expected_ms - played + 80))
            return
        self.stop()

    def stop(self):
        self._end_timer.stop()
        if self._thread is not None:
            try:
                self._thread.cancel()
            except RuntimeError:
                pass
            self._thread = None
        if self._sink is not None:
            self._sink.stop()
        if self.cue_id:
            cue_id, self.cue_id = self.cue_id, ""
            self.request_id = ""
            self.state_changed.emit(cue_id, "")

    def shutdown(self):
        """Stop and wait for decoders so no thread outlives the page."""
        self.stop()
        for thread in list(self._threads):
            try:
                thread.cancel()
                thread.wait(3000)
            except RuntimeError:
                pass


# Back-compatibility name for older callers.
ClipPlayer = CuePlayer


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------

def _issue(kind, span, original, replacement, *, checked, reason="", hit=None, options=(), evidence=""):
    return dict(kind=kind, span=tuple(span), original=original, replacement=replacement, checked=bool(checked),
                default=bool(checked), reason=reason, hit=hit, options=tuple(options), evidence=evidence,
                stale=False, reviewed=False)


def issue_key(row_id, issue):
    return (row_id, issue["kind"] if issue["kind"] != "near" else "term", issue["span"], issue["original"],
            issue["replacement"])


def row_source_text(row):
    return row["base"]


def row_effective_text(row, stutter=True):
    """The caption as it is in the project. Every action on the page is
    written at once (2026-10-10), so nothing is waiting to be applied."""
    return row["base"]


def actionable(issue, stutter=True):
    return (issue["kind"] != "suspect" and not issue["stale"]
            and (stutter or issue["kind"] != "stutter"))


def relocate_issue(issue, text):
    """Re-anchor ``issue`` to ``text`` or mark it stale (never reuse old indices).

    A name marker whose word is gone was answered by the edit itself."""
    a, b = issue["span"]
    if text[a:b] == issue["original"] and issue["original"]:
        return True
    hits = [m.start() for m in re.finditer(re.escape(issue["original"]), text)] if issue["original"] else []
    if len(hits) == 1:
        issue["span"] = (hits[0], hits[0] + len(issue["original"]))
        return True
    issue["stale"], issue["checked"] = True, False
    return False


TERM_KINDS = {"term", "near", "ai", "ai_review", "association", "consistency", "evidence"}
# Proposals from the page's own background checks, not from the glossary match.
LOCAL_KINDS = {"stutter", "merge", "consistency", "evidence"}


def resolve_overlaps(row):
    """One ticked proposal per character span; the higher-priority one wins.

    A stammer guess yields to any glossary/AI candidate on the same
    characters (对又又盾 may be 优优盾): it stays available, unticked."""
    for issue in row["issues"]:
        if issue["kind"] == "stutter" and issue["checked"] and not issue["reviewed"]:
            a, b = issue["span"]
            if any(other["kind"] in TERM_KINDS and not other["stale"] and other["span"][0] < max(b, a + 1) + 1
                   and a - 1 < other["span"][1] for other in row["issues"]):
                issue["checked"] = False
    taken = []
    for issue in sorted(row["issues"], key=lambda item: PRIORITY.get(item["kind"], 8)):
        if not issue["checked"] or issue["stale"] or issue["kind"] == "suspect":
            continue
        a, b = issue["span"]
        if any(x < b and a < y or (a == b == x) for x, y in taken):
            issue["checked"] = False
            continue
        taken.append((a, max(b, a + 1) if a == b else b))


def _word_char(ch):
    return bool(ch) and ch.isascii() and (ch.isalnum() or ch == "_")


def _expand_ascii(text, a, b):
    """Grow [a, b) over the ASCII words it touches (BerLIN, never just LIN)."""
    if a < b:
        if _word_char(text[a]):
            while a > 0 and _word_char(text[a - 1]):
                a -= 1
        if _word_char(text[b - 1]):
            while b < len(text) and _word_char(text[b]):
                b += 1
    elif 0 < a < len(text) and _word_char(text[a - 1]) and _word_char(text[a]):
        while a > 0 and _word_char(text[a - 1]):
            a -= 1
        while b < len(text) and _word_char(text[b]):
            b += 1
    return a, b


def text_changes(before, after):
    """The real differences between two texts: [(i1, i2, j1, j2)], ``before[i1:i2]``
    became ``after[j1:j2]``.

    2026-10-10 (user, 魔草巫灵 → 魔草乌灵 was described as 草巫 → 草乌): the one
    diff behind every proposal display — the marked characters in the
    sentence, the replacement under them, the short "巫 → 乌" line and the
    range adopting writes. CJK characters are compared one by one, so an
    unchanged neighbour is never part of a change; insertions, deletions,
    unequal lengths, repeated characters and several separate changes come
    out as they are. Latin words stay whole (BerLIN, never just LIN)."""
    if before == after:
        return []
    changes = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        a, b = _expand_ascii(before, i1, i2)
        c, d = _expand_ascii(after, j1, j2)
        # The text around a change is the same on both sides: grow both alike.
        left, right = max(i1 - a, j1 - c), max(b - i2, d - j2)
        left = min(left, i1, j1)
        right = min(right, len(before) - i2, len(after) - j2)
        i1, i2, j1, j2 = i1 - left, i2 + right, j1 - left, j2 + right
        if changes and (i1 <= changes[-1][1] or j1 <= changes[-1][3]):
            p1, _p2, q1, _q2 = changes[-1]
            changes[-1] = (p1, max(i2, changes[-1][1]), q1, max(j2, changes[-1][3]))
            continue
        changes.append((i1, i2, j1, j2))
    return changes


def find_spans(text, needle):
    """[(start, end)] of ``needle`` in ``text``: literal (never a regular
    expression), letters in any case, left to right without overlaps."""
    if not needle or not text:
        return []
    return [(m.start(), m.end()) for m in re.finditer(re.escape(needle), text, re.IGNORECASE)]


def replace_spans(text, spans, new):
    """``text`` with each [start, end) replaced by ``new`` exactly as typed;
    right to left, so earlier positions never shift."""
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + new + text[end:]
    return text


def change_summary(before, after, separator="，"):
    """「巫 → 乌」: only what really changes, for the short proposal line."""
    parts = []
    for i1, i2, j1, j2 in text_changes(before, after):
        old, new = before[i1:i2], after[j1:j2]
        if not new:
            parts.append(tr("删去「{word}」", word=old))
        elif not old:
            parts.append(tr("加上「{word}」", word=new))
        else:
            parts.append(f"{old} → {new}")
    return separator.join(parts)


def suggestion_marks(text, issue):
    """[(start, end, shown)] of ``issue`` inside ``text``: one mark per real
    change. Not adopted: the wrong characters with the replacement shown
    under them. Adopted: the new characters with the old ones under them."""
    a, _b = issue["span"]
    original, replacement = issue["original"], issue["replacement"]
    if issue["checked"]:
        # In the project now: the replacement is what the line shows.
        return [(a + j1, a + j2, original[i1:i2]) for i1, i2, j1, j2 in text_changes(original, replacement)]
    return [(a + i1, a + i2, replacement[j1:j2]) for i1, i2, j1, j2 in text_changes(original, replacement)]


def suggestion_mark(text, issue):
    """(start, end, shown) covering every change of ``issue`` (one box)."""
    marks = suggestion_marks(text, issue)
    a, b = issue["span"]
    if not marks:
        return (a, a + len(issue["replacement"]), issue["original"]) if issue["checked"] else (a, b, issue["replacement"])
    if len(marks) == 1:
        return marks[0]
    start, end = marks[0][0], marks[-1][1]
    if issue["checked"]:
        return start, end, issue["original"][start - a:len(issue["original"]) - (a + len(issue["replacement"]) - end)]
    return start, end, issue["replacement"][start - a:len(issue["replacement"]) - (b - end)]


# --------------------------------------------------------------------------
# Whole names: library terms and reference names (skills, characters…)
# --------------------------------------------------------------------------

CATEGORY_NAMES = {"skill": "技能名", "技能": "技能名", "spirit": "精灵名", "精灵": "精灵名", "character": "角色名",
                  "角色": "角色名", "人物": "人物名", "选手 ID": "选手 ID", "Boss": "Boss 名", "物品": "物品名",
                  "地点": "地名", "阵营": "阵营名", "事件": "事件名"}
_LEXICON_CACHE = {}


def _lexicon_categories(path):
    """{name: category} of one reference lexicon, read once per file version."""
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        return {}
    cached = _LEXICON_CACHE.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        payload = {}
    category = str(payload.get("category") or "") if isinstance(payload, dict) else ""
    names = {}
    for entry in (payload.get("entries", ()) if isinstance(payload, dict) else ()):
        if isinstance(entry, dict) and entry.get("name"):
            names[str(entry["name"])] = category
    _LEXICON_CACHE[path] = (stamp, names)
    return names


class TermIndex:
    """Whole names of the chosen libraries: confirmed spellings and the
    reference names (skills, spirits, characters…) the libraries list.

    Used to keep one name together (疫病吐息 is one skill, never two separate
    proposals) and to recognize names that are already written right."""

    def __init__(self, names=()):
        self.categories = {}
        for name, category in names:
            name = str(name or "").strip()
            if len(name) >= 2 and name not in self.categories:
                self.categories[name] = str(category or "")
        self._by_first = {}
        for name in sorted(self.categories, key=len, reverse=True):
            self._by_first.setdefault(name[0], []).append(name)
        self.version = digest_names(self.categories)

    @classmethod
    def from_snapshot(cls, snapshot, legacy=None):
        names = []
        if snapshot is None:
            return cls()
        for library in snapshot.libraries:
            for term in library.terms:
                if term.confirmed and term.canonical:
                    names.append((term.canonical, term.category))
            categories = {}
            if legacy is not None and library.profile_json:
                try:
                    profile = json.loads(library.profile_json)
                    for path in getattr(legacy, "_profile_lexicon_paths_for", lambda _p: [])(profile):
                        categories.update(_lexicon_categories(path))
                except (ValueError, TypeError, OSError):
                    pass
            names.extend((name, categories.get(name, "")) for name in library.reference_terms)
        return cls(names)

    def __bool__(self):
        return bool(self.categories)

    def __contains__(self, name):
        return name in self.categories

    def label(self, name):
        category = self.categories.get(name, "")
        return CATEGORY_NAMES.get(category, "名字" if category in {"", "term", "game_term", "其他"} else category)

    def occurrences(self, text):
        """[(start, end, name)] of names written exactly as the library
        spells them (berlin is not BerLIN written right); longest first,
        never overlapping."""
        found, position = [], 0
        while position < len(text):
            for name in self._by_first.get(text[position], ()):
                if text.startswith(name, position):
                    found.append((position, position + len(name), name))
                    position += len(name)
                    break
            else:
                position += 1
        return found


def digest_names(categories):
    return hash(tuple(sorted(categories.items())))


def _overlaps(a, b, c, d):
    """Spans [a, b) and [c, d) touch the same characters (an insertion point
    inside the other span counts)."""
    if a == b:
        return c < a < d or (c == d == a)
    if c == d:
        return a < c < b
    return a < d and c < b


def issue_groups(row, terms=None, stutter=True):
    """One decision per group of proposals of a caption.

    2026-10-10 (user, 疫病吐息 split into 疫病 → 一命 and 吐息 → 突袭, each with
    its own box, source and long reason): proposals inside one whole name
    of the libraries — written right now, or formed only when they are
    adopted together — are one group with one adopt/ignore action; readings
    for the same characters are options of one group. Unrelated neighbours
    stay separate. Each group says whether it needs a decision (pending):
    a name the library already knows is never "recommended" away, and the
    partial agreements inside a group are never presented as the whole."""
    terms = terms or TermIndex()
    key = (row["base"], terms.version, bool(stutter),
           tuple((i["kind"], i["span"], i["original"], i["replacement"], i["checked"], i["stale"], i["reviewed"],
                  i.get("default")) for i in row["issues"]))
    cached = row.get("_groups")
    if cached is not None and cached[0] == key:
        return cached[1]
    text = row["base"]
    usable = [index for index, issue in enumerate(row["issues"])
              if actionable(issue, stutter) and not issue["stale"]]
    owner = {index: index for index in usable}

    def find(index):
        while owner[index] != index:
            owner[index] = owner[owner[index]]
            index = owner[index]
        return index

    def join(x, y):
        x, y = find(x), find(y)
        if x != y:
            owner[max(x, y)] = min(x, y)

    # Groups are found on the caption as it reads with every proposal taken
    # back, so adopting a group (一命突袭 contains the skill 突袭) or undoing it
    # never splits or merges it.
    adopted = sorted((x for x in usable if row["issues"][x]["checked"]), key=lambda x: row["issues"][x]["span"][0])
    base = rewrite_text(text, [row["issues"][x] for x in adopted], adopted=False)

    def base_span(x):
        issue = row["issues"][x]
        a = issue["span"][0]
        shift = sum(len(row["issues"][y]["original"]) - len(row["issues"][y]["replacement"])
                    for y in adopted if y != x and row["issues"][y]["span"][0] < a)
        return a + shift, a + shift + len(issue["original"])

    def to_text(position):
        """A position of ``base`` in the caption as it reads now."""
        out = position
        for y in adopted:
            a, b = base_span(y)
            if b <= position:
                out += len(row["issues"][y]["replacement"]) - len(row["issues"][y]["original"])
        return out

    spans = {x: base_span(x) for x in usable}
    # Readings of the same characters are options of one decision.
    for x in usable:
        for y in usable:
            if x < y and _overlaps(*spans[x], *spans[y]):
                join(x, y)
    # Inside one name the library knows.
    names = terms.occurrences(base) if terms else []
    anchors = {}
    for x in usable:
        a, b = spans[x]
        for start, end, name in names:
            if start <= a and b <= end and (a < b or start < a < end):
                anchors.setdefault((start, end, name), []).append(x)
                break
    for members in anchors.values():
        for other in members[1:]:
            join(members[0], other)
    # Proposals that only together write a name of the library.
    formed = {}
    if terms:
        for x in usable:
            for y in usable:
                if x >= y or find(x) == find(y):
                    continue
                (a, b), (c, d) = spans[x], spans[y]
                if _overlaps(a, b, c, d) or max(a, c) - min(b, d) > 2:
                    continue
                pair = [dict(row["issues"][x], span=spans[x], checked=False),
                        dict(row["issues"][y], span=spans[y], checked=False)]
                combined = rewrite_text(base, pair, adopted=True)
                lo, hi = min(a, c), max(b, d)
                shift = len(combined) - len(base)
                for start, end, name in terms.occurrences(combined):
                    if start <= lo and hi + shift <= end and name not in base:
                        join(x, y)
                        formed[find(x)] = name
                        break
    groups = {}
    for x in usable:
        groups.setdefault(find(x), []).append(x)
    result = []
    for root, members in sorted(groups.items(), key=lambda item: min(spans[i][0] for i in item[1])):
        members.sort(key=lambda i: (spans[i][0], PRIORITY.get(row["issues"][i]["kind"], 8)))
        issues = [row["issues"][i] for i in members]
        own = [spans[i] for i in members]
        start, end = min(a for a, _b in own), max(b for _a, b in own)
        anchor = next(((s, e, name) for (s, e, name), xs in anchors.items() if set(xs) & set(members)), None)
        if anchor is not None:
            start, end = min(start, anchor[0]), max(end, anchor[1])
        options = any(_overlaps(*own[i], *own[j]) for i in range(len(own)) for j in range(i + 1, len(own)))
        checked = [issue["checked"] for issue in issues]
        if all(checked):
            state = "adopted"
        elif any(checked):
            state = "partial"
        else:
            state = "open"
        before = rewrite_text(text, [issue for issue in issues if issue["checked"]], adopted=False)
        after = None if options else rewrite_text(text, issues, adopted=True)
        name_now = anchor[2] if anchor is not None else ""
        name_after = formed.get(root, "")
        pending = bool(options)
        if not pending and name_now:
            # The library's name was written right here. Asking is right
            # unless the group writes another name of the library in its
            # place (CHIOCHOO → CHICHOO by the user's spelling choice).
            changed = rewrite_text(base, [dict(issue, checked=False, span=spans[i])
                                          for i, issue in zip(members, issues)], adopted=True)
            s, e = anchor[0], anchor[1]
            e_after = e + len(changed) - len(base)
            if changed[s:e_after] != name_now:
                replaced = next((name for a, b, name in terms.occurrences(changed) if a <= s and e_after <= b), "")
                pending = not replaced
                name_after = name_after or replaced
        recommended = bool(not pending and all(issue.get("default") for issue in issues)
                           and (len(issues) == 1 or name_after))
        result.append(dict(parts=members, span=(to_text(start), to_text(end)), name=name_now, formed=name_after,
                           options=options, state=state, pending=pending, recommended=recommended, before=before,
                           after=after, reviewed=all(issue["reviewed"] for issue in issues if not issue["checked"])
                           if state != "adopted" else False))
    row["_groups"] = (key, result)
    return result


def rewrite_text(text, issues, *, adopted):
    """``text`` with every one of ``issues`` adopted (or every one reverted),
    from the positions they have in ``text`` now; right to left, so earlier
    positions never shift."""
    for issue in sorted(issues, key=lambda item: item["span"][0], reverse=True):
        a = issue["span"][0]
        now = issue["replacement"] if issue["checked"] else issue["original"]
        new = issue["replacement"] if adopted else issue["original"]
        if text[a:a + len(now)] == now:
            text = text[:a] + new + text[a + len(now):]
    return text


def group_of(row, index, terms=None, stutter=True):
    """The group that holds proposal ``index`` of ``row`` (or None)."""
    return next((group for group in issue_groups(row, terms, stutter) if index in group["parts"]), None)


def applied_marks(origin, text):
    """Changes made on this page, as marks on ``text`` with the old wording."""
    marks = []
    if origin == text:
        return marks
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, origin, text, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        x, y = _expand_ascii(text, j1, j2)
        left, right = j1 - x, y - j2
        old = origin[max(0, i1 - left):i2 + right]
        if marks and x <= marks[-1]["end"]:
            last = marks[-1]
            last["end"] = max(last["end"], y)
            last["below"] = origin[last["old_start"]:i2 + right]
            continue
        marks.append(dict(start=x, end=y, below=old, old_start=max(0, i1 - left), style="applied", ref=None))
    return marks


def _plain_units(text, start, end, units):
    index = start
    while index < end:
        ch = text[index]
        if _word_char(ch):
            stop = index
            while stop < end and _word_char(text[stop]):
                stop += 1
            while stop < end and text[stop] == " ":
                stop += 1
            units.append(dict(top=text[index:stop], below="", mark=None, start=index, end=stop))
            index = stop
            continue
        units.append(dict(top=ch, below="", mark=None, start=index, end=index + 1))
        index += 1


def line_units(text, marks):
    """Atomic layout units: plain characters/words and one unit per mark."""
    units = []
    position = 0
    for mark in sorted(marks, key=lambda item: (item["start"], item["end"])):
        if mark["start"] < position:
            continue  # overlapping proposals are listed below the sentence only
        _plain_units(text, position, mark["start"], units)
        units.append(dict(top=text[mark["start"]:mark["end"]], below=mark["below"], mark=mark,
                          start=mark["start"], end=mark["end"]))
        position = mark["end"]
    _plain_units(text, position, len(text), units)
    return units


def _font_advance_cache(metrics):
    """Bound repeated shaping work to this widget's exact font metrics.

    Keep short words/characters only; a long unbroken caption must not fill
    a cache with thousands of large strings. The owner replaces these caches
    with its metrics on font/zoom changes and clears them with the document.
    """
    cached = lru_cache(maxsize=2048)(metrics.horizontalAdvance)

    def advance(text):
        return cached(text) if len(text) <= 128 else metrics.horizontalAdvance(text)

    advance.cache_clear = cached.cache_clear
    return advance


def wrap_units(units, width, top_metrics, below_metrics, pad, *, advances=None):
    """Greedy line breaking; a marked unit is as wide as its wider half."""
    top_advance, below_advance = advances or (top_metrics.horizontalAdvance, below_metrics.horizontalAdvance)
    lines, line, x = [], [], 0.0
    for unit in units:
        top_w = top_advance(unit["top"]) if unit["top"] else 0.0
        if unit["mark"] is None:
            w = top_w
        else:
            below_w = below_advance(unit["below"]) if unit["below"] else 0.0
            w = max(top_w, below_w, pad * 1.6) + 2 * pad
        unit["w"], unit["top_w"] = w, top_w
        if line and x + w > width:
            lines.append(line)
            line, x = [], 0.0
        unit["x"] = x
        line.append(unit)
        x += w
    if line or not lines:
        lines.append(line)
    return lines


class CaptionReviewList(QWidget):
    """Painted caption rows of varying height (one row per caption).

    Each row shows the caption as it is in the project. A proposal marks its
    characters in place and writes only the replacement right under them
    (古 over 骨); changes already written on this page are marked in the
    line with the old wording struck through underneath. Lines wrap; all
    metrics follow the interface zoom.

    Proposals are listed per group (``issue_groups``): one line with one
    adopt box, the short real change (巫 → 乌), a compact source and state;
    reasons open under 详情. The caption text can be selected with the
    mouse (2026-10-10, user: select 布克 in a search result and batch
    replace it); search hits are highlighted, and while replacing each hit
    shows its replacement and can be excluded with a click."""

    BODY_PX = 19
    BELOW_PX = 16
    SMALL_PX = 14
    LABEL_PX = 14

    play_requested = Signal(str)
    edit_requested = Signal(str)
    edit_committed = Signal(str, str)
    issue_toggled = Signal(str, int)
    remember_requested = Signal(str)
    revert_requested = Signal(str)
    context_requested = Signal(str, object, object)  # cue_id, target, global QPoint
    group_dismissed = Signal(str, int)  # cue_id, a proposal index of the group
    group_manual = Signal(str, int)
    hit_toggled = Signal(str, int)  # cue_id, start of the search hit
    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("proofreadSuggestions")
        self.rows = []
        self.visible = []
        self.heights = []
        self.offsets = [0]
        self.stutter = True
        self.terms = TermIndex()
        # Search: needle, replacement preview (None = not replacing) and
        # excluded hits {(cue_id, start)}.
        self.find = dict(needle="", replace=None, excluded=frozenset())
        self.expanded = set()  # (cue_id, first proposal index) of opened 详情
        self.remember_targets = {}
        self.current = ""
        self.playing = ("", "")
        self.empty_text = ""
        self._offset = 0
        self._hover = -1
        self._hit_boxes = []
        self._chars = {}  # cue_id -> [(top, bottom, [(left, right, index)])] of the painted caption text
        self._selection = None  # (cue_id, anchor, caret)
        self._press = None
        # Hit boxes come from the last paint. A click that arrives after a
        # scroll/filter but before the repaint (a busy UI) would otherwise
        # hit the row that used to be there (2026-10-10).
        self._serial = self._painted_serial = 0
        self._painted_text = {}
        self._editing = ""
        self._layout_cache = {}
        self._zoom = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.bar = QScrollBar(Qt.Orientation.Vertical, self)
        self.bar.valueChanged.connect(self._scrolled)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(120)
        self.editor = QLineEdit(self)
        self.editor.setObjectName("proofreadInlineEditor")
        self.editor.hide()
        self.editor.installEventFilter(self)
        self._metrics()

    # metrics ----------------------------------------------------------
    def _metrics(self):
        """Fonts and row geometry at the current interface zoom."""
        from .ui_zoom import zoom_factor
        zoom = zoom_factor()
        key = (zoom, self.font().key())
        if key == getattr(self, "_metrics_key", None):
            return
        self._metrics_key = key
        self._zoom = zoom
        z = lambda value: max(1, round(value * zoom))
        base = QFont(self.font())
        self.body = QFont(base); self.body.setPixelSize(z(self.BODY_PX))
        self.below = QFont(base); self.below.setPixelSize(z(self.BELOW_PX)); self.below.setWeight(QFont.Weight.DemiBold)
        self.small = QFont(base); self.small.setPixelSize(z(self.SMALL_PX))
        self.label_font = QFont(base); self.label_font.setPixelSize(z(self.LABEL_PX)); self.label_font.setWeight(QFont.Weight.DemiBold)
        self.mono = QFont(base)
        self.mono.setFamilies([p.strip().strip("'\"") for p in MONO_FONT_STACK.split(",")])
        self.mono.setPixelSize(z(self.SMALL_PX))
        self.body_metrics = QFontMetricsF(self.body)
        self.below_metrics = QFontMetricsF(self.below)
        self._layout_advances = (_font_advance_cache(self.body_metrics), _font_advance_cache(self.below_metrics))
        self.small_metrics = QFontMetricsF(self.small)
        self.label_metrics = QFontMetricsF(self.label_font)
        self.mono_metrics = QFontMetricsF(self.mono)
        self.PAD = z(8)
        self.LINE = int(self.body_metrics.height() + z(10))
        self.BELOW = int(self.below_metrics.height() + z(8))
        self.ISSUE = int(max(self.small_metrics.height(), z(20)) + z(10))
        self.DETAIL = int(self.small_metrics.height() + z(8))
        self.ACTION = z(36)
        self.MARK_PAD = z(3)
        self.time_w = self.mono_metrics.horizontalAdvance("00:00:00.0") + z(8)
        self.play_d = z(28)
        self.number_w = self.small_metrics.horizontalAdvance("#0000") + z(6)
        self.speaker_w = z(70)
        self.META_LINE = int(max(self.small_metrics.height(), self.mono_metrics.height()) + z(10))
        # time · play on the first line, number · speaker under it, the
        # caption's state under that: the caption itself gets the full width.
        self.META_W = int(max(self.time_w + self.play_d + z(6), self.number_w + self.speaker_w,
                              self.small_metrics.horizontalAdvance(tr("还原这句")) + z(4)))
        self.TEXT_X = int(z(14) + self.META_W + z(18))
        self.EDIT_W = int(self.label_metrics.horizontalAdvance(tr("修改")) + z(34))
        self.editor.setFont(self.body)
        self._layout_cache.clear()

    def changeEvent(self, event):
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.FontChange and self.rows:
            self.apply_ui_zoom(None)

    def apply_ui_zoom(self, _factor):
        """Interface zoom changed: keep the caption at the top in place."""
        anchor = self._top_anchor()
        self._metrics()
        self._layout_rows()
        self._restore_anchor(anchor)
        self._place_editor()

    def _top_anchor(self):
        slot = self._slot_at(0)
        if slot < 0:
            return None
        top = self.offsets[slot]
        span = max(1, self.offsets[slot + 1] - top)
        return self.rows[self.visible[slot]]["cue_id"], (self._offset - top) / span

    def _restore_anchor(self, anchor):
        if anchor is None:
            return
        cue_id, fraction = anchor
        slot = self.slot_of(cue_id)
        if slot < 0:
            return
        top = self.offsets[slot]
        span = max(1, self.offsets[slot + 1] - top)
        self.bar.setValue(int(top + fraction * span))

    # model ------------------------------------------------------------
    def set_rows(self, rows, visible=None):
        self.rows = rows
        self._layout_cache.clear()
        for advance in self._layout_advances:
            advance.cache_clear()
        self.set_visible(list(range(len(rows))) if visible is None else visible)

    def set_visible(self, visible):
        self.visible = list(visible)
        self._layout_rows()

    def row_by_id(self, cue_id):
        return next((row for row in self.rows if row["cue_id"] == cue_id), None)

    def _visible_issues(self, row):
        return [(index, issue) for index, issue in enumerate(row["issues"])
                if (self.stutter or issue["kind"] != "stutter") and not (issue["stale"] and issue.get("hidden"))]

    def _text_width(self):
        return max(120.0, self._right() - self.TEXT_X - round(10 * (self._zoom or 1)))

    def groups(self, row):
        return issue_groups(row, self.terms, self.stutter)

    def _hits(self, row):
        needle = self.find.get("needle") or ""
        return find_spans(row["base"], needle) if needle else []

    def _marks(self, row, groups=None):
        """Inline marks: search hits, changes made here, then proposals by
        priority — one mark per real change of a proposal."""
        text = row["base"]
        marks = []
        replace = self.find.get("replace")
        excluded = self.find.get("excluded") or ()
        for start, end in self._hits(row):
            out = (row["cue_id"], start) in excluded
            style = ("find_excluded" if out else "find_replace") if replace is not None else "find"
            below = (tr("不替换") if out else (replace if replace else tr("删去"))) if replace is not None else ""
            marks.append(dict(start=start, end=end, below=below, style=style, ref=start))
        taken = [(mark["start"], max(mark["end"], mark["start"] + 1)) for mark in marks]
        for mark in applied_marks(row.get("origin", text), text):
            if not any(a < max(mark["end"], mark["start"] + 1) and mark["start"] < b for a, b in taken):
                marks.append(mark)
                taken.append((mark["start"], max(mark["end"], mark["start"] + 1)))
        groups = self.groups(row) if groups is None else groups
        group_by_part = {index: group for group in groups for index in group["parts"]}
        ranked = sorted(self._visible_issues(row), key=lambda pair: (PRIORITY.get(pair[1]["kind"], 8), pair[0]))
        for index, issue in ranked:
            if issue["stale"] or issue["checked"] and issue["kind"] == "suspect":
                continue
            group = group_by_part.get(index)
            if issue["kind"] == "suspect":
                spans = [(issue["span"][0], issue["span"][1], "")]
                style = "suspect"
            elif issue["checked"]:
                spans = suggestion_marks(text, issue)
                # Shown by the applied diff already when it came from this page.
                if any(any(a < max(end, start + 1) and start < b for a, b in taken) for start, end, _ in spans):
                    for mark in marks:
                        if mark["style"] == "applied" and any(
                                mark["start"] < max(end, start + 1) and start < max(mark["end"], mark["start"] + 1)
                                for start, end, _ in spans):
                            mark["ref"] = index
                    continue
                style = "applied"
            else:
                spans = suggestion_marks(text, issue)
                # A name the library already knows is not marked as an error.
                style = ("dismissed" if issue["reviewed"] else
                         "pending" if group is not None and group["pending"] else "suggest")
            for start, end, below in spans:
                kind = style
                if style not in {"suspect", "applied"}:
                    if issue["replacement"] == "" or start < end and below == "":
                        kind += "_delete"
                        below = tr("删去")
                    elif start == end:
                        kind += "_insert"
                if any(a < max(end, start + 1) and start < b for a, b in taken):
                    continue
                taken.append((start, max(end, start + 1)))
                marks.append(dict(start=start, end=end, below=below, style=kind, ref=index))
        return marks

    def _row_key(self, row, width=None):
        return (row["cue_id"], row["base"], row.get("origin"), self._zoom,
                int(self._text_width() if width is None else width), self.stutter,
                self.terms.version, self.find.get("needle"), self.find.get("replace"),
                tuple(sorted(start for cue, start in self.find.get("excluded") or () if cue == row["cue_id"])),
                tuple(sorted(index for cue, index in self.expanded if cue == row["cue_id"])),
                tuple((i["kind"], i["span"], i["checked"], i["stale"], i["reviewed"], i["replacement"],
                       i.get("default")) for i in row["issues"]))

    def _row_layout(self, row):
        width = self._text_width()
        key = self._row_key(row, width)
        cached = self._layout_cache.get(row["cue_id"])
        if cached is not None and cached[0] == key:
            return cached[1]
        groups = self.groups(row)
        units = line_units(row["base"], self._marks(row, groups))
        lines = wrap_units(units, width, self.body_metrics, self.below_metrics, self.MARK_PAD,
                           advances=self._layout_advances)
        heights = [self.LINE + (self.BELOW if any(u["mark"] is not None and (u["below"] or u["mark"]["style"].endswith("_delete"))
                                                  for u in line) else 0) for line in lines]
        last_end = (lines[-1][-1]["x"] + lines[-1][-1]["w"]) if lines and lines[-1] else 0.0
        gap = round(12 * (self._zoom or 1))
        edit_newline = last_end + gap + self.EDIT_W > width
        if edit_newline:
            heights.append(self.LINE)
        entries = []
        for group in groups:
            entries.append(("group", group))
            if (row["cue_id"], group["parts"][0]) in self.expanded:
                entries.extend(("detail", (group, line)) for line in self._detail_lines(row, group))
        for index, issue in self._visible_issues(row):
            if issue["kind"] == "suspect" and not issue["stale"]:
                entries.append(("suspect", index))
        layout = dict(lines=lines, heights=heights, edit_newline=edit_newline, last_end=last_end, entries=entries)
        self._layout_cache[row["cue_id"]] = (key, layout)
        return layout

    def _detail_lines(self, row, group):
        """Why a group is proposed, one line per source: shown under 详情."""
        lines = []
        issues = [row["issues"][index] for index in group["parts"]]
        for index, issue in zip(group["parts"], issues):
            label = tr(KIND_LABELS.get(issue["kind"], issue["kind"]))
            if issue["replacement"] == "":
                change = tr("删去「{word}」", word=issue["original"])
            else:
                change = change_summary(issue["original"], issue["replacement"])
            reason = tr(issue["reason"]) if issue.get("reason") else tr(KIND_TIPS.get(issue["kind"], ""))
            text = f"{label}：{change}"
            if reason:
                text += " · " + reason
            if issue.get("evidence"):
                text += " · " + str(issue["evidence"])
            lines.append(dict(text=text, index=index, option=group["options"]))
        if group["name"]:
            label = tr(self.terms.label(group["name"]))
            if group["pending"] and not group["options"]:
                lines.append(dict(text=tr("「{name}」是所选词库里的{label}；改后不在词库里，先试听再决定", name=group["name"],
                                          label=label), index=None))
            else:
                lines.append(dict(text=tr("「{name}」是所选词库里的{label}", name=group["name"], label=label), index=None))
        if group["formed"] and group["formed"] != group["name"]:
            lines.append(dict(text=tr("这几处一起改，正好是词库里的{label}「{name}」", name=group["formed"],
                                      label=tr(self.terms.label(group["formed"]))), index=None))
        if len(issues) > 1 and not group["options"] and len({issue["kind"] for issue in issues}) > 1:
            lines.append(dict(text=tr("各来源只说明自己那几个字，不代表整个词都得到确认"), index=None))
        lines.append(dict(text=tr("手动改写这一处…"), index=None, manual=True))
        return lines

    def _meta_lines(self, row):
        lines = 2
        if row["base"] != row.get("origin", row["base"]):
            lines += 2  # 已写回 · 还原这句
        if any(issue["stale"] for issue in row["issues"]):
            lines += 1
        return lines

    def _row_height(self, row):
        layout = self._row_layout(row)
        text = max(sum(layout["heights"]), self.LINE)
        text += sum(self.ISSUE if kind != "detail" else self.DETAIL for kind, _value in layout["entries"])
        if self._remember_action(row) is not None:
            text += self.ACTION
        meta = self.LINE + self.META_LINE * (self._meta_lines(row) - 1)
        return self.PAD + max(text, meta) + self.PAD

    def _remember_action(self, row):
        pair = single_replacement(row.get("origin", row["base"]), row["base"])
        if pair is None or row.get("remembered") == pair:
            return None
        return pair

    def _layout_rows(self):
        self._metrics()
        self.heights = [self._row_height(self.rows[index]) for index in self.visible]
        self.offsets = [0]
        for height in self.heights:
            self.offsets.append(self.offsets[-1] + height)
        self._sync_bar()
        self.update()

    def refresh_row(self, cue_id):
        """Re-measure one caption; the others keep their cached layout."""
        if not cue_id:
            self._layout_rows()
            return
        slot = self.slot_of(cue_id)
        if slot < 0:
            self.update()
            return
        height = self._row_height(self.rows[self.visible[slot]])
        delta = height - self.heights[slot]
        if delta:
            self.heights[slot] = height
            for index in range(slot + 1, len(self.offsets)):
                self.offsets[index] += delta
            self._sync_bar()
        self._serial += 1
        self.update()

    # geometry ---------------------------------------------------------
    def _sync_bar(self):
        self._serial += 1
        total = self.offsets[-1] if self.offsets else 0
        self.bar.setRange(0, max(0, total - self.height()))
        self.bar.setPageStep(max(1, self.height()))
        self.bar.setSingleStep(max(20, self.LINE))
        self.bar.setVisible(total > self.height())
        width = max(10, round(10 * (self._zoom or 1)))
        self.bar.setGeometry(self.width() - width, 0, width, self.height())
        self._offset = self.bar.value()
        self._place_editor()

    def _scrolled(self, value):
        self._serial += 1
        self._offset = int(value)
        self._place_editor()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            anchor = self._top_anchor()
            self._layout_rows()
            self._restore_anchor(anchor)
        else:
            self._sync_bar()

    def wheelEvent(self, event):
        self.bar.setValue(self.bar.value() - round(event.angleDelta().y() / 120 * self.LINE * 3))
        event.accept()

    def _slot_at(self, y):
        y = int(y) + self._offset
        slot = bisect.bisect_right(self.offsets, y) - 1
        return slot if 0 <= slot < len(self.visible) else -1

    def slot_of(self, cue_id):
        for slot, index in enumerate(self.visible):
            if self.rows[index]["cue_id"] == cue_id:
                return slot
        return -1

    def ensure_visible(self, cue_id):
        slot = self.slot_of(cue_id)
        if slot < 0:
            return
        top, bottom = self.offsets[slot], self.offsets[slot + 1]
        if top < self.bar.value():
            self.bar.setValue(top)
        elif bottom > self.bar.value() + self.height():
            self.bar.setValue(bottom - self.height())

    def _right(self):
        # Always leave the scroll bar's room: measuring with and without it
        # made rows reflow when it appeared, and text ran under it.
        return self.width() - round(16 * (self._zoom or 1))

    def _text_rect(self, slot):
        y = self.offsets[slot] - self._offset + self.PAD
        return QRectF(self.TEXT_X, y, self._text_width(), self.LINE)

    # editing ----------------------------------------------------------
    def start_edit(self, cue_id, text, select=None):
        slot = self.slot_of(cue_id)
        if slot < 0:
            return
        self.ensure_visible(cue_id)
        caret, self._edit_caret = getattr(self, "_edit_caret", None), None
        if select is None and caret is not None and caret[0] == cue_id:
            select = (caret[1], caret[1])
        self._editing = cue_id
        self.current = cue_id
        self.editor.setText(text)
        self._place_editor()
        self.editor.show()
        self.editor.setFocus()
        if select is not None and 0 <= select[0] <= select[1] <= len(text):
            # 只改这一处: the characters chosen in the list stay chosen.
            self.editor.setSelection(select[0], select[1] - select[0])
        else:
            self.editor.end(False)

    # selection --------------------------------------------------------
    def selection(self):
        """(cue_id, start, end, text) of the characters selected with the
        mouse in a caption, or None. Only the caption's own text can be
        selected, never a proposal written under it."""
        if self._selection is None:
            return None
        cue_id, anchor, caret = self._selection
        row = self.row_by_id(cue_id)
        if row is None or anchor == caret:
            return None
        start, end = sorted((anchor, caret))
        end = min(end, len(row["base"]))
        if start >= end:
            return None
        return cue_id, start, end, row["base"][start:end]

    def select_text(self, cue_id, start, end):
        row = self.row_by_id(cue_id)
        if row is None:
            return
        start, end = max(0, int(start)), min(len(row["base"]), int(end))
        self._selection = (cue_id, start, end) if start < end else None
        self.selection_changed.emit()
        self.update()

    def clear_selection(self):
        if self._selection is not None:
            self._selection = None
            self.selection_changed.emit()
            self.update()

    def _char_at(self, cue_id, pos, clamp=False):
        """Caret position (between characters) in ``cue_id``'s caption at
        ``pos``, from the last paint; None outside its text."""
        lines = self._chars.get(cue_id)
        if not lines:
            return None
        y, x = pos.y(), pos.x()
        # Only the caption's own line counts; the proposals written under
        # it are not caption text (a drag may still pass over them).
        line = next((entry for entry in lines if entry[0] <= y < (entry[2] if clamp else entry[1])), None)
        if line is None:
            if not clamp:
                return None
            line = lines[0] if y < lines[0][0] else lines[-1]
        boxes = line[3]
        if not boxes:
            return None
        if not clamp and not (boxes[0][0] - 4 <= x <= boxes[-1][1] + 4):
            return None
        for left, right, index in boxes:
            if x < (left + right) / 2:
                return index
        return boxes[-1][2] + 1

    def editing(self):
        return self._editing

    def _place_editor(self):
        if not self._editing:
            return
        slot = self.slot_of(self._editing)
        if slot < 0:
            self.cancel_edit()
            return
        rect = self._text_rect(slot)
        pad = round(6 * (self._zoom or 1))
        self.editor.setGeometry(int(rect.left()) - pad, int(rect.top()), int(self._right() - rect.left()) - pad,
                                int(self.LINE))

    def _commit_edit(self):
        cue_id, text = self._editing, self.editor.text()
        self._editing = ""
        self.editor.hide()
        self.setFocus()
        if cue_id:
            self.edit_committed.emit(cue_id, text)

    def cancel_edit(self):
        self._editing = ""
        self.editor.hide()
        self.setFocus()

    def commit_pending_edit(self):
        if self._editing:
            self._commit_edit()

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if watched is self.editor:
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self.cancel_edit()
                return True
            if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # QLineEdit passes Return on to its parent, whose own Return
                # means "edit this row": consume it so Enter only commits.
                self._commit_edit()
                return True
            if event.type() == QEvent.Type.FocusOut and self._editing:
                QTimer.singleShot(0, self.commit_pending_edit)
        return super().eventFilter(watched, event)

    # mouse ------------------------------------------------------------
    def _target_at(self, pos):
        if self._painted_serial != self._serial and self.isVisible():
            self.repaint()
        for rect, action, cue_id, index in reversed(self._hit_boxes):
            if rect.contains(pos):
                return action, cue_id, index
        return None

    def mouseMoveEvent(self, event):
        press = self._press
        if press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if not press["dragging"] and (event.position() - press["pos"]).manhattanLength() >= \
                    QApplication.startDragDistance():
                press["dragging"] = True
            if press["dragging"] and press["char"] is None:
                return  # started off the caption (a proposal line): neither a click nor a selection
            if press["dragging"]:
                caret = self._drag_caret(press["cue_id"], event.position())
                if caret is not None and press["char"] is not None:
                    self._selection = (press["cue_id"], press["char"], caret)
                    self.update()
                return
        slot = self._slot_at(event.position().y())
        if slot != self._hover:
            self._hover = slot
            self.update()
        target = self._target_at(event.position())
        self.setCursor(Qt.CursorShape.IBeamCursor if target and target[0] in {"text"}
                       else Qt.CursorShape.PointingHandCursor if target else Qt.CursorShape.ArrowCursor)
        tip = ""
        row = self.row_by_id(target[1]) if target else None
        if target and target[0] == "kind" and row is not None and 0 <= target[2] < len(row["issues"]):
            issue = row["issues"][target[2]]
            group = group_of(row, target[2], self.terms, self.stutter)
            kinds = [row["issues"][i]["kind"] for i in group["parts"]] if group else [issue["kind"]]
            tip = "\n".join(dict.fromkeys(tr(KIND_TIPS.get(kind, "")) for kind in kinds))
            if issue.get("evidence"):
                tip += "\n" + issue["evidence"]
        elif target and target[0] == "mark" and row is not None:
            index = target[2]
            if isinstance(index, int) and 0 <= index < len(row["issues"]):
                issue = row["issues"][index]
                group = group_of(row, index, self.terms, self.stutter)
                whole = (group is not None and len(group["parts"]) > 1 and not group["options"])
                tip = (tr("已写回工程：「{old}」→「{new}」；点一下取消（可撤销），右键可批量替换", old=issue["original"],
                          new=issue["replacement"]) if issue["checked"] else
                       tr("建议：「{old}」→「{new}」；点一下采用（直接写回工程），右键可批量替换", old=issue["original"],
                          new=issue["replacement"]))
                if whole:
                    tip += "\n" + tr("这一处和同一个词里的其他建议是一组，会一起采用或取消")
                tip += "\n" + tr("拖动鼠标可以选字")
            else:
                tip = tr("在本页改过；右键可把同样的改法用到全工程")
        elif target and target[0] == "find" and row is not None:
            excluded = (row["cue_id"], target[2]) in (self.find.get("excluded") or ())
            tip = tr("已排除：这一处不替换；点一下恢复") if excluded else tr("会被替换；点一下排除这一处")
        elif target and target[0] == "text":
            tip = tr("拖动鼠标选字，右键可批量替换相同文字；双击直接修改这句字幕")
        elif target and target[0] == "ignore":
            tip = tr("不采用这组建议（不改字幕，只把它标为已看过）")
        elif target and target[0] == "detail":
            tip = tr("展开或收起这组建议的来源和理由")
        if self.toolTip() != tip:
            self.setToolTip(tip)

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    # Hit boxes over the caption's own characters: a press there may become
    # a text selection, so they act on release (a click), never on press.
    TEXT_TARGETS = frozenset({"text", "mark", "find"})

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        slot = self._slot_at(event.position().y())
        if slot < 0:
            return
        row = self.rows[self.visible[slot]]
        self.current = row["cue_id"]
        target = self._target_at(event.position())
        self._press = None
        if target is not None and target[0] not in self.TEXT_TARGETS:
            action, cue_id, index = target
            if action == "play":
                self.play_requested.emit(cue_id)
            elif action == "edit":
                # The editor takes focus; taking it back here closed it
                # again at once ("修改 does nothing", 2026-10-10).
                self.edit_requested.emit(cue_id)
                self.update()
                return
            elif action in {"check", "option"} and isinstance(index, int) and index >= 0:
                self.issue_toggled.emit(cue_id, index)
            elif action == "detail" and isinstance(index, int):
                key = (cue_id, index)
                self.expanded.symmetric_difference_update({key})
                self.refresh_row(cue_id)
            elif action == "ignore" and isinstance(index, int):
                self.group_dismissed.emit(cue_id, index)
            elif action == "manual" and isinstance(index, int):
                self.group_manual.emit(cue_id, index)
                return
            elif action == "remember":
                self.remember_requested.emit(cue_id)
            elif action == "revert":
                self.revert_requested.emit(cue_id)
        else:
            char = self._char_at(row["cue_id"], event.position())
            if char is None and target is not None and target[0] == "text":
                char = self._char_at(row["cue_id"], event.position(), clamp=True)
            selection = self.selection()
            if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier and selection is not None
                    and selection[0] == row["cue_id"] and char is not None):
                self._selection = (row["cue_id"], self._selection[1], char)
                self.selection_changed.emit()
            else:
                self._press = dict(pos=QPointF(event.position()), cue_id=row["cue_id"], char=char, target=target,
                                   dragging=False)
        self.setFocus()
        self.update()

    def _drag_caret(self, cue_id, pos):
        lines = self._chars.get(cue_id)
        row = self.row_by_id(cue_id)
        if not lines or row is None:
            return None
        if pos.y() < lines[0][0]:
            return 0
        if pos.y() >= lines[-1][2]:
            return len(row["base"])
        caret = self._char_at(cue_id, pos, clamp=True)
        return len(row["base"]) if caret is None else caret

    def mouseReleaseEvent(self, event):
        press, self._press = self._press, None
        if press is None or event.button() != Qt.MouseButton.LeftButton:
            return
        if press["dragging"]:
            self.selection_changed.emit()
            return
        # A click on the caption: deselect, then act on what was clicked.
        self.clear_selection()
        target = press["target"]
        if target is None:
            return
        action, cue_id, index = target
        if action == "mark" and isinstance(index, int) and index >= 0:
            self.issue_toggled.emit(cue_id, index)
        elif action == "find" and isinstance(index, int):
            self.hit_toggled.emit(cue_id, index)

    def mouseDoubleClickEvent(self, event):
        target = self._target_at(event.position())
        slot = self._slot_at(event.position().y())
        if slot >= 0 and (target is None or target[0] in {"text", "kind", "find"}):
            cue_id = self.rows[self.visible[slot]]["cue_id"]
            char = self._char_at(cue_id, event.position())
            # The editor opens with the caret where the caption was clicked.
            self._edit_caret = (cue_id, char) if char is not None else None
            self.edit_requested.emit(cue_id)

    def contextMenuEvent(self, event):
        slot = self._slot_at(event.pos().y())
        if slot < 0:
            return
        row = self.rows[self.visible[slot]]
        self.current = row["cue_id"]
        selection = self.selection()
        if selection is not None and selection[0] != row["cue_id"]:
            self.clear_selection()  # the menu is about the row under the mouse
        self.update()
        target = self._target_at(QPointF(event.pos()))
        self.context_requested.emit(row["cue_id"], target, event.globalPos())
        event.accept()

    def keyPressEvent(self, event):
        from PySide6.QtGui import QKeySequence
        if event.matches(QKeySequence.StandardKey.Copy) and self.selection() is not None:
            QApplication.clipboard().setText(self.selection()[3])
            return
        if event.key() == Qt.Key.Key_Escape and self._selection is not None:
            self.clear_selection()
            return
        slot = self.slot_of(self.current)
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.visible:
            slot = max(0, min(len(self.visible) - 1, slot + (1 if event.key() == Qt.Key.Key_Down else -1)))
            self.current = self.rows[self.visible[slot]]["cue_id"]
            self.ensure_visible(self.current)
            self.update()
            return
        if self.current and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F2):
            self.edit_requested.emit(self.current)
            return
        if self.current and event.key() == Qt.Key.Key_Space:
            self.play_requested.emit(self.current)
            return
        super().keyPressEvent(event)

    # painting ---------------------------------------------------------
    def _kind_color(self, theme, kind):
        return {"term": theme.danger, "near": theme.warning, "ai": theme.accent, "ai_review": theme.accent,
                "consistency": theme.info, "evidence": theme.warning,
                "association": theme.info, "stutter": theme.warning, "merge": theme.text_muted,
                "suspect": theme.warning}.get(kind, theme.text_secondary)

    def paintEvent(self, event):
        theme = _theme()
        colors = mark_colors(theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hit_boxes = []
        if self._press is None or not self._press.get("dragging"):
            self._chars = {}  # a drag keeps measuring against the row it started in
        self._painted_serial = self._serial
        if not self.visible:
            painter.setFont(self.body)
            painter.setPen(QColor(theme.text_muted))
            painter.drawText(QRectF(24, 24, self.width() - 48, self.height() - 24),
                             int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                             self.empty_text)
            painter.end()
            return
        right = self._right()
        z = lambda value: max(1, round(value * (self._zoom or 1)))
        first = max(0, self._slot_at(0))
        for slot in range(first, len(self.visible)):
            top = self.offsets[slot] - self._offset
            if top > self.height():
                break
            row = self.rows[self.visible[slot]]
            height = self.heights[slot]
            rect = QRectF(0, top, right, height)
            if row["cue_id"] == self.current:
                painter.fillRect(rect, QColor(blend_hex(theme.surface, theme.accent, 0.10)))
            elif slot == self._hover:
                painter.fillRect(rect, QColor(theme.selected))
            if slot:
                painter.fillRect(QRectF(8, top, right - 16, 1), QColor(theme.border))
            y = top + self.PAD
            line_h = self.LINE
            # meta column: time · play / number · speaker / state
            painter.setFont(self.mono)
            painter.setPen(QColor(theme.text_muted))
            x = z(14)
            painter.drawText(QRectF(x, y, self.time_w, line_h), int(Qt.AlignmentFlag.AlignVCenter), row["time"])
            play = QRectF(x + self.time_w, y + (line_h - self.play_d) / 2, self.play_d, self.play_d)
            state = self.playing[1] if self.playing[0] == row["cue_id"] else ""
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.accent if state else blend_hex(theme.surface, theme.accent_text, 0.18)))
            painter.drawEllipse(play)
            painter.setBrush(QColor(theme.text_on_accent if state else theme.accent_text))
            c = play.center()
            s = self.play_d / 28
            if state == "playing":
                painter.drawRect(QRectF(c.x() - 5 * s, c.y() - 5 * s, 10 * s, 10 * s))
            elif state == "loading":
                for dot in (-6, 0, 6):
                    painter.drawEllipse(QPointF(c.x() + dot * s, c.y()), 2 * s, 2 * s)
            else:
                painter.drawPolygon(QPolygonF([QPointF(c.x() - 4 * s, c.y() - 6 * s), QPointF(c.x() - 4 * s, c.y() + 6 * s),
                                               QPointF(c.x() + 6 * s, c.y())]))
            self._hit_boxes.append((play.adjusted(-4, -4, 4, 4), "play", row["cue_id"], -1))
            meta_y = y + line_h
            painter.setFont(self.small)
            painter.setPen(QColor(theme.text_muted))
            painter.drawText(QRectF(x, meta_y, self.number_w, self.META_LINE), int(Qt.AlignmentFlag.AlignVCenter),
                             row["number"])
            name, color = row["speaker"]
            if name:
                chip_font = QFont(self.mono); chip_font.setWeight(QFont.Weight.DemiBold)
                painter.setFont(chip_font)
                chip_metrics = QFontMetricsF(chip_font)
                shown_name = chip_metrics.elidedText(name, Qt.TextElideMode.ElideRight, self.speaker_w - z(14))
                chip_h = min(z(22), self.META_LINE - z(4))
                chip = QRectF(x + self.number_w, meta_y + (self.META_LINE - chip_h) / 2,
                              chip_metrics.horizontalAdvance(shown_name) + z(14), chip_h)
                tint = QColor(color) if QColor(color).isValid() else QColor(theme.text_secondary)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(blend_hex(theme.surface, tint.name(), 0.26)))
                painter.drawRoundedRect(chip, 5, 5)
                painter.setPen(QColor(legible(blend_hex(tint.name(), theme.text, 0.35),
                                              blend_hex(theme.surface, tint.name(), 0.26), theme)))
                painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), shown_name)
            meta_y += self.META_LINE
            painter.setFont(self.small)
            if row["base"] != row.get("origin", row["base"]):
                painter.setPen(QColor(colors["applied_line"]))
                painter.drawText(QRectF(x, meta_y, self.META_W, self.META_LINE), int(Qt.AlignmentFlag.AlignVCenter),
                                 "✓ " + tr("已写回"))
                meta_y += self.META_LINE
                revert = tr("还原这句")
                box = QRectF(x, meta_y, self.small_metrics.horizontalAdvance(revert) + z(4), self.META_LINE)
                painter.setPen(QColor(theme.text_secondary))
                painter.drawText(box, int(Qt.AlignmentFlag.AlignVCenter), revert)
                underline = box.bottom() - z(6)
                painter.drawLine(QPointF(box.left(), underline), QPointF(box.right() - z(4), underline))
                self._hit_boxes.append((box, "revert", row["cue_id"], -1))
                meta_y += self.META_LINE
            stale = sum(issue["stale"] for issue in row["issues"])
            if stale:
                painter.setPen(QColor(legible(theme.warning, theme.surface, theme)))
                painter.drawText(QRectF(x, meta_y, self.META_W, self.META_LINE), int(Qt.AlignmentFlag.AlignVCenter),
                                 self.small_metrics.elidedText(tr("{count} 条建议已过期", count=stale),
                                                               Qt.TextElideMode.ElideRight, self.META_W))
            # the caption, wrapped, with marks
            layout = self._row_layout(row)
            line_y = y
            selection = self.selection()
            selected = (selection[1], selection[2]) if selection is not None and selection[0] == row["cue_id"] else None
            char_lines = []
            for line, line_height in zip(layout["lines"], layout["heights"]):
                boxes = []
                for unit in line:
                    self._paint_unit(painter, unit, self.TEXT_X + unit["x"], line_y, theme, colors, row)
                    # Where each character of the caption itself was drawn
                    # (never the proposal under it): selection and hit tests.
                    left = self.TEXT_X + unit["x"] + (0.0 if unit["mark"] is None
                                                     else (unit["w"] - unit["top_w"]) / 2)
                    for offset in range(len(unit["top"])):
                        a = left + self.body_metrics.horizontalAdvance(unit["top"][:offset])
                        b = left + self.body_metrics.horizontalAdvance(unit["top"][:offset + 1])
                        boxes.append((a, b, unit["start"] + offset))
                if selected is not None:
                    chosen = [(a, b, index) for a, b, index in boxes if selected[0] <= index < selected[1]]
                    if chosen:
                        # A solid selection with the characters redrawn on it,
                        # as in an editor: unmistakable over any mark or hit.
                        fill = QColor(blend_hex(theme.surface, theme.accent, 0.78))
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(fill)
                        painter.drawRoundedRect(QRectF(chosen[0][0] - z(1), line_y + z(3),
                                                       chosen[-1][1] - chosen[0][0] + z(2), self.LINE - z(6)), z(3), z(3))
                        painter.setFont(self.body)
                        painter.setPen(QColor(legible(theme.text_on_accent, fill.name(), theme, 4.5)))
                        for a, b, index in chosen:
                            painter.drawText(QRectF(a, line_y, b - a + z(4), self.LINE),
                                             int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                                             row["base"][index])
                char_lines.append((line_y, line_y + self.LINE, line_y + line_height, boxes))
                if line:
                    line_box = QRectF(self.TEXT_X, line_y, line[-1]["x"] + line[-1]["w"], self.LINE)
                    self._hit_boxes.insert(0, (line_box, "text", row["cue_id"], -1))
                line_y += line_height
            self._chars[row["cue_id"]] = char_lines
            self._painted_text[row["cue_id"]] = QRectF(self.TEXT_X, y, self._text_width(), self.LINE)
            # 修改 sits right after the sentence it edits (2026-10-10, user).
            edit_text = tr("修改")
            edit_h = z(26)
            if layout["edit_newline"]:
                edit_x, edit_y = self.TEXT_X, line_y - self.LINE + (self.LINE - edit_h) / 2
            else:
                last_height = layout["heights"][len(layout["lines"]) - 1] if layout["lines"] else self.LINE
                edit_x = self.TEXT_X + layout["last_end"] + z(12)
                edit_y = line_y - last_height + (self.LINE - edit_h) / 2
            edit = QRectF(edit_x, edit_y, self.EDIT_W, edit_h)
            hot = row["cue_id"] == self.current or slot == self._hover
            painter.setFont(self.label_font)
            painter.setPen(QColor(theme.accent if hot else theme.border_strong))
            painter.setBrush(QColor(blend_hex(theme.surface, theme.accent, 0.12)) if hot else Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(edit.adjusted(.5, .5, -.5, -.5), 7, 7)
            painter.setPen(QColor(theme.accent_text if hot else theme.text_secondary))
            painter.drawText(edit.adjusted(z(8), 0, 0, 0), int(Qt.AlignmentFlag.AlignVCenter), "✎")
            painter.drawText(edit.adjusted(z(24), 0, 0, 0), int(Qt.AlignmentFlag.AlignVCenter), edit_text)
            self._hit_boxes.append((edit, "edit", row["cue_id"], -1))
            y = line_y if line_y > y else y + self.LINE
            for kind, value in layout["entries"]:
                height = self.DETAIL if kind == "detail" else self.ISSUE
                rect = QRectF(self.TEXT_X, y, right - self.TEXT_X - z(16), height)
                if kind == "group":
                    self._draw_group(painter, row, value, rect, theme, colors)
                elif kind == "detail":
                    self._draw_detail(painter, row, value[0], value[1], rect, theme)
                else:
                    self._draw_issue(painter, row, value, row["issues"][value], rect, theme, colors)
                y += height
            pair = self._remember_action(row)
            if pair is not None:
                target = self.remember_targets.get("name") or ""
                text = (tr("＋ 记住「{old} → {new}」到「{library}」", old=pair[0], new=pair[1], library=target)
                        if target else tr("＋ 记住「{old} → {new}」到词库…", old=pair[0], new=pair[1]))
                width = self.label_metrics.horizontalAdvance(text) + z(24)
                box = QRectF(self.TEXT_X, y + z(4), min(width, right - self.TEXT_X - z(16)), z(28))
                painter.setPen(QColor(theme.accent))
                painter.setBrush(QColor(blend_hex(theme.surface, theme.accent, 0.10)))
                painter.drawRoundedRect(box, 7, 7)
                painter.setFont(self.label_font)
                painter.setPen(QColor(theme.accent_text))
                painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter),
                                 self.label_metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, box.width() - z(12)))
                self._hit_boxes.append((box, "remember", row["cue_id"], -1))
        painter.end()

    def _paint_unit(self, painter, unit, x, y, theme, colors, row):
        mark = unit["mark"]
        top_box = QRectF(x, y, unit["w"], self.LINE)
        if mark is None:
            painter.setFont(self.body)
            painter.setPen(QColor(theme.text))
            painter.drawText(top_box, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), unit["top"])
            return
        style = mark["style"]
        z = lambda value: max(1, round(value * (self._zoom or 1)))
        # Fills hug the marked characters; a longer replacement below only
        # widens the gap around them, never the colored area.
        hug = unit["top_w"] + 2 * self.MARK_PAD
        inner = QRectF(top_box.center().x() - hug / 2, top_box.top() + z(4), hug, top_box.height() - z(8))
        if style.startswith("find"):
            self._paint_find(painter, unit, mark, style, x, y, top_box, inner, theme, colors, row)
            return
        if style.startswith("suggest") or style.startswith("dismissed") or style.startswith("pending"):
            strong = style.startswith("suggest")
            # A name the library knows, questioned by a source: asked, not
            # painted as an error (2026-10-10, user: 魔草巫灵 / 疫病吐息).
            asked = style.startswith("pending")
            if unit["top"]:
                if strong:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(colors["error_fill"]))
                    painter.drawRoundedRect(inner, z(4), z(4))
                painter.setFont(self.body)
                painter.setPen(QColor(colors["error_text"] if strong else theme.text))
                painter.drawText(top_box, int(Qt.AlignmentFlag.AlignCenter), unit["top"])
                pen = QPen(QColor(colors["error_line"] if strong else
                                  legible(theme.warning, theme.surface, theme, 3.0) if asked else theme.text_muted))
                pen.setWidthF(max(1.5, 2.0 * (self._zoom or 1)) if strong or asked else 1.2)
                if not strong:
                    pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                text_w = unit["top_w"]
                left = top_box.center().x() - text_w / 2
                underline_y = inner.bottom() - z(1)
                painter.drawLine(QPointF(left, underline_y), QPointF(left + text_w, underline_y))
                if style.endswith("_delete"):
                    middle = top_box.center().y()
                    painter.drawLine(QPointF(left, middle), QPointF(left + text_w, middle))
            else:
                self._caret(painter, top_box, colors["error_line"] if strong else theme.text_muted)
            below_box = QRectF(x, y + self.LINE - z(2), unit["w"], self.BELOW)
            text = unit["below"]
            if style.endswith("_insert"):
                text = "+" + text
            if text:
                painter.setFont(self.below if not style.endswith("_delete") else self.label_font)
                metrics = self.below_metrics if not style.endswith("_delete") else self.label_metrics
                width = metrics.horizontalAdvance(text) + 2 * self.MARK_PAD
                chip = QRectF(below_box.center().x() - width / 2, below_box.top() + z(1), width, below_box.height() - z(4))
                if strong:
                    painter.setPen(QPen(QColor(colors["fix_line"]), 1.0))
                    painter.setBrush(QColor(colors["fix_fill"] if not style.endswith("_delete") else colors["error_fill"]))
                    painter.drawRoundedRect(chip, z(4), z(4))
                    painter.setPen(QColor(colors["fix_text"] if not style.endswith("_delete") else colors["error_text"]))
                elif asked:
                    pen = QPen(QColor(legible(theme.warning, theme.surface, theme, 3.0)), 1.0)
                    pen.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(chip, z(4), z(4))
                    painter.setPen(QColor(theme.text))
                else:
                    painter.setPen(QColor(theme.text_muted))
                painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), text)
                self._hit_boxes.append((chip.united(top_box), "mark", row["cue_id"], mark["ref"] if mark["ref"] is not None else -1))
            else:
                self._hit_boxes.append((top_box, "mark", row["cue_id"], mark["ref"] if mark["ref"] is not None else -1))
            return
        if style == "suspect":
            painter.setFont(self.body)
            painter.setPen(QColor(theme.text))
            painter.drawText(top_box, int(Qt.AlignmentFlag.AlignCenter), unit["top"])
            pen = QPen(QColor(theme.warning))
            pen.setStyle(Qt.PenStyle.DotLine)
            pen.setWidthF(max(1.5, 2.0 * (self._zoom or 1)))
            painter.setPen(pen)
            left = top_box.center().x() - unit["top_w"] / 2
            painter.drawLine(QPointF(left, inner.bottom() - z(1)), QPointF(left + unit["top_w"], inner.bottom() - z(1)))
            self._hit_boxes.append((top_box, "kind", row["cue_id"], mark["ref"] if mark["ref"] is not None else -1))
            return
        # applied (already in the project): new wording in the line, old struck under it
        if unit["top"]:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors["applied_fill"]))
            painter.drawRoundedRect(inner, z(4), z(4))
            painter.setFont(self.body)
            painter.setPen(QColor(colors["applied_text"]))
            painter.drawText(top_box, int(Qt.AlignmentFlag.AlignCenter), unit["top"])
        else:
            self._caret(painter, top_box, colors["applied_line"])
        old = unit["below"]
        below_box = QRectF(x, y + self.LINE - z(2), unit["w"], self.BELOW)
        label = old if old else tr("新增")
        font = QFont(self.below); font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        muted = legible(theme.text_muted, theme.surface, theme, 4.5)
        painter.setPen(QColor(muted))
        painter.drawText(below_box, int(Qt.AlignmentFlag.AlignCenter), label)
        if old:
            # The old wording, struck through (a drawn line reads at any size).
            old_w = QFontMetricsF(font).horizontalAdvance(old)
            pen = QPen(QColor(muted)); pen.setWidthF(max(1.2, 1.5 * (self._zoom or 1)))
            painter.setPen(pen)
            middle = below_box.center().y()
            left = below_box.center().x() - old_w / 2
            painter.drawLine(QPointF(left - z(1), middle), QPointF(left + old_w + z(1), middle))
        self._hit_boxes.append((top_box.united(below_box), "mark", row["cue_id"],
                                mark["ref"] if mark.get("ref") is not None else -1))

    def _paint_find(self, painter, unit, mark, style, x, y, top_box, inner, theme, colors, row):
        """A search hit; while replacing, its replacement (or 不替换) under it."""
        z = lambda value: max(1, round(value * (self._zoom or 1)))
        excluded = style == "find_excluded"
        hit_fill = blend_hex(theme.surface, theme.info, 0.34)
        if unit["top"]:
            if excluded:
                pen = QPen(QColor(theme.text_muted), 1.0)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            else:
                painter.setPen(QPen(QColor(legible(theme.info, theme.surface, theme, 3.0)), 1.0))
                painter.setBrush(QColor(hit_fill))
            painter.drawRoundedRect(inner, z(4), z(4))
            painter.setFont(self.body)
            painter.setPen(QColor(theme.text if not excluded else theme.text_muted))
            painter.drawText(top_box, int(Qt.AlignmentFlag.AlignCenter), unit["top"])
        if style == "find":
            return  # plain search: the text stays selectable like any other
        below_box = QRectF(x, y + self.LINE - z(2), unit["w"], self.BELOW)
        text = unit["below"]
        painter.setFont(self.below)
        width = self.below_metrics.horizontalAdvance(text) + 2 * self.MARK_PAD
        chip = QRectF(below_box.center().x() - width / 2, below_box.top() + z(1), width, below_box.height() - z(4))
        if excluded:
            painter.setPen(QColor(theme.text_muted))
        else:
            painter.setPen(QPen(QColor(colors["fix_line"]), 1.0))
            painter.setBrush(QColor(colors["fix_fill"]))
            painter.drawRoundedRect(chip, z(4), z(4))
            painter.setPen(QColor(colors["fix_text"]))
        painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), text)
        self._hit_boxes.append((chip.united(top_box), "find", row["cue_id"], mark["ref"]))

    def _caret(self, painter, box, color):
        z = lambda value: max(1, round(value * (self._zoom or 1)))
        pen = QPen(QColor(color))
        pen.setWidthF(max(1.5, 2.0 * (self._zoom or 1)))
        painter.setPen(pen)
        cx = box.center().x()
        painter.drawLine(QPointF(cx, box.top() + z(6)), QPointF(cx, box.bottom() - z(6)))
        painter.drawLine(QPointF(cx - z(4), box.bottom() - z(6)), QPointF(cx + z(4), box.bottom() - z(6)))

    def _chip(self, painter, x, rect, label, color, theme):
        z = lambda value: max(1, round(value * (self._zoom or 1)))
        painter.setFont(self.label_font)
        chip_w = self.label_metrics.horizontalAdvance(label) + z(16)
        chip_h = z(22)
        chip = QRectF(x, rect.top() + (rect.height() - chip_h) / 2, chip_w, chip_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(blend_hex(theme.surface, color.name(), 0.20)))
        painter.drawRoundedRect(chip, 6, 6)
        painter.setPen(QColor(legible(blend_hex(color.name(), theme.text, 0.25), blend_hex(theme.surface, color.name(), 0.20), theme)))
        painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), label)
        return chip

    def _box(self, painter, x, rect, state, theme):
        """Adopt box: empty, ticked (adopted) or a dash (partly adopted)."""
        z = lambda value: max(1, round(value * (self._zoom or 1)))
        box_d = z(18)
        box = QRectF(x, rect.top() + (rect.height() - box_d) / 2, box_d, box_d)
        filled = state in {"adopted", "partial"}
        painter.setPen(QColor(theme.accent if filled else theme.border_strong))
        painter.setBrush(QColor(theme.accent) if filled else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 4, 4)
        pen = QPen(QColor(theme.text_on_accent)); pen.setWidthF(2.0 * (self._zoom or 1)); painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        k = box_d / 18
        if state == "adopted":
            painter.drawPolyline(QPolygonF([QPointF(box.left() + 4 * k, box.top() + 9 * k), QPointF(box.left() + 8 * k, box.top() + 13 * k),
                                            QPointF(box.left() + 14 * k, box.top() + 5 * k)]))
        elif state == "partial":
            painter.drawLine(QPointF(box.left() + 4 * k, box.center().y()), QPointF(box.right() - 4 * k, box.center().y()))
        return box

    def _text_button(self, painter, x, rect, text, action, row, index, theme, *, accent=False):
        z = lambda value: max(1, round(value * (self._zoom or 1)))
        painter.setFont(self.small)
        width = self.small_metrics.horizontalAdvance(text) + z(14)
        if x + width > rect.right():
            return x
        box = QRectF(x, rect.top() + z(4), width, rect.height() - z(8))
        painter.setPen(QColor(theme.accent_text if accent else theme.text_secondary))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)
        underline = box.center().y() + self.small_metrics.height() / 2
        pen = QPen(QColor(theme.border_strong)); pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(box.left() + z(7), underline), QPointF(box.right() - z(7), underline))
        self._hit_boxes.append((box, action, row["cue_id"], index))
        return x + width + z(4)

    def _draw_group(self, painter, row, group, rect, theme, colors):
        """One line per decision: box, compact source, the real change, state,
        详情 and 忽略. Reasons stay under 详情 (2026-10-10, user)."""
        z = lambda value: max(1, round(value * (self._zoom or 1)))
        issues = [row["issues"][index] for index in group["parts"]]
        first = group["parts"][0]
        x = rect.left()
        if not group["options"]:
            box = self._box(painter, x, rect, group["state"], theme)
            self._hit_boxes.append((box.adjusted(-4, -4, z(8), 4), "check", row["cue_id"], first))
        x += z(18) + z(10)
        kinds = list(dict.fromkeys(issue["kind"] for issue in issues))
        label = (" · ".join(tr(KIND_LABELS.get(kind, kind)) for kind in kinds) if len(kinds) <= 2
                 else tr("{count} 个来源", count=len(kinds)))
        chip = self._chip(painter, x, rect, label, QColor(self._kind_color(theme, kinds[0])), theme)
        self._hit_boxes.append((chip, "kind", row["cue_id"], first))
        x = chip.right() + z(10)
        painter.setFont(self.small)
        metrics = self.small_metrics
        reviewed = group["reviewed"] and group["state"] == "open"
        painter.setPen(QColor(theme.text if not reviewed else theme.text_muted))
        if group["options"]:
            a, b = group["span"]
            stem = group["before"][a:b] if group["before"][a:b] else issues[0]["original"]
            prefix = f"{stem} →"
            width = metrics.horizontalAdvance(prefix) + z(8)
            painter.drawText(QRectF(x, rect.top(), width, rect.height()), int(Qt.AlignmentFlag.AlignVCenter), prefix)
            x += width
            for index, issue in zip(group["parts"], issues):
                text = issue["replacement"] or tr("删去")
                pill_w = metrics.horizontalAdvance(text) + z(16)
                if x + pill_w > rect.right():
                    break
                pill = QRectF(x, rect.top() + z(4), pill_w, rect.height() - z(8))
                painter.setPen(QColor(theme.accent if issue["checked"] else theme.border_strong))
                painter.setBrush(QColor(blend_hex(theme.surface, theme.accent, 0.22)) if issue["checked"] else Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(pill, z(6), z(6))
                painter.setPen(QColor(theme.accent_text if issue["checked"] else theme.text))
                painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), text)
                self._hit_boxes.append((pill, "option", row["cue_id"], index))
                x += pill_w + z(6)
            x += z(4)
        else:
            if group["after"] is not None and group["before"] != group["after"]:
                text = change_summary(group["before"], group["after"])
            else:
                text = change_summary(issues[0]["original"], issues[0]["replacement"])
            main_w = min(metrics.horizontalAdvance(text) + z(8), max(z(40), rect.right() - x - z(160)))
            main = QRectF(x, rect.top(), main_w, rect.height())
            painter.drawText(main, int(Qt.AlignmentFlag.AlignVCenter), metrics.elidedText(text, Qt.TextElideMode.ElideRight, main_w))
            self._hit_boxes.append((main, "mark", row["cue_id"], first))
            x += main_w + z(6)
        if group["state"] == "adopted":
            status, tone = tr("已写回"), colors["applied_line"]
        elif group["state"] == "partial":
            status, tone = tr("部分已写回"), colors["applied_line"]
        elif reviewed:
            status, tone = tr("已忽略"), theme.text_muted
        elif group["pending"]:
            status, tone = tr("待确认"), legible(theme.warning, theme.surface, theme)
        elif group["recommended"]:
            status, tone = tr("推荐"), theme.accent_text
        else:
            status, tone = "", theme.text_muted
        if status:
            painter.setPen(QColor(tone))
            width = metrics.horizontalAdvance(status) + z(10)
            painter.drawText(QRectF(x, rect.top(), width, rect.height()), int(Qt.AlignmentFlag.AlignVCenter), status)
            x += width + z(6)
        opened = (row["cue_id"], first) in self.expanded
        x = self._text_button(painter, x, rect, tr("收起") if opened else tr("详情"), "detail", row, first, theme)
        if group["state"] == "open" and not reviewed:
            self._text_button(painter, x, rect, tr("忽略"), "ignore", row, first, theme)

    def _draw_detail(self, painter, row, group, line, rect, theme):
        z = lambda value: max(1, round(value * (self._zoom or 1)))
        x = rect.left() + z(18) + z(10)
        width = rect.right() - x
        painter.setFont(self.small)
        if line.get("manual"):
            self._text_button(painter, x - z(7), rect, line["text"], "manual", row, group["parts"][0], theme, accent=True)
            return
        painter.setPen(QColor(legible(theme.text_muted, theme.surface, theme, 4.5)))
        painter.drawText(QRectF(x, rect.top(), width, rect.height()), int(Qt.AlignmentFlag.AlignVCenter),
                         self.small_metrics.elidedText("· " + line["text"], Qt.TextElideMode.ElideRight, width))

    def _draw_issue(self, painter, row, index, issue, rect, theme, colors):
        """A suspected name without a candidate: shown, never changed by itself."""
        z = lambda value: max(1, round(value * (self._zoom or 1)))
        x = rect.left() + z(18) + z(10)
        chip = self._chip(painter, x, rect, tr(KIND_LABELS.get(issue["kind"], issue["kind"])),
                          QColor(self._kind_color(theme, issue["kind"])), theme)
        self._hit_boxes.append((chip, "kind", row["cue_id"], index))
        x = chip.right() + z(10)
        text = tr("「{word}」像专有名词，所选词库里没有收录；写错了就双击这句修改", word=issue["original"])
        painter.setFont(self.small)
        painter.setPen(QColor(theme.text_secondary))
        width = rect.right() - x
        painter.drawText(QRectF(x, rect.top(), width, rect.height()), int(Qt.AlignmentFlag.AlignVCenter),
                         self.small_metrics.elidedText(text, Qt.TextElideMode.ElideRight, width))


# --------------------------------------------------------------------------
# Spelling conflicts
# --------------------------------------------------------------------------

class ConflictPanel(QFrame):
    """'词条冲突 N 项' — expands into one decision per conflicting spelling.

    Each option names the libraries that use it; the user keeps one spelling
    for this project's proofreading or skips the word this time. Nothing is
    written to the glossary store (M15, user request)."""

    changed = Signal(str, object)  # key, (library_id, target) or None = skip

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("proofreadConflicts")
        self._rows = []
        self._choices = {}
        self._mine = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 10, 8)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.header = QPushButton()
        self.header.setObjectName("proofreadConflictHeader")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setCheckable(True)
        self.header.toggled.connect(self._expand)
        top.addWidget(self.header, 0, Qt.AlignmentFlag.AlignTop)
        self.explain = QLabel()
        self.explain.setObjectName("proofreadConflictExplain")
        self.explain.setWordWrap(True)
        self.explain.setMinimumWidth(0)
        top.addWidget(self.explain, 1)
        layout.addLayout(top)
        self.body = QWidget()
        self.body.setObjectName("proofreadConflictBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 2, 0, 0)
        self.body_layout.setSpacing(8)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("proofreadConflictScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.body)
        self.scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.scroll.hide()
        layout.addWidget(self.scroll)
        self.note = QLabel(tr("选择只用于本工程的 AI 词库校对，词库本身不变；要长期统一写法，请在术语库中修改。"))
        self.note.setObjectName("proofreadNote")
        self.note.setWordWrap(True)
        self.hide()

    def set_conflicts(self, rows, choices, mine=()):
        self._rows = list(rows)
        self._choices = dict(choices)
        self._mine = set(mine)
        self._rebuild()
        self.setVisible(bool(self._rows))

    def unresolved(self):
        return [row for row in self._rows if row["key"] not in self._choices]

    def _expand(self, expanded):
        self.scroll.setVisible(expanded)
        arrow = "▾" if expanded else "▸"
        self.header.setText(tr("{arrow}  词条冲突 {count} 项", arrow=arrow, count=len(self._rows)))
        self.explain.setText(tr("这些词在所选词库里写法不同，选定写法前不会生成对应建议") if self.unresolved()
                             else tr("已全部选定写法"))
        self.header.setProperty("resolved", not self.unresolved())
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)
        if expanded:
            content = self.body.sizeHint().height() + 4
            self.scroll.setMaximumHeight(min(340, content))
            self.scroll.setMinimumHeight(min(100, content))

    def _rebuild(self):
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            if item.widget() is not None and item.widget() is not self.note:
                item.widget().deleteLater()
        for row in self._rows:
            self.body_layout.addWidget(self._row_widget(row))
        self.note.setParent(None)
        self.body_layout.addWidget(self.note)
        self._expand(self.header.isChecked())

    def _row_widget(self, row):
        frame = QFrame()
        frame.setObjectName("proofreadConflictRow")
        grid = QGridLayout(frame)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        title = QLabel(tr("「{key}」 · 出现在 {count} 条字幕", key=self._display_key(row), count=row["count"]))
        title.setObjectName("proofreadConflictTitle")
        grid.addWidget(title, 0, 0, 1, 3)
        skip = QPushButton(tr("本次跳过"))
        skip.setObjectName("proofreadConflictChoice")
        skip.setCheckable(True)
        skip.setChecked(self._choices.get(row["key"]) is None)
        skip.clicked.connect(lambda _=False, key=row["key"]: self._choose(key, None))
        grid.addWidget(skip, 0, 4, Qt.AlignmentFlag.AlignRight)
        chosen = self._choices.get(row["key"])
        mine_targets = {option["target"] for option in row["options"]
                        if any((identity, option["target"]) in self._mine for identity in option["library_ids"])}
        line = 1
        for option in row["options"]:
            is_mine = option["target"] in mine_targets
            libraries = "、".join(f"「{name}」" for name in option["names"]) or tr("（未知词库）")
            caption = (tr("你添加的规范写法 {libraries}：", libraries=libraries) if is_mine
                       else tr("{libraries} 采用：", libraries=libraries))
            label = QLabel(caption)
            label.setObjectName("proofreadNote")
            value = QLabel(option["target"])
            value.setObjectName("proofreadConflictValue")
            text = (tr("使用我的写法（仅本工程）") if is_mine else tr("保留这个写法") if mine_targets
                    else tr("采用这个写法"))
            button = QPushButton(text)
            button.setObjectName("proofreadConflictChoice")
            button.setCheckable(True)
            identity = option["library_ids"][0] if option["library_ids"] else ""
            button.setChecked(chosen == (identity, option["target"]))
            button.clicked.connect(lambda _=False, key=row["key"], value=(identity, option["target"]): self._choose(key, value))
            grid.addWidget(label, line, 0)
            grid.addWidget(value, line, 1)
            grid.addWidget(button, line, 2)
            line += 1
        grid.setColumnMinimumWidth(1, 120)
        grid.setColumnStretch(3, 1)
        return frame

    @staticmethod
    def _display_key(row):
        for option in row["options"]:
            if option["target"].casefold() == row["key"]:
                return option["target"]
        return row["key"]

    def _choose(self, key, value):
        if value is None:
            self._choices.pop(key, None)
        else:
            self._choices[key] = tuple(value)
        self._rebuild()
        self.changed.emit(key, value)


# --------------------------------------------------------------------------
# Background review
# --------------------------------------------------------------------------

class _ReviewThread(QThread):
    ready = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, project, cue_ids, snapshot, settings, use_ai, parent, stand_in=None):
        super().__init__(parent)
        from .service import CancellationToken
        self.token = CancellationToken()
        self.inputs = (project, cue_ids, snapshot, settings)
        self.use_ai = use_ai
        self.stand_in = stand_in

    def run(self):
        try:
            if self.stand_in is not None:  # the tutorial's offline stand-in for the AI request
                result = self.stand_in(*self.inputs, cancel_token=self.token)
                self.token.raise_if_cancelled()
                self.ready.emit(result)
                return
            from .studio_glossary_service import preview_glossary_correction
            result = preview_glossary_correction(*self.inputs, cancel_token=self.token, use_ai=self.use_ai,
                                                 progress=lambda done, total: self.progress.emit(done, total))
            self.token.raise_if_cancelled()
            self.ready.emit(result)
        except Exception as exc:
            self.failed.emit("cancelled" if self.token.is_cancelled else str(exc))


_RESPONSIVE = {"count": 0, "previous": None}


def responsive_background(active):
    """While the page's review threads run, hand the interpreter lock back to
    the window every 0.3 ms instead of 5 ms (2026-10-10: a busy review made
    scrolling stall ~1.3 s, because every small file access of PySide's
    import hook during repaint waited a full switch interval). Every Qt
    event passes the app's Python filters, so one repaint asks for the lock
    hundreds of times: at 1 ms the window still paused ~0.33 s mid-check,
    at 0.3 ms ~0.1 s; the checks take ~5 s instead of ~3 s for 193
    captions, while the page stays usable throughout."""
    import sys
    if active:
        if _RESPONSIVE["count"] == 0:
            _RESPONSIVE["previous"] = sys.getswitchinterval()
            sys.setswitchinterval(min(_RESPONSIVE["previous"], 0.0003))
        _RESPONSIVE["count"] += 1
    elif _RESPONSIVE["count"] > 0:
        _RESPONSIVE["count"] -= 1
        if _RESPONSIVE["count"] == 0 and _RESPONSIVE["previous"] is not None:
            sys.setswitchinterval(_RESPONSIVE["previous"])


def _review_copy(project):
    """A read-only view for the review worker without re-serializing the project.

    The review reads captions, evidence and metadata. Captions are copied
    (the page may apply while it runs); evidence and metadata are only ever
    replaced, never edited in place, by text edits (2026-10-10: the former
    to_dict/from_dict round trip blocked the window ~1 s per match)."""
    view = copy.copy(project)
    view.cues = [copy.copy(cue) for cue in project.cues]
    view.studio_state = dict(project.studio_state or {})
    return view


def compute_stutter(project, cue_ids, protected):
    """{cue_id: (text, [TextOccurrence])} for captions that repeat something."""
    from .stutter_cleanup import stutter_occurrences
    found = {}
    for cue in project.cues:
        if cue_ids is not None and cue.id not in cue_ids:
            continue
        if _REPEAT_HINT.search(cue.text):
            found[cue.id] = (cue.text, stutter_occurrences(project, cue, protected))
        else:
            found[cue.id] = (cue.text, [])
    return found


class _StutterThread(QThread):
    """Local checks off the UI thread (2026-10-10): stammer repeats per
    caption and one spelling per sound across the transcript."""
    ready = Signal(object)

    def __init__(self, project, protected, entries=(), drafts=None, preferred=(), parent=None):
        super().__init__(parent)
        self.project, self.protected = project, protected
        self.entries, self.drafts, self.preferred = list(entries), dict(drafts or {}), set(preferred)

    def run(self):
        result = {"stutter": {}, "consistency": {}, "evidence": {},
                  "texts": {cue_id: text for cue_id, _start, text in self.entries}}
        try:
            from .transcript_evidence import project_evidence
            result["evidence"] = project_evidence(self.project, self.protected)
        except Exception:
            pass
        try:
            result["stutter"] = compute_stutter(self.project, None, self.protected)
            from .stutter_cleanup import consistency_occurrences, word_tokens
            preferred = set(self.preferred)
            words = lambda text: {word for word, _a, _b in word_tokens(text)}
            # A spelling someone chose is the one to follow: words the user is
            # typing now, and words already changed from the recognized text
            # (an applied edit must never be "unified" back).
            for base, draft in self.drafts.values():
                preferred |= words(draft) - words(base)
            for cue in self.project.cues:
                if cue.original_text and cue.text != cue.original_text:
                    preferred |= words(cue.text) - words(cue.original_text)
            result["consistency"] = consistency_occurrences(self.entries, preferred=preferred)
        except Exception:
            pass
        self.ready.emit(result)


class _SaveThread(QThread):
    """Write a private snapshot while the proofreading page keeps editing."""
    done = Signal(str)

    def __init__(self, project, path, parent=None):
        runtime = getattr(project, "_studio_state_runtime", None)
        if runtime is not None and runtime._active is not None:
            raise RuntimeError("不能在媒体编辑事务提交前保存工程")
        # The caller is the GUI thread. Capture before starting the worker:
        # asdict/save_project walks cues and receipts separately, so sharing
        # the live project could save pre-edit text with post-undo metadata.
        # Keep the existing validated, backed-up atomic save in the worker.
        from .studio_runtime_state import _json_snapshot
        # Recognition evidence and proofreading receipts dominate large
        # projects. Reuse the transaction snapshot copier for those JSON
        # fields, together so aliases within/between them stay consistent.
        # It falls back to deepcopy for values marshal cannot preserve.
        values = [project.asr_evidence, project.generation_metadata, project.studio_state,
                  project.edit_history, project.style_recipes, project.effects,
                  project.render_settings, project.original_outputs, project.edit_sequence]
        frozen = _json_snapshot(values)
        memo = {id(value): copied for value, copied in zip(values, frozen)}
        snapshot = copy.deepcopy(project, memo)
        super().__init__(parent)
        self.project, self.path = snapshot, path

    def run(self):
        try:
            from .studio_project import save_project
            save_project(self.project, self.path)
            self.done.emit("")
        except Exception as exc:  # reported in the page
            self.done.emit(str(exc) or type(exc).__name__)


class _StandalonePage:
    """The minimal Studio-page surface a text command needs, for a project
    that Studio does not have open (one undo step on a private stack, then an
    atomic save)."""

    def __init__(self, project):
        self.session = SimpleNamespace(project=project, undo_stack=QUndoStack())
        self.cue_controller = None

    def _changed(self, *_args, **_kwargs):
        return None


def _time_label(ms):
    seconds, millis = divmod(max(0, int(ms)), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}.{millis // 100}"


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

FILTERS = (("all", "全部字幕"), ("suggested", "有修改建议"), ("pending", "待确认"), ("changed", "已修改"))


def _map_position(opcodes, position, *, end=False, before_insert=False):
    """Index in the new text for ``position`` of the old text.

    At an insertion point the position has two places; ``before_insert``
    picks the one in front of the inserted text."""
    for tag, i1, i2, j1, j2 in opcodes:
        if before_insert and tag == "insert" and position == i1 and not end:
            return j1
        if tag == "equal":
            if i1 <= position < i2 or end and i1 < position <= i2:
                return j1 + (position - i1)
        elif tag in {"replace", "delete"}:
            if i1 <= position < i2:
                return j2 if end else j1
            if end and position == i2:
                return j2
        elif tag == "insert" and position == i1 and not end:
            continue
    return opcodes[-1][4] if opcodes else position


def _context(text, a, b, size=2):
    return text[max(0, a - size):a], text[b:b + size]


def rebase_issue(issue, old_text, new_text, opcodes=None):
    """Follow ``issue`` from ``old_text`` to ``new_text``.

    Whether a proposal is in the project is read from the text itself, so
    writes from this page, Studio, undo and redo all land in the same state:
    the original wording at its place = not adopted, the replacement there =
    adopted; neither = stale (never reuse old indices)."""
    original, replacement = issue["original"], issue["replacement"]
    a, b = issue["span"]
    current = replacement if issue["checked"] else original
    left, right = issue.get("context") or _context(old_text, a, b)
    if old_text == new_text:
        return True
    opcodes = opcodes if opcodes is not None else SequenceMatcher(None, old_text, new_text, autojunk=False).get_opcodes()
    start = _map_position(opcodes, a)
    end = _map_position(opcodes, b, end=True) if b > a else start
    starts = list(dict.fromkeys((start, _map_position(opcodes, a, before_insert=True))))

    def place(position, applied):
        length = len(replacement if applied else original)
        issue["span"] = (position, position + length)
        issue["checked"] = applied
        issue["context"] = _context(new_text, position, position + length)
        issue["stale"] = False
        issue.pop("anchor", None)
        return True

    # 1) The same place with its neighbours: decide adopted / not adopted.
    order = sorted((True, False), key=lambda flag: -len(replacement if flag else original))
    for applied in order:
        word = replacement if applied else original
        for candidate in starts:
            anchor = candidate - len(left)
            if anchor >= 0 and new_text.startswith(left + word + right, anchor):
                return place(candidate, applied)
    # 2) The place itself, without neighbours (a neighbour changed too).
    for applied in order:
        word = replacement if applied else original
        for candidate in starts:
            if word and new_text.startswith(word, candidate):
                return place(candidate, applied)
    if not replacement and original and start == end and current == original:
        return place(start, True)  # the characters this deletion named are gone
    # 3) A unique occurrence elsewhere in the caption.
    for applied, word in ((False, original), (True, replacement)):
        if not word:
            continue
        hits = [m.start() for m in re.finditer(re.escape(word), new_text)]
        if len(hits) == 1:
            return place(hits[0], applied)
    # Keep the text it was last valid in: undo/redo may bring that back.
    issue["anchor"] = (old_text, issue["checked"])
    issue["stale"], issue["checked"] = True, False
    return False


def rebase_issues(issues, old_text, new_text):
    """``rebase_issue`` for a caption's proposals. A stale one is checked
    again against the text it was last valid in, so a replacement that is
    undone (or redone) shows the proposal as it was, not as expired."""
    opcodes = SequenceMatcher(None, old_text, new_text, autojunk=False).get_opcodes()
    for issue in issues:
        if not issue["stale"]:
            rebase_issue(issue, old_text, new_text, opcodes)
            continue
        anchor = issue.get("anchor")
        if anchor is None:
            continue
        anchor_text, checked = anchor
        issue["stale"], issue["checked"] = False, checked
        if anchor_text == new_text:
            issue.pop("anchor", None)
        else:
            rebase_issue(issue, anchor_text, new_text)


def adopt_text(text, issues, adopt=True):
    """``text`` with ``issues`` adopted (or reverted), right to left."""
    for issue in sorted(issues, key=lambda item: item["span"][0], reverse=True):
        a, b = issue["span"]
        if adopt and not issue["checked"] and text[a:b] == issue["original"]:
            text = text[:a] + issue["replacement"] + text[b:]
        elif not adopt and issue["checked"] and text[a:a + len(issue["replacement"])] == issue["replacement"]:
            text = text[:a] + issue["original"] + text[a + len(issue["replacement"]):]
    return text


def issue_pair(row, issue):
    """(old, new) words of a proposal, e.g. 古龙 → 骨龙 for a 古 → 骨 hit.

    Used for the batch replace offered on right click and for the proposal
    line: whole words (like 记住), never a lone character that would replace
    every 古 in the project. None for deletions."""
    if not issue["replacement"]:
        return None
    key = (row["base"], issue["checked"], issue["span"])
    cached = issue.get("_pair")
    if cached is not None and cached[0] == key:
        return cached[1]
    text = row["base"]
    before, after = ((adopt_text(text, [issue], adopt=False), text) if issue["checked"]
                     else (text, adopt_text(text, [issue], adopt=True)))
    pair = single_replacement(before, after) if before != after else None
    pair = pair or (issue["original"], issue["replacement"])
    issue["_pair"] = (key, pair)
    return pair


def group_pair(row, group):
    """(old, new) for a batch replace started from a proposal group: the
    whole name when the group belongs to one (魔草巫灵 → 魔草乌灵), else the
    whole word (古龙 → 骨龙); never a lone character. None for deletions."""
    if group is None or group["options"] or group["after"] is None:
        return None
    before, after = group["before"], group["after"]
    changes = text_changes(before, after)
    if not changes:
        return None
    if len(group["parts"]) == 1 and not (group["name"] or group["formed"]):
        return issue_pair(row, row["issues"][group["parts"][0]])
    i1, i2, j1, j2 = changes[0][0], changes[-1][1], changes[0][2], changes[-1][3]
    for name, text, (x1, x2) in ((group["name"], before, (i1, i2)), (group["formed"], after, (j1, j2))):
        if not name:
            continue
        at = text.find(name)
        while at >= 0:
            if at <= x1 and x2 <= at + len(name):
                # The text around the changes is the same on both sides.
                left, right = x1 - at, at + len(name) - x2
                left = min(left, i1, j1)
                right = min(right, len(before) - i2, len(after) - j2)
                i1, i2, j1, j2 = i1 - left, i2 + right, j1 - left, j2 + right
                break
            at = text.find(name, at + 1)
        break
    old, new = before[i1:i2], after[j1:j2]
    if not old or not new:
        return None
    return old, new


class GlossaryProofreadPage(QWidget):
    back_requested = Signal()
    applied = Signal(str)
    # Set by the first-run tutorial while it runs: "AI 校对" then uses this offline
    # stand-in (same arguments as preview_glossary_correction) instead of a request.
    ai_stand_in = None

    def __init__(self, window):
        super().__init__()
        self.setObjectName("glossaryProofreadPage")
        self._window = window
        self._project_path = ""
        self._project = None
        self._studio_project = None
        self._standalone = None
        self._stack = None
        self._writing = False
        self._binding = None
        self._snapshot = None
        self._snapshot_digest = None
        self._library_ids = ()
        self._inherit_origin = ""
        self._receipt = None
        self._worker = None
        self._worker_ai = False
        self._worker_scope_all = True
        self._generation = 0
        self._rows = []
        self._by_id = {}
        self._flash = ""
        self._queued = None
        self._conflict_choices = {}
        self._conflict_rows = []
        self._review_choices = {}
        self._session_added = set()
        self._session_added_labels = set()
        self._ai_status = ""
        self._term_overrides = {}
        self._delete_confirm = None
        self._ime_commit_at = 0.0
        self._ime_composing = False
        self._player = CuePlayer(self)
        self._player.state_changed.connect(self._playing_changed)
        self._player.failed.connect(self._set_status)
        self._library_dirty = False
        self._save_thread = None
        self._save_again = False
        self._save_error = ""
        self._terms = TermIndex()
        self._excluded = set()  # search hits the user excluded: {(cue_id, start)}
        self._sticky = ("", set())  # (needle, captions just replaced): kept listed
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(self._save_now)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(140)
        self._filter_timer.timeout.connect(self._apply_filter)
        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.setInterval(120)
        self._count_timer.timeout.connect(self._refresh_replace_count)
        self._rematch_ids = set()
        self._rematch_timer = QTimer(self)
        self._rematch_timer.setSingleShot(True)
        self._rematch_timer.setInterval(500)
        self._rematch_timer.timeout.connect(self._rematch_changed)
        self._build()
        self.refresh_theme_palette()
        # Normally already loaded after Studio opened its project.
        from .stutter_cleanup import warm_text_analysis
        warm_text_analysis()

    # compatibility views ----------------------------------------------
    @property
    def _entries(self):
        """Flat list of (row, issue) proposals, for diagnostics and audits."""
        return [dict(issue, cue_id=row["cue_id"], before=row["base"], after=self._issue_after(row, issue))
                for row in self._rows for issue in row["issues"] if issue["kind"] != "suspect"]

    @staticmethod
    def _issue_after(row, issue):
        return adopt_text(row["base"], [issue], adopt=not issue["checked"]) if not issue["checked"] else row["base"]

    @property
    def suggestions(self):
        return self.list

    def pending_values(self):
        """{cue_id: text} still waiting to be written — always empty now:
        every action on this page is written to the project at once."""
        return {}

    def changed_values(self):
        """{cue_id: text} changed in the project since the page opened."""
        return {row["cue_id"]: row["base"] for row in self._rows if row["base"] != row["origin"]}

    # build ------------------------------------------------------------
    def _caption(self, text):
        label = QLabel(text)
        label.setObjectName("proofreadCaption")
        return label

    def _note(self, text=""):
        label = QLabel(text)
        label.setObjectName("proofreadNote")
        label.setWordWrap(True)
        return label

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 18, 28, 14)
        root.setSpacing(14)
        header = QHBoxLayout()
        header.setSpacing(16)
        self.back_button = QPushButton("返回结果")
        self.back_button.setObjectName("proofreadNav")
        self.back_button.setFixedHeight(44)
        self.back_button.clicked.connect(self._back)
        from .themed_icons import install_themed_icon
        install_themed_icon(self.back_button, "fa5s.arrow-left", "secondary")
        header.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignVCenter)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        title = QLabel("AI 词库校对")
        title.setObjectName("proofreadTitle")
        heading.addWidget(title)
        self.file_label = QLabel()
        self.file_label.setObjectName("proofreadFile")
        heading.addWidget(self.file_label)
        header.addLayout(heading, 1)
        self.status_label = QLabel()
        self.status_label.setObjectName("proofreadStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(420)
        self.status_label.setMaximumWidth(720)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(16)
        # ---------------------------------------------------------- left
        left = QFrame()
        left.setObjectName("proofreadPanel")
        # Sized by _fit_left_panel: grows with the interface zoom but never
        # takes the captions' room (at most ~1/3 of the page).
        left.setProperty("uiZoomOwnSize", True)
        self.left_panel = left
        left_outer = QVBoxLayout(left)
        left_outer.setContentsMargins(0, 0, 0, 0)
        left_scroll = QScrollArea()
        left_scroll.setObjectName("proofreadLeftScroll")
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_body = QWidget()
        left_body.setObjectName("proofreadLeftBody")
        left_scroll.setWidget(left_body)
        left_outer.addWidget(left_scroll)
        left_layout = QVBoxLayout(left_body)
        left_layout.setContentsMargins(18, 16, 18, 16)
        left_layout.setSpacing(8)
        left_layout.addWidget(self._caption("使用的词库"))
        self.library_list = QListWidget()
        self.library_list.setObjectName("proofreadList")
        self.library_list.setFixedHeight(128)
        self.library_list.itemChanged.connect(self._libraries_changed)
        left_layout.addWidget(self.library_list)
        self.library_summary = self._note()
        left_layout.addWidget(self.library_summary)
        rule = QFrame(); rule.setObjectName("proofreadRule"); rule.setFixedHeight(1)
        left_layout.addSpacing(4); left_layout.addWidget(rule); left_layout.addSpacing(4)
        left_layout.addWidget(self._caption("添加专有名词"))
        left_layout.addWidget(self._note(tr("只想改一句字幕，在右侧双击修改即可；这里把写法存进词库。每行一个：左边写常被听错的写法，"
                                            "右边写正确写法，用空格、“-”或 Tab 隔开（可直接从表格粘贴）；只写一个词就是标准写法。")))
        self.term_input = QPlainTextEdit()
        self.term_input.setObjectName("proofreadInput")
        self.term_input.setFixedHeight(104)
        bind_text(self.term_input, 'CHICHOO\n球球 CHICHOO\n古龙 - 骨龙', property='placeholderText')
        self.term_input.textChanged.connect(self._preview_terms)
        left_layout.addWidget(self.term_input)
        self.term_preview = QLabel()
        self.term_preview.setObjectName("proofreadTermPreview")
        self.term_preview.setWordWrap(True)
        self.term_preview.setTextFormat(Qt.TextFormat.RichText)
        self.term_preview.linkActivated.connect(self._flip_term)
        self.term_preview.hide()
        left_layout.addWidget(self.term_preview)
        target_row = QHBoxLayout()
        target_row.setSpacing(8)
        self.target_combo = QComboBox()
        self.target_combo.setEditable(True)
        self.target_combo.setObjectName("proofreadCombo")
        self.target_combo.lineEdit().setPlaceholderText(tr("加入的词库（可输入新名称）"))
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        self.target_combo.editTextChanged.connect(self._target_changed)
        target_row.addWidget(self.target_combo, 1)
        self.category_combo = QComboBox()
        self.category_combo.setObjectName("proofreadCombo")
        for category in CATEGORIES:
            self.category_combo.addItem(category, category)
        self.category_combo.setCurrentIndex(self.category_combo.findData("其他"))
        target_row.addWidget(self.category_combo)
        left_layout.addLayout(target_row)
        self.target_note = self._note()
        left_layout.addWidget(self.target_note)
        add_row = QHBoxLayout()
        self.add_button = QPushButton("加入词库")
        self.add_button.setObjectName("proofreadSecondary")
        self.add_button.setFixedHeight(40)
        self.add_button.clicked.connect(self._add_terms)
        add_row.addWidget(self.add_button)
        add_row.addStretch(1)
        left_layout.addLayout(add_row)
        self.add_status = self._note()
        self.add_status.hide()
        left_layout.addWidget(self.add_status)
        rule = QFrame(); rule.setObjectName("proofreadRule"); rule.setFixedHeight(1)
        left_layout.addSpacing(4); left_layout.addWidget(rule); left_layout.addSpacing(4)
        terms_header = QHBoxLayout()
        terms_header.addWidget(self._caption("词库中的规范词"))
        terms_header.addStretch(1)
        self.term_count = self._note()
        terms_header.addWidget(self.term_count)
        left_layout.addLayout(terms_header)
        self.term_filter = QLineEdit()
        self.term_filter.setObjectName("proofreadSearch")
        self.term_filter.setPlaceholderText(tr("筛选规范词或别名"))
        self.term_filter.textChanged.connect(self._fill_terms)
        left_layout.addWidget(self.term_filter)
        self.term_list = QListWidget()
        self.term_list.setObjectName("proofreadList")
        self.term_list.setMinimumHeight(170)
        self.term_list.itemClicked.connect(self._term_clicked)
        left_layout.addWidget(self.term_list, 1)
        body.addWidget(left, 0)

        # ---------------------------------------------------------- right
        right = QFrame()
        right.setObjectName("proofreadPanel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 16, 18, 12)
        right_layout.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self._caption("字幕"))
        self.count_label = self._note()
        # Wraps instead of forcing the page wider at large interface zoom.
        self.count_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.count_label, 1)
        self.stutter_toggle = QCheckBox(tr("口吃整理"))
        self.stutter_toggle.setObjectName("proofreadToggle")
        self.stutter_toggle.setToolTip(tr("列出同一人卡顿、起句重来的重复字（只改显示文字，不删音频）；"
                                          "采用后才写回"))
        self.stutter_toggle.setChecked(self._stored_stutter())
        self.stutter_toggle.toggled.connect(self._stutter_toggled)
        top.addWidget(self.stutter_toggle)
        self.local_button = QPushButton("按词库匹配")
        self.local_button.setObjectName("proofreadSecondary")
        self.local_button.setFixedHeight(40)
        bind_text(self.local_button, '只用所选词库里已确认的写法在本机匹配，不调用 AI', property='toolTip')
        self.local_button.clicked.connect(lambda: self._run(False))
        top.addWidget(self.local_button)
        self.ai_button = QPushButton("AI 校对")
        self.ai_button.setObjectName("proofreadAccent")
        self.ai_button.setFixedHeight(40)
        bind_text(self.ai_button, '用已配置的校对模型结合所选词库和上下文生成建议（会调用付费模型）；不会直接修改字幕',
                  property='toolTip')
        self.ai_button.clicked.connect(lambda: self._run(True))
        top.addWidget(self.ai_button)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("proofreadGhost")
        self.cancel_button.setFixedHeight(40)
        self.cancel_button.clicked.connect(self._cancel_run)
        self.cancel_button.hide()
        top.addWidget(self.cancel_button)
        right_layout.addLayout(top)
        from .studio_toolbar_layout import CommandBar, CommandFlowLayout
        filter_bar = CommandBar()
        filter_bar.setObjectName("proofreadFilterBar")
        filters = CommandFlowLayout(filter_bar)
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(6)
        # Filters left, bulk actions right; whole buttons wrap when narrow.
        filters.stretch_after = {len(FILTERS) - 1}
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons = {}
        for key, label in FILTERS:
            button = QPushButton(tr(label))
            button.setObjectName("proofreadFilter")
            button.setCheckable(True)
            button.setFixedHeight(36)
            button.setProperty("filterKey", key)
            button.setToolTip(tr({"all": "本工程全部字幕（条）",
                                  "suggested": "有修改建议的字幕条数；一条字幕可以有几处建议",
                                  "pending": "需要你看一眼的字幕条数：还没决定的建议，或疑似专名",
                                  "changed": "打开本页以来改过的字幕条数"}[key]))
            self.filter_group.addButton(button)
            self.filter_buttons[key] = button
            filters.addWidget(button)
        self.filter_buttons["all"].setChecked(True)
        self.filter_group.buttonClicked.connect(lambda *_: self._apply_filter())
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search = QLineEdit()
        self.search.setObjectName("proofreadSearch")
        self.search.setPlaceholderText(tr("查找字幕或词条（Ctrl+F）"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._search_changed)
        self.search.installEventFilter(self)
        search_row.addWidget(self.search, 1)
        self.replace_toggle = QPushButton(tr("替换…"))
        self.replace_toggle.setObjectName("proofreadGhost")
        self.replace_toggle.setFixedHeight(36)
        self.replace_toggle.setCheckable(True)
        bind_text(self.replace_toggle, '在这里展开替换（Ctrl+H）：沿用上面的查找文字，只需输入新写法；也可以在字幕里选字后右键批量替换',
                  property='toolTip')
        self.replace_toggle.toggled.connect(self._show_replace_bar)
        search_row.addWidget(self.replace_toggle)
        self.select_all = QPushButton("采用全部建议")
        self.select_none = QPushButton("全部不采用")
        bind_text(self.select_all, '把列表中显示的建议全部写回工程（一步，可撤销）', property='toolTip')
        bind_text(self.select_none, '列表中显示的、已采用的建议改回原文；其余建议标为不采用（一步，可撤销）', property='toolTip')
        for button, state in ((self.select_all, True), (self.select_none, False)):
            button.setObjectName("proofreadGhost")
            button.setFixedHeight(36)
            button.clicked.connect(lambda _=False, value=state: self._set_all(value))
            filters.addWidget(button)
        right_layout.addWidget(filter_bar)
        right_layout.addLayout(search_row)
        # find / replace bar (Ctrl+H, or 替换…)
        self.replace_bar = QFrame()
        self.replace_bar.setObjectName("proofreadReplaceBar")
        bar = QHBoxLayout(self.replace_bar)
        bar.setContentsMargins(10, 6, 6, 6)
        bar.setSpacing(8)
        replace_caption = QLabel(tr("替换为"))
        replace_caption.setObjectName("proofreadNote")
        bar.addWidget(replace_caption)
        self.replace_input = QLineEdit()
        self.replace_input.setObjectName("proofreadSearch")
        self.replace_input.setPlaceholderText(tr("新写法（Enter 替换）"))
        self.replace_input.installEventFilter(self)
        self.replace_input.textChanged.connect(lambda *_: self._replace_input_changed())
        bar.addWidget(self.replace_input, 2)
        # 2026-10-10 (user): replacing in a filtered list never quietly grows
        # to captions that are not listed; the whole project is a choice.
        self.replace_scope = QComboBox()
        self.replace_scope.setObjectName("proofreadCombo")
        self.replace_scope.addItem(tr("范围：当前列表"), "list")
        self.replace_scope.addItem(tr("范围：整个工程"), "project")
        bind_text(self.replace_scope, '当前列表＝上面的筛选和查找结果（包括还没滚动到的字幕）；整个工程＝全部字幕',
                  property='toolTip')
        self.replace_scope.currentIndexChanged.connect(lambda *_: self._refresh_replace_count())
        bar.addWidget(self.replace_scope)
        self.replace_go = QPushButton(tr("替换"))
        self.replace_go.setObjectName("proofreadSecondary")
        self.replace_go.setFixedHeight(32)
        bind_text(self.replace_go, '按范围替换列出的命中（排除的不改）；一步完成，可撤销', property='toolTip')
        self.replace_go.clicked.connect(self._replace_enter)
        bar.addWidget(self.replace_go)
        self.replace_count = QLabel()
        self.replace_count.setObjectName("proofreadReplaceCount")
        self.replace_count.setWordWrap(True)
        bar.addWidget(self.replace_count, 3)
        close = QPushButton("×")
        close.setObjectName("proofreadGhost")
        close.setFixedSize(32, 32)
        bind_text(close, '关闭查找替换（Esc）', property='toolTip')
        close.clicked.connect(lambda: self.replace_toggle.setChecked(False))
        bar.addWidget(close)
        self.replace_bar.hide()
        right_layout.addWidget(self.replace_bar)
        from PySide6.QtGui import QKeySequence, QShortcut
        # Keys come from the shared shortcut registry (customizable, 2026-10-13).
        page_shortcuts = {}
        for action_id, keys, handler in (("proofread.find", "Ctrl+F", self._focus_find),
                                         ("proofread.replace", "Ctrl+H", self._open_replace),
                                         ("proofread.undo", "Ctrl+Z", self._undo),
                                         ("proofread.redo", "Ctrl+Y", self._redo),
                                         ("proofread.redo_alt", "Ctrl+Shift+Z", self._redo)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)
            page_shortcuts[action_id] = shortcut
        from .shortcut_registry import keep_keys
        keep_keys(page_shortcuts)
        self.hint_label = QLabel()
        self.hint_label.setObjectName("proofreadHint")
        self.hint_label.setWordWrap(True)
        self.hint_label.hide()
        right_layout.addWidget(self.hint_label)
        # 2026-10-13: what this page checks right now, and the next step when
        # the project brought no glossary (never a blank page to puzzle over).
        self.scope_banner = QFrame()
        self.scope_banner.setObjectName("proofreadScope")
        scope_row = QHBoxLayout(self.scope_banner)
        scope_row.setContentsMargins(10, 6, 6, 6)
        self.scope_text = QLabel()
        self.scope_text.setObjectName("proofreadScopeText")
        self.scope_text.setWordWrap(True)
        scope_row.addWidget(self.scope_text, 1)
        self.scope_use_home = QPushButton(tr("用首页启用的词库检查"))
        self.scope_use_home.setObjectName("proofreadScopeUseHome")
        self.scope_use_home.clicked.connect(self._use_home_libraries)
        scope_row.addWidget(self.scope_use_home)
        self.scope_dismiss = QPushButton(tr("知道了"))
        self.scope_dismiss.setObjectName("proofreadGhost")
        self.scope_dismiss.clicked.connect(self._dismiss_scope_banner)
        scope_row.addWidget(self.scope_dismiss)
        self.scope_banner.hide()
        right_layout.addWidget(self.scope_banner)
        self.conflicts = ConflictPanel()
        self.conflicts.changed.connect(self._conflict_chosen)
        right_layout.addWidget(self.conflicts)
        self.conflicts.header.toggled.connect(
            lambda expanded: right_layout.setStretchFactor(self.conflicts, 3 if expanded else 0))
        self.list = CaptionReviewList()
        self.list.setProperty("uiZoomOwnSize", True)
        self.list.stutter = self.stutter_toggle.isChecked()
        self.list.play_requested.connect(self._play)
        self.list.edit_requested.connect(self._edit)
        self.list.edit_committed.connect(self._edit_committed)
        self.list.issue_toggled.connect(self._toggle_issue)
        self.list.remember_requested.connect(self._remember)
        self.list.revert_requested.connect(self._revert)
        self.list.context_requested.connect(self._context_menu)
        self.list.group_dismissed.connect(self._dismiss_group)
        self.list.group_manual.connect(self._manual_group)
        self.list.hit_toggled.connect(self._toggle_hit)
        right_layout.addWidget(self.list, 1)
        body.addWidget(right, 1)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.setSpacing(12)
        self.footer_note = self._note(tr("本页的修改会直接写回工程（字幕工作台、预览和导出同时更新）；"
                                         "建议要点一下或勾选才采用。可撤销 / 重做（Ctrl+Z / Ctrl+Y）。"))
        footer.addWidget(self.footer_note, 1)
        self.undo_button = QPushButton("撤销")
        self.undo_button.setObjectName("proofreadGhost")
        self.undo_button.setFixedHeight(42)
        self.undo_button.setMinimumWidth(110)
        self.undo_button.clicked.connect(self._undo)
        self.undo_button.setEnabled(False)
        footer.addWidget(self.undo_button)
        self.redo_button = QPushButton("重做")
        self.redo_button.setObjectName("proofreadGhost")
        self.redo_button.setFixedHeight(42)
        self.redo_button.setMinimumWidth(110)
        self.redo_button.clicked.connect(self._redo)
        self.redo_button.setEnabled(False)
        footer.addWidget(self.redo_button)
        # Kept for audits and old callers: there is nothing left to apply.
        self.apply_button = QPushButton("应用修改")
        self.apply_button.setObjectName("proofreadPrimary")
        self.apply_button.hide()
        root.addLayout(footer)
        self._fit_left_panel()

    def refresh_theme_palette(self):
        t = _theme()
        colors = mark_colors(t)
        self.setStyleSheet(f"""
QWidget#glossaryProofreadPage {{ background: transparent; }}
QScrollArea#proofreadLeftScroll, QWidget#proofreadLeftBody {{ background: transparent; border: 0; }}
QScrollArea#proofreadLeftScroll > QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QFrame#proofreadPanel {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 12px; }}
QLabel#proofreadTitle {{ color: {t.text}; font-size: 26px; font-weight: 800; background: transparent; }}
QLabel#proofreadFile {{ color: {t.text_secondary}; font-size: 15px; background: transparent; }}
QLabel#proofreadStatus {{ color: {t.text_secondary}; font-size: 15px; background: transparent; }}
QLabel#proofreadCaption {{ color: {t.text}; font-size: 17px; font-weight: 700; background: transparent; }}
QLabel#proofreadNote {{ color: {t.text_muted}; font-size: 14px; background: transparent; }}
QLabel#proofreadReplaceCount {{ color: {t.text_secondary}; font-size: 14px; background: transparent; }}
QLabel#proofreadReplaceCount[warn="true"] {{ color: {legible(t.warning, t.surface, t)}; font-weight: 700; }}
QLabel#proofreadTermPreview {{ color: {t.text}; font-size: 14px; background: {t.panel}; border: 1px solid {t.border};
    border-radius: 8px; padding: 6px 8px; }}
QFrame#proofreadReplaceBar {{ background: {blend_hex(t.surface, t.accent, 0.06)}; border: 1px solid {t.border};
    border-radius: 9px; }}
QFrame#proofreadRule {{ background: {t.border}; border: 0; }}
QListWidget#proofreadList {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 8px; color: {t.text};
    font-size: 15px; padding: 4px; }}
QListWidget#proofreadList::item {{ padding: 4px 6px; border-radius: 6px; }}
QListWidget#proofreadList::item:hover {{ background: {t.selected}; }}
QPlainTextEdit#proofreadInput, QLineEdit#proofreadSearch {{ background: {t.panel}; border: 1px solid {t.border};
    border-radius: 8px; color: {t.text}; font-size: 16px; padding: 6px 8px;
    selection-background-color: {blend_hex(t.surface, t.accent, 0.45)}; selection-color: {t.text}; }}
QPlainTextEdit#proofreadInput:focus, QLineEdit#proofreadSearch:focus {{ border-color: {t.accent}; }}
QLineEdit#proofreadInlineEditor {{ background: {t.panel}; border: 2px solid {t.accent}; border-radius: 6px;
    color: {t.text}; padding: 0 4px; selection-background-color: {blend_hex(t.surface, t.accent, 0.45)};
    selection-color: {t.text}; }}
QComboBox#proofreadCombo {{ font-size: 15px; min-height: 34px; background: {t.panel}; color: {t.text};
    border: 1px solid {t.border}; border-radius: 8px; padding: 0 8px; }}
QComboBox#proofreadCombo:hover, QComboBox#proofreadCombo:focus {{ border-color: {t.accent}; }}
QComboBox#proofreadCombo:disabled {{ color: {t.disabled}; }}
QComboBox#proofreadCombo QLineEdit {{ background: transparent; color: {t.text}; border: 0; padding: 0;
    selection-background-color: {blend_hex(t.surface, t.accent, 0.35)}; }}
QComboBox#proofreadCombo::drop-down {{ border: 0; width: 22px; }}
QComboBox#proofreadCombo QAbstractItemView {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
    selection-background-color: {t.selected}; selection-color: {t.text}; outline: 0; }}
QCheckBox#proofreadToggle {{ color: {t.text}; font-size: 15px; spacing: 6px; background: transparent; }}
QPushButton#proofreadNav, QPushButton#proofreadSecondary {{ background: {t.surface}; color: {t.text};
    border: 1px solid {t.border_strong}; border-radius: 8px; font-size: 16px; font-weight: 600; padding: 0 16px; }}
QPushButton#proofreadNav:hover, QPushButton#proofreadSecondary:hover {{ background: {t.selected}; border-color: {t.accent}; }}
QPushButton#proofreadAccent {{ background: {blend_hex(t.surface, t.accent, 0.16)}; color: {t.accent_text};
    border: 1px solid {t.accent}; border-radius: 8px; font-size: 16px; font-weight: 700; padding: 0 16px; }}
QPushButton#proofreadAccent:hover {{ background: {blend_hex(t.surface, t.accent, 0.26)}; }}
QPushButton#proofreadGhost {{ background: transparent; color: {t.text_secondary}; border: 1px solid {t.border};
    border-radius: 8px; font-size: 15px; padding: 0 12px; }}
QPushButton#proofreadGhost:hover {{ color: {t.text}; background: {t.selected}; }}
QPushButton#proofreadGhost:checked {{ color: {t.accent_text}; border-color: {t.accent};
    background: {blend_hex(t.surface, t.accent, 0.12)}; }}
QPushButton#proofreadGhost:disabled {{ color: {t.disabled}; }}
QPushButton#proofreadFilter {{ background: transparent; color: {t.text_secondary}; border: 1px solid {t.border};
    border-radius: 8px; font-size: 15px; padding: 0 12px; }}
QPushButton#proofreadFilter:hover {{ color: {t.text}; background: {t.selected}; }}
QPushButton#proofreadFilter:checked {{ background: {blend_hex(t.surface, t.accent, 0.16)}; color: {t.accent_text};
    border-color: {t.accent}; font-weight: 700; }}
QPushButton#proofreadPrimary {{ background: {t.accent}; color: {t.text_on_accent}; border: 1px solid {t.accent_pressed};
    border-radius: 8px; font-size: 17px; font-weight: 700; padding: 0 22px; }}
QPushButton#proofreadPrimary:hover {{ background: {t.accent_hover}; }}
QPushButton#proofreadPrimary:disabled, QPushButton#proofreadAccent:disabled, QPushButton#proofreadSecondary:disabled {{
    background: {t.panel}; color: {t.disabled}; border-color: {t.border}; }}
QLabel#proofreadHint {{ background: {blend_hex(t.surface, t.info, 0.10)}; color: {t.text};
    border: 1px solid {blend_hex(t.surface, t.info, 0.35)}; border-radius: 8px; font-size: 15px; padding: 8px 12px; }}
QFrame#proofreadConflicts {{ background: {blend_hex(t.surface, t.warning, 0.08)};
    border: 1px solid {blend_hex(t.surface, t.warning, 0.40)}; border-radius: 10px; }}
QPushButton#proofreadConflictHeader {{ background: transparent; border: 0; color: {legible(t.warning, t.surface, t)}; font-size: 16px;
    font-weight: 700; text-align: left; padding: 4px 2px; }}
QPushButton#proofreadConflictHeader[resolved="true"] {{ color: {t.text_secondary}; }}
QPushButton#proofreadConflictHeader:hover {{ color: {t.text}; }}
QLabel#proofreadConflictExplain {{ color: {t.text_secondary}; font-size: 15px; background: transparent; padding-top: 5px; }}
QScrollArea#proofreadConflictScroll, QWidget#proofreadConflictBody {{ background: transparent; border: 0; }}
QFrame#proofreadConflictRow {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; }}
QLabel#proofreadConflictTitle {{ color: {t.text}; font-size: 16px; font-weight: 700; background: transparent; }}
QLabel#proofreadConflictValue {{ color: {t.text}; font-size: 16px; font-weight: 700; background: transparent; }}
QPushButton#proofreadConflictChoice {{ background: {t.surface}; color: {t.text_secondary}; border: 1px solid {t.border};
    border-radius: 7px; font-size: 14px; padding: 4px 12px; min-height: 26px; }}
QPushButton#proofreadConflictChoice:hover {{ border-color: {t.accent}; color: {t.text}; }}
QPushButton#proofreadConflictChoice:checked {{ background: {blend_hex(t.surface, t.accent, 0.16)}; color: {t.accent_text};
    border-color: {t.accent}; font-weight: 700; }}
QMenu#proofreadMenu {{ background: {t.surface_elevated}; color: {t.text}; border: 1px solid {t.border_strong};
    border-radius: 8px; padding: 6px; font-size: 15px; }}
QMenu#proofreadMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu#proofreadMenu::item:selected {{ background: {t.selected}; color: {t.text}; }}
QMenu#proofreadMenu::item:disabled {{ color: {t.disabled}; }}
QMenu#proofreadMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 8px; }}
""")
        self._term_colors = colors
        self.list.update()

    def _fit_left_panel(self):
        from .ui_zoom import zoom_factor
        width = min(round(430 * zoom_factor()), max(300, int(self.width() * 0.34)))
        if self.left_panel.width() != width or self.left_panel.minimumWidth() != width:
            self.left_panel.setFixedWidth(width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_left_panel()

    def apply_ui_zoom(self, _factor):
        self._fit_left_panel()

    # settings -----------------------------------------------------------
    @staticmethod
    def _stored_stutter():
        from PySide6.QtCore import QSettings
        value = QSettings("2ByteASR", "2ByteASR").value("glossary_proofread/stutter_cleanup", True)
        return str(value).lower() not in {"false", "0"}

    def _stutter_toggled(self, enabled):
        from PySide6.QtCore import QSettings
        QSettings("2ByteASR", "2ByteASR").setValue("glossary_proofread/stutter_cleanup", bool(enabled))
        self.list.stutter = bool(enabled)
        self._refresh_view()

    # task -------------------------------------------------------------
    def open_task(self, project_path, project=None, hint="", *, studio=None):
        """Show every caption of ``project_path``; match locally right away."""
        if studio is not None and project is not studio.session.project:
            raise ValueError('Proofreading must bind the open Studio document')
        if not self.settle_writes():
            return  # the user keeps the unsaved edits of the open project
        self._save_error = ""
        self._player.stop()
        self._cancel_worker()
        self._generation += 1
        self._studio_project = project if studio is not None else None
        self._project_path = str(project_path or "")
        self._project = project
        self._standalone = None
        self._receipt = None
        self._ai_status = ""
        live, studio_page = self._live_project()
        if live is not None and studio_page is None:
            self._standalone = _StandalonePage(live)
        self._bind_stack(getattr(studio_page.session, "undo_stack", None) if studio_page is not None
                         else (self._standalone.session.undo_stack if self._standalone is not None else None))
        self.file_label.setText(Path(getattr(getattr(live, "media", None), "path", "") or self._project_path).name)
        self.hint_label.setText(str(hint or ""))
        self.hint_label.setVisible(bool(hint))
        self._conflict_choices = self._load_choices(live)
        inherited, origin = inherited_library_ids(live) if live is not None else ((), "")
        self._inherit_origin = origin
        self._fill_libraries(live, keep=inherited)
        self._show_scope_banner(inherited, origin)
        self.term_input.clear()
        self.add_status.hide()
        self._build_rows(live, start_checks=False)
        self.filter_buttons["all"].setChecked(True)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._refresh_view()
        from .ui_zoom import apply_to
        apply_to(self)
        # The captions paint first; the local checks start right after. Both
        # threads starting with the page held its first paint back ~1 s
        # (2026-10-10 measurement: 1.25 s → 0.29 s to the first paint).
        generation = self._generation
        self._checks_pending = True
        QTimer.singleShot(150, lambda: self._start_checks(generation))
        if self._selected_ids():
            self._set_status(tr("已载入 {count} 条字幕 · 正在按词库匹配（本地）…", count=len(self._rows)))
        else:
            self._set_status(tr("已载入 {count} 条字幕 · 未选择词库：可以直接阅读、试听和修改；"
                                "勾选左侧词库后会匹配专有名词", count=len(self._rows)))

    def checks_running(self):
        """True while local checks are scheduled or running (tests, audits)."""
        return bool(getattr(self, "_checks_pending", False) or self._worker is not None
                    or getattr(self, "_stutter_threads", None))

    def _start_checks(self, generation):
        if generation != self._generation:
            return  # another project was opened meanwhile
        self._checks_pending = False
        live, _studio = self._live_project()
        if live is None:
            return

        def then():
            if generation == self._generation and self._selected_ids():
                self._run(False)

        # One after the other: Python threads do not run in parallel anyway,
        # and two busy threads left the window about a third of the
        # interpreter lock (every Qt event passes Python filters).
        self._start_stutter(live, then=then)

    def _bind_stack(self, stack):
        previous = self._stack
        if previous is stack:
            self._update_undo_buttons()
            return
        if previous is not None:
            for signal, slot in ((previous.indexChanged, self._stack_changed),
                                 (previous.canUndoChanged, self._update_undo_buttons),
                                 (previous.canRedoChanged, self._update_undo_buttons)):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self._stack = stack
        if stack is not None:
            stack.indexChanged.connect(self._stack_changed)
            stack.canUndoChanged.connect(self._update_undo_buttons)
            stack.canRedoChanged.connect(self._update_undo_buttons)
        self._update_undo_buttons()

    def _live_stack(self):
        """The bound undo stack, or None once its owner has destroyed it
        (a stack being destroyed still emits its signals into our slots)."""
        stack = self._stack
        if stack is not None:
            from shiboken6 import isValid
            if not isValid(stack):
                self._stack = stack = None
        return stack

    def _update_undo_buttons(self, *_args):
        stack = self._live_stack()
        can_undo = bool(stack is not None and stack.canUndo())
        can_redo = bool(stack is not None and stack.canRedo())
        self.undo_button.setEnabled(can_undo)
        self.redo_button.setEnabled(can_redo)
        self.undo_button.setToolTip(tr("撤销：{what}", what=stack.undoText()) if can_undo else "")
        self.redo_button.setToolTip(tr("重做：{what}", what=stack.redoText()) if can_redo else "")

    def _studio_page(self):
        studio = existing_page(self._window, "studio")
        path = str(getattr(studio, "project_path", "") or "")
        project = getattr(getattr(studio, "session", None), "project", None)
        if self._studio_project is not None:
            return studio if project is self._studio_project else None
        if (studio is not None and project is not None and path and self._project_path
                and os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(self._project_path))):
            return studio
        return None

    def _live_project(self):
        """Studio's open project when it has this file open, else our copy."""
        studio = self._studio_page()
        if studio is not None:
            return studio.session.project, studio
        if self._studio_project is not None:
            return None, None  # The editor replaced the document; never write to its old copy.
        if self._project is None and self._project_path:
            from .studio_project import load_project
            self._project = load_project(self._project_path)
        return self._project, None

    # rows -------------------------------------------------------------
    def _protected_terms(self):
        if self._snapshot is None:
            return ()
        return tuple({value for library in self._snapshot.libraries for term in library.terms
                      for value in (term.canonical, *term.aliases) if value})

    def _build_rows(self, project, *, start_checks=True):
        from .studio_cue_table import _speaker_color, _speaker_name
        rows = []
        if project is not None:
            cues = sorted(project.cues, key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
            for number, cue in enumerate(cues, 1):
                rows.append(dict(cue_id=cue.id, number=f"#{number}", time=_time_label(cue.start_ms),
                                 start_ms=cue.start_ms, end_ms=cue.end_ms, base=cue.text, origin=cue.text,
                                 speaker=(_speaker_name(project, cue.speaker_id),
                                          _speaker_color(project, cue.speaker_id).name()),
                                 issues=[], applied=False, remembered=None))
        self._rows = rows
        self._by_id = {row["cue_id"]: row for row in rows}
        self.list.set_rows(self._rows)
        if project is not None and start_checks:
            self._start_stutter(project)

    def _preferred_spellings(self):
        if self._snapshot is None:
            return ()
        return tuple({term.canonical for library in self._snapshot.libraries for term in library.terms
                      if term.confirmed and term.canonical})

    def _schedule_local_checks(self):
        timer = getattr(self, "_local_timer", None)
        if timer is None:
            timer = self._local_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self._start_stutter(self._live_project()[0]))
        timer.start(600)

    def _start_stutter(self, project, then=None):
        if project is None:
            return
        self._stutter_generation = getattr(self, "_stutter_generation", 0) + 1
        generation = self._stutter_generation
        entries = [(row["cue_id"], row["start_ms"], row["base"]) for row in self._rows]
        thread = _StutterThread(_review_copy(project), self._protected_terms(), entries, {},
                                self._preferred_spellings(), self)
        self._stutter_threads = getattr(self, "_stutter_threads", set()) | {thread}

        def ready(result):
            if generation != self._stutter_generation:
                return
            live, _studio = self._live_project()
            if live is None:
                return
            decisions = self._decisions()
            current = {cue.id: cue.text for cue in live.cues}
            fresh = {cue_id: hits for cue_id, (text, hits) in result.get("stutter", {}).items()
                     if current.get(cue_id) == text}
            self._add_stutter_issues(live, set(fresh), fresh)
            self._set_consistency(result.get("consistency", {}), result.get("texts", {}))
            self._set_evidence(result.get("evidence", {}))
            for row in self._rows:
                self._apply_decisions(row, decisions)
            self._apply_filter()

        def finished():
            self._stutter_threads.discard(thread)
            responsive_background(False)
            thread.deleteLater()
            if then is not None:
                then()

        thread.ready.connect(ready)
        thread.finished.connect(finished)
        responsive_background(True)
        thread.start()

    def _decisions(self):
        """Proposals the user already answered (dismissed), by identity."""
        return {issue_key(row["cue_id"], issue): issue["checked"] for row in self._rows
                for issue in row["issues"] if issue["reviewed"] and not issue["checked"]}

    @staticmethod
    def _apply_decisions(row, decisions):
        for issue in row["issues"]:
            key = issue_key(row["cue_id"], issue)
            if key in decisions and not issue["checked"]:
                issue["reviewed"] = True

    @staticmethod
    def _keep_applied(row, kinds):
        """Proposals already written stay attached while their check reruns."""
        return [issue for issue in row["issues"] if issue["kind"] in kinds and issue["checked"] and not issue["stale"]]

    def _set_evidence(self, found):
        """Two-recognizer readings, anchored to the caption as it is now."""
        for row in self._rows:
            kept = self._keep_applied(row, {"evidence"})
            row["issues"] = [issue for issue in row["issues"] if issue["kind"] != "evidence"] + kept
            source, hits = found.get(row["cue_id"], ("", ()))
            text = row["base"]
            for span, original, replacement, agreed, provider in hits:
                if agreed:
                    reason = tr("FireRed 和 Qwen 都听成「{text}」", text=replacement)
                else:
                    reason = tr("{model} 听成「{text}」；两个模型不一致，请听原声后选择", model=provider, text=replacement)
                issue = _issue("evidence", span, original, replacement, checked=False, reason=reason)
                issue["default"] = bool(agreed)
                if text != source and not relocate_issue(issue, text):
                    continue  # the caption was edited there; the edit decides
                if any(issue_key(row["cue_id"], other) == issue_key(row["cue_id"], issue) for other in kept):
                    continue
                issue["context"] = _context(text, *issue["span"])
                row["issues"].append(issue)

    def _set_consistency(self, found, texts):
        """Spelling-consistency proposals, anchored to the text they were found in."""
        for row in self._rows:
            kept = self._keep_applied(row, {"consistency"})
            row["issues"] = [issue for issue in row["issues"] if issue["kind"] != "consistency"] + kept
            if texts.get(row["cue_id"]) != row["base"]:
                continue  # the caption changed since; the next check covers it
            for hit in found.get(row["cue_id"], ()):
                issue = _issue("consistency", hit.span, hit.original, hit.replacement, checked=False,
                               reason=hit.reason, hit=hit)
                issue["default"] = bool(hit.default_selected)
                issue["context"] = _context(row["base"], *issue["span"])
                row["issues"].append(issue)

    def _add_stutter_issues(self, project, cue_ids=None, found=None):
        if project is None:
            return
        if found is None:
            found = {cue_id: hits for cue_id, (_text, hits) in
                     compute_stutter(project, cue_ids, self._protected_terms()).items()}
        for row in self._rows:
            if cue_ids is not None and row["cue_id"] not in cue_ids:
                continue
            kept = self._keep_applied(row, {"stutter", "merge"})
            row["issues"] = [issue for issue in row["issues"] if issue["kind"] not in {"stutter", "merge"}] + kept
            for hit in found.get(row["cue_id"], ()):
                kind = "stutter" if hit.source == "stutter" else "merge"
                issue = _issue(kind, hit.span, hit.original, "", checked=False,
                               reason=hit.reason, hit=hit, evidence=hit.evidence)
                issue["default"] = bool(hit.default_selected)
                issue["context"] = _context(row["base"], *issue["span"])
                row["issues"].append(issue)

    def _refresh_view(self):
        self.list.stutter = self.stutter_toggle.isChecked()
        self._apply_filter()

    def _groups(self, row):
        return issue_groups(row, self._terms, self.stutter_toggle.isChecked())

    def _row_state(self, row):
        """(has proposals, needs a look, changed here) of one caption.

        A group is one proposal (one decision); a suspected name without a
        candidate is something to look at, not a proposal."""
        groups = self._groups(row)
        suggested = bool(groups)
        pending = any(group["state"] != "adopted" and not group["reviewed"] for group in groups) or any(
            issue["kind"] == "suspect" and not issue["stale"] and not issue["reviewed"] for issue in row["issues"])
        changed = row["base"] != row["origin"]
        return suggested, pending, changed

    def _needle(self):
        text = self.search.text()
        return text if text.strip() else ""

    def _search_changed(self, *_args):
        self._filter_timer.start()
        self._excluded = set()
        self._sticky = ("", set())
        self._delete_confirm = None
        if self.replace_bar.isVisible():
            self._count_timer.start()

    def _apply_filter(self, *_args):
        self._filter_timer.stop()
        button = self.filter_group.checkedButton()
        key = str(button.property("filterKey")) if button is not None else "all"
        raw = self._needle()
        needle = raw.casefold()
        sticky_needle, sticky = getattr(self, "_sticky", ("", set()))
        visible, counts = [], dict(all=0, suggested=0, pending=0, changed=0)
        for index, row in enumerate(self._rows):
            suggested, pending, changed = self._row_state(row)
            counts["all"] += 1
            counts["suggested"] += suggested
            counts["pending"] += pending
            counts["changed"] += changed
            if key == "suggested" and not suggested or key == "pending" and not pending or key == "changed" and not changed:
                continue
            if needle and needle not in (row["base"] + " " + row["origin"] + " " + " ".join(
                    f"{i['original']} {i['replacement']}" for i in row["issues"])).casefold() and not (
                    raw == sticky_needle and row["cue_id"] in sticky):
                # Captions just replaced stay listed (changed) until the
                # search changes: the result does not vanish under the user.
                continue
            visible.append(index)
        for filter_key, label in FILTERS:
            self.filter_buttons[filter_key].setText(tr("{label} {count} 条", label=tr(label), count=counts[filter_key]))
        empty = {"all": tr("这个工程没有字幕"),
                 "suggested": tr("目前没有修改建议") + ("" if self._selected_ids() else tr("（尚未选择词库）")),
                 "pending": tr("没有需要你确认的地方"), "changed": tr("本页还没有修改")}
        self.list.empty_text = tr("没有符合搜索条件的字幕") if needle else empty.get(key, "")
        anchor = self.list._top_anchor() if self.list.visible else None
        self.list.find = dict(needle=raw, replace=self.replace_input.text() if self.replace_bar.isVisible() and raw else None,
                              excluded=frozenset(getattr(self, "_excluded", ())))
        self.list.set_visible(visible)
        self.list._restore_anchor(anchor)
        self._selection_changed()
        if self.replace_bar.isVisible():
            self._refresh_replace_count()

    def checked_hits(self):
        stutter = self.stutter_toggle.isChecked()
        return [issue["hit"] for row in self._rows for issue in row["issues"]
                if issue["checked"] and actionable(issue, stutter) and issue["hit"] is not None]

    def proposal_counts(self):
        """Units shown above the list: proposals are groups (one decision
        each), suspected names are counted apart, captions by caption."""
        groups = [group for row in self._rows for group in self._groups(row)]
        return dict(captions=len(self._rows), proposals=len(groups),
                    adopted=sum(group["state"] == "adopted" for group in groups),
                    asked=sum(group["pending"] and group["state"] != "adopted" and not group["reviewed"] for group in groups),
                    suspects=sum(issue["kind"] == "suspect" and not issue["stale"] for row in self._rows
                                 for issue in row["issues"]),
                    changed=sum(1 for row in self._rows if row["base"] != row["origin"]))

    def _selection_changed(self, *_args):
        counts = self.proposal_counts()
        text = tr('共 {total} 条字幕 · 修改建议 {proposals} 处（已采用 {adopted} 处）', total=counts["captions"],
                  proposals=counts["proposals"], adopted=counts["adopted"])
        if counts["suspects"]:
            text += tr(' · 疑似专名 {count} 处', count=counts["suspects"])
        text += tr(' · 本页已改 {changed} 条', changed=counts["changed"])
        self.count_label.setText(text)
        self.count_label.setToolTip(tr("一处建议＝一个要决定的修改（同一个词里的几处算一处）；"
                                       "「有修改建议」「待确认」按字幕条数计；待确认包括还没决定的建议和疑似专名"))
        self.list.remember_targets = {"name": self._target_name()}
        self.list.update()

    # writing ------------------------------------------------------------
    def _write(self, values, *, label, kinds=None, manual=False, operation="edit", focus=None):
        """Write {cue_id: text} into the current project as one undo step.

        The single path for a direct edit, an adopted (or reverted) proposal,
        a batch replace and Ctrl+H: Studio, previews, exports, undo/redo and
        save all see the same document."""
        values = {cue_id: str(text) for cue_id, text in values.items()
                  if cue_id in self._by_id and str(text) != self._by_id[cue_id]["base"]}
        if not values:
            return 0
        project, studio = self._live_project()
        if project is None:
            self._set_status(tr("工程已关闭或被替换；本次没有修改字幕"))
            return 0
        current = {cue.id: cue.text for cue in project.cues}
        stale = [cue_id for cue_id in values if current.get(cue_id) != self._by_id[cue_id]["base"]]
        if stale:
            self._sync_from_project()
            self._set_status(tr("{count} 条字幕已在别处改变，已按工程里的文字刷新；本次没有修改", count=len(stale)))
            return 0
        from .studio_commands import BatchReplaceTextCommand
        kinds = kinds or {}
        changes = [{"cue_id": cue_id, "from": self._by_id[cue_id]["base"], "to": text, "manual": bool(manual),
                    "kinds": sorted(kinds.get(cue_id, ()))} for cue_id, text in values.items()]
        receipt = {**(self._receipt or {}), "kind": "proofread_workspace_apply", "source": "user_confirmed",
                   "operation": operation, "changes": changes, "library_ids": list(self._selected_ids())}
        receipt.pop("segments", None)
        if self._review_choices:
            receipt["spelling_choices"] = [
                {"key": key, "library_id": identity, "target": target, "scope": "project_proofreading"}
                for key, (identity, target) in sorted(self._review_choices.items())]
        glossary_ids = list(dict.fromkeys([*(project.glossary_ids or ()), *self._selected_ids()]))
        page = studio if studio is not None else self._standalone
        if page is None:
            self._standalone = page = _StandalonePage(project)
            self._bind_stack(page.session.undo_stack)
        command = BatchReplaceTextCommand(project, values, needle=label, changed=page._changed,
                                          glossary_ids=glossary_ids, review_receipt=receipt)
        command.setText(label)
        self._writing = True
        try:
            page.session.undo_stack.push(command)
        finally:
            self._writing = False
        self._sync_from_project(set(values))
        self._persist_soon(project, studio)
        if focus:
            self.list.ensure_visible(focus)
        return len(values)

    def _stack_changed(self, *_args):
        if self._live_stack() is None:
            self._update_undo_buttons()
            return
        if not self._writing:
            # Undo/redo here or in Studio: re-read every caption it touched.
            self._sync_from_project()
            project, studio = self._live_project()
            if project is not None:
                self._persist_soon(project, studio)
        self._update_undo_buttons()

    def _sync_from_project(self, cue_ids=None):
        """Follow the project's text: rows, proposals and their state."""
        project, _studio = self._live_project()
        if project is None:
            return
        texts = {cue.id: cue.text for cue in project.cues}
        if set(texts) != set(self._by_id):
            # Captions were added or removed (Studio): rebuild, keep answers.
            decisions, origins = self._decisions(), {row["cue_id"]: row["origin"] for row in self._rows}
            self._build_rows(project)
            for row in self._rows:
                row["origin"] = origins.get(row["cue_id"], row["origin"])
                self._apply_decisions(row, decisions)
            if self._selected_ids():
                self._run(False)
            self._apply_filter()
            return
        changed = []
        for cue_id in (cue_ids if cue_ids is not None else texts):
            row = self._by_id.get(cue_id)
            if row is None or texts.get(cue_id) is None or texts[cue_id] == row["base"]:
                continue
            self._rebase_row(row, texts[cue_id])
            changed.append(cue_id)
        if not changed:
            return
        # Excluded search hits were positions in the old text.
        self._excluded = {key for key in self._excluded if key[0] not in changed}
        self._rematch_ids |= set(changed)
        self._rematch_timer.start()
        self._schedule_local_checks()
        self._apply_filter()

    def _rebase_row(self, row, text):
        rebase_issues(row["issues"], row["base"], text)
        row["issues"] = [issue for issue in row["issues"] if not (issue["kind"] == "suspect" and issue["stale"])]
        row["base"] = text
        row["applied"] = text != row["origin"]
        if row.get("remembered") is not None and single_replacement(row["origin"], text) != row["remembered"]:
            row["remembered"] = None

    def _rematch_changed(self):
        ids, self._rematch_ids = self._rematch_ids, set()
        if ids and self._selected_ids():
            self._run(False, ids)

    def _persist_soon(self, project, studio):
        """With Studio open the change is an ordinary edit of its document:
        Studio autosaves it and Ctrl+S saves the project file. Without Studio
        the project file is written here, off the UI thread, after a pause."""
        if studio is not None:
            schedule = getattr(studio, "_schedule_autosave", None)
            if callable(schedule):
                schedule()
            self.applied.emit(self._project_path)
            return
        self._save_timer.start()

    def _save_now(self):
        project, studio = self._live_project()
        if project is None or studio is not None or not self._project_path:
            return
        if self._save_thread is not None and self._save_thread.isRunning():
            self._save_again = True
            return
        try:
            thread = _SaveThread(project, self._project_path, self)
        except Exception as exc:
            self._save_error = str(exc) or type(exc).__name__
            self._set_status(tr("修改还在本页，但没有保存到工程文件：{reason}。可以再试一次保存（离开本页时也会再试）",
                                reason=self._save_error[:200]))
            return
        self._save_thread = thread

        def done(error):
            if self._save_thread is thread:
                self._save_thread = None
            thread.deleteLater()
            self._save_error = error or ""
            if error:
                self._set_status(tr("修改还在本页，但没有保存到工程文件：{reason}。可以再试一次保存（离开本页时也会再试）",
                                    reason=error[:200]))
            if self._save_again:
                self._save_again = False
                self._save_now()
                return
            if not error:
                self.applied.emit(self._project_path)

        thread.done.connect(done)
        thread.start()

    def _flush_save(self):
        """Write any pending save before the page lets go of the project.

        True when everything written on this page is in the project file (or
        Studio owns the document); False when the last save failed."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_now()
        for _attempt in range(3):
            thread = self._save_thread
            if thread is None:
                break
            # The finished signal is queued; deliver it so the error is known.
            finished = thread.wait(15000)
            QApplication.processEvents()
            if not finished:
                # Still writing (slow or network drive): never report the
                # file as saved or let Studio read it half-written. The
                # thread stays tracked; its finished signal clears this.
                self._save_error = tr("工程文件仍在写入（磁盘较慢），请稍候重试")
                return False
            if self._save_thread is thread:
                self._save_thread = None
            if self._save_again:
                self._save_again = False
                self._save_now()
        return not getattr(self, "_save_error", "")

    def settle_writes(self, project_path=None):
        """Finish this page's writes before something else reads the file.

        Called when the page is left and before Studio opens a project. When
        the newest edits could not be saved the user decides: retry, or stay
        here with the edits (they are never dropped silently). False = stay."""
        self.list.commit_pending_edit()
        if self._flush_save():
            return True
        if project_path and self._project_path and (
                os.path.normcase(os.path.abspath(str(project_path)))
                != os.path.normcase(os.path.abspath(self._project_path))):
            return True  # another project: this one's edits stay on the page
        from PySide6.QtWidgets import QMessageBox
        while True:
            box = QMessageBox(self.window() if self.isVisible() else None)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("校对修改没有保存"))
            box.setText(tr("本页的修改还没有写进工程文件：{reason}\n\n修改仍保留在校对页，可以重试保存。",
                           reason=str(getattr(self, "_save_error", ""))[:200]))
            retry = box.addButton(tr("重试保存"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("留在校对页"), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(retry)
            self._show_message(box)
            if box.clickedButton() is not retry:
                return False
            self._save_error = ""
            self._save_now()
            if self._flush_save():
                self._set_status(tr("已保存到工程文件"))
                return True

    def _show_message(self, box):
        box.exec()

    def _undo(self):
        self.list.commit_pending_edit()
        stack = self._live_stack()
        if stack is not None and stack.canUndo():
            what = stack.undoText()
            stack.undo()
            self._set_status(tr("已撤销：{what}", what=what))

    def _redo(self):
        stack = self._live_stack()
        if stack is not None and stack.canRedo():
            what = stack.redoText()
            stack.redo()
            self._set_status(tr("已重做：{what}", what=what))

    def _saved_note(self):
        return (tr("工作台已更新（自动保存中，按 Ctrl+S 保存工程）") if self._live_project()[1] is not None
                else tr("工程已自动保存"))

    # proposals ----------------------------------------------------------
    def _set_all(self, adopt):
        """Adopt (or revert) every listed proposal group as a whole, one step.

        Groups that need a decision (several readings, or a change that
        would replace a name the library already knows) are never adopted
        in bulk: they stay listed as 待确认."""
        values, kinds, skipped = {}, {}, 0
        for index in self.list.visible:
            row = self._rows[index]
            chosen = []
            for group in self._groups(row):
                issues = [row["issues"][i] for i in group["parts"]]
                if adopt:
                    if group["state"] == "adopted" or any(issue["kind"] == "merge" for issue in issues):
                        continue
                    if group["options"] or group["pending"]:
                        skipped += 1
                        continue
                    chosen.extend(issue for issue in issues if not issue["checked"])
                else:
                    for issue in issues:
                        if not issue["checked"]:
                            issue["reviewed"] = True
                    chosen.extend(issue for issue in issues if issue["checked"])
            text = rewrite_text(row["base"], chosen, adopted=adopt)
            if text != row["base"]:
                values[row["cue_id"]] = text
                kinds[row["cue_id"]] = {issue["kind"] for issue in chosen}
            for issue in chosen:
                issue["reviewed"] = True
        left = tr("；{count} 处待确认的建议没有自动采用，请逐个决定", count=skipped) if adopt and skipped else ""
        if not values:
            self._apply_filter()
            self._set_status((tr("列表中没有可采用的建议") if adopt else tr("已把列表中的建议标为不采用")) + left)
            return
        label = tr("采用 {count} 条字幕的建议", count=len(values)) if adopt else tr("改回 {count} 条字幕的原文", count=len(values))
        written = self._write(values, label=label, kinds=kinds, operation="adopt_all" if adopt else "revert_all")
        if written:
            self._set_status(tr("已写回 {count} 条字幕：{what} · {saved} · 可撤销", count=written, what=label,
                                saved=self._saved_note()) + left)

    def _toggle_issue(self, cue_id, index):
        """Adopt or take back the whole group that holds proposal ``index``.

        One click never leaves half a name changed (疫病吐息, 2026-10-10); for
        readings of the same characters it picks that reading."""
        row = self._by_id.get(cue_id)
        if row is None or not 0 <= index < len(row["issues"]):
            return
        issue = row["issues"][index]
        if not actionable(issue, self.stutter_toggle.isChecked()):
            return
        self.list.commit_pending_edit()
        group = group_of(row, index, self._terms, self.stutter_toggle.isChecked())
        if group is None or group["options"]:
            parts = [issue]
            adopt = not issue["checked"]
        else:
            parts = [row["issues"][i] for i in group["parts"]]
            adopt = group["state"] != "adopted"
        moving = [part for part in parts if part["checked"] != adopt]
        text = rewrite_text(row["base"], moving, adopted=adopt)
        if text == row["base"]:
            for part in moving:
                part["stale"], part["checked"] = True, False  # its words are no longer there
            self.list.refresh_row(cue_id)
            self._set_status(tr("这处建议已对不上现在的字幕（已过期）"))
            self._apply_filter()
            return
        for part in parts:
            part["reviewed"] = True
        # The proposal's direction either way: 巫 → 乌.
        summary = change_summary(row["base"], text) if adopt else change_summary(text, row["base"])
        label = tr("采用建议：{what}", what=summary) if adopt else tr("取消采用：{what}", what=summary)
        if self._write({cue_id: text}, label=label, kinds={cue_id: {part["kind"] for part in parts}},
                       operation="adopt" if adopt else "revert", focus=cue_id):
            self._set_status(tr("{what}（{number}）· {saved}", what=label, number=row["number"],
                                saved=self._saved_note()))

    def _dismiss_group(self, cue_id, index):
        """忽略: the group is answered without changing the caption."""
        row = self._by_id.get(cue_id)
        group = group_of(row, index, self._terms, self.stutter_toggle.isChecked()) if row is not None else None
        if group is None:
            return
        for part in group["parts"]:
            if not row["issues"][part]["checked"]:
                row["issues"][part]["reviewed"] = True
        self._set_status(tr("已忽略这组建议（{number}，没有修改字幕）", number=row["number"]))
        self._apply_filter()

    def _manual_group(self, cue_id, index):
        """手动改写: the editor opens with the group's whole word selected."""
        row = self._by_id.get(cue_id)
        group = group_of(row, index, self._terms, self.stutter_toggle.isChecked()) if row is not None else None
        if group is None:
            return
        self.list.start_edit(cue_id, row["base"], select=group["span"])
        self._set_status(tr("直接输入完整写法，按 Enter 写回；Esc 取消"))

    def _toggle_hit(self, cue_id, start):
        """Exclude one search hit from the replacement, or bring it back."""
        key = (cue_id, int(start))
        self._excluded.symmetric_difference_update({key})
        self.list.find = dict(self.list.find, excluded=frozenset(self._excluded))
        self.list.refresh_row(cue_id)
        self._refresh_replace_count()

    # editing ----------------------------------------------------------
    def _edit(self, cue_id):
        row = self._by_id.get(cue_id)
        if row is None:
            return
        selection = self.list.selection()
        select = (selection[1], selection[2]) if selection is not None and selection[0] == cue_id else None
        self.list.start_edit(cue_id, row["base"], select=select)

    def _edit_committed(self, cue_id, text):
        row = self._by_id.get(cue_id)
        if row is None:
            return
        text = re.sub(r"[\r\n]+", " ", str(text)).strip()
        if not text:
            self._set_status(tr("字幕文字不能为空；如需删除这条字幕，请在字幕工作台操作"))
            return
        if text == row["base"]:
            return
        if self._write({cue_id: text}, label=tr("修改字幕 {number}", number=row["number"]), manual=True,
                       operation="manual_edit", focus=cue_id):
            self._set_status(tr("已写回 {number}：{text} · {saved}", number=row["number"], text=text[:40],
                                saved=self._saved_note()))

    def _revert(self, cue_id):
        row = self._by_id.get(cue_id)
        if row is None or row["base"] == row["origin"]:
            return
        if self._write({cue_id: row["origin"]}, label=tr("还原 {number}", number=row["number"]), manual=True,
                       operation="restore", focus=cue_id):
            self._set_status(tr("已把 {number} 还原为打开本页时的文字 · 可撤销", number=row["number"]))

    # batch replace ----------------------------------------------------------
    def replace_counts(self, old, new=None):
        """(occurrences, captions) of ``old`` in the whole current project
        (literal, letters in any case, the same rule as the replacement)."""
        project, _studio = self._live_project()
        if project is None or not old:
            return 0, 0
        hits = captions = 0
        for cue in project.cues:
            count = len(find_spans(cue.text, old))
            if count:
                hits += count
                captions += 1
        return hits, captions

    def replace_everywhere(self, old, new, *, operation="batch_replace"):
        """Replace every ``old`` with ``new`` in every caption of the project
        (not just the visible rows), as one undo step."""
        old, new = str(old or ""), str(new or "")
        if not old:
            self._set_status(tr("先输入要查找的文字"))
            return 0
        if old == new:
            self._set_status(tr("查找和替换的文字相同，没有修改"))
            return 0
        project, _studio = self._live_project()
        if project is None:
            self._set_status(tr("工程已关闭或被替换；本次没有修改字幕"))
            return 0
        self.list.commit_pending_edit()
        values = {}
        hits = 0
        for cue in project.cues:
            spans = find_spans(cue.text, old)
            if spans:
                values[cue.id] = replace_spans(cue.text, spans, new)
                hits += len(spans)
        if not values:
            self._set_status(tr("本工程没有「{old}」，没有修改", old=old))
            return 0
        label = (tr("替换「{old}」→「{new}」", old=old, new=new) if new else tr("删去「{old}」", old=old))
        written = self._write(values, label=label, manual=True, operation=operation)
        if written:
            self._set_status(tr("已在本工程 {captions} 条字幕里把「{old}」{action}（{hits} 处）· {saved} · 可撤销（Ctrl+Z）",
                                captions=written, old=old, hits=hits,
                                action=tr("替换为「{new}」", new=new) if new else tr("删去"),
                                saved=self._saved_note()))
        return written

    def replace_plan(self, scope=None):
        """What the replace box would write now: {cue_id: text}, counted.

        "list" is every caption the filter and search list (also those not
        scrolled to yet), "project" every caption. Hits are found in the
        caption text itself (never in times, speakers or labels), literally,
        and replaced right to left; excluded hits stay as they are."""
        needle, new = self._needle(), self.replace_input.text()
        scope = scope or self.replace_scope.currentData() or "list"
        listed = {self._rows[index]["cue_id"] for index in self.list.visible}
        values, hits, captions, excluded, outside = {}, 0, 0, 0, 0
        for row in self._rows:
            spans = find_spans(row["base"], needle)
            if not spans:
                continue
            if scope == "list" and row["cue_id"] not in listed:
                outside += len(spans)
                continue
            keep = [span for span in spans if (row["cue_id"], span[0]) not in self._excluded]
            excluded += len(spans) - len(keep)
            if keep:
                values[row["cue_id"]] = replace_spans(row["base"], keep, new)
                hits += len(keep)
                captions += 1
        return dict(values=values, hits=hits, captions=captions, excluded=excluded, outside=outside,
                    needle=needle, new=new, scope=scope)

    def start_batch_replace(self, old, new=None):
        """批量替换相同文字: ``old`` becomes the search, the replace box opens
        with the cursor in 新写法 — the old wording is never typed again."""
        old = str(old or "")
        if not old:
            return
        self.list.commit_pending_edit()
        anchor = self.list.current
        self.list.clear_selection()
        self.search.blockSignals(True)
        self.search.setText(old)
        self.search.blockSignals(False)
        self._excluded = set()
        self._sticky = ("", set())
        self._delete_confirm = None
        self.replace_input.blockSignals(True)
        self.replace_input.setText("" if new is None else str(new))
        self.replace_input.blockSignals(False)
        if self.replace_toggle.isChecked():
            self._show_replace_bar(True)
        else:
            self.replace_toggle.setChecked(True)
        self._apply_filter()
        if anchor:
            self.list.ensure_visible(anchor)
        self._focus_replace_input()
        # Started from a context menu: the closing menu hands the focus back
        # to where it was; take it again once the menu is gone.
        QTimer.singleShot(0, self._focus_replace_input)

    def _focus_replace_input(self):
        if self.replace_bar.isVisible():
            self.replace_input.setFocus(Qt.FocusReason.OtherFocusReason)
            self.replace_input.selectAll()

    def _context_menu(self, cue_id, target, global_pos):
        from PySide6.QtWidgets import QMenu
        row = self._by_id.get(cue_id)
        if row is None:
            return
        menu = QMenu(self)
        menu.setObjectName("proofreadMenu")
        selection = self.list.selection()
        if selection is not None and selection[0] == cue_id:
            _cue, start, end, chosen = selection
            hits, captions = self.replace_counts(chosen)
            batch = menu.addAction(tr("批量替换相同文字「{text}」…（{hits} 处，{captions} 条字幕）", text=chosen,
                                      hits=hits, captions=captions))
            batch.triggered.connect(lambda _=False, t=chosen: self.start_batch_replace(t))
            single = menu.addAction(tr("只改这一处…"))
            single.triggered.connect(lambda _=False, c=cue_id, s=(start, end): self.list.start_edit(
                c, self._by_id[c]["base"], select=s))
            copy_selected = menu.addAction(tr("复制「{text}」", text=chosen))
            copy_selected.triggered.connect(lambda _=False, t=chosen: QApplication.clipboard().setText(t))
            menu.addSeparator()
        pair = None
        stutter = self.stutter_toggle.isChecked()
        if target is not None and target[0] in {"mark", "check", "kind", "option"} and isinstance(target[2], int) \
                and 0 <= target[2] < len(row["issues"]):
            index = target[2]
            issue = row["issues"][index]
            group = group_of(row, index, self._terms, stutter)
            if group is not None and actionable(issue, stutter):
                if group["options"]:
                    text = (tr("取消采用这个写法") if issue["checked"] else
                            tr("采用这个写法「{new}」（写回工程）", new=issue["replacement"] or tr("删去")))
                else:
                    text = tr("取消采用这组建议") if group["state"] == "adopted" else tr("采用这组建议（写回工程）")
                action = menu.addAction(text)
                action.triggered.connect(lambda _=False, c=cue_id, i=index: self._toggle_issue(c, i))
                if group["state"] == "open" and not group["reviewed"]:
                    ignore = menu.addAction(tr("忽略这组建议"))
                    ignore.triggered.connect(lambda _=False, c=cue_id, i=index: self._dismiss_group(c, i))
                manual = menu.addAction(tr("手动改写这一处…"))
                manual.triggered.connect(lambda _=False, c=cue_id, i=index: self._manual_group(c, i))
                pair = issue_pair(row, issue) if group["options"] else group_pair(row, group)
        elif target is not None and target[0] == "mark":
            pair = single_replacement(row["origin"], row["base"])
        if pair is not None:
            old, new = pair
            hits, captions = self.replace_counts(old)
            text = (tr("批量替换「{old}」→「{new}」…（{hits} 处，{captions} 条字幕）", old=old, new=new,
                       hits=hits, captions=captions) if hits else
                    tr("本工程已没有『{old}』可替换", old=old))
            action = menu.addAction(text)
            action.setEnabled(bool(hits))
            action.triggered.connect(lambda _=False, o=old, n=new: self.start_batch_replace(o, n))
            remember = menu.addAction(tr("把『{old} → {new}』加入词库…", old=old, new=new))
            remember.triggered.connect(lambda _=False, o=old, n=new: self._remember_pair(o, n))
            copy_action = menu.addAction(tr("复制『{new}』", new=new))
            copy_action.triggered.connect(lambda _=False, n=new: QApplication.clipboard().setText(n))
            menu.addSeparator()
        edit = menu.addAction(tr("修改这句…"))
        edit.triggered.connect(lambda _=False, c=cue_id: self._edit(c))
        play = menu.addAction(tr("试听这句"))
        play.triggered.connect(lambda _=False, c=cue_id: self._play(c))
        if row["base"] != row["origin"]:
            restore = menu.addAction(tr("还原这句"))
            restore.triggered.connect(lambda _=False, c=cue_id: self._revert(c))
        from .ui_zoom import apply_to
        apply_to(menu)
        self._show_menu(menu, global_pos)

    def _show_menu(self, menu, global_pos):
        menu.exec(global_pos)

    # find / replace bar ------------------------------------------------------
    def _focus_find(self):
        self.search.setFocus()
        self.search.selectAll()

    def _open_replace(self):
        """Ctrl+H: the selected characters (in the list or the inline editor)
        become the search; otherwise the current search is kept."""
        selection = self.list.selection()
        chosen = selection[3] if selection is not None else (
            self.list.editor.selectedText() if self.list.editing() else "")
        if chosen:
            self.start_batch_replace(chosen)
            return
        self.replace_toggle.setChecked(True)
        if not self.search.text():
            self.search.setFocus()
        else:
            self.replace_input.setFocus()
            self.replace_input.selectAll()
        self._refresh_replace_count()

    def _show_replace_bar(self, shown):
        self.replace_bar.setVisible(bool(shown))
        self._delete_confirm = None
        if not shown:
            self._excluded = set()
        # The list shows each hit's replacement while the bar is open.
        self.list.find = dict(needle=self._needle(), excluded=frozenset(self._excluded),
                              replace=self.replace_input.text() if shown and self._needle() else None)
        self.list._layout_rows()
        if shown:
            self._refresh_replace_count()
        else:
            self.list.setFocus()

    def _replace_input_changed(self):
        self._delete_confirm = None
        self._count_timer.start()
        if self.replace_bar.isVisible() and self._needle():
            self.list.find = dict(self.list.find, replace=self.replace_input.text())
            self._preview_timer().start()

    def _preview_timer(self):
        timer = getattr(self, "_replace_preview_timer", None)
        if timer is None:
            timer = self._replace_preview_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(120)
            timer.timeout.connect(self.list._layout_rows)
        return timer

    def _refresh_replace_count(self):
        self._count_timer.stop()
        self.replace_count.setProperty("warn", False)
        plan = self.replace_plan()
        old, new = plan["needle"], plan["new"]
        listed_all = (self.filter_group.checkedButton() is self.filter_buttons["all"]
                      and not plan["outside"])
        self.replace_go.setEnabled(bool(plan["hits"]) and old != new)
        if not old:
            text = tr("先在上面的查找框输入要替换的文字，或在字幕里选字后右键「批量替换相同文字…」")
        elif old == new:
            text = tr("查找和替换相同，不会修改")
        elif not plan["hits"]:
            text = tr("没有要替换的「{old}」", old=old)
            if plan["excluded"]:
                text += tr("（{count} 处已排除）", count=plan["excluded"])
            if plan["outside"]:
                text += tr(" · 当前列表以外还有 {count} 处：范围选「整个工程」才会替换", count=plan["outside"])
        elif self._delete_confirm == (old, new, plan["scope"]):
            text = tr("替换为空会删去 {hits} 处「{old}」（{captions} 条字幕）；再按一次 Enter 确认删除",
                      hits=plan["hits"], old=old, captions=plan["captions"])
            self.replace_count.setProperty("warn", True)
        else:
            text = tr("将替换 {hits} 处（{captions} 条字幕）", hits=plan["hits"], captions=plan["captions"])
            if plan["scope"] == "project" or listed_all:
                text += tr("，即全部字幕里的「{old}」", old=old) if not plan["excluded"] else ""
            else:
                text += tr("，只在当前列表里")
            if plan["excluded"]:
                text += tr(" · 已排除 {count} 处", count=plan["excluded"])
            if plan["outside"]:
                text += tr(" · 列表以外的 {count} 处不改", count=plan["outside"])
            if not new:
                text += tr(" · 替换框为空：会删去这些文字")
                self.replace_count.setProperty("warn", True)
            else:
                text += tr(" · 点命中可排除 · Enter 替换")
        self.replace_count.setText(text)
        self.replace_count.style().unpolish(self.replace_count)
        self.replace_count.style().polish(self.replace_count)

    def _replace_enter(self):
        """Enter in the replace box (or 替换): replace the planned hits, one step."""
        plan = self.replace_plan()
        old, new = plan["needle"], plan["new"]
        if not old:
            self.search.setFocus()
            self._refresh_replace_count()
            return
        if not plan["hits"] or old == new:
            self._refresh_replace_count()
            return
        if not new and self._delete_confirm != (old, new, plan["scope"]):
            self._delete_confirm = (old, new, plan["scope"])
            self._refresh_replace_count()
            return
        self._delete_confirm = None
        self.list.commit_pending_edit()
        label = (tr("替换「{old}」→「{new}」（{hits} 处）", old=old, new=new, hits=plan["hits"]) if new
                 else tr("删去「{old}」（{hits} 处）", old=old, hits=plan["hits"]))
        sticky = self._sticky
        # The captions just replaced stay listed (now changed) for this search.
        self._sticky = (self._needle(), set(plan["values"]))
        written = self._write(plan["values"], label=label, manual=True, operation="find_replace")
        if not written:
            self._sticky = sticky
            self._refresh_replace_count()
            return
        self._excluded = set()
        self._apply_filter()
        self._set_status(tr("已在 {captions} 条字幕里替换 {hits} 处（{scope}）· {saved} · 可撤销（Ctrl+Z）",
                            captions=written, hits=plan["hits"],
                            scope=tr("整个工程") if plan["scope"] == "project" else tr("当前列表"),
                            saved=self._saved_note()))
        self._refresh_replace_count()

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if watched is getattr(self, "replace_input", None) or watched is getattr(self, "search", None):
            if not hasattr(self, "replace_bar"):
                return super().eventFilter(watched, event)
            kind = event.type()
            if kind == QEvent.Type.InputMethod:
                # Enter while an input method composes (or the same Enter that
                # committed the composition) must never replace anything.
                self._ime_composing = bool(event.preeditString())
                if event.commitString():
                    self._ime_commit_at = time.monotonic()
            elif kind == QEvent.Type.KeyPress:
                key = event.key()
                if key == Qt.Key.Key_Escape:
                    if self.replace_bar.isVisible():
                        self.replace_toggle.setChecked(False)
                    elif watched is self.search and self.search.text():
                        self.search.clear()
                    else:
                        self.list.setFocus()
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if self._ime_composing or time.monotonic() - self._ime_commit_at < 0.08:
                        return True
                    if watched is self.replace_input:
                        self._replace_enter()
                        return True
                    if watched is self.search and self.replace_bar.isVisible():
                        self.replace_input.setFocus()
                        return True
                    return False
        return super().eventFilter(watched, event)

    # remembering a correction in a library ---------------------------------
    def _target_name(self):
        identity = self._target_id()
        if not identity:
            return ""
        index = self.target_combo.findData(identity)
        return self.target_combo.itemText(index) if index >= 0 else identity

    def _target_id(self):
        text = self.target_combo.currentText().strip()
        index = self.target_combo.findText(text)
        if index >= 0:
            return str(self.target_combo.itemData(index) or "")
        return text

    def _remember(self, cue_id):
        row = self._by_id.get(cue_id)
        if row is None:
            return
        pair = single_replacement(row["origin"], row["base"])
        if pair is None:
            return
        if self._remember_pair(*pair):
            row["remembered"] = pair
            self.list.refresh_row(cue_id)

    def _remember_pair(self, old, new):
        import subtitle_core as legacy
        identity = self._target_id()
        if not identity:
            self.target_combo.setFocus()
            self._set_status(tr("先在左侧选择要加入的词库，再点「记住」"))
            return False
        prepare = getattr(self._window, "_prepare_glossary_for_task", None)
        if callable(prepare) and not prepare():
            self._set_status(tr("术语库里有尚未提交的编辑，请先保存或放弃后再添加"))
            return False
        category = str(self.category_combo.currentData() or "其他")
        try:
            legacy.add_learned_mapping(identity, new, new, category=category, origin="手动")
            legacy.add_learned_mapping(identity, old, new, category=category, origin="手动")
        except (OSError, ValueError, TypeError) as exc:
            self._set_status(tr("没有加入词库：{reason}", reason=str(exc)[:160]))
            return False
        self._session_added.add((identity, new))
        self._session_added_labels.add(new)
        self._notify_library_changed()
        live, _studio = self._live_project()
        chosen = set(self._selected_ids()) | {identity}
        self._fill_libraries(live, keep=chosen, target=identity)
        self._set_status(tr("已把「{old} → {new}」加入「{library}」（只改词库，没有改字幕）",
                            old=old, new=new, library=self._target_name() or identity))
        self._apply_filter()
        return True

    # conflict choices -------------------------------------------------
    def _choices_key(self, project):
        identity = str(getattr(project, "project_id", "") or self._project_path)
        return "glossary_proofread/conflict_choices/" + re.sub(r"[^0-9A-Za-z_-]", "_", identity)

    def _load_choices(self, project):
        from PySide6.QtCore import QSettings
        try:
            raw = json.loads(str(QSettings("2ByteASR", "2ByteASR").value(self._choices_key(project), "{}") or "{}"))
        except (TypeError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(key): (str(value[0]), str(value[1])) for key, value in raw.items()
                if isinstance(value, list) and len(value) == 2}

    def _save_choices(self):
        from PySide6.QtCore import QSettings
        live, _studio = self._live_project()
        QSettings("2ByteASR", "2ByteASR").setValue(
            self._choices_key(live), json.dumps({key: list(value) for key, value in self._conflict_choices.items()},
                                                ensure_ascii=False))

    def _conflict_chosen(self, key, value):
        if value is None:
            self._conflict_choices.pop(key, None)
        else:
            self._conflict_choices[key] = tuple(value)
        self._save_choices()
        self._refresh_library_summary()
        self._run(False)

    def _active_choices(self):
        rows = {row["key"]: row for row in self._conflict_rows}
        return {key: value for key, value in self._conflict_choices.items()
                if key in rows and any(value[1] == option["target"] and value[0] in option["library_ids"]
                                       for option in rows[key]["options"])}

    # libraries --------------------------------------------------------
    def _fill_libraries(self, project, keep=None, target=None):
        import subtitle_core as legacy
        chosen = set(keep if keep is not None else (getattr(project, "glossary_ids", ()) or ()))
        self.library_list.blockSignals(True)
        self.library_list.clear()
        catalog = sorted(legacy.glossary_catalog(), key=lambda row: (str(row["id"]) not in chosen, str(row["name"]).casefold()))
        self._catalog = {str(row["id"]): str(row["name"]) for row in catalog}
        for row in catalog:
            item = QListWidgetItem(str(row["name"]))
            item.setData(Qt.ItemDataRole.UserRole, str(row["id"]))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if str(row["id"]) in chosen else Qt.CheckState.Unchecked)
            self.library_list.addItem(item)
        self.library_list.blockSignals(False)
        missing = [identity for identity in chosen if identity not in self._catalog]
        self._missing_libraries = missing
        self._sync_target(prefer=target)
        self._read_snapshot()

    def _sync_target(self, prefer=None):
        """New terms go to the one chosen library; with several, ask which."""
        selected = self._selected_ids()
        previous = prefer or self._target_id()
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        pool = selected or tuple(self._catalog)
        for identity in pool:
            self.target_combo.addItem(self._catalog.get(identity, identity), identity)
        if previous and previous in pool:
            self.target_combo.setCurrentIndex(self.target_combo.findData(previous))
        elif len(selected) == 1:
            self.target_combo.setCurrentIndex(0)
        else:
            self.target_combo.setCurrentIndex(-1)
            self.target_combo.setEditText("")
        self.target_combo.blockSignals(False)
        self._target_changed()

    def _target_changed(self, *_args):
        selected = self._selected_ids()
        identity = self._target_id()
        if len(selected) > 1 and not identity:
            self.target_note.setText(tr("已勾选 {count} 个词库：请选择新词要加入哪一个", count=len(selected)))
        elif identity and selected and identity not in selected and identity in getattr(self, "_catalog", {}):
            self.target_note.setText(tr("注意：「{name}」不在当前使用的词库中", name=self._target_name()))
        elif identity and identity not in getattr(self, "_catalog", {}):
            self.target_note.setText(tr("将新建词库「{name}」", name=identity))
        else:
            self.target_note.setText(tr("新词会加入「{name}」", name=self._target_name()) if identity else "")
        self.add_button.setEnabled(bool(identity))
        self.list.remember_targets = {"name": self._target_name()}
        self.list.update()

    def _selected_ids(self):
        return tuple(str(self.library_list.item(i).data(Qt.ItemDataRole.UserRole))
                     for i in range(self.library_list.count())
                     if self.library_list.item(i).checkState() == Qt.CheckState.Checked)

    def _read_snapshot(self):
        import subtitle_core as legacy
        from .terminology import snapshot_glossaries
        try:
            legacy.load_learned_term_payload(strict=True)
            self._snapshot = snapshot_glossaries(legacy, self._selected_ids())
        except (OSError, ValueError) as exc:
            self._snapshot = None
            self._terms = self.list.terms = TermIndex()
            bind_text(self.library_summary, '词库读取失败：{reason}', reason=str(exc)[:160])
            self._fill_terms()
            return
        # Whole names (confirmed spellings and the libraries' skill, spirit,
        # character lists) keep one name together in the proposals.
        self._terms = self.list.terms = TermIndex.from_snapshot(self._snapshot, legacy)
        live, _studio = self._live_project()
        texts = [cue.text for cue in getattr(live, "cues", ())]
        self._conflict_rows = spelling_conflicts(self._snapshot, texts)
        self.conflicts.set_conflicts(self._conflict_rows, self._active_choices(), self._session_added)
        self._refresh_library_summary()
        self._fill_terms()

    def _refresh_library_summary(self):
        if self._snapshot is None:
            return
        summary = self._snapshot.summary()
        if not self._selected_ids():
            bind_text(self.library_summary, '未选择词库：字幕照常可读、可听、可改；勾选后才会匹配专有名词')
            return
        live, _studio = self._live_project()
        recorded = recorded_revisions(live) if live is not None else {}
        origin = ""
        if self._inherit_origin == "recognition" and set(self._selected_ids()) == set(recorded):
            changed = [library.name for library in self._snapshot.libraries
                       if recorded.get(library.id) and recorded[library.id] != library.revision]
            origin = (tr(" · 沿用本次识别的词库（识别后已更新：{names}）", names="、".join(changed)) if changed
                      else tr(" · 沿用本次识别的词库"))
        elif self._inherit_origin == "project":
            origin = tr(" · 沿用本工程的词库")
        unresolved = len(self._conflict_rows) - len(self._active_choices())
        missing = getattr(self, "_missing_libraries", ())
        bind_text(self.library_summary, '已选 {count} 个词库 · 有效 {terms} 个规范词{origin}{conflicts}{missing}',
                  count=len(self._selected_ids()), terms=summary["effective_terms"], origin=origin,
                  conflicts=tr(' · {count} 项词条冲突待处理（见右侧）', count=unresolved) if unresolved else '',
                  missing=tr(' · 找不到词库：{names}', names='、'.join(missing)) if missing else '')

    def _libraries_changed(self, *_args):
        self._sync_target()
        self._read_snapshot()
        self._run(False)

    # ---- first use: scope and next step (2026-10-13) -------------------------
    def _home_library_ids(self):
        import subtitle_core as legacy
        settings = getattr(legacy, "RUNTIME_SETTINGS", {}) or {}
        ids = [str(x) for x in ((settings.get("glossary") or {}).get("enabled_glossary_ids") or ()) if str(x)]
        return tuple(identity for identity in dict.fromkeys(ids) if identity in getattr(self, "_catalog", {}))

    def _show_scope_banner(self, inherited, origin):
        from PySide6.QtCore import QSettings
        seen = QSettings("2ByteASR", "2ByteASR").value("onboarding/proofread_scope_seen", False) in (True, "true")
        names = "、".join(self._catalog.get(identity, identity) for identity in inherited)
        home = self._home_library_ids() if not inherited else ()
        self.scope_use_home.setVisible(bool(home))
        if inherited:
            where = tr("本次识别") if origin == "recognition" else tr("本工程")
            text = tr("正在用{where}的词库检查：{names}", where=where, names=names)
            if not seen:
                text += "　·　" + tr("词库匹配免费；AI 校对可能收费，要你点才会运行")
        elif home:
            text = tr("这个工程没有词库。要用首页的词库（{names}）检查吗？免费",
                      names="、".join(self._catalog.get(identity, identity) for identity in home))
        else:
            text = tr("这个工程没有词库，可以直接阅读和修改；要检查写法，在左侧勾选词库")
        self.scope_text.setText(text)
        self.scope_banner.setVisible(True)

    def _use_home_libraries(self):
        home = self._home_library_ids()
        if not home:
            return
        live, _studio = self._live_project()
        self._inherit_origin = "home"
        self._fill_libraries(live, keep=home)
        self._libraries_changed()
        self.scope_use_home.hide()
        self.scope_text.setText(tr("正在用首页的词库检查：{names}",
                                   names="、".join(self._catalog.get(identity, identity) for identity in home)))

    def _dismiss_scope_banner(self):
        from PySide6.QtCore import QSettings
        QSettings("2ByteASR", "2ByteASR").setValue("onboarding/proofread_scope_seen", True)
        self.scope_banner.hide()

    def _fill_terms(self, *_args):
        self.term_list.clear()
        if self._snapshot is None:
            self.term_count.setText("")
            return
        needle = self.term_filter.text().strip().casefold()
        terms = {}
        for library in self._snapshot.libraries:
            for term in library.terms:
                if term.confirmed:
                    terms.setdefault(term.canonical, set()).update(term.aliases)
        for canonical in sorted(terms, key=str.casefold):
            aliases = sorted(alias for alias in terms[canonical] if alias and alias != canonical)
            if needle and needle not in canonical.casefold() and not any(needle in a.casefold() for a in aliases):
                continue
            fresh = canonical in self._session_added_labels
            item = QListWidgetItem(canonical + (f"   ← {'、'.join(aliases[:4])}" if aliases else "")
                                   + ("   · " + tr("刚添加") if fresh else ""))
            item.setData(Qt.ItemDataRole.UserRole, canonical)
            item.setToolTip("、".join([canonical, *aliases]))
            if fresh:
                item.setForeground(QColor(_theme().accent_text))
                font = item.font(); font.setBold(True); item.setFont(font)
            self.term_list.addItem(item)
        bind_text(self.term_count, '{count} 个', count=len(terms))

    def _term_clicked(self, item):
        self.search.setText(str(item.data(Qt.ItemDataRole.UserRole) or ""))

    # adding terms -----------------------------------------------------
    def _parsed_terms(self):
        return parse_term_input(self.term_input.toPlainText(), self._term_overrides)

    def _preview_terms(self):
        """Show how each typed line will be stored before anything is written."""
        import html
        entries = self._parsed_terms()
        if not entries:
            self.term_preview.hide()
            return
        theme = _theme()
        warn = legible(theme.warning, theme.panel, theme)
        lines = []
        for number, entry in enumerate(entries):
            if number >= 8:
                lines.append(html.escape(tr("…另有 {count} 项", count=len(entries) - 8)))
                break
            source = html.escape(entry["source"])
            key = html.escape(entry["source"], quote=True)
            if entry.get("ambiguous"):
                first, last = entry["pair"]
                lines.append(
                    f'<span style="color:{warn}">⚠</span> {tr("「{text}」当作一个标准写法", text=source)} · '
                    f'<a href="pair:{key}">{html.escape(tr("改为「{old}」→「{new}」", old=first, new=last))}</a>')
            elif entry["alias"]:
                flip = (f' · <a href="name:{key}">{html.escape(tr("改回一个名称"))}</a>' if entry.get("flipped") else "")
                lines.append(f'{html.escape(entry["alias"])} <b>→</b> {html.escape(entry["canonical"])}{flip}')
            else:
                note = tr("标准写法")
                undo = (f' · <a href="pair:{key}">{html.escape(tr("改为左错右对"))}</a>'
                        if entry.get("confirmed") else "")
                lines.append(f'{html.escape(entry["canonical"])} <span style="color:{theme.text_muted}">（{note}）</span>{undo}')
        self.term_preview.setText("<br>".join(lines))
        self.term_preview.show()

    def _flip_term(self, link):
        mode, _sep, source = str(link).partition(":")
        if source:
            self._term_overrides[source] = mode
            self._preview_terms()

    def _add_terms(self):
        import subtitle_core as legacy
        entries = self._parsed_terms()
        if not entries:
            self._show_add_status(tr("请先输入专有名词，每行一个"))
            return
        unresolved = [entry for entry in entries if entry.get("ambiguous")]
        entries = [entry for entry in entries if not entry.get("ambiguous")]
        prepare = getattr(self._window, "_prepare_glossary_for_task", None)
        if callable(prepare) and not prepare():
            self._show_add_status(tr("术语库里有尚未提交的编辑，请先保存或放弃后再添加"))
            return
        identity = self._target_id()
        target = self._target_name() or identity
        if not identity:
            self._show_add_status(tr("请选择或输入要加入的词库"))
            return
        category = str(self.category_combo.currentData() or "其他")
        added, existing, errors = [], [], []
        for entry in entries:
            alias, canonical = entry["alias"], entry["canonical"]
            label = f"{alias} → {canonical}" if alias else canonical
            try:
                new = bool(legacy.add_learned_mapping(identity, canonical, canonical, category=category, origin="手动"))
                if alias:
                    new = bool(legacy.add_learned_mapping(identity, alias, canonical, category=category, origin="手动")) or new
                (added if new else existing).append(label)
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f"{label}：{exc}")
        if entries:
            self._notify_library_changed()
            chosen = set(self._selected_ids())
            catalog = {str(row["name"]): str(row["id"]) for row in legacy.glossary_catalog()}
            library_id = identity if identity in catalog.values() else catalog.get(target, identity)
            chosen.add(library_id)
            for entry in entries:
                self._session_added.add((library_id, entry["canonical"]))
            self._session_added_labels |= {entry["canonical"] for entry in entries}
            live, _studio = self._live_project()
            self._fill_libraries(live, keep=chosen, target=library_id)
        lines = []
        if added:
            lines.append(tr("已加入「{library}」{count} 项：{items}", library=target, count=len(added), items="、".join(added)))
        if existing:
            lines.append(tr("已在词库中，未重复添加：{items}", items="、".join(existing)))
        if errors:
            lines.append(tr("未加入：") + "；".join(errors[:3]))
        if unresolved:
            lines.append(tr("{count} 项需要先确认是一个名称还是“错→对”（见输入框下方），没有加入", count=len(unresolved)))
            self.term_input.setPlainText("\n".join(entry["source"] for entry in unresolved))
        elif not errors:
            self.term_input.clear()
            self._term_overrides = {}
        self._show_add_status("\n".join(lines) or tr("没有新的词条"))
        if entries:
            self._run(False)

    def _show_add_status(self, text):
        self.add_status.setText(str(text))
        self.add_status.setVisible(bool(text))

    def _notify_library_changed(self):
        # Refreshing the term library page and home choices is slow and they
        # are not visible here; do it once when leaving the page.
        self._library_dirty = True

    def _flush_library_changes(self):
        if not self._library_dirty:
            return
        self._library_dirty = False
        library = getattr(getattr(self._window, "term_library_page", None), "library", None)
        notify = getattr(library, "_notify_library_changed", None)
        if callable(notify):
            notify()
        else:
            refresh = getattr(self._window, "_refresh_content_choices", None)
            if callable(refresh):
                refresh()

    # review -----------------------------------------------------------
    def _cancel_worker(self):
        if self._worker is not None and self._worker.isRunning():
            self._generation += 1
            self._queued = None
            self._worker.token.cancel()

    def _cancel_run(self):
        if self._worker is not None and self._worker.isRunning():
            self._queued = None
            self._worker.token.cancel()
            self._set_status(tr("正在取消…已有的建议和你的修改都会保留"))

    def _queue(self, use_ai, cue_ids):
        if self._queued is None:
            self._queued = (bool(use_ai), None if cue_ids is None else set(cue_ids))
            return
        queued_ai, queued_ids = self._queued
        ids = None if queued_ids is None or cue_ids is None else queued_ids | set(cue_ids)
        self._queued = (queued_ai or bool(use_ai), ids)

    def _run(self, use_ai, cue_ids=None):
        """Match (or AI-review) all captions, or only ``cue_ids``."""
        if self._worker is not None and self._worker.isRunning():
            if self._worker_ai and not use_ai:
                # A running AI review keeps going; local rematch follows it.
                self._queue(False, cue_ids)
                return
            self._queue(use_ai, cue_ids if not self._worker_scope_all else None)
            self._generation += 1
            self._worker.token.cancel()
            return
        import subtitle_core as legacy
        prepare = getattr(self._window, "_prepare_glossary_for_task", None)
        if callable(prepare) and not prepare():
            self._set_status(tr("术语库里有尚未提交的编辑，请先保存或放弃后再生成建议"))
            return
        self._read_snapshot()
        live, _studio = self._live_project()
        if live is None:
            return
        if self._snapshot is None or not self._selected_ids():
            self._clear_term_issues()
            self._set_status(tr("未选择词库：字幕照常可读、可听、可改；勾选左侧词库后会匹配专有名词"))
            self._apply_filter()
            return
        if use_ai and not self._snapshot.canonical_terms:
            self._set_status(tr("所选词库还没有已确认的规范词"))
            return
        self._generation += 1
        generation = self._generation
        self._library_ids = self._selected_ids()
        self._snapshot_digest = self._snapshot.digest
        texts_at_run = {cue.id: cue.text for cue in live.cues}
        project_identity = (id(live), str(live.project_id))
        scope = None if cue_ids is None else {cue_id for cue_id in cue_ids if cue_id in texts_at_run}
        if scope is not None and not scope:
            return
        wanted = [cue.id for cue in live.cues if scope is None or cue.id in scope]
        settings = copy.deepcopy(getattr(legacy, "RUNTIME_SETTINGS", {}) or {})
        self._review_choices = self._active_choices()
        review_snapshot = prefer_spellings(self._snapshot, self._review_choices)
        worker = _ReviewThread(_review_copy(live), wanted, review_snapshot, settings, bool(use_ai), self,
                               stand_in=self.ai_stand_in if use_ai else None)
        self._worker, self._worker_ai, self._worker_scope_all = worker, bool(use_ai), scope is None
        self._set_busy(True)
        self._set_status(tr("正在请求 AI 校对…") if use_ai else tr("正在按词库匹配（本地）…"))

        def progress(done, total):
            if generation == self._generation and use_ai and total:
                self._set_status(tr("AI 校对中：第 {done}/{total} 批…（可取消；已有建议和修改会保留）",
                                    done=done, total=total))

        def ready(result):
            if generation != self._generation:
                return
            current, _studio_now = self._live_project()
            if current is None or (id(current), str(current.project_id)) != project_identity:
                self._set_status(tr("工程已切换，丢弃了旧的校对结果"))
                return
            self._show_result(result, current, use_ai, texts_at_run, scope)

        def failed(message):
            if generation != self._generation:
                return
            if message == "cancelled":
                self._set_status(tr("已取消 {what}；已有建议和你的修改都保留", what=tr("AI 校对") if use_ai else tr("匹配")))
            else:
                self._set_status(tr("没有生成建议：{reason}", reason=str(message)[:200]))

        def finished():
            self._worker = None
            self._worker_ai = False
            responsive_background(False)
            self._set_busy(False)
            worker.deleteLater()
            if self._queued is not None:
                (queued_ai, queued_ids), self._queued = self._queued, None
                self._run(queued_ai, queued_ids)

        worker.progress.connect(progress)
        worker.ready.connect(ready)
        worker.failed.connect(failed)
        worker.finished.connect(finished)
        responsive_background(True)
        worker.start()

    def _set_busy(self, busy):
        for button in (self.local_button, self.ai_button):
            button.setEnabled(not busy)
        self.cancel_button.setVisible(busy)

    def _clear_term_issues(self):
        for row in self._rows:
            row["issues"] = [issue for issue in row["issues"] if issue["kind"] in LOCAL_KINDS or issue["checked"]]

    def _show_result(self, result, project, use_ai, texts_at_run, scope=None):
        """Merge term/AI proposals; keep answers, written proposals and local rows.

        Late results never touch a caption that changed after the run began
        (a direct edit, Ctrl+H or Studio): its proposals are dropped.
        ``scope``: the captions this run looked at (None = all)."""
        from .stutter_cleanup import plausible_name_span
        self._receipt = result.receipt
        receipt = result.receipt or {}
        decisions = self._decisions()
        current = {cue.id: cue.text for cue in project.cues}
        fresh = {}
        dropped = 0

        def still_valid(cue_id):
            return current.get(cue_id) is not None and current.get(cue_id) == texts_at_run.get(cue_id)

        kinds = {"local_confirmed": "term", "local_review": "near", "ai_accepted": "ai", "ai_review": "ai_review"}
        for hit in result.hits:
            if not still_valid(hit.cue_id) or self._by_id.get(hit.cue_id) is None:
                dropped += 1
                continue
            kind = kinds.get(hit.source, "near")
            reason = hit.reason or ""
            issue = _issue(kind, hit.span, hit.original, hit.replacement, checked=False, reason=reason, hit=hit,
                           evidence=hit.missing_evidence or hit.evidence)
            issue["default"] = bool(hit.default_selected)
            fresh.setdefault(hit.cue_id, []).append(issue)
        from .studio_text_tools import TextOccurrence
        for pending in receipt.get("pending_rows", ()):
            if pending.get("state") != "missing_alias_or_candidate":
                continue
            cue_id = pending.get("cue_id")
            if not still_valid(cue_id) or self._by_id.get(cue_id) is None:
                continue
            start, end = (pending.get("span") or [0, 0])[:2]
            text = current[cue_id]
            surface = text[int(start):int(end)]
            if not surface or not plausible_name_span(text, int(start), int(end)):
                continue  # 刚刚 / 哦 又是 / spans cutting through 话题 are not names
            options = [option for option in pending.get("canonical_options") or [] if option and option != surface]
            if options:
                # 2026-10-10 (user): the candidate is recommended; one click adopts it.
                for number, option in enumerate(options[:3]):
                    hit = TextOccurrence(cue_id, project_cue_start(project, cue_id), surface, option,
                                         (int(start), int(end)), reason="疑似专有名词的词库候选",
                                         confidence=.6, default_selected=len(options) == 1,
                                         source="association", evidence=str(pending.get("reason") or ""))
                    issue = _issue("association", hit.span, surface, option, checked=False,
                                   reason=tr("词库候选") + (tr("（另有 {count} 个候选）", count=len(options) - 1) if len(options) > 1 else ""),
                                   hit=hit, options=options)
                    issue["default"] = len(options) == 1 and number == 0
                    fresh.setdefault(cue_id, []).append(issue)
            else:
                row = self._by_id[cue_id]
                if any(issue["kind"] in {"stutter", "merge"} and issue["span"][0] < int(end)
                       and int(start) < issue["span"][1] + len(issue["original"]) for issue in row["issues"]):
                    continue  # already explained as a repeat, not a name
                if any(a <= int(start) and int(end) <= b for a, b, _name in self._terms.occurrences(text)):
                    # 布克 in 布克棱岩: the libraries list the whole name (2026-10-10).
                    continue
                fresh.setdefault(cue_id, []).append(_issue("suspect", (int(start), int(end)), surface, "",
                                                           checked=False, reason=""))
        for row in self._rows:
            if scope is not None and row["cue_id"] not in scope:
                continue
            keep = [issue for issue in row["issues"] if issue["kind"] in LOCAL_KINDS or issue["checked"]]
            if not still_valid(row["cue_id"]):
                # Changed after the run started: keep what still anchors, add nothing.
                row["issues"] = keep + [issue for issue in row["issues"] if issue not in keep]
                continue
            new, seen = [], {issue_key(row["cue_id"], issue) for issue in keep}
            # A near hit that writes the same sentence as a confirmed one
            # (古龙 → 骨龙 next to 古 → 骨) is the same proposal twice.
            results = {adopt_text(row["base"], [issue]) for issue in keep
                       if not issue["checked"] and issue["replacement"]}
            for issue in sorted(fresh.get(row["cue_id"], ()), key=lambda item: PRIORITY.get(item["kind"], 8)):
                key = issue_key(row["cue_id"], issue)
                if key in seen:
                    continue
                seen.add(key)
                if issue["kind"] != "suspect":
                    result = adopt_text(row["base"], [issue])
                    if result != row["base"] and result in results:
                        continue
                    results.add(result)
                issue["context"] = _context(row["base"], *issue["span"])
                new.append(issue)
            new.sort(key=lambda item: (item["span"][0], PRIORITY.get(item["kind"], 8)))
            row["issues"] = new + keep
            self._apply_decisions(row, decisions)
        if use_ai:
            errors = receipt.get("request_errors") or ()
            ok, fallback = receipt.get("successful_cues", 0), receipt.get("fallback_cues", 0)
            if errors and not ok:
                status = tr("AI 校对没有成功（{reason}）；下面只有本地匹配和口吃整理的结果",
                            reason="；".join(errors)[:160])
            else:
                status = tr("AI 校对完成：{ok} 条已核对 · {fallback} 条未完成（保留原文）", ok=ok, fallback=fallback)
            self._ai_status = status
        elif scope is not None:
            status = tr("已重新匹配改过的 {checked} 条字幕（本地，未使用 AI）", checked=receipt.get("checked_cues", 0))
            if self._ai_status:
                status += "\n" + self._ai_status
        else:
            status = tr("已按词库匹配 {checked} 条字幕（本地，未使用 AI）", checked=receipt.get("checked_cues", 0))
            if self._ai_status:
                status += "\n" + self._ai_status
        if dropped:
            status += tr(" · {count} 条结果因字幕已改动而丢弃", count=dropped)
        flash, self._flash = self._flash, ""
        self._set_status(f"{flash}\n{status}" if flash else status)
        self._apply_filter()

    # audio ------------------------------------------------------------
    def _play(self, cue_id):
        if self._player.cue_id == cue_id:
            self._player.stop()
            return
        live, _studio = self._live_project()
        if live is None:
            self._set_status(tr("工程已关闭或被替换，无法试听"))
            return
        self._player.play(live, cue_id)

    def _playing_changed(self, cue_id, state):
        self.list.playing = (cue_id, state) if state else ("", "")
        self.list.update()

    # misc -------------------------------------------------------------
    def _set_status(self, text):
        self.status_label.setText(str(text or ""))

    def _back(self):
        self._player.stop()
        if not self.settle_writes():
            return
        self._flush_library_changes()
        self.back_requested.emit()

    def hideEvent(self, event):
        self._player.stop()
        self.list.commit_pending_edit()
        # Leaving through the header (字幕工作台, 设置…) instead of 返回: the
        # file must be written before the next page reads it, or Studio could
        # load the old text and later save over these edits (2026-10-10).
        if not event.spontaneous():
            self._flush_save()
        self._flush_library_changes()
        super().hideEvent(event)

    def shutdown(self):
        self._player.shutdown()
        for thread in list(getattr(self, "_stutter_threads", ())):
            try:
                thread.wait(5000)
            except RuntimeError:
                pass
        self._flush_save()
        if self._worker is not None and self._worker.isRunning():
            self._worker.token.cancel()
            self._worker.wait(3000)


def project_cue_start(project, cue_id):
    return next((cue.start_ms for cue in project.cues if cue.id == cue_id), 0)
