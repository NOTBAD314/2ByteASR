"""Application-owned downloader UI adapter; background results never own navigation.

Two front ends share one queue (2026-10-26, user's design A+B): the full
link window and the Studio quick card that Ctrl+V opens. A toolbar capsule
in the Studio shows running work; finished imports raise a short notice.
"""
from __future__ import annotations
import copy
from collections import deque
import json
from pathlib import Path
import queue
import threading
import time
import uuid
import weakref

from PySide6.QtCore import QObject, QTimer, QUrl, QStandardPaths, Signal, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from ..i18n import tr
from ..media.link_download import DownloadEngine, fetch_image, make_task, redact
from ..media.link_manifest import MANIFEST_NAME, atomic_json, load_bundle, local_subtitle_bundle
from ..media.link_queue import DownloadQueue
from ..media.link_tools import DownloadCancelled
from ..projects.link_import import LinkImportCommand, target_matches
from ..projects.studio_project import studio_settings_path
from ..projects.studio_runtime_state import state_for
from ..runtime_paths import get_runtime_paths

ATTENTION = {"pending_import", "partial", "failed"}
THUMBNAIL_LIMIT = 60


def default_directory() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation))/"2ByteASR"


def link_preferences() -> dict:
    try:
        return json.loads(studio_settings_path().read_text(encoding="utf-8-sig")).get("link_download", {})
    except (ValueError, OSError):
        return {}


def save_link_preferences(values: dict) -> None:
    path = studio_settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
        data["link_download"] = values
        atomic_json(path, data)
    except (ValueError, OSError):
        pass


def controller_for(widget):
    host = widget.window()
    controller = getattr(host, "_link_download_controller", None)
    if controller is None:
        controller = LinkDownloadController(host)
        host._link_download_controller = controller
    return controller


def show_link_download(widget):
    controller = controller_for(widget)
    controller.show()
    return controller


def paste_link(page) -> bool:
    """Studio Ctrl+V: a video link on the clipboard opens the quick
    card; anything else is left to the focused widget (returns False)."""
    from ..media.link_choices import find_video_link
    clipboard = QApplication.clipboard()
    link = find_video_link(clipboard.text() if clipboard is not None else "")
    if not link:
        return False
    controller_for(page).quick_paste(page, link)
    return True


