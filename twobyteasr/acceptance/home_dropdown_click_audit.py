"""Real-window check: a click on a home-page dropdown row chooses it (2026-10-28).

Mac user: every dropdown opened and highlighted its rows, but a click chose
nothing. The list's outside-click check treated the press on a row as outside
and hid the list before the release. On Windows the system then sends the
release to the main window and Qt still hands it to the row that got the
press, so the choice went through; on macOS it did not reach the list.

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=home-dropdown-click`` (isolated
data; ``scripts/verify_home_dropdown_click_headed.py`` on Windows,
``scripts/verify_home_dropdown_click_macos.py`` on macOS; source or frozen).

Windows: native mouse messages through the Windows platform plugin, sent where
the system would deliver them (the capture window, else the window under the
point); each row is chosen once that way and once with every message sent to
the window under the point. macOS: Quartz mouse events posted to the window
server, which routes them like a real mouse. The check that tells the old code
from the new is "the list stays open while the button is down".
``TWOBYTEASR_DROPDOWN_OLD_CHECK=1`` puts the old outside-click check back, to
show on the same build what it did.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

FAKE_KEY = "sk-audit-not-a-real-key-0001"
OLD_CHECK_ENV = "TWOBYTEASR_DROPDOWN_OLD_CHECK"


def _old_event_filter(self, obj, event):
    """``_ComboPopup.eventFilter`` before 2026-10-28 (3a1962f5): compares the
    list's screen rectangle with a point in its own coordinates."""
    from PySide6.QtCore import QEvent, QRect
    from PySide6.QtWidgets import QFrame
    if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
        try:
            gp = event.globalPosition().toPoint()
        except Exception:
            gp = event.globalPos()
        popup_rect = self.geometry()
        if not popup_rect.contains(self.mapFromGlobal(gp)):
            try:
                cgeo = self.combo.geometry()
                combo_global = QRect(self.combo.mapToGlobal(cgeo.topLeft()), cgeo.size())
            except Exception:
                combo_global = QRect()
            if combo_global.contains(gp):
                try:
                    self.combo._suppress_show_until_click_release = True
                except Exception:
                    pass
            self.hide()
            return False
    return QFrame.eventFilter(self, obj, event)


class _WindowsMouse:
    """Native WM_* mouse messages, routed by capture or by the point."""
    routings = ('windows', 'pointer')

    def __init__(self, window):
        import ctypes
        from ctypes import wintypes as W
        self.ctypes, self.W, self.window = ctypes, W, window
        user = self.user = ctypes.windll.user32
        user.WindowFromPoint.argtypes = [W.POINT]
        user.WindowFromPoint.restype = W.HWND
        user.GetCapture.restype = W.HWND
        user.ClientToScreen.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
        user.ScreenToClient.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
        user.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        user.SendMessageW.restype = ctypes.c_ssize_t

    def info(self):
        return dict(platform='windows')

    def _screen_point(self, widget, local):
        """Device-pixel screen point of ``local`` in ``widget``."""
        top = widget.window()
        corner = widget.mapTo(top, local)
        dpr = top.devicePixelRatioF()
        spot = self.W.POINT(round(corner.x() * dpr), round(corner.y() * dpr))
        self.user.ClientToScreen(self.W.HWND(int(top.winId())), self.ctypes.byref(spot))
        return spot

    def _kind(self, hwnd, combo):
        if not hwnd:
            return 'none'
        if hwnd in (int(self.window.winId()), int(self.window.window().winId())):
            return 'main'
        if hwnd == int(combo._popup.winId()):
            return 'popup'
        return f'other:{hwnd}'

    def _send(self, spot, message, buttons, routing):
        """'windows': the capture window, else the window under the point;
        'pointer': the shown window under the point."""
        user, W = self.user, self.W
        hwnd = int(user.GetCapture() or 0) if routing == 'windows' else 0
        hwnd = hwnd or int(user.WindowFromPoint(spot) or 0)
        local = W.POINT(spot.x, spot.y)
        user.ScreenToClient(W.HWND(hwnd), self.ctypes.byref(local))
        lparam = ((local.y & 0xFFFF) << 16) | (local.x & 0xFFFF)
        user.SendMessageW(W.HWND(hwnd), message, buttons, lparam)
        return hwnd

    def click(self, widget, local, routing, combo, settle, between=None):
        spot = self._screen_point(widget, local)
        self._send(spot, 0x0200, 0, routing)            # WM_MOUSEMOVE
        settle(80)
        down = self._send(spot, 0x0201, 0x0001, routing)  # WM_LBUTTONDOWN, MK_LBUTTON
        settle(120)
        state = between() if between else None
        capture = int(self.user.GetCapture() or 0)
        up = self._send(spot, 0x0202, 0, routing)       # WM_LBUTTONUP
        settle(300)
        return dict(press_to=self._kind(down, combo), capture_after_press=self._kind(capture, combo),
                    release_to=self._kind(up, combo), between=state)


