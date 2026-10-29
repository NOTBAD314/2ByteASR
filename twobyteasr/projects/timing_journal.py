"""Manual caption timing edits in Studio, appended to a journal (2026-10-22, MFA plan step 5).

The user asked to keep the time every step produced. Recognition writes its
own ledger (``recognition.timing_ledger``); after that, the steps are the
user's edits. This journal subscribes to the project's state deltas and
appends one line per caption whose display time changed: when, which edit
(the action id), before and after. Undo and redo are edits too and are
appended, never removed. The journal lives in the app's data folder (one file
per project path), not in the project, so undo still returns the project
exactly and nothing is written beside the user's files.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

FOLDER = "timing-journal"


def journal_path(project_path) -> Path:
    from ..runtime_paths import user_data_root
    source = str(Path(project_path).resolve()) if project_path else "unsaved"
    stem = Path(project_path).stem if project_path else "unsaved"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:40] or "project"
    return user_data_root() / FOLDER / f"{safe}-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:10]}.jsonl"


class TimingJournal:
    def __init__(self, project, project_path=None):
        """``project_path``: the project file, or a callable returning it (None while unsaved)."""
        self.project = project
        self._path = project_path if callable(project_path) else (lambda: project_path)
        self._times = {cue.id: (int(cue.start_ms), int(cue.end_ms)) for cue in project.cues}
        self._pending: list[dict] = []

    def consume(self, delta) -> None:
        """A runtime-state subscriber: diff the affected captions' times, append what moved."""
        if not delta.affected_cue_ids:
            return
        wanted = set(delta.affected_cue_ids)
        present = {cue.id for cue in self.project.cues}
        # An undone split names only the restored caption; the removed half is found here.
        wanted |= set(self._times) - present
        current = {cue.id: cue for cue in self.project.cues if cue.id in wanted}
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        for cue_id in sorted(wanted):
            cue = current.get(cue_id)
            after = (int(cue.start_ms), int(cue.end_ms)) if cue is not None else None
            before = self._times.get(cue_id)
            if before == after:
                continue
            self._pending.append({"t": stamp, "revision": int(delta.revision), "action": str(delta.action_id),
                                  "cue": cue_id, "before": list(before) if before else None,
                                  "after": list(after) if after else None,
                                  "text": str(cue.text)[:24] if cue is not None else ""})
            if after is None:
                self._times.pop(cue_id, None)
            else:
                self._times[cue_id] = after
        self.flush()

    def flush(self) -> str | None:
        """Append pending lines once the project has a path (kept in memory until then)."""
        path = self._path()
        if not self._pending or not path:
            return None
        target = journal_path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as stream:
                for row in self._pending:
                    stream.write(json.dumps(dict(row, project=str(path)), ensure_ascii=False) + "\n")
        except OSError:
            return None
        self._pending.clear()
        return str(target)
