"""Opening acceptance (2026-10-21): does a large project open, and how long does each stage take?

User report: opening a project often stops at 「建立时间轴失败 / 准备超时；请检查素材和播放器状态」.
The readiness gate fails when 30 s have passed since the open began. This opens each
listed project in the real window (fresh copy each time, no autosave to recover), waits
until the gate is ready or failed, and records the gate profile, the time of every
open step (each next() of _open_project_steps runs on the GUI thread) and memory.
Projects: TWOBYTEASR_OPEN_PROJECTS="label=path;label=path", repeated TWOBYTEASR_OPEN_REPEATS times.
TWOBYTEASR_OPEN_RECOVERY_WAITS="2,40": with a newer autosave, the recovery prompt stays up that
long before 「打开正式保存」. Passed = every open and every recovery case reached ready.
Run through scripts/verify_editor_diagnostics_headed.py --open-timing LABEL=PROJECT [--recovery-waits].
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        try:
            code = run(Path(output), window=window)
        except Exception:
            (Path(output) / 'result.json').write_text(json.dumps(dict(passed=False, error=traceback.format_exc())), 'utf8')
            code = 1
        window.result_exit_code = code

        def stopped():
            path = Path(output) / 'result.json'
            result = json.loads(path.read_text('utf8'))
            result['gui_shutdown'] = True
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(100, execute)


def run(output, *, window):
    from PySide6.QtTest import QTest
    import psutil
    from ..diagnostics.build_identity import load_build_identity
    from ..projects import studio_project_controller

    plan = [item.split('=', 1) for item in os.environ['TWOBYTEASR_OPEN_PROJECTS'].split(';') if item]
    repeats = int(os.environ.get('TWOBYTEASR_OPEN_REPEATS', '2'))
    page = window.studio_page
    window.resize(1440, 900)
    window.show()
    boxes = []
    studio_project_controller.studio_message_box = lambda *args, **kwargs: boxes.append([str(a) for a in args[1:]])
    controller = page.project_controller
    original_steps = type(controller)._open_project_steps
    steps_log = []

    def timed_steps(self, *args, **kwargs):
        generator = original_steps(self, *args, **kwargs)
        previous = '(start)'
        while True:
            began = time.perf_counter()
            try:
                stage = next(generator)
            except StopIteration:
                steps_log.append(dict(after=previous, ms=round((time.perf_counter() - began) * 1000, 1)))
                return
            steps_log.append(dict(after=previous, ms=round((time.perf_counter() - began) * 1000, 1)))
            previous = str(stage)
            yield stage

    type(controller)._open_project_steps = timed_steps  # the controller has __slots__
    result = dict(passed=False, pid=os.getpid(), identity=load_build_identity().to_dict(), opens=[])

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    projects = output / 'projects'
    projects.mkdir(exist_ok=True)
    process = psutil.Process()
    QTest.qWait(1500)
    for repeat in range(repeats):
        for label, source in plan:
            target = projects / f'{label}-{repeat}.2byteproj'
            shutil.copyfile(source, target)
            steps_log.clear()
            boxes.clear()
            rss_before = process.memory_info().rss / 1024 ** 2
            began = time.perf_counter()
            window.open_studio_project(str(target), mode='edit', source='studio_recognition')
            readiness = page._readiness
            deadline = time.monotonic() + 120
            QTest.qWait(50)
            while readiness.active and time.monotonic() < deadline:
                QTest.qWait(20)
            profile = copy.deepcopy(getattr(readiness, 'profile', {}))
            gaps = sorted(profile.pop('gui_gaps_ms', []) or [], reverse=True)
            entry = dict(label=label, repeat=repeat, file_mb=round(Path(source).stat().st_size / 1024 ** 2, 2),
                         ready=bool(readiness.ready), still_active=bool(readiness.active),
                         wall_ms=round((time.perf_counter() - began) * 1000, 1),
                         error=profile.get('error'), stages_ms=profile.get('stages_ms'),
                         total_ms=profile.get('total_ms'), open_phases=profile.get('open_phases'),
                         stalled_s=profile.get('stalled_s'), user_wait_ms=profile.get('user_wait_ms'),
                         gui_gaps_top_ms=gaps[:6], steps=list(steps_log), message_boxes=list(boxes),
                         styles=len(page.project.styles) if page.project is not None else None,
                         rss_mb=[round(rss_before, 1), round(process.memory_info().rss / 1024 ** 2, 1)],
                         label_text=readiness.label.text())
            result['opens'].append(entry)
            save()
            if readiness.active:
                readiness.cancel()
            QTest.qWait(1500)
    # Recovery prompt: a newer autosave exists; the prompt stays up `wait` seconds,
    # then 「打开正式保存」 is pressed. Does the prompt's time count against 30 s?
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    from ..projects.studio_project import load_project, save_autosave
    result['recovery'] = []
    waits = [float(x) for x in os.environ.get('TWOBYTEASR_OPEN_RECOVERY_WAITS', '').split(',') if x]
    for index, wait_s in enumerate(waits):
        label, source = plan[0]
        target = projects / f'recovery-{index}.2byteproj'
        shutil.copyfile(source, target)
        changed = load_project(target)
        changed.cues[0].text = changed.cues[0].text + ' (autosave)'
        candidate = save_autosave(changed, target)
        stamp = target.stat().st_mtime + 5
        os.utime(candidate, (stamp, stamp))
        seen = {}

        def poll():
            box = QApplication.activeModalWidget()
            if isinstance(box, QMessageBox) and 'shown' not in seen:
                seen['shown'] = round((time.perf_counter() - began) * 1000, 1)
                seen['title'] = box.windowTitle()

                def press(box=box):
                    for button in box.buttons():
                        if '打开正式保存' in button.text():
                            seen['pressed'] = round((time.perf_counter() - began) * 1000, 1)
                            button.click()
                            return
                QTimer.singleShot(int(wait_s * 1000), press)
            if 'pressed' not in seen:
                QTimer.singleShot(100, poll)

        steps_log.clear()
        began = time.perf_counter()
        QTimer.singleShot(100, poll)
        window.open_studio_project(str(target), mode='edit', source='studio_recognition')
        readiness = page._readiness
        deadline = time.monotonic() + 150
        QTest.qWait(50)
        while (readiness.active or 'pressed' not in seen) and time.monotonic() < deadline:
            QTest.qWait(20)
        profile = copy.deepcopy(getattr(readiness, 'profile', {}))
        result['recovery'].append(dict(wait_s=wait_s, autosave=str(candidate), prompt=dict(seen),
                                       ready=bool(readiness.ready), error=profile.get('error'),
                                       user_wait_ms=profile.get('user_wait_ms'), stalled_s=profile.get('stalled_s'),
                                       stages_ms=profile.get('stages_ms'), steps=list(steps_log),
                                       wall_ms=round((time.perf_counter() - began) * 1000, 1),
                                       label_text=readiness.label.text()))
        save()
        if readiness.active:
            readiness.cancel()
        QTest.qWait(1500)
    result['passed'] = (all(item['ready'] for item in result['opens'])
                        and all(item['ready'] for item in result['recovery']))
    save()
    return 0
