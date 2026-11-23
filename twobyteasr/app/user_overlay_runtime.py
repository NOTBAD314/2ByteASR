"""Applying 「我的改动」 (``user_overlay``) to the running program (2026-11-16).

* At start (``install``, before the main window): hold Shift (or set ``TWOBYTEASR_SAFE_MODE=1``)
  for a safe start that applies nothing this time. After an update (another program build than
  last time) every entry is checked again: a sentence that is no longer in the interface, a style
  the rules no longer accept, a script for another ``API_VERSION`` is marked 「更新后暂停」 and
  listed for the user; nothing is deleted. A loading marker left by the previous start means a
  script was loading when the program died: all scripts are paused.
* Texts go into ``i18n`` (``set_user_texts``); every translation path asks it first.
* Styles are appended to the named control's own sheet, between markers, and put back whenever
  that control's sheet is set again (Show / StyleChange): a control's own sheet wins over the
  window's, so this is the only place a user style reliably applies.
* Scripts run after the main window is shown (``after_window``), each in its own module with a
  small ``ScriptAPI``; one that raises is switched off and reported.
* ``reapply`` puts a changed layer into effect at once (兔白's 「帮我做」, the settings page).
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import traceback

from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QWidget

from . import user_overlay

MARK_START = '/* 2byteasr-user-overlay */'
MARK_END = '/* end 2byteasr-user-overlay */'
_BLOCK = re.compile(re.escape(MARK_START) + r'.*?' + re.escape(MARK_END), re.S)
SAFE_ENV = 'TWOBYTEASR_SAFE_MODE'
LOADING_MARKER = 'scripts-loading.json'

_RUNTIME = None


def runtime():
    """The installed runtime, or None (tests, tools without the main window)."""
    return _RUNTIME


def program_identity() -> str:
    """Which build this is: version + source commit, so a daily with the same version counts as new."""
    try:
        from ..diagnostics.build_identity import load_build_identity
        build = load_build_identity()
        sha = str(getattr(build, 'git_sha', '') or '')[:10]
        return f'{build.app_version} {sha}'.strip()
    except Exception:  # noqa: BLE001
        try:
            from .updater import current_version
            return current_version()
        except Exception:  # noqa: BLE001
            return ''


def is_ui_text(source: str) -> bool:
    """A built-in interface sentence (a key the language pass knows), not user content."""
    from .. import i18n
    if source in i18n._KNOWN_KEYS:
        return True
    return source in i18n.language_table('zh-Hant')


def resolve_ui_text(shown: str) -> str:
    """The source key of a sentence as it is shown in any language, or '' when it is not interface text."""
    text = ' '.join(str(shown or '').split()) if '\n' not in str(shown or '') else str(shown or '').strip()
    if not text:
        return ''
    if is_ui_text(text):
        return text
    from ..i18n_widgets import _reverse_translations
    source = _reverse_translations().get(text, '')
    return source if source and is_ui_text(source) else ''


# ------------------------------------------------------------------ styles
class StyleKeeper(QObject):
    """Keeps each named control's user style at the end of its own sheet."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.blocks: dict[str, str] = {}
        self._pending: dict[int, QWidget] = {}
        self._busy = False
        self._listening = False

    def set_styles(self, styles: dict) -> None:
        old = set(self.blocks)
        self.blocks = {name: MARK_START + '\n' + '\n'.join(f'{selector} {{ {rules} }}' for _id, selector, rules in items)
                       + '\n' + MARK_END for name, items in styles.items()}
        from ..design.app_events import listen, unlisten
        if self.blocks and not self._listening:
            listen(self, (QEvent.Type.Show, QEvent.Type.StyleChange))
            self._listening = True
        elif not self.blocks and self._listening:
            unlisten(self)
            self._listening = False
        names = old | set(self.blocks)
        if names:
            for widget in self.app.allWidgets():
                if widget.objectName() in names:
                    self.keep(widget)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if self._busy or not isinstance(watched, QWidget) or watched.objectName() not in self.blocks:
            return False
        key = id(watched)
        if key not in self._pending:
            self._pending[key] = watched
            QTimer.singleShot(0, self, self._flush)
        return False

    def _flush(self):
        from shiboken6 import isValid
        pending, self._pending = list(self._pending.values()), {}
        for widget in pending:
            if isValid(widget):
                self.keep(widget)

    def keep(self, widget) -> None:
        sheet = widget.styleSheet()
        base = _BLOCK.sub('', sheet).rstrip()
        block = self.blocks.get(widget.objectName(), '')
        wanted = (base + '\n' + block) if block else base
        if wanted != sheet:
            self._busy = True
            try:
                widget.setStyleSheet(wanted)
            finally:
                self._busy = False


