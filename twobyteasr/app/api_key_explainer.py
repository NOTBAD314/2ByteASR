"""「API Key 是什么？」— the picture explainer (2026-10-15).

User feedback: many people have never heard of an API key, and many do not
know a key needs credit before it works. The window says it with pictures and
a line each:

* on top, what the key is for: translation, AI 断句 and AI 校对 all need it —
  the AI makes the sentences read well — with 我要用 AI：一步步教我, which
  opens 「申请与设置 API」 on DeepSeek (text AI, the best fit);
* below, three cards: what a key is, top up 10 yuan first, copy it and paste
  it in; 稍后再填 closes.

2026-10-21 (user): it no longer opens with "不填也能出字幕" — new users are asked
for a key, DeepSeek recommended.

The animations come from assets/onboarding/source/tutorial.html
(ai_polish, key_what, key_topup, key_get), like the tutorial's.

``offer_api_key_help`` is the short note in front of it when a user-clicked
AI action (Studio AI 断句 / AI 设计 / 翻译 / 查找替换的 AI 预览, AI 词库校对's
AI 校对, 术语库 AI 建库) finds no key; ``ask_for_key_if_missing`` checks and asks.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..design.main_ui_dialogs import SpringDialog
from ..i18n import bind_text, tr

# (animation, title, line) — short on purpose: the picture carries the meaning.
HERO = ('ai_polish', '有了 API Key，AI 才能帮你改字幕', '翻译、AI 断句、AI 校对都要它：AI 会把句子改得通顺好看')
KEY_STEPS = (
    ('key_what', '① API Key 是一把钥匙', '服务商给的一串密码（sk- 开头），别外传'),
    ('key_topup', '② 先充值 10 元', '多数服务要先充值才能用；用多少扣多少，10 元够先用一阵'),
    ('key_get', '③ 复制，贴进兔白', '贴好点“测试”，变绿就能用'),
)
TEXT_AI_GUIDE = 'deepseek'


def explainer_qss(theme) -> str:
    return (
        f"QDialog#apiKeyExplainer {{ background: {theme.surface}; }}"
        f"QLabel#explainerTitle {{ color: {theme.text}; font-size: 22px; font-weight: 700; }}"
        f"QFrame#explainerHero, QFrame#explainerCard {{ background: {theme.surface_elevated}; border: 1px solid {theme.border};"
        f" border-radius: 18px; }}"
        f"QFrame#explainerHero {{ border: 2px solid {theme.accent}; }}"
        f"QLabel#explainerCardTitle {{ color: {theme.text}; font-size: 16px; font-weight: 700; }}"
        f"QLabel#explainerHeroTitle {{ color: {theme.text}; font-size: 20px; font-weight: 700; }}"
        f"QLabel#explainerLine {{ color: {theme.text_secondary}; font-size: 13px; }}"
        f"QLabel#explainerSection {{ color: {theme.text}; font-size: 15px; font-weight: 700; }}"
    )


class ApiKeyExplainerDialog(SpringDialog):
    """``choice`` after closing: 'setup' or '' (稍后再填 / closed)."""

    ANIM_HERO = QSize(330, 140)
    ANIM_CARD = QSize(250, 106)

    def __init__(self, parent=None, *, offer_setup: bool = True):
        super().__init__(parent)
        from ..design.presentation import button_role, glyph_button
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        from .home_tour import TourAnim
        self.setObjectName('apiKeyExplainer')
        bind_text(self, 'API Key 是什么？', property='windowTitle')
        theme = theme_definition(theme_key())
        self.setStyleSheet(explainer_qss(theme))
        # Three cards of ANIM_CARD width plus their margins, side by side.
        self.setMinimumWidth(3 * (self.ANIM_CARD.width() + 26) + 2 * 12 + 48)
        light = QColor(theme.app_background).lightness() > 128
        self.choice = ''
        self.anims: list[TourAnim] = []

        def anim(name: str, size: QSize) -> TourAnim:
            widget = TourAnim(self)
            widget.setFixedSize(size)
            widget.load(name, light)
            widget.setObjectName(f'explainerAnim_{name}')
            self.anims.append(widget)
            return widget

        def label(text: str, name: str) -> QLabel:
            widget = QLabel()
            bind_text(widget, text)
            widget.setObjectName(name)
            widget.setWordWrap(True)
            return widget

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 20, 20, 22)
        outer.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(label('API Key 是什么？', 'explainerTitle'), 1)
        close = glyph_button(button_role(QPushButton('×'), 'ghost'))
        bind_text(close, '关闭', property='accessibleName')
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)

        hero = QFrame()
        hero.setObjectName('explainerHero')
        row = QHBoxLayout(hero)
        row.setContentsMargins(16, 14, 22, 14)
        row.setSpacing(20)
        row.addWidget(anim(HERO[0], self.ANIM_HERO))
        words = QVBoxLayout()
        words.setSpacing(8)
        words.addStretch(1)
        words.addWidget(label(HERO[1], 'explainerHeroTitle'))
        words.addWidget(label(HERO[2], 'explainerLine'))
        self.setup_button = button_role(QPushButton(), 'primary')
        bind_text(self.setup_button, '我要用 AI：一步步教我（推荐 DeepSeek）' if offer_setup else '知道了')
        self.setup_button.setObjectName('explainerSetup')
        self.setup_button.clicked.connect(lambda: self._finish('setup' if offer_setup else ''))
        words.addSpacing(4)
        words.addWidget(self.setup_button, 0, Qt.AlignmentFlag.AlignLeft)
        words.addStretch(1)
        row.addLayout(words, 1)
        outer.addWidget(hero)

        outer.addWidget(label('三步拿到 API Key', 'explainerSection'))
        cards = QHBoxLayout()
        cards.setSpacing(12)
        for name, title, line in KEY_STEPS:
            card = QFrame()
            card.setObjectName('explainerCard')
            body = QVBoxLayout(card)
            body.setContentsMargins(12, 12, 12, 14)
            body.setSpacing(8)
            body.addWidget(anim(name, self.ANIM_CARD), 0, Qt.AlignmentFlag.AlignHCenter)
            body.addWidget(label(title, 'explainerCardTitle'))
            body.addWidget(label(line, 'explainerLine'))
            body.addStretch(1)
            cards.addWidget(card, 1)
        outer.addLayout(cards)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.later_button = button_role(QPushButton(), 'secondary')
        bind_text(self.later_button, '稍后再填')
        self.later_button.setObjectName('explainerLater')
        self.later_button.clicked.connect(lambda: self._finish(''))
        self.later_button.setVisible(offer_setup)
        footer.addWidget(self.later_button)
        outer.addLayout(footer)
        self.setup_button.setFocus()

    def showEvent(self, event):  # noqa: N802 - Qt override
        super().showEvent(event)
        for widget in self.anims:
            widget.start()

    def done(self, result):  # noqa: D401 - Qt override
        for widget in self.anims:
            widget.stop()
        super().done(result)

    def _finish(self, choice: str) -> None:
        self.choice = choice
        self.accept()


def open_api_key_explainer(window, *, offer_setup: bool = True) -> str:
    """Show the explainer over ``window``; '我要用 AI' opens the API guide on text AI."""
    dialog = ApiKeyExplainerDialog(window, offer_setup=offer_setup)
    dialog.exec()
    choice = dialog.choice
    dialog.deleteLater()
    if choice == 'setup' and hasattr(window, '_open_api_setup_guide'):
        window._open_api_setup_guide(TEXT_AI_GUIDE, 'text')
    return choice


NEEDS_KEY_TITLE = '需要 API Key'
NEEDS_KEY = '这个功能要用 AI，需要先填 API Key'


def _setup_host(widget):
    """The main window (it opens 申请与设置 API), else the widget's own window."""
    from PySide6.QtWidgets import QApplication
    window = widget.window() if widget is not None else None
    if window is not None and hasattr(window, '_open_api_setup_guide'):
        return window
    for candidate in QApplication.topLevelWidgets():
        if hasattr(candidate, '_open_api_setup_guide'):
            return candidate
    return window


