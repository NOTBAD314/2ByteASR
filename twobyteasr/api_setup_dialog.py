"""「申请与设置 API」: choose a provider, follow its guide, paste, test, save (2026-10-13).

The dialog never stores anything itself. ``SetupHost`` (implemented by the
main window) reads the current values and saves through the existing settings
and credential paths, so the old advanced dialog and this guide always agree.
Tests run on worker threads; the paid recognition test runs only after an
explicit confirmation that names the provider, the data and the cost basis.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

from . import api_setup_catalog as catalog
from . import cloud_api_test as tests
from .i18n import bind_text, tr, ui_literal
from .main_ui_dialogs import SpringDialog

STATUS_MARKS = {tests.PASS: '✓', tests.FAIL: '✗', tests.UNKNOWN: '?', tests.SKIP: '—'}
STATUS_NAMES = {'ok': tests.PASS, 'fail': tests.FAIL}

OSS_REGIONS = (('cn-hangzhou', '华东1（杭州）'), ('cn-shanghai', '华东2（上海）'), ('cn-beijing', '华北2（北京）'),
               ('cn-shenzhen', '华南1（深圳）'), ('cn-hongkong', '中国香港'), ('ap-southeast-1', '新加坡'))


@dataclass
class SetupHost:
    """Callbacks into the main window (kept small so the dialog is testable)."""
    settings: Callable[[], dict]
    saved_key: Callable[[str, str], str]
    saved_oss_credentials: Callable[[], tuple]
    save: Callable[[str, dict, bool], tuple]          # (provider, values, use_as_primary) -> (ok, message)
    open_advanced: Callable[[str], None] | None = None
    open_text_settings: Callable[[str], None] | None = None


def _shrinkable(combo: QComboBox) -> None:
    """Long item labels must not widen the whole page."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(18)


class _Runner(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, job):
        super().__init__()
        self.job = job

    def run(self):
        try:
            self.finished.emit(self.job())
        except Exception as exc:  # shown to the user, never swallowed
            from .provider_diagnostics import redact_diagnostics
            self.failed.emit(redact_diagnostics(str(exc))[:600])


