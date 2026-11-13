"""Multilingual editing on the existing glossary page and project settings."""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from PySide6.QtCore import Qt, QObject, Signal, QTimer, QRect, QSize, QPoint
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QComboBox, QListWidget, QListWidgetItem, QDialogButtonBox,
    QMessageBox, QCheckBox, QWidget, QInputDialog, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QScrollArea, QSizePolicy, QLayout, QFrame, QMenu)
from . import multilingual_terms as m
from .glossary_page_parts import FlowLayout


def language_combo(parent=None, *, unspecified=True):
    combo = QComboBox(parent)
    for code, label in m.LANGUAGES.items():
        if unspecified or code != 'und': combo.addItem(label, code)
    return combo


def summary(c):
    return ' · '.join(f'{code}: {row["name"]}' for code, row in c['names'].items())


class _Row(QFrame):
    clicked = Signal()

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton: self.clicked.emit()
        super().mousePressEvent(event)


def _restyle(widget):
    widget.style().unpolish(widget); widget.style().polish(widget)


CATEGORIES = ('角色', '人物', '选手 ID', 'Boss', '技能', '物品', '装备', '地点', '阵营', '机制', '活动', '货币', '玩家用语', '其他')


class NamesEditor(QDialog):
    """「名称与译名」. 2026-11-13 (plan 2026-11-13-glossary-library-redesign-c),
    laid out after draft C: header with ‹ › ×, the concept name and category
    chip, what the card display language translates to (one-click confirm),
    then ① 听写识别 ② 各语言译名 ③ 待审核 ④ 说明, and a footer with the unsaved
    count, 还原 and 保存. A language's fields open under the list when its row
    is clicked. ``embedded`` puts it in the page's right-side drawer; without
    it the same editor is a dialog (tests, other callers)."""
    saved = Signal(object)

    def __init__(self, page, record, *, embedded=False):
        super().__init__(page)
        self.page, self.library_id = page, page._library_key()
        self.embedded = embedded
        self.original = copy.deepcopy(record)
        self.draft = copy.deepcopy(record)
        self.current = None
        self._loading = False
        self.setObjectName('multilingualNamesEditor')
        self.setProperty('embedded', embedded)
        self.setWindowTitle('名称与译名')
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        if embedded: root.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)

        # Header: caption and navigation, name and category, translation banner.
        head = QWidget(); head.setObjectName('termDrawerHead'); head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        head_layout = QVBoxLayout(head); head_layout.setContentsMargins(22, 16, 22, 14); head_layout.setSpacing(10)
        top = QHBoxLayout(); top.setSpacing(6)
        caption = QLabel('名称与译名'); caption.setObjectName('termDrawerCaption'); top.addWidget(caption, 1)
        # 2026-11-13 (user): parented to the header, or setVisible(True) showed
        # each button as its own blank window for a moment on every card switch.
        self.prev_button, self.next_button, self.close_button = (QPushButton(t, head) for t in ('‹', '›', '×'))
        for button, tip in ((self.prev_button, '上一张卡片'), (self.next_button, '下一张卡片'), (self.close_button, '关闭')):
            button.setObjectName('termDrawerNav'); button.setFixedSize(32, 32); button.setToolTip(tip)
            top.addWidget(button); button.setVisible(embedded)
        self.prev_button.clicked.connect(lambda: self.go(-1)); self.next_button.clicked.connect(lambda: self.go(1))
        self.close_button.clicked.connect(self.reject)
        head_layout.addLayout(top)
        title_row = QHBoxLayout(); title_row.setSpacing(10)
        self.title = QLabel(); self.title.setObjectName('termDrawerTitle'); title_row.addWidget(self.title)
        self.category = QLineEdit(record.get('category', '其他')); self.category.hide()
        self.category_button = QPushButton(); self.category_button.setObjectName('termDrawerCategory')
        self.category_menu = QMenu(self.category_button)
        for name in dict.fromkeys((record.get('category', '其他'), *CATEGORIES)):
            self.category_menu.addAction(name, lambda n=name: self.set_category(n))
        self.category_menu.addSeparator(); self.category_menu.addAction('自定义…', self.custom_category)
        self.category_button.setMenu(self.category_menu)
        title_row.addWidget(self.category_button, 0, Qt.AlignmentFlag.AlignVCenter); title_row.addStretch(1)
        head_layout.addLayout(title_row)
        self.banner = QWidget(); self.banner.setObjectName('termDrawerBanner')
        self.banner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        banner = QHBoxLayout(self.banner); banner.setContentsMargins(12, 10, 10, 10); banner.setSpacing(10)
        self.banner_text = QLabel(); self.banner_text.setObjectName('termDrawerBannerText'); self.banner_text.setWordWrap(True)
        banner.addWidget(self.banner_text, 1)
        self.banner_button = QPushButton('确认'); self.banner_button.setObjectName('termDrawerBannerButton')
        self.banner_button.clicked.connect(self.confirm_display); banner.addWidget(self.banner_button)
        head_layout.addWidget(self.banner)
        root.addWidget(head)

        scroll = QScrollArea(self); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setObjectName('termDrawerScroll')
        body = QWidget(); body.setObjectName('termDrawerBody'); scroll.setWidget(body)
        layout = QVBoxLayout(body); layout.setContentsMargins(22, 14, 18, 14); layout.setSpacing(8)
        root.addWidget(scroll, 1)

        def section(text, extra=None):
            row = QHBoxLayout(); row.setSpacing(8)
            label = QLabel(text); label.setObjectName('termDrawerSection'); row.addWidget(label)
            if extra is not None: row.addWidget(extra)
            row.addStretch(1); layout.addSpacing(6); layout.addLayout(row)

        # ① 听写识别: the source name's misrecognitions as chips.
        section('① 听写识别')
        heard = QWidget(); self.heard_flow = FlowLayout(heard); layout.addWidget(heard)
        self.heard_input = QLineEdit(); self.heard_input.setObjectName('termDrawerInlineInput')
        self.heard_input.setPlaceholderText('输入常被听成的写法，回车添加'); self.heard_input.hide()
        self.heard_input.returnPressed.connect(self.add_heard); layout.addWidget(self.heard_input)

        # ② 各语言译名: one compact row per language; a click opens its fields.
        self.name_count = QLabel(); self.name_count.setObjectName('termDrawerCount')
        section('② 各语言译名', self.name_count)
        self.name_list = QFrame(); self.name_list.setObjectName('termDrawerList')
        self.name_rows = QVBoxLayout(self.name_list); self.name_rows.setContentsMargins(0, 0, 0, 0); self.name_rows.setSpacing(0)
        layout.addWidget(self.name_list)
        self.names = QListWidget(); self.names.hide()  # selection model behind the rows
        self.names.currentRowChanged.connect(self.select_name)
        self.edit_panel = QFrame(); self.edit_panel.setObjectName('termDrawerEdit'); self.edit_panel.hide()
        edit = QVBoxLayout(self.edit_panel); edit.setContentsMargins(12, 10, 12, 10); edit.setSpacing(6)
        self.edit_title = QLabel(); self.edit_title.setObjectName('termDrawerEditTitle'); edit.addWidget(self.edit_title)
        form = QFormLayout(); form.setSpacing(6); form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.standard = QLineEdit(); self.standard.setObjectName('termStandardName')
        self.aliases, self.mishearings, self.mistranslations = QLineEdit(), QLineEdit(), QLineEdit()
        self.aliases.setPlaceholderText('也算对的写法，用 | 分隔')
        self.mishearings.setPlaceholderText('识别常听成的写法，用 | 分隔')
        self.mistranslations.setPlaceholderText('译文里出现就提示的错误译法')
        for text, field in (('名称', self.standard), ('合法别名', self.aliases), ('常被听成', self.mishearings), ('错误译法', self.mistranslations)):
            field.setObjectName(field.objectName() or 'termDrawerField'); form.addRow(text, field)
            field.textEdited.connect(self.mark_dirty)
        edit.addLayout(form)
        self.state = QLabel(); self.state.setObjectName('termHint')
        actions = QHBoxLayout(); actions.setSpacing(6); actions.addWidget(self.state, 1)
        self.confirm_name_button = QPushButton('确认此语言'); self.confirm_name_button.setObjectName('termToolButton')
        self.confirm_name_button.setToolTip('只确认这一种语言；保存后才写入词库')
        self.confirm_name_button.clicked.connect(self.confirm_name); actions.addWidget(self.confirm_name_button)
        remove = QPushButton('删除'); remove.setObjectName('termGhostButton'); remove.clicked.connect(self.remove_language)
        actions.addWidget(remove)
        more = QPushButton('更多 ▾'); more.setObjectName('termGhostButton'); more.setCheckable(True); actions.addWidget(more)
        edit.addLayout(actions)
        self.advanced = QWidget(); advanced = QFormLayout(self.advanced); advanced.setContentsMargins(0, 4, 0, 0)
        self.language = language_combo(); self.language.setObjectName('termNameLanguage')
        self.unify = QCheckBox('合法别名统一为这个名称（默认保留正确简称）')
        self.correction = QCheckBox('用于这种语言的原文识别／校对')
        self.emphasis = QCheckBox('保留关键词强调用途')
        self.sources = QPlainTextEdit(); self.sources.setMaximumHeight(60)
        link = QPushButton('关联已有术语…'); link.setObjectName('termGhostButton'); link.clicked.connect(self.link)
        for text, field in (('语言', self.language), ('统一写法', self.unify), ('原文用途', self.correction),
                            ('字幕强调', self.emphasis), ('来源（每行一项）', self.sources), ('', link)):
            advanced.addRow(text, field)
        edit.addWidget(self.advanced); self.advanced.hide(); more.toggled.connect(self.advanced.setVisible)
        layout.addWidget(self.edit_panel)
        self.add_row = QFrame(); self.add_row.setObjectName('termDrawerEdit'); self.add_row.hide()
        add = QHBoxLayout(self.add_row); add.setContentsMargins(10, 8, 10, 8); add.setSpacing(6)
        self.add_language_combo = QComboBox(); self.add_name = QLineEdit(); self.add_name.setPlaceholderText('这种语言的名称')
        self.add_name.returnPressed.connect(self.commit_language)
        add_ok = QPushButton('添加'); add_ok.setObjectName('termToolButton'); add_ok.clicked.connect(self.commit_language)
        add_cancel = QPushButton('取消'); add_cancel.setObjectName('termGhostButton'); add_cancel.clicked.connect(self.add_row.hide)
        for widget in (self.add_language_combo, self.add_name, add_ok, add_cancel): add.addWidget(widget, 1 if widget is self.add_name else 0)
        layout.addWidget(self.add_row)
        add_link = QPushButton('＋ 添加语言'); add_link.setObjectName('termDrawerLink'); add_link.clicked.connect(self.add_language)
        layout.addWidget(add_link, 0, Qt.AlignmentFlag.AlignLeft)

        # ③ 待审核: name candidates, each with 忽略 / 采用.
        self.candidate_badge = QLabel(); self.candidate_badge.setObjectName('termDrawerBadge')
        section('③ 待审核', self.candidate_badge)
        self.candidate_box = QVBoxLayout(); self.candidate_box.setSpacing(6); layout.addLayout(self.candidate_box)
        self.candidate_label = QLabel(); self.candidate_label.setObjectName('termHint'); layout.addWidget(self.candidate_label)

        # ④ 说明: shared by every language.
        section('④ 说明')
        self.description = QLineEdit(record.get('description', '')); self.description.setObjectName('termDrawerNote')
        self.description.setPlaceholderText('给 AI 的上下文，如「宠物名，玳瑁龟造型，不要按字面译」')
        self.description.textEdited.connect(self.mark_dirty)
        layout.addWidget(self.description)
        layout.addStretch(1)

        foot = QWidget(); foot.setObjectName('termDrawerFoot'); foot.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        foot_layout = QHBoxLayout(foot); foot_layout.setContentsMargins(22, 12, 22, 12); foot_layout.setSpacing(8)
        self.message = QLabel(); self.message.setObjectName('termDrawerStatus'); self.message.setWordWrap(True)
        foot_layout.addWidget(self.message, 1)
        if not embedded:
            cancel = QPushButton('取消'); cancel.setObjectName('termGhostButton'); cancel.clicked.connect(self.reject)
            foot_layout.addWidget(cancel)
        self.revert_button = QPushButton('还原'); self.revert_button.setObjectName('termToolButton')
        self.revert_button.clicked.connect(self.revert); foot_layout.addWidget(self.revert_button)
        self.save_button = QPushButton('保存'); self.save_button.setObjectName('termAccentButton')
        self.save_button.clicked.connect(self.save); foot_layout.addWidget(self.save_button)
        root.addWidget(foot)
        if not embedded and self.screen():
            self.resize(min(500, self.screen().availableGeometry().width() - 60),
                        min(760, self.screen().availableGeometry().height() - 70))
        self.reload_names()

    # ---------------------------------------------------------- presentation
    def display_language(self):
        combo = getattr(self.page, 'term_display_language', None)
        return combo.currentData() if combo is not None else ''

    def source_code(self):
        return next(iter(self.draft['names']), None)

    def set_category(self, name):
        self.category.setText(name); self.category_button.setText(f'{name} ▾'); self.mark_dirty()

    def custom_category(self):
        name, ok = QInputDialog.getText(self, '分类', '分类名称', text=self.category.text())
        if ok and name.strip(): self.set_category(name.strip())

    def refresh_banner(self):
        """「翻译到 X 时 → Y」for the card display language, with one-click confirm."""
        names = self.draft['names']
        self.title.setText(next(iter(names.values()))['name'] if names else '')
        self.category_button.setText(f'{self.category.text() or "其他"} ▾')
        from .glossary_term_cards import category_colors
        fill, ink, _dot = category_colors(self.category.text() or '其他')
        self.category_button.setStyleSheet(f'QPushButton#termDrawerCategory {{ background: {fill.name()}; color: {ink.name()}; }}')
        code = self.display_language()
        if not code or not names or code == self.source_code():
            self.banner.hide(); return
        label = m.LANGUAGES.get(code, code)
        state = m.translation_state(self.draft, code)
        if state == 'missing':
            text, button = f'翻译到 <b>{label}</b> 时：还没有译名', 'AI 联网查'
        elif state == 'candidate':
            first = self.draft['candidates'][code][0]
            where = '官方资料' if first.get('formality') == 'official' else '社区资料' if first.get('formality') else 'AI 推测'
            text, button = f'翻译到 <b>{label}</b> 时 → <b>{first.get("name", "")}</b><br><small>{where}，采用后才用于翻译</small>', '采用'
        else:
            name = names[code]['name']
            if state == 'confirmed':
                text, button = f'翻译到 <b>{label}</b> 时 → <b>{name}</b><br><small>已确认，翻译时固定使用</small>', ''
            else:
                text, button = f'翻译到 <b>{label}</b> 时 → <b>{name}</b><br><small>尚未确认，翻译时只作参考</small>', '确认'
        self.banner.setProperty('state', state); _restyle(self.banner)
        self.banner_text.setText(text)
        self.banner_button.setText(button); self.banner_button.setVisible(bool(button))
        self.banner.show()

    def _status_widget(self, kind, text=''):
        label = QLabel(text or {'confirmed': '✓', 'pending': '待确认', 'candidate': 'AI'}.get(kind, ''))
        label.setObjectName({'confirmed': 'termDrawerCheck', 'pending': 'termDrawerPending', 'candidate': 'termDrawerAI'}.get(kind, 'termHint'))
        return label

    def rebuild_rows(self):
        while self.name_rows.count():
            item = self.name_rows.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        display, source = self.display_language(), self.source_code()
        rows = [(code, row['name'], 'confirmed' if m.is_confirmed(row) else 'pending') for code, row in self.draft['names'].items()]
        for code, candidates in self.draft.get('candidates', {}).items():
            if code not in self.draft['names'] and candidates: rows.append((code, candidates[0].get('name', ''), 'candidate'))
        if display and display not in {r[0] for r in rows}: rows.append((display, '', 'missing'))
        confirmed = sum(1 for r in rows if r[2] == 'confirmed')
        self.name_count.setText(f'{confirmed} 已确认 / {len(rows)}')
        for index, (code, name, state) in enumerate(rows):
            row = _Row(); row.setObjectName('termDrawerRow')
            row.setProperty('display', code == display); row.setProperty('selected', code == self.current and not self.edit_panel.isHidden())
            row.setProperty('first', index == 0); row.setProperty('last', index == len(rows) - 1)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            line = QHBoxLayout(row); line.setContentsMargins(12, 9, 12, 9); line.setSpacing(10)
            tag = QLabel('源' if code == source else m.SHORT_LANGUAGES.get(code, code.upper()[:2]))
            tag.setObjectName('termDrawerTagSource' if code == source else 'termDrawerTagShown' if code == display else 'termDrawerTag')
            tag.setFixedWidth(30); line.addWidget(tag)
            text = QLabel(name or '尚未填写'); text.setObjectName('termDrawerRowSource' if code == source else 'termDrawerRowName' if name else 'termDrawerRowEmpty')
            line.addWidget(text, 1)
            if code == source:
                lang = QLabel(m.LANGUAGES.get(code, code)); lang.setObjectName('termDrawerRowLang'); line.addWidget(lang)
            if state == 'missing':
                generate = QPushButton('AI 生成'); generate.setObjectName('termDrawerSmall')
                generate.setToolTip('AI 联网查这种语言的官方名称，结果进「待审核」')
                generate.clicked.connect(lambda _c=False, c=code: self.generate(c)); line.addWidget(generate)
            else:
                line.addWidget(self._status_widget(state))
            if state in ('confirmed', 'pending'):
                row.clicked.connect(lambda c=code: self.open_language(c))
            elif state == 'missing':
                row.clicked.connect(lambda c=code: self.add_language(c))
            self.name_rows.addWidget(row)

    def rebuild_heard(self):
        while self.heard_flow.count():
            item = self.heard_flow.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        label = QLabel('常被听成'); label.setObjectName('termDrawerChipLabel'); label.setFixedHeight(28); self.heard_flow.addWidget(label)
        source = self.source_code()
        for word in (self.draft['names'][source].get('mishearings', ()) if source else ()):
            chip = QPushButton(word); chip.setObjectName('termDrawerChip'); chip.setToolTip('点击移除'); chip.setFixedHeight(28)
            chip.clicked.connect(lambda _c=False, w=word: self.remove_heard(w)); self.heard_flow.addWidget(chip)
        plus = QPushButton('＋'); plus.setObjectName('termDrawerChipAdd'); plus.setToolTip('添加常被听成的写法')
        plus.setFixedSize(34, 28)
        plus.clicked.connect(lambda: (self.heard_input.show(), self.heard_input.setFocus())); self.heard_flow.addWidget(plus)

    def rebuild_candidates(self):
        while self.candidate_box.count():
            item = self.candidate_box.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        total = 0
        for code, candidates in self.draft.get('candidates', {}).items():
            for candidate in candidates:
                total += 1
                row = QFrame(); row.setObjectName('termDrawerCandidate')
                line = QHBoxLayout(row); line.setContentsMargins(12, 8, 10, 8); line.setSpacing(8)
                words = QVBoxLayout(); words.setSpacing(1)
                name = QLabel(f'<span style="font-size:11px;font-weight:700">{m.SHORT_LANGUAGES.get(code, code.upper()[:2])}</span>&nbsp; {candidate.get("name", "")}')
                name.setObjectName('termDrawerCandidateName'); words.addWidget(name)
                where = {'official': '官方资料', 'community': '社区资料'}.get(candidate.get('formality'), 'AI 推测，未联网')
                note = str(candidate.get('note') or '')
                detail = QLabel(where + (f' · {note}' if note and note not in ('官方资料', '社区资料') else ''))
                detail.setObjectName('termDrawerCandidateNote'); detail.setWordWrap(True)
                detail.setToolTip('\n'.join(map(str, candidate.get('sources', ()))) or where)
                words.addWidget(detail); line.addLayout(words, 1)
                ignore = QPushButton('忽略'); ignore.setObjectName('termGhostButton')
                ignore.clicked.connect(lambda _c=False, c=code, i=candidate['id']: self.decide(c, i, False))
                accept = QPushButton('采用'); accept.setObjectName('termToolButton')
                accept.clicked.connect(lambda _c=False, c=code, i=candidate['id']: self.decide(c, i, True))
                line.addWidget(ignore); line.addWidget(accept)
                self.candidate_box.addWidget(row)
        self.candidate_badge.setText(str(total)); self.candidate_badge.setVisible(bool(total))
        self.candidate_label.setText('' if total else '没有待审核的译名候选')
        self.candidate_label.setVisible(not total)

    def mark_dirty(self, *_args):
        if self._loading: return
        try:
            self.store_fields()
        except ValueError as exc:
            self.message.setText(str(exc)); return
        self.update_status()

    def update_status(self, text=''):
        draft = dict(self.draft, category=self.category.text().strip() or '其他', description=self.description.text().strip())
        keys = {*draft['names'], *self.original['names']}
        changed = sum(draft['names'].get(k) != self.original['names'].get(k) for k in keys)
        changed += (draft['category'] != self.original.get('category', '其他')) + (draft['description'] != self.original.get('description', ''))
        self.message.setText(text or (f'有 {changed} 处修改未保存' if changed else '没有未保存的修改'))
        self.revert_button.setEnabled(bool(changed))

    # ---------------------------------------------------------- state
    def has_unsaved(self):
        try:
            self.store_fields()
        except ValueError:
            return True
        draft = dict(self.draft, category=self.category.text().strip() or '其他', description=self.description.text().strip())
        return draft != self.original

    def store_fields(self):
        if self.current is None or self.current not in self.draft['names']: return
        code = self.language.currentData()
        if code != self.current and code in self.draft['names']:
            raise ValueError('该语言已有名称，请编辑已有行或关联时选择')
        prior = self.draft['names'][self.current]
        fields = dict(name=self.standard.text().strip(), aliases=m.words(self.aliases.text()),
            mishearings=m.words(self.mishearings.text()), mistranslations=m.words(self.mistranslations.text()),
            unify_aliases=self.unify.isChecked(), correction_enabled=self.correction.isChecked(), emphasis_enabled=self.emphasis.isChecked())
        if not fields['name']: raise ValueError('名称不能为空；要删除这种语言请点「删除」')
        source_text = self.sources.toPlainText()
        old_source = '\n'.join(str(s) for s in prior.get('sources', ()))
        sources = m.words(source_text) if source_text != old_source else copy.deepcopy(prior.get('sources', []))
        changed = code != self.current or any(fields[k] != prior.get(k, [] if k in {'aliases', 'mishearings', 'mistranslations'}
            else True if k == 'correction_enabled' else False if k in {'unify_aliases', 'emphasis_enabled'} else '') for k in fields)
        if changed or source_text != old_source:
            new = m.name_record(**{**prior, **fields, 'confirmed': True, 'sources': sources,
                                   'user_modified': True, 'confirmation_action': 'manual_save'})
        else: new = copy.deepcopy(prior)
        old_code = self.current
        self.draft['names'] = {code if key == old_code else key: new if key == old_code else value
                               for key, value in self.draft['names'].items()}
        self.current = code
        for i in range(self.names.count()):
            item = self.names.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == old_code:
                item.setData(Qt.ItemDataRole.UserRole, code); item.setText(new['name'])

    def reload_names(self, selected=None):
        self._loading = True
        self.current = None
        self.names.blockSignals(True); self.names.clear()
        for code, row in self.draft['names'].items():
            item = QListWidgetItem(row['name']); item.setData(Qt.ItemDataRole.UserRole, code); self.names.addItem(item)
        index = list(self.draft['names']).index(selected) if selected in self.draft['names'] else 0
        self.names.setCurrentRow(index); self.names.blockSignals(False)
        self._loading = False
        self.select_name(index)
        self.rebuild_rows(); self.rebuild_heard(); self.rebuild_candidates(); self.refresh_banner(); self.update_status()

    def select_name(self, index):
        try: self.store_fields()
        except ValueError as exc:
            self.message.setText(str(exc)); return
        item = self.names.item(index)
        if item is None: return
        self._loading = True
        self.current = item.data(Qt.ItemDataRole.UserRole)
        row = self.draft['names'][self.current]
        self.language.setCurrentIndex(max(0, self.language.findData(self.current)))
        self.standard.setText(row['name']); self.aliases.setText(' | '.join(row.get('aliases', ())))
        self.mishearings.setText(' | '.join(row.get('mishearings', ())))
        self.mistranslations.setText(' | '.join(row.get('mistranslations', ())))
        self.unify.setChecked(row.get('unify_aliases', False))
        self.correction.setChecked(row.get('correction_enabled', True)); self.emphasis.setChecked(row.get('emphasis_enabled', False))
        self.sources.setPlainText('\n'.join(str(s) for s in row.get('sources', ())))
        self.state.setText(('已确认' if m.is_confirmed(row) else '尚未确认') + (' · 手动维护' if row.get('user_modified') else ''))
        self.confirm_name_button.setEnabled(not m.is_confirmed(row))
        self.edit_title.setText(f'编辑 {m.LANGUAGES.get(self.current, self.current)}')
        self._loading = False

    def open_language(self, code):
        """A row was clicked: open (or close) that language's fields."""
        if code == self.current and not self.edit_panel.isHidden():
            self.edit_panel.hide()
        else:
            if code in self.draft['names']: self.names.setCurrentRow(list(self.draft['names']).index(code))
            self.edit_panel.show(); self.add_row.hide()
        self.rebuild_rows()

    # ---------------------------------------------------------- actions
    def confirm_name(self):
        try:
            self.store_fields()
            self.draft['names'][self.current].update(confirmed=True, status='confirmed', user_modified=True,
                confirmation_action='user_accept_name')
            self.reload_names(self.current)
            self.update_status('已确认这一种语言；点「保存」后写入词库。')
        except Exception as exc: self.message.setText(str(exc))

    def confirm_display(self):
        code = self.display_language()
        state = m.translation_state(self.draft, code) if code else ''
        if state == 'pending':
            self.names.setCurrentRow(list(self.draft['names']).index(code)); self.confirm_name()
        elif state == 'candidate':
            self.decide(code, self.draft['candidates'][code][0]['id'], True)
        elif state == 'missing':
            self.generate(code)

    def add_language(self, code=None):
        try: self.store_fields()
        except ValueError as exc: self.message.setText(str(exc)); return
        available = [c for c in m.LANGUAGES if c not in self.draft['names']]
        self.add_language_combo.clear()
        for c in available: self.add_language_combo.addItem(m.LANGUAGES[c], c)
        self.add_language_combo.setCurrentIndex(max(0, self.add_language_combo.findData(code or self.display_language() or 'en')))
        self.add_name.clear(); self.edit_panel.hide(); self.add_row.show(); self.add_name.setFocus()
        self.rebuild_rows()

    def commit_language(self):
        code, value = self.add_language_combo.currentData(), self.add_name.text().strip()
        if not code or not value: self.message.setText('请选择语言并填写名称'); return
        self.draft['names'][code] = m.name_record(value, sources=['手动'], user_modified=True)
        self.add_row.hide(); self.reload_names(code)

    def remove_language(self):
        if self.current is None: return
        if len(self.draft['names']) == 1:
            if QMessageBox.question(self, '删除词条', '这是最后一个名称。是否删除整个词条？') != QMessageBox.StandardButton.Yes: return
            try:
                m.delete_concept(self.page.legacy, self.library_id, self.draft['id'])
                self.saved.emit(None); self.accept()
            except Exception as exc: self.message.setText(str(exc))
            return
        del self.draft['names'][self.current]; self.current = None; self.edit_panel.hide(); self.reload_names()

    def add_heard(self):
        word, source = self.heard_input.text().strip(), self.source_code()
        self.heard_input.clear(); self.heard_input.hide()
        if not word or source is None: return
        self.store_fields()
        row = self.draft['names'][source]
        if word not in row.get('mishearings', ()):
            self.draft['names'][source] = dict(row, mishearings=[*row.get('mishearings', ()), word], user_modified=True)
        self.reload_names(self.current)

    def remove_heard(self, word):
        source = self.source_code()
        if source is None: return
        self.store_fields()
        row = self.draft['names'][source]
        self.draft['names'][source] = dict(row, mishearings=[w for w in row.get('mishearings', ()) if w != word], user_modified=True)
        self.reload_names(self.current)

    def revert(self):
        self.draft = copy.deepcopy(self.original)
        self.category.setText(self.original.get('category', '其他')); self.description.setText(self.original.get('description', ''))
        self.edit_panel.hide(); self.add_row.hide(); self.reload_names()

    def reload_from_store(self):
        fresh = next((r for r in m.read_concepts(self.page.legacy, self.library_id) if r['id'] == self.draft['id']), None)
        if fresh is None: return
        self.original = fresh; self.draft = copy.deepcopy(fresh); self.reload_names(self.current); self.saved.emit(self.draft)

    def decide(self, code, candidate_id, accept):
        if not self.require_saved(): return
        try:
            from .translation_name_candidates import review_candidates
            review_candidates(self.page.legacy, self.library_id, [(self.draft['id'], code, candidate_id)], accept=accept)
            self.reload_from_store()
            self.update_status('已采用并保存。' if accept else '已忽略这条候选。')
        except Exception as exc: self.message.setText(str(exc))

    def generate(self, code):
        if not self.require_saved(): return
        if getattr(self.page, '_name_completion_active', False):
            self.message.setText('已有联网补全在进行，请稍后'); return
        identity = self.draft['id']
        def done(_stats, editor=self):
            try:
                if editor.draft.get('id') == identity and not editor.has_unsaved(): editor.reload_from_store()
            except RuntimeError:
                pass
        try:
            run_name_search(self.page, [identity], code, on_done=done)
            self.message.setText(f'正在联网查 {m.LANGUAGES.get(code, code)} 名称…结果会出现在「待审核」')
        except Exception as exc: self.message.setText(str(exc))

    def go(self, delta):
        """‹ / ›: open the previous or next card of the page."""
        model = getattr(self.page, '_term_model', None)
        if model is None: return
        ids = [model.data_for_row(i).get('concept_id') for i in range(model.rowCount())]
        ids = [i for i in ids if i]
        if self.draft['id'] not in ids: return
        target = ids[(ids.index(self.draft['id']) + delta) % len(ids)]
        open_editor(self.page, target)

    def persist(self):
        self.store_fields()
        self.draft.update(category=self.category.text().strip() or '其他', description=self.description.text().strip())
        self.original = m.save_concept(self.page.legacy, self.library_id, self.draft, expected=self.original)
        self.draft = copy.deepcopy(self.original)
        self.saved.emit(self.draft)

    def save(self):
        try:
            self.persist()
            if self.embedded:
                self.reload_names(self.current); self.update_status('已保存。')
            else:
                self.accept()
        except Exception as exc: self.message.setText(str(exc))

    def link(self):
        if not self.require_saved(): return
        dialog = LinkDialog(self.page, self.library_id, self.draft, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.original = dialog.result_record; self.draft = copy.deepcopy(self.original)
            self.reload_names(); self.saved.emit(self.draft)

    def review(self):
        if not self.require_saved(): return
        CandidateDialog(self.page, self.library_id, [self.draft['id']], self).exec()
        self.original = next(r for r in m.read_concepts(self.page.legacy, self.library_id) if r['id'] == self.draft['id'])
        self.draft = copy.deepcopy(self.original); self.reload_names(); self.saved.emit(self.draft)

    def require_saved(self):
        try:
            self.store_fields()
            self.draft.update(category=self.category.text().strip() or '其他', description=self.description.text().strip())
            if self.draft != self.original:
                self.message.setText('当前名称有未保存的修改，请先保存；查看候选或打开关联预览不会替你确认这些修改。')
                return False
            return True
        except Exception as exc:
            self.message.setText(str(exc)); return False


class LinkDialog(QDialog):
    def __init__(self, page, library_id, record, parent=None):
        super().__init__(parent); self.page, self.library_id, self.record = page, library_id, record
        self.setWindowTitle('关联已有术语 / 跨库复制译名'); self.resize(720, 540)
        layout = QVBoxLayout(self); layout.addWidget(QLabel('当前：' + summary(record)))
        self.library = QComboBox()
        for lib in page.legacy.glossary_catalog(): self.library.addItem(lib['name'], lib['id'])
        self.library.setCurrentIndex(max(0, self.library.findData(library_id)))
        layout.addWidget(self.library)
        self.search = QLineEdit(); self.search.setPlaceholderText('搜索名称或别名'); layout.addWidget(self.search)
        self.list = QListWidget(); layout.addWidget(self.list)
        self.conflicts = QTableWidget(0, 4); self.conflicts.setHorizontalHeaderLabels(['语言', '当前名称', '关联名称', '保留方式'])
        self.conflicts.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); layout.addWidget(self.conflicts)
        self.message = QLabel(); self.message.setWordWrap(True); layout.addWidget(self.message)
        self.apply = QPushButton(); self.apply.clicked.connect(self.commit); layout.addWidget(self.apply)
        self.library.currentIndexChanged.connect(self.load); self.search.textChanged.connect(self.filter)
        self.list.currentRowChanged.connect(self.preview); self.load()

    def load(self):
        self.rows = [r for r in m.read_concepts(self.page.legacy, self.library.currentData())
                     if r['id'] != self.record['id'] or self.library.currentData() != self.library_id]
        self.filter()

    def filter(self):
        query = self.search.text().casefold(); self.list.clear()
        for r in self.rows:
            text = summary(r)
            extra = ' '.join(a for n in r['names'].values() for a in n.get('aliases', ()))
            if query not in (text + ' ' + extra).casefold(): continue
            item = QListWidgetItem(text); item.setData(Qt.ItemDataRole.UserRole, r); self.list.addItem(item)
        self.preview()

    def preview(self, *args):
        item = self.list.currentItem(); self.conflicts.setRowCount(0); self.choices = []
        self.apply.setEnabled(item is not None)
        cross = self.library.currentData() != self.library_id
        self.apply.setText('复制译名到当前词条（保留另一词库原记录）' if cross else '关联为同一概念（保留当前 ID）')
        if item is None: return
        conflicts = m.merge_preview(self.record, item.data(Qt.ItemDataRole.UserRole)); self.conflicts.setRowCount(len(conflicts))
        for i, conflict in enumerate(conflicts):
            for j, key in enumerate(('language', 'current', 'incoming')):
                cell = QTableWidgetItem(conflict[key]); cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable); self.conflicts.setItem(i, j, cell)
            choice = QComboBox(); choice.addItem('请选择…', ''); choice.addItem('当前为首选，另一名称作合法别名', 'current'); choice.addItem('关联名称为首选，当前作合法别名', 'incoming')
            self.conflicts.setCellWidget(i, 3, choice); self.choices.append((conflict['language'], choice))

    def commit(self):
        try:
            other = self.list.currentItem().data(Qt.ItemDataRole.UserRole)
            self.result_record = m.link_concepts(self.page.legacy, self.library_id, self.record['id'], other['id'],
                {lang: combo.currentData() for lang, combo in self.choices}, source_library=self.library.currentData())
            self.accept()
        except Exception as exc: self.message.setText(str(exc))


