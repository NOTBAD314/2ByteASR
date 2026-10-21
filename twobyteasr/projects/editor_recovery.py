"""Private editor drafts, separate from committed project/undo state.

Five-second maximum scheduling interval, plus snapshot/write time. Drafts are
offered explicitly after reopening, never replayed as model edits.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import threading
import time
import uuid
from PySide6.QtCore import QObject, QTimer

INTERVAL_MS = 5000

def draft_root():
    from .studio_project import studio_data_root
    return studio_data_root()/"editor-drafts"

def candidates(project_id=None):
    result=[]
    for path in draft_root().glob("*.json"):
        try:
            if path.stat().st_size > 1024*1024: continue
            row=json.loads(path.read_text("utf8"))
            if row.get("version") != 1 or (project_id and row.get("project_id") != project_id):
                continue
            row["_file"]=str(path)
            result.append(row)
        except (OSError, ValueError, TypeError):
            pass
    return sorted(result,key=lambda r:r.get("saved_at",0),reverse=True)[:64]

def write_draft(path, payload):
    from .studio_project import _atomic_json_write
    path.parent.mkdir(parents=True,exist_ok=True)
    _atomic_json_write(path,payload)
    # Private recovery store, independent of the user's official project.
    # Keep the most recent 64 journals (typically one per open editor).
    journals=sorted(path.parent.glob("*.json"),key=lambda p:p.stat().st_mtime,reverse=True)
    for old in journals[64:]:
        try:old.unlink()
        except OSError:pass

class DraftRecovery(QObject):
    def __init__(self,page):
        super().__init__(page)
        self.page=page
        self.lease=None
        self.revision=0
        self.saved_revision=-1
        self.offered=set()
        self.timer=QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(INTERVAL_MS)
        self.timer.timeout.connect(self._tick)
        self.offer_timer=QTimer(self);self.offer_timer.setSingleShot(True)
        self.offer_timer.timeout.connect(self.offer)

    def changed(self):
        page=self.page
        if page.project is None or getattr(page,"_canvas_editor",None) is not page.subtitle_edit_input:
            return
        cue_id=(getattr(page,"_review_edit_lock",None) or {}).get("cue_id") or page.selected_cue_id
        cue=page._cue_lookup.get(cue_id)
        if cue is None:return
        if self.lease is None:
            valid=threading.Event();valid.set()
            self.lease=dict(valid=valid,path=draft_root()/(uuid.uuid4().hex+".json"),
                project_id=page.project.project_id,project_path=str(page.project_path or ""),
                cue_id=cue_id,base_text=cue.text)
        self.revision+=1
        if not self.timer.isActive():self.timer.start()

    def snapshot(self):
        lease=self.lease;page=self.page
        if (lease is None or not lease["valid"].is_set() or page.project is None
            or page.project.project_id != lease["project_id"]
            or getattr(page,"_canvas_editor",None) is not page.subtitle_edit_input):
            return None
        text=page.subtitle_edit_input.toPlainText()
        if text==lease["base_text"]:return None
        cursor=page.subtitle_edit_input.textCursor()
        return dict(lease=lease,revision=self.revision,payload=dict(version=1,
            project_id=lease["project_id"],project_path=lease["project_path"],cue_id=lease["cue_id"],
            base_text=lease["base_text"],text=text,position=cursor.position(),anchor=cursor.anchor(),
            saved_at=time.time()))

    def _tick(self):
        if getattr(self.page,"_close_requested",False):return
        snapshot=self.snapshot()
        if snapshot is None:return
        if self.page._autosave_worker_running:
            self.timer.start(250);return
        if self.saved_revision!=self.revision:
            self.page._autosave_generation+=1
            self.page._start_autosave_worker(self.page._autosave_generation, draft_only=True)
        if self.lease is not None:self.timer.start()

    def persist(self,snapshot,autosave):
        # Called under the existing page save lock, from its save worker.
        if snapshot is None:return
        lease=snapshot["lease"]
        if not lease["valid"].is_set():return
        payload=dict(snapshot["payload"],autosave=str(autosave))
        write_draft(lease["path"],payload)
        if not lease["valid"].is_set():
            lease["path"].unlink(missing_ok=True)
        elif lease is self.lease:
            self.saved_revision=snapshot["revision"]
            previous=lease.pop("previous_file",None)
            if previous:
                try:Path(previous).unlink(missing_ok=True)
                except OSError:pass

    def discard(self):
        self.timer.stop()
        lease,self.lease=self.lease,None
        self.revision=0;self.saved_revision=-1
        if lease is None:return
        lease["valid"].clear()
        lock=self.page._autosave_write_lock
        def remove():
            # If a captured writer was already running, its publish finishes
            # before this tombstone. It can never recreate the canceled draft.
            with lock:
                try:
                    lease["path"].unlink(missing_ok=True)
                    previous=lease.get("previous_file")
                    if previous:Path(previous).unlink(missing_ok=True)
                except OSError:pass
        threading.Thread(target=remove,name="draft-discard",daemon=True).start()

    def project_changed(self):
        self.offer_timer.start(1000)

    def offer(self):
        page=self.page
        if page.project is None or getattr(page,"_close_requested",False):return
        if getattr(page,"_project_view_state","") != "open":return
        if getattr(page,"_readiness",None) is not None and not page._readiness.ready:
            self.offer_timer.start(500);return
        rows=[r for r in candidates(page.project.project_id)
              if r["_file"] not in self.offered and
              (not r.get("project_path") or r["project_path"]==str(page.project_path or ""))]
        if not rows:return
        row=rows[0];self.offered.add(row["_file"])
        show_draft(page,row)

def restore_into_editor(page,row):
    if page.project is None or page.project.project_id!=row["project_id"]:
        return False
    cue=page._cue_lookup.get(row["cue_id"])
    if cue is None or cue.text!=row["base_text"]:
        return False
    page.select_cue(cue.id)
    page._begin_canvas_inline_edit()
    if getattr(page,"_canvas_editor",None) is None:return False
    editor=page.subtitle_edit_input
    editor.setPlainText(row["text"])
    from PySide6.QtGui import QTextCursor
    cursor=editor.textCursor()
    maximum=editor.document().characterCount()-1
    cursor.setPosition(min(maximum,max(0,int(row.get("anchor",0)))))
    cursor.setPosition(min(maximum,max(0,int(row.get("position",0)))),QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    # Retain the recovered disk copy until the replacement journal publishes,
    # or the user explicitly confirms/cancels this editor.
    recovery=getattr(page,"_draft_recovery",None)
    if recovery is not None and recovery.lease is not None:
        recovery.lease["previous_file"]=row.get("_file")
    return True

def show_draft(page,row):
    from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPlainTextEdit,QDialogButtonBox
    dialog=QDialog(page);dialog.setWindowTitle("发现未确认的编辑草稿");dialog.resize(560,320)
    layout=QVBoxLayout(dialog)
    layout.addWidget(QLabel("草稿独立于工程。恢复后仍需确认；当前原句变化时请手动复制。"))
    view=QPlainTextEdit(row.get("text",""));view.setReadOnly(True);layout.addWidget(view)
    buttons=QDialogButtonBox(QDialogButtonBox.Close)
    restore=buttons.addButton("恢复到编辑框",QDialogButtonBox.AcceptRole)
    discard=buttons.addButton("删除这份草稿",QDialogButtonBox.DestructiveRole)
    def apply():
        if restore_into_editor(page,row):
            # Replacement journal takes over; never insert the draft into the
            # canonical model until the user confirms the editor.
            dialog.accept()
        else:
            restore.setEnabled(False)
    restore.clicked.connect(apply)
    discard.clicked.connect(lambda:(Path(row["_file"]).unlink(missing_ok=True),dialog.reject()))
    buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()

