"""An explicit user decision owned by one project-loading request.

2026-11-15 (user's pick A from the drafts, 「两张卡片」): when 设置 says to ask, the question is a
candy window with the two versions side by side as cards — click one to open it. The newer
autosave is the tinted card marked 「较新」. Times say 今天 / 昨天 / the date, so 00:43 beside
22:27 no longer reads backwards. 「删除恢复点」 is a small link in the corner, and 「以后直接打开
自动恢复」 puts the default back. Esc or ✕ cancels the opening.

The old message box's surface stays for callers and audits: ``choice``, ``buttons()`` with the
``recovery_recover`` / ``recovery_ignore`` / ``recovery_saved`` object names, ``informativeText()``.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QPushButton, QVBoxLayout

from ..app.candy_prompt import CandyPrompt
from ..i18n import tr


class RecoveryCancelled(Exception):
    pass


@dataclass
class RecoveryChoice:
    candidate: Path
    official_path: Path
    error: str = ''
    choice: str = 'cancel'


def saved_at(path, today: date | None = None) -> tuple[str, str]:
    """(``'22:27'``, ``'今天'`` / ``'昨天'`` / ``'11月14日'``) for a file's last change; ``--:--`` when unreadable."""
    try:
        moment = datetime.fromtimestamp(Path(path).stat().st_mtime)
    except (OSError, TypeError, ValueError):
        return '--:--', ''
    today = today or date.today()
    if moment.date() == today:
        day = str(tr('今天'))
    elif moment.date() == today - timedelta(days=1):
        day = str(tr('昨天'))
    else:
        day = str(tr('{month}月{day}日', month=moment.month, day=moment.day))
    return moment.strftime('%H:%M'), day


class _VersionCard(QPushButton):
    def __init__(self, kind: str, icon_label, time_text: str, day: str, note: str, newer: bool):
        super().__init__()
        self.setObjectName('recoveryCard')
        self.setProperty('card', True)
        self.setProperty('newer', newer)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        from ..app.ui_zoom import px
        self.setMinimumHeight(px(140))
        column = QVBoxLayout(self)
        column.setContentsMargins(18, 14, 18, 14)
        column.setSpacing(3)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(icon_label)
        head.addWidget(CandyPrompt.label(kind, 'recoveryKind'))
        head.addStretch(1)
        column.addLayout(head)
        column.addWidget(CandyPrompt.label(time_text, 'recoveryTime'))
        column.addWidget(CandyPrompt.label(' · '.join(part for part in (day, note) if part), 'recoveryDay', wrap=True))
        column.addStretch(1)
        column.addWidget(CandyPrompt.label(str(tr('打开这份 →')), 'recoveryGo'))
        self.setAccessibleName(f'{kind} {day} {time_text}')
        self.ribbon = None
        if newer:
            self.ribbon = CandyPrompt.label(str(tr('较新')), 'recoveryRibbon')
            self.ribbon.setParent(self)

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if self.ribbon is not None:
            self.ribbon.adjustSize()
            self.ribbon.move(self.width() - self.ribbon.width() - 14, 10)
            self.ribbon.raise_()