class LinkDownloadController(QObject):
    # Emitted from worker threads after a mailbox message: the main thread
    # handles it at once instead of on the next 200 ms tick (2026-10-26).
    wake = Signal()

    def __init__(self, host, *, engine=None, storage=None):
        super().__init__(host)
        self.host = host
        self.engine = engine or DownloadEngine()
        self.queue = DownloadQueue(storage or get_runtime_paths().user_data_root/"link-downloads/queue.json", self.engine)
        self.dialog = None
        self._dialog_creating = False
        self._pending_dialog_page = ''
        self.card = None
        self.popover = None
        self.toast = None
        self._capsules = []
        self._mailbox = queue.SimpleQueue()
        self._closed = False
        self._analysis_token = ""
        self._analysis_owner = "dialog"
        self._analysis_request = None
        self._analysis_cancel = threading.Event()
        self._browser_pending = deque()
        self._browser_cancel = threading.Event()
        self._browser_active = False
        self._browser_note = ""
        self._browser_choices = deque(maxlen=32)
        self._browser_form_url = ""
        self._jobs = []
        self._preparing = set()
        self._enqueue_requests = {}
        self._event_details = {}
        self._thumbnails = {}
        self._tools_error = ""
        self._tools_busy = False
        self._tools_cancel = threading.Event()
        self._attention = set()
        self._states = {t["task_id"]: t["state"] for t in self.queue.snapshots()}
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.wake.connect(self.poll)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        host.destroyed.connect(self.shutdown)

    def page(self):
        built = getattr(self.host, "built_page", None)
        return built("studio") if callable(built) else self.host if hasattr(self.host, "project_controller") else None

    def context(self):
        page = self.page()
        project = getattr(page, "project", None)
        session = getattr(page, "session", None)
        pages = getattr(self.host, "pages", None)
        view = pages.currentWidget() if pages is not None else page or self.host
        return dict(project_id=project.project_id if project else "",
            generation=session.generation if session else -1,
            revision=state_for(project).revision if project else -1, view=id(view))

    def _ensure_dialog(self):
        if self.dialog is None:
            # Own construction before any layout/theme callbacks can reenter.
            if self._dialog_creating:return None
            self._dialog_creating = True
            try:
                from .link_download_dialog import LinkDownloadDialog
                self.dialog = LinkDownloadDialog(self, self.host)
            finally:
                self._dialog_creating = False
        return self.dialog

    def receive_browser(self, request):
        from .browser_link_intake import receive
        return receive(self, request)

    def offer_browser_choices(self, catalog, mode, auth):
        self._browser_choices.append((catalog, mode, auth))
        self._browser_note = tr("请在链接下载窗口选择兔白助手任务的字幕语言与来源。")
        if not self.context()["project_id"]:
            self.show("home")

    def show_browser_choices(self):
        if self.dialog is None or not self._browser_choices:
            return
        if self.dialog.cancel_parse.isEnabled() or (
                self._browser_form_url and self._browser_form_url == self.dialog.url.text()):
            return
        catalog, mode, auth = self._browser_choices.popleft()
        self.dialog.url.setText(catalog["url"])
        self._browser_form_url = catalog["url"]
        self.dialog.set_catalog(catalog)
        self.dialog.apply_selection(dict(mode=mode, auto_import=mode != "subtitles"))
        if auth and auth.valid_for(catalog["url"]):
            self.dialog._authorization = auth
            self.dialog._authorization_url = catalog["url"]
            self.dialog.cookie.setText(tr("已接收浏览器授权"))
        self.dialog.message.setText(tr("请选择要下载的原语字幕，再开始下载。"))

    def browser_choice_submitted(self, url):
        if self._browser_form_url == url:
            self._browser_form_url = ""
            if self._browser_choices:
                QTimer.singleShot(0, self, self.show_browser_choices)

    def show(self, page_key=""):
        if self._closed:return
        if self._dialog_creating:
            self._pending_dialog_page = page_key or self._pending_dialog_page
            return
        dialog = self._ensure_dialog()
        if dialog is None:return
        dialog.refresh_targets()
        dialog.update_tasks(self.queue.snapshots(), self._event_details)
        page_key=self._pending_dialog_page or page_key
        self._pending_dialog_page=''
        if page_key:
            dialog.show_page(page_key)
        if dialog.isMinimized():
            dialog.setWindowState(dialog.windowState() & ~Qt.WindowMinimized)
        if not dialog.isVisible():dialog.show()
        if self._browser_note:
            dialog.message.setText(self._browser_note)
        if page_key in ("", "home") and self._browser_choices:
            self.show_browser_choices()
        dialog.raise_()
        dialog.activateWindow()

    # ----------------------------------------------------------- quick card
    def quick_paste(self, page, url):
        from .link_quick_card import LinkQuickCard
        if self.card is not None and self.card.page is not page:
            self.card.close()   # before the new analysis: closing a parsing card cancels it
            self.card.deleteLater()
            self.card = None
        # Parsing takes seconds; it starts before the card is built (2026-10-26).
        self.analyze(url, owner="card", **self.network())
        if self.card is None:
            self.card = LinkQuickCard(self, page)
        self.card.start(url)

    def more_options(self, url, catalog, thumbnail, selection):
        """Hand the card's parsed video to the full window without parsing again."""
        dialog = self._ensure_dialog()
        if self._analysis_owner == "card":
            self.cancel_analysis()
        dialog.url.blockSignals(True)
        dialog.url.setText(url)
        dialog.url.blockSignals(False)
        if catalog is not None:
            dialog.set_catalog(catalog, thumbnail)
            dialog.apply_selection(selection)
        dialog.parsing_finished()
        self.show("home")

    def network(self):
        return self.dialog._network() if self.dialog is not None else dict(proxy="", cookie_file="")

    def directory(self):
        if self.dialog is not None:
            return self.dialog.directory.text()
        return link_preferences().get("directory") or str(default_directory())

    # ------------------------------------------------------------- analysis
    def _background(self, kind, token, work, **context):
        mailbox = self._mailbox
        wake = self.wake
        def run():
            try:
                value = work()
                mailbox.put(dict(kind=kind, token=token, value=value, **context))
            except DownloadCancelled:
                mailbox.put(dict(kind=kind, token=token, cancelled=True, **context))
            except Exception as exc:
                mailbox.put(dict(kind=kind, token=token, error=redact(exc), **context))
            try:
                wake.emit()
            except RuntimeError:
                pass   # the controller is gone; nothing waits for this message
        thread = threading.Thread(target=run, daemon=True, name="link-"+kind)
        self._jobs = [job for job in self._jobs if job.is_alive()]
        self._jobs.append(thread)
        thread.start()

    def analyze(self, url, proxy="", cookie_file="", owner="dialog"):
        request=(str(url).strip(),str(proxy),id(cookie_file) if cookie_file else None,owner)
        if self._closed or request==self._analysis_request:return
        self.cancel_analysis()
        self._analysis_request=request
        token = self._analysis_token = uuid.uuid4().hex
        self._analysis_owner = owner
        cancel = self._analysis_cancel = threading.Event()
        covers = {}   # the preview's cover, reused by the full result
        quick = getattr(self.engine, "preview", None)
        if owner == "card" and callable(quick):
            def preview():
                value = quick(url, cancel=cancel.is_set, proxy=proxy)
                covers.setdefault("image", value.get("thumbnail", b""))
                return value
            self._background("preview", token, preview)
        def work():
            last = [0., ""]
            def progress(event):
                now = time.monotonic()
                if event.get("stage") != last[1] or now-last[0] >= .25:
                    self._mailbox.put(dict(kind="analysis_progress", token=token, value=event))
                    last[:] = [now, event.get("stage", "")]
            catalog = self.engine.analyze(url, cancel=cancel.is_set, proxy=proxy, cookie_file=cookie_file, notify=progress)
            # The choices go out now; the cover follows (it used to hold the
            # result back by another download, 2026-10-26).
            cover = covers.get("image", b"")
            self._mailbox.put(dict(kind="analyze", token=token, value=(catalog, cover)))
            self.wake.emit()
            if not cover and catalog.get("thumbnail") and not cancel.is_set():
                return fetch_image(catalog["thumbnail"], cancel=cancel.is_set, proxy=proxy) or None
            return None
        self._background("cover", token, work)

    def cancel_analysis(self):
        self._analysis_token = ""
        self._analysis_request = None
        self._analysis_cancel.set()

    def read_firefox_authorization(self, url, path):
        from .browser_profiles import load_firefox_site
        import sqlite3
        def work():
            try:
                return load_firefox_site(url, path)
            except (sqlite3.Error, OSError, ValueError):
                raise ValueError(tr("无法读取 Firefox 授权。请确认已登录，关闭 Firefox 后重试，或改用兔白助手。")) from None
        token = uuid.uuid4().hex
        self._background("profile_auth", token, work, url=url)
        return token

    def _analysis_target(self):
        """The front end that asked for the running analysis, if still shown."""
        if self._analysis_owner == "card":
            return self.card if self.card is not None and self.card.isVisible() else None
        return self.dialog if self.dialog is not None and self.dialog.isVisible() else None

    # ----------------------------------------------------------------- tools
    def install_tools(self):
        self.change_tools("repair")

    def change_tools(self, action):
        if self._tools_busy:
            return
        self._tools_busy = True
        self._tools_cancel.clear()
        token = uuid.uuid4().hex

        def work():
            from ..media.link_tools import ensure_tools
            from ..media.link_tool_updates import check_latest, install_latest, rollback_tools
            root = getattr(self.engine, "root", None) or get_runtime_paths().install_root
            if action == "check":
                return check_latest(root=root)
            if action in {"update", "rollback"}:
                if action == "update":
                    last = 0.

                    def progress(done, total):
                        nonlocal last
                        now = time.monotonic()
                        if now - last >= .35:
                            self._mailbox.put(dict(kind="tools_progress", token=token,
                                                   value=(done, total)))
                            self.wake.emit()
                            last = now

                    self.engine.tools = install_latest(root=root, progress=progress, cancel=self._tools_cancel)
                else:
                    self.engine.tools = rollback_tools(root=root)
            else:
                self.engine.tools = ensure_tools(root=root, cancel=self._tools_cancel.is_set)
            return self.engine.tools["versions"]

        self._background("tools_check" if action == "check" else "tools", token, work)

    def tool_versions(self) -> dict:
        tools = getattr(self.engine, "tools", None)
        return dict(tools.get("versions", {})) if isinstance(tools, dict) else {}

    def tools_status(self) -> tuple[str, str]:
        versions = self.tool_versions()
        if self._tools_error:
            return "warn", tr("下载工具需要检查 / 修复")
        if versions.get("yt_dlp"):
            return "ok", tr("下载工具正常") + f" · yt-dlp {versions['yt_dlp']}"
        return "off", tr("下载工具：首次解析时检查")

    # ----------------------------------------------------------------- tasks
    def enqueue(self, catalog, directory, options, *, proxy="", cookie_file="", thumbnail=b""):
        options=dict(options)
        context = self.context()
        target = dict(context, kind=options.pop("destination"), clip_id=options.pop("clip_id", ""),
                      confirmed_media=options.pop("confirmed_media", False),
                      replace_source=options.pop("replace_source", False))
        page = self.page()
        target["position_ms"] = int(getattr(getattr(page, "timeline", None), "playhead_ms", 0))
        if target["kind"] == "current" and not context["project_id"]:
            raise ValueError("当前没有工程，请选择新建工程。")
        task = make_task(catalog, directory, target=target, **options)
        # make_task allocates a fresh UUID, so queue.add's ID guard cannot
        # coalesce repeated UI submissions of the same in-flight download.
        active={row['task_id']:row for row in self.queue.snapshots()
                if row.get('state') in {'queued','running','paused','pausing','cancelling'}}
        self._enqueue_requests={key:value for key,value in self._enqueue_requests.items() if value in active}
        import os
        selection={k:v for k,v in task.items() if k not in {'task_id','directory','state','title'}}
        # Playback advances between clicks; retain the first task's import
        # position without treating that clock sample as a new user intent.
        selection['target']={k:v for k,v in task['target'].items() if k!='position_ms'}
        request=json.dumps(dict(directory=os.path.normcase(str(Path(directory).expanduser().resolve())),
            selection=selection,
            proxy=proxy,authorization=id(cookie_file) if cookie_file else None),sort_keys=True,ensure_ascii=False)
        existing=self._enqueue_requests.get(request)
        if existing in active:
            self._refresh_views()
            return active[existing]
        if thumbnail:
            self._thumbnails[(catalog.get("platform", "Youtube"), catalog["video_id"])] = bytes(thumbnail)
            while len(self._thumbnails) > THUMBNAIL_LIMIT:
                self._thumbnails.pop(next(iter(self._thumbnails)))
        self.queue.add(task, proxy=proxy, cookie_file=cookie_file)
        self._enqueue_requests[request]=task['task_id']
        self._refresh_views()
        return task

    def thumbnail_for(self, task) -> bytes:
        return self._thumbnails.get((task.get("platform", "Youtube"), task.get("video_id", "")), b"")

    def task(self, task_id):
        return next(t for t in self.queue.snapshots() if t["task_id"] == task_id)

    def task_action(self, name, task_id):
        """One place for the window's task cards and the Studio popover."""
        try:
            if name == "cancel":
                self.queue.cancel(task_id)
            elif name == "pause":
                self.queue.pause(task_id)
            elif name == "resume":
                self.queue.resume(task_id, **self.network())
            elif name in ("retry", "retry_subtitles"):
                self.queue.retry(task_id, subtitles_only=name == "retry_subtitles", **self.network())
            elif name == "import":
                self.request_import(task_id, kind="current" if self.context()["project_id"] else "new")
            elif name in ("edit", "ai"):
                self.open_editor(task_id, ai=name == "ai")
            elif name == "folder":
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.task(task_id)["directory"]))
            elif name == "preview":
                from .link_subtitle_preview import prepare
                directory = self.task(task_id)["directory"]
                self._background("subtitle_preview", task_id, lambda: prepare(directory, MANIFEST_NAME))
            elif name == "reprocess":
                from PySide6.QtWidgets import QInputDialog
                modes = {"smart": tr("智能整句重建"), "original": tr("原始字幕"), "ai": tr("AI 精细断句")}
                selected, accepted = QInputDialog.getItem(self.host, tr("重新处理字幕"),
                    tr("从已保存的原稿重新生成字幕。已保存工程里的内容会保留。"),
                    list(modes.values()), 0, False)
                if accepted:
                    mode = next(key for key, title in modes.items() if title == selected)
                    self.queue.reprocess(task_id, mode)
            elif name == "locate":
                self.locate(task_id)
        except (ValueError, KeyError, StopIteration) as exc:
            self._show_error(str(exc))
        self._refresh_views()

    def open_editor(self, task_id, ai=False):
        result = self.task(task_id).get("import_result", {})
        page = self.page()
        def ready(studio):
            if self.dialog is not None:
                self.dialog.hide()
            if ai:
                from ..studio.link_caption_cleanup import LinkCaptionCleanupDialog
                LinkCaptionCleanupDialog(studio, studio).exec()
        if page and page.project and page.project.project_id == result.get("project_id"):
            switch = getattr(self.host, "_switch_page", None)
            if switch:
                switch(page)
            ready(page)
        elif result.get("project_path") and hasattr(self.host, "open_studio_project"):
            self.host.open_studio_project(result["project_path"], on_ready=ready)
        else:
            self._show_error("请先导入此任务，再进入编辑。")

    def locate(self, task_id):
        result = self.task(task_id).get("import_result", {})
        page = self.page()
        if page is None or page.project is None or page.project.project_id != result.get("project_id"):
            return
        clip = next((c for t in page.project.video_tracks for c in t.clips if c.id == result.get("clip_id")), None)
        if clip is not None:
            page.video.set_paused(True)
            page._seek(clip.timeline_in_ms / 1000.0)

    def _automatic_allowed(self, target):
        current = self.context()
        if target.get("kind") == "new":
            return all(target.get(key) == current[key] for key in ("project_id", "generation", "revision", "view"))
        return (target_matches(self.page(), target) and current["view"] == target.get("view")
                and (not target.get("replace_source") or current["revision"] == target.get("revision")))

    def request_import(self, task_id, *, automatic=False, bundle=None, kind=None):
        if task_id in self._preparing:
            return
        task = self.task(task_id)
        if task["state"] in {"queued", "running", "cancelling", "pausing"}:
            self._show_error("请等待下载完成，或先取消任务再导入已完成的部分。")
            return
        target = copy.deepcopy(task["target"])
        if automatic:
            if not self._automatic_allowed(target):
                self.queue.pending(task_id, tr("目标工程已切换，下载完成，待导入。"))
                return
        elif kind:
            page = self.page()
            target = dict(self.context(), kind=kind, clip_id="", confirmed_media=False, replace_source=False,
                          position_ms=int(getattr(getattr(page, "timeline", None), "playhead_ms", 0)))
        else:
            target = self.dialog.import_target() if self.dialog else dict(self.context(), kind="current")
        self._preparing.add(task_id)
        if bundle is None:
            self._background("bundle", task_id, lambda: self.queue._prepare_bundle(Path(task["directory"])/MANIFEST_NAME),
                target=target, automatic=automatic)
        else:
            self._route_bundle(task_id, bundle, target, automatic)

    def _route_bundle(self, task_id, bundle, target, automatic):
        if automatic and not self._automatic_allowed(target):
            self._preparing.discard(task_id)
            self.queue.pending(task_id, tr("目标工程已切换，下载完成，待导入。"))
            return
        if target["kind"] == "new":
            if not bundle.get("media_result"):
                self._preparing.discard(task_id)
                self._show_error("仅字幕任务请选择已打开工程中的对应媒体片段。")
                return
            task = self.task(task_id)
            def blank():
                from ..projects.studio_project import SubtitleProject, StudioMedia, save_project
                from ..projects.link_import import prepare_import
                from ..media.link_catalog import safe_video_filename
                project = SubtitleProject(media=StudioMedia(path="", display_name=task["title"]))
                basename = safe_video_filename(task["video_id"])
                path = Path(task["directory"])/"project"/(basename+"-"+uuid.uuid4().hex[:8]+".2byteproj")
                project.validate()
                started = time.perf_counter()
                prepared = prepare_import(project, bundle, bundle["media_result"])
                planning_ms = round((time.perf_counter() - started) * 1000, 1)
                save_project(project, path)
                return str(path), project.project_id, prepared, planning_ms
            self._background("blank", task_id, blank, bundle=bundle, target=target, automatic=automatic)
            return
        page = self.page()
        if not target_matches(page, target):
            self._preparing.discard(task_id)
            self.queue.pending(task_id, tr("目标工程已切换，下载完成，待导入。"))
            return
        self._apply(page, task_id, bundle, target)

    def _apply(self, page, task_id, bundle, target, *, prepared=None, background_planning_ms=None):
        try:
            if not target_matches(page, target):
                raise ValueError("目标工程已失效；文件仍保留在下载目录。")
            page.video.set_paused(True)
            planning_start = time.perf_counter()
            command = LinkImportCommand(page.project, bundle, bundle.get("media_result"),
                prepared=prepared,
                position_ms=target.get("position_ms", 0), clip_id=target.get("clip_id", ""),
                confirmed_media=target.get("confirmed_media", False),
                replace_source=target.get("replace_source", False))
            transaction_start = time.perf_counter()
            page.undo_stack.push(command)
            refresh_start = time.perf_counter()
            refresh_after_import(page, command.result)
            page._studio_trace("LINK_IMPORT_COMMIT", task_id=task_id, video_id=bundle["manifest"]["video_id"],
                primary_track_id=bundle["manifest"].get("primary_track_id", ""),
                output_file=bundle.get("media_path", ""), cue_count=command.result.get("cue_count", 0),
                project_id=page.project.project_id, background_planning_ms=background_planning_ms,
                gui_planning_ms=round((transaction_start-planning_start)*1000, 1),
                transaction_ms=round((refresh_start-transaction_start)*1000, 1),
                refresh_ms=round((time.perf_counter()-refresh_start)*1000, 1))
            imported = dict(command.result, project_path=str(page.project_path or ""),
                            project_id=page.project.project_id, generation=page.session.generation)

            def record_import():
                from ..storage.project_stage_history import record_stage

                project_id = imported["project_id"]
                manifest = bundle["manifest"]
                tracks = manifest.get("subtitles") or ()
                platform = str(manifest.get("platform") or "").lower()
                source = platform if platform in {"youtube", "bilibili"} else "online_media"
                record_stage(project_id, "download", "partial" if manifest.get("errors") else "completed",
                             source=source, tracks=len(tracks), media=int(bool(bundle.get("media_path"))))
                json3_tracks = sum(row.get("actual_format") == "json3" for row in tracks)
                if json3_tracks:
                    record_stage(project_id, "json3", "completed", source="json3", tracks=json3_tracks)
                rebuilt = [row for row in tracks if row.get("processing_mode") in ("smart", "ai")]
                if rebuilt:
                    record_stage(project_id, "reconstruction", "completed", tracks=len(rebuilt),
                                 cues=sum(int(row.get("cue_count") or 0) for row in rebuilt))
                record_stage(project_id, "import", "completed", source="studio",
                             cues=int(imported.get("cue_count") or 0))

            if target.get("newly_created"):
                completed = []
                expected_project = page.project
                generation = page.session.generation
                def saved(_path, error):
                    completed.append(True)
                    if error is not None:
                        self.queue.pending(task_id, redact(error))
                        self._show_error(str(error))
                        return
                    self.queue.imported(task_id, imported)
                    record_import()
                    if page.project is expected_project and page.session.generation == generation:
                        self._notify_imported(page, task_id)
                if page.save(on_finished=saved) is None and not completed:
                    saved(None, RuntimeError('新工程尚未完成保存，导入内容仍保留在内存中。'))
            else:
                self.queue.imported(task_id, imported)
                record_import()
                self._notify_imported(page, task_id)
        except Exception as exc:
            self.queue.pending(task_id, redact(exc))
            self._show_error(str(exc))
        finally:
            self._preparing.discard(task_id)

    def _notify_imported(self, page, task_id):
        if not page.isVisible():
            return
        try:
            task = self.task(task_id)
            project = page.project
            if task.get("recognize") and hasattr(page, "_open_recognition_sheet"):
                QTimer.singleShot(0, page, lambda: page._open_recognition_sheet() if page.project is project else None)
            from .link_quick_card import ImportToast
            if self.toast is None or self.toast.page is not page:
                if self.toast is not None:
                    self.toast.deleteLater()
                self.toast = ImportToast(self, page)
            self.toast.show_task(task)
        except Exception as exc:  # the notice is a courtesy; the import already happened
            from ..diagnostics.event_log import emit
            emit("link.import.notice", result="failed", error=redact(exc))

    def import_sidecar(self, page, source, media, clip_id):
        target = dict(self.context(), kind="current", clip_id=clip_id, confirmed_media=True)
        def work():
            return load_bundle(Path(source)) if str(source).endswith(".2byte-download.json") else local_subtitle_bundle(Path(media), Path(source))
        self._background("sidecar", uuid.uuid4().hex, work, target=target)

    def _show_error(self, message):
        target = self._analysis_target() if self._analysis_owner == "card" else None
        if target is not None:
            target.show_error(tr(str(message)))
        elif self.dialog is not None and self.dialog.isVisible():
            self.dialog.message.setText(tr(str(message)))
        else:
            page = self.page()
            if page is not None and getattr(page, "save_state", None) is not None:
                page.save_state.setText(tr(str(message)))

    # -------------------------------------------------------- studio capsule
    def attach_capsule(self, capsule):
        self._capsules.append(weakref.ref(capsule))
        capsule.clicked.connect(lambda _=False, c=capsule: self.show_popover(c))
        self._refresh_capsules()

    def show_popover(self, capsule):
        from .link_quick_card import TaskPopover
        if self.popover is None or self.popover.anchor is not capsule:
            if self.popover is not None:
                self.popover.deleteLater()
            self.popover = TaskPopover(self, capsule)
        self._attention.clear()
        self.popover.update_tasks(self.queue.snapshots(), self._event_details)
        self.popover.popup()
        self._refresh_capsules()

    def _refresh_capsules(self, tasks=None):
        from .link_download_widgets import ACTIVE, progress_parts
        if not self._capsules:
            capsule = getattr(self.page(), "studio_link_capsule", None)
            if capsule is not None:
                self.attach_capsule(capsule)
                return
        tasks = self.queue.snapshots() if tasks is None else tasks
        running = [t for t in tasks if t["state"] in ACTIVE]
        current = next((t for t in running if t["state"] == "running"), None)
        fraction = progress_parts(self._event_details.get(current["task_id"], {}))[0] if current else None
        attention = bool(self._attention)
        alive = []
        for ref in self._capsules:
            capsule = ref()
            if capsule is None:
                continue
            try:
                capsule.set_state(len(running), fraction, attention)
            except RuntimeError:
                continue
            alive.append(ref)
        self._capsules = alive

    def _refresh_views(self, snapshots=None):
        snapshots = self.queue.snapshots() if snapshots is None else snapshots
        if self.dialog is not None and self.dialog.isVisible():
            self.dialog.update_tasks(snapshots, self._event_details)
        if self.popover is not None and self.popover.isVisible():
            self.popover.update_tasks(snapshots, self._event_details)
        if self.card is not None and self.card.isVisible():
            self.card.update_tasks(snapshots, self._event_details)
        self._refresh_capsules(snapshots)

    # ------------------------------------------------------------------ poll
    def poll(self):
        if self._closed:
            return
        for event in self.queue.events():
            task_id = event["task_id"]
            self._event_details[task_id] = {k: v for k, v in event.items() if k != "bundle"}
            if event.get("terminal") and event.get("state") == "pending_import":
                task = self.task(task_id)
                if task.get("auto_import"):
                    self.request_import(task_id, automatic=True, bundle=event.get("bundle"))
        while not self._mailbox.empty():
            item = self._mailbox.get()
            kind, token = item["kind"], item["token"]
            if kind in {"tools", "tools_check"}:
                self._tools_busy = False
            if kind == "profile_auth":
                if self.dialog is not None and self.dialog._profile_request == token:
                    if item.get("error"):
                        self.dialog.cookie.setText(tr("当前浏览器无法读取"))
                        self.dialog.message.setText(item["error"])
                    else:
                        self.dialog.install_authorization(item["url"], item["value"])
                continue
            if kind == "browser_analysis":
                from .browser_link_intake import enqueue, setup
                self._browser_active = False
                error = item.get("error")
                if not error and not item.get("cancelled"):
                    try:
                        task = enqueue(self, item["value"])
                        if task:
                            self._browser_note = tr("已接收兔白助手任务，可在队列中查看。")
                    except (ValueError, OSError) as exc:
                        error = redact(exc)
                if error:
                    self._browser_note = tr("兔白助手任务未完成") + " · " + error
                    if not self.context()["project_id"]:
                        self.show("home")
                        if self.dialog is not None:
                            self.dialog.url.setText(item["browser_url"])
                if self.dialog is not None and self.dialog.isVisible():
                    self.dialog.message.setText(self._browser_note)
                setup(self, self._browser_pending)
                continue
            if kind in {"analyze", "analysis_progress", "preview", "cover"} and token != self._analysis_token:
                continue
            if kind == "preview" and (item.get("error") or item.get("cancelled")):
                continue   # no preview: the full result still comes
            if kind == "cover" and (item.get("error") or item.get("cancelled")):
                kind = "analyze"   # the analysis itself failed or was cancelled
            elif kind == "cover" and item.get("value") is None:
                continue
            if kind == 'analyze':
                self._analysis_request = None
            if item.get("error") or item.get("cancelled"):
                self._preparing.discard(token)
                if kind == "analyze" and self.dialog and self._analysis_owner == "dialog":
                    self.dialog.parsing_finished()
                    if self.dialog._authorization:
                        self.dialog.cookie.setText(tr("授权可能过期或网站限制访问"))
                if kind == "tools":
                    self._tools_error = item.get("error", "")
                self._show_error(item.get("error") or tr("已取消"))
                continue
            if kind == "analysis_progress":
                target = self._analysis_target()
                if target is not None:
                    from .link_download_widgets import STAGES
                    event = item["value"]
                    detail = tr(STAGES.get(event.get("stage"), "正在解析"))
                    if event.get("total"):
                        detail += f" · {event.get('downloaded', 0)/event['total']:.0%}"
                    if target is self.dialog:
                        target.message.setText(detail)
                    else:
                        target.set_progress(detail)
            elif kind == "analyze":
                target = self._analysis_target()
                if target is not None:
                    target.set_catalog(*item["value"])
            elif kind == "preview":
                target = self._analysis_target()
                if target is not None and hasattr(target, "set_preview"):
                    target.set_preview(item["value"])
            elif kind == "cover":
                target = self._analysis_target()
                if target is not None and target.catalog is not None:
                    target.set_thumbnail(item["value"])
            elif kind == "tools":
                self._tools_error = ""
                self._show_error(tr("下载工具已校验") + " · " + " / ".join(f"{k} {v}" for k, v in item["value"].items()))
                if self.dialog is not None and self.dialog.isVisible():
                    self.dialog._refresh_tools()
            elif kind == "tools_check":
                result = item["value"]
                message = tr("已在使用签名清单的下载工具。")
                if result["available"]:
                    message = tr("可安装工具元件 · {version} · {size} MiB",
                        version=result["release"], size=round(result["component"].archive.size / 1048576))
                self._show_error(message)
            elif kind == "tools_progress":
                done, total = item["value"]
                if total:
                    self._show_error(tr("正在下载已签名工具元件 · {percent}%", percent=round(100 * done / total)))
            elif kind == "bundle":
                self._route_bundle(token, item["value"], item["target"], item["automatic"])
            elif kind == "subtitle_preview":
                from .link_subtitle_preview import show_preview
                show_preview(self.dialog if self.dialog and self.dialog.isVisible() else self.host, item["value"])
            elif kind == "blank":
                target = item["target"]
                if not self._automatic_allowed(target):
                    self._preparing.discard(token)
                    self.queue.pending(token, tr("目标工程已切换，下载完成，待导入。"))
                    continue
                path, identity, prepared, planning_ms = item["value"]
                def opened(page, task_id=token, bundle=item["bundle"], identity=identity,
                           prepared=prepared, planning_ms=planning_ms):
                    if self._closed:
                        return
                    if page.project is None or page.project.project_id != identity:
                        self._preparing.discard(task_id)
                        return
                    new_target = dict(self.context(), kind="current", newly_created=True, position_ms=0)
                    self._apply(page, task_id, bundle, new_target, prepared=prepared,
                                background_planning_ms=planning_ms)
                opener = getattr(self.host, "open_studio_project", None)
                if callable(opener):
                    opener(path, source="link_download", on_ready=opened)
                else:
                    page = self.page()
                    page.open_project(path, on_ready=lambda p=page: opened(p))
                self._watch_open(token, identity)
            elif kind == "sidecar":
                page = self.page()
                if target_matches(page, item["target"]):
                    try:
                        command = LinkImportCommand(page.project, item["value"],
                            clip_id=item["target"]["clip_id"], confirmed_media=True)
                        page.undo_stack.push(command)
                        refresh_after_import(page, command.result)
                    except Exception as exc:
                        self._show_error(str(exc))
        snapshots = self.queue.snapshots()
        self._track_attention(snapshots)
        self._refresh_views(snapshots)

    def _track_attention(self, snapshots):
        """Tasks that finished needing a decision during this session light the capsule."""
        for task in snapshots:
            before = self._states.get(task["task_id"])
            if before != task["state"]:
                self._states[task["task_id"]] = task["state"]
                if task["state"] in ATTENTION and before is not None:
                    self._attention.add(task["task_id"])
                else:
                    self._attention.discard(task["task_id"])

    def _watch_open(self, task_id, project_id):
        """Release an import when the normal open/save guard is cancelled."""
        def check():
            if self._closed or task_id not in self._preparing:
                return
            page = self.page()
            building = getattr(self.host, "_studio_entry_pending", None)
            gate = getattr(page, "_readiness", None)
            if building is not None or (gate is not None and gate.active):
                QTimer.singleShot(300, self, check)
                return
            if page is None or page.project is None or page.project.project_id != project_id:
                self._preparing.discard(task_id)
                self.queue.pending(task_id, tr("目标工程已切换，下载完成，待导入。"))
        QTimer.singleShot(300, self, check)

    def shutdown(self, *_):
        if self._closed:
            return
        self._closed = True
        self._analysis_cancel.set()
        self._tools_cancel.set()
        self._browser_cancel.set()
        self._browser_pending.clear()
        self._browser_choices.clear()
        self.timer.stop()
        self.queue.close()
        for widget in (self.card, self.popover, self.toast):
            if widget is not None:
                try:
                    widget.hide()
                except RuntimeError:
                    pass


def refresh_after_import(page, result):
    page.cue_model.set_project(page.project)
    page.timeline.set_project(page.project)
    page._populate_speakers()
    page._sync_video_empty_state()
    page._refresh_edit_playback_state()
    page._sync_multitrack_preview_at(int(page.timeline.playhead_ms))
    page._generate_project_waveforms()
    page.video.set_paused(True)
    from ..studio.studio_bilingual import sync_controls
    sync_controls(page)
    page.save_state.setText(tr("已导入 {count} 条配套字幕", count=result.get("cue_count", 0)))
    if result.get("warnings"):
        page.save_state.setText(page.save_state.text() + " · " + " ".join(result["warnings"]))
