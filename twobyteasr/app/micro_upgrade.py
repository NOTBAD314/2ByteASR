"""Action-First Micro-Upgrade detector (2026-11-25).

Instead of interrupting idle users with random tips, observes concrete
repetitive manual editing friction locally (zero LLM calls) and emits at most
one compact, immediately actionable upgrade pill right when the pain happens:

  1. ``repeated_typo``  - User manually replaced the same word >= 2 times and
                          occurrences remain in the project (feeds directly
                          from ``learned_pairs``) -> 1-click replace-all +
                          add to glossary/series, then 1-line Ctrl+H insight.
  2. ``manual_review``  - User opened/edited >= 5 flagged cues without using
                          ``R`` review mode -> 1-click open R review mode.
  3. ``manual_pronoun`` - User manually edited 他/她/它 >= 3 times -> 1-line
                          action hint for Shift+F quick cycle.
  4. ``manual_shift``   - User dragged >= 4 consecutive cue timings in the same
                          direction with similar delta -> 1-click offer to
                          batch shift following cues (Alt+Left/Right insight).

Anti-Clippy guardrails (mirrors ``bunny_events.py``):
  - Never uses modal dialogs.
  - Per-session cap and cooldown between pills.
  - Dismissing the same kind twice silences that kind for 7 days.
  - Global opt-out switch respected immediately.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

SCHEMA_VERSION = 1
MIN_GAP_S = 35.0
SESSION_CAP = 5
DISMISSES_BEFORE_QUIET = 2
QUIET_DURATION_S = 7 * 24 * 3600.0
PRONOUNS = frozenset(("他", "她", "它"))


@dataclass(frozen=True)
class MicroUpgradeOffer:
    kind: str                   # repeated_typo | manual_review | manual_pronoun | manual_shift
    message: str                # short plain line describing the detected pain
    action_label: str           # concrete 1-click action label
    insight_after: str          # 1-sentence mental-model / shortcut takeaway shown AFTER clicking
    task_key: str = ""          # optional newbie_tasks key to tick on real execution
    payload: dict[str, Any] = field(default_factory=dict)


def _store_path(base: str | os.PathLike[str] | None = None) -> Path:
    if base is not None:
        return Path(base) / "micro-upgrades.json"
    from ..runtime_paths import user_data_root
    return Path(user_data_root()) / "SubtitleStudioPreview" / "micro-upgrades.json"


def _load_prefs(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": bool(raw.get("enabled", True)),
        "dismissed": dict(raw.get("dismissed") or {}),
        "completed": list(raw.get("completed") or ()),
    }


def _save_prefs(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


class MicroUpgradeTracker:
    """Per-Studio-session local friction detector with persistent quiet rules."""

    def __init__(self, *, prefs_path: str | os.PathLike[str] | None = None):
        self.path = Path(prefs_path) if prefs_path is not None else _store_path()
        self._prefs = _load_prefs(self.path)
        self._shown_this_session = 0
        self._last_shown_at = -1e9
        self._shown_keys: set[str] = set()
        # Rolling per-session friction counters
        self._flagged_manual_edits = 0
        self._used_review_mode = False
        self._pronoun_manual_edits = 0
        self._used_shift_f = False
        self._timing_deltas_ms: list[int] = []

    @property
    def enabled(self) -> bool:
        return bool(self._prefs.get("enabled", True))

    def set_enabled(self, on: bool) -> None:
        self._prefs["enabled"] = bool(on)
        _save_prefs(self.path, self._prefs)

    def _allowed(self, kind: str, dedupe_key: str, now: float) -> bool:
        if not self.enabled:
            return False
        if dedupe_key in self._shown_keys:
            return False
        if self._shown_this_session >= SESSION_CAP:
            return False
        if now - self._last_shown_at < MIN_GAP_S:
            return False
        entry = self._prefs["dismissed"].get(kind)
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            count, until = int(entry[0]), float(entry[1])
            if count >= DISMISSES_BEFORE_QUIET and now < until:
                return False
        return True

    def _emit(self, offer: MicroUpgradeOffer, dedupe_key: str, now: float) -> MicroUpgradeOffer:
        self._shown_this_session += 1
        self._last_shown_at = now
        self._shown_keys.add(dedupe_key)
        return offer

    def record_dismissed(self, kind: str, *, now: float | None = None) -> None:
        ts = time.time() if now is None else float(now)
        prev = self._prefs["dismissed"].get(kind)
        count = 0
        if isinstance(prev, (list, tuple)) and len(prev) == 2:
            prev_count, prev_until = int(prev[0]), float(prev[1])
            count = 0 if (prev_count >= DISMISSES_BEFORE_QUIET and ts >= prev_until) else prev_count
        count += 1
        until = ts + QUIET_DURATION_S if count >= DISMISSES_BEFORE_QUIET else 0.0
        self._prefs["dismissed"][kind] = [count, until]
        _save_prefs(self.path, self._prefs)

    def record_accepted(self, kind: str) -> None:
        self._prefs["dismissed"].pop(kind, None)
        if kind not in self._prefs["completed"]:
            self._prefs["completed"].append(kind)
        _save_prefs(self.path, self._prefs)

    # ------------------------------------------------------------------ friction detectors
    def check_repeated_typo(
        self,
        learned_pairs: Sequence[dict[str, Any]],
        *,
        now: float | None = None,
    ) -> MicroUpgradeOffer | None:
        """Surface 1-click batch replace + glossary add when a manual typo fix repeats >= 2x."""
        ts = time.time() if now is None else float(now)
        for row in learned_pairs:
            src = str(row.get("source") or "").strip()
            dst = str(row.get("target") or "").strip()
            count = int(row.get("count") or 0)
            left = int(row.get("left") or 0)
            if not src or not dst or src == dst or count < 2 or left <= 0:
                continue
            dedupe = f"repeated_typo:{src.casefold()}->{dst.casefold()}"
            if not self._allowed("repeated_typo", dedupe, ts):
                continue
            return self._emit(
                MicroUpgradeOffer(
                    kind="repeated_typo",
                    message=f"刚连改 {count} 次「{src} → {dst}」，工程里还有 {left} 处",
                    action_label=f"一键全片替换（{left} 处）并入词库",
                    insight_after=f"已一次修完 {left} 处并记入词库（可 Ctrl+Z 撤回）；以后遇到批量错字也可以直接按 Ctrl+H。",
                    task_key="add_term",
                    payload={"source": src, "target": dst, "left": left, "count": count},
                ),
                dedupe,
                ts,
            )
        return None

    def note_review_mode_used(self) -> None:
        self._used_review_mode = True

    def note_manual_flagged_edit(self, *, remaining_flagged: int, now: float | None = None) -> MicroUpgradeOffer | None:
        if self._used_review_mode:
            return None
        self._flagged_manual_edits += 1
        if self._flagged_manual_edits < 5 or remaining_flagged < 3:
            return None
        ts = time.time() if now is None else float(now)
        if not self._allowed("manual_review", "manual_review", ts):
            return None
        return self._emit(
            MicroUpgradeOffer(
                kind="manual_review",
                message=f"这批还有 {remaining_flagged} 处待确认字幕",
                action_label="按 R 开启原声逐条秒审",
                insight_after="审核模式会自动播放当前句原声并列出多模型候选，不用反复手动拖播放头。",
                task_key="review",
                payload={"remaining": remaining_flagged},
            ),
            "manual_review",
            ts,
        )

    def note_shift_f_used(self) -> None:
        self._used_shift_f = True

    def note_text_diff(self, old_text: str, new_text: str, *, now: float | None = None) -> MicroUpgradeOffer | None:
        """Detect repeated single-character 他/她/它 manual edits."""
        if self._used_shift_f or len(old_text) != len(new_text) or old_text == new_text:
            return None
        diffs = [(a, b) for a, b in zip(old_text, new_text) if a != b]
        if len(diffs) == 1 and diffs[0][0] in PRONOUNS and diffs[0][1] in PRONOUNS:
            self._pronoun_manual_edits += 1
            if self._pronoun_manual_edits >= 3:
                ts = time.time() if now is None else float(now)
                if self._allowed("manual_pronoun", "manual_pronoun", ts):
                    return self._emit(
                        MicroUpgradeOffer(
                            kind="manual_pronoun",
                            message="刚手动改了 3 次人称代词（他/她/它）",
                            action_label="记住快捷改法：Shift+F",
                            insight_after="编辑字幕时把光标放在「他/她/它」旁直接按 Shift+F，无需选字即可按 他→她→它 循环替换。",
                        ),
                        "manual_pronoun",
                        ts,
                    )
        return None

    def note_manual_timing_shift(self, delta_ms: int, *, remaining_after: int = 0, now: float | None = None) -> MicroUpgradeOffer | None:
        """Detect >= 4 consecutive single-cue timing shifts in the same direction."""
        if abs(delta_ms) < 60 or abs(delta_ms) > 5000:
            return None
        if self._timing_deltas_ms and (self._timing_deltas_ms[-1] > 0) != (delta_ms > 0):
            self._timing_deltas_ms.clear()
        self._timing_deltas_ms.append(int(delta_ms))
        if len(self._timing_deltas_ms) < 4:
            return None
        avg = int(round(sum(self._timing_deltas_ms[-4:]) / 4))
        ts = time.time() if now is None else float(now)
        if not self._allowed("manual_shift", "manual_shift", ts):
            return None
        direction = "推后" if avg > 0 else "提前"
        return self._emit(
            MicroUpgradeOffer(
                kind="manual_shift",
                message=f"连续 4 条字幕都在往同一方向{direction}约 {abs(avg)}ms",
                action_label="全选后用 Alt+← / → 一起对齐",
                insight_after="整片或整段字幕一起偏移时，按 Ctrl+A（或框选多条）再用 Alt+← / → 就能一步整体微调。",
                task_key="shift_all",
                payload={"avg_delta_ms": avg, "remaining_after": remaining_after},
            ),
            "manual_shift",
            ts,
        )


__all__ = [
    "DISMISSES_BEFORE_QUIET",
    "MIN_GAP_S",
    "MicroUpgradeOffer",
    "MicroUpgradeTracker",
    "QUIET_DURATION_S",
    "SESSION_CAP",
]