class _MacMouse:
    """Quartz mouse events posted to the window server (HID level)."""
    routings = ('system',)

    def __init__(self, window):
        import ctypes

        class CGPoint(ctypes.Structure):
            _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double)]

        self.ctypes, self.CGPoint, self.window = ctypes, CGPoint, window
        quartz = self.quartz = ctypes.cdll.LoadLibrary(
            '/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
        self.cf = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        quartz.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
        quartz.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        quartz.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
        quartz.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]

    def info(self):
        detail = dict(platform='darwin')
        for name in ('AXIsProcessTrusted', 'CGPreflightPostEventAccess'):
            try:
                function = getattr(self.quartz, name)
                function.restype = self.ctypes.c_bool
                detail[name] = bool(function())
            except Exception as exc:  # noqa: BLE001
                detail[name] = repr(exc)
        return detail

    def _post(self, kind, point):
        event = self.quartz.CGEventCreateMouseEvent(None, kind, point, 0)   # left button
        if kind in (1, 2):
            self.quartz.CGEventSetIntegerValueField(event, 1, 1)          # kCGMouseEventClickState
        self.quartz.CGEventPost(0, event)                                   # kCGHIDEventTap
        self.cf.CFRelease(event)

    def click(self, widget, local, routing, combo, settle, between=None):
        spot = widget.mapToGlobal(local)
        point = self.CGPoint(float(spot.x()), float(spot.y()))
        self._post(5, point)       # kCGEventMouseMoved
        settle(120)
        self._post(1, point)       # kCGEventLeftMouseDown
        settle(200)
        state = between() if between else None
        self._post(2, point)       # kCGEventLeftMouseUp
        settle(400)
        return dict(point=[spot.x(), spot.y()], between=state)


