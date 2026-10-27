"""Explicit Markdown input and occurrence-local formatting for ordinary captions."""
from copy import deepcopy
import json
from PySide6.QtCore import Qt, QSignalBlocker, QMimeData
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QKeySequence
from PySide6.QtWidgets import QWidget, QHBoxLayout, QComboBox, QToolButton, QColorDialog
from ..caption_style.text_marks import (parse_markdown, markdown_text, layer_marks,
    with_marks, remap_marks, edit_marks, normalize_marks, python_offset, utf16_offset, runs)
from ..diagnostics.input_latency import InputLatencyTextEdit
from ..i18n import bind_text, tr


class CaptionInputEdit(InputLatencyTextEdit):
    MIME = 'application/x-2byte-caption-marks-v1'

    def keyPressEvent(self, event):
        tools = getattr(self, '_caption_tools', None)
        if tools is not None and (event.matches(QKeySequence.Undo) or event.matches(QKeySequence.Redo)):
            stack = tools.page.undo_stack
            stack.undo() if event.matches(QKeySequence.Undo) else stack.redo()
            cue = tools.current()
            if cue is not None: tools.hydrate(cue, tools.body(cue))
            event.accept()
            return
        super().keyPressEvent(event)

    def createMimeDataFromSelection(self):
        base = super().createMimeDataFromSelection()
        tools = getattr(self, '_caption_tools', None)
        if tools is None or tools.current() is None or not self.textCursor().hasSelection(): return base
        # Qt's lazy QTextDocument MIME object does not advertise added formats.
        mime = QMimeData()
        for name in base.formats(): mime.setData(name, base.data(name))
        text = self.toPlainText(); cursor = self.textCursor()
        a,b = python_offset(text,cursor.selectionStart()),python_offset(text,cursor.selectionEnd())
        if tools.mode.currentIndex():
            text,_,positions = parse_markdown(text)
            a,b = sum(i<a for i in positions),sum(i<b for i in positions)
        if a>=b:return base
        marks = [dict(m,start=max(a,m['start'])-a,end=min(b,m['end'])-a)
                 for m in normalize_marks(text,layer_marks(tools.current(),tools.layer)) if m['start']<b and m['end']>a]
        selected=text[a:b]
        mime.setText(selected)
        mime.setData(self.MIME,json.dumps({'text':selected,'marks':marks},ensure_ascii=False).encode('utf8'))
        mime.setData('text/markdown',markdown_text(selected,marks).encode('utf8'))
        return mime

    def insertFromMimeData(self, mime):
        tools = getattr(self, '_caption_tools', None)
        if tools is None or not mime.hasFormat(self.MIME):
            return super().insertFromMimeData(mime)
        try:
            payload = json.loads(bytes(mime.data(self.MIME)))
            text = str(payload['text']); marks = normalize_marks(text,payload.get('marks',[]))
        except (ValueError, KeyError, TypeError):
            return super().insertFromMimeData(mime)
        raw=self.toPlainText()
        start=python_offset(raw,self.textCursor().selectionStart())
        if tools.mode.currentIndex():
            _,_,positions=parse_markdown(raw)
            start=sum(i<start for i in positions)
        tools.page.undo_stack.beginMacro('粘贴字幕与局部格式')
        try:
            self.insertPlainText(markdown_text(text,marks) if tools.mode.currentIndex() else text)
            if tools.layer == 'translation' and callable(getattr(self, 'commit', None)):
                self.commit()  # the bound draft must exist before pasted marks target its text
            cue = tools.current()
            if cue is not None:
                kept=[m for m in layer_marks(cue,tools.layer) if not (start<=m['start'] and m['end']<=start+len(text))]
                tools.apply(tools.body(cue), kept +
                    [dict(m,start=m['start']+start,end=m['end']+start) for m in marks])
        finally: tools.page.undo_stack.endMacro()


