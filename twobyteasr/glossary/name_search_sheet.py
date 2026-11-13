"""「查外语官方名」: which language, which terms, try 20 first.

2026-11-13 (user, option A of tmp/glossary-ai-menu-20261113): the old dialog
was two bare combo boxes and a paragraph, and nothing said that the chosen AI
could not search (so names were only guessed). This sheet asks two questions
with counts, says in plain words whether the AI can go online (with one-click
switches to one that can), offers "先试 20 条" and shows what the run costs.
Results still land as candidates in 待处理; only review writes a name.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QVBoxLayout, QWidget)

from . import multilingual_terms as m

TRIAL = 20
QUICK_LANGUAGES = ('en', 'ja', 'ko', 'zh-Hant')
SCOPES = (
    ('missing', '还没确认 {label} 名的', '最常用：只查缺的和没确认的'),
    ('all', '全部词条', '也核对已经确认的写法，有出入会提醒'),
    ('selected', '只查我选中的', '先在卡片上按住 Ctrl / Shift 选几张'),
)


def _qss(theme) -> str:
    t = theme
    return f"""
    QWidget#nameSearchRoot {{ background: {t.surface_elevated}; }}
    QWidget#nameSearchRoot QLabel {{ background: transparent; color: {t.text}; }}
    QLabel#nameSearchTitle {{ font-size: 18px; font-weight: 800; }}
    QLabel#nameSearchTip {{ background: {t.panel}; border-radius: 12px; padding: 8px 12px; color: {t.text_secondary}; }}
    QLabel#nameSearchQuestion {{ font-size: 15px; font-weight: 800; padding-top: 6px; }}
    QPushButton#nameSearchClose {{ background: {t.panel}; border: 0; border-radius: 16px; font-size: 16px; color: {t.text}; }}
    QPushButton#nameSearchClose:hover {{ background: {t.selected}; }}
    QPushButton#nameSearchLanguage {{ background: {t.surface}; border: 1.5px solid {t.border_strong}; border-radius: 15px;
        padding: 5px 14px; font-weight: 600; color: {t.text}; }}
    QPushButton#nameSearchLanguage:hover {{ border-color: {t.accent}; }}
    QPushButton#nameSearchLanguage:checked {{ background: {t.accent_soft}; border-color: {t.accent}; color: {t.accent}; }}
    QPushButton#nameSearchScope {{ background: {t.surface}; border: 1.5px solid {t.border}; border-radius: 14px;
        text-align: left; padding: 0; min-height: 58px; max-height: 58px; }}
    QPushButton#nameSearchScope:hover {{ border-color: {t.border_strong}; }}
    QPushButton#nameSearchScope:checked {{ border: 2px solid {t.accent}; background: {t.surface_elevated}; }}
    QPushButton#nameSearchScope:disabled {{ background: {t.panel}; }}
    QLabel#nameSearchScopeTitle {{ font-weight: 700; }}
    QLabel#nameSearchScopeSub, QLabel#nameSearchEstimate {{ color: {t.text_secondary}; font-size: 12px; }}
    QLabel#nameSearchScopeCount {{ color: {t.text_secondary}; font-weight: 800; }}
    QFrame#nameSearchAi {{ border-radius: 12px; }}
    QFrame#nameSearchAi[web="yes"] {{ background: {t.accent_soft}; }}
    QFrame#nameSearchAi[web="no"] {{ background: {t.warning_soft}; }}
    QPushButton#nameSearchSwitch {{ background: {t.surface}; border: 1.5px solid {t.border_strong}; border-radius: 10px;
        padding: 4px 10px; font-weight: 600; color: {t.text}; }}
    QPushButton#nameSearchSwitch:hover {{ border-color: {t.accent}; }}
    QFrame#nameSearchFoot {{ border-top: 1px solid {t.border}; }}
    QPushButton#nameSearchStart {{ background: {t.accent}; color: white; border: 0; border-radius: 12px;
        padding: 8px 18px; font-weight: 700; }}
    QPushButton#nameSearchStart:hover {{ background: {t.accent_hover}; }}
    QPushButton#nameSearchStart:disabled {{ background: {t.disabled}; }}
    QPushButton#nameSearchCancel {{ background: {t.surface}; border: 1.5px solid {t.border_strong}; border-radius: 12px;
        padding: 7px 16px; font-weight: 600; color: {t.text}; }}
    QCheckBox#nameSearchTrial {{ color: {t.text}; spacing: 8px; background: transparent; }}
    """


class NameSearchSheet(QDialog):
    """Ask what to look up; ``chosen()`` returns (language, concept ids)."""

    def __init__(self, page, code: str = 'en', *, selected=()):
        super().__init__(page)
        self.page = page
        self.code = m.locale(code) if code and code != 'und' else 'en'
        self.selected = [i for i in selected if i]
        self.concepts = m.read_concepts(page.legacy, page._library_key())
        self.setObjectName('nameSearchSheet')
        self.setWindowTitle('查外语官方名')
        from ..design.studio_theme import _active_theme, apply_secondary_surface_theme, build_secondary_surface_qss
        apply_secondary_surface_theme(self)
        theme = _active_theme(None)
        self.setStyleSheet(build_secondary_surface_qss(theme) + _qss(theme))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.root = QWidget()
        self.root.setObjectName('nameSearchRoot')
        self.root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self.root)
        column = QVBoxLayout(self.root)
        column.setContentsMargins(22, 16, 22, 0)
        column.setSpacing(8)

        self.header = QWidget()
        head = QHBoxLayout(self.header)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        try:
            from ..app.settings_widgets import Bunny
            head.addWidget(Bunny(38))
        except Exception:  # the mascot is decoration only
            pass
        title = QLabel('给词条查外语官方名')
        title.setObjectName('nameSearchTitle')
        head.addWidget(title, 1)
        close = QPushButton('✕')
        close.setObjectName('nameSearchClose')
        close.setFixedSize(32, 32)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        head.addWidget(close)
        column.addWidget(self.header)
        tip = QLabel('AI 会去官网、国际服商店页和维基找每个词的官方写法，查不到就空着，不会照字面硬翻。'
                     '结果先放进「待处理」，你点确认才生效。')
        tip.setObjectName('nameSearchTip')
        tip.setWordWrap(True)
        column.addWidget(tip)

        column.addWidget(self._question('查哪种语言？'))
        self.language_row = QHBoxLayout()
        self.language_row.setSpacing(8)
        self.language_group = QButtonGroup(self)
        self.language_group.setExclusive(True)
        self.language_buttons: dict[str, QPushButton] = {}
        for code in dict.fromkeys([*QUICK_LANGUAGES, self.code]):
            self._add_language(code)
        self.more_language = QPushButton('其他 ▾')
        self.more_language.setObjectName('nameSearchLanguage')
        self.more_language.setCursor(Qt.CursorShape.PointingHandCursor)
        menu = QMenu(self.more_language)
        for code, label in m.LANGUAGES.items():
            if code not in ('und', *self.language_buttons):
                menu.addAction(label, lambda c=code: self._pick_other(c))
        self.more_language.setMenu(menu)
        self.language_row.addWidget(self.more_language)
        self.language_row.addStretch(1)
        column.addLayout(self.language_row)

        column.addWidget(self._question('查哪些词？'))
        self.scope_group = QButtonGroup(self)
        self.scope_group.setExclusive(True)
        self.scope_buttons: dict[str, QPushButton] = {}
        self.scope_labels: dict[str, tuple[QLabel, QLabel]] = {}
        for key, _title, sub in SCOPES:
            button = QPushButton()
            button.setObjectName('nameSearchScope')
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            row = QHBoxLayout(button)
            row.setContentsMargins(14, 9, 14, 9)
            row.setSpacing(10)
            texts = QVBoxLayout()
            texts.setSpacing(1)
            name = QLabel()
            name.setObjectName('nameSearchScopeTitle')
            note = QLabel(sub)
            note.setObjectName('nameSearchScopeSub')
            texts.addWidget(name)
            texts.addWidget(note)
            row.addLayout(texts, 1)
            count = QLabel()
            count.setObjectName('nameSearchScopeCount')
            row.addWidget(count)
            for label in (name, note, count):
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            button.setMinimumHeight(54)
            button.clicked.connect(self._refresh)
            self.scope_group.addButton(button)
            self.scope_buttons[key] = button
            self.scope_labels[key] = (name, count)
            column.addWidget(button)
        self.scope_buttons['selected' if self.selected else 'missing'].setChecked(True)
        self.scope_buttons['selected'].setEnabled(bool(self.selected))

        self.ai_box = QFrame()
        self.ai_box.setObjectName('nameSearchAi')
        self.ai_box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        ai = QVBoxLayout(self.ai_box)
        ai.setContentsMargins(12, 10, 12, 10)
        ai.setSpacing(6)
        self.ai_text = QLabel()
        self.ai_text.setWordWrap(True)
        ai.addWidget(self.ai_text)
        self.switch_row = QHBoxLayout()
        self.switch_row.setSpacing(6)
        ai.addLayout(self.switch_row)
        column.addSpacing(4)
        column.addWidget(self.ai_box)

        self.trial = QCheckBox(f'先试 {TRIAL} 条，满意再查剩下的（省钱，也能先看看质量）')
        self.trial.setObjectName('nameSearchTrial')
        self.trial.setChecked(True)
        self.trial.toggled.connect(self._refresh)
        column.addWidget(self.trial)

        foot = QFrame()
        foot.setObjectName('nameSearchFoot')
        f = QHBoxLayout(foot)
        f.setContentsMargins(0, 12, 0, 16)
        f.setSpacing(8)
        self.estimate = QLabel()
        self.estimate.setObjectName('nameSearchEstimate')
        self.estimate.setWordWrap(True)
        f.addWidget(self.estimate, 1)
        cancel = QPushButton('取消')
        cancel.setObjectName('nameSearchCancel')
        cancel.clicked.connect(self.reject)
        f.addWidget(cancel)
        self.start = QPushButton('开始查')
        self.start.setObjectName('nameSearchStart')
        self.start.setDefault(True)
        self.start.clicked.connect(self.accept)
        f.addWidget(self.start)
        column.addSpacing(4)
        column.addWidget(foot)
        for button in self.findChildren(QPushButton):
            if button is not self.start:
                button.setAutoDefault(False)
        self._refresh()
        from ..app.rounded_window import RoundedWindow
        self.chrome = RoundedWindow(self, self.root, title_areas=[self.header], radius=22, maximizable=False)
        self.setMinimumWidth(600)

    # ---------------------------------------------------------------- build
    @staticmethod
    def _question(text):
        label = QLabel(text)
        label.setObjectName('nameSearchQuestion')
        return label

    def _add_language(self, code):
        button = QPushButton(m.LANGUAGES.get(code, code))
        button.setObjectName('nameSearchLanguage')
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setChecked(code == self.code)
        button.clicked.connect(lambda _c=False, c=code: self._pick(c))
        self.language_group.addButton(button)
        self.language_buttons[code] = button
        index = self.language_row.count() - (2 if hasattr(self, 'more_language') else 0)
        self.language_row.insertWidget(max(0, index), button)

    def _pick(self, code):
        self.code = code
        self._refresh()

    def _pick_other(self, code):
        if code not in self.language_buttons:
            self._add_language(code)
        self.language_buttons[code].setChecked(True)
        self._pick(code)

    # ---------------------------------------------------------------- state
    def scope(self) -> str:
        return next((key for key, button in self.scope_buttons.items() if button.isChecked()), 'missing')

    def _ids(self, scope: str) -> list[str]:
        if scope == 'selected':
            return list(self.selected)
        if scope == 'missing':
            return [c['id'] for c in self.concepts if m.translation_state(c, self.code) != 'confirmed']
        return [c['id'] for c in self.concepts]

    def chosen(self) -> tuple[str, list[str]]:
        ids = self._ids(self.scope())
        return self.code, ids[:TRIAL] if self.trial.isChecked() else ids

    def capability(self) -> dict:
        from .glossary_skill import detect_search_capability
        try:
            return detect_search_capability(self.page._ai_update_settings())
        except Exception:
            return {'provider_search': False, 'tool_search': False}

    def _switch_options(self):
        """Search-capable services in the page's AI picker (index, label)."""
        from .glossary_skill import detect_search_capability, settings_with_service_override
        combo = getattr(self.page, 'ai_service_combo', None)
        if combo is None:
            return []
        base = dict(getattr(self.page.legacy, 'RUNTIME_SETTINGS', {}) or {})
        options = []
        for index in range(combo.count()):
            service = str(combo.itemData(index) or '')
            if not service or index == combo.currentIndex():
                continue
            try:
                capability = detect_search_capability(settings_with_service_override(base, service))
            except Exception:
                continue
            if capability.get('provider_search') or capability.get('tool_search'):
                options.append((index, combo.itemText(index).split('（')[0]))
        return options[:3]

    def _switch(self, index):
        self.page.ai_service_combo.setCurrentIndex(index)
        self._refresh()

    def _refresh(self, *_args):
        label = m.LANGUAGES.get(self.code, self.code)
        for key, title, _sub in SCOPES:
            name, count = self.scope_labels[key]
            name.setText(title.format(label=label))
            count.setText(f'{len(self._ids(key))} 条')
        capability = self.capability()
        web = bool(capability.get('provider_search') or capability.get('tool_search'))
        ai_name = ''
        combo = getattr(self.page, 'ai_service_combo', None)
        if combo is not None:
            ai_name = combo.currentText().split('（')[0]
        model = str(capability.get('model') or '')
        who = ' / '.join(part for part in (ai_name, model) if part) or '当前 AI'
        if capability.get('provider_search'):
            self.ai_text.setText(f'● 用 {who}，能自己上网查官方资料。')
        elif capability.get('tool_search'):
            self.ai_text.setText(f'● 用 {who}：软件先用 DeepSeek 搜索每个词，再交给模型核对；只收下搜索真找到的网页。')
        else:
            self.ai_text.setText(f'○ 现在用的 {who} 不能上网，只能照字面猜，国际服的官方名大多会不对。')
        self.ai_box.setProperty('web', 'yes' if web else 'no')
        self.ai_box.style().unpolish(self.ai_box)
        self.ai_box.style().polish(self.ai_box)
        while self.switch_row.count():
            item = self.switch_row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if not web:
            for index, name in self._switch_options():
                button = QPushButton(f'换成 {name}', self.ai_box)
                button.setObjectName('nameSearchSwitch')
                button.setAutoDefault(False)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.clicked.connect(lambda _c=False, i=index: self._switch(i))
                self.switch_row.addWidget(button)
            self.switch_row.addStretch(1)
        language, ids = self.chosen()
        total = len(self._ids(self.scope()))
        from .translation_name_candidates import TOOL_BATCH_SIZE, WEB_BATCH_SIZE
        size = TOOL_BATCH_SIZE if capability.get('tool_search') and not capability.get('provider_search') else WEB_BATCH_SIZE
        requests = -(-len(ids) // size) if ids else 0
        text = f'这次查 {len(ids)} 条，约 {requests} 次 AI 请求'
        if capability.get('tool_search') and not capability.get('provider_search') and ids:
            from ..providers.deepseek_tools import estimate_cost_usd
            searches = len(ids) + sum(1 for c in self.concepts if c['id'] in set(ids) and language in c['names'])
            text += f'、约 {searches} 次 DeepSeek 搜索（约 {estimate_cost_usd(searches):.2f} 美元）'
        if self.trial.isChecked() and total > len(ids):
            text += f'；剩下 {total - len(ids)} 条看过结果再查'
        self.estimate.setText(text + '。')
        self.start.setEnabled(bool(ids))
        self.start.setText('开始查' if web else '仍然开始（只靠猜）')