class CandidateDialog(QDialog):
    def __init__(self, page, library_id, identities=None, parent=None):
        super().__init__(parent or page); self.page, self.library_id, self.identities = page, library_id, identities
        self.setWindowTitle('译名候选：按语言确认'); self.resize(720, 470)
        layout = QVBoxLayout(self)
        self.list = QListWidget(); self.list.itemChanged.connect(self.count); layout.addWidget(self.list)
        self.note = QLabel(); self.note.setWordWrap(True); layout.addWidget(self.note)
        row = QHBoxLayout()
        all_button = QPushButton('勾选当前列表全部候选'); all_button.clicked.connect(self.select_all); row.addWidget(all_button)
        official = QPushButton('勾选有官方来源的'); official.clicked.connect(self.select_official); row.addWidget(official)
        official.setToolTip('只勾选联网查到官方网页、且不会替换已确认名称的候选；仍需点「确认」')
        self.accept_button = QPushButton('确认所选'); self.accept_button.clicked.connect(lambda: self.review(True)); row.addWidget(self.accept_button)
        reject = QPushButton('拒绝所选候选'); reject.clicked.connect(lambda: self.review(False)); row.addWidget(reject)
        layout.addLayout(row); self.reload()

    def reload(self):
        self.list.clear()
        for c in m.read_concepts(self.page.legacy, self.library_id):
            if self.identities is not None and c['id'] not in self.identities: continue
            for lang, candidates in c.get('candidates', {}).items():
                for candidate in candidates:
                    tag = {'official': '官方来源', 'community': '社区来源'}.get(candidate.get('formality'), '未联网')
                    item = QListWidgetItem(f'{summary(c)}  →  {lang}: {candidate["name"]}　［{tag}］')
                    item.setToolTip('\n'.join([*map(str, candidate.get('sources', [])), candidate.get('note', '')]))
                    item.setData(Qt.ItemDataRole.UserRole, (c['id'], lang, candidate['id']))
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable); item.setCheckState(Qt.CheckState.Unchecked); self.list.addItem(item)
        self.count()

    def selected(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def count(self, *args):
        selected = self.selected(); languages = ', '.join(sorted({r[1] for r in selected}))
        self.accept_button.setText(f'确认 {len(selected)} 条（{languages or "未选择语言"}）')
        self.note.setText('只处理勾选的语言候选；原有其他语言名称保持。「官方来源」是联网查到的官方网页，悬停可看网址；「未联网」只是 AI 推测。')

    def select_all(self):
        for i in range(self.list.count()): self.list.item(i).setCheckState(Qt.CheckState.Checked)

    def select_official(self):
        from .translation_name_candidates import sourced_official_candidates
        picks = set(sourced_official_candidates(self.page.legacy, self.library_id))
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in picks else Qt.CheckState.Unchecked)

    def review(self, accept):
        try:
            from .translation_name_candidates import review_candidates
            review_candidates(self.page.legacy, self.library_id, self.selected(), accept=accept)
            refresh(self.page); self.reload()
        except Exception as exc: self.note.setText(str(exc))


