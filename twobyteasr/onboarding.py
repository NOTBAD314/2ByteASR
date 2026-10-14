"""Home "现在先做什么": the next step from the real state, not a tutorial (2026-10-13).

``compute_next_step`` turns cheap facts (media chosen, whether the saved plan
can run on this computer, which plans this computer can use) into four step
pills (选择影音 → 准备识别方式 → 生成字幕 → 校对导出), one short line with the
key words in the accent colour, and one main button (2026-10-14). The facts are gathered off the GUI thread
(``probe_facts``) after the home page is painted.

Who sees what:
* a fresh install (no projects, reports, models or saved keys when this
  version first ran) gets the welcome with three directions until they
  dismiss it or finish a first recognition;
* everyone else only sees the card when something is missing (no usable
  recognition plan for this computer) — never a forced tutorial;
* the help menu can always bring the guide back.

Plans are explained in plain words without "fastest/most accurate" claims,
and nothing switches to a paid cloud service unless the user clicks it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

STATE_KEY = 'onboarding/state'
STATE_VERSION = 1

# Plain-language descriptions of each plan (recognition_choices.plan_options keys).
PLAN_WORDS = {
    'cloud_only': ('云端识别', '不需要显卡或下载模型；需要网络和服务账号，音频会上传给服务商并按用量计费。'),
    'cloud_plus_align': ('云端识别 + 本机精细对齐', '文字由云端识别，字词时间在本机对齐（可用 CPU）；音频会上传给服务商。'),
    'windows_cuda': ('本机识别（NVIDIA 显卡）', '使用本机，不上传影音；需要 NVIDIA 显卡并下载模型。'),
    'apple_local': ('Mac 本机识别（Apple Silicon）', '使用本机，不上传影音；需要在模型工坊下载 MLX 模型。'),
    'apple_gpu_local': ('Mac 本机高质量（MOSS + FireRed）',
                        '使用本机 Apple 芯片 GPU，不上传影音；需要在模型工坊准备 MOSS 与 FireRed，建议 16 GB 以上内存。'),
    'cpu_local': ('本机识别（不需要显卡）', '使用本机，不上传影音；速度较慢，没有说话人区分。'),
}


@dataclass
class NextStep:
    key: str                     # '' hides the card
    title: str = ''
    message: str = ''
    actions: list = field(default_factory=list)   # [(label, action_id)]
    tone: str = 'info'           # info | warn | good
    dismissible: bool = False
    step: int = -1               # index into STEPS shown as the current pill; -1 hides the pills
    detail: str = ''             # the exact reason, shown on hover only


@dataclass
class Facts:
    host: object = None
    options: list = field(default_factory=list)
    plan_ready: bool = False
    plan_problem: str = ''
    cloud_ready: bool = False
    installed: frozenset = frozenset()


# ----------------------------------------------------------------- state

def _settings():
    from PySide6.QtCore import QSettings
    return QSettings('2ByteASR', '2ByteASR')


def load_state() -> dict:
    try:
        raw = _settings().value(STATE_KEY, '')
        value = json.loads(raw) if raw else {}
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        _settings().setValue(STATE_KEY, json.dumps(dict(state, version=STATE_VERSION)))
    except Exception:
        pass


def looks_like_existing_user() -> bool:
    """Evidence that someone already used 兔白 before this version ran."""
    try:
        from .studio_project import project_library_root, studio_settings_path
        try:
            payload = json.loads(studio_settings_path().read_text(encoding='utf-8'))
        except (OSError, ValueError):
            payload = {}
        if isinstance(payload, dict) and payload.get('recent_projects'):
            return True
        library = project_library_root()
        if library.is_dir() and any(library.glob('*/*.2byteproj')):
            return True
    except Exception:
        pass
    try:
        from .reporting import REPORT_ROOT
        if REPORT_ROOT.is_dir() and any(REPORT_ROOT.iterdir()):
            return True
    except Exception:
        pass
    try:
        from .llm_config import _read_secrets
        secrets = _read_secrets()
        if any(str(key).startswith(('API__', 'QWEN_ASR', 'POLISH_', 'GROUP_')) and value
               for key, value in dict(secrets or {}).items()):
            return True
    except Exception:
        pass
    return False


def ensure_state() -> dict:
    """Stamp once per data folder: was this a fresh install?"""
    state = load_state()
    if state.get('version') == STATE_VERSION and 'fresh' in state:
        return state
    fresh = not looks_like_existing_user()
    state = {'version': STATE_VERSION, 'fresh': fresh, 'guide': fresh, 'first_task_done': False}
    save_state(state)
    return state


def set_guide(on: bool) -> dict:
    state = ensure_state()
    state['guide'] = bool(on)
    save_state(state)
    return state


def mark_first_task_done() -> None:
    state = ensure_state()
    if not state.get('first_task_done'):
        state['first_task_done'] = True
        state['guide'] = False
        save_state(state)


# ----------------------------------------------------------------- facts

def probe_facts(settings: dict, install_root=None) -> Facts:
    """Hardware, installed models and cloud readiness; safe off the GUI thread."""
    from .recognition_choices import cloud_asr_readiness, host_profile, plan_options
    facts = Facts()
    try:
        from .model_workshop import installed_model_keys
        from .runtime_paths import detect_install_root
        facts.installed = frozenset(installed_model_keys(install_root or detect_install_root()))
    except Exception:
        facts.installed = frozenset()
    try:
        facts.host = host_profile()
    except Exception:
        facts.host = None
    models = (settings or {}).get('models', {}) or {}
    try:
        facts.cloud_ready, cloud_reason = cloud_asr_readiness(models)
    except Exception:
        facts.cloud_ready, cloud_reason = False, ''
    provider = str(models.get('qwen_asr_api_provider') or '')
    if facts.host is not None:
        try:
            facts.options = plan_options(settings, set(facts.installed), facts.host, {provider: facts.cloud_ready})
        except Exception:
            facts.options = []
    facts.plan_ready, facts.plan_problem = current_plan_status(models, facts, cloud_reason)
    return facts


REQUIRED_MODELS = {
    'moss': {'moss'}, 'firered': {'firered_aed'}, 'qwen_local': {'qwen_asr'}, 'firered_llm': {'firered_llm'},
    'sensevoice': {'sensevoice'}, 'paraformer': {'paraformer'}, 'whisper_turbo': {'whisper_turbo'},
    'mlx_qwen3_asr': {'mlx_qwen3_asr_0_6b'}, 'mlx_qwen3_asr_1_7b': {'mlx_qwen3_asr_1_7b'},
}
CUDA_PRIMARY = {'moss', 'firered', 'qwen_local', 'firered_llm'}


def current_plan_status(models: dict, facts: Facts, cloud_reason: str = '') -> tuple[bool, str]:
    """Can the saved primary recognizer run here, and if not, why (plain words)."""
    primary = str(models.get('primary_asr_backend') or 'moss')
    host = facts.host
    if primary == 'api':
        return (True, '') if facts.cloud_ready else (False, cloud_reason or '还没有设置云端识别服务。')
    if primary in CUDA_PRIMARY and host is not None and not host.cuda_possible:
        # MOSS / FireRed run on the Apple GPU of an Apple Silicon Mac (2026-10-14).
        from .recognition_choices import unavailable_on_host
        limit = unavailable_on_host('primary', primary, host)
        if limit == '只能在 Apple Silicon Mac 上运行':
            return False, '当前方案只能在 Apple 芯片 Mac 上运行。'
        if limit:
            return False, '当前方案需要 NVIDIA 显卡，这台电脑没有检测到。'
    if primary.startswith('mlx') and host is not None and not host.apple_silicon:
        return False, 'MLX 本机识别只能在 Apple Silicon Mac 上运行。'
    needed = REQUIRED_MODELS.get(primary, set())
    if needed and not needed <= set(facts.installed):
        return False, '当前方案的本机模型还没有下载。'
    return True, ''


# ----------------------------------------------------------------- next step

# The four things a first subtitle takes; the card highlights where you are.
STEPS = ('选择影音', '准备识别方式', '生成字幕', '校对导出')


def compute_next_step(*, media_count: int, facts: Facts | None, state: dict, running: bool = False) -> NextStep:
    """One short line and one main button for where the user is now (2026-10-14)."""
    if running:
        return NextStep('')
    guide = bool(state.get('guide'))
    if media_count == 0:
        if not guide:
            return NextStep('')  # nothing to run yet; someone who closed the guide is not followed
        return NextStep('welcome', '跟着这几步做', '把视频或音频**拖进来**，或点“选择影音”',
                        [('选择影音', 'choose_media'), ('带我看一遍', 'tour'), ('看看范例', 'open_sample')],
                        'info', True, step=0)
    if facts is None:
        return NextStep('')  # still checking in the background; never block the page
    if not facts.plan_ready:
        from .i18n import tr
        actions = [('选择识别方式', 'choose_plan')]
        usable = [o for o in facts.options if o.available]
        if usable:
            title = PLAN_WORDS.get(usable[0].key, (usable[0].title,))[0]
            actions.append((str(tr('改用“{title}”', title=tr(title))), 'use_plan:' + usable[0].key))
        return NextStep('plan', '还差一步', '先**选择识别方式**：本机免费，云端快速', actions, 'warn', guide,
                        step=1, detail=facts.plan_problem)
    if guide:
        return NextStep('ready', '都准备好了', '点右下角的**开始生成字幕**', [], 'good', True, step=2)
    return NextStep('')


def _hardware_blocked(option, host) -> bool:
    if host is None:
        return False
    if option.key == 'windows_cuda':
        return not host.cuda_possible
    if option.key in {'apple_local', 'apple_gpu_local'}:
        return not host.apple_silicon
    return False


def plan_patch(option_key: str, facts: Facts) -> dict:
    option = next((o for o in facts.options if o.key == option_key), None)
    return dict(option.patch) if option is not None else {}


def emphasis_html(text: str, color: str) -> str:
    """Plain text with **marked** words shown in the accent colour (everything else escaped)."""
    import html
    parts = str(text).split('**')
    out = []
    for index, part in enumerate(parts):
        safe = html.escape(part)
        out.append(f'<span style="color:{color}; font-weight:700;">{safe}</span>' if index % 2 else safe)
    return ''.join(out)


# ----------------------------------------------------------------- widget

def build_card(parent=None):
    """The home card: four small step pills, one line, one main button."""
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout
    from .design.presentation import button_role
    from .i18n import bind_text, tr

    class NextStepCard(QFrame):
        action_requested = Signal(str)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName('nextStepCard')
            self.setProperty('tone', 'info')
            self._theme_key = None
            self._accent = '#b34470'
            outer = QVBoxLayout(self)
            outer.setContentsMargins(18, 12, 12, 14)
            outer.setSpacing(10)
            top = QHBoxLayout()
            top.setSpacing(6)
            self.pills, self.lines = [], []
            for index, _name in enumerate(STEPS):
                if index:
                    line = QFrame()
                    line.setObjectName('nextStepLine')
                    line.setFixedSize(18, 2)
                    top.addWidget(line, 0, Qt.AlignmentFlag.AlignVCenter)
                    self.lines.append(line)
                pill = QLabel()
                pill.setObjectName('nextStepPill')
                top.addWidget(pill)
                self.pills.append(pill)
            top.addStretch(1)
            self.close_button = QToolButton()
            self.close_button.setObjectName('nextStepClose')
            self.close_button.setText('×')
            self.close_button.setAutoRaise(True)
            bind_text(self.close_button, '不再显示（可在“说明”里重新打开）', property='toolTip')
            self.close_button.clicked.connect(lambda: self.action_requested.emit('dismiss'))
            top.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
            outer.addLayout(top)
            bottom = QHBoxLayout()
            bottom.setSpacing(8)
            self.message = QLabel()
            self.message.setObjectName('nextStepMessage')
            self.message.setTextFormat(Qt.TextFormat.RichText)
            self.message.setWordWrap(True)
            bottom.addWidget(self.message, 1)
            self.buttons = QHBoxLayout()
            self.buttons.setSpacing(8)
            bottom.addLayout(self.buttons)
            outer.addLayout(bottom)
            # Old attribute kept for callers that read the title text.
            self.title = self.message
            self.step = NextStep('')
            self.hide()

        def _apply_theme(self):
            from .theme_manager import theme_key
            from .ui_theme import theme_definition
            key = theme_key()
            if key != self._theme_key:
                theme = theme_definition(key)
                self._theme_key, self._accent = key, theme.accent
                self.setStyleSheet(card_qss(theme))

        def show_step(self, step: NextStep):
            self.step = step
            if not step.key:
                self.hide()
                return
            self._apply_theme()
            self.setProperty('tone', step.tone)
            for index, pill in enumerate(self.pills):
                state = 'done' if index < step.step else 'current' if index == step.step else 'todo'
                mark = '✓' if state == 'done' else str(index + 1)
                pill.setText(f'{mark}  {tr(STEPS[index])}')
                pill.setProperty('state', state)
                pill.style().unpolish(pill)
                pill.style().polish(pill)
                pill.setVisible(step.step >= 0)
            for line in self.lines:
                line.setVisible(step.step >= 0)
            title = emphasis_html(str(tr(step.title)), self._accent) if step.title else ''
            body = emphasis_html(str(tr(step.message)), self._accent)
            self.message.setText(f'<b>{title}</b>&nbsp;&nbsp;&nbsp;{body}' if title else body)
            self.setToolTip(str(tr(step.detail)) if step.detail else '')
            while self.buttons.count():
                item = self.buttons.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
            for index, (label, action_id) in enumerate(step.actions):
                role = 'primary' if index == 0 else 'secondary' if index == 1 else 'ghost'
                button = button_role(QPushButton(tr(label)), role)
                button.setObjectName('nextStepAction_' + action_id.split(':', 1)[0])
                button.setProperty('actionId', action_id)
                button.clicked.connect(lambda _=False, value=action_id: self.action_requested.emit(value))
                self.buttons.addWidget(button)
            self.close_button.setVisible(step.dismissible)
            self.style().unpolish(self)
            self.style().polish(self)
            self.show()

    return NextStepCard(parent)


CARD_QSS = """
QFrame#nextStepCard { border-radius: 16px; border: 1px solid %(border)s; background: %(surface)s; }
QFrame#nextStepCard[tone="warn"] { border-color: %(warning)s; }
QFrame#nextStepCard[tone="good"] { border-color: %(success)s; }
QLabel#nextStepMessage { color: %(text)s; font-size: 15px; }
QLabel#nextStepPill { border-radius: 11px; padding: 3px 11px; font-size: 12px; font-weight: 600;
                      color: %(muted)s; border: 1px solid %(border)s; background: transparent; }
QLabel#nextStepPill[state="current"] { color: %(on_accent)s; background: %(accent)s; border-color: %(accent)s; }
QLabel#nextStepPill[state="done"] { color: %(success)s; border-color: %(success)s; }
QFrame#nextStepLine { background: %(border)s; border: 0; }
QToolButton#nextStepClose { color: %(muted)s; border: 0; padding: 2px 6px; font-size: 15px; }
QToolButton#nextStepClose:hover { color: %(text)s; }
"""


def card_qss(theme) -> str:
    def pick(*names, default='#888888'):
        for name in names:
            value = getattr(theme, name, None)
            if value:
                return value
        return default
    return CARD_QSS % {
        'border': pick('border', 'outline', 'divider'),
        'surface': pick('surface_elevated', 'surface', 'panel'),
        'warning': pick('warning'),
        'success': pick('success'),
        'muted': pick('text_muted', 'muted'),
        'text': pick('text'),
        'accent': pick('accent'),
        'on_accent': pick('text_on_accent', default='#ffffff'),
    }
