"""兔白助手 window: a step-by-step install guide and the browsers it serves.

2026-11-26 (user picked draft A 票根逐张撕, ``tmp/helper-onboarding-drafts-20261126/``):
six small stubs along the top are the progress, a finished one is "torn off";
one big ticket shows a drawing of the browser screen on the left (the control to
press pulses) and what to do on the right, with 兔白 giving a tip (sad face when
the user says 我卡住了, a hop when a step ticks). Steps the window can see tick
by themselves: the desktop link (registry), the helper loaded into a Chromium
browser (its own settings file, read only) and the first contact (the helper
names its browser when it tests the connection). 我的浏览器 lists every browser
with what is set up, the helper version it runs and its last contact. When the
helper is listed in a store, ``STORE_PAGES`` can turn the load step into a store
button later.
"""
from __future__ import annotations

import subprocess
import time

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..design.elided_label import ElidedLabel
from ..design.studio_theme import apply_secondary_surface_theme
from ..i18n import tr
from ..runtime_paths import get_runtime_paths
from .browser_helper_art import LABELS, BrowserArt
from .browser_helper_setup import (SHARED_CHROMIUM_HOST, detect, helper_in_browser, helper_version, last_contact,
                                   registration, same_folder)
from .link_download_widgets import apply_link_sheet, button, named_label, pill, set_tone
from .link_ticket_widgets import EarsButton, Perforation

EXTENSION_PAGES = {"Chrome": "chrome://extensions/", "Edge": "edge://extensions/",
                   "Brave": "brave://extensions/", "Firefox": "about:debugging#/runtime/this-firefox"}
LOGOS = {"Chrome": "fa5b.chrome", "Edge": "fa5b.edge", "Brave": "fa5s.shield-alt", "Firefox": "fa5b.firefox-browser"}
ORDER = ("Edge", "Chrome", "Brave", "Firefox")
STEPS = ("browser", "link", "dev", "load", "pin", "try")
SHORT = {"browser": "选浏览器", "link": "连上兔白", "dev": "开发人员模式", "load": "载入兔白", "pin": "钉到工具栏", "try": "试一次"}
WHERE = {"Edge": "左边栏最下面", "Chrome": "右上角", "Brave": "右上角"}


def _when(stamp: float) -> str:
    moment = time.localtime(stamp)
    if time.strftime("%Y%m%d", moment) == time.strftime("%Y%m%d"):
        return tr("今天 {time}", time=time.strftime("%H:%M", moment))
    return time.strftime("%m/%d %H:%M", moment)


class StepStub(QPushButton):
    """One progress stub: its number (✓ once done) and the step's short name."""

    def __init__(self, index, key):
        super().__init__()
        self.setObjectName("linkStepStub")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.index, self.key = index, key
        self.set_state("")

    def set_state(self, state):
        # The app font has no ✓, so a finished stub carries a check icon instead of its number.
        import qtawesome
        from ..design.soft_qss import soft_tokens
        from .link_download_widgets import active_theme
        self.setText(("" if state == "done" else str(self.index + 1) + "  ") + tr(SHORT[self.key]))
        self.setIcon(qtawesome.icon("fa5s.check", color=soft_tokens(active_theme()).ok) if state == "done" else QIcon())
        self.setIconSize(QSize(12, 12))
        if self.property("state") != state:
            self.setProperty("state", state)
            self.style().unpolish(self)
            self.style().polish(self)


class HelperWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("browserHelperDialog")
        self.setWindowTitle(tr("兔白助手"))
        self.root = get_runtime_paths().install_root
        self.folder = self.root / "assets/browser-helper"
        self.paths = detect()
        self.browser = next((name for name in ORDER if name in self.paths), "")
        self.step = 0
        self._manual: dict[str, set[str]] = {}
        self._stuck = False
        self._signature = None
        self._advance = QTimer(self)
        self._advance.setSingleShot(True)
        self._advance.timeout.connect(self._auto_next)
        body = QWidget(self)
        body.setObjectName("linkRoot")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_guide())
        self.pages.addWidget(self._build_manage())
        layout.addWidget(self.pages, 1)
        apply_secondary_surface_theme(self)
        apply_link_sheet(body)
        # As tall as the content (2026-11-26, user: the guide looked empty).
        from .ui_zoom import set_size
        set_size(self, min_w=820)
        self.adjustSize()
        self._poll = QTimer(self)
        self._poll.setInterval(2000)
        self._poll.timeout.connect(self.refresh)
        self._plain_buttons()
        self._start()

    def _plain_buttons(self):
        """A dialog makes its first button the default one (painted as chosen,
        pressed by Enter); none of these buttons should be."""
        for widget in self.findChildren(QPushButton):
            widget.setAutoDefault(False)
            widget.setDefault(False)

    # ------------------------------------------------------------- status
    def status(self, name):
        try:
            linked = registration(self.root, name)
        except OSError:
            linked = False
        # Older Chromium helpers cannot identify their browser.
        contact = last_contact().get(name, 0.0)
        return dict(linked=linked, helper=helper_in_browser(self.root, name), contact=contact)

    def done_steps(self, name, status=None):
        if not name:
            return set()
        status = status or self.status(name)
        done = set(self._manual.get(name, set())) | {"browser"}
        if status["linked"]:
            done.add("link")
        if (status["helper"] or {}).get("loaded") or status["contact"]:
            done |= {"dev", "load"}
        if status["contact"]:
            done |= {"pin", "try"}
        return done

    def _start(self):
        """Open where the user left off: the first unfinished step of the first
        browser that still needs one, or 我的浏览器 when all of them are ready."""
        for name in [n for n in ORDER if n in self.paths]:
            missing = [key for key in STEPS if key not in self.done_steps(name)]
            if missing:
                self.browser = name
                self.step = STEPS.index(missing[0])
                self.show_tab("guide")
                return
        self.show_tab("manage" if self.paths else "guide")

    # -------------------------------------------------------------- header
    def _build_header(self):
        header = QFrame()
        header.setObjectName("linkHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(10)
        logo = QLabel()
        image = QPixmap(str(self.folder / "icon.png"))
        logo.setPixmap(image.scaled(30, 30, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        row.addWidget(logo)
        row.addWidget(named_label(tr("兔白助手"), "linkBrandTitle"), 1)
        self.tabs = {}
        for key, label in (("guide", "安装引导"), ("manage", "我的浏览器")):
            tab = button(tr(label), "linkNav")
            tab.setCheckable(True)
            tab.clicked.connect(lambda _=False, k=key: self.show_tab(k))
            self.tabs[key] = tab
            row.addWidget(tab)
        return header

    def show_tab(self, key):
        self.pages.setCurrentIndex(0 if key == "guide" else 1)
        for name, tab in self.tabs.items():
            tab.setChecked(name == key)
        # Keyboard focus on the chosen tab: a focused unchosen tab looks chosen too.
        (self.next if key == "guide" else self.tabs[key]).setFocus()
        self._signature = None
        self.refresh()

    # --------------------------------------------------------------- guide
    def _build_guide(self):
        page = QWidget()
        page.setObjectName("linkRoot")
        column = QVBoxLayout(page)
        column.setContentsMargins(20, 14, 20, 16)
        column.setSpacing(12)
        stubs = QHBoxLayout()
        stubs.setSpacing(6)
        self.stubs = [StepStub(index, key) for index, key in enumerate(STEPS)]
        for stub in self.stubs:
            stub.clicked.connect(lambda _=False, i=stub.index: self.go(i))
            stubs.addWidget(stub, 1)
        column.addLayout(stubs)

        ticket = QFrame()
        ticket.setObjectName("linkCard")
        ticket.setProperty("ticket", True)
        row = QHBoxLayout(ticket)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.art_stack = QStackedWidget()
        tiles = QWidget()
        from PySide6.QtWidgets import QGridLayout
        tile_row = QGridLayout(tiles)
        tile_row.setContentsMargins(0, 0, 0, 0)
        tile_row.setSpacing(10)
        self.tiles = {}
        from ..design.themed_icons import install_themed_icon
        for name in ORDER:
            tile = QPushButton(f"{name}\n{tr('已检测到') if name in self.paths else tr('未安装')}")
            tile.setObjectName("linkBrowserTile")
            tile.setCheckable(True)
            tile.setEnabled(name in self.paths)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            install_themed_icon(tile, LOGOS[name], "accent")
            tile.setProperty("big", True)
            tile.setIconSize(QSize(30, 30))
            tile.clicked.connect(lambda _=False, n=name: self.choose(n))
            tile_row.addWidget(tile, ORDER.index(name) // 2, ORDER.index(name) % 2)
            self.tiles[name] = tile
        self.art_stack.addWidget(tiles)
        self.art = BrowserArt(self.root)
        self.art_stack.addWidget(self.art)
        art_box = QVBoxLayout()
        art_box.setContentsMargins(16, 16, 12, 16)
        art_box.addWidget(self.art_stack)
        row.addLayout(art_box, 115)
        row.addWidget(Perforation(vertical=True))
        copy = QVBoxLayout()
        copy.setContentsMargins(6, 18, 18, 16)
        copy.setSpacing(9)
        self.kicker = named_label("", "linkStepKicker")
        copy.addWidget(self.kicker)
        self.step_title = named_label("", "linkTitle", wrap=True)
        copy.addWidget(self.step_title)
        self.say = named_label("", "linkMeta", wrap=True)
        copy.addWidget(self.say)
        self.path_row = QFrame()
        self.path_row.setObjectName("linkPathRow")
        path = QHBoxLayout(self.path_row)
        path.setContentsMargins(10, 5, 10, 5)
        self.path_label = ElidedLabel(str(self.folder), mode=Qt.TextElideMode.ElideLeft, minimum=60)
        self.path_label.setObjectName("linkPathText")
        path.addWidget(self.path_label, 1)
        copy.addWidget(self.path_row)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.primary = button("", "linkPrimary")
        self.primary.setProperty("small", True)
        self.secondary = button("", "linkGhost")
        self.secondary.setProperty("small", True)
        self.primary.clicked.connect(lambda: self._act("primary"))
        self.secondary.clicked.connect(lambda: self._act("secondary"))
        actions.addWidget(self.primary)
        actions.addWidget(self.secondary)
        actions.addStretch(1)
        copy.addLayout(actions)
        auto = QHBoxLayout()
        auto.setSpacing(6)
        self.auto_icon = QLabel()
        auto.addWidget(self.auto_icon, 0, Qt.AlignmentFlag.AlignTop)
        self.auto_line = named_label("", "linkHelperState", wrap=True)
        auto.addWidget(self.auto_line, 1)
        copy.addLayout(auto)
        self.error = named_label("", "linkHint", wrap=True)
        self.error.hide()
        copy.addWidget(self.error)
        copy.addStretch(1)
        self.tip = QFrame()
        self.tip.setObjectName("linkTipBox")
        tip = QHBoxLayout(self.tip)
        tip.setContentsMargins(6, 4, 12, 4)
        tip.setSpacing(8)
        from ..design.bunny_mascot import BunnyMascot
        self.mascot = BunnyMascot(height=52, motion="bob")
        tip.addWidget(self.mascot, 0, Qt.AlignmentFlag.AlignVCenter)
        from .ui_zoom import set_size
        set_size(self.tip, min_h=78)
        self.tip_text = named_label("", "linkHint", wrap=True)
        tip.addWidget(self.tip_text, 1)
        copy.addWidget(self.tip)
        row.addLayout(copy, 100)
        set_size(ticket, min_h=300)
        column.addWidget(ticket, 1)

        nav = QHBoxLayout()
        nav.setSpacing(10)
        self.back = button(tr("上一步"), "linkGhost", "fa5s.chevron-left", "secondary")
        self.back.setProperty("tall", True)
        self.back.clicked.connect(lambda: self.go(self.step - 1))
        nav.addWidget(self.back)
        self.stuck = button(tr("我卡住了"), "linkLink", "fa5s.question-circle", "accent")
        self.stuck.clicked.connect(self._toggle_stuck)
        nav.addWidget(self.stuck)
        nav.addStretch(1)
        self.next = EarsButton(tr("下一步"), "fa5s.chevron-right")
        self.next.clicked.connect(self._next)
        nav.addWidget(self.next, 0, Qt.AlignmentFlag.AlignBottom)
        column.addLayout(nav)
        return page

    def choose(self, name):
        self.browser = name
        self._manual.setdefault(name, set()).add("browser")
        self._stuck = False
        self._signature = None
        self.refresh()

    def go(self, index):
        self.step = max(0, min(len(STEPS) - 1, index))
        self._stuck = False
        self._advance.stop()
        self.error.clear()
        self._signature = None
        self.refresh()

    def _next(self):
        if not self.browser:
            return
        key = STEPS[self.step]
        if key in ("browser", "dev", "pin"):
            self._manual.setdefault(self.browser, set()).add(key)
        if self.step == len(STEPS) - 1:
            self.show_tab("manage")
            return
        self.go(self.step + 1)

    def _auto_next(self):
        if self.pages.currentIndex() == 0 and STEPS[self.step] in self.done_steps(self.browser) \
                and self.step < len(STEPS) - 1:
            self.go(self.step + 1)

    def _toggle_stuck(self):
        self._stuck = not self._stuck
        self._signature = None
        self.refresh()

    def _redraw(self):
        self._signature = None
        self.refresh()

    def _copy(self, text):
        QApplication.clipboard().setText(text)
        self.primary.setText(tr("已复制"))
        QTimer.singleShot(1600, self, self._redraw)

    def _open(self, address):
        if self.browser not in self.paths:
            return
        try:
            subprocess.Popen([str(self.paths[self.browser]), address],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.error.setText(tr("无法打开浏览器扩展管理。"))
            self._redraw()

    def _act(self, which):
        key = STEPS[self.step]
        self.error.clear()
        if key == "link" and which == "primary":
            try:
                registration(self.root, self.browser, change="install")
            except (ValueError, OSError) as exc:
                self.error.setText(tr(str(exc)))
            self._redraw()
        elif key == "dev":
            self._open(EXTENSION_PAGES[self.browser])
        elif key == "load" and which == "primary":
            self._copy(str(self.folder / "manifest.json") if self.browser == "Firefox" else str(self.folder))
        elif key == "load":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder)))
        elif key == "try":
            self._open("https://www.youtube.com/")

    def _copy_for(self, key):
        """(title, say, tip, stuck, primary, secondary, auto) for this step and browser."""
        name = self.browser or tr("浏览器")
        labels = LABELS.get(self.browser, LABELS["Edge"])
        firefox = self.browser == "Firefox"
        if key == "browser":
            return (tr("要装进哪个浏览器？"), tr("先选你平常看视频用的浏览器。兔白找到了这几个。"),
                    tr("之后想再装到别的浏览器，回到这里再走一次就好。"),
                    tr("这里没有你的浏览器的话，兔白助手暂时只支持 Edge、Chrome、Brave 和 Firefox。"), "", "", "")
        if key == "link":
            return (tr("让兔白和浏览器连得上"),
                    tr("按一下，兔白会在 Windows 帮 {browser} 登记一条通道。浏览器本身不会被改动。", browser=name),
                    tr("用安装版的话，这一步通常已经做好了，会直接打勾。"),
                    tr("按了没反应的话，先关掉 {browser}，再按一次「一键连上」。", browser=name),
                    tr("一键连上"), "", tr("按完会自动打勾"))
        if key == "dev" and firefox:
            return (tr("打开 Firefox 的调试页"), tr("按下面的按钮，Firefox 会打开调试页，左边选「此 Firefox」。"),
                    tr("Firefox 载入的助手只在这次开着时有效，关掉 Firefox 后要再载入一次。"),
                    tr("调试页没打开的话，在网址栏输入 about:debugging 再按 Enter。"), tr("打开调试页"), "", "")
        if key == "dev":
            switch = tr(labels["dev"])
            return (tr("在 {browser} 打开「{switch}」", browser=name, switch=switch),
                    tr("按下面的按钮，{browser} 会打开扩展页。「{switch}」开关在{where}，把它打开。", browser=name,
                       switch=switch, where=tr(WHERE.get(self.browser, "右上角"))),
                    tr("这个开关只是让浏览器接受从文件夹载入的扩展，平常浏览不受影响。"),
                    tr("扩展页没打开的话，在 {browser} 的网址栏输入 {page} 再按 Enter。", browser=name, page=labels["page"]),
                    tr("打开扩展页"), "", "")
        if key == "load" and firefox:
            return (tr("载入兔白助手"), tr("按「{load}」，选文件夹里的 manifest.json。", load=tr(labels["load"])),
                    tr("关掉 Firefox 后要再载入一次。"), tr("在选择窗口最上面贴上路径，再按「打开」。"),
                    tr("复制 manifest.json 路径"), tr("打开文件夹"), "")
        if key == "load":
            return (tr("把兔白助手载入进来"),
                    tr("按「{load}」，在跳出的窗口最上面贴上文件夹路径，再按「选择文件夹」。", load=tr(labels["load"])),
                    tr("也可以直接把文件夹拖进扩展页。"),
                    tr("看不到「{load}」按钮的话，先确认「{switch}」已经打开。也可以按「打开文件夹」，把整个文件夹拖进扩展页。",
                       load=tr(labels["load"]), switch=tr(labels["dev"])),
                    tr("复制文件夹路径"), tr("打开文件夹"), tr("兔白一出现在清单里就会自动打勾"))
        if key == "pin":
            return (tr("把兔白钉在工具栏"), tr("按网址栏右边的拼图图示，在兔白助手旁边按一下图钉。之后兔白就一直待在右上角。"),
                    tr("不钉也能用，只是每次要先按拼图。"), tr("拼图里没有兔白助手的话，回到上一步看看它有没有载入。"),
                    "", "", "")
        return (tr("最后，试一次"),
                tr("打开任何一个 YouTube 或 Bilibili 视频页，按右上角的兔白。看到「已连接兔白」就完成了。"),
                tr("看到「无法连接」的话，回到第 2 步再按一次「一键连上」。"),
                tr("兔白助手显示「无法连接」的话，回到第 2 步按「一键连上」，再关掉浏览器重开。"),
                tr("打开 YouTube 试试"), "", tr("兔白收到第一次连接就会自动打勾"))

    def _refresh_guide(self, done):
        key = STEPS[self.step]
        signature = ("guide", self.browser, self.step, tuple(sorted(done)), self._stuck, self.error.text())
        if signature == self._signature:
            return
        previous = self._signature
        just_done = bool(previous and previous[:3] == signature[:3] and key not in previous[3] and key in done)
        self._signature = signature
        for stub in self.stubs:
            stub.set_state("now" if stub.index == self.step else "done" if stub.key in done else "")
        for name, tile in self.tiles.items():
            tile.setChecked(name == self.browser)
        self.art_stack.setCurrentIndex(0 if key == "browser" else 1)
        if key != "browser":
            self.art.set_scene(self.browser or "Edge", key, key in done)
        title, say, tip, stuck, primary, secondary, auto = self._copy_for(key)
        self.kicker.setText(tr("第 {step} 步，共 {count} 步", step=self.step + 1, count=len(STEPS)))
        self.step_title.setText(title)
        self.say.setText(say)
        self.path_row.setVisible(key == "load")
        if key == "load":
            self.path_label.setText(str(self.folder / "manifest.json") if self.browser == "Firefox" else str(self.folder))
        for widget, text in ((self.primary, primary), (self.secondary, secondary)):
            widget.setText(text)
            widget.setVisible(bool(text) and not (key == "link" and key in done))
        self.auto_line.setText((tr("完成") if key in done else auto) if auto else "")
        set_tone(self.auto_line, "ok" if key in done else "")
        self.auto_line.setVisible(bool(self.auto_line.text()))
        self.auto_icon.setVisible(bool(self.auto_line.text()))
        if self.auto_line.text():
            import qtawesome
            from ..design.soft_qss import soft_tokens
            from .link_download_widgets import active_theme
            theme = active_theme()
            self.auto_icon.setPixmap(qtawesome.icon("fa5s.check-circle" if key in done else "fa5s.hourglass-half",
                color=soft_tokens(theme).ok if key in done else theme.text_muted).pixmap(13, 13))
        self.error.setVisible(bool(self.error.text()))
        self.mascot.set_mood("sad" if self._stuck else "idle")
        if self.tip.property("stuck") != self._stuck:
            self.tip.setProperty("stuck", self._stuck)
            self.tip.style().unpolish(self.tip)
            self.tip.style().polish(self.tip)
        self.tip_text.setText(stuck if self._stuck else tip)
        self.stuck.setText(tr("回到提示") if self._stuck else tr("我卡住了"))
        self.back.setEnabled(self.step > 0)
        last = self.step == len(STEPS) - 1
        self.next.setText(tr("完成") if last else tr("下一步"))
        from ..design.themed_icons import install_themed_icon
        install_themed_icon(self.next, "fa5s.check" if last else "fa5s.chevron-right", "on_accent")
        self.next.setEnabled(bool(self.browser))
        if just_done:
            self.mascot.hop()
            if key in ("link", "load"):
                from ..design.motion_tokens import PAGE_IN
                self._advance.start(PAGE_IN.ms * 2)   # let the tick be seen, then move on

    # -------------------------------------------------------------- manage
    def _build_manage(self):
        page = QWidget()
        page.setObjectName("linkRoot")
        column = QVBoxLayout(page)
        column.setContentsMargins(20, 16, 20, 16)
        column.setSpacing(8)
        self.update_bar = QFrame()
        self.update_bar.setObjectName("linkUpdateBar")
        bar = QHBoxLayout(self.update_bar)
        bar.setContentsMargins(12, 8, 8, 8)
        self.update_text = named_label("", "linkUpdateText", wrap=True)
        bar.addWidget(self.update_text, 1)
        self.update_button = button(tr("打开扩展页"), "linkPrimary")
        self.update_button.setProperty("small", True)
        self.update_button.clicked.connect(lambda: self._open_for(self._stale, EXTENSION_PAGES.get(self._stale, "")))
        bar.addWidget(self.update_button)
        self.update_bar.hide()
        self._stale = ""
        column.addWidget(self.update_bar)
        self.rows_host = QVBoxLayout()
        self.rows_host.setSpacing(8)
        column.addLayout(self.rows_host)
        column.addStretch(1)
        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addWidget(named_label(tr("插件文件夹"), "linkHint"))
        folder = ElidedLabel(str(self.folder), mode=Qt.TextElideMode.ElideLeft, minimum=80)
        folder.setObjectName("linkPathText")
        foot.addWidget(folder, 1)
        copy = button(tr("复制"), "linkLink", "fa5s.copy", "accent")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(str(self.folder)))
        foot.addWidget(copy)
        opener = button(tr("打开文件夹"), "linkLink", "fa5s.folder-open", "accent")
        opener.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder))))
        foot.addWidget(opener)
        column.addLayout(foot)
        return page

    def _row(self, name, status):
        frame = QFrame()
        frame.setObjectName("linkTicketRow")
        frame.setProperty("absent", name not in self.paths)
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 10, 12, 10)
        row.setSpacing(14)
        title = QLabel()
        import qtawesome
        from .link_download_widgets import active_theme
        title.setPixmap(qtawesome.icon(LOGOS[name], color=active_theme().accent_text).pixmap(22, 22))
        row.addWidget(title)
        label = named_label(name, "linkRowTitle")
        from .ui_zoom import set_size
        set_size(label, min_w=90)
        row.addWidget(label)
        pills = QHBoxLayout()
        pills.setSpacing(6)
        actions = []
        if name not in self.paths:
            pills.addWidget(named_label(tr("这台电脑没有装"), "linkHint"))
        else:
            helper = status["helper"] or {}
            done = self.done_steps(name, status)
            if status["linked"] and status["contact"]:
                pills.addWidget(pill(tr("已连接"), "ok"))
            elif status["linked"]:
                pills.addWidget(pill(tr("通道已设定"), "ok"))
            else:
                pills.addWidget(pill(tr("还没连上兔白"), "warn"))
            if helper.get("loaded"):
                version = helper.get("version") or ""
                pills.addWidget(pill(tr("插件 {version}", version=version) if version else tr("插件已载入")))
                if helper.get("path") and not same_folder(self.root, helper["path"]):
                    pills.addWidget(pill(tr("载入的是另一个文件夹"), "warn"))
                if not helper.get("enabled", True):
                    pills.addWidget(pill(tr("插件已停用"), "warn"))
            elif status["helper"] is not None and not status["contact"]:
                pills.addWidget(pill(tr("还没载入插件"), "warn"))
            if status["contact"]:
                pills.addWidget(named_label(tr("上次连接 {when}", when=_when(status["contact"])), "linkHint"))
            if name in SHARED_CHROMIUM_HOST:
                frame.setToolTip(tr("Chrome 和 Brave 共用本机通信，设定或解除会同时作用于两者。"))
            if set(STEPS) <= done:
                reload = button(tr("打开扩展页"), "linkGhost", "fa5s.external-link-alt", "secondary")
                reload.setProperty("small", True)
                reload.clicked.connect(lambda _=False, n=name: self._open_for(n, EXTENSION_PAGES[n]))
                unlink = button(tr("解除连接"), "linkLink")
                unlink.clicked.connect(lambda _=False, n=name: self._unlink(n))
                actions = [reload, unlink]
            else:
                started = bool(done - {"browser"})
                go = button(tr("继续引导") if started else tr("开始引导"), "linkPrimary" if started else "linkGhost",
                            "fa5s.chevron-right", "on_accent" if started else "secondary")
                go.setProperty("small", True)
                go.clicked.connect(lambda _=False, n=name: self._guide_for(n))
                actions = [go]
        pills.addStretch(1)
        row.addLayout(pills, 1)
        for action in actions:
            row.addWidget(action)
        return frame

    def _open_for(self, name, address):
        if name and address:
            self.browser = name
            self._open(address)

    def _guide_for(self, name):
        self.browser = name
        done = self.done_steps(name)
        self.step = next((STEPS.index(key) for key in STEPS if key not in done), 0)
        self.show_tab("guide")

    def _unlink(self, name):
        try:
            registration(self.root, name, change="remove")
        except OSError:
            pass
        self._redraw()

    def _refresh_manage(self):
        statuses = {name: self.status(name) for name in ORDER}
        signature = ("manage", repr(sorted((name, s["linked"], repr(s["helper"]), int(s["contact"] // 60))
                                           for name, s in statuses.items())))
        if signature == self._signature:
            return
        self._signature = signature
        while self.rows_host.count():
            item = self.rows_host.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for name in ORDER:
            self.rows_host.addWidget(self._row(name, statuses[name]))
        self._plain_buttons()
        current = helper_version(self.root)
        stale = [name for name, s in statuses.items()
                 if (s["helper"] or {}).get("version") and current and s["helper"]["version"] != current]
        self._stale = stale[0] if stale else ""
        self.update_bar.setVisible(bool(stale))
        if stale:
            self.update_text.setText(tr("兔白更新了插件（{old} → {new}）。请到 {browser} 的扩展页，在兔白助手上按「重新载入」。",
                                        old=statuses[self._stale]["helper"]["version"], new=current, browser=self._stale))

    # ------------------------------------------------------------- refresh
    def refresh(self):
        if self.pages.currentIndex() == 0:
            self._refresh_guide(self.done_steps(self.browser))
        else:
            self._refresh_manage()

    def showEvent(self, event):
        super().showEvent(event)
        self._poll.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._poll.stop()


def show_wizard(parent):
    window = HelperWindow(parent)
    window.exec()