class CompletionJob(QObject):
    progress = Signal(object)
    finished = Signal(object)


def run_name_search(page, identities, code, *, on_done=None):
    """Background web lookup of names in ``code`` for ``identities``; results
    become candidates (see translation_name_candidates.search_translation_names)."""
    from ..recognition.service import CancellationToken
    token = CancellationToken(); job = CompletionJob(page)
    page._name_completion_token, page._name_completion_job, page._name_completion_active = token, job, True
    if hasattr(page, 'name_completion_button'): page.name_completion_button.setText('停止查外语名')
    library_id = page._library_key(); settings = page._ai_update_settings()
    game = str(page.state.get('game') or '') if hasattr(page, 'state') else ''
    label = m.LANGUAGES.get(code, code)

    def show(stats):
        web = '查' if stats.get('web', True) else '猜（当前 AI 不能上网）'
        text = (f'{web} {label} 官方名：第 {stats.get("done", 0)}/{stats.get("total", 0)} 批'
                f' · 找到 {stats.get("added", 0)} · 与资料一致 {stats.get("agreed", 0)}'
                f' · 有出入 {stats.get("conflicts", 0)}')
        if stats.get('unsourced'): text += f' · 没来源丢弃 {stats["unsourced"]}'
        if stats.get('searches'):
            from ..providers.deepseek_tools import estimate_cost_usd
            text += f' · DeepSeek 搜索 {stats["searches"]} 次（约 {estimate_cost_usd(stats["searches"]):.2f} 美元）'
        if stats.get('failed'): text += f' · 失败 {stats["failed"]}'
        if stats.get('stopped'): text += f' · 已停：{stats["stopped"]}'
        if stats.get('cancelled'): text += ' · 已取消'
        if hasattr(page, 'name_completion_status'): page.name_completion_status.setText(text)

    def finished(stats):
        page._name_completion_active = False
        if hasattr(page, 'name_completion_button'): page.name_completion_button.setText('查外语官方名…')
        show(stats)
        if stats.get('errors') and hasattr(page, 'name_completion_status'):
            page.name_completion_status.setToolTip('\n'.join(str(e) for e in stats['errors']))
        refresh(page)
        if on_done: on_done(stats)
    job.progress.connect(show); job.finished.connect(finished)

    def work():
        try:
            from .translation_name_candidates import search_translation_names
            stats = search_translation_names(page.legacy, library_id, game, identities, [code], settings,
                                             token=token, progress=job.progress.emit)
        except Exception as exc:
            stats = dict(done=0, total=1, failed=1, errors=[str(exc)])
        try: job.finished.emit(stats)
        except RuntimeError: pass
    threading.Thread(target=work, name='translation-name-search', daemon=True).start()


