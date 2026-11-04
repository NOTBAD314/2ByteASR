"""Shared project/default terminology controls and direction-aware library editor."""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoCommand
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem, QLineEdit,
    QComboBox, QDialogButtonBox, QFileDialog, QHeaderView)

from .translation_terms import KEY, SOURCE_ENABLED, normalize, policy_of
from ..i18n import tr


class TerminologySettingsCommand(QUndoCommand):
    def __init__(self, project, *, policy=None, source_ids=None, source_enabled=None, changed=None):
        super().__init__(tr('修改原文／翻译术语库'))
        self.project, self.changed = project, changed
        owned = {key: copy.deepcopy(project.generation_metadata[key]) for key in (KEY, SOURCE_ENABLED)
                 if key in project.generation_metadata}
        self.before = (owned, list(project.glossary_ids))
        meta = copy.deepcopy(owned)
        if policy is not None:
            meta[KEY] = normalize(policy)
        if source_enabled is not None:
            meta[SOURCE_ENABLED] = bool(source_enabled)
        self.after = (meta, list(project.glossary_ids if source_ids is None else source_ids))

    def _apply(self, state, previous):
        from ..timeline.studio_commands import _commit_mutation
        from ..projects.studio_runtime_state import DirtyDomain
        # Only these settings belong to this command; concurrent translations
        # and unrelated metadata must survive undo/redo.
        keys = (KEY, SOURCE_ENABLED)
        def mutate():
            for key in keys:
                if state[0].get(key) != previous[0].get(key) or (key in state[0]) != (key in previous[0]):
                    if key in state[0]:
                        self.project.generation_metadata[key] = copy.deepcopy(state[0][key])
                    else:
                        self.project.generation_metadata.pop(key, None)
            if state[1] != previous[1]:
                self.project.glossary_ids = list(state[1])
        _commit_mutation(self.project, action_id=self.text(),
            dirty=DirtyDomain.PROJECT_METADATA | DirtyDomain.AUTOSAVE | DirtyDomain.QC,
            cue_ids=(), mutate=mutate, changed=self.changed)

    def redo(self):
        self._apply(self.after, self.before)

    def undo(self):
        self._apply(self.before, self.after)