# ------------------------------------------------------------------ scripts
class ScriptAPI:
    """What an extension script's ``setup(api)`` receives (``API_VERSION`` 1)."""
    API_VERSION = user_overlay.API_VERSION

    def __init__(self, window, entry: dict, runtime_):
        self.window = window
        self.app = QApplication.instance()
        self.script_id = entry['id']
        self.version = runtime_.identity
        self._runtime = runtime_

    @property
    def data_dir(self):
        """A folder of this script's own, kept with 「我的改动」."""
        folder = user_overlay.root() / 'script-data' / self.script_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def find(self, object_name: str):
        """The control with this objectName in any 2ByteASR window, or None."""
        for top in [self.window, *QApplication.topLevelWidgets()]:
            if top.objectName() == object_name:
                return top
            found = top.findChild(QWidget, object_name)
            if found is not None:
                return found
        return None

    def log(self, message) -> None:
        self._runtime.log.append(f'[{self.script_id}] {message}')

    def every(self, ms: int, callback):
        """A repeating timer owned by the main window (stops with it)."""
        timer = QTimer(self.window)
        timer.setInterval(max(50, int(ms)))
        timer.timeout.connect(callback)
        self._runtime.script_timers.setdefault(self.script_id, []).append(timer)
        timer.start()
        return timer

    # -------------------------------------------------------------- 2026-11-20: still API_VERSION 1, more to use
    def on(self, event: str, callback) -> None:
        """``callback(payload: dict)`` at a moment of ``extension_events.EVENTS`` (GUI thread)."""
        from . import extension_events
        extension_events.on(self.script_id, event, callback)

    def say(self, text) -> bool:
        """兔白 says one short line in her bubble when she is free; always written to the script log too."""
        self.log(f'兔白说：{text}')
        resident = getattr(self.window, '_bunny_resident', None)
        try:
            return bool(resident is not None and resident.say_line(str(text)))
        except RuntimeError:
            return False

    def in_background(self, work, on_done=None) -> None:
        """``work()`` on a worker thread; then ``on_done(result, error)`` back on the GUI thread."""
        import threading
        bridge = self._runtime.bridge()
        owner = sys.modules.get(f'twobyteasr_user_script_{self.script_id}')

        def run():
            try:
                result, error = work(), None
            except Exception as exc:  # noqa: BLE001 - handed to on_done
                result, error = None, exc
            bridge.finished.emit(self.script_id, on_done, (owner, result, error))
        threading.Thread(target=run, name=f'user-script-{self.script_id}', daemon=True).start()

    def ai(self, prompt, on_done, *, system: str = '', max_tokens: int = 2000) -> None:
        """Ask the user's own text AI (AI 设置; it spends their key); ``on_done(text, error)`` on the GUI thread."""
        from .bunny_chat import runtime_settings
        settings = runtime_settings(self.window)
        messages = ([{'role': 'system', 'content': str(system)}] if system else []) + [
            {'role': 'user', 'content': str(prompt)}]

        def work():
            if not settings:
                raise RuntimeError('还没有 AI 设置')
            from ..providers.ai_providers import provider_for_stage
            return provider_for_stage(settings, 'polish').complete(
                messages, max_tokens=int(max_tokens), temperature=0.2, timeout=(15, 180), stage='extension_script')
        self.in_background(work, on_done)

    def project(self):
        """The project open in the workbench (``.cues``: text, start_ms, end_ms, speaker_id), or None."""
        page = getattr(self.window, 'built_page', lambda _name: None)('studio')
        return getattr(page, 'project', None) if page is not None else None

    def learned(self) -> list[dict]:
        """The program's record of the user's own repeated corrections (original_term → corrected_term,
        occurrence_count, status, glossary_id), the same list 术语库 → 学习建议 shows."""
        from ..glossary.glossary_learning import GlossaryLearningStore
        page = getattr(self.window, 'built_page', lambda _name: None)('studio')
        store = getattr(page, '_learning_store', None) or GlossaryLearningStore()
        return [dict(item) for item in store.load().get('candidates') or ()]

    @property
    def glossary(self):
        return ScriptGlossary(self)