def start_completion(page, code=None):
    """AI 帮忙 ▾ → 查外语官方名 (and the 待处理 strip's 「让 AI 查官方…名」).

    2026-11-13 (user, option A): a sheet asks the language and which terms,
    with counts, says whether the chosen AI can go online and offers 先试 20
    条; the AI then looks up each term's official name, a batch per request,
    filling gaps and checking existing names. Results wait in 待处理."""
    if getattr(page, '_name_completion_active', False):
        page._name_completion_token.cancel(); return
    from .name_search_sheet import NameSearchSheet
    shown = page.term_display_language.currentData() if hasattr(page, 'term_display_language') else ''
    selected = []
    try:
        selected = [page._term_model.data_for_row(i.row()).get('concept_id')
                    for i in page.listing.selectionModel().selectedRows()]
    except Exception:
        pass
    sheet = NameSearchSheet(page, code or shown or 'en', selected=selected)
    if sheet.exec() != QDialog.DialogCode.Accepted: return
    code, identities = sheet.chosen()
    if not identities: page._show_toast('没有需要处理的词条：请先选择词条，或换一个范围'); return
    run_name_search(page, identities, code)


def refresh(page):
    scroll = page.listing.verticalScrollBar().value()
    selected = page.listing.currentIndex()
    identity = (page._term_model.data_for_row(selected.row()) or {}).get('concept_id') if selected.isValid() else None
    page._notify_library_changed(); page.refresh_current_game()
    def restore():
        page.listing.verticalScrollBar().setValue(scroll)
        if identity:
            for i in range(page._term_model.rowCount()):
                if page._term_model.data_for_row(i).get('concept_id') == identity:
                    page.listing.setCurrentIndex(page._term_model.index(i, 0)); break
    QTimer.singleShot(0, restore)


