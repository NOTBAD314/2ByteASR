"""Real-window check: a downloaded Apple Silicon model reads 已就绪 on the home card (2026-10-28).

Mac user: Qwen3 对齐（Apple Silicon）was downloaded, yet the timeline card said
需要下载 and the start bar 「开始前还需处理：字幕时间轴」. The card's own list
of the files each choice needs had no MLX choices.

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=home-mlx-readiness`` (isolated
data; ``scripts/verify_home_mlx_readiness_headed.py``). On Windows the Mac is
simulated inside the real app: an Apple Silicon host profile, the user's plan
(FireRed on the Apple GPU, Qwen3 对齐 MLX, SenseVoice) and those models
installed. The cards and the start bar are then painted by the real code.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

PLAN = ('firered', 'mlx_qwen_aligner', 'sensevoice')
INSTALLED = frozenset({'firered_aed', 'mlx_qwen_aligner', 'sensevoice'})


def start(window, output: Path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog
    app = QApplication.instance()
    output.mkdir(parents=True, exist_ok=True)
    result = dict(checks=[], records=[], errors=[], passed=False, pid=os.getpid(),
                  executable=os.path.realpath(sys.executable))

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))

    def settle(ms=300):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def grab(widget, name):
        try:
            widget.grab().save(str(output / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'grab {name}: {exc!r}')

    def cards():
        return {role: dict(name=card.model_label.text(), status=card.status_badge.text(),
                           recovery=None if card.recovery.isHidden() else card.recovery.text())
                for role, card in window.recognition_plan.cards.items()}

    def run_all():
        try:
            from ..app import ui
            from ..design.theme_manager import apply_theme
            from ..recognition.recognition_choices import HostProfile
            apply_theme(os.environ.get('TWOBYTEASR_HOME_AI_THEME', 'grape'), app)
            for dialog in [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]:
                QDialog.done(dialog, 0)
            window.showNormal()
            if window.pages.currentWidget() is not window.__dict__.get('settings_scroll'):
                window._return_to_settings()   # a startup project may have opened Studio
            area = window.screen().availableGeometry()
            window.resize(min(1500, area.width()), min(980, area.height()))
            window.move(area.topLeft())
            settle(1500)
            ui.installed_model_keys = lambda _root: set(INSTALLED)
            window._home_host_profile = HostProfile('darwin', 'arm64', nvidia_tool=False, main_runtime=True,
                                                    mlx_runtime=True)
            window._shown_asr_backends = lambda: PLAN
            options = window._subtitle_language_options
            for spoken in ('zh', 'ja'):
                window._subtitle_language_options = lambda spoken=spoken: dict(options(), recognition_language=spoken)
                window._refresh_asr_summary()
                settle(800)
                shown = cards()
                bar = window.action_status.text()
                result['records'].append(dict(spoken=spoken, cards=shown, start_bar=bar))
                grab(window.recognition_plan, f'cards_{spoken}')
                grab(window, f'home_{spoken}')
                check(f'{spoken}: timeline card says 已就绪', '已就绪' in shown['timeline']['status'], shown['timeline'])
                check(f'{spoken}: no 安装模型 on the timeline card', shown['timeline']['recovery'] is None,
                      shown['timeline'])
                check(f'{spoken}: every card is ready', all('已就绪' in c['status'] for c in shown.values()), shown)
                check(f'{spoken}: the start bar has nothing left to do', '开始前还需处理' not in bar, bar)
            check('timeline card names the aligner, not its key',
                  'mlx_qwen_aligner' not in result['records'][0]['cards']['timeline']['name'],
                  result['records'][0]['cards']['timeline'])
        except Exception:  # noqa: BLE001
            result['errors'].append(traceback.format_exc())
        result['passed'] = bool(result['checks']) and all(c['passed'] for c in result['checks']) and not result['errors']
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
        window.close()
        QTimer.singleShot(500, app.quit)

    def shutdown():
        result['gui_shutdown'] = True
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(2500, run_all)
