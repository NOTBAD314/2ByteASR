"""Every step that moves caption times, recorded in order (2026-10-22, MFA plan step 5).

The user asked to keep the time each step produced, with acoustic time kept
apart from display time. After the captions are formed, a recognition task
moves their times in a few named steps (display tails, pause snapping of
unmeasured cuts, Japanese CTC line starts, the display rules that put the
result back on the frame grid). Each checkpoint stores which captions moved,
from where to where and why (the step's own receipts, never truncated), and
the last one adds every caption's measured acoustic span next to its display
time. Saved beside the aligner receipts in ``timing-evidence/`` (one file per
task, never overwritten by a later task). Recognition never reads it back.
"""
from __future__ import annotations

import gzip
import json
import os
import time
import uuid
from pathlib import Path

FORMAT = "2byteasr-timing-ledger-v1"


def _ms(value) -> int:
    return int(round(float(value) * 1000))


class TimingLedger:
    def __init__(self):
        self.stages: list[dict] = []
        self._last: list[tuple[int, int]] | None = None

    def checkpoint(self, stage: str, cues, *, reason: str = "", receipts=None) -> dict:
        """Record the captions' display times after ``stage`` (changes against the previous checkpoint)."""
        times = [(_ms(cue.start), _ms(cue.end)) for cue in cues]
        row = {"stage": stage, "reason": reason, "cues": len(times)}
        if self._last is None or len(self._last) != len(times):
            row["snapshot"] = [[index + 1, a, b, str(getattr(cue, "text", ""))[:24]]
                               for index, ((a, b), cue) in enumerate(zip(times, cues))]
        else:
            row["changes"] = [{"cue": index + 1, "text": str(getattr(cue, "text", ""))[:24],
                               "before": list(old), "after": list(new)}
                              for index, (old, new, cue) in enumerate(zip(self._last, times, cues)) if old != new]
            row["changed"] = len(row["changes"])
        if receipts:
            row["receipts"] = list(receipts)
        self.stages.append(row)
        self._last = times
        return row

    def acoustic(self, cues) -> list[dict]:
        """Display time next to the measured span and edge grades of every aligned caption."""
        rows = []
        for index, cue in enumerate(cues, 1):
            alignment = getattr(cue, "forced_alignment", None) or {}
            pieces = alignment.get("segments") or ()
            if not pieces:
                continue
            grades = {int(row["pos"]): row for row in alignment.get("boundaries") or ()}
            text = str(alignment.get("text") or "")
            first, last = pieces[0], pieces[-1]
            rows.append({"cue": index, "display": [_ms(cue.start), _ms(cue.end)],
                         "acoustic": [int(first["start_ms"]), int(last["end_ms"])],
                         "basis": [first.get("start_basis"), last.get("end_basis")],
                         "grades": [(grades.get(0) or {}).get("grade"), (grades.get(len(text)) or {}).get("grade")]})
        self.stages.append({"stage": "acoustic_spans", "reason": "measured words beside display time", "rows": rows})
        return rows

    def save(self, folder, *, job_id: str = "", **meta) -> str | None:
        if not folder or not self.stages:
            return None
        record = {"format": FORMAT, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "job_id": job_id, **meta,
                  "stages": self.stages}
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = Path(folder) / f"timing-ledger-{stamp}-{(job_id or uuid.uuid4().hex)[:8]}.json.gz"
        temporary = path.with_name(path.name + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(gzip.compress(json.dumps(record, ensure_ascii=False).encode("utf-8")))
            os.replace(temporary, path)
        except OSError:
            temporary.unlink(missing_ok=True)
            return None
        return str(path)
