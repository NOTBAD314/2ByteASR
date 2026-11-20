"""Pop up at once when a recognition task runs out of balance (2026-11-18).

User (2026-11-18): some users used up their MOSS / Qwen credits without noticing and only found out
when recognition failed. Neither platform lets an API Key read the remaining balance (MOSS answers
HTTP 402 ``insufficient_credits`` / ``billing_error``; DashScope answers ``Arrearage`` or a
free-tier-exhausted code, and its balance API needs an AccessKey), so the app cannot warn ahead.
What it can do is speak up the moment the provider says so, instead of leaving it in the report:
the first balance error of a run opens one window that names the service, links to the page where
the user tops up, and offers to stop the rest of the queue (it would fail the same way).

``QuotaWatch`` reads the run's console lines and failure events; it is reset for each run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from ..i18n import tr
# Loaded with the watch (the run's first log line), not when the alert has to appear: the window
# then opens in about 0.1-0.2 s instead of paying for these imports first.
from ..projects.save_changes_dialog import _Tile
from .candy_prompt import CandyPrompt

QUOTA_CATEGORIES = frozenset({'balance', 'insufficient_credits', 'quota_exhausted', 'free_tier_only'})

# Words providers (and our own explanations of them) use for "out of money". Deliberately no bare
# "402": a log line may say "402 条" or carry a timestamp.
_QUOTA_TEXT = re.compile(
    r'Arrearage|欠费|欠費|余额不足|餘額不足|积分不足|積分不足|额度不足|額度不足|免费额度已用完|免費額度已用完'
    r'|insufficient[ _-]?(?:balance|credits?|quota|funds)|billing_error|good standing'
    r'|HTTP\s*402|\b402\s+Payment|Payment Required', re.IGNORECASE)
_MOSS = re.compile(r'\bMOS[SI]\b|MOSI|mosi|moss[_-]', re.IGNORECASE)
_QWEN = re.compile(r'Arrearage|DashScope|千问|千問|Qwen|百炼|百煉|免费额度|免費額度|good standing', re.IGNORECASE)

MOSS_USAGE_PAGE = 'https://platform.mosi.cn/app/usage/'   # balance and top-up live in the console's 用量


@dataclass(frozen=True)
class QuotaProblem:
    service: str          # 'moss' | 'qwen' | 'ai'
    name: str             # what the user calls it
    detail: str           # the provider's own words, shortened
    link: str = ''        # where to top up, when known


def qwen_billing_page(api_url: str = '') -> str:
    """The billing page of the Qwen site the user set up (千问AI平台 / Qwen Cloud / 百炼)."""
    from urllib.parse import urlsplit
    from ..providers import dashscope_service as ds
    try:
        host = urlsplit(api_url).hostname or ''
    except ValueError:
        host = ''
    if ds.is_qwen_cloud_host(host):
        return ds.QWEN_CLOUD_BILLING
    if ds.is_qianwen_host(host):
        return ds.QIANWEN_BILLING
    return 'https://billing-cost.console.aliyun.com/' if host else ds.QIANWEN_BILLING


def detect(text: str, category: str = '', qwen_url: str = '') -> QuotaProblem | None:
    """A balance problem in one failure message / log line, or None."""
    text = str(text or '')
    category = str(category or '')
    if category not in QUOTA_CATEGORIES and not _QUOTA_TEXT.search(text):
        return None
    detail = ' '.join(text.split())
    detail = re.sub(r'^\[[^\]]{1,12}\]\s*[^：:]{0,120}[：:]\s*', '', detail)[:180]   # "[文件失败] a.mp4：" off
    if category == 'insufficient_credits' or _MOSS.search(text):
        return QuotaProblem('moss', 'MOSS Pro', detail, MOSS_USAGE_PAGE)
    if category in {'balance', 'free_tier_only'} or _QWEN.search(text):
        return QuotaProblem('qwen', '千问 / 百炼', detail, qwen_billing_page(qwen_url))
    return QuotaProblem('ai', 'AI 服务', detail)


class QuotaAlertDialog(CandyPrompt):
    """「余额不足」: what happened, 去充值, 停止任务, 知道了."""

    WIDTH = 500

    def __init__(self, parent, problem: QuotaProblem, *, can_stop: bool):
        super().__init__(parent, object_name='quotaAlertDialog', title=str(tr('余额不足')), icon='fa5s.wallet')
        self.problem = problem
        self.choice = 'ok'
        head = QHBoxLayout()
        head.setSpacing(12)
        mascot = self.bunny(66, 'sad')
        if mascot is not None:
            head.addWidget(mascot, 0, Qt.AlignmentFlag.AlignVCenter)
        words = QVBoxLayout()
        words.setSpacing(4)
        self.heading = self.label(str(tr('{name} 余额不足', name=tr(problem.name))), 'candyHeading', wrap=True)
        words.addWidget(self.heading)
        tail = (tr('后面的文件也会因为同样的原因失败。充值后重新开始就好，已经完成的结果会保留。')
                if can_stop else tr('充值后重新开始就好，已经完成的结果会保留。'))
        self.sub = self.label(str(tr('服务商拒绝了这次请求。')) + str(tail), 'candyMuted', wrap=True)
        words.addWidget(self.sub)
        if problem.detail:
            detail = self.label(str(tr('服务商的原话：{text}', text=problem.detail)), 'candyMuted', wrap=True)
            detail.setTextFormat(Qt.TextFormat.PlainText)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            detail.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            words.addWidget(detail)
        head.addLayout(words, 1)
        self.body.addLayout(head)
        self.body.addSpacing(8)
        # The save question's candies: accent = the way forward, soft red = stop, plain = back.
        from ..design.theme_manager import theme_definition, theme_key
        t = theme_definition(theme_key())
        row = QHBoxLayout()
        row.setSpacing(10)
        self.top_up_button = (_Tile('save', self.icon_label('fa5s.wallet', t.text_on_accent, 18), str(tr('去充值')),
                                    str(tr('打开用量与充值页'))) if problem.link else None)
        self.stop_button = (_Tile('drop', self.icon_label('fa5s.stop-circle', t.danger, 18), str(tr('停止任务')),
                                  str(tr('剩下的文件先不跑了'))) if can_stop else None)
        self.ok_button = _Tile('back', self.icon_label('fa5s.check', t.text_secondary, 18), str(tr('知道了')),
                               str(tr('先关掉这个窗口')))
        for button, value in ((self.top_up_button, 'top_up'), (self.stop_button, 'stop'), (self.ok_button, 'ok')):
            if button is not None:
                button.setObjectName('candyTile')
                button.clicked.connect(lambda _=False, v=value: self._choose(v))
                row.addWidget(button, 1)
        self.body.addLayout(row)
        self.ok_button.setDefault(True)
        self.ok_button.setFocus()
        self.finish_layout()

    def _choose(self, value: str):
        self.choice = value
        self.accept()

    def reject(self):                 # Esc or the round ✕
        self.choice = 'ok'
        super().reject()


class QuotaWatch:
    """One alert per run, from the first balance error seen in its log or failure events."""

    def __init__(self, window):
        self.window = window
        self.problem = None
        self.dialog = None

    def reset(self):
        from shiboken6 import isValid
        self.problem = None
        if self.dialog is not None and isValid(self.dialog):
            self.dialog.reject()

    def feed(self, text: str, category: str = '') -> QuotaProblem | None:
        if self.problem is not None:
            return None
        problem = detect(text, category, self._qwen_url())
        if problem is None:
            return None
        self.problem = problem
        QTimer.singleShot(0, self.window, lambda: self._show(problem))
        return problem

    def _qwen_url(self) -> str:
        try:
            return str(self.window.legacy.RUNTIME_SETTINGS.get('models', {}).get('qwen_asr_api_url') or '')
        except Exception:  # noqa: BLE001 - only picks which billing page to link
            return ''

    def _can_stop(self) -> bool:
        button = getattr(self.window, 'cancel_run_button', None)
        return bool(button is not None and button.isVisible() and button.isEnabled())

    def _show(self, problem: QuotaProblem):
        from shiboken6 import isValid
        if problem is not self.problem:
            return
        if self.dialog is not None and isValid(self.dialog) and self.dialog.isVisible():
            return
        dialog = QuotaAlertDialog(self.window, problem, can_stop=self._can_stop())
        self.dialog = dialog

        def done(_result):
            self.dialog = None
            if dialog.choice == 'top_up' and problem.link:
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl(problem.link))
            elif dialog.choice == 'stop' and problem is self.problem and self._can_stop():
                self.window.cancel_run_button.click()
            dialog.deleteLater()

        dialog.finished.connect(done)
        dialog.open()                      # the run keeps reporting while the window is up


__all__ = ['QUOTA_CATEGORIES', 'QuotaAlertDialog', 'QuotaProblem', 'QuotaWatch', 'detect', 'qwen_billing_page']