def open_editor(page, identity):
    """Open 「名称与译名」 in the page's right-side drawer (a dialog when the
    page has none). Clicking another card switches the drawer, unless the
    open one has unsaved changes."""
    record = next((r for r in m.read_concepts(page.legacy, page._library_key()) if r['id'] == identity), None)
    if record is None: return
    drawer = getattr(page, 'names_drawer', None)
    if drawer is None:
        dialog = NamesEditor(page, record); dialog.saved.connect(lambda _r: refresh(page))
        page._names_editor = dialog; dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose); dialog.show()
        return
    current = getattr(page, '_names_editor', None)
    previous = None
    if current is not None and getattr(current, 'embedded', False):
        if current.draft.get('id') == identity:
            return
        if current.has_unsaved():
            current.message.setText('这一条还有未保存的修改：先「保存」，或点「关闭」放弃后再切换。')
            return
        previous = current
    # 2026-11-13 (user: switching cards felt choppy): an open drawer swaps its
    # content in place, in one paint. Closing and reopening it made the card
    # wall widen and narrow again and the toolbar re-wrap twice per click.
    drawer.setUpdatesEnabled(False)
    try:
        editor = NamesEditor(page, record, embedded=True)
        editor.saved.connect(lambda _r: refresh(page))
        editor.finished.connect(lambda _code, e=editor: close_drawer(page, e))
        drawer.layout().addWidget(editor)
        page._names_editor = editor
        if previous is not None:
            _discard_editor(page, previous)
        drawer.show()
    finally:
        drawer.setUpdatesEnabled(True)
    if previous is None:
        relayout(page)


