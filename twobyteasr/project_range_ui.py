from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLineEdit, QLabel
from .project_range import (range_points, effective_range, validated_range, set_range,
                            clock_text, parse_clock)

from .i18n import bind_text, tr, current_language


class ProjectRangeBar(QWidget):
    changed = Signal()

    def __init__(self, project, position, seek, undo_stack=None, parent=None):
        super().__init__(parent)
        self.project_getter, self.position, self.seek, self.undo_stack = project, position, seek, undo_stack
        self._signature = None
        row = QHBoxLayout(self); row.setContentsMargins(8,0,8,2)
        self.fields = []
        for index, label in enumerate(('入点 I', '出点 O')):
            button = QPushButton(label); button.clicked.connect(lambda _=False,i=index:self.mark(i))
            row.addWidget(button)
            field = QLineEdit(); field.setMinimumWidth(110); field.setMaximumWidth(150)
            (bind_text(field, '工程开头', property='placeholderText') if index == 0 else bind_text(field, '工程结尾', property='placeholderText'))
            bind_text(field, '工程时间：时:分:秒.毫秒；留空采用工程边界', property='toolTip')
            field.editingFinished.connect(lambda i=index:self.edit(i))
            row.addWidget(field); self.fields.append(field)
            jump = QPushButton('跳到'); jump.setMinimumWidth(45)
            jump.clicked.connect(lambda _=False,i=index:self.jump(i)); row.addWidget(jump)
        self.status = QLabel(); self.status.setWordWrap(True); row.addWidget(self.status,1)
        clear = QPushButton('清除范围'); clear.clicked.connect(self.clear); row.addWidget(clear)
        self._timer = QTimer(self); self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh); self._timer.start()
        self.refresh()

    def apply(self, points):
        p = self.project_getter()
        if p is None: return
        set_range(p,*points,undo_stack=self.undo_stack)
        self._signature = None; self.refresh(); self.changed.emit()

    def mark(self,index):
        p = self.project_getter()
        if p is None:return
        points = list(range_points(p)); points[index] = int(self.position())
        self.apply(points)

    def edit(self,index):
        p = self.project_getter()
        if p is None:return
        try:
            points = list(range_points(p)); value = self.fields[index].text().strip()
            points[index] = parse_clock(value) if value else None
            self.apply(points)
        except ValueError as exc:self.status.setText(tr(str(exc)))

    def jump(self,index):
        p = self.project_getter()
        if p is not None:self.seek(effective_range(p)[index])

    def clear(self):self.apply((None,None))

    def refresh(self):
        p = self.project_getter()
        self.setEnabled(p is not None)
        if p is None:return
        points, effective = range_points(p),effective_range(p)
        signature = (id(p),points,effective,current_language())
        if signature == self._signature:return
        self._signature = signature
        for field, value in zip(self.fields,points):
            if not field.hasFocus():field.setText('' if value is None else clock_text(value))
        try:
            start,end = validated_range(p)
            bind_text(self.status, '时长 {duration} · 出点帧不包含', duration=clock_text(end-start))
        except ValueError as exc:self.status.setText(tr(str(exc)))
        self.changed.emit()
