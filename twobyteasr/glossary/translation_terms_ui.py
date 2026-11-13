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
    QComboBox, QDialogButtonBox, QFileDialog, QHeaderView, QMessageBox, QRadioButton,
    QInputDialog)

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
            if state[0].get(KEY) != previous[0].get(KEY):
                from .translation_terms import _index
                _index.cache_clear()
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
        self.policy['libraries'] = [lib for lib in self.policy['libraries'] if not lib.get('shared_concepts')]
        self._current = None
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox(tr('启用翻译／译文术语库（独立于原文校对）'))
        self.enabled.setChecked(self.policy['enabled'])
        layout.addWidget(self.enabled)
        self.list = QListWidget()
        self.list.setMaximumHeight(115)
        layout.addWidget(self.list)
        controls = QHBoxLayout()
        self.delete_button = QPushButton(tr('删除词库'))
        self.delete_button.clicked.connect(self.delete_library)
        for label, handler in (('新建词库', self.add_library), ('导入…', self.import_library),
                               ('导出…', self.export_library)):
            button = QPushButton(tr(label)); button.clicked.connect(handler); controls.addWidget(button, 1)
            if handler == self.export_library:
                self.export_button = button
        controls.addWidget(self.delete_button, 1)
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
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr(s) for s in ('源语言术语', '标准译名', '别名／常见误识别（用 | 分隔）', '语境限制／说明', '允许的目标别名（用 | 分隔）')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        add = QPushButton(tr('添加术语')); add.clicked.connect(lambda: self.table.insertRow(self.table.rowCount()))
        remove = QPushButton(tr('移除所选术语')); remove.clicked.connect(self.remove_rows)
        self.add_term_button, self.remove_term_button = add, remove
        actions.addWidget(add); actions.addWidget(remove); layout.addLayout(actions)
        from .multilingual_terms_ui import SharedLibrariesPanel
        self.shared_panel = SharedLibrariesPanel(self.policy, self)
        layout.addWidget(self.shared_panel)
        self.note = QLabel(tr('勾选参与翻译的词库。语境说明用于区分同形异义；旧原文纠错库不会自动变成翻译库。可导入本窗口JSON，或按当前方向导入两列TSV。'))
        self.note.setWordWrap(True); layout.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.list.currentRowChanged.connect(self.select_library)
        for library in self.policy['libraries']:
            self._item(library)
        if self.policy['libraries']:
            self.list.setCurrentRow(0)
        else:
            self._load_current()

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
            values = [self.table.item(i, j).text().strip() if self.table.item(i, j) else '' for j in range(5)]
            if any(values):
                if not values[0] or not values[1]:
                    raise ValueError(tr('每条术语必须同时填写源语言术语和标准译名'))
                terms.append(dict(source=values[0], target=values[1],
                    aliases=list(dict.fromkeys(a.strip() for a in values[2].split('|') if a.strip())), context=values[3], target_aliases=[a.strip() for a in values[4].split('|') if a.strip()]))
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
        self._load_current()

    def _load_current(self):
        for control in (self.name, self.source, self.target, self.table, self.add_term_button,
                        self.remove_term_button, self.export_button, self.delete_button):
            control.setEnabled(self._current is not None)
        # Shared concepts need a conflict-inspection direction even when no
        # older directional library has been created in this dialog.
        self.source.setEnabled(True); self.target.setEnabled(True)
        if self._current is None:
            self.name.clear(); self.table.setRowCount(0)
            return
        lib = self.policy['libraries'][self._current]
        self.name.setText(lib['name'])
        self.source.setCurrentIndex(max(0, self.source.findData(lib['source_language'])))
        self.target.setCurrentIndex(max(0, self.target.findData(lib['target_language'])))
        self.table.setRowCount(len(lib['terms']))
        for i, term in enumerate(lib['terms']):
            for j, value in enumerate((term['source'], term['target'], '|'.join(term['aliases']), term['context'], '|'.join(term.get('target_aliases', ())))):
                self.table.setItem(i, j, QTableWidgetItem(value))

    def add_library(self):
        try:
            self.store_current()
        except ValueError as exc:
            self.note.setText(str(exc)); return
        lib = dict(id=uuid.uuid4().hex, name=tr('新翻译术语库'), source_language='ja', target_language='zh-Hans', terms=[])
        self.policy['libraries'].append(lib); self.policy['selected_ids'].append(lib['id'])
        self._item(lib); self.list.setCurrentRow(len(self.policy['libraries'])-1)

    def _sync_checks(self):
        self.policy['selected_ids'] = [self.list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def _reload_libraries(self, current_id=''):
        self._current = None
        self.list.blockSignals(True)
        self.list.clear()
        for lib in self.policy['libraries']:
            self._item(lib)
        index = next((i for i, lib in enumerate(self.policy['libraries']) if lib['id'] == current_id),
                     0 if self.policy['libraries'] else -1)
        self.list.setCurrentRow(index)
        self.list.blockSignals(False)
        self._current = index if index >= 0 else None
        self._load_current()

    def delete_library(self):
        if self._current is None:
            return
        lib = self.policy['libraries'][self._current]
        name = self.name.text().strip() or lib['name']
        count = sum(any(self.table.item(i, j) and self.table.item(i, j).text().strip()
                        for j in range(4)) for i in range(self.table.rowCount()))
        answer = QMessageBox.question(self, tr('删除整份译文词库'),
            tr('将删除整份词库“{name}”（{count} 条术语）。其他词库不受影响。点击本窗口“确定”后才会保存；“取消”可放弃此次删除。', name=name, count=count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._sync_checks()
        index = self._current
        identity = lib['id']
        self.policy['libraries'].pop(index)
        self.policy['selected_ids'] = [key for key in self.policy['selected_ids'] if key != identity]
        remaining = self.policy['libraries']
        self._reload_libraries(remaining[min(index, len(remaining)-1)]['id'] if remaining else '')
        self.note.setText(tr('已暂存删除“{name}”；点击“确定”保存，点击“取消”放弃。', name=name))

    def remove_rows(self):
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def value(self):
        self.store_current()
        self.shared_panel.store()
        self.policy['enabled'] = self.enabled.isChecked()
        self._sync_checks()
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
            from .translation_terms_import import parse_libraries
            text = Path(path).read_text('utf-8-sig')
            libs = parse_libraries(text, is_json=Path(path).suffix.lower() == '.json', name=Path(path).stem,
                source_language=self.source.currentData(), target_language=self.target.currentData())
            mode = self.choose_import_mode()
            if mode is None:
                return
            if mode == 'append' and len(libs) > 1:
                labels = [f"{i+1}. {lib['name']}（{lib['source_language']} → {lib['target_language']}，{len(lib['terms'])} 条）"
                          for i, lib in enumerate(libs)]
                label, ok = QInputDialog.getItem(self, tr('选择要追加的词库'),
                    tr('JSON 含多个词库。请选择一份追加到当前高亮词库；其他词库不会混入。'), labels, 0, False)
                if not ok:
                    return
                libs = [libs[labels.index(label)]]
            decisions = {}
            if mode == 'append':
                from .translation_terms_import import merge_library
                _lib, _stats, conflicts = merge_library(self.policy['libraries'][self._current], libs[0])
                if conflicts:
                    decisions = self.choose_conflicts(conflicts)
                    if decisions is None:
                        return
            self.apply_import(libs, mode=mode, decisions=decisions)
        except (OSError, ValueError, TypeError) as exc:
            self.note.setText(str(exc))

    def choose_import_mode(self):
        dialog = QDialog(self); dialog.setWindowTitle(tr('选择导入方式'))
        layout = QVBoxLayout(dialog)
        lib = self.policy['libraries'][self._current] if self._current is not None else None
        append = QRadioButton(tr('追加到当前词库：{name}', name=lib['name']) if lib else tr('追加到当前词库（请先选择词库）'))
        append.setEnabled(lib is not None); append.setChecked(lib is not None)
        new = QRadioButton(tr('导入为新词库')); new.setChecked(lib is None)
        layout.addWidget(append); layout.addWidget(new)
        note = QLabel(tr('目标只取当前高亮词库。上方勾选框仅表示是否参与翻译。新增内容将在主窗口“确定”后保存。'))
        note.setWordWrap(True); layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        return ('append' if append.isChecked() else 'new') if dialog.exec() == QDialog.Accepted else None

    def choose_conflicts(self, conflicts):
        dialog = QDialog(self); dialog.setWindowTitle(tr('处理译名／语境冲突')); dialog.resize(850, 430)
        layout = QVBoxLayout(dialog)
        note = QLabel(tr('相同源术语存在不同译名、语境或别名。默认保留现有内容；采用导入会替换该源术语的现有条目组，也可明确同时保留。'))
        note.setWordWrap(True); layout.addWidget(note)
        table = QTableWidget(len(conflicts), 4)
        table.setHorizontalHeaderLabels([tr(s) for s in ('源术语', '现有内容', '导入内容', '处理方式')])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        choices = []
        def summary(rows):
            return '\n'.join(f"{r['target']} · {r['context'] or '无语境限制'} · {'|'.join(r['aliases'])}" for r in rows)
        for i, conflict in enumerate(conflicts):
            for j, text in enumerate((conflict['source'], summary(conflict['existing']), summary(conflict['incoming']))):
                item = QTableWidgetItem(text); item.setFlags(item.flags() & ~Qt.ItemIsEditable); item.setToolTip(text)
                table.setItem(i, j, item)
            box = QComboBox()
            for text, key in (('保留现有内容', 'keep'), ('采用导入内容', 'imported'), ('同时保留', 'both')):
                box.addItem(tr(text), key)
            table.setCellWidget(i, 3, box); choices.append(box)
        table.resizeRowsToContents(); layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return None
        return {c['key']: box.currentData() for c, box in zip(conflicts, choices)}

    def apply_import(self, libraries, *, mode, decisions=None):
        """Commit one fully parsed import to this dialog's private draft only."""
        from .translation_terms_import import merge_library, unique_terms
        self.store_current(); self._sync_checks()
        draft = copy.deepcopy(self.policy)
        if mode == 'append':
            if self._current is None or len(libraries) != 1:
                raise ValueError('追加必须明确选择当前词库及一份导入词库')
            target, stats, _conflicts = merge_library(draft['libraries'][self._current], libraries[0], decisions)
            draft['libraries'][self._current] = target
            selected_id = target['id']
        elif mode == 'new':
            stats = dict(added=0, duplicates=0, conflicts=0, replaced=0)
            selected_id = ''
            for library in libraries:
                lib = copy.deepcopy(library); lib['id'] = uuid.uuid4().hex
                lib['terms'], duplicates = unique_terms(lib['terms'])
                stats['added'] += len(lib['terms']); stats['duplicates'] += duplicates
                draft['libraries'].append(lib); draft['selected_ids'].append(lib['id']); selected_id = lib['id']
        else:
            raise ValueError('无效的导入方式')
        self.policy = draft
        self._reload_libraries(selected_id)
        self.note.setText(tr('新增 {added} 条；重复跳过 {duplicates} 条；冲突 {conflicts} 条；采用导入 {replaced} 条。点击“确定”保存，点击“取消”放弃。', **stats))
        return stats

    def export_library(self):
        path, _ = QFileDialog.getSaveFileName(self, tr('导出翻译术语库'), 'translation-terms.json', 'JSON (*.json)')
        if not path: return
        try: Path(path).write_text(json.dumps(self.value(), ensure_ascii=False, indent=2), 'utf8')
        except (OSError, ValueError) as exc: self.note.setText(str(exc))


class TranslationTermsWidget(QWidget):
    def __init__(self, read, commit, parent=None, *, compact=False):
        super().__init__(parent)
        self.read, self.commit = read, commit
        self.compact = compact
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel(); self.summary.setWordWrap(True); layout.addWidget(self.summary, 1)
        self.manage = QPushButton(tr('选择／编辑词库…' if compact else '选择／编辑翻译词库…')); self.manage.clicked.connect(self.edit)
        layout.addWidget(self.manage); self.refresh()

    def refresh(self):
        value = normalize(self.read())
        from ..projects.subtitle_import import language_label
        chosen = [lib for lib in value['libraries'] if lib['id'] in value['selected_ids']]
        detail = '、'.join(f"{lib['name']}（多语言）" if lib.get('shared_concepts') else f"{lib['name']}（{language_label(lib['source_language'])} → {language_label(lib['target_language'])}）" for lib in chosen)
        if not detail and value.get('concept_library_ids'):
            import subtitle_core as legacy
            detail = '、'.join(legacy.glossary_display_name(i) + '（多语言）' for i in value['concept_library_ids'])
        self.summary.setText(tr('译文词库' if self.compact else '翻译／译文术语库') + '：' + (detail if value['enabled'] and detail else tr('已关闭／未选择')))
        self.summary.setToolTip(self.summary.text())

    def edit(self):
        dialog = TranslationTermsDialog(self.read(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if self.commit(dialog.value()) is False:
                self.summary.setText(tr('工程已切换，词库选择没有写入。'))
            else:
                from .translation_terms import _index
                _index.cache_clear()
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