def start(window, output: Path):
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    app = QApplication.instance()
    output.mkdir(parents=True, exist_ok=True)
    old_check = os.environ.get(OLD_CHECK_ENV) == '1'
    result = dict(checks=[], records=[], errors=[], passed=False, pid=os.getpid(), old_check=old_check,
                  executable=os.path.realpath(sys.executable))
    mouse = _MacMouse(window) if sys.platform == 'darwin' else _WindowsMouse(window)
    result['mouse'] = mouse.info()

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))

    def settle(ms=300):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def grab(widget, name):
        try:
            widget.grab().save(str(output / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'grab {name}: {exc!r}')

    def click(widget, local, routing, combo, between=None):
        return mouse.click(widget, local, routing, combo, settle, between)

    def close_strays():
        popup = QApplication.activePopupWidget()
        if popup is not None:
            popup.close()
        for top in QApplication.topLevelWidgets():
            if top is not window and top.isVisible() and isinstance(top, (QDialog, QMessageBox)):
                top.reject() if isinstance(top, QDialog) else top.close()
        settle(200)

    def open_list(combo, routing):
        info = click(combo, combo.rect().center(), routing, combo)
        settle(400)   # the open motion
        return combo._popup.isVisible(), info

    def choose(combo, label, routing, row):
        before = combo.currentIndex()
        opened, opening = open_list(combo, routing)
        popup = combo._popup
        if opened:
            grab(popup, f'{label}_{routing}_open')
        info = {}
        if opened:
            listing = popup.listing
            info = click(listing.viewport(), listing.visualItemRect(listing.item(row)).center(), routing, combo,
                         between=popup.isVisible)
        record = dict(combo=label, routing=routing, opened=opened, opening=opening, before=before,
                      wanted=row, after=combo.currentIndex(), text=combo.currentText(),
                      closed=not popup.isVisible(), **info)
        result['records'].append(record)
        close_strays()
        return record

    def unlock_subtitle_output(output_combo):
        """字幕显示 is locked until the AI is connected (the user's is): a fake
        key and a remembered test, no network (as in home_widgets_audit). Where
        the key store is not usable (macOS test root: no Keychain), the gate
        itself is reported ready for this run."""
        from ..providers import ai_connection_record
        try:
            from ..providers.llm_config import save_api_key_for
            values = window._primary_ai_editor().values()
            save_api_key_for(values['provider'], values['base_url'], FAKE_KEY)
            for editor in (window.polish_editor, window.group_editor):
                editor.refresh_secret_status()
            ai_connection_record.remember(window.legacy.RUNTIME_SETTINGS, 'polish', True)
            window._apply_ai_feature_gate()
            settle(600)
        except Exception as exc:  # noqa: BLE001
            result['key_store_error'] = repr(exc)
        if not output_combo.isEnabled():
            ai_connection_record.service_gate = lambda *args, **kwargs: 'ready'
            result['gate_forced_ready'] = True
            window._apply_ai_feature_gate()
            settle(600)
        return output_combo.isEnabled()

    def run_all():
        try:
            if old_check:
                from ..design import main_ui_popup
                main_ui_popup._ComboPopup.eventFilter = _old_event_filter
            from ..design.theme_manager import apply_theme
            apply_theme(os.environ.get('TWOBYTEASR_HOME_AI_THEME', 'grape'), app)
            for dialog in [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]:
                QDialog.done(dialog, 0)
            window.showNormal()
            if window.pages.currentWidget() is not window.__dict__.get('settings_scroll'):
                window._return_to_settings()   # a startup project may have opened Studio
            area = window.screen().availableGeometry()
            window.resize(min(1500, area.width()), min(980, area.height()))
            window.move(area.topLeft())
            window.raise_()
            window.activateWindow()
            settle(1500)
            punctuation, output_combo, language = (window.subtitle_punctuation, window.subtitle_output,
                                                   window.recognition_language)
            check('字幕显示 is unlocked (AI connected with a fake key)', unlock_subtitle_output(output_combo),
                  dict(key_store_error=result.get('key_store_error'), forced=result.get('gate_forced_ready')))
            scroll = window.__dict__.get('settings_scroll')
            targets = {}
            for name, combo in (('punctuation', punctuation), ('output', output_combo), ('language', language)):
                if scroll is not None and hasattr(scroll, 'ensureWidgetVisible'):
                    scroll.ensureWidgetVisible(combo)
                settle(300)
                corner = combo.mapToGlobal(QPoint(0, 0))
                targets[name] = [corner.x(), corner.y(), combo.width(), combo.height(),
                                 area.contains(combo.mapToGlobal(combo.rect().center()))]
            check('the dropdowns are on the screen', all(t[4] for t in targets.values()),
                  dict(targets=targets, screen=[area.x(), area.y(), area.width(), area.height()]))
            grab(window, 'home_before')
            if sys.platform == 'darwin':
                # The first click may only bring the app forward: spend it on the arrow.
                arrow = window.__dict__.get('home_language_arrow')
                if arrow is not None:
                    click(arrow, arrow.rect().center(), 'system', punctuation)
            # 标点 and 字幕显示: each row chosen with every routing.
            for combo, label in ((punctuation, 'punctuation'), (output_combo, 'output')):
                first = combo.currentIndex()
                other = 1 if first != 1 else 0
                for routing in mouse.routings:
                    for row in (other, first):
                        record = choose(combo, label, routing, row)
                        check(f'{label} ({routing} routing): the list opens', record['opened'], record.get('opening'))
                        check(f'{label} ({routing} routing): the list stays open while the button is down',
                              record.get('between') is True, record)
                        check(f'{label} ({routing} routing): the click chooses row {row} and closes the list',
                              record['after'] == row and record['closed'], record)
                grab(window, f'home_after_{label}')
            routing = mouse.routings[0]
            # A press outside closes the list without choosing.
            before = punctuation.currentIndex()
            opened, _ = open_list(punctuation, routing)
            arrow = window.__dict__.get('home_language_arrow')
            target, spot = (arrow, arrow.rect().center()) if arrow is not None else (
                window, QPoint(8, window.height() - 8))
            info = click(target, spot, routing, punctuation)
            check('outside press closes the list without choosing',
                  opened and not punctuation._popup.isVisible() and punctuation.currentIndex() == before, info)
            close_strays()
            # A click on the box of an open list closes it (no reopening).
            opened, _ = open_list(punctuation, routing)
            info = click(punctuation, punctuation.rect().center(), routing, punctuation)
            settle(300)
            check('a click on the box of its open list closes it',
                  opened and not punctuation._popup.isVisible(), info)
            close_strays()
            # A long list: a press on the scroll bar pages and keeps it open.
            opened, _ = open_list(language, routing)
            bar = language._popup.listing.verticalScrollBar()
            before_value = bar.value()
            if opened and bar.isVisible():
                info = click(bar, QPoint(bar.width() // 2, bar.height() - 12), routing, language,
                             between=language._popup.isVisible)
                check('scroll bar press keeps the long list open and scrolls it',
                      language._popup.isVisible() and bar.value() > before_value,
                      dict(info, value=bar.value(), before=before_value))
                grab(language._popup, 'language_scrolled')
            else:
                check('scroll bar press keeps the long list open and scrolls it', False,
                      dict(opened=opened, bar=bar.isVisible()))
            close_strays()
        except Exception:  # noqa: BLE001
            result['errors'].append(traceback.format_exc())
        result['passed'] = bool(result['checks']) and all(c['passed'] for c in result['checks']) and not result['errors']
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
        window.close()
        QTimer.singleShot(500, app.quit)

    def shutdown():
        result['gui_shutdown'] = True
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(2500, run_all)
