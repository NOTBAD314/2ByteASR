"""Painted browser pictures for the 兔白助手 install guide (2026-11-26, draft A 票根逐張撕).

Each step shows a small drawing of the browser screen the user is about to see,
with a slowly pulsing ring and a pointer on the one control to press. The
labels follow the chosen browser (Edge keeps 开发人员模式 at the bottom of its
side bar, Chrome at the top right). Draft: ``tmp/helper-onboarding-drafts-20261126/``.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..i18n import tr
from .link_download_widgets import active_theme

LOGO_COLORS = {"Edge": ("#2fb4d8", "#1d7fd6"), "Chrome": ("#e44", "#22a35a"), "Brave": ("#ff7b3a", "#e8452c"),
               "Firefox": ("#ffcf4a", "#c53c86")}
# What each browser calls the things on its extensions page.
LABELS = {
    "Edge": dict(page="edge://extensions", title="扩展", dev="开发人员模式", load="加载解压缩的扩展",
                 side=("已安装的扩展", "键盘快捷方式"), dev_in_side=True),
    "Chrome": dict(page="chrome://extensions", title="扩展程序", dev="开发者模式", load="加载已解压的扩展程序",
                   side=("我的扩展程序", "键盘快捷键"), dev_in_side=False),
    "Brave": dict(page="brave://extensions", title="扩展程序", dev="开发者模式", load="加载已解压的扩展程序",
                  side=("我的扩展程序", "键盘快捷键"), dev_in_side=False),
    "Firefox": dict(page="about:debugging", title="临时扩展", dev="", load="临时载入附加组件…",
                    side=("设置", "此 Firefox"), dev_in_side=False),
}
PAPER, LINE, INK, MUTED, BLUE = "#ffffff", "#dddddd", "#2b2b2b", "#6b6b6b", "#0f6cbd"


class BrowserArt(QWidget):
    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        from .ui_zoom import set_size
        set_size(self, min_w=300, min_h=236)
        self.browser, self.scene, self.done = "Edge", "dev", False
        self.helper_path = str(root / "assets/browser-helper")
        self._icon = QPixmap(str(root / "assets/browser-helper/icon.png"))
        self._pulse = 0.0
        from ..design.motion_tokens import ATTENTION_PULSE, ATTENTION_REST_MS, easing_curve
        from ..design.ui_motion import reduced_motion
        self._still = reduced_motion()
        self._motion = QVariantAnimation(self)
        self._motion.setStartValue(0.0)
        self._motion.setEndValue(1.0)
        self._motion.setDuration(ATTENTION_PULSE.ms)
        self._motion.setEasingCurve(easing_curve(ATTENTION_PULSE))
        self._motion.valueChanged.connect(self._tick)
        # One pulse, a rest, the next pulse.
        self._rest = QTimer(self)
        self._rest.setSingleShot(True)
        self._rest.setInterval(ATTENTION_REST_MS)
        self._rest.timeout.connect(self._motion.start)
        self._motion.finished.connect(self._rest.start)
        self._pulsing = False

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(round(420 * self._f()), round(236 * self._f()))

    def set_scene(self, browser, scene, done):
        self.browser, self.scene, self.done = browser, scene, bool(done)
        self._sync_motion()
        self.update()

    def _tick(self, value):
        self._pulse = float(value)
        self.update()

    def _sync_motion(self):
        wanted = self.isVisible() and not self.done and not self._still and self.scene != "link"
        if wanted and not self._pulsing:
            self._pulsing = True
            self._motion.start()
        elif not wanted:
            self._pulsing = False
            self._rest.stop()
            self._motion.stop()
            self._pulse = 0.35

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_motion()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._pulsing = False
        self._rest.stop()
        self._motion.stop()

    # ------------------------------------------------------------- painting
    def _f(self):
        from .ui_zoom import effective_factor
        return effective_factor(self)

    def _font(self, size, bold=False):
        # A browser screen, so the system face rather than the app's display font.
        font = QFont(self.font())
        font.setFamilies(["Segoe UI", "Microsoft JhengHei UI", "Microsoft YaHei UI", self.font().family()])
        font.setPixelSize(max(1, round(size * self._f())))
        font.setBold(bold)
        return font

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        if self.scene == "link":
            self._paint_link(painter, rect)
            return
        getattr(self, "_paint_" + self.scene)(painter, rect)

    def _frame(self, p, rect, url, *, bunny=False, video=False):
        f = self._f()
        p.setPen(QPen(QColor(LINE), 1))
        p.setBrush(QColor(PAPER))
        p.drawRoundedRect(rect, 12 * f, 12 * f)
        bar = QRectF(rect.left(), rect.top(), rect.width(), 32 * f)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 12 * f, 12 * f)
        p.save()
        p.setClipPath(clip)
        p.fillRect(bar, QColor("#f3f3f3"))
        p.setPen(QPen(QColor(LINE), 1))
        p.drawLine(bar.bottomLeft(), bar.bottomRight())
        body = QRectF(rect.left(), bar.bottom(), rect.width(), rect.bottom() - bar.bottom())
        if video:
            gradient = QLinearGradient(body.topLeft(), body.bottomRight())
            gradient.setColorAt(0, QColor("#1e1b26"))
            gradient.setColorAt(.6, QColor("#3a2540"))
            gradient.setColorAt(1, QColor("#6b3a33"))
            p.fillRect(body, gradient)
        p.restore()
        first, second = LOGO_COLORS.get(self.browser, LOGO_COLORS["Edge"])
        logo = QRectF(bar.left() + 9 * f, bar.center().y() - 7 * f, 14 * f, 14 * f)
        gradient = QLinearGradient(logo.topLeft(), logo.bottomRight())
        gradient.setColorAt(0, QColor(first))
        gradient.setColorAt(1, QColor(second))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(gradient)
        p.drawEllipse(logo)
        icons_width = (52 if bunny else 28) * f
        pill = QRectF(logo.right() + 8 * f, bar.top() + 6 * f, bar.width() - (logo.right() - bar.left()) - 16 * f - icons_width, 20 * f)
        p.setPen(QPen(QColor(LINE), 1))
        p.setBrush(QColor(PAPER))
        p.drawRoundedRect(pill, 10 * f, 10 * f)
        p.setPen(QColor(MUTED))
        p.setFont(self._font(10.5))
        p.drawText(pill.adjusted(9 * f, 0, -6 * f, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, url)
        puzzle = QRectF(bar.right() - 26 * f, bar.top() + 6 * f, 20 * f, 20 * f)
        self._puzzle(p, puzzle)
        bunny_rect = QRectF(puzzle.left() - 24 * f, puzzle.top(), 20 * f, 20 * f)
        if bunny and not self._icon.isNull():
            p.drawPixmap(bunny_rect.adjusted(1, 1, -1, -1).toRect(), self._icon)
        return bar, body, puzzle, bunny_rect

    def _glyph(self, p, rect, name):
        import qtawesome
        size = max(8, round(min(rect.width(), rect.height())))
        p.drawPixmap(rect.toRect(), qtawesome.icon(name, color=MUTED).pixmap(size, size))

    def _puzzle(self, p, rect):
        f = self._f()
        self._glyph(p, rect.adjusted(3 * f, 3 * f, -3 * f, -3 * f), "fa5s.puzzle-piece")

    def _ring(self, p, rect, radius=8):
        f = self._f()
        accent = QColor(active_theme().accent)
        grow = (2 + 7 * self._pulse) * f
        accent.setAlphaF(max(0.0, 1 - self._pulse) * .95)
        p.setPen(QPen(accent, 2.4 * f))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(-grow, -grow, grow, grow), (radius + grow / f) * f, (radius + grow / f) * f)
        solid = QColor(active_theme().accent)
        p.setPen(QPen(solid, 1.6 * f))
        p.drawRoundedRect(rect.adjusted(-2 * f, -2 * f, 2 * f, 2 * f), radius * f, radius * f)

    def _pointer(self, p, at):
        f = self._f()
        tip = QPointF(at)
        shape = QPolygonF([tip, tip + QPointF(0, 15 * f), tip + QPointF(4 * f, 11 * f),
                           tip + QPointF(7.5 * f, 17 * f), tip + QPointF(10 * f, 16 * f),
                           tip + QPointF(6.5 * f, 10 * f), tip + QPointF(11.5 * f, 10 * f)])
        p.setPen(QPen(QColor("#222222"), 1.2 * f))
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(shape)

    def _toggle(self, p, rect, on):
        f = self._f()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(BLUE if on else "#c9c9c9"))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setBrush(QColor("#ffffff"))
        d = rect.height() - 5 * f
        x = rect.right() - d - 2.5 * f if on else rect.left() + 2.5 * f
        p.drawEllipse(QRectF(x, rect.top() + 2.5 * f, d, d))

    def _button(self, p, rect, text, *, filled=False):
        f = self._f()
        p.setPen(QPen(QColor(BLUE if filled else LINE), 1))
        p.setBrush(QColor(BLUE if filled else PAPER))
        p.drawRoundedRect(rect, 5 * f, 5 * f)
        p.setPen(QColor("#ffffff" if filled else INK))
        p.setFont(self._font(10.5))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _text_width(self, text, size):
        from PySide6.QtGui import QFontMetricsF
        return QFontMetricsF(self._font(size)).horizontalAdvance(text)

    def _extensions_page(self, p, rect, *, dev_on, hot):
        """Returns the rectangles of the developer switch and the load button."""
        f = self._f()
        labels = LABELS.get(self.browser, LABELS["Edge"])
        bar, body, *_ = self._frame(p, rect, labels["page"])
        side = QRectF(body.left(), body.top(), body.width() * .34, body.height())
        p.fillRect(side.adjusted(1, 0, 0, -1), QColor("#fafafa"))
        p.setPen(QPen(QColor(LINE), 1))
        p.drawLine(side.topRight(), side.bottomRight())
        p.setFont(self._font(10.5))
        for index, text in enumerate(labels["side"]):
            item = QRectF(side.left() + 7 * f, side.top() + (9 + index * 24) * f, side.width() - 14 * f, 20 * f)
            if index == 0:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#e8f0fb"))
                p.drawRoundedRect(item, 5 * f, 5 * f)
            p.setPen(QColor(BLUE if index == 0 else MUTED))
            p.drawText(item.adjusted(7 * f, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, tr(text))
        main = QRectF(side.right() + 10 * f, body.top() + 8 * f, body.right() - side.right() - 20 * f, body.height() - 16 * f)
        p.setPen(QColor(INK))
        p.setFont(self._font(13, True))
        p.drawText(QRectF(main.left(), main.top(), main.width(), 22 * f), Qt.AlignmentFlag.AlignVCenter, tr(labels["title"]))
        dev_rect = QRectF()
        if labels["dev"]:
            label = tr(labels["dev"])
            width = (34 + 6) * f + self._text_width(label, 10.5)
            if labels["dev_in_side"]:
                dev_rect = QRectF(side.left() + 8 * f, side.bottom() - 30 * f, min(width, side.width() - 14 * f), 20 * f)
            else:
                dev_rect = QRectF(main.right() - width, main.top() + 1 * f, width, 20 * f)
            self._toggle(p, QRectF(dev_rect.left(), dev_rect.top() + 2 * f, 30 * f, 16 * f), dev_on)
            p.setPen(QColor(INK))
            p.setFont(self._font(10.5))
            p.drawText(dev_rect.adjusted(36 * f, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, label)
        y = main.top() + 30 * f
        load_rect = QRectF()
        if dev_on or not labels["dev"]:
            load = tr(labels["load"])
            load_rect = QRectF(main.left(), y, self._text_width(load, 10.5) + 20 * f, 22 * f)
            self._button(p, load_rect, load)
            y += 32 * f
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ececec"))
            p.drawRoundedRect(QRectF(main.left(), y + 6 * f, main.width() * .6, 7 * f), 3 * f, 3 * f)
            y += 26 * f
        if self.scene == "load" and self.done:
            self._card(p, QRectF(main.left(), y, main.width(), 38 * f), tr("兔白助手"), tr("已启用"), helper=True)
            y += 46 * f
        self._card(p, QRectF(main.left(), y, main.width(), 38 * f), tr("其他扩展"), tr("已启用"))
        if hot == "dev" and not dev_rect.isNull():
            self._ring(p, dev_rect, 7)
            self._pointer(p, dev_rect.center() + QPointF(dev_rect.width() * .1, 4 * f))
        elif hot == "load" and not load_rect.isNull():
            self._ring(p, load_rect, 6)
            self._pointer(p, load_rect.center() + QPointF(load_rect.width() * .2, 4 * f))
        return dev_rect, load_rect

    def _card(self, p, rect, title, note, helper=False):
        f = self._f()
        p.setPen(QPen(QColor("#9bc3a8" if helper else LINE), 1))
        p.setBrush(QColor("#f2faf4" if helper else PAPER))
        p.drawRoundedRect(rect, 7 * f, 7 * f)
        icon = QRectF(rect.left() + 7 * f, rect.center().y() - 12 * f, 24 * f, 24 * f)
        if helper and not self._icon.isNull():
            p.drawPixmap(icon.toRect(), self._icon)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ececec"))
            p.drawRoundedRect(icon, 5 * f, 5 * f)
        p.setPen(QColor(INK))
        p.setFont(self._font(11, True))
        p.drawText(QRectF(icon.right() + 8 * f, rect.top() + 4 * f, rect.width() - 80 * f, 16 * f), Qt.AlignmentFlag.AlignVCenter, title)
        p.setPen(QColor(MUTED))
        p.setFont(self._font(9.5))
        p.drawText(QRectF(icon.right() + 8 * f, rect.top() + 19 * f, rect.width() - 80 * f, 14 * f), Qt.AlignmentFlag.AlignVCenter, note)
        self._toggle(p, QRectF(rect.right() - 38 * f, rect.center().y() - 8 * f, 30 * f, 16 * f), True)

    # -------------------------------------------------------------- scenes
    def _paint_dev(self, p, rect):
        self._extensions_page(p, rect, dev_on=self.done, hot="" if self.done else ("dev" if LABELS.get(self.browser, {}).get("dev") else "side"))
        if self.browser == "Firefox" and not self.done:
            f = self._f()
            item = QRectF(rect.left() + 9 * f, rect.top() + 32 * f + 33 * f, rect.width() * .34 - 18 * f, 20 * f)
            self._ring(p, item, 5)

    def _paint_load(self, p, rect):
        self._extensions_page(p, rect, dev_on=True, hot="" if self.done else "load")
        if self.done:
            return
        f = self._f()
        dialog = QRectF(rect.left() + rect.width() * .14, rect.top() + 104 * f, rect.width() * .72, 92 * f)
        p.setPen(QPen(QColor("#c8c8c8"), 1))
        p.setBrush(QColor(PAPER))
        p.drawRoundedRect(dialog, 7 * f, 7 * f)
        p.fillRect(QRectF(dialog.left() + 1, dialog.top() + 1, dialog.width() - 2, 22 * f), QColor("#f0f0f0"))
        p.setPen(QColor("#555555"))
        p.setFont(self._font(10))
        p.drawText(QRectF(dialog.left() + 8 * f, dialog.top(), dialog.width(), 23 * f), Qt.AlignmentFlag.AlignVCenter,
                   tr("选择 manifest.json") if self.browser == "Firefox" else tr("选择文件夹"))
        field = QRectF(dialog.left() + 8 * f, dialog.top() + 30 * f, dialog.width() - 16 * f, 22 * f)
        p.setPen(QPen(QColor("#c8c8c8"), 1))
        p.setBrush(QColor(PAPER))
        p.drawRoundedRect(field, 3 * f, 3 * f)
        p.setPen(QColor(INK))
        mono = QFont()
        mono.setFamilies(["Consolas", "Cascadia Mono", self.font().family()])
        mono.setPixelSize(max(1, round(10 * f)))
        p.setFont(mono)
        path = self.helper_path + ("\\manifest.json" if self.browser == "Firefox" else "")
        shown = p.fontMetrics().elidedText(path, Qt.TextElideMode.ElideLeft, int(field.width() - 12 * f))
        p.drawText(field.adjusted(6 * f, 0, -6 * f, 0), Qt.AlignmentFlag.AlignVCenter, shown)
        self._ring(p, field, 4)
        choose = QRectF(dialog.right() - 150 * f, dialog.bottom() - 30 * f, 80 * f, 22 * f)
        self._button(p, choose, tr("选择文件夹") if self.browser != "Firefox" else tr("打开"), filled=True)
        self._button(p, QRectF(choose.right() + 8 * f, choose.top(), 54 * f, 22 * f), tr("取消"))

    def _paint_pin(self, p, rect):
        f = self._f()
        bar, body, puzzle, bunny = self._frame(p, rect, "youtube.com/watch?v=…", bunny=self.done, video=True)
        if self.done:
            return
        menu = QRectF(rect.right() - 208 * f, bar.bottom() + 6 * f, 200 * f, 92 * f)
        p.setPen(QPen(QColor(LINE), 1))
        p.setBrush(QColor(PAPER))
        p.drawRoundedRect(menu, 9 * f, 9 * f)
        p.setPen(QColor(INK))
        p.setFont(self._font(11, True))
        p.drawText(QRectF(menu.left() + 10 * f, menu.top() + 6 * f, menu.width(), 18 * f), Qt.AlignmentFlag.AlignVCenter, tr("扩展"))
        rows = [(tr("兔白助手"), True), (tr("其他扩展"), False)]
        pin_rect = QRectF()
        for index, (text, helper) in enumerate(rows):
            row = QRectF(menu.left() + 6 * f, menu.top() + (28 + index * 30) * f, menu.width() - 12 * f, 26 * f)
            icon = QRectF(row.left() + 4 * f, row.center().y() - 9 * f, 18 * f, 18 * f)
            if helper and not self._icon.isNull():
                p.drawPixmap(icon.toRect(), self._icon)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#ececec"))
                p.drawRoundedRect(icon, 4 * f, 4 * f)
            p.setPen(QColor(INK))
            p.setFont(self._font(11))
            p.drawText(row.adjusted(30 * f, 0, -30 * f, 0), Qt.AlignmentFlag.AlignVCenter, text)
            pin = QRectF(row.right() - 22 * f, row.center().y() - 8 * f, 16 * f, 16 * f)
            self._glyph(p, pin.adjusted(2 * f, 2 * f, -2 * f, -2 * f), "fa5s.thumbtack")
            if helper:
                pin_rect = pin
        self._ring(p, puzzle.adjusted(1, 1, -1, -1), 6)
        self._ring(p, pin_rect, 5)
        self._pointer(p, pin_rect.center() + QPointF(2 * f, 3 * f))

    def _paint_try(self, p, rect):
        f = self._f()
        bar, body, puzzle, bunny = self._frame(p, rect, "youtube.com/watch?v=…", bunny=True, video=True)
        pop = QRectF(rect.right() - 186 * f, bar.bottom() + 6 * f, 178 * f, 84 * f)
        p.setPen(QPen(QColor("#e2d8c9"), 1))
        p.setBrush(QColor("#fff8f2"))
        p.drawRoundedRect(pop, 10 * f, 10 * f)
        chip = QRectF(pop.left() + 9 * f, pop.top() + 9 * f, 108 * f, 20 * f)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e1eee4"))
        p.drawRoundedRect(chip, 10 * f, 10 * f)
        p.setPen(QColor("#3d7a57"))
        p.setFont(self._font(10, True))
        p.drawText(chip, Qt.AlignmentFlag.AlignCenter, "● " + tr("已连接兔白"))
        send = QRectF(pop.left() + 9 * f, pop.bottom() - 32 * f, pop.width() - 18 * f, 24 * f)
        p.setBrush(QColor(active_theme().accent))
        p.drawRoundedRect(send, 8 * f, 8 * f)
        p.setPen(QColor("#ffffff"))
        p.setFont(self._font(11, True))
        p.drawText(send, Qt.AlignmentFlag.AlignCenter, tr("送到兔白"))
        if not self.done:
            self._ring(p, bunny.adjusted(1, 1, -1, -1), 6)
            self._pointer(p, bunny.center() + QPointF(2 * f, 4 * f))
            self._ring(p, chip, 10)

    def _paint_link(self, p, rect):
        t = active_theme()
        f = self._f()
        node_w, node_h, wire = 104 * f, 88 * f, min(130 * f, rect.width() - 2 * 104 * f - 20 * f)
        left = rect.center().x() - (node_w * 2 + wire) / 2
        top = rect.center().y() - node_h / 2
        nodes = [QRectF(left, top, node_w, node_h), QRectF(left + node_w + wire, top, node_w, node_h)]
        for index, node in enumerate(nodes):
            p.setPen(QPen(QColor(t.border), 1))
            p.setBrush(QColor(t.surface_elevated))
            p.drawRoundedRect(node, 18 * f, 18 * f)
            icon = QRectF(node.center().x() - 17 * f, node.top() + 14 * f, 34 * f, 34 * f)
            if index == 0 and not self._icon.isNull():
                p.drawPixmap(icon.toRect(), self._icon)
            else:
                first, second = LOGO_COLORS.get(self.browser, LOGO_COLORS["Edge"])
                gradient = QLinearGradient(icon.topLeft(), icon.bottomRight())
                gradient.setColorAt(0, QColor(first))
                gradient.setColorAt(1, QColor(second))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(gradient)
                p.drawEllipse(icon)
            p.setPen(QColor(t.text_secondary))
            p.setFont(self._font(12, True))
            p.drawText(QRectF(node.left(), icon.bottom() + 4 * f, node.width(), 20 * f), Qt.AlignmentFlag.AlignCenter,
                       tr("兔白") if index == 0 else self.browser)
        y = rect.center().y()
        ok = QColor(t.success)
        pen = QPen(ok if self.done else QColor(t.border_strong), 3 * f)
        if not self.done:
            pen.setDashPattern([2.5, 2])
        p.setPen(pen)
        p.drawLine(QPointF(nodes[0].right(), y), QPointF(nodes[1].left(), y))
        badge = QRectF(rect.center().x() - 14 * f, y - 14 * f, 28 * f, 28 * f)
        p.setPen(QPen(ok if self.done else QColor(t.border), 1))
        p.setBrush(ok if self.done else QColor(t.surface_elevated))
        p.drawEllipse(badge)
        p.setPen(QPen(QColor("#ffffff") if self.done else QColor(t.text_muted), 2 * f))
        if self.done:
            p.drawPolyline(QPolygonF([badge.center() + QPointF(-6 * f, 0), badge.center() + QPointF(-1.5 * f, 4.5 * f),
                                      badge.center() + QPointF(6 * f, -4 * f)]))
        else:
            p.drawLine(badge.center() + QPointF(-3 * f, -5 * f), badge.center() + QPointF(-3 * f, -1 * f))
            p.drawLine(badge.center() + QPointF(3 * f, -5 * f), badge.center() + QPointF(3 * f, -1 * f))
            p.drawRoundedRect(QRectF(badge.center().x() - 5 * f, badge.center().y() - 1 * f, 10 * f, 6 * f), 2 * f, 2 * f)