def _discard_editor(page, editor):
    editor.hide()
    page.names_drawer.layout().removeWidget(editor)
    editor.deleteLater()


def close_drawer(page, editor):
    if getattr(page, '_names_editor', None) is editor:
        page._names_editor = None
        page.names_drawer.hide()
        relayout(page)
    _discard_editor(page, editor)


def relayout(page):
    """The library panel changed width: let the header and toolbar re-wrap."""
    queue = getattr(page, '_queue_term_toolbar', None)
    if callable(queue): QTimer.singleShot(0, queue)


def refresh_drawer(page):
    """The card display language changed: update the drawer's banner."""
    editor = getattr(page, '_names_editor', None)
    if editor is not None and getattr(editor, 'embedded', False):
        editor.refresh_banner()


def import_dialog(page):
    dialog = QDialog(page); dialog.setWindowTitle('导入多语言术语'); dialog.resize(800, 600)
    layout = QVBoxLayout(dialog)
    text = QPlainTextEdit(); text.setPlaceholderText('粘贴完整 JSON，或带标题行的 CSV / TSV（如 中文、日文、英文、id）'); layout.addWidget(text)
    file_button = QPushButton('读取 JSON / CSV / TSV 文件…')
    def load_file():
        path, _ = QFileDialog.getOpenFileName(dialog, '导入术语', '', '术语 (*.json *.csv *.tsv);;全部文件 (*)')
        if path:
            try: text.setPlainText(Path(path).read_text('utf-8-sig'))
            except OSError as exc: note.setText(str(exc))
    file_button.clicked.connect(load_file); layout.addWidget(file_button)
    columns = QTableWidget(0, 2); columns.setHorizontalHeaderLabels(['表格列', '对应语言（可忽略）']); layout.addWidget(columns)
    preview = QPushButton('解析列 / 预览新增、补充与冲突'); layout.addWidget(preview)
    note = QLabel(); note.setWordWrap(True); layout.addWidget(note)
    commit = QPushButton('应用此预览'); commit.setEnabled(False); layout.addWidget(commit)
    state = {}
    def changed(): commit.setEnabled(False)
    text.textChanged.connect(changed)
    def parse():
        raw = text.toPlainText()
        try:
            mapping = None
            if not raw.lstrip().startswith(('{', '[')):
                import csv, io
                headers = next(csv.reader(io.StringIO(raw), delimiter='\t' if '\t' in raw.partition('\n')[0] else ','), [])
                if state.get('headers') != headers:
                    state['headers'] = headers; columns.setRowCount(len(headers))
                    for i, h in enumerate(headers):
                        columns.setItem(i, 0, QTableWidgetItem(h)); combo = language_combo(); combo.insertItem(0, '忽略', '')
                        combo.setCurrentIndex(max(0, combo.findData(m.COLUMN_LANGUAGES.get(h, '')))); columns.setCellWidget(i, 1, combo)
                        combo.currentIndexChanged.connect(changed)
                mapping = {h: columns.cellWidget(i, 1).currentData() for i, h in enumerate(headers)}
            incoming = m.parse_import(raw, mapping)
            stats, conflicts = m.import_preview(m.read_concepts(page.legacy, page._library_key()), incoming)
            note.setText(f'新增 {stats["added"]} · 补充 {stats["supplemented"]} · 重复 {stats["duplicates"]} · 冲突 {stats["conflicts"]}\n'
                + ('冲突保留本地名称，导入不会覆盖人工译名。\n' if conflicts else '') + '\n'.join(str(c) for c in conflicts[:8]))
            state['incoming'] = incoming; commit.setEnabled(bool(incoming))
        except Exception as exc: note.setText(str(exc)); commit.setEnabled(False)
    def apply():
        try:
            m.import_concepts(page.legacy, page._library_key(), state['incoming']); refresh(page); dialog.accept()
        except Exception as exc: note.setText(str(exc))
    preview.clicked.connect(parse); commit.clicked.connect(apply); dialog.exec()


