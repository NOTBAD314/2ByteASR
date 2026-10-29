"""Production Qt rendering of an immutable real-request diagnostic receipt.

run_cli_ui_checks is called by the isolated normal-entry audit. This replays
the separately measured HTTP 426; it does not claim another live request.
The update confirmation is exercised and cancelled, with no updater call.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QVBoxLayout

from twobyteasr.app import ui
from twobyteasr.providers import endpoint_editor_ui
from twobyteasr.providers.provider_diagnostics import redact_diagnostics
from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY


def run_cli_ui_checks(owner, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / 'cli-real-receipt.json'
    if not receipt_path.is_file():
        source = Path(__file__).resolve().parents[1] / 'tmp' / 'cli-real-receipt.json'
        receipt_path.write_text(source.read_text(encoding='utf8'), encoding='utf8')
    receipt = json.loads(receipt_path.read_text(encoding='utf8'))
    diagnostics = copy.deepcopy(receipt['diagnostics'])
    checks = {}
    screenshots = []
    old_settings = GLOBAL_PROVIDER_REGISTRY.settings()
    settings = {'models': {'ai_service': 'grok_account', 'polish_model': 'grok-4.7'},
                'switches': {'unified_glm_processing': True}}
    dialog = QDialog(owner)
    dialog.setWindowTitle('CLI 状态验收 · 真实 426 回执重放（不新增请求）')
    layout = QVBoxLayout(dialog)
    editor = ui.EndpointEditor('统一校对与断句模型', ui.CORAL, 'polish', settings)
    layout.addWidget(editor)
    dialog.resize(1050, 900)
    try:
        editor.account_status.setText('Grok Account：已登录/连接正常')
        editor._tester = SimpleNamespace(diagnostics=diagnostics)
        editor._connection_finished(False, receipt['message'])
        dialog.show()
        QApplication.processEvents()
        checks['real_receipt_failed_upgrade'] = receipt['category'] == 'upgrade_required' and receipt['request_succeeded'] is False
        checks['exact_executable_visible'] = diagnostics['executable'] in editor.cli_status.text()
        checks['version_visible'] = diagnostics['cli_version'] in editor.cli_status.text()
        checks['previous_ready_cleared'] = '连接正常' not in editor.account_status.text()
        checks['credentials_and_request_separate'] = '登录/凭据：' in editor.account_status.text() and '请求：' in editor.account_status.text()
        checks['server_minimum_visible'] = diagnostics['failure']['minimum_version'] in editor.status.text()
        checks['last_test_time_visible'] = diagnostics['last_tested_at'] in editor.account_status.text()
        checks['update_action_visible'] = editor.update_cli_button.isVisible()
        checks['plain_test_not_capability_proof'] = (not editor.json_mode.isEnabled() and not editor.json_mode.isChecked()
            and not editor.structured_output.isEnabled() and '本地校验' in editor.structured_output.text()
            and not editor.stream_output.isEnabled() and not editor.stream_output.isChecked())
        path = output / 'cli-diagnostics-collapsed.png'
        dialog.grab().save(str(path))
        screenshots.append(str(path))
        editor.diagnostics_toggle.click()
        QApplication.processEvents()
        checks['details_expand'] = editor.diagnostics_details.isVisible()
        checks['details_same_receipt'] = diagnostics['failure']['minimum_version'] in editor.diagnostics_details.toPlainText()
        checks['details_redacted'] = editor.diagnostics_details.toPlainText() == json.dumps(redact_diagnostics(diagnostics), ensure_ascii=False, indent=2)
        path = output / 'cli-diagnostics-expanded.png'
        dialog.grab().save(str(path))
        screenshots.append(str(path))

        # Feed the already-inspected native self-update plan into the real UI.
        # The modal is rendered and cancelled. No filesystem/network adapter
        # operation is called during this UI replay.
        target = diagnostics['executable']
        plan = {'executable': target, 'version': diagnostics['cli_version'],
                'supported': True, 'command': [target, 'update'],
                'message': '使用这份官方 CLI 的自更新命令；保留现有登录凭据。'}
        original_provider = endpoint_editor_ui.provider_for_stage
        original_question = ui.QMessageBox.question
        class PreviewOnly:
            def cli_update_plan(self):
                return copy.deepcopy(plan)
        def question(parent, title, text, buttons, default):
            box = QMessageBox(QMessageBox.Icon.Question, title, text, buttons, parent)
            box.setDefaultButton(default)
            def capture_and_cancel():
                checks['update_confirm_exact_target'] = target in box.text() and 'update' in box.text()
                checks['update_confirm_minimal_retest'] = '最小普通文本请求' in box.text()
                path = output / 'cli-update-confirmation-cancelled.png'
                box.grab().save(str(path))
                screenshots.append(str(path))
                box.done(int(QMessageBox.StandardButton.Cancel))
            QTimer.singleShot(120, capture_and_cancel)
            return box.exec()
        try:
            endpoint_editor_ui.provider_for_stage = lambda *_a, **_k: PreviewOnly()
            ui.QMessageBox.question = question
            editor.start_cli_update()
            checks['update_cancel_no_worker'] = getattr(editor, '_update_worker', None) is None
        finally:
            endpoint_editor_ui.provider_for_stage = original_provider
            ui.QMessageBox.question = original_question
    finally:
        dialog.close()
        dialog.deleteLater()
        GLOBAL_PROVIDER_REGISTRY.bind(old_settings)
        QApplication.processEvents()
    result = {'checks': checks, 'screenshots': screenshots, 'passed': all(checks.values()),
              'evidence': 'actual server receipt replay; update confirmation cancelled; no new live request'}
    (output / 'cli-ui-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    return result