class ScriptGlossary:
    """Term libraries for an extension script: read, create, add (written with origin 「扩展脚本 uN」)."""

    def __init__(self, api: ScriptAPI):
        self._api = api

    def _legacy(self):
        legacy = getattr(self._api.window, 'legacy', None)
        if legacy is None:
            import subtitle_core as legacy
        return legacy

    def _refresh(self) -> None:
        library = getattr(getattr(self._api.window, 'term_library_page', None), 'library', None)
        notify = getattr(library, '_notify_library_changed', None)
        if callable(notify):
            try:
                notify()
            except RuntimeError:
                pass

    def libraries(self) -> list[dict]:
        from ..local_mcp import mcp_glossary
        return [dict(id=row['id'], name=row['name'], terms=row['terms'], aliases=row['aliases'], builtin=row['builtin'])
                for row in mcp_glossary.list_libraries(self._legacy())]

    def find(self, text: str = '', library: str = '', limit: int = 500) -> list[dict]:
        """Rows ``{'from', 'to', 'category', 'library', 'confirmed', 'kind'}`` containing ``text``."""
        from ..local_mcp import mcp_glossary
        return list(mcp_glossary.search(self._legacy(), text, library, 0, min(int(limit), mcp_glossary.MAX_PAGE))['rows'])

    def create(self, name: str, content_type: str = 'game') -> str:
        """A new (or the existing) library with this name; returns its id."""
        from ..local_mcp import mcp_glossary
        legacy = self._legacy()
        try:
            return mcp_glossary.resolve_library(legacy, name)[0]
        except mcp_glossary.GlossaryError:
            pass
        if not legacy.ensure_learned_content(str(name), str(content_type or 'game')):
            raise RuntimeError(f'术语库《{name}》没建成（写不进文件）')
        self._refresh()
        self._api.log(f'建了术语库《{name}》')
        return mcp_glossary.resolve_library(legacy, name)[0]

    def add(self, library: str, terms) -> str:
        """Add terms: strings (a canonical term) or dicts ``{'to', 'from', 'category'}`` (from ≠ to: an alias,
        replaced literally in recognized text). Repeats are skipped; at most 200 at a time. Returns the receipt."""
        # bunny_tools first: importing bunny_harness_tools on its own (a script that runs before 兔白's chat
        # was ever opened) would import bunny_tools, which builds its tool table from bunny_harness_tools.
        from . import bunny_tools  # noqa: F401
        from .bunny_harness_tools import apply_term_changes
        changes = []
        for item in terms if isinstance(terms, (list, tuple)) else [terms]:
            if isinstance(item, str) and item.strip():
                changes.append({'action': 'add', 'to': item.strip()})
            elif isinstance(item, dict) and (item.get('to') or item.get('term')):
                row = {'action': 'add', 'to': str(item.get('to') or item.get('term')).strip()}
                if item.get('from'):
                    row['from'] = str(item['from']).strip()
                if item.get('category'):
                    row['category'] = str(item['category']).strip()
                changes.append(row)
        if not changes:
            return '没有要加的词'
        receipt, _undo = apply_term_changes(self._api.window, library, changes[:200],
                                            origin=f'扩展脚本 {self._api.script_id}')
        self._api.log(receipt)
        return receipt


class _Bridge(QObject):
    """Hands a background result back to the GUI thread (``ScriptAPI.in_background``)."""
    finished = Signal(str, object, object)

    def __init__(self, runtime_):
        super().__init__(runtime_.app)
        self._runtime = runtime_
        self.finished.connect(self._done)

    def _done(self, script_id, callback, outcome):
        if callback is None:
            return
        owner, result, error = outcome
        try:
            if owner is not None:
                from .extension_events import _active_ids
                if self._runtime.loaded.get(script_id) is not owner or script_id not in _active_ids():
                    return
            callback(result, error)
        except Exception as exc:  # noqa: BLE001 - a script's own callback never breaks the program
            where = traceback.extract_tb(exc.__traceback__)[-1].lineno if exc.__traceback__ else '?'
            self._runtime.log.append(f'[{script_id}] 后台结果处理出错：{type(exc).__name__}: {str(exc)[:160]}（第 {where} 行）')


LOG_KEEP = 400


