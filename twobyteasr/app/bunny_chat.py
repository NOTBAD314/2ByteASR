"""「问问兔白」: the keychain 兔白 answers in a little chat card (2026-11-14).

User (2026-11-14): 「需要帮忙吗」 gets its own 「问问兔白」 entry. 兔白 comes out at the
window's lower right, types her answers one character at a time with the tutorial's babble
voice, can point at the place she is talking about (an outline that pulses on it) and offers
「带我去」 to open it — only when the user presses it. An AI plays her (persona and world book
in ``bunny_persona`` / ``bunny_lore``), using the text AI the user set up for 字幕校对; without
one she still points at features by their words.

Layout (2026-11-14, user picked B and wants A as a switch): by default a big round dialog box
(B) where she says one sentence at a time, the 「兔白」 name tag tilted on its edge and a bouncing
▼ when there is more (a click or Enter goes on); or a chat thread (A) with one bubble per line
that scrolls back. 兔白 stands beside either, never over the words; her lines use 猫啃什锦黑
and wrap evenly (``balanced_width``). On Windows the main window's pages are a native child
window that would cover a child overlay, so the card and the outline are frameless tool
windows above the main window (like the tutorial), following it when it moves.
"""
from __future__ import annotations

import json
import math
import sys
import time

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QThread, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..i18n import tr
from . import bunny_lore, bunny_persona
from .tour_mascot import MarkedLabel, MascotVoice, Typewriter, marker_colors

AI_STAGE = 'polish'          # the 字幕校对 service, the one key AI 断句 / 校对 / 翻译 share
HISTORY_TURNS = 6            # earlier question/answer pairs sent along
NOTICE_KEY = 'bunny_chat_round4_notice'
MOOD_FACE = {'happy': 'happy', 'excited': 'happy', 'teasing': 'happy', 'surprised': 'happy',
             'sorry': 'sad', 'shy': 'idle', 'thinking': 'idle', 'comfort': 'idle'}
HOPS = {'excited', 'surprised'}
# 2026-11-14: the reaction a mood brings when the AI picks none (``act`` wins); plain happy needs none.
MOOD_ACT = {'excited': 'excited', 'surprised': 'startled', 'sorry': 'sorry', 'shy': 'shy',
            'thinking': 'wonder', 'comfort': 'bloom', 'teasing': 'smirk'}
# D (2026-11-14): the expression layers a mood asks for once the user has drawn them. A layer in
# rig.json whose role is "<role>:<name>" (e.g. "eyes:cry", "mouthClosed:cat") is drawn instead of
# the plain one; until it exists nothing changes.
MOOD_EXPRESSION = {'sorry': {'eyes': 'cry', 'blink': 'cry'}, 'excited': {'eyes': 'star'},
                   'surprised': {'eyes': 'round'}, 'teasing': {'mouthClosed': 'cat'}, 'shy': {'mouthClosed': 'pout'},
                   'comfort': {'eyes': 'smile'}}
IDLE_DOZE_S = 75.0           # no talk, typing or pointer nearby for this long: she dozes off
BUBBLE_MIN_HEIGHT = 34       # a chat bubble's two 16 px corners on one side need this much height
POKES_FOR_HMPH = 4           # this many pokes within POKE_WINDOW_S and she turns away
POKE_WINDOW_S = 5.0
LATE_NIGHT_KEY = 'bunny_late_night'


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def _rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f'rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})'


def runtime_settings(window) -> dict | None:
    import copy
    legacy = getattr(window, 'legacy', None)
    settings = getattr(legacy, 'RUNTIME_SETTINGS', None)
    return copy.deepcopy(settings) if isinstance(settings, dict) else None


def ai_readiness(settings) -> tuple[bool, str]:
    """(ready, service label) without any request, as the diagnosis dialog decides it."""
    from .run_diagnosis_dialog import AiAnalysisPanel
    try:
        ready, service, _gate = AiAnalysisPanel._readiness(settings)
    except Exception:  # noqa: BLE001 - an unreadable configuration counts as not set up
        return False, ''
    return bool(ready), str(service or '')


def current_page(window) -> str:
    pages = getattr(window, 'pages', None)
    current = pages.currentWidget() if pages is not None else None
    if current is None:
        return ''
    built = getattr(window, 'built_page', lambda _name: None)
    known = ((getattr(window, 'settings_scroll', None), '首页'), (pages.widget(1), '识别进度'),
             (pages.widget(2), '识别完成的结果页'), (getattr(window, 'term_library_page', None), '术语库'),
             (built('workshop'), '模型工坊'), (built('history'), '识别记录'), (built('studio'), '字幕工作台'))
    return next((name for widget, name in known if widget is not None and widget is current), '')


def app_state(window, ready: bool) -> dict:
    """What 兔白 may know about this moment; ``bunny_persona.format_state`` drops anything else."""
    from ..i18n import current_language
    state = {'page': current_page(window), 'text_ai_ready': ready, 'ui_language': current_language()}
    studio = getattr(window, 'built_page', lambda _name: None)('studio')
    if studio is not None:
        state['project_open'] = getattr(studio, 'project', None) is not None
    try:
        from .run_diagnosis_dialog import current_app_version
        state['app_version'] = current_app_version()
    except Exception:  # noqa: BLE001 - the version is a nicety
        pass
    try:                                     # 2026-11-15 agent step 1: what she can see of the moment
        from .bunny_tools import snapshot
        state.update(snapshot(window))
    except Exception:  # noqa: BLE001 - seeing less is never a failure
        pass
    try:                                     # step 3: what she is allowed to do now
        from .bunny_permissions import describe
        state['permission'] = describe()
    except Exception:  # noqa: BLE001
        pass
    return state


def _visible(widget):
    return widget if widget is not None and widget.isVisible() and widget.width() > 0 else None


def reveal_widget(widget) -> None:
    """Scroll every scroll area around ``widget`` so it is on screen before she points or floats there.

    (2026-11-14: the home page's language dropdowns sit below the fold; outlining one that was
    scrolled away put the outline, and 兔白, over the bottom bar instead.)
    """
    from PySide6.QtWidgets import QScrollArea
    parent = widget.parentWidget() if widget is not None else None
    while parent is not None:
        if isinstance(parent, QScrollArea):
            parent.ensureWidgetVisible(widget, 40, 60)
        parent = parent.parentWidget()


def target_widget(window, key: str):
    """The control 兔白 outlines for a feature key, if it is on screen now."""
    studio = getattr(window, 'built_page', lambda _name: None)('studio')
    settings_button = getattr(window, 'app_settings_button', None)
    help_button = getattr(window, 'help_button', None)
    targets = {
        'model_workshop': getattr(window, 'model_workshop_button', None),
        'check_update': getattr(window, 'update_button', None),
        'punctuation_new_task': getattr(window, 'subtitle_punctuation', None),
        'subtitle_language': getattr(window, 'recognition_language', None),
        'punctuation_project': getattr(studio, 'punctuation_button', None),
        'math_formula': getattr(studio, 'punctuation_button', None),
        **dict.fromkeys(('shortcuts', 'mcp', 'theme', 'project_save', 'storage_cache'), settings_button),
        **dict.fromkeys(('tutorial', 'sample_project', 'recognition_mode', 'diagnostics'), help_button),
    }
    return _visible(targets.get(key))


def _floating() -> bool:
    return sys.platform == 'win32' if BunnyChat.FLOATING is None else bool(BunnyChat.FLOATING)


# 2026-11-15 (user): she reasons before answering, "high" by default; "max" for the hard ones (she
# asks for it herself with think_harder, or the user picks it); "off" is the fastest. Thinking
# tokens count against the output budget, so the budget grows with the depth.
REASONING_LEVELS = ('off', 'high', 'max')
REASONING_KEY = 'bunny_chat_reasoning'
REASONING_BUDGET = {'off': (700, 90), 'high': (8000, 180), 'max': (16000, 300)}
# 2026-11-15 (user): a brain icon lit for two levels and grey for one was hard to read; the chip
# says the level in a word, and a click lists all three with what each means.
REASONING_CHIPS = {'off': '快速', 'high': '深思', 'max': '最深'}
REASONING_LABELS = {'off': '快速：不思考，回得最快', 'high': '深思：先想再答（默认）', 'max': '最深：难题用，会慢一点'}
EMPTY_ANSWER = {'reasoning_only', 'empty_content', 'structured_output_truncated_before_answer'}


class BunnyChatWorker(QThread):
    """One answer from the user's text AI; the result comes back on the GUI thread."""

    answered = Signal(str)
    failed = Signal(str)
    looked_up = Signal(dict)     # the lookup turn handed to the AI (kept in the chat history)

    def __init__(self, settings: dict, messages: list[dict], parent=None, *, lookup: str = '', ai_ready=None,
                 receipts=None, background=(), state_text: str = '', effort: str = 'high'):
        super().__init__(parent)
        self._settings = settings
        self._messages = messages
        self._lookup = lookup
        self._ai_ready = ai_ready
        self._receipts = receipts            # tool receipts from the GUI thread, sent with the background reads
        self._background = tuple(background)
        self._state_text = state_text
        self.effort = effort if effort in REASONING_LEVELS else 'high'

    def run(self):  # noqa: D401 - QThread override
        from ..providers.ai_providers import AIProviderError, provider_for_stage
        try:
            if self.isInterruptionRequested():
                return
            if self._receipts is not None or self._background:
                # Agent step 2: the slow reads run here, beside the request, then go back as one result turn.
                from .bunny_tools import run_background
                receipts = [*(self._receipts or []), *run_background(self._background, ai_ready=self._ai_ready,
                                                                     settings=self._settings)]
                turn = bunny_persona.tool_results_message(receipts, self._state_text)
                self._messages = [*self._messages, turn]
                self.looked_up.emit(turn)
            elif self._lookup:
                from .bunny_lookup import run_check
                from . import bunny_permissions
                from .bunny_tools import TOOLS
                refused = bunny_permissions.refusal(TOOLS[self._lookup], bunny_permissions.load())
                found = ('没有读取：' + refused) if refused else run_check(
                    self._lookup, ai_ready=self._ai_ready, settings=self._settings)
                turn = bunny_persona.lookup_message(self._lookup, found)
                self._messages = [*self._messages, turn]
                self.looked_up.emit(turn)
            if self.isInterruptionRequested():
                return
            provider = provider_for_stage(self._settings, AI_STAGE)
            # A thinking model now and then puts everything in its reasoning and leaves no answer
            # (2026-11-15, seen once in 80 with "high"): the same depth once more, then without thinking.
            efforts = [self.effort] if self.effort == 'off' else [self.effort, self.effort, 'off']
            for attempt, effort in enumerate(efforts):
                budget, read_s = REASONING_BUDGET[effort]
                try:
                    text = provider.complete(self._messages, max_tokens=budget, temperature=0.8, timeout=(15, read_s),
                                             cancel_check=self.isInterruptionRequested, stage='bunny_chat',
                                             enable_thinking=False if effort == 'off' else effort,
                                             operation_kind='bunny_chat')
                    break
                except Exception as exc:  # noqa: BLE001 - LLMRequestError or AIProviderError, both carry a category
                    if (getattr(exc, 'category', '') not in EMPTY_ANSWER or attempt == len(efforts) - 1
                            or self.isInterruptionRequested()):
                        raise
        except AIProviderError as exc:
            self.failed.emit(' '.join(str(exc).split())[:200])
        except Exception as exc:  # noqa: BLE001 - any provider surprise is a readable failure
            self.failed.emit(' '.join(f'{type(exc).__name__}: {exc}'.split())[:200])
        else:
            self.answered.emit(str(text or ''))