class TranslationTermsDialog(QDialog):
    def __init__(self, value, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('翻译／译文术语库'))
        self.resize(900, 600)
        self.policy = normalize(value)
        self._current = None
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox(tr('启用翻译／译文术语库（独立于原文校对）'))
        self.enabled.setChecked(self.policy['enabled'])
        layout.addWidget(self.enabled)
        self.list = QListWidget()
        self.list.setMaximumHeight(115)
        layout.addWidget(self.list)
        controls = QHBoxLayout()
        for label, handler in (('新建词库', self.add_library), ('导入…', self.import_library),
                               ('导出…', self.export_library)):
            button = QPushButton(tr(label)); button.clicked.connect(handler); controls.addWidget(button)
        layout.addLayout(controls)
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.source = QComboBox(); self.target = QComboBox()
        from ..subtitle_rules.subtitle_translation import SOURCE_LANGUAGES, TARGET_LABELS
        from ..projects.subtitle_import import language_label
        for code in SOURCE_LANGUAGES:
            self.source.addItem(language_label(code), code)
        for code, name in TARGET_LABELS.items():
            self.target.addItem(name, code)
        self.source.setCurrentIndex(max(0, self.source.findData('ja')))
        self.target.setCurrentIndex(max(0, self.target.findData('zh-Hans')))
        row.addWidget(self.name, 1); row.addWidget(self.source); row.addWidget(QLabel('→')); row.addWidget(self.target)
        layout.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr(s) for s in ('源语言术语', '标准译名', '别名／常见误识别（用 | 分隔）', '语境限制／说明')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        add = QPushButton(tr('添加术语')); add.clicked.connect(lambda: self.table.insertRow(self.table.rowCount()))
        remove = QPushButton(tr('移除所选术语')); remove.clicked.connect(self.remove_rows)
        actions.addWidget(add); actions.addWidget(remove); layout.addLayout(actions)
        self.note = QLabel(tr('勾选参与翻译的词库。语境说明用于区分同形异义；旧原文纠错库不会自动变成翻译库。可导入本窗口JSON，或按当前方向导入两列TSV。'))
        self.note.setWordWrap(True); layout.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.list.currentRowChanged.connect(self.select_library)
        for library in self.policy['libraries']:
            self._item(library)
        if not self.policy['libraries']:
            self.add_library()
        else:
            self.list.setCurrentRow(0)

    def _item(self, library):
        item = QListWidgetItem(library['name'])
        item.setData(Qt.ItemDataRole.UserRole, library['id'])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if library['id'] in self.policy['selected_ids'] else Qt.CheckState.Unchecked)
        self.list.addItem(item)

    def store_current(self):
        if self._current is None:
            return
        lib = self.policy['libraries'][self._current]
        terms = []
        for i in range(self.table.rowCount()):
            values = [self.table.item(i, j).text().strip() if self.table.item(i, j) else '' for j in range(4)]
            if any(values):
                if not values[0] or not values[1]:
                    raise ValueError(tr('每条术语必须同时填写源语言术语和标准译名'))
                terms.append(dict(source=values[0], target=values[1], aliases=values[2].split('|'), context=values[3]))
        lib.update(name=self.name.text().strip() or tr('翻译术语库'), source_language=self.source.currentData(),
                   target_language=self.target.currentData(), terms=terms)
        self.list.item(self._current).setText(lib['name'])

    def select_library(self, index):
        try:
            self.store_current()
        except ValueError as exc:
            self.note.setText(str(exc))
            self.list.blockSignals(True); self.list.setCurrentRow(self._current); self.list.blockSignals(False)
            return
        self._current = index if 0 <= index < len(self.policy['libraries']) else None
        if self._current is None:
            return
        lib = self.policy['libraries'][index]
        self.name.setText(lib['name'])
        self.source.setCurrentIndex(max(0, self.source.findData(lib['source_language'])))
        self.target.setCurrentIndex(max(0, self.target.findData(lib['target_language'])))
        self.table.setRowCount(len(lib['terms']))
        for i, term in enumerate(lib['terms']):
            for j, value in enumerate((term['source'], term['target'], '|'.join(term['aliases']), term['context'])):
                self.table.setItem(i, j, QTableWidgetItem(value))

    def add_library(self):
        lib = dict(id=uuid.uuid4().hex, name=tr('新翻译术语库'), source_language='ja', target_language='zh-Hans', terms=[])
        self.policy['libraries'].append(lib); self.policy['selected_ids'].append(lib['id'])
        self._item(lib); self.list.setCurrentRow(len(self.policy['libraries'])-1)

    def remove_rows(self):
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def value(self):
        self.store_current()
        self.policy['enabled'] = self.enabled.isChecked()
        self.policy['selected_ids'] = [self.list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.CheckState.Checked]
        return normalize(self.policy)

    def accept(self):
        try:
            self.value()
        except ValueError as exc:
            self.note.setText(str(exc)); return
        super().accept()

    def import_library(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('导入有方向的翻译术语库'), '', 'JSON / TSV (*.json *.tsv *.txt)')
        if not path: return
        try:
            self.store_current()
            text = Path(path).read_text('utf-8-sig')
            if Path(path).suffix.lower() == '.json':
                raw = json.loads(text)
                libs = raw.get('libraries', []) if isinstance(raw, dict) else []
                if not libs or any(not lib.get('source_language') or not lib.get('target_language') for lib in libs):
                    raise ValueError(tr('请选择含明确语言方向和source/target术语的翻译库；原文纠错库不能自动转换。'))
                from ..subtitle_rules.subtitle_translation import SOURCE_LANGUAGES, TARGETS
                if any(lib.get('source_language') not in SOURCE_LANGUAGES or lib.get('target_language') not in TARGETS for lib in libs):
                    raise ValueError(tr('翻译库的语言方向无效，请使用窗口列出的语言代码。'))
                libs = normalize(dict(libraries=libs))['libraries']
            else:
                from ..studio.studio_translation_dialog import parse_glossary
                pairs = parse_glossary(text)
                if not pairs: raise ValueError(tr('没有读取到源语言术语和标准译名'))
                libs = [dict(id=uuid.uuid4().hex, name=Path(path).stem, source_language=self.source.currentData(),
                    target_language=self.target.currentData(), terms=[dict(source=a,target=b,aliases=[],context='') for a,b in pairs])]
            for lib in libs:
                lib['id'] = uuid.uuid4().hex
                self.policy['libraries'].append(lib); self.policy['selected_ids'].append(lib['id']); self._item(lib)
            self.list.setCurrentRow(len(self.policy['libraries'])-1)
        except (OSError, ValueError, TypeError) as exc:
            self.note.setText(str(exc))

    def export_library(self):
        path, _ = QFileDialog.getSaveFileName(self, tr('导出翻译术语库'), 'translation-terms.json', 'JSON (*.json)')
        if not path: return
        try: Path(path).write_text(json.dumps(self.value(), ensure_ascii=False, indent=2), 'utf8')
        except (OSError, ValueError) as exc: self.note.setText(str(exc))


class TranslationTermsWidget(QWidget):
    def __init__(self, read, commit, parent=None):
        super().__init__(parent)
        self.read, self.commit = read, commit
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel(); self.summary.setWordWrap(True); layout.addWidget(self.summary, 1)
        self.manage = QPushButton(tr('选择／编辑翻译词库…')); self.manage.clicked.connect(self.edit)
        layout.addWidget(self.manage); self.refresh()

    def refresh(self):
        value = normalize(self.read())
        from ..projects.subtitle_import import language_label
        chosen = [lib for lib in value['libraries'] if lib['id'] in value['selected_ids']]
        detail = '、'.join(f"{lib['name']}（{language_label(lib['source_language'])} → {language_label(lib['target_language'])}）" for lib in chosen)
        self.summary.setText(tr('翻译／译文术语库') + '：' + (detail if value['enabled'] and detail else tr('已关闭／未选择')))

    def edit(self):
        dialog = TranslationTermsDialog(self.read(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if self.commit(dialog.value()) is False:
                self.summary.setText(tr('工程已切换，词库选择没有写入。'))
            else:
                self.refresh()


def project_widget(page, parent=None):
    def current():
        return getattr(getattr(page, 'session', None), 'project', None) or getattr(page, 'project', None)
    owner = current()
    def commit(value):
        if current() is not owner:
            return False
        if policy_of(owner) == normalize(value) and KEY in owner.generation_metadata:
            return True
        stack = getattr(getattr(page, 'session', None), 'undo_stack', None) or getattr(page, 'undo_stack', None)
        if stack is None:
            return False
        stack.push(TerminologySettingsCommand(owner, policy=value, changed=getattr(page, '_changed', None)))
        return True
    return TranslationTermsWidget(lambda: policy_of(owner), commit, parent)
