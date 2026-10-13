"""GUI side of local MCP access: the only writer (2026-10-12).

The stdio MCP server (``mcp_stdio``) is a thin translator. Every request
reaches this bridge over a per-user named pipe (QLocalServer, current-user
access only, plus a random key) and runs on the GUI thread against the
project open in Studio:

* read tools answer from the open project (paged, searchable);
* edits are two steps: ``preview_*`` builds a plan bound to the project id,
  its edit revision, the scope and a summary; ``apply_plan`` shows the plan in
  an in-product dialog and only the user's click applies it, through the
  existing undoable commands as one undo step. Nothing a client sends
  ("confirmed": true or otherwise) can skip the dialog. A plan is single-use
  and becomes stale as soon as the project changes;
* exports go to "<project folder>/MCP 导出" through the normal exporter,
  which never replaces an existing file.

Subtitle text, glossary words and file names are data. They are shown and
returned as plain text and never interpreted as instructions or markup.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer

from . import mcp_common as common
from .i18n import tr

PLAN_TTL_S = 600
MAX_PAGE = 500
MAX_EDITS = 200
MAX_TEXT = 500
WAIT_MAX_S = 120
ROLE_CHOICES = ("main", "secondary", "own", "auto")


class BridgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Plan:
    id: str
    kind: str
    project_id: str
    revision: int
    scope: dict
    summary: str
    changes: list
    created: float = field(default_factory=time.monotonic)
    status: str = "previewed"
    undo_index: int | None = None
    label: str = ""
    message: str = ""

    def digest(self) -> str:
        body = json.dumps([self.kind, self.project_id, self.revision, self.scope, self.changes],
                          ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]

    def public(self) -> dict:
        return dict(plan_id=self.id, kind=self.kind, status=self.status, project_id=self.project_id,
                    revision=self.revision, scope=self.scope, summary=self.summary, digest=self.digest(),
                    changes=self.changes[:50], change_count=len(self.changes),
                    expires_in_s=max(0, round(PLAN_TTL_S - (time.monotonic() - self.created))),
                    message=self.message)


class McpBridge(QObject):
    status_changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.server: QLocalServer | None = None
        self.settings = dict(common.DEFAULTS)
        self.plans: dict[str, Plan] = {}
        self.revision = 0
        self._stack = None
        self._dialogs: dict[str, object] = {}
        self._waiting: dict[str, list] = {}
        self.stats = dict(requests=0, refused=0, last_method="", last_at=0.0, connections=0)

    # ------------------------------------------------------------ lifecycle
    def apply_settings(self, settings: dict | None = None) -> None:
        self.settings = dict(settings or common.read_settings())
        if self.settings.get("enabled"):
            self.start()
        else:
            self.stop("disabled")

    def listening(self) -> bool:
        return self.server is not None and self.server.isListening()

    def start(self) -> None:
        if self.listening():
            return
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(common.pipe_name())
        if not server.listen(common.pipe_name()):
            self.stats["error"] = server.errorString()
            self.status_changed.emit()
            return
        server.newConnection.connect(self._accept)
        self.server = server
        self._key = common.create_key()   # compared in memory; the file only hands it to clients
        if not getattr(self, "_quit_hooked", False):
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.instance().aboutToQuit.connect(lambda: self.stop("quit"))
            self._quit_hooked = True
        self.status_changed.emit()

    def stop(self, reason: str = "") -> None:
        self._key = ""
        common.delete_key()
        for plan_id, dialog in list(self._dialogs.items()):
            plan = self.plans.get(plan_id)
            if plan is not None and plan.status == "awaiting_approval":
                plan.status, plan.message = "cancelled", tr("授权已关闭")
            dialog.close()
        self._dialogs.clear()
        for plan_id in list(self._waiting):
            self._answer_waiting(plan_id)
        if self.server is not None:
            self.server.close()
            self.server.deleteLater()
            self.server = None
        self.stats["stopped"] = reason
        self.status_changed.emit()

    def revoke(self) -> None:
        """撤销授权: off now (settings saved), key deleted, pending plans cancelled."""
        values = dict(self.settings, enabled=False)
        self.settings = common.save_settings(values)
        self.plans.clear()
        self.stop("revoked")

    # ------------------------------------------------------------ transport
    def _accept(self) -> None:
        while self.server is not None and self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.stats["connections"] += 1
            buffer = bytearray()

            def ready(socket=socket, buffer=buffer):
                buffer.extend(bytes(socket.readAll()))
                if len(buffer) > common.MAX_LINE_BYTES:
                    socket.abort()
                    return
                if b"\n" in buffer:
                    line = bytes(buffer).split(b"\n", 1)[0]
                    buffer.clear()
                    socket.readyRead.disconnect()
                    self._handle(socket, line)
            socket.readyRead.connect(ready)
            socket.disconnected.connect(socket.deleteLater)

    @staticmethod
    def _send(socket, payload: dict) -> None:
        try:
            if socket.state() == socket.LocalSocketState.ConnectedState:
                socket.write(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8") + b"\n")
                socket.flush()
                socket.disconnectFromServer()
        except RuntimeError:
            pass  # client went away; its plan stays queryable

    def _handle(self, socket, line: bytes) -> None:
        try:
            request = json.loads(line.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            self._send(socket, dict(ok=False, error=dict(code="bad_request", message="not a JSON object")))
            return
        key = getattr(self, "_key", "")
        supplied = str(request.get("key") or "")
        if not key or not self.listening() or not hmac.compare_digest(key, supplied):
            self.stats["refused"] += 1
            self._send(socket, dict(ok=False, error=dict(code="unauthorized",
                                                         message="MCP 访问未开启或已撤销")))
            return
        method = str(request.get("method") or "")
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        self.stats.update(requests=self.stats["requests"] + 1, last_method=method, last_at=time.time())
        self.status_changed.emit()
        handler = getattr(self, "op_" + method, None) if method.isidentifier() else None
        if handler is None:
            self._send(socket, dict(ok=False, error=dict(code="unknown_method", message=method)))
            return
        try:
            result = handler(socket=socket, **params)
        except TypeError as exc:
            self._send(socket, dict(ok=False, error=dict(code="bad_params", message=str(exc))))
            return
        except BridgeError as exc:
            self._send(socket, dict(ok=False, error=dict(code=exc.code, message=str(exc))))
            return
        except Exception as exc:  # noqa: BLE001 - reported to the client, GUI keeps running
            self._send(socket, dict(ok=False, error=dict(code="internal", message=f"{type(exc).__name__}: {exc}")))
            return
        if result is not None:   # None: answered later (approval)
            self._send(socket, dict(ok=True, result=result))

    # ------------------------------------------------------------ project access
    def _page(self):
        built = getattr(self.window, "built_page", None)
        page = built("studio") if callable(built) else getattr(self.window, "studio_page", None)
        if page is not None and page.undo_stack is not self._stack:
            if self._stack is not None:
                try:
                    self._stack.indexChanged.disconnect(self._bump)
                except (RuntimeError, TypeError):
                    pass
            self._stack = page.undo_stack
            self._stack.indexChanged.connect(self._bump)
        return page

    def _bump(self, *_args) -> None:
        self.revision += 1

    def _project(self):
        page = self._page()
        if page is None or page.project is None:
            raise BridgeError("no_project", "Studio 没有打开工程")
        path = getattr(page.session, "project_path", None)
        if self.settings.get("scope") == "library" and path:
            from pathlib import Path
            from .studio_project import project_library_root
            if not common.inside(project_library_root(), Path(path)):
                raise BridgeError("out_of_scope", "当前工程不在授权的工程库目录内")
        return page, page.project

    def _project_info(self, page, project) -> dict:
        from .bilingual_layout import settings_from_state, translations_of
        from .language_rules import project_language
        from pathlib import Path
        path = getattr(page.session, "project_path", None)
        translations = translations_of(project.generation_metadata)
        settings = settings_from_state(project.studio_state)
        return dict(project_id=project.project_id, name=Path(path).stem if path else project.studio_state.get("project_name", ""),
                    revision=self.revision, cues=len(project.cues), speakers=len(project.speakers),
                    language=project_language(project) or "", translated=sum(1 for v in translations.values() if str(v or "").strip()),
                    bilingual=dict(mode=settings.mode, order=settings.order, layout=getattr(settings, "layout", "")),
                    unsaved=not page.undo_stack.isClean())

    # ------------------------------------------------------------ read tools
    def op_status(self, socket=None):
        from .build_identity import load_build_identity
        page = self._page()
        identity = load_build_identity()
        project = None
        if page is not None and page.project is not None:
            try:
                project = self._project_info(*self._project())
            except BridgeError as exc:
                project = dict(error=exc.code)
        return dict(app="2ByteASR", version=identity.app_version, protocol=common.PROTOCOL,
                    permissions=dict(read=True, edit_with_approval=self.settings.get("allow_edits", False),
                                     export=self.settings.get("allow_export", False)),
                    scope=self.settings.get("scope"), project=project)

    def op_list_projects(self, socket=None):
        import os
        from pathlib import Path
        page = self._page()
        open_path = str(getattr(page.session, "project_path", "") or "") if page is not None and page.project else ""
        rows = []
        if self.settings.get("scope") == "library":
            from .studio_project import PROJECT_SUFFIX, project_library_root
            root = project_library_root()
            if root.is_dir() and not common.is_reparse_point(root):
                for current, folders, files in os.walk(root):
                    depth = len(Path(current).relative_to(root).parts)
                    folders[:] = [f for f in folders if depth < 2 and not common.is_reparse_point(Path(current) / f)]
                    for name in files:
                        target = Path(current) / name
                        if target.suffix.lower() == PROJECT_SUFFIX and not common.is_reparse_point(target):
                            rows.append(dict(name=target.stem, relative_path=str(target.relative_to(root)),
                                             modified=round(target.stat().st_mtime),
                                             open=bool(open_path) and os.path.normcase(str(target)) == os.path.normcase(open_path)))
                    if len(rows) >= 500:
                        break
        elif open_path:
            rows.append(dict(name=Path(open_path).stem, relative_path=Path(open_path).name, open=True))
        return dict(scope=self.settings.get("scope"), projects=rows,
                    note="只列出授权范围内的工程；读取与修改针对 Studio 当前打开的工程")

    def _speaker_names(self, project) -> dict:
        return {s.id: (s.name or s.id) for s in project.speakers}

    def _cue_row(self, project, cue, index, translations, names, roles):
        return dict(id=cue.id, index=index, start_ms=cue.start_ms, end_ms=cue.end_ms, speaker_id=cue.speaker_id,
                    speaker=names.get(cue.speaker_id, cue.speaker_id), role=roles.get(cue.speaker_id, "main"),
                    text=cue.text, translation=str(translations.get(cue.id, "") or ""))

    def op_get_cues(self, socket=None, offset: int = 0, limit: int = 100, speaker_id: str = ""):
        from .bilingual_layout import translations_of
        from .speaker_roles import effective_roles
        page, project = self._project()
        offset, limit = max(0, int(offset)), max(1, min(MAX_PAGE, int(limit)))
        cues = [c for c in project.cues if not speaker_id or c.speaker_id == str(speaker_id)]
        translations, names, roles = translations_of(project.generation_metadata), self._speaker_names(project), effective_roles(project)
        rows = [self._cue_row(project, c, offset + i, translations, names, roles) for i, c in enumerate(cues[offset:offset + limit])]
        return dict(project=self._project_info(page, project), total=len(cues), offset=offset, cues=rows,
                    next_offset=offset + len(rows) if offset + len(rows) < len(cues) else None)

    def op_search(self, socket=None, query: str = "", field: str = "both", limit: int = 50):
        from .bilingual_layout import translations_of
        from .speaker_roles import effective_roles
        page, project = self._project()
        needle = str(query or "").strip().casefold()
        if not needle or len(needle) > 200:
            raise BridgeError("bad_params", "query must be 1-200 characters")
        if field not in ("text", "translation", "both"):
            raise BridgeError("bad_params", "field must be text, translation or both")
        translations, names, roles = translations_of(project.generation_metadata), self._speaker_names(project), effective_roles(project)
        hits = []
        for index, cue in enumerate(project.cues):
            haystacks = ([cue.text] if field != "translation" else []) + \
                        ([str(translations.get(cue.id, "") or "")] if field != "text" else [])
            if any(needle in h.casefold() for h in haystacks):
                hits.append(self._cue_row(project, cue, index, translations, names, roles))
                if len(hits) >= max(1, min(MAX_PAGE, int(limit))):
                    break
        return dict(query=query, field=field, matches=hits, revision=self.revision)

    def op_get_speakers(self, socket=None):
        from .speaker_roles import effective_roles, group_members, state_of
        _page, project = self._project()
        roles, members, state = effective_roles(project), set(group_members(project)), state_of(project)
        counts = {}
        for cue in project.cues:
            row = counts.setdefault(cue.speaker_id, [0, 0])
            row[0] += 1
            row[1] += max(0, cue.end_ms - cue.start_ms)
        names = self._speaker_names(project)
        manual = state.get("manual") or {}
        return dict(grouped=bool(state.get("grouped")), rule=state.get("rule", ""),
                    speakers=[dict(id=key, name=names.get(key, key), role=role, manual=key in manual,
                                   in_secondary_group=key in members, cues=counts.get(key, [0, 0])[0],
                                   speech_ms=counts.get(key, [0, 0])[1]) for key, role in roles.items()])

    def op_alignment_status(self, socket=None, offset: int = 0, limit: int = 100):
        """Where each line's start/end came from: measured by the aligner or placed."""
        page, project = self._project()
        offset, limit = max(0, int(offset)), max(1, min(MAX_PAGE, int(limit)))
        labels = dict(model="实测（对齐器）", cue_edge="字幕边界（未实测）", window_edge="窗口边缘（未实测）",
                      nearest="最近实测点", interpolated="插值", ctc="CTC 对齐模型校正（与参考相差 80 ms 内）")
        summary, rows = {}, []
        for index, cue in enumerate(project.cues):
            ref = next((r for r in cue.evidence_refs if str(r).startswith("cue-align:")), None)
            row = project.asr_evidence.get(ref, {}) if ref else {}
            pieces = (row.get("caption_arbitration") or {}).get("acoustic_words") or ()
            start = pieces[0].get("start_basis") if pieces else "none"
            end = pieces[-1].get("end_basis") if pieces else "none"
            summary[f"start:{start}"] = summary.get(f"start:{start}", 0) + 1
            summary[f"end:{end}"] = summary.get(f"end:{end}", 0) + 1
            if offset <= index < offset + limit:
                rows.append(dict(id=cue.id, index=index, start_ms=cue.start_ms, end_ms=cue.end_ms,
                                 start_basis=start, end_basis=end, start_label=labels.get(start, "无字词时间"),
                                 end_label=labels.get(end, "无字词时间"), word_pieces=len(pieces)))
        return dict(summary=summary, offset=offset, lines=rows, total=len(project.cues),
                    note="model = 对齐器实测；其他来源是按字幕边界或窗口放置，不代表声音位置")

    # ------------------------------------------------------------ plans
    def _require_edits(self):
        if not self.settings.get("allow_edits"):
            raise BridgeError("not_permitted", "设置中未允许外部 AI 提出修改")

    def _new_plan(self, kind, project, scope, summary, changes) -> dict:
        self._expire()
        plan = Plan(uuid.uuid4().hex[:12], kind, project.project_id, self.revision, scope, summary, changes)
        self.plans[plan.id] = plan
        return plan.public()

    def _expire(self):
        now = time.monotonic()
        for plan in self.plans.values():
            if plan.status == "previewed" and now - plan.created > PLAN_TTL_S:
                plan.status = "expired"

    def op_preview_text_edits(self, socket=None, edits=None):
        from .bilingual_layout import translations_of
        self._require_edits()
        _page, project = self._project()
        if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_EDITS:
            raise BridgeError("bad_params", f"edits must be a list of 1-{MAX_EDITS} items")
        by_id = {c.id: c for c in project.cues}
        translations = translations_of(project.generation_metadata)
        changes, seen = [], set()
        for item in edits:
            if not isinstance(item, dict) or str(item.get("cue_id")) not in by_id:
                raise BridgeError("unknown_cue", f"unknown cue: {item.get('cue_id') if isinstance(item, dict) else item}")
            cue_id = str(item["cue_id"])
            if cue_id in seen:
                raise BridgeError("bad_params", f"cue listed twice: {cue_id}")
            seen.add(cue_id)
            row = dict(cue_id=cue_id)
            for name, before in (("text", by_id[cue_id].text), ("translation", str(translations.get(cue_id, "") or ""))):
                if name in item and item[name] is not None:
                    value = str(item[name])
                    if len(value) > MAX_TEXT or any(ord(ch) < 32 and ch not in "\n" for ch in value):
                        raise BridgeError("bad_params", f"{name} of {cue_id}: at most {MAX_TEXT} characters, no control characters")
                    if name == "text" and not value.strip():
                        raise BridgeError("bad_params", f"text of {cue_id} cannot be empty")
                    if value != before:
                        row[name] = dict(before=before, after=value)
            if len(row) > 1:
                changes.append(row)
        if not changes:
            raise BridgeError("no_change", "所有修改都与当前内容相同")
        summary = tr("修改 {count} 条字幕的文字/译文", count=len(changes))
        return self._new_plan("text", project, dict(cue_ids=[c["cue_id"] for c in changes]), summary, changes)

    def op_preview_role_changes(self, socket=None, changes=None, organize: bool = False):
        from .speaker_roles import effective_roles
        self._require_edits()
        _page, project = self._project()
        roles = effective_roles(project)
        rows = []
        for item in changes or []:
            if not isinstance(item, dict) or str(item.get("speaker_id")) not in roles or item.get("role") not in ROLE_CHOICES:
                raise BridgeError("bad_params", f"each change needs a known speaker_id and role in {ROLE_CHOICES}")
            rows.append(dict(speaker_id=str(item["speaker_id"]), before=roles[str(item["speaker_id"])], role=item["role"]))
        if not rows and not organize:
            raise BridgeError("no_change", "没有角色修改")
        summary = tr("调整 {count} 位说话人的主要/次要角色", count=len(rows)) if rows else ""
        if organize:
            summary = (summary + "；" if summary else "") + tr("按主要/次要角色整理轨道")
        return self._new_plan("roles", project, dict(speaker_ids=[r["speaker_id"] for r in rows], organize=bool(organize)),
                              summary, rows)

    def op_preview_bilingual_layout(self, socket=None, compact: bool = True, mode: str = "", order: str = ""):
        from .bilingual_layout import MODES, settings_from_state
        self._require_edits()
        _page, project = self._project()
        current = settings_from_state(project.studio_state)
        if mode and mode not in MODES:
            raise BridgeError("bad_params", f"mode must be one of {MODES}")
        if order and order not in ("translation_first", "original_first"):
            raise BridgeError("bad_params", "order must be translation_first or original_first")
        change = dict(compact=bool(compact), mode=mode or current.mode, order=order or current.order,
                      before=dict(mode=current.mode, order=current.order, layout=getattr(current, "layout", "")))
        parts = [tr("套用紧凑双语排版")] if compact else []
        if mode and mode != current.mode:
            parts.append(tr("显示模式 {before} → {after}", before=current.mode, after=mode))
        if order and order != current.order:
            parts.append(tr("双语顺序 {before} → {after}", before=current.order, after=order))
        if not parts:
            raise BridgeError("no_change", "双语显示没有变化")
        return self._new_plan("bilingual", project, dict(display=True), "；".join(parts), [change])

    def op_get_plan_status(self, socket=None, plan_id: str = ""):
        self._expire()
        plan = self.plans.get(str(plan_id))
        if plan is None:
            raise BridgeError("unknown_plan", "没有这个计划（可能已撤销授权或程序已重启）")
        return plan.public()

    def _check_fresh(self, plan: Plan, page) -> None:
        self._expire()
        if plan.status == "expired":
            raise BridgeError("expired", "计划已过期，请重新预览")
        if page.project is None or page.project.project_id != plan.project_id:
            plan.status = "stale"
            raise BridgeError("stale", "Studio 中打开的已不是这个工程")
        if plan.revision != self.revision:
            plan.status = "stale"
            raise BridgeError("stale", "工程在预览之后已被修改，请重新预览")

    def op_apply_plan(self, socket=None, plan_id: str = "", wait_seconds: float = 60):
        """Ask the user in Studio. The answer comes from the dialog, never the client."""
        plan = self.plans.get(str(plan_id))
        if plan is None:
            raise BridgeError("unknown_plan", "没有这个计划")
        if plan.status in ("applied", "rejected", "undone", "cancelled"):
            raise BridgeError("already_used", f"计划已是 {plan.status} 状态，不能重复套用")
        self._require_edits()
        page, _project = self._project()
        if plan.status != "awaiting_approval":
            self._check_fresh(plan, page)
            plan.status = "awaiting_approval"
            self._ask(plan, undo=False)
        return self._wait(plan, socket, wait_seconds)

    def op_undo_plan(self, socket=None, plan_id: str = "", wait_seconds: float = 60):
        plan = self.plans.get(str(plan_id))
        if plan is None or plan.status not in ("applied", "awaiting_undo_approval"):
            raise BridgeError("not_undoable", "只能撤销本客户端已套用、且之后没有其他修改的计划")
        self._require_edits()
        page, _project = self._project()
        if plan.status == "applied":
            if page.undo_stack.index() != plan.undo_index or page.project.project_id != plan.project_id:
                raise BridgeError("not_undoable", "之后已有其他修改，请在 Studio 中用撤销历史处理")
            plan.status = "awaiting_undo_approval"
            self._ask(plan, undo=True)
        return self._wait(plan, socket, wait_seconds)

    def _wait(self, plan: Plan, socket, wait_seconds):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda plan_id=plan.id: self._answer_waiting(plan_id))
        self._waiting.setdefault(plan.id, []).append((socket, timer))
        timer.start(int(1000 * max(0.0, min(WAIT_MAX_S, float(wait_seconds or 0)))))
        return None

    def _answer_waiting(self, plan_id: str) -> None:
        plan = self.plans.get(plan_id)
        for socket, timer in self._waiting.pop(plan_id, []):
            timer.stop()
            if plan is None:
                self._send(socket, dict(ok=False, error=dict(code="unknown_plan", message="计划已取消")))
            else:
                self._send(socket, dict(ok=True, result=plan.public()))

    def _ask(self, plan: Plan, *, undo: bool) -> None:
        from .mcp_approval import ApprovalDialog
        page = self._page()
        dialog = ApprovalDialog(page.window() if page is not None else self.window, plan, undo=undo)
        dialog.decided.connect(lambda approved, plan_id=plan.id, undo=undo: self._decided(plan_id, approved, undo))
        self._dialogs[plan.id] = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _decided(self, plan_id: str, approved: bool, undo: bool) -> None:
        self._dialogs.pop(plan_id, None)
        plan = self.plans.get(plan_id)
        if plan is None or plan.status not in ("awaiting_approval", "awaiting_undo_approval"):
            return
        page = self._page()
        if not approved:
            plan.status, plan.message = ("applied", tr("用户拒绝撤销")) if undo else ("rejected", tr("用户拒绝"))
        elif undo:
            if page is None or page.undo_stack.index() != plan.undo_index:
                plan.status, plan.message = "applied", tr("之后已有其他修改，未撤销")
            else:
                page.undo_stack.undo()
                plan.status, plan.message = "undone", tr("已撤销")
        else:
            try:
                plan.status = "previewed"
                self._check_fresh(plan, page)
                self._apply(plan, page)
                plan.status, plan.undo_index = "applied", page.undo_stack.index()
                plan.message = tr("已套用，可在 Studio 中撤销")
            except BridgeError as exc:
                plan.message = str(exc)
            except Exception as exc:  # noqa: BLE001 - shown to the client, project stays as it was
                plan.status, plan.message = "failed", f"{type(exc).__name__}: {exc}"
        self.status_changed.emit()
        self._answer_waiting(plan_id)

    def _apply(self, plan: Plan, page) -> None:
        from .studio_commands import MutationOrigin
        plan.label = tr("外部 AI：{summary}", summary=plan.summary)[:80]
        stack = page.undo_stack
        stack.beginMacro(plan.label)
        try:
            if plan.kind == "text":
                for change in plan.changes:
                    if "text" in change:
                        page.cue_controller.set_text(change["cue_id"], change["text"]["after"],
                                                     command_text=plan.label, origin=MutationOrigin.LLM)
                    if "translation" in change:
                        page.cue_controller.set_translation(change["cue_id"], change["translation"]["after"])
            elif plan.kind == "roles":
                from .speaker_roles import decide, state_of
                from .studio_speaker_roles import SetSpeakerRolesCommand
                state = copy.deepcopy(state_of(page.project)) or decide(page.project, manual={})
                manual = dict(state.get("manual") or {})
                for change in plan.changes:
                    if change["role"] == "auto":
                        manual.pop(change["speaker_id"], None)
                    else:
                        manual[change["speaker_id"]] = change["role"]
                if plan.scope.get("organize"):
                    state = decide(page.project, manual=manual, expanded=bool(state.get("expanded")))
                state.update(manual=manual, grouped=True)
                stack.push(SetSpeakerRolesCommand(page.project, state, plan.label))
            elif plan.kind == "bilingual":
                from .studio_bilingual import apply_compact_layout, apply_display
                change = plan.changes[0]
                if change["compact"]:
                    apply_compact_layout(page)
                apply_display(page, mode=change["mode"], order=change["order"])
        finally:
            stack.endMacro()
        page.timeline.reindex_project()

    # ------------------------------------------------------------ export
    def op_export(self, socket=None, layers=None, name: str = ""):
        from pathlib import Path
        from .studio_subtitle_export import SUPPORTED_LANGUAGE_LAYERS, export_language_layers
        if not self.settings.get("allow_export"):
            raise BridgeError("not_permitted", "设置中未允许外部 AI 导出")
        page, project = self._project()
        path = getattr(page.session, "project_path", None)
        if not path:
            raise BridgeError("unsaved_project", "工程尚未保存到文件，无法确定导出位置")
        layers = list(layers or ["original"])
        if not set(layers) <= SUPPORTED_LANGUAGE_LAYERS:
            raise BridgeError("bad_params", f"layers must be within {sorted(SUPPORTED_LANGUAGE_LAYERS)}")
        stem = common.safe_file_stem(name or Path(path).stem)
        if stem is None:
            raise BridgeError("bad_name", "导出名只能是普通文件名（不含路径、保留名或控制字符）")
        project_dir = Path(path).parent
        target = project_dir / common.EXPORT_FOLDER
        if common.is_reparse_point(project_dir) or (target.exists() and not common.inside(project_dir, target)):
            raise BridgeError("out_of_scope", "导出位置是链接或指向工程文件夹之外")
        result = export_language_layers(copy.deepcopy(project), target, stem, layers)
        files = []
        for artifact in result.artifacts:
            if not common.inside(project_dir, Path(artifact.path)):
                raise BridgeError("out_of_scope", "导出结果不在工程文件夹内")
            files.append(dict(file=str(Path(artifact.path).relative_to(project_dir)), layer=artifact.layer,
                              cues=artifact.cue_count))
        return dict(folder=common.EXPORT_FOLDER, files=files, overwritten=False,
                    missing_translations=len(result.missing_translation_ids))


_BRIDGE: McpBridge | None = None


def bridge_for(window) -> McpBridge:
    global _BRIDGE
    if _BRIDGE is None or _BRIDGE.window is not window:
        _BRIDGE = McpBridge(window)
    return _BRIDGE


def start_if_enabled(window) -> McpBridge | None:
    """Called once after the main window shows: a settings read when off."""
    settings = common.read_settings()
    if not settings.get("enabled"):
        return None
    bridge = bridge_for(window)
    bridge.apply_settings(settings)
    return bridge
