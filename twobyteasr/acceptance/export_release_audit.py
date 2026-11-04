"""Run the export clock matrix through the normal frozen application entry."""
import json
import sys
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import launch_identity_payload
    def run():
        result = {}
        try:
            from .export_clock_audit import run as audit
            code = audit(output)
            result = json.loads((output/'result.json').read_text('utf8'))
            result['passed'] = bool(result.get('passed') and code == 0)
        except Exception:
            result.update(passed=False, error=traceback.format_exc())
        finally:
            result.update(build=launch_identity_payload(), frozen=bool(getattr(sys, 'frozen', False)))
            window.close()
            result['gui_shutdown'] = True
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
            QTimer.singleShot(300, QApplication.instance().quit)
    QTimer.singleShot(1500, run)