class OverlayRuntime:
    def __init__(self, app, *, safe: bool = False):
        self.app = app
        self.safe = safe
        self.identity = program_identity()
        self.notices: list[str] = []
        self.log: list[str] = []
        self.loaded: dict[str, object] = {}
        self.script_timers: dict[str, list] = {}
        self.styles = StyleKeeper(app)
        self._bridge = None
        from . import extension_events
        extension_events.reset()

    def bridge(self) -> _Bridge:
        if self._bridge is None:
            self._bridge = _Bridge(self)
        return self._bridge

    def script_log(self, entry_id: str = '', limit: int = 40) -> list[str]:
        """The newest lines of the script log, of one script or all."""
        del self.log[:-LOG_KEEP]
        rows = [line for line in self.log if not entry_id or line.startswith(f'[{entry_id}]')]
        return rows[-limit:]

    def unload(self, entry_id: str) -> None:
        """Forget a loaded script (its code changed or it was removed): timers stop, events stop, the next
        load runs the new code."""
        from shiboken6 import isValid
        from . import extension_events
        for timer in self.script_timers.pop(entry_id, []):
            if isValid(timer):
                timer.stop()
                timer.deleteLater()
        extension_events.drop(entry_id)
        self.loaded.pop(entry_id, None)
        sys.modules.pop(f'twobyteasr_user_script_{entry_id}', None)

    # -------------------------------------------------------------- start
    def start(self) -> None:
        if self.safe:
            self.notices.append('这次是安全模式启动（按住了 Shift）：「我的改动」都没有套用，改动本身都还在，下次正常启动就会恢复。')
            self.apply_texts_and_styles()          # nothing: clears whatever was applied before
            return
        self._after_crash()
        self._after_update()
        self.apply_texts_and_styles()

    def _after_crash(self) -> None:
        marker = user_overlay.root() / LOADING_MARKER
        if not marker.is_file():
            return
        paused = []
        for entry in user_overlay.active('script'):
            user_overlay.mark(entry['id'], 'paused_crash', '上次启动加载扩展脚本时程序没有正常结束')
            paused.append(entry['id'])
        marker.unlink(missing_ok=True)
        if paused:
            self.notices.append(f'上次启动加载扩展脚本时程序意外关闭了，已暂停 {len(paused)} 个脚本（{"、".join(paused)}）。'
                                '可以在「设置 → 我的改动」检查后再打开。')

    def _after_update(self) -> None:
        state = user_overlay.load()
        seen = state.get('last_app_version') or ''
        if seen and seen != self.identity:
            problems = []
            for entry in [item for item in state['entries'] if item.get('enabled') and not item.get('status')]:
                why = self.incompatible(entry)
                if why:
                    user_overlay.mark(entry['id'], 'paused_update', why)
                    problems.append(f'{user_overlay.KIND_LABELS[entry["kind"]]} {entry["id"]}：{why}')
            if problems:
                self.notices.append('程序更新后，有 {} 条「我的改动」对不上新版本，先暂停了（没有删除）：\n· '.format(len(problems))
                                    + '\n· '.join(problems[:6]) + ('\n· …' if len(problems) > 6 else ''))
        if seen != self.identity and self.identity:
            user_overlay.mark_seen_version(self.identity)

    def incompatible(self, entry: dict) -> str:
        """Why an entry no longer fits this build, or ''."""
        kind = entry['kind']
        try:
            user_overlay.check(kind, entry['target'], entry['value'])
        except user_overlay.OverlayError as exc:
            return str(exc)
        if kind == 'text' and not is_ui_text(entry['target']):
            return '新版本里已经没有这句界面文字了'
        if kind == 'script':
            path = user_overlay.script_path(entry)
            if not path.is_file():
                return '脚本文件不见了'
            try:
                user_overlay.check_script(path.read_text('utf-8'))
            except (OSError, user_overlay.OverlayError) as exc:
                return str(exc)
        return ''

    def apply_texts_and_styles(self) -> None:
        from .. import i18n
        state = user_overlay.load()
        texts = user_overlay.text_overrides(state) if not self.safe else {}
        if any(source not in i18n._KNOWN_KEYS for source in texts):
            i18n.language_table('zh-Hant')     # its code literals join the known keys the language pass rewrites
        i18n.set_user_texts(texts)
        self.styles.set_styles(user_overlay.styles(state) if not self.safe else {})

    # -------------------------------------------------------------- after the window shows
    def after_window(self, window, *, show_notices: bool = True) -> None:
        self.window = window
        if not self.safe:
            self.load_scripts(window)
        if show_notices and self.notices:
            QTimer.singleShot(0, window, lambda: self.show_notices(window))

    def load_scripts(self, window) -> list[str]:
        state = user_overlay.load()
        active_ids = {entry['id'] for entry in user_overlay.active('script', state)} if state.get('scripts_allowed') else set()
        from shiboken6 import isValid
        for entry_id, timers in self.script_timers.items():
            for timer in timers:
                if isValid(timer):
                    if entry_id in active_ids and not timer.isActive():
                        timer.start()
                    elif entry_id not in active_ids:
                        timer.stop()
        if not state.get('scripts_allowed'):
            return []
        wanted = [entry for entry in user_overlay.active('script', state) if entry['id'] not in self.loaded]
        if not wanted:
            return []
        marker = user_overlay.root() / LOADING_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(' '.join(entry['id'] for entry in wanted), 'utf-8')
        done = []
        try:
            for entry in wanted:
                why = self._run_script(window, entry)
                if why:
                    user_overlay.mark(entry['id'], 'paused_api' if 'API_VERSION' in why else 'failed', why, disable=True)
                    self.notices.append(f'扩展脚本 {entry["id"]}（{entry["value"]}）没能运行，已停用：{why}')
                else:
                    done.append(entry['id'])
        finally:
            marker.unlink(missing_ok=True)
        return done

    def _run_script(self, window, entry) -> str:
        path = user_overlay.script_path(entry)
        try:
            code = user_overlay.check_script(path.read_text('utf-8'))
        except (OSError, user_overlay.OverlayError) as exc:
            return str(exc)
        name = f'twobyteasr_user_script_{entry["id"]}'
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            exec(compile(code, str(path), 'exec'), module.__dict__)   # noqa: S102 - the user's own, switched-on script
            if getattr(module, 'API_VERSION', None) != user_overlay.API_VERSION:
                return f'脚本写的 API_VERSION 不是 {user_overlay.API_VERSION}'
            module.setup(ScriptAPI(window, entry, self))
        except Exception as exc:  # noqa: BLE001 - a broken script is reported, never raised into the program
            for timer in self.script_timers.pop(entry['id'], []):
                timer.stop()
                timer.deleteLater()
            from . import extension_events
            extension_events.drop(entry['id'])
            sys.modules.pop(name, None)
            where = traceback.extract_tb(exc.__traceback__)[-1].lineno if exc.__traceback__ else '?'
            return f'{type(exc).__name__}: {str(exc)[:160]}（第 {where} 行）'
        self.loaded[entry['id']] = module
        self.log.append(f'[{entry["id"]}] 已运行')
        return ''

    def show_notices(self, window) -> None:
        from PySide6.QtWidgets import QMessageBox
        from ..i18n import tr
        notices, self.notices = list(self.notices), []
        if not notices:
            return
        box = QMessageBox(window)
        box.setObjectName('userOverlayNotice')
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(str(tr('我的改动')))
        box.setText(str(tr('关于你自己的改动，有几件事要告诉你')))
        box.setInformativeText('\n\n'.join(notices))
        open_button = box.addButton(str(tr('打开我的改动')), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(str(tr('知道了')), QMessageBox.ButtonRole.RejectRole)

        def done(_result):
            if box.clickedButton() is open_button and callable(getattr(window, '_open_application_settings', None)):
                window._open_application_settings(initial_section='我的改动')
        box.finished.connect(done)
        box.open()
        self.notice_box = box

    # -------------------------------------------------------------- after a change
    def reapply(self) -> None:
        """Put the current layer into effect now: texts and styles at once, newly enabled scripts run."""
        from .. import i18n
        from ..i18n_widgets import refresh_application
        before = dict(i18n._USER_TEXTS)
        self.apply_texts_and_styles()
        if before != i18n._USER_TEXTS:
            for widget in self.app.allWidgets():
                widget.__dict__.pop('_i18n_pass', None)
            refresh_application(i18n.current_language())
        window = getattr(self, 'window', None)
        if window is not None and not self.safe:
            self.load_scripts(window)


def safe_start_requested() -> bool:
    if os.environ.get(SAFE_ENV) == '1':
        return True
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        return bool(QGuiApplication.queryKeyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
    except Exception:  # noqa: BLE001
        return False


def install(app, *, safe: bool | None = None) -> OverlayRuntime:
    """At start, before the main window: never raises (a broken layer must not stop the program)."""
    global _RUNTIME
    if _RUNTIME is not None:                       # installed again (tests, audits): the old one lets go first
        try:
            _RUNTIME.styles.set_styles({})
        except RuntimeError:
            pass
    runtime_ = OverlayRuntime(app, safe=safe_start_requested() if safe is None else safe)
    try:
        runtime_.start()
    except Exception as exc:  # noqa: BLE001
        runtime_.notices.append(f'「我的改动」这次没能套用（{type(exc).__name__}: {str(exc)[:120]}），改动本身没有动。')
    _RUNTIME = runtime_
    return runtime_


def reapply() -> None:
    """After 兔白 or the settings page changed the layer; installs a runtime when there is none yet."""
    current = _RUNTIME
    if current is None:
        app = QApplication.instance()
        if app is None:
            return
        current = install(app, safe=False)
    current.reapply()


__all__ = ['OverlayRuntime', 'ScriptAPI', 'StyleKeeper', 'install', 'is_ui_text', 'program_identity', 'reapply',
           'resolve_ui_text', 'runtime', 'safe_start_requested']