class RecoveryDialog(CandyPrompt):
    WIDTH = 580

    def __init__(self, page, request):
        super().__init__(page, object_name='projectRecoveryChoice', title=str(tr('发现未保存的自动恢复版本')),
                         icon='fa5s.history')
        from ..design.theme_manager import theme_definition, theme_key
        t = theme_definition(theme_key())
        self.choice = 'cancel'
        top = QHBoxLayout()
        top.setSpacing(12)
        mascot = self.bunny(70, 'happy')
        if mascot is not None:
            top.addWidget(mascot, 0, Qt.AlignmentFlag.AlignBottom)
        words = QVBoxLayout()
        words.setSpacing(4)
        words.addStretch(1)
        words.addWidget(self.label(str(tr('上次有修改没正式保存')), 'candyHeading', wrap=True))
        self._message = str(tr('自动恢复里有正式保存之后的修改。要打开哪一份？'))
        words.addWidget(self.label(self._message, 'candySub', wrap=True))
        top.addLayout(words, 1)
        self.body.addLayout(top)
        self._error = ''
        if request.error:
            self._error = str(tr('上次操作失败：{reason}。可以重试或取消打开。', reason=request.error[:200]))
            self.body.addWidget(self.label(self._error, 'candyError', wrap=True))
        self.body.addSpacing(8)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        auto_time, auto_day = saved_at(request.candidate)
        saved_time, saved_day = saved_at(request.official_path)
        self.recover_button = _VersionCard(str(tr('自动恢复')), self.icon_label('fa5s.history', t.accent_text, 14),
                                           auto_time, auto_day, str(tr('多了正式保存之后的修改')), True)
        self.saved_button = _VersionCard(str(tr('正式保存')), self.icon_label('fa5s.save', t.text_muted, 14),
                                         saved_time, saved_day, '', False)
        cards.addWidget(self.recover_button, 23)
        cards.addWidget(self.saved_button, 20)
        self.body.addLayout(cards)
        self.body.addSpacing(6)
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.always = QCheckBox(str(tr('以后直接打开自动恢复（设置里能改回来）')))
        self.always.setObjectName('recoveryAlways')
        self.always.setCursor(Qt.CursorShape.PointingHandCursor)
        foot.addWidget(self.always)
        foot.addStretch(1)
        self.delete_button = QPushButton(str(tr('删除恢复点')))
        self.delete_button.setObjectName('recoveryDelete')
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.setToolTip(str(tr('删掉这份自动恢复，打开正式保存')))
        foot.addWidget(self.delete_button)
        self.body.addLayout(foot)
        self._choices = {}
        for button, value in ((self.recover_button, 'recover'), (self.delete_button, 'ignore'),
                              (self.saved_button, 'saved')):
            button.setProperty('recoveryRole', value)
            self._choices[button] = value
            button.clicked.connect(lambda _=False, b=button: self._clicked(b))
        # The old object names (audits find the buttons by them).
        self.recover_button.setObjectName('recovery_recover')
        self.saved_button.setObjectName('recovery_saved')
        self.delete_button.setObjectName('recovery_ignore')
        self.recover_button.setDefault(True)
        self.recover_button.setFocus()
        self._trace = getattr(page, '_studio_trace', lambda *args, **kw: None)
        self._lease = getattr(getattr(getattr(page, '_readiness', None), 'loading', None), '_input_lease', None)
        if self._lease is not None:
            self._lease.allow_dialog(self)
        self.finished.connect(self._finished)
        self.finish_layout()

    # The message box's surface, for callers and audits.
    def buttons(self):
        return list(self._choices)

    def informativeText(self) -> str:  # noqa: N802 - kept from QMessageBox
        return '\n\n'.join(part for part in (self._message, self._error) if part)

    def _clicked(self, button):
        self.choice = self._choices.get(button, 'cancel')
        self._trace('RECOVERY_BUTTON_CLICK', choice=self.choice)
        if self.always.isChecked():
            from ..app.application_settings import save_recovery_policy
            try:
                save_recovery_policy('auto')
                self._trace('RECOVERY_POLICY_SAVED', policy='auto')
            except OSError as exc:
                self._trace('RECOVERY_POLICY_SAVE_FAILED', error=str(exc))
        self.accept()

    def _finished(self, result):
        if self._lease is not None:
            self._lease.release_dialog(self)
        self._trace('RECOVERY_CHOICE_SUBMITTED', choice=self.choice, dialog_result=result)

    def showEvent(self, event):
        super().showEvent(event)
        self._trace('RECOVERY_DIALOG_SHOWN', enabled=self.isEnabled())

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._trace('RECOVERY_DIALOG_FOCUS')

    def reject(self):                   # Esc or ✕: the opening is cancelled
        self.choice = 'cancel'
        super().reject()

    def closeEvent(self, event):
        self.reject()
        event.accept()