def offer_api_key_help(widget) -> str:
    """A user-clicked AI action has no key: say so instead of failing (2026-10-15).

    「API Key 是什么？」 opens the explainer (which offers 申请与设置 API);
    「取消」 closes. Nothing is sent either way. Returns 'cancel' or the
    explainer's choice.
    """
    from PySide6.QtWidgets import QMessageBox
    host = _setup_host(widget) or widget
    box = QMessageBox(host)
    box.setObjectName('apiKeyNeeded')
    box.setIcon(QMessageBox.Icon.Information)
    bind_text(box, NEEDS_KEY_TITLE, property='windowTitle')
    bind_text(box, NEEDS_KEY)
    explain = box.addButton(tr('API Key 是什么？'), QMessageBox.ButtonRole.AcceptRole)
    explain.setObjectName('apiKeyNeededExplain')
    box.addButton(tr('取消'), QMessageBox.ButtonRole.RejectRole).setObjectName('apiKeyNeededCancel')
    box.setDefaultButton(explain)
    box.exec()
    clicked = box.clickedButton()
    box.deleteLater()
    if clicked is not explain:
        return 'cancel'
    return open_api_key_explainer(host)


def ask_for_key_if_missing(widget, settings, stage: str = 'polish', *, status=None) -> bool:
    """True, after the note, when this click needs a key that is not there; nothing is sent.

    ``status``: called first, to leave a line where the feature reports (it did not run)."""
    from ..providers.llm_config import text_ai_key_missing
    if not text_ai_key_missing(settings, stage):
        return False
    if status is not None:
        status()
    offer_api_key_help(widget)
    return True


def explainer_strings() -> tuple[str, ...]:
    """Every user-facing string here (the localization test reads this)."""
    texts = ['API Key 是什么？', '关闭', '稍后再填', '三步拿到 API Key',
             '我要用 AI：一步步教我（推荐 DeepSeek）', '知道了', HERO[1], HERO[2], NEEDS_KEY_TITLE, NEEDS_KEY, '取消']
    for _name, title, line in KEY_STEPS:
        texts += [title, line]
    return tuple(texts)


__all__ = ['ApiKeyExplainerDialog', 'open_api_key_explainer', 'offer_api_key_help', 'ask_for_key_if_missing',
           'explainer_strings', 'KEY_STEPS', 'HERO']