class MarkHighlighter(QSyntaxHighlighter):
    """Visual formatting without replacing the editor document or its undo stack."""
    def __init__(self, editor):
        super().__init__(editor.document())
        self.editor = editor
        self.marks = []

    def highlightBlock(self, text):
        if self.editor.property('captionMarkdown'):
            return
        body = self.editor.toPlainText()
        offset = self.currentBlock().position()
        for start, end, attrs in runs(body, self.marks):
            mark = dict(start=start, end=end, **attrs)
            a, b = utf16_offset(body, mark['start'])-offset, utf16_offset(body, mark['end'])-offset
            if a >= len(text.encode('utf-16-le'))//2 or b <= 0:
                continue
            fmt = QTextCharFormat()
            if 'bold' in mark or 'italic' in mark: fmt.setFontStyleName('')
            if 'bold' in mark: fmt.setFontWeight(700 if mark['bold'] else 400)
            if 'italic' in mark: fmt.setFontItalic(bool(mark['italic']))
            if mark.get('color'): fmt.setForeground(QColor(mark['color']))
            elif mark.get('highlight'): fmt.setForeground(QColor('#FFD166'))
            self.setFormat(max(0, a), min(b, len(text.encode('utf-16-le'))//2)-max(0, a), fmt)


class CaptionTextTools(QWidget):
    def __init__(self, page, editor, layer):
        super().__init__(page)
        self.page, self.editor, self.layer = page, editor, layer
        self._last_raw = editor.toPlainText()
        self._last_mode = 0
        self._pending_edit = None
        editor.document().contentsChange.connect(self.content_change)
        self.highlighter = MarkHighlighter(editor)
        editor._caption_tools = self
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.mode = QComboBox(self)
        self.mode.addItems(['纯文字', 'Markdown'])
        # The real app pins every combo to 180 px (design.presentation.prepare_controls); in this
        # narrow row that drew B / I over the box. It only needs its own text (2026-10-25).
        self.mode.setProperty('fieldWidth', 'captionTextMode')
        self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.mode.setToolTip('Markdown：**粗体**、*斜体*、==重点==（兔白扩展）；\\ 可转义，`文字` 原样输入。')
        layout.addWidget(self.mode)
        for label, field in [('B', 'bold'), ('I', 'italic'), ('重点', 'highlight'), ('颜色', 'color'), ('清除', 'clear')]:
            button = QToolButton(self); button.setText(label); button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda checked=False, key=field: self.format_selection(key))
            layout.addWidget(button)
        self.mode.currentIndexChanged.connect(self.change_mode)

    def current(self):
        binding = getattr(self.editor, "binding", None)
        if self.layer == "translation" and binding is not None:
            return (next((cue for cue in binding[0].cues if cue.id == binding[1]), None)
                    if self.page.project is binding[0] else None)
        return self.page.session._cue_lookup.get(self.page.selected_cue_id)

    def content_change(self, position, removed, added):
        raw = self.editor.toPlainText()
        if raw != self._last_raw:
            self._pending_edit = (self._last_raw, raw, position, removed, added)
            self._last_raw = raw

    def split_position(self):
        raw = self.editor.toPlainText()
        pos = python_offset(raw, self.editor.textCursor().position())
        if self.mode.currentIndex():
            _, _, positions = parse_markdown(raw)
            pos = sum(index < pos for index in positions)
        return pos

    def body(self, cue):
        return (str(self.page.project.generation_metadata.get('translations', {}).get(cue.id, ''))
                if self.layer == 'translation' else cue.text)

    def hydrate(self, cue, body):
        self.highlighter.marks = layer_marks(cue, self.layer)
        if not getattr(self.page, '_text_input_in_progress', False):
            value = markdown_text(body, self.highlighter.marks) if self.mode.currentIndex() else body
            if value != self.editor.toPlainText():
                blocker = QSignalBlocker(self.editor)
                self.editor.setPlainText(value)
                del blocker
        if self.layer == 'translation':
            bind_text(self.editor, '译文按自身词界估算分配，尚待核对；无法分配时保留整组译文。'
                      if cue.appearance_override.get('translation_group') else '', property='toolTip')
        if self.layer == 'original':
            # A project note; known notes are catalog keys (older Traditional ones show as written).
            bind_text(self.editor, str(cue.appearance_override.get('text_marks_review', '')), property='toolTip')
        self.rehighlight()

    def rehighlight(self):
        # QTextDocument formatting can emit the editor's textChanged signal.
        # It is a paint update, never another user text command.
        blocker = QSignalBlocker(self.editor)
        try: self.highlighter.rehighlight()
        finally: del blocker

    def change_mode(self, index):
        if self.layer == 'translation' and getattr(self.editor, 'dirty', False):
            blocker = QSignalBlocker(self.mode)
            self.mode.setCurrentIndex(self._last_mode)
            self.editor.commit()
            self.mode.setCurrentIndex(index)
            del blocker
        self._last_mode = index
        self.editor.setProperty('captionMarkdown', bool(index))
        cue = self.current()
        if cue is not None: self.hydrate(cue, self.body(cue))

    def commit(self):
        cue = self.current()
        if cue is None: return
        raw, previous = self.editor.toPlainText(), self.body(cue)
        old = layer_marks(cue, self.layer)
        edit, self._pending_edit = self._pending_edit, None
        def remap(body, marks):
            if edit is not None:
                before_raw, after_raw, position, removed, added = edit
                a,b,c = python_offset(before_raw,position),python_offset(before_raw,position+removed),python_offset(after_raw,position+added)
                if self.mode.currentIndex():
                    before_body, _, before_positions = parse_markdown(before_raw)
                    after_body, _, after_positions = parse_markdown(after_raw)
                    a,b,c = sum(i<a for i in before_positions),sum(i<b for i in before_positions),sum(i<c for i in after_positions)
                else:
                    before_body, after_body = before_raw, after_raw
                if before_body == previous and after_body == body:
                    return edit_marks(previous,body,marks,a,b,c)
            return remap_marks(previous,body,marks)
        if self.mode.currentIndex():
            body, parsed, _ = parse_markdown(raw)
            from ..caption_style.text_marks import unencoded_marks
            marks = remap(body,unencoded_marks(old)) + parsed
        else:
            body, marks = raw, remap(raw, old)
        if body == previous and normalize_marks(body, marks) == normalize_marks(body, old):
            return
        self.apply(body, marks)

    def apply(self, body, marks):
        binding = getattr(self.editor, 'binding', None)
        if self.layer == 'translation' and binding is not None:
            from ..subtitle_rules.subtitle_translation import container_target
            if self.page.project is not binding[0] or container_target(self.page.project) != binding[2]:
                self.page.save_state.setText(tr("译文语言或工程已切换，请重新选择字幕后编辑"))
                return
        from ..timeline.studio_commands import SetCueFieldsCommand
        cue = self.current()
        if cue is None: return
        marks = normalize_marks(body, marks)
        override = with_marks(cue, marks, self.layer)
        if self.layer == 'translation' and body != self.body(cue):
            override.pop('translation_group', None)
        if body == self.body(cue) and override == cue.appearance_override:
            return
        stack = self.page.session.undo_stack
        self.page._text_input_in_progress = True
        try:
            if self.layer == 'translation':
                stack.beginMacro('编辑译文与局部格式')
                try:
                    self.page.cue_controller.set_translation(cue.id, body)
                    if override != cue.appearance_override:
                        stack.push(SetCueFieldsCommand(self.page.project, cue.id, {'appearance_override': override},
                            '修改译文局部格式', self.page._changed))
                finally: stack.endMacro()
            else:
                changes = {}
                if body != cue.text: changes['text'] = body
                if override != cue.appearance_override: changes['appearance_override'] = override
                if changes:
                    if 'text' in changes:
                        self.page._manual_text_baselines.setdefault(cue.id,cue.text)
                    stack.push(SetCueFieldsCommand(self.page.project, cue.id, changes, '编辑字幕与局部格式',
                        lambda: self.page.cue_controller.cue_changed(cue.id, columns=(3, 4)),
                        learning_observer=self.page.cue_controller.observe_learnable_text))
                    if 'text' in changes:self.page._manual_learning_timer.start()
        finally:
            self.page._text_input_in_progress = False
        self.highlighter.marks = marks
        self.rehighlight()

    def format_selection(self, field):
        cue = self.current()
        if cue is None: return
        cursor = self.editor.textCursor()
        if not cursor.hasSelection(): return
        raw = self.editor.toPlainText()
        a, b = python_offset(raw, cursor.selectionStart()), python_offset(raw, cursor.selectionEnd())
        if self.mode.currentIndex():
            body, marks, positions = parse_markdown(raw)
            from ..caption_style.text_marks import unencoded_marks
            marks=remap_marks(self.body(cue),body,unencoded_marks(layer_marks(cue,self.layer)))+marks
            a, b = sum(p < a for p in positions), sum(p < b for p in positions)
        else:
            body, marks = raw, deepcopy(layer_marks(cue, self.layer))
        if a >= b: return
        if field == 'clear':
            marks = [part for m in marks for part in
                ([dict(m, end=min(a, m['end']))] if m['start'] < a else []) +
                ([dict(m, start=max(b, m['start']))] if m['end'] > b else [])]
            marks.append(dict(start=a, end=b, bold=False, italic=False, highlight=False))
        else:
            value = True
            if field == 'color':
                color = QColorDialog.getColor(QColor('#FFD166'), self, tr('局部文字颜色'))
                if not color.isValid(): return
                value = color.name()
            marks.append(dict(start=a, end=b, **{field:value}))
        self.apply(body, marks)
        self.hydrate(self.current(), body)
        shown=self.editor.toPlainText()
        if self.mode.currentIndex():
            _,_,positions=parse_markdown(shown)
            if a<len(positions) and b<=len(positions): a,b=positions[a],positions[b-1]+1
        from PySide6.QtGui import QTextCursor
        cursor=self.editor.textCursor();cursor.setPosition(utf16_offset(shown,a))
        cursor.setPosition(utf16_offset(shown,b),QTextCursor.KeepAnchor);self.editor.setTextCursor(cursor)


def hydrate_editor(editor, cue, text):
    tools = getattr(editor, '_caption_tools', None)
    if tools is not None:
        tools.hydrate(cue, text)
    elif editor.toPlainText() != text:
        editor.setPlainText(text)