_LIVE_WORKERS: set[BunnyChatWorker] = set()   # a worker outlives a closed card until its request returns


class Spotlight(QWidget):
    """A rounded outline that pulses three times around one control, then goes away."""

    PULSES = 3
    PULSE_MS = 1100

    def __init__(self, window):
        floating = _floating()
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput
                 ) if floating else Qt.WindowType.Widget
        super().__init__(window, flags)
        self.floating = floating
        self.window_ = window
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if floating:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.color = QColor(_theme().accent)
        self.target = QRect()
        self.level = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(self.PULSE_MS)
        self.anim.setLoopCount(self.PULSES)
        self.anim.valueChanged.connect(self._pulse)
        self.anim.finished.connect(self.hide)
        self.hide()

    def show_on(self, widget) -> bool:
        if widget is None:
            return False
        reveal_widget(widget)
        window = self.window_
        top_left = widget.mapTo(window, QPoint(0, 0))
        self.target = QRect(top_left, widget.size())
        if self.floating:
            self.setGeometry(QRect(window.mapToGlobal(QPoint(0, 0)), window.size()))
        else:
            self.setGeometry(window.rect())
        self.show()
        self.raise_()
        self.anim.stop()
        self.anim.start()
        return True

    def _pulse(self, value):
        self.level = math.sin(math.pi * float(value))
        self.update()

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        if self.target.isNull():
            return
        from . import ui_zoom
        pad = ui_zoom.px(6)
        rect = QRectF(self.target.adjusted(-pad, -pad, pad, pad))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        glow = QColor(self.color)
        glow.setAlphaF(0.10 + 0.16 * self.level)
        painter.setBrush(glow)
        pen = QPen(self.color, ui_zoom.px(2) + ui_zoom.px(2) * self.level)
        painter.setPen(pen)
        radius = ui_zoom.px(12)
        painter.drawRoundedRect(rect, radius, radius)


CHAT_MODES = ('dialog', 'thread')
# 2026-11-14 (user: a click gave the same short blip every time): what she says when poked, with
# the mood her voice takes. Nothing about subtitles: being poked is not a cue to talk shop.
POKE_LINES = (
    ('嘿嘿，被你发现我啦～', 'happy'),
    ('别戳啦，耳朵会痒的！', 'teasing'),
    ('%%呜哇%%，吓我一跳……', 'surprised'),
    ('我的眼镜是不是很好看？', 'shy'),
    ('再戳我就要收费了哦，__一次一根胡萝卜__', 'teasing'),
    ('钥匙扣叮当叮当～', 'happy'),
    ('干嘛干嘛，想我了吗？', 'teasing'),
    ('摸摸头可以，戳脸不行！', 'shy'),
    ('累了就休息一下嘛，喝口水。', 'comfort'),
    ('^^哇^^！我在这儿～', 'excited'),
)
MODE_KEY = 'bunny_chat_mode'
LINE_PAUSE_MS = 300          # thread view: the breath between two of her bubbles


def chat_font_family() -> str:
    """猫啃什锦黑 (user, 2026-11-14: cuter), the bundled loading font; '' falls back to the app font."""
    try:
        from ..design.loading_font import loading_font
        return loading_font().family()
    except Exception:  # noqa: BLE001 - a missing font file leaves the app font
        return ''


def chat_sheet(t, family: str) -> str:
    fam = f'font-family: "{family}";' if family else ''
    on_accent = t.text_on_accent or '#ffffff'
    radius = 13                  # under half of the 30-38 px the main window sheet gives these controls
    return (
        f"QLabel#bunnyDialogText {{ {fam} font-size: 18px; color: {t.text}; background: transparent; border: 0; }}"
        f"QLabel#bunnyBubbleText {{ {fam} font-size: 15px; color: {t.text}; background: transparent; border: 0; }}"
        f"QLabel#bunnyBubbleText[user=\"true\"] {{ color: {on_accent}; }}"
        f"QLabel#bunnyCount {{ {fam} font-size: 12px; color: {t.text_muted}; background: transparent; border: 0; }}"
        f"QFrame#bunnyThread {{ background: {t.surface_elevated}; border: 2px solid {t.accent}; border-radius: 22px; }}"
        f"QLabel#bunnyThreadTitle {{ {fam} color: {t.accent}; font-size: 16px; background: transparent; border: 0; }}"
        f"QLabel#bunnyThreadHint {{ {fam} color: {t.text_muted}; font-size: 11px; background: transparent; border: 0; }}"
        f"QFrame#bunnyBubble {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 16px;"
        f" border-bottom-left-radius: 6px; }}"
        f"QFrame#bunnyBubbleUser {{ background: {t.accent}; border: 0; border-radius: 16px; border-bottom-right-radius: 6px; }}"
        f"QScrollArea#bunnyScroll, QWidget#bunnyScrollBody {{ background: transparent; border: 0; }}"
        f"QFrame#bunnyChatBar {{ background: transparent; border: 0; }}"
        f"QFrame#bunnyChatBar[framed=\"true\"] {{ background: {t.surface_elevated}; border: 2px solid {t.accent};"
        f" border-radius: 20px; }}"
        f"QPushButton#bunnyChatIcon {{ background: transparent; border: 0; border-radius: 12px; padding: 3px; }}"
        f"QPushButton#bunnyChatIcon:hover {{ background: {_rgba(t.accent, 0.16)}; }}"
        f"QPushButton#bunnyChatGo {{ {fam} background: {_rgba(t.accent, 0.16)}; color: {t.accent}; border: 0;"
        f" border-radius: {radius}px; padding: 0 14px; min-height: 28px; font-size: 14px; }}"
        f"QPushButton#bunnyChatGo:hover {{ background: {_rgba(t.accent, 0.26)}; }}"
        f"QPushButton#bunnyChatChip {{ {fam} background: {_rgba(t.accent, 0.12)}; color: {t.accent}; border: 0;"
        f" border-radius: 12px; padding: 0 10px; min-height: 24px; font-size: 13px; }}"
        f"QPushButton#bunnyChatChip:hover {{ background: {_rgba(t.accent, 0.24)}; }}"
        f"QPushButton#bunnySuggest {{ {fam} background: {t.surface}; color: {t.text}; border: 1px solid {t.border};"
        f" border-radius: 12px; padding: 0 10px; min-height: 24px; font-size: 13px; }}"
        f"QPushButton#bunnySuggest:hover {{ border: 1px solid {t.accent}; color: {t.accent}; }}"
        f"QLabel#bunnySteps {{ {fam} background: {_rgba(t.accent, 0.08)}; color: {t.text}; border: 0; border-radius: 10px;"
        f" padding: 5px 10px; font-size: 13px; }}"
        f"QMenu#bunnyReasoningMenu {{ {fam} background: {t.surface_elevated}; color: {t.text}; border: 2px solid {t.accent};"
        f" border-radius: 14px; padding: 6px; font-size: 14px; }}"
        f"QMenu#bunnyReasoningMenu::item {{ padding: 6px 14px 6px 28px; border-radius: 10px; }}"
        f"QMenu#bunnyReasoningMenu::item:selected {{ background: {_rgba(t.accent, 0.16)}; color: {t.text}; }}"
        f"QLineEdit#bunnyChatInput {{ {fam} background: {t.input_surface}; color: {t.text}; border: 1px solid {t.border};"
        f" border-radius: {radius}px; padding: 0 12px; min-height: 28px; font-size: 14px; }}"
        f"QLineEdit#bunnyChatInput:focus {{ border: 1px solid {t.accent}; }}"
        f"QPushButton#bunnyChatSend {{ {fam} background: {t.accent}; color: {on_accent}; border: 0;"
        f" border-radius: {radius}px; padding: 0 16px; min-height: 28px; font-size: 14px; }}"
        f"QPushButton#bunnyChatSend:disabled {{ background: {t.disabled}; }}")


class DialogBox(QWidget):
    """B, the user's pick (2026-11-14): one big round box, one sentence at a time, like a village
    neighbour talking. Painted here: the box, a little tail toward 兔白, the 「兔白」 name tag
    tilted on its top-left edge, and the bouncing ▼ when there is more to say (a click goes on)."""

    TAG_H = 26
    TAIL_W = 18
    RADIUS = 34
    PAD = (26, 18, 26, 30)       # inside the border: left, top, right, bottom (room for ▼ and the count)

    def __init__(self, theme, family: str, parent=None):
        super().__init__(parent)
        self.setObjectName('bunnyDialog')
        self.theme = theme
        self.family = family
        self.more = False
        self.flipped = False         # 2026-11-15: 兔白 on the left of the box (the tail points left)
        self._bounce = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self.PAD[0], self.TAG_H // 2 + self.PAD[1], self.PAD[2] + self.TAIL_W,
                                  self.PAD[3])
        layout.setSpacing(10)
        self.label = MarkedLabel()
        self.label.setObjectName('bunnyDialogText')
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.go_row = QHBoxLayout()
        self.go_row.addStretch(1)
        layout.addLayout(self.go_row)
        layout.addStretch(1)
        self.count = QLabel(self)
        self.count.setObjectName('bunnyCount')

    def text_width(self, width: int) -> int:
        return max(60, width - self.PAD[0] - self.PAD[2] - self.TAIL_W)

    def set_flipped(self, flipped: bool):
        if bool(flipped) == self.flipped:
            return
        self.flipped = bool(flipped)
        top, bottom = self.TAG_H // 2 + self.PAD[1], self.PAD[3]
        if self.flipped:
            self.layout().setContentsMargins(self.PAD[0] + self.TAIL_W, top, self.PAD[2], bottom)
        else:
            self.layout().setContentsMargins(self.PAD[0], top, self.PAD[2] + self.TAIL_W, bottom)
        self._place_count()
        self.update()

    def set_count(self, index: int, total: int):
        self.count.setText(f'{index} / {total}' if total > 1 else '')
        self.count.adjustSize()
        self._place_count()

    def set_more(self, more: bool):
        from ..design.ui_motion import reduced_motion
        self.more = bool(more)
        if self.more and not reduced_motion():
            self._timer.start()
        else:
            self._timer.stop()
            self._bounce = 0.0
        self.update()

    def _tick(self):
        self._bounce = (self._bounce + 0.18) % (2 * math.pi)
        self.update()

    def box_rect(self) -> QRectF:
        if self.flipped:
            return QRectF(self.rect()).adjusted(self.TAIL_W + 2, self.TAG_H / 2 + 1, -2, -2)
        return QRectF(self.rect()).adjusted(2, self.TAG_H / 2 + 1, -self.TAIL_W - 2, -2)

    def _place_count(self):
        box = self.box_rect()
        self.count.move(int(box.right() - self.count.width() - 44), int(box.bottom() - self.count.height() - 12))

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._place_count()

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath, QPolygonF
        t = self.theme
        box = self.box_rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(box, self.RADIUS, self.RADIUS)
        tail = QPainterPath()
        if self.flipped:
            tail.addPolygon(QPolygonF([QPointF(box.left() + 6, box.bottom() - 50), QPointF(box.left() - self.TAIL_W, box.bottom() - 18),
                                       QPointF(box.left() + 10, box.bottom() - 24)]))
        else:
            tail.addPolygon(QPolygonF([QPointF(box.right() - 6, box.bottom() - 50), QPointF(box.right() + self.TAIL_W, box.bottom() - 18),
                                       QPointF(box.right() - 10, box.bottom() - 24)]))
        path = path.united(tail)
        painter.setPen(QPen(QColor(t.accent), 3))
        painter.setBrush(QColor(t.surface_elevated))
        painter.drawPath(path)
        # The name tag, tilted, half over the top edge.
        font = QFont(self.family) if self.family else QFont(self.font())
        font.setPixelSize(14)
        font.setBold(True)
        name = str(tr('兔白'))
        width = QFontMetricsF(font).horizontalAdvance(name) + 30
        painter.save()
        painter.translate(box.left() + 26, box.top())
        painter.rotate(-4)
        tag = QRectF(0, -self.TAG_H / 2, width, self.TAG_H)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.accent))
        painter.drawRoundedRect(tag, self.TAG_H / 2, self.TAG_H / 2)
        painter.setPen(QColor(t.text_on_accent or '#ffffff'))
        painter.setFont(font)
        painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, name)
        painter.restore()
        if self.more:
            x, y = box.right() - 30, box.bottom() - 22 + 3 * math.sin(self._bounce)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.accent))
            painter.drawPolygon(QPolygonF([QPointF(x - 7, y - 5), QPointF(x + 7, y - 5), QPointF(x, y + 5)]))