def install(page):
    """Place the multilingual controls (2026-11-13, plan 2026-11-13-glossary-library-redesign-c).

    Card display language sits at the right of the search row; translation
    work joins the 待处理 strip as chips that filter the cards; 导入多语言 is in
    the 导入 menu and 设为默认录入语言 in ⋯. The input language is the first
    field of the one-row quick add."""
    from .glossary_page_parts import ActionPopup
    page.term_input_language = language_combo(); page.term_input_language.setObjectName('termInputLanguage')
    page.term_input_language.setFixedWidth(105)
    page.term_input_language.setToolTip('新词的语言；可在 ⋯ 里设为本词库默认')
    composer = page.term_editor.parentWidget(); composer.layout().insertWidget(1, page.term_input_language)
    # Keep real input fields readable beside the drawer. Wrap complete controls
    # rather than squeezing QLineEdits to zero or clipping the Add button.
    from ..studio.studio_toolbar_layout import CommandFlowLayout
    import shiboken6
    previous = composer.layout(); items = []
    while previous.count(): items.append(previous.takeAt(0))
    shiboken6.delete(previous)
    commands = CommandFlowLayout(composer)
    commands.setContentsMargins(10, 6, 10, 6); commands.setSpacing(8)
    commands.stretch_after = set(); commands.expand = {2, 3}
    for item in items: commands.addItem(item)
    header = page._add_head_labels[0].parentWidget(); label = QLabel('语言'); label.setFixedWidth(105); header.layout().insertWidget(1, label)
    # Card display language: presentation only.
    display_label = QLabel('卡片显示'); display_label.setObjectName('termHint')
    page.term_display_language = language_combo(unspecified=False)
    page.term_display_language.insertItem(0, '只看原文', ''); page.term_display_language.setCurrentIndex(0)
    page.term_display_language.setObjectName('termDisplayLanguage')
    page.term_display_language.setToolTip('卡片下方显示该语言的译名和确认状态')
    page.term_actions_layout.addWidget(display_label)
    # Shown as a segment (只看原文 · the library's main languages · ＋); the
    # combo stays the single source of truth for the chosen language.
    page.term_display_language.hide()
    page.display_segment = QFrame(); page.display_segment.setObjectName('termSegment')
    segment = QHBoxLayout(page.display_segment); segment.setContentsMargins(3, 3, 3, 3); segment.setSpacing(2)
    page._display_codes = None
    page.term_actions_layout.addWidget(page.display_segment)
    page.term_actions_layout.addWidget(page.term_display_language)
    rebuild_display_segment(page, [])
    # The language filter stays one combo (driven by the strip's chips).
    page.term_language_filter = QComboBox(page)
    for text, value in (('全部语言', ''), ('包含显示语言', 'has'), ('缺少显示语言译名', 'missing'), ('有待确认译名', 'pending')):
        page.term_language_filter.addItem(text, value)
    page.term_language_filter.hide()
    def display_changed():
        if not page.term_display_language.currentData() and page.term_language_filter.currentData() == 'missing':
            choose_translation_filter(page, '')
    page.term_display_language.currentIndexChanged.connect(display_changed)
    page.term_display_language.currentIndexChanged.connect(lambda _i: refresh_drawer(page))
    for combo in (page.term_display_language, page.term_language_filter): combo.currentIndexChanged.connect(page.apply_filter)
    # 设为默认录入语言 → ⋯
    default = QPushButton('把当前录入语言设为默认')
    def set_default():
        try: m.set_default_language(page.legacy, page._library_key(), page.term_input_language.currentData()); page._show_toast('已保存默认录入语言')
        except Exception as exc: page._show_toast(str(exc))
    default.clicked.connect(set_default)
    page.more_popup._layout.insertWidget(max(0, page.more_popup._layout.count() - 2), default)
    default.setObjectName('termPopupItem'); default.clicked.connect(page.more_popup.hide)
    page.default_language_button = default
    # 导入 ▾: plain import and multilingual import.
    page.import_terms.clicked.disconnect()
    page.import_terms.setText('导入 ▾')
    page.import_popup = ActionPopup(page.import_terms, min_width=220)
    plain = QPushButton('导入术语…'); plain.setToolTip(page.import_terms.toolTip())
    plain.clicked.connect(lambda: page.show_import_dialog())
    page.import_popup.add_button(plain)
    import_button = QPushButton('导入多语言…'); import_button.clicked.connect(lambda: import_dialog(page))
    page.import_popup.add_button(import_button)
    page.import_multilingual_button = import_button
    # AI 帮忙 ▾ → 加外语名: look up official names, then review them (2026-11-13, option A).
    from .glossary_page_parts import AIMenuEntry
    page.name_completion_button = AIMenuEntry('查外语官方名…', '国际服、各地区的官方写法；AI 查到后等你确认',
                                              'fa5s.globe-asia', 'lang')
    page.name_completion_button.clicked.connect(lambda: start_completion(page))
    page.name_completion_button.setToolTip('以前叫「联网补全与校对译名」。AI 联网查每个词条在所选语言的官方名称，补上缺的、核对已有的；结果确认后才生效')
    review = AIMenuEntry('确认 AI 找到的译名', '逐条或一键收下 AI 查到的写法', 'fa5s.check-double', 'ok')
    review.setToolTip('以前叫「确认译名候选」')
    review.clicked.connect(lambda: CandidateDialog(page, page._library_key()).exec())
    page.name_review_button = review
    popup_layout = page.ai_popup._layout
    caption = getattr(page, 'ai_names_caption', None)
    at = popup_layout.indexOf(caption) + 1 if caption is not None else popup_layout.count()
    for offset, entry in enumerate((page.name_completion_button, review)):
        popup_layout.insertWidget(at + offset, entry)
        entry.clicked.connect(page.ai_popup.hide)
    if hasattr(page, '_refresh_ai_capability_label'):
        try: page._refresh_ai_capability_label()
        except Exception: pass
    # Counts: concept totals in the header; translation work in the 待处理 strip.
    page.name_counts = QLabel(); page.name_counts.setObjectName('termMeta')
    page.header_meta.layout().insertWidget(page.header_meta.layout().count() - 1, page.name_counts)
    strip = page.learning_panel.header_layout
    page.translation_chips = {}
    from .glossary_page_parts import StripChip
    for key, text in (('pending', '有待确认译名'), ('missing', '缺译名')):
        chip = StripChip(text, tone='info' if key == 'pending' else '', dashed=key == 'missing', checkable=True)
        chip.setToolTip('只显示这些卡片；再点一次取消')
        chip.clicked.connect(lambda checked, k=key: choose_translation_filter(page, k if checked else ''))
        chip.hide(); page.learning_panel.chip_layout.addWidget(chip); page.translation_chips[key] = chip
    reference = getattr(page, 'reference_chip', None)
    if reference is not None:  # draft order: candidates · translations · missing · references
        page.learning_panel.chip_layout.removeWidget(reference); page.learning_panel.chip_layout.addWidget(reference)
    # 2026-11-13 (user): the strip's 「N 个缺 English 译名」 gets the action beside it.
    page.name_search_strip_button = QPushButton('让 AI 查官方英文名')
    page.name_search_strip_button.setObjectName('termStripAction')
    page.name_search_strip_button.setCursor(Qt.CursorShape.PointingHandCursor)
    page.name_search_strip_button.clicked.connect(
        lambda: start_completion(page, page.term_display_language.currentData() or 'en'))
    page.name_search_strip_button.hide()
    page.learning_panel.chip_layout.insertWidget(
        page.learning_panel.chip_layout.indexOf(page.translation_chips['missing']) + 1, page.name_search_strip_button)
    page.name_completion_status = QLabel(); page.name_completion_status.setObjectName('termHint')
    page.learning_panel.chip_layout.addWidget(page.name_completion_status)


