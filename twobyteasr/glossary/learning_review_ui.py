"""Explicit review actions, separate from the formal term-card collection."""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout)

from .learning_review import suspected_legacy


class LearningReviewPanel(QFrame):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.store = owner._learning_store
        self.entries = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 10, 8)
        # 2026-11-13 (plan 2026-11-13-glossary-library-redesign-c): one 待处理
        # strip. Subtitle candidates first; multilingual_terms_ui adds the
        # translation chips to ``header_layout``.
        self.setObjectName("termPendingStrip")
        header = QHBoxLayout()
        header.setSpacing(8)
        self.header_layout = header
        title = QLabel("待处理")
        title.setObjectName("termPendingTitle")
        header.addWidget(title)
        from .glossary_page_parts import FlowLayout, StripChip
        # Chips wrap onto a second line when the panel is narrow (drawer open).
        chips = QFrame(); chips.setObjectName("termPendingChips")
        self.chip_layout = FlowLayout(chips, spacing=8)
        self.count = StripChip(tone="accent")
        self.count.setToolTip("字幕已修改。候选仅在明确加入术语库后生效。")
        self.count.clicked.connect(lambda _checked: self._toggle())
        self.chip_layout.addWidget(self.count)
        header.addWidget(chips, 1)
        self.hint = QLabel("字幕已改，候选需确认后才进词库")
        self.hint.setObjectName("termPendingHint")
        header.addWidget(self.hint)
        self.toggle = QPushButton("开始审核")
        self.toggle.setObjectName("termPendingAction")
        self.toggle.clicked.connect(self._toggle)
        header.addWidget(self.toggle)
        self.history = QPushButton("检查历史条目")
        self.history.setObjectName("termGhostButton")
        self.history.clicked.connect(self.open_history)
        self.history.setToolTip("检查来源不明的旧条目，由你选择移至待确认或忽略")
        header.addWidget(self.history)
        layout.addLayout(header)
        self.box = QFrame()
        body = QVBoxLayout(self.box)
        body.setContentsMargins(0, 0, 0, 0)
        self.listing = QListWidget()
        self.listing.setObjectName("termLearningList")
        self.listing.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.listing.itemChanged.connect(self._actions)
        self.listing.itemSelectionChanged.connect(self._actions)
        self.listing.itemDoubleClicked.connect(lambda _item: self.edit_current())
        body.addWidget(self.listing)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        body.addWidget(self.summary)
        actions = QHBoxLayout()
        self.select_all = QPushButton("全选候选")
        self.select_all.clicked.connect(self._select_all)
        actions.addWidget(self.select_all)
        self.edit = QPushButton("编辑候选…")
        self.edit.clicked.connect(self.edit_current)
        actions.addWidget(self.edit)
        self.single = QPushButton("加入术语库")
        self.single.clicked.connect(lambda: self.commit(self.current_ids()))
        actions.addWidget(self.single)
        self.accept = QPushButton("加入所选（0 条）")
        self.accept.clicked.connect(lambda: self.commit(self.checked_ids()))
        actions.addWidget(self.accept)
        self.ignore = QPushButton("忽略")
        self.ignore.clicked.connect(self.ignore_selected)
        actions.addWidget(self.ignore)
        body.addLayout(actions)
        self.box.hide()
        layout.addWidget(self.box)

    def _fit_hint(self):
        """The hint is the first thing to go when the strip is narrow."""
        self.hint.setVisible(getattr(self, '_pending', False) and self.width() >= 1000)

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._fit_hint()

    def _toggle(self):
        self.box.setVisible(self.box.isHidden())
        self.toggle.setText("收起" if not self.box.isHidden() else "开始审核")

    def _libraries(self):
        games = self.owner.legacy.load_learned_term_payload(strict=True).get("games", {})
        return {key: str(row.get("game") or key) for key, row in games.items()}

    def current_ids(self):
        item = self.listing.currentItem()
        return [str(item.data(Qt.ItemDataRole.UserRole))] if item else []

    def checked_ids(self):
        return [str(self.listing.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(self.listing.count())
                if self.listing.item(i).checkState() == Qt.CheckState.Checked]

    def _select_all(self):
        checked = len(self.checked_ids()) != self.listing.count()
        self.listing.blockSignals(True)
        for i in range(self.listing.count()):
            self.listing.item(i).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.listing.blockSignals(False)
        self._actions()

    def _actions(self, *_args):
        checked = self.checked_ids()
        current = self.current_ids()
        self.accept.setEnabled(bool(checked))
        self.accept.setText(f"加入所选（{len(checked)} 条）")
        self.single.setEnabled(bool(current))
        self.edit.setEnabled(bool(current))
        self.ignore.setEnabled(bool(checked or current))
        counts = Counter(self.entries[key].get("glossary_id") or "" for key in checked if key in self.entries)
        self.summary.setText("勾选仅表示选择。" + "　".join(
            f"《{self.names.get(key, key) if key else '尚未指定词库'}》{count} 条" for key, count in counts.items()))
        if current:
            destination = self.entries.get(current[0], {}).get("glossary_id", "")
            self.single.setToolTip(f"明确确认 1 条，加入《{self.names.get(destination, destination) or '请先编辑目标词库'}》")

    def refresh(self):
        try:
            self.store.sync_legacy(self.owner.legacy)
            self.names = self._libraries()
            pending = self.store.pending()
        except (OSError, ValueError, TypeError) as exc:
            self.count.setText("候选读取失败")
            self.summary.setText(str(exc))
            self.box.show()
            self.show()
            return
        checked, current = set(self.checked_ids()), self.current_ids()
        self.entries = {row['id']: row for row in pending}
        self.listing.blockSignals(True)
        self.listing.clear()
        for row in pending:
            key = row.get('glossary_id', '')
            target = self.names.get(key, key) if key else '尚未指定词库'
            item = QListWidgetItem(f"待确认　{row['original_term']} → {row['corrected_term']}"
                                   f"　《{target}》 · {row.get('language', 'und')} · 原文")
            item.setData(Qt.ItemDataRole.UserRole, row['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if row['id'] in checked else Qt.CheckState.Unchecked)
            item.setToolTip("\n".join([*row.get('contexts', ()), row.get('last_error', ''),
                "双击可编辑候选，勾选、查看和关闭均不会入库"]))
            self.listing.addItem(item)
            if row['id'] in current:
                self.listing.setCurrentItem(item)
        self.listing.blockSignals(False)
        self.count.setText(f"{len(pending)} 条字幕候选")
        self.toggle.setEnabled(bool(pending))
        # Nothing waiting: keep only the history check in the strip.
        self.count.setVisible(bool(pending))
        self.toggle.setVisible(bool(pending))
        self._pending = bool(pending)
        self._fit_hint()
        if not pending and not self.box.isHidden():
            self._toggle()
        self.listing.setFixedHeight(min(max(len(pending), 1), 5) * 34 + 8)
        self._actions()
        self.show()  # Historical inspection remains available even with no new candidates.

    def _changed(self):
        self.owner._mappings_cache.clear()
        self.owner._notify_library_changed()
        self.owner.refresh_current_game()
        self.refresh()

    def commit(self, identities):
        if not identities:
            return
        count = 0
        added = 0
        errors = []
        try:
            groups = {}
            for key in identities:
                row = self.entries[key]
                destination = str(row.get('glossary_id') or '')
                if not destination:
                    errors.append(f"{row['corrected_term']} 尚未指定词库，请先编辑候选")
                    continue
                groups.setdefault(destination, []).append(key)
            for destination, keys in groups.items():
                count += self.store.accept(keys, destination,
                    add_mapping=self.owner.legacy.confirm_learning_candidate)
                added += self.store.added_count
                errors.extend(self.store.errors)
        except (OSError, ValueError, TypeError) as exc:
            errors.append(str(exc))
        finally:
            # A formal write may have succeeded just before a ledger IO failure.
            self._changed()
        message = f"已确认 {count} 条，新增正式规则 {added} 条。" if count else ""
        self.owner._show_toast(message + ("候选保留，" + "；".join(errors) if errors else ""), 6000)

    def ignore_selected(self):
        keys = self.checked_ids() or self.current_ids()
        try:
            count = self.store.ignore(keys)
            self.refresh()
            self.owner._show_toast(f"已忽略 {count} 条候选，字幕修改已保留。")
        except (OSError, ValueError) as exc:
            self.owner._show_toast("忽略失败，候选已保留。" + str(exc))

    def edit_current(self):
        keys = self.current_ids()
        if not keys:
            return
        key = keys[0]
        row = self.entries[key]
        dialog = QDialog(self)
        dialog.setWindowTitle("编辑待确认候选")
        dialog.resize(520, 260)
        form = QFormLayout(dialog)
        source, target = QLineEdit(row['original_term']), QLineEdit(row['corrected_term'])
        destination = QComboBox()
        destination.addItem("请选择目标词库", "")
        for identity, name in self.names.items():
            destination.addItem(name, identity)
        destination.setCurrentIndex(max(0, destination.findData(row.get('glossary_id', ''))))
        form.addRow("误识别写法（可不填）", source)
        form.addRow("规范词", target)
        form.addRow("目标词库", destination)
        form.addRow("用途及语言", QLabel(f"原文 · {row.get('language', 'und')}"))
        error = QLabel()
        error.setWordWrap(True)
        form.addRow(error)
        buttons = QHBoxLayout()
        save, confirm = QPushButton("保存候选"), QPushButton("加入术语库（1 条）")
        buttons.addWidget(save)
        buttons.addWidget(confirm)
        form.addRow(buttons)

        def submit(commit=False):
            try:
                self.store.edit_candidate(key, source.text(), target.text(), destination.currentData())
            except (OSError, ValueError) as exc:
                error.setText(str(exc))
                return
            self.refresh()
            if commit:
                self.commit([key])
                if key in self.entries:
                    error.setText(self.entries[key].get('last_error', '候选尚未写入，请检查提示'))
                    return
            dialog.accept()

        save.clicked.connect(lambda: submit(False))
        confirm.clicked.connect(lambda: submit(True))
        self.editor = dialog
        self.edit_source, self.edit_target, self.edit_destination = source, target, destination
        self.edit_save, self.edit_confirm = save, confirm
        dialog.show()

    def open_history(self):
        key = self.owner._library_key()
        payload = self.owner.legacy.load_learned_term_payload()
        games = payload.get('games', {})
        identity = self.owner.legacy._glossary_entry_key(key, games)
        rows = [row for row in games.get(identity, {}).get('mappings', ()) if suspected_legacy(row)]
        dialog = QDialog(self)
        dialog.setWindowTitle("疑似自动收录的历史条目")
        dialog.resize(620, 380)
        layout = QVBoxLayout(dialog)
        hint = QLabel(f"《{self.names.get(identity, identity)}》共 {len(rows)} 条来源待核查。"
                      "来源不足以自动判断，请勾选后主动处理。原始记录随条目保留。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        listing = QListWidget()
        for row in rows:
            item = QListWidgetItem(f"{row.get('from')} → {row.get('to')}　{row.get('origin') or '来源不明'}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            listing.addItem(item)
        layout.addWidget(listing)
        actions = QHBoxLayout()
        layout.addLayout(actions)

        def apply(ignore):
            keys = [(row.get('from'), row.get('to')) for i, row in enumerate(rows)
                    if listing.item(i).checkState() == Qt.CheckState.Checked]
            if not keys:
                return
            try:
                self.owner.legacy.review_legacy_mappings(identity, keys, ignore=ignore)
                self.store.sync_legacy(self.owner.legacy)
            except (OSError, ValueError) as exc:
                hint.setText("处理未完成，原始记录保留。" + str(exc))
                self._changed()
                return
            self._changed()
            dialog.accept()

        for label, ignore in (("将所选移至待确认", False), ("忽略所选", True)):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, ignored=ignore: apply(ignored))
            actions.addWidget(button)
        self.history_dialog = dialog
        dialog.show()