class ThreadView(QFrame):
    """A, the chat thread (2026-11-14): her lines one bubble each on the left, the user's on the
    right, scrollable to read back. 兔白 stands outside the panel, so she never covers a word."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('bunnyThread')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)
        head = QHBoxLayout()
        self.title = QLabel(str(tr('问问兔白')))
        self.title.setObjectName('bunnyThreadTitle')
        head.addWidget(self.title)
        head.addStretch(1)
        self.hint = QLabel()
        self.hint.setObjectName('bunnyThreadHint')
        head.addWidget(self.hint)
        layout.addLayout(head)
        from PySide6.QtWidgets import QScrollArea
        self.scroll = QScrollArea()
        self.scroll.setObjectName('bunnyScroll')
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName('bunnyScrollBody')
        self.rows = QVBoxLayout(self.body)
        self.rows.setContentsMargins(0, 0, 4, 0)
        self.rows.setSpacing(8)
        self.rows.addStretch(1)          # bubbles gather at the bottom, like a chat
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll, 1)
        self.go_row = QHBoxLayout()
        self.go_row.addStretch(1)
        layout.addLayout(self.go_row)
        self.bar_slot = QVBoxLayout()
        layout.addLayout(self.bar_slot)
        self.sheet = ''

    def bubble_width(self) -> int:
        return max(120, int((self.width() - 28 - 16) * 0.8))

    def add_bubble(self, who: str, rich_text: str):
        """A new bubble; returns its label (the typing goes into it)."""
        from .tour_mascot import balanced_width
        user = who == 'user'
        frame = QFrame()
        frame.setObjectName('bunnyBubbleUser' if user else 'bunnyBubble')
        # 2026-11-15 (user: one-line bubbles had square corners): Qt drops the rounding of a side whose
        # two radii (16 + 16) do not fit its height; a one-line bubble is ~30 px, so it gets room for both.
        frame.setMinimumHeight(BUBBLE_MIN_HEIGHT)
        inner = QHBoxLayout(frame)
        inner.setContentsMargins(12, 7, 12, 8)
        label = MarkedLabel()
        label.setObjectName('bunnyBubbleText')
        label.setProperty('user', user)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        for widget in (frame, label):
            widget.setStyleSheet(self.sheet)
        label.ensurePolished()
        label.setFixedWidth(balanced_width(rich_text, label.font(), self.bubble_width() - 24))
        label.setText(rich_text)
        inner.addWidget(label)
        row = QHBoxLayout()
        if user:
            row.addStretch(1)
        row.addWidget(frame)
        if not user:
            row.addStretch(1)
        self.rows.insertLayout(self.rows.count(), row)
        self.scroll_to_end()
        return label, row

    def remove_row(self, row):
        while row.count():
            item = row.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self.rows.removeItem(row)

    def clear(self):
        while self.rows.count() > 1:
            item = self.rows.takeAt(1)
            if item.layout() is not None:
                self.remove_row(item.layout())

    def scroll_to_end(self):
        bar = self.scroll.verticalScrollBar()
        QTimer.singleShot(0, self, lambda: bar.setValue(bar.maximum()))


class BunnyChat(QWidget):
    """「问问兔白」: 兔白 beside a dialog box (B) or a chat thread (A); the user switches between them."""

    FLOATING = None              # None: floating on Windows (tests may pin it)
    DIALOG_WIDTH = 410
    THREAD_WIDTH = 380
    THREAD_HEIGHT = 440
    MASCOT_HEIGHT = 150
    MARGIN = 16
    DRAG_SLOP = 4

    closed = Signal()

    def __init__(self, window):
        floating = _floating()
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
                 ) if floating else Qt.WindowType.Widget
        super().__init__(window, flags)
        self.floating = floating
        if floating:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName('bunnyChat')
        self.window_ = window
        self.theme = _theme()
        self._colors = marker_colors(self.theme)
        self._offset = QPoint()          # where the user dragged the card, from its corner place
        self._press = None
        self._dragging = False
        self._worker = None
        self._generation = 0
        self._history: list[dict] = []   # what the AI sees
        self.transcript: list[tuple] = []   # what was said on screen: ('bunny' | 'user', marked text)
        self._pending: list[str] = []
        self._line_total = 0
        self._offer_after = ''
        self._offer_key = ''
        self._dots_row = None
        self.mascot_docked = True          # False while she is out on her own (BunnyPuck)
        self.mascot_slot = QPoint()       # her place beside the card, in card coordinates
        self.flipped = False              # 2026-11-15: carried to the left edge, she stands left of the box
        self._do_after = ()
        self._do = ()
        self.action_log: list[str] = []   # every tool receipt this chat (agent step 1)
        self.log_entries: list[dict] = []  # 「兔白做过什么」: one row per round of her actions (2026-11-16)
        self.steps: tuple = ()             # a goal she walks the user through, and where they are
        self.step_now = 0
        self._chat_key = None              # which project's saved chat this is (bunny_memory.save_chat)
        self._ticks = 0
        self._question = ''
        self._later = []
        self._tool_rounds = 0
        self._pending_edits = []          # her edits waiting for 「帮我做」 (agent step 3)
        self._undo_batch = []             # UndoRecords of the edits she made for this question
        self._last_undo = []              # what 「撤销兔白刚才做的」 takes back
        self._show_pending = False
        self._show_undo = False
        self.puck = None
        self._pokes = []
        self._active_at = time.monotonic()
        self._dozing = False
        self._window_at = window.pos()
        self._ear_hold_until = 0.0
        from .onboarding import load_state
        mode = load_state().get(MODE_KEY, 'dialog')
        self.mode = mode if mode in CHAT_MODES else 'dialog'
        reasoning = load_state().get(REASONING_KEY, 'high')
        self.reasoning = reasoning if reasoning in REASONING_LEVELS else 'high'
        self._escalated = False          # she asked for the deepest thinking once for this question
        self.settings = runtime_settings(window)
        self.ready, self.service = ai_readiness(self.settings)
        self.features = bunny_lore.feature_index(window)
        self.keys = [key for key, _title, _where in self.features]
        from .feature_search import entries
        self.feature_entries = [entry for entry in entries(window) if entry.key]
        self.lore = bunny_lore.build_entries(window)
        self.spotlight = Spotlight(window)
        self.voice = MascotVoice(self)       # the tutorial's own babble voice
        self.typer = Typewriter(self)
        self.typer.keep_words = True          # words never break across lines
        self.typer.spoke_marked.connect(self._spoke_marked)
        self.typer.finished.connect(self._line_done)
        self._voice_mood = ''
        from .tour_mascot import warm_words
        warm_words()
        self._think = QTimer(self)
        self._think.setInterval(320)
        self._think.timeout.connect(self._think_tick)
        self._think_step = 0
        self._build()
        window.installEventFilter(self)
        self._beat = QTimer(self)
        self._beat.setInterval(120)
        self._beat.timeout.connect(self._heartbeat)
        self._beat.start()
        self.input.textEdited.connect(self._typing)

    # ------------------------------------------------------------ building
    def _build(self):
        from . import ui_zoom
        from ..design.themed_icons import themed_icon
        t = self.theme
        self.family = chat_font_family()
        self.sheet = chat_sheet(t, self.family)
        self.box = DialogBox(t, self.family, self)
        self.thread = ThreadView(self)
        self.thread.sheet = self.sheet
        self.bar = QFrame(self)
        self.bar.setObjectName('bunnyChatBar')
        bar = QHBoxLayout(self.bar)
        bar.setContentsMargins(8, 6, 8, 6)
        bar.setSpacing(4)
        self.mode_button = self._icon_button(self.toggle_mode)
        bar.addWidget(self.mode_button)
        self.input = QLineEdit()
        self.input.setObjectName('bunnyChatInput')
        self.input.setPlaceholderText(str(tr('问兔白点什么吧～')))
        self.input.setMaxLength(300)
        self.input.returnPressed.connect(self.send)
        bar.addWidget(self.input, 1)
        self.send_button = QPushButton(str(tr('发送')))
        self.send_button.setObjectName('bunnyChatSend')
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.clicked.connect(self.send)
        bar.addWidget(self.send_button)
        self.voice_button = self._icon_button(self._toggle_voice)
        bar.addWidget(self.voice_button)
        self.reasoning_button = QPushButton()
        self.reasoning_button.setObjectName('bunnyChatChip')
        self.reasoning_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reasoning_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reasoning_button.clicked.connect(self._reasoning_menu)
        bar.addWidget(self.reasoning_button)
        self.log_button = self._icon_button(self.show_log)
        self.log_button.setIcon(themed_icon('fa5s.history', 'muted'))
        self.log_button.setToolTip(str(tr('兔白做过什么（能逐项撤销）')))
        bar.addWidget(self.log_button)
        self.close_button = self._icon_button(self.close_chat)
        self.close_button.setIcon(themed_icon('fa5s.times', 'muted'))
        self.close_button.setToolTip(str(tr('关掉（Esc）')))
        bar.addWidget(self.close_button)
        self.go_button = QPushButton()
        self.go_button.setObjectName('bunnyChatGo')
        self.go_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.go_button.clicked.connect(self._take_me_there)
        self.go_button.hide()
        self.do_button = QPushButton()
        self.do_button.setObjectName('bunnyChatGo')
        self.do_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.do_button.clicked.connect(self._do_it)
        self.do_button.hide()
        self.undo_button = QPushButton(str(tr('撤销兔白刚才做的')))
        self.undo_button.setObjectName('bunnyChatGo')
        self.undo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_button.clicked.connect(self._undo_her)
        self.undo_button.hide()
        self.steps_label = QLabel()
        self.steps_label.setObjectName('bunnySteps')
        self.steps_label.setTextFormat(Qt.TextFormat.RichText)
        self.steps_label.setWordWrap(True)
        self.steps_label.hide()
        self.suggest_row = QWidget()
        self.suggest_row.setObjectName('bunnySuggestRow')
        suggest = QHBoxLayout(self.suggest_row)
        suggest.setContentsMargins(0, 0, 0, 0)
        suggest.setSpacing(6)
        self.suggest_row.hide()
        # The main window's own sheet styles every QPushButton / QLineEdit; a widget's own sheet
        # always wins over an inherited one, so each of these gets the chat's rules directly.
        for widget in (self.box.label, self.box.count, self.thread, self.thread.title, self.thread.hint,
                       self.thread.scroll, self.thread.body, self.bar, self.mode_button, self.input,
                       self.send_button, self.voice_button, self.reasoning_button, self.close_button, self.go_button,
                       self.do_button, self.undo_button, self.log_button, self.steps_label, self.suggest_row):
            widget.setStyleSheet(self.sheet)
        self._sync_voice_button()
        self._sync_reasoning_button()
        self._sync_hint()
        self.mascot = None
        try:
            from ..design.bunny_mascot import BunnyMascot
            mascot = BunnyMascot(self, height=ui_zoom.px(self.MASCOT_HEIGHT), motion='swing')
        except Exception:  # noqa: BLE001 - no pictures: the box alone
            mascot = None
        if mascot is not None and mascot.available:
            mascot.setObjectName('bunnyChatMascot')
            mascot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            mascot.setCursor(Qt.CursorShape.PointingHandCursor)
            mascot._timer.setInterval(33)
            mascot.installEventFilter(self)
            self.mascot = mascot
            from .bunny_puck import BunnyPuck
            self.puck = BunnyPuck(self)       # dragged, thrown, drifting to places
        elif mascot is not None:
            mascot.deleteLater()
        self._apply_mode()

    def _icon_button(self, slot):
        button = QPushButton()
        button.setObjectName('bunnyChatIcon')
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setIconSize(QSize(15, 15))
        button.clicked.connect(slot)
        return button

    def _sync_voice_button(self):
        from ..design.themed_icons import themed_icon
        on = self.voice.enabled
        self.voice_button.setIcon(themed_icon('fa5s.volume-up' if on else 'fa5s.volume-mute', 'accent' if on else 'muted'))
        self.voice_button.setToolTip(str(tr('兔白的声音：开（点一下关掉）' if on else '兔白的声音：关（点一下打开）')))

    def _sync_hint(self):
        if self.ready:
            text = tr('用你设置的 AI 回答：{service}').format(service=self.service)
        else:
            text = tr('还没设置文字 AI：兔白只能帮你找功能在哪里')
        self.thread.hint.setText(str(text) if len(str(text)) <= 26 else str(text)[:25] + '…')
        self.thread.hint.setToolTip(str(text))
        self.send_button.setToolTip(str(text))

    def _sync_reasoning_button(self):
        level = self.reasoning
        self.reasoning_button.setText(str(tr(REASONING_CHIPS[level])))
        self.reasoning_button.setToolTip(str(tr('兔白的思考深度：{now}（点一下选）')).format(now=tr(REASONING_LABELS[level])))
        self.reasoning_button.setAccessibleName(str(tr(REASONING_LABELS[level])))

    def _reasoning_menu(self):
        from PySide6.QtGui import QAction, QActionGroup
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setObjectName('bunnyReasoningMenu')
        menu.setStyleSheet(self.sheet)
        group = QActionGroup(menu)
        for level in REASONING_LEVELS:
            action = QAction(str(tr(REASONING_LABELS[level])), menu, checkable=True)
            action.setChecked(level == self.reasoning)
            action.triggered.connect(lambda _checked=False, value=level: self.set_reasoning(value))
            group.addAction(action)
            menu.addAction(action)
        self._reasoning_menu_open = menu
        menu.ensurePolished()
        above = QPoint(0, -menu.sizeHint().height() - 4)          # it opens above the chip, inside the window
        menu.popup(self.reasoning_button.mapToGlobal(above))

    def cycle_reasoning(self):
        """思考：高 → 最强 → 关 → 高 (2026-11-15, user: let people decide how hard she thinks)."""
        self.set_reasoning(REASONING_LEVELS[(REASONING_LEVELS.index(self.reasoning) + 1) % len(REASONING_LEVELS)])

    def set_reasoning(self, level: str):
        if level not in REASONING_LEVELS:
            return
        self.reasoning = level
        from .onboarding import load_state, save_state
        save_state(dict(load_state(), **{REASONING_KEY: level}))
        self._sync_reasoning_button()

    def _toggle_voice(self):
        from .tour_mascot import set_voice_enabled
        self.voice.set_enabled(not self.voice.enabled)
        if not self.voice.enabled:
            self.voice.close()
        set_voice_enabled(self.voice.enabled)
        self._sync_voice_button()

    # ------------------------------------------------------------ the two views
    def toggle_mode(self):
        self.set_mode('thread' if self.mode == 'dialog' else 'dialog')

    def set_mode(self, mode: str):
        if mode not in CHAT_MODES or mode == self.mode:
            return
        self.reveal_all()
        self._clear_thinking()
        self.mode = mode
        from .onboarding import load_state, save_state
        save_state(dict(load_state(), **{MODE_KEY: mode}))
        self._apply_mode()
        if self.busy:
            self._show_thinking()
        self.input.setFocus()

    def _apply_mode(self):
        from .tour_mascot import marked_html
        from ..design.themed_icons import themed_icon
        dialog = self.mode == 'dialog'
        self.mode_button.setIcon(themed_icon('fa5s.comments' if dialog else 'fa5s.comment-dots', 'accent'))
        self.mode_button.setToolTip(str(tr('换成聊天串（能往回看）' if dialog else '换成对话框（一句一句说）')))
        self.bar.setProperty('framed', dialog)
        self.bar.style().unpolish(self.bar)
        self.bar.style().polish(self.bar)
        self.box.setVisible(dialog)
        self.thread.setVisible(not dialog)
        if dialog:
            self.bar.setParent(self)
            self.bar.show()
            self.box.go_row.insertWidget(0, self.undo_button)
            self.box.go_row.insertWidget(0, self.do_button)
            self.box.go_row.insertWidget(0, self.go_button)
            self.box.go_row.insertWidget(3, self.suggest_row)
            self.box.layout().insertWidget(0, self.steps_label)
            said = [text for who, text in self.transcript if who == 'bunny']
            self._dialog_line(marked_html(said[-1], self._colors, keep_words=True) if said else '')
            self.box.set_count(0, 0)
            self.box.set_more(False)
        else:
            self.thread.bar_slot.addWidget(self.bar)
            self.thread.go_row.insertWidget(0, self.undo_button)
            self.thread.go_row.insertWidget(0, self.do_button)
            self.thread.go_row.insertWidget(0, self.go_button)
            self.thread.go_row.insertWidget(3, self.suggest_row)
            self.thread.layout().insertWidget(1, self.steps_label)
            self.thread.clear()
            self.relayout()
            for who, text in self.transcript:
                self.thread.add_bubble(who, self._user_html(text) if who == 'user' else marked_html(text, self._colors, keep_words=True))
        # Moving to the other view reparents these, and Qt hides a reparented widget: show them again.
        self.steps_label.setVisible(bool(self.steps))
        self.refresh_suggestions()
        self.relayout()

    def _dialog_line(self, rich_text: str):
        from .tour_mascot import balanced_width
        from . import ui_zoom
        label = self.box.label
        label.ensurePolished()
        width = self.box.text_width(ui_zoom.px(self.DIALOG_WIDTH))
        label.setFixedWidth(balanced_width(rich_text, label.font(), width) if rich_text else width)
        label.setText(rich_text)

    @staticmethod
    def _user_html(text: str) -> str:
        import html
        return html.escape(text)

    # ------------------------------------------------------------ geometry
    def relayout(self):
        from . import ui_zoom
        bunny = self.mascot.size() if self.mascot is not None else QSize(0, 0)
        pad = self.mascot.pad_x if self.mascot is not None else 0
        if self.mode == 'dialog':
            width = ui_zoom.px(self.DIALOG_WIDTH)
            layout = self.box.layout()
            layout.activate()
            box_h = max(ui_zoom.px(112), layout.totalHeightForWidth(width) if layout.hasHeightForWidth()
                        else layout.totalSizeHint().height())
            self.bar.adjustSize()
            bar_h = self.bar.sizeHint().height()
            gap = ui_zoom.px(10)
            content_h = box_h + gap + bar_h
            total = QSize(width + max(0, bunny.width() - pad), max(content_h, bunny.height()))
            self.resize(total)
            left = max(0, bunny.width() - pad) if self.flipped else 0
            tail = self.box.TAIL_W
            self.box.setGeometry(left, total.height() - content_h, width, box_h)
            self.bar.setGeometry(left + (tail if self.flipped else 0), total.height() - bar_h, width - tail, bar_h)
        else:
            width, height = ui_zoom.px(self.THREAD_WIDTH), ui_zoom.px(self.THREAD_HEIGHT)
            gap = ui_zoom.px(4)
            total = QSize(width + gap + max(0, bunny.width() - pad), max(height, bunny.height()))
            self.resize(total)
            left = gap + max(0, bunny.width() - pad) if self.flipped else 0
            self.thread.setGeometry(left, total.height() - height, width, height)
        self.mascot_slot = QPoint(0 if self.flipped else total.width() - bunny.width(), total.height() - bunny.height())
        if self.mascot is not None and self.mascot_docked:
            self.mascot.move(self.mascot_slot)
            self.mascot.raise_()
        self.place()

    def _home_rect(self) -> QRect:
        """Where the card goes in window coordinates: its corner place, moved by the user's drag."""
        window = self.window_
        corner = self._corner()
        x = corner.x() + self._offset.x()
        y = corner.y() + self._offset.y()
        x = max(0, min(x, window.width() - self.width()))
        y = max(0, min(y, window.height() - self.height()))
        return QRect(QPoint(x, y), self.size())

    def place(self):
        rect = self._home_rect()
        if self.floating:
            self.move(self.window_.mapToGlobal(rect.topLeft()))
        else:
            self.move(rect.topLeft())
            self.raise_()
        if self.puck is not None and not self.puck.docked:
            self.puck.carrier.raise_()                     # out on her own, she stays in front of the card

    def follow_bunny(self, at):
        """2026-11-15 (user): carried or thrown, 兔白 takes her card along. ``at`` is where her
        place beside the card should be (window coordinates); the card stays inside the window,
        and its new spot is kept as the user's own (like dragging the card itself)."""
        # Near the left edge there is no room for the box on her left: she stands left of it instead.
        unflipped_x = self.width() - (self.mascot.width() if self.mascot is not None else 0)
        # (Round 2: as soon as the box would be stopped by the edge, so it never falls behind her.)
        if not self.flipped and at.x() < unflipped_x and at.x() + self.width() <= self.window_.width():
            self.set_flipped(True)
        elif self.flipped and (at.x() >= unflipped_x + 60 or at.x() + self.width() > self.window_.width() + 24):
            self.set_flipped(False)
        slot = QPoint(round(at.x()), round(at.y())) - self.mascot_slot
        self._offset = slot - self._corner()
        self._offset = self._home_rect().topLeft() - self._corner()
        self.place()

    def set_flipped(self, flipped: bool):
        if bool(flipped) == self.flipped:
            return
        self.flipped = bool(flipped)
        self.box.set_flipped(self.flipped)
        self.relayout()

    def _keep_bunny_on_top(self):
        if self.puck is not None and not self.puck.docked:
            self.puck.carrier.raise_()

    def event(self, event):  # noqa: N802 - Qt override
        handled = super().event(event)
        if event.type() == QEvent.Type.WindowActivate:
            self._keep_bunny_on_top()       # a click on the card must not bury her under it
        return handled

    def _corner(self) -> QPoint:
        """The lower right corner; on the home page just above 「开始生成字幕」, which lives down there."""
        from . import ui_zoom
        window = self.window_
        margin = ui_zoom.px(self.MARGIN)
        bottom = window.height() - margin
        start = _visible(getattr(window, 'start_button', None))
        if start is not None and start.window() is window:
            top = start.mapTo(window, QPoint(0, 0)).y()
            if self.height() + margin <= top < window.height():
                bottom = min(bottom, top - margin)
        return QPoint(window.width() - self.width() - margin, bottom - self.height())

    # ------------------------------------------------------------ events
    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        kind = event.type()
        if watched is self.window_:
            if kind in (QEvent.Type.Move, QEvent.Type.Resize):
                if kind == QEvent.Type.Move and self.mascot is not None:
                    moved = self.window_.pos() - self._window_at
                    self.mascot.nudge(moved.x())
                self._window_at = self.window_.pos()
                self.place()
                if self.puck is not None and not self.puck.docked:
                    self.puck._place(self.puck._clamp(self.puck.pos))
            elif kind == QEvent.Type.WindowStateChange and self.floating:
                self.setVisible(not self.window_.isMinimized())
            elif kind == QEvent.Type.WindowActivate:
                self._keep_bunny_on_top()
            elif kind == QEvent.Type.Close:
                self.close_chat()
        elif watched is self.mascot and self.puck is not None and kind in (
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease):
            if self.puck.mouse(event):
                return True
        elif watched is self.mascot and kind == QEvent.Type.MouseButtonRelease:
            self.poke()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self.close_chat()
            return
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter) and not self.input.hasFocus():
            self.advance()
            return
        super().keyPressEvent(event)

    def _grab_area(self, point: QPoint) -> bool:
        areas = (self.box, self.bar) if self.mode == 'dialog' else (self.thread,)
        return any(widget.isVisible() and widget.geometry().contains(point) for widget in areas)

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self._grab_area(event.position().toPoint()):
            self._press = (event.globalPosition().toPoint(), QPoint(self._offset), event.position().toPoint())
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt override
        if self._press is not None:
            start, offset, _at = self._press
            moved = event.globalPosition().toPoint() - start
            if self._dragging or moved.manhattanLength() > self.DRAG_SLOP:
                self._dragging = True
                self._offset = offset + moved
                self.place()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt override
        if self._press is not None:
            _start, _offset, at = self._press
            self._press = None
            if self._dragging:
                self._offset = self._home_rect().topLeft() - self._corner()    # keep what clamping allowed
            elif self.mode == 'dialog' and self.box.geometry().contains(at):
                self.advance()                                                # a click on the box: go on
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------ talking
    def open(self):
        self.relayout()
        self.show()
        self.raise_()
        if self.floating:
            self.activateWindow()
        self.input.setFocus()
        restored = self._restore_chat(self._project_key())
        self.say(self._greeting(restored))
        if self._first_notice:
            # The disclosure must be readable before Send, even in the default
            # one-line-at-a-time dialog. Do not hide it behind a later greeting.
            self.typer.finish()

    def _greeting(self, restored: bool = False) -> bunny_persona.BunnyReply:
        from .onboarding import load_state, save_state
        self._first_notice = False
        if not self.ready:
            return bunny_persona.BunnyReply(
                lines=['嗨～小兔纸，我是兔白。', '还没设置文字 AI，兔白现在只能帮你 ==找功能在哪里==。'],
                offer_open='text_ai' if 'text_ai' in self.keys else '', mood='happy')
        state = load_state()
        lines = ['嗨～小兔纸，我是兔白。', '有不懂的随时问我，想聊天也可以哦。']
        if restored:
            lines = ['欢迎回来～', '上次聊的兔白都还记得，接着说吧。']
        act = 'hello'
        night = self._late_night()
        if night and state.get(LATE_NIGHT_KEY) != night:
            lines[1] = '这么晚了还在忙呀……__哈啊__，记得早点休息哦。'
            act = 'sleepy'
            state = dict(state, **{LATE_NIGHT_KEY: night})
            save_state(state)
        if not state.get(NOTICE_KEY):
            self._first_notice = True
            lines.insert(0, f'聊天、请求的电脑配置或识别摘要会发给你设置的 **{self.service}**，会用掉 ==一点点额度==。'
                         '查问题时也可读取并发送一小段字幕原文、译文和诊断。'
                         '长期习惯、知识库和配方会存到本机，并随聊天发给文字 AI。各工程聊天默认保存在本机，最近几轮会随新问题发送；可在兔白权限里清空或关闭。'
                         '可在「设置 → 兔白权限」分别关闭字幕与诊断读取；关闭后，新问题不带之前的聊天记录。'
                         '电脑配置与识别摘要不带个人路径或密钥。')
            save_state(dict(state, **{NOTICE_KEY: True}))
        return bunny_persona.BunnyReply(lines=lines, mood='happy', act=act)

    @staticmethod
    def _late_night() -> str:
        """Today's date between midnight and 5 am (C10: she yawns once such a night), else ''."""
        from datetime import datetime
        now = datetime.now()
        return now.strftime('%Y-%m-%d') if now.hour < 5 else ''

    def say(self, reply: bunny_persona.BunnyReply):
        """Queue her lines: the dialog box shows one at a time (▼, a click goes on); the thread adds them as bubbles."""
        self.reveal_all()
        self._clear_thinking()
        self._offer_after = reply.offer_open
        self._do_after = tuple(reply.do or ())
        self._set_do(())
        self._set_offer('')
        self._pending = [line for line in reply.lines if line]
        self._line_total = len(self._pending)
        if reply.steps is not None:
            self.set_steps(reply.steps, reply.step_now)
        self.suggest_row.hide()
        from .tour_mascot import VOICE_MOODS
        self._voice_mood = reply.mood if reply.mood in VOICE_MOODS else ''
        self.typer.pace = VOICE_MOODS[self._voice_mood][1]   # long syllables, slower words: they stay together
        if self.mascot is not None:
            self.mascot.set_mood(MOOD_FACE.get(reply.mood, 'idle'))
            self.mascot.expression = dict(MOOD_EXPRESSION.get(reply.mood, {}))
            self._stop_waiting_moves()
            act = reply.act or MOOD_ACT.get(reply.mood, '')
            if not (act and self.mascot.act(act)) and reply.mood in HOPS:
                self.mascot.hop()
        self._awake()
        if reply.point_to:
            target = target_widget(self.window_, reply.point_to)
            if self.spotlight.show_on(target):
                self._drift_to(target)
        self._next_line()

    def _next_line(self):
        if not self._pending:
            return
        from ..design.ui_motion import reduced_motion
        from .tour_mascot import marked_html
        line = self._pending.pop(0)
        self.transcript.append(('bunny', line))
        rich = marked_html(line, self._colors, keep_words=True)
        if self.mode == 'dialog':
            self.box.set_more(False)
            self._dialog_line(rich)
            self.box.set_count(self._line_total - len(self._pending), self._line_total)
            label = self.box.label
            self.relayout()
        else:
            label, _row = self.thread.add_bubble('bunny', rich)
        if reduced_motion():
            label.setText(rich)
            self._line_done()
        else:
            self.typer.prepare([(label, line)], self._colors)
            self.typer.start()

    def _line_done(self):
        if self._pending:
            if self.mode == 'dialog':
                self.box.set_more(True)
            else:
                QTimer.singleShot(LINE_PAUSE_MS, self, self._next_if_waiting)
            return
        self._set_offer(self._offer_after)
        self._set_do(self._do_after)
        self._apply_agent_buttons()
        self.refresh_suggestions()
        self._save_chat()
        self.relayout()
        if self.mascot is not None and self.mascot.mood == 'happy':
            QTimer.singleShot(1600, self.mascot, lambda: self.mascot.set_mood('idle'))   # dies with the card

    def _next_if_waiting(self):
        if self.mode == 'thread' and self._pending and not self.typer.running:
            self._next_line()

    def advance(self):
        """A click on the box, or Enter with nothing typed: finish this sentence, or go to the next one."""
        if self.typer.running:
            self.typer.finish()
        elif self._pending:
            self._next_line()

    def reveal_all(self):
        """Everything still queued at once (a new question, a view switch, tests)."""
        for _attempt in range(4 * bunny_persona.MAX_LINES + 4):
            if self.typer.running:
                self.typer.finish()
            elif self._pending:
                self._next_line()
            else:
                break

    def last_reply_html(self) -> list:
        """Her lines since the user last spoke, as the bubble shows them (marks included)."""
        from .tour_mascot import marked_html
        lines = []
        for who, text in reversed(self.transcript):
            if who == 'user':
                break
            lines.insert(0, marked_html(text, self._colors))
        return lines

    def _show_thinking(self):
        self._think_step = 0
        if self.mode == 'dialog':
            self.box.set_count(0, 0)
            self.box.set_more(False)
            self._dialog_line('· · ·')
            self.relayout()
        else:
            _label, self._dots_row = self.thread.add_bubble('bunny', '·')
        self._think.start()
        if self.mascot is not None:                  # C4: hugging her key ring while she thinks
            self.mascot.play('think')
            self.mascot.stick('dots')

    def _think_tick(self):
        self._think_step = (self._think_step + 1) % 3
        dots = ' '.join('·' * (self._think_step + 1))
        if self.mode == 'dialog':
            self.box.label.setText(dots)
        elif self._dots_row is not None and self._dots_row.count():
            frame = self._dots_row.itemAt(0 if self._dots_row.itemAt(0).widget() else 1).widget()
            label = frame.findChild(MarkedLabel) if frame is not None else None
            if label is not None:
                label.setText(dots)

    def _clear_thinking(self):
        self._think.stop()
        if self._dots_row is not None:
            self.thread.remove_row(self._dots_row)
            self._dots_row = None

    def _drift_to(self, widget, then=None, stay_ms: int = 4500):
        """She floats over beside ``widget`` (hops when there), stays a moment, then floats back."""
        if self.puck is None:
            if then is not None:
                then()
            return

        def arrived():
            if self.mascot is not None:
                self.mascot.hop()
                self._ears_toward(widget, 3.0)
            if then is not None:
                then()
            if self.puck is not None and not self.puck.docked:
                self.puck.home_timer.start(stay_ms)
        if not self.puck.drift_to(widget, then=arrived) and then is not None:
            then()

    # ------------------------------------------------------------ living a little (C)
    def _stop_waiting_moves(self):
        if self.mascot is None:
            return
        for name in ('think', 'search', 'doze'):
            self.mascot.stop_move(name)
        for name in ('dots', 'magnifier', 'zzz'):
            self.mascot.unstick(name)

    def _awake(self):
        """Something happened: idle time starts over, and she wakes if she dozed off (A16)."""
        self._active_at = time.monotonic()
        if self._dozing and self.mascot is not None:
            self._dozing = False
            self.mascot.stop_move('doze')
            self.mascot.unstick('zzz')
            self.mascot.play('wake')
            self.mascot.stick('exclaim')

    def _typing(self, _text=''):
        """C6: she leans toward the input while the user types, and eases back after."""
        self._awake()
        if self.mascot is not None:
            self.mascot.lean_target = -12.0
            self._typed_at = time.monotonic()

    def _ears_toward(self, widget, seconds: float):
        """C3: both ears lean toward ``widget`` for a while."""
        if self.mascot is None or widget is None:
            return
        from PySide6.QtCore import QPoint as _QPoint
        target = widget.mapToGlobal(_QPoint(widget.width() // 2, widget.height() // 2))
        mine = self.mascot.mapToGlobal(_QPoint(self.mascot.width() // 2, self.mascot.height() // 3))
        self.mascot.ear_bias = 28.0 if target.x() > mine.x() else -28.0
        self._ear_hold_until = time.monotonic() + seconds

    def _heartbeat(self):
        """Every 120 ms: the pointer nearby turns her ears and wakes her (C9), the lean eases back (C6),
        and after a long quiet she dozes off (A16)."""
        self._ticks += 1
        if self._ticks % 8 == 0 and self.isVisible():
            self.watch_tick()
        mascot = self.mascot
        if mascot is None or not self.isVisible():
            return
        now = time.monotonic()
        from PySide6.QtCore import QPoint as _QPoint
        from PySide6.QtGui import QCursor
        centre = mascot.mapToGlobal(_QPoint(mascot.width() // 2, mascot.height() // 3))
        pointer = QCursor.pos()
        dx, dy = pointer.x() - centre.x(), pointer.y() - centre.y()
        near = dx * dx + dy * dy < 200 * 200
        if now >= self._ear_hold_until:
            wanted = max(-26.0, min(26.0, dx / 200 * 26)) if near else 0.0
            mascot.ear_bias += (wanted - mascot.ear_bias) * 0.35
            if abs(mascot.ear_bias) < 0.2 and not near:
                mascot.ear_bias = 0.0
        if near:
            self._awake()
        if now - getattr(self, '_typed_at', 0.0) > 1.2:
            mascot.lean_target = 0.0
        if abs(mascot.lean - mascot.lean_target) > 0.05:
            mascot.lean += (mascot.lean_target - mascot.lean) * 0.3
            mascot.update()
        quiet = not self.busy and not self.typer.running and not self._pending
        if quiet and not self._dozing and now - self._active_at > IDLE_DOZE_S and not mascot.current_move:
            self._dozing = True
            mascot.play('doze')
            mascot.stick('zzz')

    def task_finished(self, successes: int):
        """C11: a recognition finished while she is open: she pops out and cheers."""
        if successes <= 0 or self.busy:
            return
        self._awake()
        self.reveal_all()
        self.say(bunny_persona.BunnyReply(lines=['^^识别做完啦^^！', '要不要打开 **字幕工作台** 看看？'], mood='excited',
                                          act='cheer'))

    def _set_do(self, do):
        """「帮我做：…」 for an action she offered (bunny_actions); nothing runs until it is pressed."""
        from . import bunny_actions
        self._do = tuple(do or ())
        if not self._do or self._do[0] not in bunny_actions.ACTIONS:
            self._do = ()
            self.do_button.hide()
            return
        self.do_button.setText(str(tr('帮我做：{what}')).format(what=bunny_actions.button_text(*self._do)))
        self.do_button.show()

    def _do_it(self):
        """The user pressed 「帮我做」: she floats to the control, outlines it, then does it."""
        from . import bunny_actions
        if self._pending_edits:
            self._run_pending()
            return
        if not self._do:
            return
        key, value = self._do
        action = bunny_actions.ACTIONS[key]
        self._set_do(())

        def run():
            if self.mascot is not None:              # C2: she gives the control a little push
                self.mascot.play('push')
                self.mascot.stick('wrench')
            try:
                done = action.run(self.window_, value)
            except Exception as exc:  # noqa: BLE001 - said, not raised
                self.say(bunny_persona.BunnyReply(lines=['呜哇，没改成……', str(exc)[:60]], mood='sorry'))
                return
            target = action.target(self.window_, value) if action.target else None
            if target is not None:
                self.spotlight.show_on(_visible(target))
            self.say(bunny_persona.BunnyReply(lines=[done], mood='happy'))
        target = _visible(action.target(self.window_, value)) if action.target else None
        if target is not None:
            self.spotlight.show_on(target)
            self._drift_to(target, then=run)
        else:
            run()

    def _set_offer(self, key: str):
        entry = next((item for item in self.feature_entries if item.key == key), None) if key else None
        self._offer_key = entry.key if entry is not None else ''
        if entry is None:
            self.go_button.hide()
            return
        title = entry.title.split('（')[0].strip() or entry.title
        title = title if len(title) <= 14 else title[:13] + '…'
        self.go_button.setText(str(tr('带我去：{title}')).format(title=title))
        self.go_button.setToolTip(str(entry.where))
        self.go_button.show()

    def _take_me_there(self):
        entry = next((item for item in self.feature_entries if item.key == self._offer_key), None)
        if entry is None:
            return
        target = target_widget(self.window_, entry.key)
        if target is not None:
            self.spotlight.show_on(target)
        try:
            entry.run()
        except Exception as exc:  # noqa: BLE001 - a place that cannot open now is said, not raised
            self.say(bunny_persona.BunnyReply(lines=['呜哇，那里现在打不开……', str(exc)[:60]], mood='sorry'))

    def _spoke(self, char: str, mood: str = ''):
        if self.voice.say(char, mood) and self.mascot is not None:
            self.mascot.open_mouth(0.075)

    def _spoke_marked(self, char: str, style: str):
        """Her voice follows her mood, and the marked words: louder bold, a whispered small, a trembling shake."""
        from .tour_mascot import STYLE_VOICE
        self._spoke(char, STYLE_VOICE.get(style) or self._voice_mood)

    def poke(self):
        """A click on 兔白: she hops and says something short of her own (not a single blip)."""
        import random
        if self.mascot is not None:
            self.mascot.hop()
        if self.busy or self.typer.running or self._pending:
            self._spoke('喵', 'surprised')
            return
        now = time.monotonic()
        self._pokes = [at for at in self._pokes if now - at < POKE_WINDOW_S] + [now]
        if len(self._pokes) >= POKES_FOR_HMPH:       # C8: enough is enough
            self._pokes = []
            self.say(bunny_persona.BunnyReply(lines=['哼，不理你了……', '__……好啦，就理你一下下__'], mood='teasing',
                                              act='hmph'))
            return
        line, mood = random.choice([item for item in POKE_LINES if item[0] != getattr(self, '_last_poke', '')])
        self._last_poke = line
        self.say(bunny_persona.BunnyReply(lines=[line], mood=mood))

    @property
    def busy(self) -> bool:
        return self._worker is not None

    def send(self):
        self._awake()
        question = ' '.join(self.input.text().split())
        if not question:
            self.advance()               # Enter with nothing typed goes on, like a click on the box
            return
        if self.busy:
            return
        self.input.clear()
        self.reveal_all()
        self._sync_chat_context()
        self.transcript.append(('user', question))
        if self.mode == 'thread':
            self.thread.add_bubble('user', self._user_html(question))
        if not self.ready:
            reply = bunny_persona.offline_reply(question, self.feature_entries)
            if not reply.offer_open and 'text_ai' in self.keys:
                reply.offer_open = 'text_ai'
            self.say(reply)
            return
        self._ask(question)

    def messages_for(self, question: str) -> list[dict]:
        from . import bunny_permissions
        self._sync_chat_context()
        permissions = bunny_permissions.load()
        history = self._history[-2 * HISTORY_TURNS:] if (
            permissions['read_subtitles'] and permissions['read_diagnostics'] and permissions['remember']) else []
        return bunny_persona.build_messages(
            question, features=self.features, core=bunny_lore.CORE,
            entries=bunny_lore.select_extra(question, self.lore), state=app_state(self.window_, self.ready),
            history=history)

    def _ask(self, question: str):
        self._generation += 1
        self._question = question
        self.suggest_row.hide()
        self._turn_messages = self.messages_for(question)
        self._looked = False             # one lookup per question at most
        self._tool_rounds = 0            # rounds of tools she ran for this question
        self._later = []                 # windows her tools open once she has answered
        self._format_retried = False     # one more chance for a reply that was not the JSON object
        self._escalated = False          # think_harder used for this question
        self._rounds_closed = False      # the out-of-rounds last request was made
        self._pending_edits = []
        self._pending_context = None
        self._undo_batch = []
        self._show_pending = self._show_undo = False
        self.undo_button.hide()
        self._turn_start = len(self._history)
        self._history.append({'role': 'user', 'content': bunny_persona.own_words(question)})
        self._set_busy(True)
        self._set_offer('')
        self._show_thinking()
        self._start_worker(self._turn_messages)

    def _start_worker(self, messages, lookup: str = '', **extra):
        generation = self._generation
        from .bunny_tools import edit_context
        self._request_context = edit_context(self.window_)
        extra.setdefault('effort', 'max' if getattr(self, '_escalated', False) else self.reasoning)
        worker = BunnyChatWorker(self.settings, messages, lookup=lookup, ai_ready=self.ready, **extra)
        self._worker = worker
        _LIVE_WORKERS.add(worker)
        worker.answered.connect(lambda text, g=generation: self._answered(g, text))
        worker.failed.connect(lambda message, g=generation: self._failed(g, message))
        worker.looked_up.connect(lambda turn, g=generation: g == self._generation and (
            self._history.append(turn), self._turn_messages.append(turn)))
        worker.finished.connect(lambda w=worker: (_LIVE_WORKERS.discard(w), w.deleteLater()))
        worker.start()

    @staticmethod
    def _reply_turn(reply) -> dict:
        data = {'lines': reply.lines, 'point_to': reply.point_to, 'offer_open': reply.offer_open, 'mood': reply.mood}
        if reply.check:
            data['check'] = reply.check
        if reply.tools:
            data['tools'] = [{'name': name, 'args': args} for name, args in reply.tools]
        if reply.steps is not None:
            data['steps'], data['step_now'] = list(reply.steps), reply.step_now
        return {'role': 'assistant', 'content': json.dumps(data, ensure_ascii=False)}

    def _set_busy(self, busy: bool):
        self._worker = self._worker if busy else None
        self.send_button.setEnabled(not busy)
        if not busy:
            self.input.setFocus()

    def _answered(self, generation: int, text: str):
        if generation != self._generation:
            return
        reply = bunny_persona.parse_reply(text, self.keys, pending_edits=bool(self._pending_edits))
        if not reply.structured and not getattr(self, '_format_retried', False):
            # Plain text instead of the JSON object: whatever she meant to do never ran. Ask once more.
            self._format_retried = True
            self._turn_messages = [*self._turn_messages, *bunny_persona.format_retry_messages(text)]
            self._start_worker(self._turn_messages)
            return
        if reply.think_harder and self.reasoning != 'off' and not getattr(self, '_escalated', False):
            # She judged this one hard: the same question again with the deepest thinking (once).
            self._escalated = True
            if self.mascot is not None:
                self.mascot.play('think')
            self._start_worker(self._turn_messages)
            return
        turn = self._reply_turn(reply)
        self._history.append(turn)
        from .bunny_tools import MAX_ROUNDS, TOOLS, edit_context
        if (any(TOOLS[name].acts or TOOLS[name].edit for name, _args in reply.tools)
                and self._request_context != edit_context(self.window_)):
            self._set_busy(False)
            self.say(bunny_persona.BunnyReply(lines=['等待回答时工程、选中字幕或设置变了，请重新告诉兔白要操作什么。'], mood='sorry'))
            return
        if reply.tools and getattr(self, '_tool_rounds', 0) < MAX_ROUNDS:
            self._run_tools(reply, turn)
            return
        if reply.tools and not getattr(self, '_rounds_closed', False):
            # Out of rounds while still asking for tools: one last request to answer from what she has.
            self._rounds_closed = True
            self._turn_messages = [*self._turn_messages, *bunny_persona.rounds_done_messages(text)]
            self._start_worker(self._turn_messages)
            return
        if reply.check and not self._looked:
            # 兔白 wants to look first: she says so, the lookup runs with the next request.
            self._looked = True
            self.say(reply)
            if self.mascot is not None:              # C1: off to look it up, magnifier in hand
                self.mascot.play('search')
                self.mascot.stick('magnifier')
            self._turn_messages = [*self._turn_messages, turn]
            self._start_worker(self._turn_messages, lookup=reply.check)
            return
        self._set_busy(False)
        self._show_pending = bool(self._pending_edits)
        bunny_persona.ensure_confirm_line(reply, self._pending_edits)
        if self._undo_batch:
            self._last_undo, self._undo_batch = list(self._undo_batch), []
            self._show_undo = True
        self.say(reply)
        self._open_later()

    # ------------------------------------------------------------ step 3: 「帮我做」 and 「撤销兔白刚才做的」
    def _apply_agent_buttons(self):
        from .bunny_tools import pending_summary
        if self._show_pending and self._pending_edits:
            self.do_button.setText(str(tr('帮我做：{what}')).format(what=pending_summary(self._pending_edits)))
            self.do_button.show()
        self.undo_button.setVisible(bool(self._show_undo and self._last_undo))

    @staticmethod
    def _receipt_words(receipts) -> list[str]:
        lines = []
        for line in receipts:
            _call, _sep, said = line.partition('：')
            said = said.replace('成功。', '', 1).replace('没做成。', '没做成：', 1).strip()
            if said:
                lines.append(said if len(said) <= 60 else said[:59] + '…')
        return lines[:3]

    def _run_pending(self):
        """The user pressed 「帮我做」 on edits she proposed: they run now, one undo batch."""
        from . import bunny_permissions
        from .bunny_tools import edit_context, run_turn
        pending, self._pending_edits = list(self._pending_edits), []
        self._show_pending = False
        self.do_button.hide()
        if self._pending_context != edit_context(self.window_):
            self.say(bunny_persona.BunnyReply(lines=['工程、选中字幕或设置已经变了，请重新告诉兔白要改什么。'], mood='sorry'))
            return
        if self.mascot is not None:
            self.mascot.play('push')
            self.mascot.stick('wrench')
        result = run_turn(self.window_, pending, bunny_permissions.load(), confirmed=True)
        self.action_log.extend(result.receipts)
        self._log(result.receipts, result.undo, pressed=True)
        self._later = [*getattr(self, '_later', []), *result.later]
        self._history.append({'role': 'user', 'content': bunny_persona.tool_results_message(
            result.receipts, '（小兔纸按了「帮我做」）')['content']})
        if result.undo:
            self._last_undo = list(result.undo)
            self._show_undo = True
        ok = all('成功' in line for line in result.receipts)
        self.say(bunny_persona.BunnyReply(lines=self._receipt_words(result.receipts) or ['好啦～'],
                                          mood='happy' if ok else 'sorry'))
        self._open_later()

    def _undo_her(self):
        from .bunny_tools import undo_records
        records, self._last_undo = list(self._last_undo), []
        self._show_undo = False
        self.undo_button.hide()
        try:
            undone, why = undo_records(records)
        except RuntimeError:
            undone, why = 0, '原来的工程已经关闭，请在当前工程用 Ctrl+Z 检查修改。'
        if why:
            self.say(bunny_persona.BunnyReply(lines=[f'撤回了 {undone} 步，后面的兔白不敢动～', why], mood='sorry'))
        else:
            self.say(bunny_persona.BunnyReply(lines=['都撤回去啦，跟兔白动手之前一样～'], mood='happy'))
        self._history.append({'role': 'user', 'content': f'（小兔纸按了「撤销兔白刚才做的」：撤回了 {undone} 步）'})

    def _run_tools(self, reply, turn):
        """Agent step 1 (2026-11-15): her 🟢 tools run now; the receipts and the new moment go back to her."""
        from . import bunny_permissions
        from .bunny_tools import edit_context, run_turn, split_calls
        self._tool_rounds = getattr(self, '_tool_rounds', 0) + 1
        permissions = bunny_permissions.load()
        now, background = split_calls(reply.tools, permissions)
        if self.mascot is not None:                  # C2 / C1: a push for doing, the magnifier for looking up
            self.mascot.play('push' if now else 'search')
            if background:
                self.mascot.stick('magnifier')
        result = run_turn(self.window_, now, permissions)
        receipts, later = result.receipts, result.later
        if result.pending and not self._pending_edits:
            self._pending_context = edit_context(self.window_)
        for call in result.pending:                     # the same edit asked again in a later round waits once
            if call not in self._pending_edits:
                self._pending_edits.append(call)
        self._undo_batch = [*self._undo_batch, *result.undo]
        self._later = [*getattr(self, '_later', []), *later]
        self.action_log.extend(line for line in receipts)
        self._log([line for line in receipts if '还没做' not in line], result.undo)
        state_text = bunny_persona.format_state(app_state(self.window_, self.ready))
        if background:
            # The slow reads run on the worker beside the next request; it hands back one result turn.
            self._turn_messages = [*self._turn_messages, turn]
            self._start_worker(self._turn_messages, receipts=receipts, background=background, state_text=state_text)
            return
        result = bunny_persona.tool_results_message(receipts, state_text)
        self._history.append(result)
        self._turn_messages = [*self._turn_messages, turn, result]
        self._start_worker(self._turn_messages)

    def _open_later(self):
        """Windows her tools opened wait until her answer is on screen (their modal loops)."""
        later, self._later = list(getattr(self, '_later', [])), []
        if not later:
            return
        from .bunny_tools import TOOLS, run_later
        from . import bunny_permissions
        generation = self._generation

        def open_all():
            for name, args in later:
                if generation != self._generation or bunny_permissions.refusal(TOOLS[name], bunny_permissions.load()):
                    return
                try:
                    run_later(self.window_, name, args)
                except Exception as exc:  # noqa: BLE001 - said, not raised
                    self.say(bunny_persona.BunnyReply(lines=['呜哇，窗口没打开……', str(exc)[:60]], mood='sorry'))
        QTimer.singleShot(400, open_all)

    def _failed(self, generation: int, message: str):
        if generation != self._generation:
            return
        self._set_busy(False)
        if self._undo_batch:
            self._last_undo, self._undo_batch = list(self._undo_batch), []
            self._show_undo = True
        del self._history[getattr(self, '_turn_start', len(self._history)):]   # the whole unanswered question
        short = message if len(message) <= 60 else message[:59] + '…'
        self.say(bunny_persona.BunnyReply(lines=['呜哇，兔白没连上 AI 脑袋……', short or '等一下再问问看？'],
                                          offer_open='text_ai' if 'text_ai' in self.keys else '', mood='sorry'))
        if self.mascot is not None:                  # C5: her glasses fog up
            self.mascot.play('fog')
            self.mascot.stick('sweat')

    # ------------------------------------------------------------ round 4 (2026-11-16)
    def set_steps(self, steps, now: int = 0):
        """The goal she walks the user through, as a small checklist above her words."""
        import html
        self.steps = tuple(steps or ())
        self.step_now = max(0, min(int(now or 0), len(self.steps)))
        if not self.steps:
            self.steps_label.hide()
            self.relayout()
            return
        accent = self.theme.accent
        parts = []
        for index, step in enumerate(self.steps):
            name = html.escape(step)
            if index < self.step_now:
                parts.append(f'<span style="color:{self.theme.text_muted}">✓ {name}</span>')
            elif index == self.step_now:
                parts.append(f'<b style="color:{accent}">▶ {index + 1}. {name}</b>')
            else:
                parts.append(f'{index + 1}. {name}')
        self.steps_label.setText('　'.join(parts))
        self.steps_label.setToolTip(str(tr('兔白带你一步步做：做完这一步，她会接着讲下一步')))
        self.steps_label.show()
        self.relayout()

    def refresh_suggestions(self):
        """Two or three things worth asking right here, as buttons above the input."""
        layout = self.suggest_row.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        shown = [] if (self.busy or self._pending or not self.ready or self.do_button.isVisible()
                       or self.go_button.isVisible() or self.undo_button.isVisible()) else suggestions(self.window_)
        for words in shown:
            button = QPushButton(str(tr(words)))
            button.setObjectName('bunnySuggest')
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setStyleSheet(self.sheet)
            button.clicked.connect(lambda _checked=False, value=str(tr(words)): self.ask_now(value))
            layout.addWidget(button)
        self.suggest_row.setVisible(bool(shown))

    def ask_now(self, question: str):
        self.input.setText(question)
        self.send()

    def _log(self, receipts, undo, pressed: bool = False):
        if not receipts:
            return
        self.log_entries.append(dict(at=time.strftime('%H:%M'), question=self._question, receipts=list(receipts),
                                     undo=[record for record in undo if record is not None], undone=False,
                                     pressed=pressed))

    def show_log(self):
        """「兔白做过什么」: every action of hers this time, each with its own undo where she can."""
        from PySide6.QtWidgets import QDialog, QListWidget, QListWidgetItem, QVBoxLayout
        dialog = QDialog(self.window_)
        dialog.setObjectName('bunnyLog')
        dialog.setWindowTitle(str(tr('兔白做过什么')))
        dialog.resize(520, 420)
        th, fam = self.theme, f'font-family: "{self.family}";' if self.family else ''
        dialog.setStyleSheet(
            f"QDialog#bunnyLog {{ background: {th.surface_elevated}; }}"
            f"QDialog#bunnyLog QLabel {{ {fam} color: {th.text_muted}; font-size: 13px; }}"
            f"QListWidget#bunnyLogList {{ {fam} background: {th.surface}; color: {th.text}; border: 1px solid {th.border};"
            f" border-radius: 12px; padding: 6px; font-size: 14px; }}"
            f"QListWidget#bunnyLogList::item {{ padding: 8px; border-radius: 8px; }}"
            f"QListWidget#bunnyLogList::item:selected {{ background: {_rgba(th.accent, 0.18)}; color: {th.text}; }}"
            f"QDialog#bunnyLog QPushButton {{ {fam} background: {_rgba(th.accent, 0.16)}; color: {th.accent}; border: 0;"
            f" border-radius: 13px; padding: 0 16px; min-height: 28px; font-size: 14px; }}"
            f"QDialog#bunnyLog QPushButton:disabled {{ color: {th.text_muted}; background: {th.surface}; }}")
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        listing.setObjectName('bunnyLogList')
        listing.setWordWrap(True)
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        listing.setTextElideMode(Qt.TextElideMode.ElideNone)
        listing.setResizeMode(QListWidget.ResizeMode.Adjust)
        layout.addWidget(listing, 1)
        note = QLabel()
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        undo = QPushButton(str(tr('撤销这一项')))
        undo.setObjectName('bunnyLogUndo')
        close = QPushButton(str(tr('关闭')))
        row.addStretch(1)
        row.addWidget(undo)
        row.addWidget(close)
        layout.addLayout(row)

        def fill():
            listing.clear()
            for index, entry in reversed(list(enumerate(self.log_entries))):
                head = f'{entry["at"]}  ' + (str(tr('（按了「帮我做」）')) if entry['pressed'] else (entry['question'][:30] or ''))
                said = '\n'.join('· ' + plain_receipt(line)[:90] for line in entry['receipts'])
                tail = str(tr('（已撤销）')) if entry['undone'] else ''
                item = QListWidgetItem(f'{head}{tail}\n{said}')
                item.setData(Qt.ItemDataRole.UserRole, index)
                listing.addItem(item)
            if not self.log_entries:
                note.setText(str(tr('这次还没有动手做过什么。')))
            elif listing.currentRow() < 0:
                listing.setCurrentRow(0)
            pick()

        def pick():
            item = listing.currentItem()
            entry = self.log_entries[item.data(Qt.ItemDataRole.UserRole)] if item is not None else None
            undo.setEnabled(bool(entry and entry['undo'] and not entry['undone']))

        def take_back():
            from .bunny_tools import undo_records
            item = listing.currentItem()
            if item is None:
                return
            entry = self.log_entries[item.data(Qt.ItemDataRole.UserRole)]
            try:
                undone, why = undo_records(entry['undo'])
            except RuntimeError:
                undone, why = 0, str(tr('原来的工程已经关闭了'))
            if not why:
                entry['undone'] = True
                if self._last_undo == entry['undo']:
                    self._last_undo = []
                    self.undo_button.hide()
            note.setText(why or str(tr('撤回了 {count} 步。')).format(count=undone))
            self._history.append({'role': 'user', 'content': f'（小兔纸在「兔白做过什么」里撤销了一项：撤回 {undone} 步）'})
            fill()
        listing.currentItemChanged.connect(lambda *_args: pick())
        undo.clicked.connect(take_back)
        close.clicked.connect(dialog.accept)
        fill()
        self._log_dialog = dialog
        dialog.show()
        return dialog

    def watch_tick(self):
        """Once a second: tell how her AI 断句 went, and follow the user to another project's chat."""
        from .bunny_tools import _built
        page = _built(self.window_, 'studio')
        if page is not None and getattr(page, '_bunny_refine_watch', None) and not self.busy:
            from .bunny_subtitle_tools import refine_report
            lines = refine_report(page)
            if lines:
                reply = bunny_persona.BunnyReply(lines=lines, mood='happy')
                from . import bunny_permissions
                if bunny_permissions.load()['read_subtitles']:
                    self._history.append(self._reply_turn(reply))
                self.say(reply)
        if not self.busy and not self._pending and not self.typer.running:
            self._sync_chat_context()

    def _sync_chat_context(self):
        from . import bunny_memory, bunny_permissions
        values = bunny_permissions.load()
        token = (values['keep_chat'], values['remember'], bunny_memory.CHAT_EPOCH)
        key = self._project_key()
        if key != self._chat_key or token != getattr(self, '_chat_token', None):
            self._save_chat()
            self._restore_chat(key)

    def _project_key(self) -> str:
        from .bunny_tools import _built
        page = _built(self.window_, 'studio')
        project = getattr(page, 'project', None)
        if project is None:
            return 'home'
        session = getattr(page, 'session', None)
        return str(getattr(session, 'project_path', '') or getattr(project, 'project_id', '') or 'project')

    def _restore_chat(self, key: str) -> bool:
        """This project's chat from last time (when kept); True when there was one."""
        from . import bunny_memory, bunny_permissions
        self._chat_key = key
        values = bunny_permissions.load()
        self._chat_token = (values['keep_chat'], values['remember'], bunny_memory.CHAT_EPOCH)
        items = bunny_memory.load_chat(key) if values['keep_chat'] and values['remember'] else []
        self._pending_edits = []
        self._last_undo = []
        self._set_do(())
        self.undo_button.hide()
        self.transcript = list(items)
        self._history = history_from(items)
        self.set_steps((), 0)
        if self.mode == 'thread':
            self._apply_mode()
        return bool(items)

    def _save_chat(self):
        from . import bunny_memory, bunny_permissions
        values = bunny_permissions.load()
        token = (values['keep_chat'], values['remember'], bunny_memory.CHAT_EPOCH)
        if self._chat_key is None or not all(token[:2]) or token != getattr(self, '_chat_token', None):
            return
        if not any(who == 'user' for who, _text in self.transcript):
            return                                   # only her greeting: nothing worth keeping
        try:
            bunny_memory.save_chat(self._chat_key, self.transcript)
        except OSError:
            pass

    def ask_about(self, number: int, text: str):
        """「问兔白这条」 from a subtitle's right-click menu: the question starts with that line."""
        self.input.setText(str(tr('第 {number} 条「{text}」：')).format(number=number, text=text[:30]))
        self.input.setFocus()
        self.input.end(False)

    def close_chat(self):
        self._save_chat()
        self._generation += 1
        if self._worker is not None:
            self._worker.requestInterruption()
            self._worker = None
        self.typer.stop()
        self._think.stop()
        self._beat.stop()
        self.voice.close()
        self.spotlight.hide()
        if self.puck is not None:
            self.puck.close()
        try:
            self.window_.removeEventFilter(self)
        except RuntimeError:
            pass
        if getattr(self.window_, '_bunny_chat', None) is self:
            self.window_._bunny_chat = None
        self.hide()
        self.closed.emit()
        self.spotlight.deleteLater()
        self.deleteLater()


def plain_receipt(line: str) -> str:
    """A tool receipt in her words: what happened, without the call itself."""
    _call, _sep, said = str(line).partition('：')
    said = said.replace('成功。', '', 1).replace('没做成。', '没做成：', 1).strip()
    return said or str(line).lstrip('- ')


def suggestions(window) -> list:
    """What is worth asking right here (2026-11-16): at most three short questions."""
    page = current_page(window)
    from .bunny_tools import _built, refine_failed_ids
    studio = _built(window, 'studio')
    project = getattr(studio, 'project', None) if page == '字幕工作台' else None
    if project is not None:
        picks = ['帮我检查字幕']
        if refine_failed_ids(project):
            picks.append('把失败的断句补齐')
        from .bunny_subtitle_tools import learned_summary
        try:
            learned = learned_summary(studio)
        except Exception:  # noqa: BLE001
            learned = ''
        picks.append('把我常改的字全片改掉' if learned else '字幕太长了，帮我调短')
        return picks[:3]
    if page == '识别完成的结果页':
        return ['这次结果有问题吗？', '接下来该做什么？']
    if page == '首页':
        return ['我该怎么开始？', '我的电脑能用本机识别吗？']
    return ['这个页面怎么用？']


def history_from(items) -> list:
    """A saved chat back into what the AI sees: the user's words, her lines as one answer each time."""
    history, lines = [], []
    for who, text in items:
        if who == 'user':
            if lines:
                history.append({'role': 'assistant', 'content': json.dumps({'lines': lines}, ensure_ascii=False)})
                lines = []
            history.append({'role': 'user', 'content': bunny_persona.own_words(text)})
        else:
            lines.append(text)
    if lines:
        history.append({'role': 'assistant', 'content': json.dumps({'lines': lines}, ensure_ascii=False)})
    return history


def ask_about_cue(window, cue_id: str) -> BunnyChat | None:
    """The workbench's 「问兔白这条」: open her chat with that subtitle in the question."""
    from .bunny_tools import _built, _cues
    page = _built(window, 'studio')
    project = getattr(page, 'project', None)
    if project is None:
        return None
    cues = _cues(project)
    number = next((index for index, cue in enumerate(cues, 1) if cue.id == cue_id), 0)
    if not number:
        return None
    chat = open_bunny_chat(window)
    chat.ask_about(number, cues[number - 1].text)
    return chat


def open_bunny_chat(window) -> BunnyChat:
    """Bring 兔白's chat up over ``window`` (the one already open, if any)."""
    chat = getattr(window, '_bunny_chat', None)
    if chat is not None:
        try:
            chat.show()
            chat.raise_()
            chat.input.setFocus()
            if chat.mascot is not None and chat.mascot_docked:
                chat.mascot.play('peek')
            return chat
        except RuntimeError:     # deleted under us
            pass
    chat = BunnyChat(window)
    window._bunny_chat = chat
    chat.open()
    return chat


__all__ = ['BunnyChat', 'BunnyChatWorker', 'CHAT_MODES', 'DialogBox', 'Spotlight', 'ThreadView', 'app_state',
           'ask_about_cue', 'history_from', 'open_bunny_chat', 'suggestions', 'target_widget']