def _before_stretch(layout):
    """Index of the strip's stretch: chips go before it, actions after."""
    for i in range(layout.count()):
        if layout.itemAt(i).spacerItem() is not None:
            return i
    return layout.count()


def choose_translation_filter(page, key):
    """A strip chip filters the cards; clicking it again clears the filter."""
    page.term_language_filter.setCurrentIndex(max(0, page.term_language_filter.findData(key)))
    for name, chip in page.translation_chips.items():
        chip.setChecked(name == key)


def choose_display_language(page, code):
    page.term_display_language.setCurrentIndex(max(0, page.term_display_language.findData(code)))


def rebuild_display_segment(page, codes, sources=()):
    """只看原文 · up to two of the library's languages (plus the chosen one) · ＋ for any other.

    2026-11-13 (user): a library with no translations yet showed only
    「只看原文 ＋」, which did not read as a choice; 日本語 is offered by
    default (English when the library itself is Japanese)."""
    current = page.term_display_language.currentData() or ''
    codes = list(codes[:2])
    if len(codes) < 2:
        fallback = 'en' if 'ja' in sources else 'ja'
        if fallback not in codes:
            codes.append(fallback)
    codes = list(dict.fromkeys([*codes, *([current] if current else [])]))
    if page._display_codes == (codes, current):
        return
    page._display_codes = (codes, current)
    layout = page.display_segment.layout()
    while layout.count():
        item = layout.takeAt(0)
        if item.widget(): item.widget().deleteLater()
    for code in ['', *codes]:
        button = QPushButton(m.LANGUAGES.get(code, code) if code else '只看原文')
        button.setObjectName('termSegmentButton'); button.setCheckable(True); button.setChecked(code == current)
        button.setToolTip('卡片下方显示这种语言的译名和确认状态' if code else '卡片只显示原文名称')
        button.clicked.connect(lambda _c=False, c=code: choose_display_language(page, c))
        layout.addWidget(button)
    more = QPushButton('＋'); more.setObjectName('termSegmentButton'); more.setToolTip('显示其他语言的译名')
    menu = QMenu(more)
    for code, label in m.LANGUAGES.items():
        if code != 'und': menu.addAction(label, lambda c=code: choose_display_language(page, c))
    more.setMenu(menu); layout.addWidget(more)
    relayout(page)


def update_pending(page, cards, display_language):
    """Refresh the translation chips of the 待处理 strip from the current cards."""
    concepts = [row for row in cards if row.get('concept')]
    if getattr(page, 'display_segment', None) is not None:
        from collections import Counter
        counts = Counter(code for row in concepts for code in [*list(row['concept']['names'])[1:], *row['concept'].get('candidates', {})])
        sources = {str(next(iter(row['concept']['names']), '')).split('-')[0] for row in concepts}
        rebuild_display_segment(page, [code for code, _n in counts.most_common() if code != 'und'], sources)
    chips = getattr(page, 'translation_chips', None)
    if not chips:
        return
    label = m.LANGUAGES.get(display_language, display_language)
    if display_language:
        pending = sum(1 for row in concepts if m.translation_state(row['concept'], display_language) in ('pending', 'candidate'))
        missing = sum(1 for row in concepts if m.translation_state(row['concept'], display_language) == 'missing')
        chips['pending'].setText(f'{pending} 个 {label} 译名待确认')
        chips['missing'].setText(f'{missing} 个缺 {label} 译名')
    else:
        pending = sum(1 for row in concepts if row.get('pending_languages'))
        missing = 0
        chips['pending'].setText(f'{pending} 个词条有待确认译名')
    current = page.term_language_filter.currentData()
    chips['pending'].setVisible(bool(pending) or current == 'pending')
    chips['missing'].setVisible(bool(display_language) and (bool(missing) or current == 'missing'))
    action = getattr(page, 'name_search_strip_button', None)
    if action is not None:
        names = {'en': '英文', 'ja': '日文', 'ko': '韩文', 'zh-Hant': '繁体', 'zh-Hans': '简体'}
        action.setText(f'让 AI 查官方{names.get(display_language, label)}名')
        action.setVisible(bool(display_language) and bool(missing)
                          and not getattr(page, '_name_completion_active', False))
    review = getattr(page, 'name_review_button', None)
    if review is not None:
        waiting = sum(1 for row in concepts if any(row['concept'].get('candidates', {}).values()))
        review.set_badge(str(waiting) if waiting else '', 'count')
    for name, chip in chips.items():
        chip.setChecked(current == name)


class SharedLibrariesPanel(QWidget):
    """Shared concepts are selected in the existing translation settings."""
    def __init__(self, policy, parent=None):
        super().__init__(parent); self.policy = policy
        import subtitle_core as legacy
        self.legacy = legacy
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(QLabel('多语言词库：翻译／译文校对用途（与原文词库分别选择）'))
        self.list = QListWidget(); self.list.setMaximumHeight(105); layout.addWidget(self.list)
        catalog = legacy.glossary_catalog()
        for lib in catalog:
            item = QListWidgetItem(lib['name']); item.setData(Qt.ItemDataRole.UserRole, lib['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if lib['id'] in policy.get('concept_library_ids', []) else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        resolve = QPushButton('检查当前语言方向的同名冲突 / 选择优先词库…')
        resolve.clicked.connect(self.conflicts); layout.addWidget(resolve)
        note = QLabel('名称与译名在术语库卡片内编辑。未指定语言、缺少目标名称或待确认名称不产生确定翻译约束。')
        note.setWordWrap(True); layout.addWidget(note)

    def store(self):
        self.policy['concept_library_ids'] = [self.list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def conflicts(self):
        from .translation_terms import freeze, match_text
        self.store(); parent = self.parentWidget()
        value = m.hydrate_policy(dict(self.policy, enabled=True), self.legacy)
        rows, surfaces, _ = freeze(value).index(parent.source.currentData(), parent.target.currentData())
        conflicts = [(key, indices) for key, indices in surfaces.items() if len({rows[i]['target'] for i in indices}) > 1]
        # Include a previously chosen surface so the priority can be changed.
        if not conflicts:
            raw = dict(value, preferred_libraries={}); rows, surfaces, _ = freeze(raw).index(parent.source.currentData(), parent.target.currentData())
            conflicts = [(key, ids) for key, ids in surfaces.items() if len({rows[i]['target'] for i in ids}) > 1]
        dialog = QDialog(self); dialog.setWindowTitle('同名冲突：明确选择或保留未决'); dialog.resize(740, 400)
        layout = QVBoxLayout(dialog); table = QTableWidget(len(conflicts), 2); table.setHorizontalHeaderLabels(['来源词与冲突', '明确优先词库'])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); layout.addWidget(table)
        choices = []
        for n, (key, indices) in enumerate(conflicts):
            table.setItem(n, 0, QTableWidgetItem(key + '\n' + '\n'.join(f'{rows[i]["library_name"]}: {rows[i]["target"]}' for i in indices)))
            box = QComboBox(); box.addItem('保留未决，不强制采用任何译名', '')
            for i in indices: box.addItem(f'{rows[i]["library_name"]} → {rows[i]["target"]}', rows[i]['library_id'])
            box.setCurrentIndex(max(0, box.findData(self.policy.get('preferred_libraries', {}).get(key, ''))))
            table.setCellWidget(n, 1, box); choices.append((key, box))
        table.resizeRowsToContents()
        if not conflicts: layout.addWidget(QLabel('当前方向没有同名冲突。'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            preferred = self.policy.setdefault('preferred_libraries', {})
            for key, box in choices:
                if box.currentData(): preferred[key] = box.currentData()
                else: preferred.pop(key, None)
