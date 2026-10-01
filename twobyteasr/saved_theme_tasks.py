"""Discover completed local stages; a saved network request is never resumed implicitly."""
import json
from pathlib import Path
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QListWidget,QPushButton,QHBoxLayout,QFileDialog

from .i18n import bind_text

from .i18n import tr

def saved_tasks(root,limit=30):
    paths=sorted(Path(root).glob('*/creative/ledger.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    rows=[]
    for path in paths:
        try:
            data=json.loads(path.read_text('utf8'))
            if data.get('pipeline') not in {'authored-stages-1','authored-stages-2','authored-stages-3'}:continue
            concepts=data.get('partial_concepts',[])
            ready=sum(c.get('technical_status')!='failed' and bool(c.get('motion_preview')) for c in concepts)
            rows.append(dict(path=str(path),label=f"{data['raw_user_prompt'][:55]} · 已保存动画 {ready}/3 · {path.parent.parent.name[:8]}"))
            if len(rows)>=limit:break
        except (OSError,ValueError,KeyError):continue
    return rows

class SavedThemeTasksDialog(QDialog):
    def __init__(self,rows,parent=None):
        super().__init__(parent);self.path='';self.resume=False;self.rows=rows
        bind_text(self, '已保存的 AI 字幕设计', property='windowTitle');self.resize(690,400)
        layout=QVBoxLayout(self)
        description=QLabel('可查看已保存的版本和动画。上次未完成的远端请求已停止；点击继续才会发起新请求。')
        description.setWordWrap(True);layout.addWidget(description)
        self.items=QListWidget();self.items.addItems([r['label'] for r in rows]);layout.addWidget(self.items)
        if rows:self.items.setCurrentRow(0)
        actions=QHBoxLayout();layout.addLayout(actions)
        for label,resume in [('查看已保存成果',False),('继续未完成部分',True)]:
            button=QPushButton(label);button.setEnabled(bool(rows));actions.addWidget(button)
            button.clicked.connect(lambda checked=False,value=resume:self.choose(value))
        close=QPushButton('关闭');close.clicked.connect(self.reject);actions.addWidget(close)
        legacy=QPushButton('从其他草稿记录继续…');layout.addWidget(legacy)
        legacy.clicked.connect(self.open_record)
    def open_record(self):
        path,_=QFileDialog.getOpenFileName(self,tr('选择已保存的 AI 草稿记录'),'','AI 草稿 (ledger.json);;JSON (*.json)')
        if path:self.path=path;self.resume=True;self.accept()
    def choose(self,resume):
        index=self.items.currentRow()
        if index<0:return
        self.path=self.rows[index]['path'];self.resume=resume;self.accept()
