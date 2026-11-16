"""The import sheet's sources row: 选文件 / drop a file, AI 整理, which game (2026-11-16).

``attach_sources`` adds a row under the sheet's mode picker in ``TermLibraryPage.show_import_dialog``:

* 「选文件…」 and dropping a file on the editor read it with ``term_import_files.load_import_file``
  (any encoding, CSV / TSV / Excel / JSON / text) into the editor, so the user sees and can edit
  what will be read; a table gets a header line naming its columns;
* 「AI 整理」 sends the editor's text to the 字幕校对 text AI (``term_import_ai``) and puts the
  table it returns back in the editor; nothing is saved until 「确认导入可用项」;
* a game picker appears when a JSON holds several games, and only that game is imported.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton

from ..i18n import bind_text, tr

FILE_FILTER = '术语表 (*.csv *.tsv *.txt *.json *.xlsx *.xlsm);;全部文件 (*)'


class ImportEditor(QPlainTextEdit):
    """The paste box; a file dropped on it is read instead of pasted as its path."""

    file_dropped = Signal(str)

    def _local_file(self, event):
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile() and Path(url.toLocalFile()).is_file():
                    return url.toLocalFile()
        return ''

    def dragEnterEvent(self, event):  # noqa: N802 - Qt API
        if self._local_file(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):  # noqa: N802 - Qt API
        if self._local_file(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):  # noqa: N802 - Qt API
        path = self._local_file(event)
        if path:
            event.acceptProposedAction()
            self.file_dropped.emit(path)
            return
        super().dropEvent(event)


class TidyWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, text, game, settings, parent=None):
        super().__init__(parent)
        self.text, self.game, self.settings = text, game, settings
        self.role_names = header_words()          # read on the GUI thread

    def run(self):  # noqa: D401 - QThread override
        from .term_import_ai import tidy_terms
        try:
            self.done.emit(tidy_terms(self.text, self.game, self.settings, role_names=self.role_names,
                                      cancel_check=self.isInterruptionRequested))
        except Exception as exc:  # noqa: BLE001 - shown in the sheet
            self.failed.emit(' '.join(str(exc).split())[:240])


_WORKERS: set = set()


def header_words():
    """Column names for an added header line: Chinese in a Chinese UI, English otherwise."""
    from ..i18n import current_language
    from .term_import_files import ENGLISH_ROLE_NAMES, ROLE_NAMES
    return ROLE_NAMES if current_language() in {'zh', 'zh-Hant'} else ENGLISH_ROLE_NAMES


class ImportSources:
    """State of the sources row; ``selected_game()`` is None unless a multi-game JSON is loaded."""

    def __init__(self, page, layout, editor, game_name):
        self.page, self.editor, self.game_name = page, editor, game_name
        row = QHBoxLayout()
        row.setSpacing(8)
        self.pick = QPushButton(tr('选文件…'))
        self.pick.setObjectName('workshopSecondary')
        bind_text(self.pick, '读 CSV、Excel、TSV、JSON 或文本文件；也可以把文件拖进下面的框', property='toolTip')
        self.tidy = QPushButton(tr('AI 整理'))
        self.tidy.setObjectName('workshopSecondary')
        bind_text(self.tidy, '把贴进来的百科、表格或聊天文字交给 AI 挑出术语，整理成下面的表格；保存前仍可逐行检查',
                  property='toolTip')
        self.games = QComboBox()
        self.games.hide()
        self.info = QLabel()
        self.info.setObjectName('muted')
        self.info.setWordWrap(True)
        row.addWidget(self.pick)
        row.addWidget(self.tidy)
        row.addWidget(self.games)
        row.addWidget(self.info, 1)
        layout.addLayout(row)
        self.pick.clicked.connect(self.choose_file)
        self.tidy.clicked.connect(self.start_tidy)
        editor.file_dropped.connect(self.load)
        editor.textChanged.connect(self.refresh_games)
        self.worker = None

    # ---------------------------------------------------------------- files
    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self.page, tr('导入术语'), '', tr(FILE_FILTER))
        if path:
            self.load(path)

    def load(self, path):
        from .term_import_files import load_import_file
        try:
            loaded = load_import_file(path, role_names=header_words())
        except (OSError, ValueError) as exc:
            self.info.setText(tr('读不了这个文件：{value0}', value0=' '.join(str(exc).split())[:160]))
            return
        self.editor.setPlainText(loaded['text'])
        name = Path(path).name
        encoding = '' if loaded['encoding'] in {'utf-8', 'xlsx'} else f"（{loaded['encoding']}）"
        if loaded['header_added']:
            self.info.setText(tr('已读取 {value0}{value1}。第一行是我猜的列名（术语 / 别名 / 分类 / 忽略），不对可以直接改。',
                                 value0=name, value1=encoding))
        else:
            self.info.setText(tr('已读取 {value0}{value1}。', value0=name, value1=encoding))

    # ---------------------------------------------------------------- games
    def refresh_games(self):
        from .term_import_files import json_game_groups
        groups = json_game_groups(self.editor.toPlainText()) if self.editor.toPlainText().lstrip().startswith('{') else []
        names = [name for name, _count in groups]
        current = [self.games.itemData(i) for i in range(self.games.count())]
        if names == current:
            return
        self.games.blockSignals(True)
        self.games.clear()
        for name, count in groups:
            self.games.addItem(tr('{value0}（{value1} 条）', value0=name, value1=count), name)
        if groups:
            index = next((i for i, name in enumerate(names) if name == self.game_name), 0)
            self.games.setCurrentIndex(index)
        self.games.blockSignals(False)
        self.games.setVisible(len(groups) > 1)
        if len(groups) > 1:
            self.info.setText(tr('这个文件里有 {value0} 个游戏，只导入选中的那个。', value0=len(groups)))

    def selected_game(self):
        if not self.games.isHidden() and self.games.count() > 1:
            return self.games.currentData()
        return None

    # ---------------------------------------------------------------- AI 整理
    def start_tidy(self):
        text = self.editor.toPlainText().strip()
        if not text:
            self.info.setText(tr('先在下面贴一段资料，再按「AI 整理」。'))
            return
        settings = self.page._ai_update_settings()
        if self.page._ai_update_needs_key(settings):
            return
        self.tidy.setEnabled(False)
        self.info.setText(tr('AI 正在整理，一般十几秒到一分钟…'))
        worker = TidyWorker(text, self.game_name, settings, self.page)
        self.worker = worker
        _WORKERS.add(worker)
        worker.done.connect(self._tidied)
        worker.failed.connect(self._tidy_failed)
        worker.finished.connect(lambda: _WORKERS.discard(worker))
        worker.start()

    def _alive(self):
        try:
            self.tidy.isEnabled()
            return True
        except RuntimeError:          # the sheet was closed while the AI worked
            return False

    def _tidied(self, result):
        if not self._alive():
            return
        self.tidy.setEnabled(True)
        self.editor.setPlainText(result['text'])
        note = tr('AI 整理出 {value0} 个词，下面逐行检查后再导入。', value0=result['kept'])
        if result.get('dropped'):
            note += tr('另有 {value0} 个原文里找不到的词已丢掉。', value0=result['dropped'])
        if result.get('truncated'):
            note += tr('资料太长，只整理了前 1.2 万字。')
        self.info.setText(note)

    def _tidy_failed(self, message):
        if not self._alive():
            return
        self.tidy.setEnabled(True)
        self.info.setText(tr('AI 整理没有完成：{value0}', value0=message))


def attach_sources(page, layout, editor, game_name) -> ImportSources:
    return ImportSources(page, layout, editor, game_name)


__all__ = ['ImportEditor', 'ImportSources', 'TidyWorker', 'attach_sources']