class ApiSetupDialog(SpringDialog):
    ENTRY_ANIMATED = False

    def __init__(self, parent, host: SetupHost, *, kind: str = 'asr', initial: str = '', show_advanced: bool = False):
        super().__init__(parent)
        self.host = host
        self.kind = kind
        self._threads = []
        self._fields = {}
        self._field_rows = {}
        self._locked_widgets = []
        self._lockable_widgets = []
        self._result_labels = {}
        self._guide = None
        self._last_price = {}
        self.oss_button = None
        self.setObjectName('apiSetupDialog')
        bind_text(self, '申请与设置 API', property='windowTitle')
        self.resize(1080, 760)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel(tr('申请与设置 API'))
        title.setProperty('typography', 'title')
        header.addWidget(title, 1)
        from .design.presentation import button_role, glyph_button
        close = glyph_button(button_role(QPushButton('×'), 'ghost'))
        bind_text(close, '关闭', property='accessibleName')
        close.clicked.connect(self.reject)
        header.addWidget(close)
        outer.addLayout(header)
        # 2026-10-14: no intro sentence; the ①②③ strip on each page says what to do.
        body = QHBoxLayout()
        body.setSpacing(14)
        self.provider_list = QListWidget()
        self.provider_list.setObjectName('apiSetupProviders')
        self.provider_list.setFixedWidth(320)
        self.provider_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.provider_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._populate_list(show_advanced)
        body.addWidget(self.provider_list)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(self.scroll, 1)
        outer.addLayout(body, 1)
        footer = QHBoxLayout()
        self.status = QLabel('')
        self.status.setObjectName('muted')
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.advanced_button = button_role(QPushButton(tr('进阶设置…')), 'secondary')
        self.advanced_button.clicked.connect(self._open_advanced)
        footer.addWidget(self.advanced_button)
        self.save_button = button_role(QPushButton(tr('保存')), 'secondary')
        self.save_button.clicked.connect(lambda: self._save(False))
        footer.addWidget(self.save_button)
        self.save_primary_button = button_role(QPushButton(tr('保存并用于识别')), 'primary')
        self.save_primary_button.clicked.connect(lambda: self._save(True))
        footer.addWidget(self.save_primary_button)
        outer.addLayout(footer)
        self.provider_list.currentItemChanged.connect(lambda current, _old: self._show(current))
        self._select_initial(initial)
        # Start in the list (arrow keys pick a service). The header × came
        # first in the tab order: it opened with a focus ring, and Enter closed.
        self.provider_list.setFocus()

    # ------------------------------------------------------------------ list
    def _populate_list(self, show_advanced: bool):
        def header(text):
            item = QListWidgetItem(tr(text))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            self.provider_list.addItem(item)

        groups = (('语音识别（生成字幕）', catalog.ASR_GUIDES), ('文字 AI（断句、校对、翻译）', catalog.TEXT_GUIDES))
        for label, guides in groups:
            header(label)
            for guide in guides:
                if guide.advanced_only and not show_advanced:
                    continue
                item = QListWidgetItem(('   ' + tr(guide.title)) + ('（进阶）' if guide.advanced_only else ''))
                item.setToolTip(tr(guide.title))
                item.setData(Qt.ItemDataRole.UserRole, (guide.kind, guide.key))
                self.provider_list.addItem(item)
        if not show_advanced:
            more = QListWidgetItem('   ' + tr('显示进阶选项（自架接口、待验证服务）'))
            more.setData(Qt.ItemDataRole.UserRole, ('more', ''))
            self.provider_list.addItem(more)

    def _select_initial(self, initial: str):
        guide = catalog.guide_for(initial, self.kind) if initial else None
        target = (guide.kind, guide.key) if guide is not None else None
        rows = [(row, self.provider_list.item(row).data(Qt.ItemDataRole.UserRole))
                for row in range(self.provider_list.count())]
        for row, data in rows:
            if data and tuple(data) == target:
                self.provider_list.setCurrentRow(row)
                return
        for row, data in rows:
            if data and data[0] == self.kind:
                self.provider_list.setCurrentRow(row)
                return

    # ------------------------------------------------------------- content
    def _show(self, item):
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data[0] == 'more':
            current = self._guide.key if self._guide else ''
            self.provider_list.clear()
            self._populate_list(True)
            self._select_initial(current)
            return
        kind, key = data
        guide = catalog.guide_for(key, kind)
        if guide is None:
            return
        self._guide = guide
        self._fields = {}
        self._field_rows = {}
        self._locked_widgets = []      # hint/address rows of a locked prefilled field
        self._lockable_widgets = []
        self._result_labels = {}
        self._last_price = {}
        self.oss_button = None
        self._step_cards = None
        page = QWidget()
        page.setObjectName('apiSetupPage')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)
        name = QLabel(tr(guide.title))
        name.setProperty('typography', 'section')
        name.setWordWrap(True)
        layout.addWidget(name)
        role = QLabel(tr(guide.role))
        role.setWordWrap(True)
        layout.addWidget(role)
        # 2026-10-14: three steps and the fields first; notes, links and the
        # full tutorial stay one click away under "详细说明与教程".
        details = QWidget()
        details.setObjectName('apiSetupDetails')
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(12)
        facts = []
        if guide.account_note:
            facts.append(tr('需要的账号：') + tr(guide.account_note))
        if guide.uploads:
            facts.append(tr('会传送的数据：') + tr(guide.uploads))
        if guide.cost:
            facts.append(tr('费用：') + tr(guide.cost))
        if guide.status_note:
            facts.append(tr('兔白验证状态：') + tr(guide.status_note))
        if facts:
            info = QLabel('\n'.join(facts))
            info.setObjectName('muted')
            info.setWordWrap(True)
            info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            details_layout.addWidget(info)
        if guide.links:
            details_layout.addWidget(self._links(guide))
        guide_box = QTextBrowser()
        guide_box.setObjectName('apiSetupGuide')
        guide_box.setOpenExternalLinks(True)
        text = guide.guide_text()
        if text.startswith('<!--'):
            # The generated 繁體 tutorials start with a "generated from" comment.
            text = text.partition(chr(10))[2]
        if text.startswith('# '):
            # The page already shows the provider name; keep the guide body only.
            text = text.partition(chr(10))[2]
        guide_box.setMarkdown(text)
        guide_box.setMinimumHeight(300)
        guide_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        details_layout.addWidget(guide_box, 1)
        if guide.kind == 'asr':
            if guide.links and guide.key != 'custom':
                layout.addWidget(self._steps(guide))
            layout.addWidget(self._form(guide))
            layout.addWidget(self._test_panel(guide))
            key_field = self._fields.get('api_key')
            if isinstance(key_field, QLineEdit):
                key_field.textChanged.connect(lambda _t: self._update_steps())
            self._update_steps()
            self._add_details(layout, details)
        else:
            # 2026-10-14: picture steps for text AI too; the key itself is
            # entered and tested in “AI 智能断句设置”.
            go_fill = None
            if self.host.open_text_settings is not None:
                def go_fill():
                    self.accept()
                    self.host.open_text_settings(guide.key)
            if guide.links and guide.key != 'cli_accounts':
                from .guide_steps import GuideStep, StepCards
                links = list(guide.links)
                key_link = next((item for item in links if 'key' in item.label.lower()), links[0])
                signup = next((item for item in links if '注册' in item.label), key_link)
                steps = [GuideStep('注册并登录', 'account', '打开网页', signup.url),
                         GuideStep('创建 API Key', 'key', '打开网页', key_link.url),
                         GuideStep('贴到“AI 智能断句设置”并测试', 'paste', '去填写' if go_fill else '', callback=go_fill)]
                self._step_cards = StepCards(steps)
                self._step_cards.setObjectName('apiSetupSteps')
                self._step_cards.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
                layout.addWidget(self._step_cards)
            note = QLabel(tr('文字 AI 只发送字幕文字。密钥在“AI 智能断句设置”里填写，按“测试连接”确认（会发送一句很短的文字）。'))
            note.setObjectName('fieldHint')
            note.setWordWrap(True)
            layout.addWidget(note)
            if go_fill is not None:
                from .design.presentation import button_role
                go = button_role(QPushButton(tr('去填写这家服务的密钥')), 'primary')
                go.clicked.connect(go_fill)
                layout.addWidget(go, 0, Qt.AlignmentFlag.AlignLeft)
            self._add_details(layout, details)
        is_asr = guide.kind == 'asr'
        for button in (self.save_button, self.save_primary_button):
            button.setVisible(is_asr)
        self.advanced_button.setVisible(is_asr and self.host.open_advanced is not None)
        self.status.setText('')
        self.scroll.setWidget(page)

    def _add_details(self, layout, details):
        """Notes, links and the full tutorial stay one click away (collapsed)."""
        toggle = QPushButton()
        toggle.setObjectName('apiSetupDetailsToggle')
        toggle.setCheckable(True)
        toggle.setFlat(True)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)

        def show_details(shown):
            details.setVisible(shown)
            toggle.setText(('▾  ' if shown else '▸  ') + tr('详细说明与教程'))
        toggle.toggled.connect(show_details)
        show_details(False)
        layout.addWidget(toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(details)
        # A short page keeps its content at the top instead of spreading it.
        layout.addStretch(1)

    def _steps(self, guide):
        """Picture steps (2026-10-14, user feedback “按钮直接跳转网页、少写字”).

        注册并登录 › 创建 API Key › (录音文件识别: 私有 OSS 与 AccessKey) ›
        贴到下面 › 检查并保存; each button opens the exact official page or
        does the step. Steps tick off as the key is pasted and a check passes.
        """
        from .guide_steps import GuideStep, StepCards
        links = list(guide.links)
        key_link = next((item for item in links if 'key' in item.label.lower() or 'AppID' in item.label), links[0])
        signup = next((item for item in links if '注册' in item.label),
                      next((item for item in links if not item.needs_login and item is not key_link), key_link))
        key_title = '创建应用，复制三项' if guide.key == 'spark_asr_v2' else '创建 API Key'
        steps = [GuideStep('注册并登录', 'account', '打开网页', signup.url),
                 GuideStep(key_title, 'key', '打开网页', key_link.url)]
        self._step_paste = len(steps)
        if guide.needs_storage:
            oss = next((item for item in links if 'OSS 控制台' in item.label), None)
            if oss is not None:
                steps.append(GuideStep('建私有 OSS 与 AccessKey', 'folder', '打开网页', oss.url))
                self._step_paste = len(steps)
        steps.append(GuideStep('贴到下面', 'paste', '去填写', callback=self._focus_first_empty))
        steps.append(GuideStep('检查并保存', 'check', '免费检查', callback=self._run_free))
        self._step_cards = StepCards(steps)
        self._step_cards.setObjectName('apiSetupSteps')
        # Natural height only: a short page must not stretch the cards.
        self._step_cards.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        return self._step_cards

    def _focus_first_empty(self):
        for key, widget in self._fields.items():
            if isinstance(widget, QLineEdit) and widget.isEnabled() and not widget.text().strip():
                widget.setFocus()
                return
        widget = self._fields.get('api_key')
        if widget is not None:
            widget.setFocus()

    def _update_steps(self, *, checked: bool | None = None):
        cards = getattr(self, '_step_cards', None)
        if cards is None:
            return
        pasted = False
        key = self._fields.get('api_key')
        if isinstance(key, QLineEdit):
            pasted = bool(key.text().strip() or self._saved_secret(self._guide, next(
                (f for f in self._guide.fields if f.key == 'api_key'), catalog.Field('api_key', '', '')), ''))
        if pasted:
            for index in range(self._step_paste + 1):
                cards.set_done(index)
        if checked is not None:
            cards.set_done(len(cards.cards) - 1, checked)

    def _links(self, guide):
        box = QWidget()
        # The page must never be wider than the pane; buttons elide instead.
        box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        box.setMinimumWidth(1)
        row = QGridLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(8)
        row.setVerticalSpacing(4)
        for index, link in enumerate(guide.links):
            button = QPushButton(tr(link.label) + (tr('（需登录）') if link.needs_login else ''))
            button.setObjectName('helpLink')
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f'{link.url}\n{tr("最后核对")} {link.checked}')
            button.clicked.connect(lambda _=False, url=link.url: QDesktopServices.openUrl(QUrl(url)))
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(80)  # explicit minimum: long labels must not widen the page
            row.addWidget(button, index // 3, index % 3)
        return box

    def _form(self, guide):
        group = QGroupBox(tr('填写'))
        form = QFormLayout(group)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        settings = self.host.settings() or {}
        models = settings.get('models', {}) if isinstance(settings, dict) else {}
        same_provider = models.get('qwen_asr_api_provider') == guide.key
        current_url = str(models.get('qwen_asr_api_url') or '') if same_provider else ''
        if guide.models:
            combo = QComboBox()
            combo.setObjectName('apiSetupModel')
            _shrinkable(combo)
            for choice in guide.models:
                combo.addItem(choice.label, choice.model)
            wanted = str(models.get('qwen_asr_api_model') or '') if same_provider else ''
            combo.setCurrentIndex(max(0, combo.findData(wanted)))
            summary = QLabel()
            summary.setObjectName('fieldHint')
            summary.setWordWrap(True)

            def describe():
                choice = catalog.model_choice(guide, combo.currentData())
                if choice is None:
                    return
                speakers = tr('有说话人') if choice.speakers else tr('不分说话人')
                timing = tr('字/词级时间') if choice.timestamps == 'word' else tr('只有句段时间')
                # Two facts in one short line; the full description is the tooltip.
                summary.setText(f'{speakers}  ·  {timing}')
                summary.setToolTip(ui_literal(choice.summary))
                combo.setToolTip(ui_literal(choice.summary))

            combo.currentIndexChanged.connect(lambda _i: describe())
            describe()
            form.addRow(tr('模型'), combo)
            form.addRow('', summary)
            self._fields['model'] = combo
        for spec in guide.fields:
            editor = QLineEdit()
            editor.setObjectName('apiSetupField_' + spec.key)
            if spec.secret:
                editor.setEchoMode(QLineEdit.EchoMode.Password)
            value = self._initial_value(guide, spec, models, current_url)
            if spec.secret:
                saved = self._saved_secret(guide, spec, current_url)
                editor.setPlaceholderText(tr('已保存（···{value0}）；留空表示不修改', value0=saved[-4:]) if saved
                                          else (spec.example or tr('尚未保存')))
            else:
                editor.setText(value)
                editor.setPlaceholderText(spec.example)
            # One short line under the field; the full explanation is on hover
            # and in "详细说明与教程" (2026-10-14: less text on the page).
            hint = QLabel(tr(spec.short_help))
            hint.setObjectName('fieldHint')
            hint.setWordWrap(True)
            if spec.help and spec.help != spec.short_help:
                hint.setToolTip(ui_literal(spec.help))
            label = tr(spec.label) + ('' if spec.required else tr('（可选）'))
            if spec.choices:
                editor = QComboBox()
                editor.setObjectName('apiSetupField_' + spec.key)
                _shrinkable(editor)
                for choice_value, choice_label in spec.choices:
                    editor.addItem(tr(choice_label), choice_value)
                editor.setCurrentIndex(max(0, editor.findData(value or spec.prefilled)))
                editor.currentIndexChanged.connect(lambda _i: self._apply_field_visibility())
            elif spec.key == 'oss_region':
                editor = QComboBox()
                editor.setObjectName('apiSetupField_oss_region')
                _shrinkable(editor)
                for code, region_label in OSS_REGIONS:
                    editor.addItem(f'{tr(region_label)} · {code}', code)
                index = editor.findData(value or 'cn-hangzhou')
                if index < 0:
                    editor.addItem(value, value)
                    index = editor.count() - 1
                editor.setCurrentIndex(index)
            if spec.help:
                editor.setToolTip(ui_literal(spec.help))
            form.addRow(label, editor)
            form.addRow('', hint)
            self._fields[spec.key] = editor
            rows = [editor, hint]
            address = None
            if spec.key == 'api_host' or (spec.key == 'url' and guide.key in {'mosi_moss_pro', 'qwen_cloud_filetrans'}):
                address = self.address_view = QLabel()
                self.address_view.setObjectName('fieldHint')
                self.address_view.setWordWrap(True)
                self.address_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                form.addRow(tr('将使用'), self.address_view)
                rows.append(address)
            if spec.advanced:
                # A prefilled address stays one line until the user chooses to
                # change it; then its hint and the address breakdown appear.
                editor.setEnabled(False)
                unlock = QToolButton()
                unlock.setText(tr('修改'))
                locked = [hint] + ([address] if address is not None else [])
                self._locked_widgets.extend(locked)

                def unlock_field(_=False, widget=editor, button=unlock, widgets=tuple(locked)):
                    widget.setEnabled(True)
                    button.setEnabled(False)
                    for item in widgets:
                        if item in self._locked_widgets:
                            self._locked_widgets.remove(item)
                    self._apply_field_visibility()

                unlock.clicked.connect(unlock_field)
                form.addRow('', unlock)
                rows.append(unlock)
                self._lockable_widgets.extend(locked)
            if spec.key == 'filetrans_upload':
                # Shown only while the trial upload is selected (ADR 0112).
                trial = QLabel(tr(catalog.TRIAL_UPLOAD_NOTE))
                trial.setObjectName('statusWarn')
                trial.setWordWrap(True)
                form.addRow('', trial)
                self._field_rows['filetrans_upload_trial'] = (
                    catalog.Field('filetrans_upload_trial', '', '', show_when=('filetrans_upload', catalog.UPLOAD_PROVIDER)),
                    [trial])
            if spec.show_when:
                self._field_rows[spec.key] = (spec, rows)
        self._form_layout = form
        source = 'api_host' if 'api_host' in self._fields else (
            'url' if guide.key in {'mosi_moss_pro', 'qwen_cloud_filetrans'} else '')
        if source:
            self._fields[source].textChanged.connect(lambda _t: self._describe_address())
            self._describe_address()
        if guide.needs_storage:
            auto_delete = QCheckBox(tr('识别成功后自动删除 OSS 临时音频（建议开启）'))
            auto_delete.setChecked(bool(models.get('oss_auto_delete', True)))
            form.addRow('', auto_delete)
            self._fields['oss_auto_delete'] = auto_delete
            self._field_rows['oss_auto_delete'] = (catalog.Field('oss_auto_delete', '', '', show_when=('filetrans_upload',
                                                   catalog.UPLOAD_OWN_OSS)), [auto_delete])
        self._apply_field_visibility()
        return group

    def _apply_field_visibility(self):
        """Fields that only apply to one choice (e.g. own OSS) are hidden otherwise."""
        form = getattr(self, '_form_layout', None)
        if form is None:
            return
        values = {key: self._value(key) for key in self._fields}
        shown = {}
        for widget in self._lockable_widgets:
            shown[id(widget)] = (widget, True)
        for spec, widgets in self._field_rows.values():
            visible = catalog.visible_field(spec, values)
            for widget in widgets:
                shown[id(widget)] = (widget, visible)
        for widget, visible in shown.values():
            visible = visible and widget not in self._locked_widgets
            try:
                form.setRowVisible(widget, visible)
            except (AttributeError, TypeError):
                widget.setVisible(visible)
        if self.oss_button is not None:
            self.oss_button.setVisible(catalog.uses_own_storage(self._guide, values))

    def _initial_value(self, guide, spec, models, current_url):
        if spec.key == 'api_host':
            if not current_url:
                return ''
            from .api_endpoints import EndpointInputError, parse_dashscope_address
            try:
                return parse_dashscope_address(current_url).host
            except EndpointInputError:
                return current_url
        if spec.key == 'url':
            return current_url or spec.prefilled
        if spec.key.startswith('oss_'):
            return str(models.get(spec.key) or spec.prefilled or '')
        if spec.key == 'filetrans_upload':
            try:
                saved = tuple(self.host.saved_oss_credentials() or ())
            except Exception:
                saved = ()
            mode = catalog.resolve_upload_mode(models, guide.key, has_oss_credentials=len(saved) >= 2 and all(saved[:2]))
            # Nothing set up yet: start on the regular route (own OSS), never on the trial upload.
            return catalog.UPLOAD_OWN_OSS if mode == catalog.UPLOAD_MISSING else mode
        if spec.key == 'model':
            return str(models.get('qwen_asr_api_model') or '') if models.get('qwen_asr_api_provider') == guide.key else ''
        if guide.key == 'spark_asr_v2' and spec.key == 'app_id':
            # AppID is not secret: show the saved one so a check works without re-pasting.
            return self._spark_saved(current_url).get('app_id', '')
        return spec.prefilled

    def _spark_saved(self, current_url='') -> dict:
        try:
            from .llm_config import read_spark_credentials
            from .ui import ASR_API_PRESETS
            return read_spark_credentials(current_url or ASR_API_PRESETS['spark_asr_v2']['url'])
        except Exception:
            return {}

    def _saved_secret(self, guide, spec, current_url):
        try:
            if guide.key == 'spark_asr_v2' and spec.key in {'api_key', 'api_secret'}:
                # Spark keeps its three values under its own scope (2026-10-14 fix:
                # reopening showed them as not saved and checks failed).
                return str(self._spark_saved(current_url).get(spec.key) or '')
            if spec.key == 'api_key':
                url = current_url or next((f.prefilled for f in guide.fields if f.key == 'url'), '')
                return str(self.host.saved_key(guide.key, url) or '')
            if spec.key in {'oss_access_key_id', 'oss_access_key_secret'}:
                ident, secret = (tuple(self.host.saved_oss_credentials() or ()) + ('', ''))[:2]
                return str(ident if spec.key == 'oss_access_key_id' else secret)
        except Exception:
            return ''
        return ''

    def _describe_address(self):
        from .api_endpoints import EndpointInputError, describe_dashscope, describe_mosi
        try:
            if self._guide.key == 'mosi_moss_pro':
                info = describe_mosi(self._value('url'))
            elif self._guide.key == 'qwen_cloud_filetrans':
                info = describe_dashscope(self._value('url') or 'https://maas.qwencloudapi.com')
            else:
                info = describe_dashscope(self._value('api_host'))
        except EndpointInputError as exc:
            self.address_view.setText(ui_literal(str(exc)))
            self.address_view.setToolTip('')
            return
        lines = [f"{tr('官方网站')}：{info['website']}", f"API Host：{info['api_host']}",
                 f"Base URL：{info['base_url']}", f"{tr('完整请求 Endpoint')}：{info['endpoint']}"]
        if info.get('region_label'):
            lines.append(f"{tr('地域')}：{ui_literal(info['region_label'])}")
        notes = [tr(note) for note in info.get('notes') or ()]
        # One line on the page (where requests go); the four addresses kept
        # apart on hover, so nobody has to guess about /v1.
        compact = ' · '.join(part for part in (ui_literal(info.get('region_label') or ''), info['base_url']) if part)
        legacy = [note for note in notes if '旧' in note]
        self.address_view.setText('\n'.join([compact] + legacy))
        self.address_view.setToolTip('\n'.join(lines + notes))

    def _value(self, key):
        widget = self._fields.get(key)
        if widget is None:
            return ''
        if isinstance(widget, QComboBox):
            return str(widget.currentData() or widget.currentText() or '')
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        return widget.text().strip()

    # -------------------------------------------------------------- values
    def collected(self) -> dict:
        values = {key: self._value(key) for key in self._fields}
        guide = self._guide
        # A field hidden by the current choice is not part of the setup.
        for spec in guide.fields:
            if spec.show_when and not catalog.visible_field(spec, values):
                values.pop(spec.key, None)
        if guide.key == 'qwen31_filetrans':
            from .api_endpoints import filetrans_endpoint
            values['url'] = filetrans_endpoint(values.get('api_host', ''))
            if 'oss_region' in values:
                values['oss_endpoint'] = catalog.oss_endpoint_for_region(values.get('oss_region', ''))
        elif guide.key == 'qwen_cloud_filetrans':
            from .api_endpoints import EndpointInputError, parse_dashscope_address
            address = parse_dashscope_address(values.get('url') or 'https://maas.qwencloudapi.com')
            if not (address.qwen_cloud or address.host == 'dashscope-intl.aliyuncs.com'):
                raise EndpointInputError('这里只接受 Qwen Cloud 的地址（maas.qwencloudapi.com 或 dashscope-intl.aliyuncs.com）。'
                                         '阿里云百炼的地址请到“阿里云百炼 · 录音文件识别”填写。')
            values['url'] = address.filetrans_url
        elif guide.key == 'mosi_moss_pro':
            from .mosi_asr import normalize_api_base
            values['url'] = normalize_api_base(values.get('url', ''))
        return values

    def _endpoint(self, values) -> dict:
        from .llm_config import read_asr_api_key
        from .ui import ASR_API_PRESETS
        preset = ASR_API_PRESETS.get(self._guide.key, {})
        endpoint = {'provider': self._guide.key, 'protocol': preset.get('protocol', ''),
                    'model': values.get('model') or preset.get('model', ''),
                    'url': values.get('url') or preset.get('url', ''), 'speaker_source': 'native'}
        if self._guide.key == 'spark_asr_v2':
            saved = self._spark_saved(endpoint['url'])
            for name in ('app_id', 'api_key', 'api_secret'):
                endpoint[name] = values.get(name) or saved.get(name, '')
            return endpoint
        key = values.get('api_key') or read_asr_api_key(self._guide.key, endpoint['url'])[0]
        endpoint['api_key'] = key
        for name in ('app_id', 'api_secret'):
            if values.get(name):
                endpoint[name] = values[name]
        return endpoint

    def _settings_snapshot(self, values) -> dict:
        import copy
        settings = copy.deepcopy(self.host.settings() or {})
        models = settings.setdefault('models', {})
        for key in ('oss_region', 'oss_endpoint', 'oss_bucket', 'oss_prefix', 'oss_auto_delete', 'filetrans_upload'):
            if key in values and values[key] not in ('', None):
                models[key] = values[key]
        models['qwen_asr_api_provider'] = self._guide.key
        return settings

    def _oss_credentials(self, values) -> tuple:
        saved = (tuple(self.host.saved_oss_credentials() or ()) + ('', ''))[:2]
        return (values.get('oss_access_key_id') or saved[0], values.get('oss_access_key_secret') or saved[1])

    # ---------------------------------------------------------------- tests
    def _test_panel(self, guide):
        group = QGroupBox(tr('测试'))
        layout = QVBoxLayout(group)
        buttons = QGridLayout()
        from .design.presentation import button_role
        actions = [(tr('免费检查（不上传音频）'), self._run_free, 'free')]
        if guide.needs_storage:
            actions.append((tr('检查 OSS（上传很小的测试文件后删除）'), self._run_oss, 'oss'))
        actions.append((tr('试识别一小段…'), self._run_recognition, 'paid'))
        for index, (text, handler, name) in enumerate(actions):
            button = button_role(QPushButton(text), 'secondary')
            button.setObjectName('apiSetupTest_' + name)
            button.setToolTip(text)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(80)
            button.clicked.connect(handler)
            buttons.addWidget(button, index // 2, index % 2)
            if name == 'oss':
                self.oss_button = button
        layout.addLayout(buttons)
        note = QLabel(tr('免费检查不上传音频；“试识别一小段”成功，才说明真的能用（会按用量计费）。'))
        note.setObjectName('fieldHint')
        note.setWordWrap(True)
        layout.addWidget(note)
        grid = QGridLayout()
        levels = [level for level in tests.LEVELS if guide.key in catalog.FILETRANS_GUIDES or level != 'storage']
        for row, level in enumerate(levels):
            mark = QLabel(STATUS_MARKS[tests.SKIP])
            mark.setFixedWidth(22)
            name = QLabel(tr(tests.LEVEL_LABELS[level]))
            detail = QLabel(tr('尚未检查'))
            detail.setObjectName('muted')
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(mark, row, 0)
            grid.addWidget(name, row, 1)
            grid.addWidget(detail, row, 2)
            self._result_labels[level] = (mark, detail)
        grid.setColumnStretch(2, 1)
        # The eight result rows appear once a check has run.
        self._results_box = QWidget()
        self._results_box.setLayout(grid)
        self._results_box.hide()
        layout.addWidget(self._results_box)
        self._apply_field_visibility()
        return group

    def _show_report(self, report):
        box = getattr(self, '_results_box', None)
        if box is not None:
            box.show()
        if getattr(report, 'price', None):
            self._last_price = dict(report.price)
        for check in report.checks:
            labels = self._result_labels.get(check.level)
            if labels is None:
                continue
            labels[0].setText(STATUS_MARKS.get(check.status, '?'))
            labels[1].setText(ui_literal(check.detail) if check.detail else {
                tests.PASS: tr('通过'), tests.FAIL: tr('未通过'), tests.UNKNOWN: tr('无法判断'),
                tests.SKIP: tr('未执行')}[check.status])
        failed = [c for c in report.checks if c.status == tests.FAIL]
        self.status.setText(tr('有项目未通过，请按右侧说明处理。') if failed else tr('检查完成。'))
        if any(c.level in {'key', 'recognition'} for c in report.checks):
            self._update_steps(checked=not failed and report.status('key') != tests.UNKNOWN)

    def _start(self, job, message):
        self.status.setText(tr(message))
        thread = QThread(self)
        runner = _Runner(job)
        runner.moveToThread(thread)
        thread.started.connect(runner.run)
        runner.finished.connect(self._show_report)
        runner.failed.connect(lambda text: self.status.setText(tr('检查失败：') + ui_literal(text)))
        for signal in (runner.finished, runner.failed):
            signal.connect(thread.quit)
        thread.finished.connect(runner.deleteLater)
        thread.finished.connect(lambda: self._threads.remove(item) if item in self._threads else None)
        item = (thread, runner)
        self._threads.append(item)
        thread.start()

    def _format_failure(self, message):
        """Address/field errors land in the result grid, not only the status line."""
        report = tests.Report().add('format', tests.FAIL, str(message))
        self._show_report(report)

    def _run_free(self):
        try:
            values = self.collected()
        except Exception as exc:
            self._format_failure(exc)
            return
        endpoint = self._endpoint(values)
        checked_values = dict(values)
        if catalog.uses_own_storage(self._guide, values):
            ident, secret = self._oss_credentials(values)
            checked_values.update(oss_access_key_id=ident, oss_access_key_secret=secret)
        temporary = (self._guide.key in catalog.FILETRANS_GUIDES
                     and str(values.get('filetrans_upload') or '') == catalog.UPLOAD_PROVIDER)
        precheck = tests.format_check(endpoint, checked_values)
        if precheck.status('format') == tests.FAIL:
            # Local mistakes are shown at once; nothing is sent anywhere.
            self._show_report(precheck)
            return

        def job():
            report = tests.free_checks(endpoint, values=checked_values)
            if temporary and report.status('format') != tests.FAIL and report.status('key') != tests.FAIL \
                    and report.status('connection') != tests.FAIL:
                for check in tests.temporary_upload_check(endpoint).checks:
                    report.add(check.level, check.status, check.detail)
            return report

        self._start(job, '正在检查格式、连线与密钥（不上传音频）…')

    def _run_oss(self):
        try:
            values = self.collected()
        except Exception as exc:
            self._format_failure(exc)
            return
        settings = self._settings_snapshot(values)
        credentials = self._oss_credentials(values)
        self._start(lambda: tests.oss_check(settings, credentials), '正在检查 OSS…')

    def _run_recognition(self):
        try:
            values = self.collected()
        except Exception as exc:
            self._format_failure(exc)
            return
        endpoint = self._endpoint(values)
        precheck = tests.format_check(endpoint, values)
        if precheck.status('format') == tests.FAIL:
            self._show_report(precheck)
            return
        from urllib.parse import urlsplit
        host = urlsplit(str(endpoint.get('url') or '')).hostname or endpoint.get('url')
        cost = tests.estimate_test_cost(endpoint, self._last_price)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr('实际短音频识别测试'))
        box.setText(tr('这一步会把测试音频上传到 {value0}，并可能产生费用。', value0=host))
        extra = tr('默认上传兔白自带的约 6 秒英文合成语音（不含你的任何素材）。也可以改选你自己的短音频（60 秒以内）。')
        if catalog.uses_own_storage(self._guide, values):
            extra += '\n' + tr('音频会先放到你的 OSS 私有存储，结果取回后删除。')
        elif self._guide.key in catalog.FILETRANS_GUIDES:
            extra += '\n' + tr('音频会先上传到服务商临时空间（你选的“仅供试用”方式，48 小时后由服务商删除），再提交识别。')
        box.setInformativeText(f'{extra}\n{tr("可能费用")}：{tr(cost)}')
        use_sample = box.addButton(tr('上传自带测试音频'), QMessageBox.ButtonRole.AcceptRole)
        choose = box.addButton(tr('选择我的音频…'), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr('取消'), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        audio_path = None
        if clicked is choose:
            audio_path, _ = QFileDialog.getOpenFileName(self, tr('选择测试音频'), '',
                                                        tr('音频 (*.wav *.mp3 *.m4a *.flac *.aac *.ogg)'))
            if not audio_path:
                return
        elif clicked is not use_sample:
            return
        settings = self._settings_snapshot(values)
        credentials = self._oss_credentials(values) if catalog.uses_own_storage(self._guide, values) else ()
        self._start(lambda: tests.short_recognition(endpoint, settings, audio_path=audio_path,
                                                    storage_credentials=credentials),
                    '正在上传并等待云端识别…（通常几十秒）')

    # ----------------------------------------------------------------- save
    def _save(self, use_as_primary: bool):
        try:
            values = self.collected()
        except Exception as exc:
            self.status.setText(ui_literal(str(exc)))
            return
        ok, message = self.host.save(self._guide.key, values, use_as_primary)
        self.status.setText(tr(message))
        if ok and use_as_primary:
            self.accept()

    def _open_advanced(self):
        if self.host.open_advanced is not None and self._guide is not None:
            key = self._guide.key
            self.accept()
            self.host.open_advanced(key)

    def done(self, result):
        for thread, _runner in list(self._threads):
            thread.quit()
            thread.wait(30000)
        super().done(result)
