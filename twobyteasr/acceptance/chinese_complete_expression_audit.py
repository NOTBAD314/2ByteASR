"""Run the complete-expression checks in the ordinary application process."""
from __future__ import annotations

import json
import os
import sys
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    from scripts.verify_chinese_complete_expression import child

    def execute():
        code = 1
        try:
            code = child(output, window=window)
        except Exception:
            (output/'audit-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
            window.close()
        path = output/'result.json'
        result = json.loads(path.read_text('utf-8')) if path.is_file() else {}
        checks = result.get('checks', [])
        result.update(passed=code == 0 and bool(checks) and all(row['passed'] for row in checks),
            checks_passed=sum(row['passed'] for row in checks), executable=sys.executable,
            entry='frozen' if getattr(sys, 'frozen', False) else 'quick_start.main',
            pid=os.getpid(), identity=load_build_identity().to_dict())
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        QApplication.instance().exit(code)

    QTimer.singleShot(600, execute)
