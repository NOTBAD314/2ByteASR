"""Actual nested Qt event loops in an isolated offscreen profile."""
import json
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QMessageBox, QPushButton, QWidget, QVBoxLayout

from tests.test_storage_maintenance_ui import qapp
from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
from twobyteasr.acceptance.modal_acceptance_driver import ModalAcceptanceDriver, cancel_without_settings_save_prompt


class ProbeDriver(ModalAcceptanceDriver):
    def finish(self):
        if self.finished:
            return
        self.stop()
        self.checkpoint()
        self.close_diagnostics()


def drain(qapp, driver, emergency):
    # The independent timer also proves a nested exec cannot make QA hang.
    watchdog=QTimer(driver);watchdog.setSingleShot(True)
    watchdog.timeout.connect(emergency);watchdog.start(2500)
    deadline=time.monotonic()+3
    while not driver.finished and time.monotonic()<deadline:
        qapp.processEvents()
        time.sleep(.005)
    watchdog.stop()
    assert driver.finished


def test_actual_settings_and_nested_confirmation_run_with_generator_idle(qapp,tmp_path):
    window=QWidget();window.setObjectName('ownedModalAuditWindow');window.resize(900,700)
    layout=QVBoxLayout(window);open_button=QPushButton('Settings');layout.addWidget(open_button)
    driver=ProbeDriver(window,tmp_path,'nested',timeout=2)
    observed=[];answers=[]

    def open_settings():
        observed.append(('constructor',driver.busy))
        dialog=ApplicationSettingsDialog(window,{},tmp_path/'Projects',browse=lambda:None,
            clear_recent=lambda:None,reset_layout=lambda:None)
        driver.dialog=dialog
        # Real test-induced dirty input must not introduce a save confirmation.
        dialog.root_edit.setText(str(tmp_path/'different-qa-root'))
        ask=QPushButton('confirm fixture',dialog)
        dialog.layout().insertWidget(1,ask)

        def ask_confirmation():
            observed.append(('nested-confirmation',driver.busy))
            answers.append(QMessageBox.question(dialog,'Owned fixture','Tiny fixture only',
                QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel))
        ask.clicked.connect(ask_confirmation)
        driver.ask=ask
        answers.append(dialog.exec())
    open_button.clicked.connect(open_settings)

    def steps():
        driver.phase('open actual settings')
        driver.queue_action('Settings mouse click',lambda:QTest.mouseClick(open_button,Qt.LeftButton))
        yield lambda:driver.dialog is not None and driver.dialog.isVisible()
        driver.check('dialog is observed while outer exec has not returned',not answers)
        driver.queue_action('cleanup mouse click',lambda:QTest.mouseClick(driver.ask,Qt.LeftButton))
        yield lambda:isinstance(qapp.activeModalWidget(),QMessageBox)
        modal=qapp.activeModalWidget()
        driver.check('actual QMessageBox nested under real Settings',modal.parentWidget() is driver.dialog)
        driver.queue_action('real Yes button',lambda:QTest.mouseClick(modal.button(QMessageBox.Yes),Qt.LeftButton))
        yield lambda:bool(answers)
        driver.dialog._saved_values=driver.dialog._values()
        driver.queue_action('real Cancel button',lambda:QTest.mouseClick(driver.dialog.buttons.button(QDialogButtonBox.Cancel),Qt.LeftButton))
        yield lambda:not driver.dialog.isVisible()
        driver.check('normal Yes and Cancel results',answers==[QMessageBox.Yes,0],answers)
    window.show();driver.progress('observer installed before timers');driver.begin(steps())

    def emergency():
        modal=qapp.activeModalWidget()
        if modal:modal.reject()
        if driver.dialog:cancel_without_settings_save_prompt(driver.dialog)
        driver.fail('Independent QA watchdog: nested Qt loop failed to advance')
    drain(qapp,driver,emergency)
    assert driver.result['passed'],driver.result
    assert observed==[('constructor',False),('nested-confirmation',False)]
    progress=json.loads((tmp_path/'nested-progress.json').read_text('utf8'))
    assert progress['finished'] and progress['timer_active'] is False
    assert any(e['event']=='action-enter' for e in progress['events'])
    window.close()


def test_deferred_failure_preserves_original_exception_and_progress(qapp,tmp_path):
    window=QWidget();driver=ProbeDriver(window,tmp_path,'failure',timeout=2)
    def broken():raise RuntimeError('owned deferred failure with original traceback')
    def steps():
        driver.phase('deferred Settings callback')
        driver.queue_action('broken normal entry',broken)
        yield lambda:False
    driver.begin(steps());drain(qapp,driver,lambda:driver.fail('unexpected watchdog'))
    result=json.loads((tmp_path/'failure-result.json').read_text('utf8'))
    progress=json.loads((tmp_path/'failure-progress.json').read_text('utf8'))
    assert not result['passed'] and 'RuntimeError: owned deferred failure' in result['error']
    assert 'in broken' in result['error'] and result['phase']=='deferred Settings callback'
    assert progress['finished'] and progress['error']==result['error']


def test_failure_cancel_real_settings_never_opens_unsaved_changes_prompt(qapp,tmp_path,monkeypatch):
    window=QWidget()
    dialog=ApplicationSettingsDialog(window,{},tmp_path/'Projects',browse=lambda:None,
        clear_recent=lambda:None,reset_layout=lambda:None)
    dialog.root_edit.setText(str(tmp_path/'changed-by-qa'))
    assert dialog._saved_values!=dialog._values()
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Unexpected save prompt')))
    dialog.show();cancel_without_settings_save_prompt(dialog)
    deadline=time.monotonic()+2
    while dialog.isVisible() and time.monotonic()<deadline:
        qapp.processEvents();time.sleep(.005)
    assert dialog._saved_values==dialog._values() and dialog.result()==0 and not dialog.isVisible()
