# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
import pytest
from scripts.macos_build import bundle_inventory, finder_environment
from scripts.macos_collect_artifacts import main, selected_files
from scripts.macos_dependency_contract import verify_native_wheels
from scripts.macos_media_contract import verify_media_formula


def test_artifact_selection_does_not_expose_runtime_models_or_nested_build_source(tmp_path):
    root=tmp_path/"tmp/qa"
    for name in ("runtime/secrets.json","models/model.pt","build/source/private.json",
                 "desktop-flow/local/settings.json","build/app.app.zip","build/native-build-inputs.json",
                 "desktop-flow/exports/中文.srt"):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text("owned test")
    assert {p.relative_to(root).as_posix() for p in selected_files(root)}=={
        "build/app.app.zip","build/native-build-inputs.json","desktop-flow/exports/中文.srt"}
    with pytest.raises(SystemExit,match="reserve at least"):
        main(["--qa-root",str(root),"--maximum-bytes","16"])
    with pytest.raises(SystemExit,match="600 MiB cap"):
        main(["--qa-root",str(root),"--maximum-bytes",str(601*1024*1024)])
    assert not (root/"artifacts").exists()


def test_relocation_inventory_detects_content_change_and_finder_drops_build_overrides(tmp_path,monkeypatch):
    app=tmp_path/"app";app.mkdir();binary=app/"binary";binary.write_bytes(b"original")
    before=bundle_inventory(app);binary.write_bytes(b"tampered")
    assert bundle_inventory(app)!=before
    monkeypatch.setenv("PATH","/opt/homebrew/bin:/build/venv/bin")
    monkeypatch.setenv("TWOBYTEASR_MAIN_PYTHON","/build/venv/bin/python")
    monkeypatch.setenv("DEEPSEEK_API_KEY","must-not-transfer")
    environment=finder_environment(tmp_path/"tmp/qa")
    assert environment["PATH"]=="/usr/bin:/bin:/usr/sbin:/sbin"
    assert "TWOBYTEASR_MAIN_PYTHON" not in environment
    assert "DEEPSEEK_API_KEY" not in environment


def test_native_installer_receipt_rejects_version_and_hash_drift():
    lock={"critical_wheel_availability":{"torch":{"version":"2.11.0",
        "arm64_cp310_or_universal":[{"filename":"owned-arm64.whl","sha256":"a"*64}]}}}
    row={"metadata":{"name":"torch","version":"2.11.0"},
         "download_info":{"url":"https://files.pythonhosted.org/owned-arm64.whl","archive_info":{"hashes":{"sha256":"a"*64}}}}
    assert verify_native_wheels({"install":[row]},lock)[0]["filename"]=="owned-arm64.whl"
    row["download_info"]["archive_info"]["hashes"]["sha256"]="b"*64
    with pytest.raises(RuntimeError,match="digest differs"):verify_native_wheels({"install":[row]},lock)
    row["metadata"]["version"]="2.12.0"
    with pytest.raises(RuntimeError,match="version drift"):verify_native_wheels({"install":[row]},lock)


def test_media_contract_rejects_the_actual_first_ci_version_and_revision_drift():
    lock=json.loads((Path(__file__).resolve().parents[1]/"packaging/macos/native-dependencies.lock.json").read_text("utf8"))
    for name,version,revision in (("ffmpeg","9.0.1",1),("mpv","0.41.0",9)):
        expected=lock["media"][name]
        formula={"name":expected.get('formula_name',name),"versions":{"stable":version},"revision":revision,
                 "bottle":{"stable":{"files":{"arm64_sequoia":{"sha256":expected["arm64_sequoia_bottle"]["sha256"]}}}}}
        with pytest.raises(RuntimeError,match="formula drift"):
            verify_media_formula(formula,name,expected)
        formula["versions"]["stable"]=expected["version"];formula["revision"]=expected["revision"]
        formula['installed']=[{'version':expected['version']+('_'+str(expected['revision']) if expected['revision'] else '')}]
        assert verify_media_formula(formula,name,expected)["bottle_tag"]=="arm64_sequoia"
        formula["bottle"]["stable"]["files"]["arm64_sequoia"]["sha256"]="0"*64
        with pytest.raises(RuntimeError,match="checksum drift"):
            verify_media_formula(formula,name,expected)


def test_large_app_does_not_discard_receipts(tmp_path):
    root=tmp_path/'tmp/qa';(root/'build').mkdir(parents=True)
    (root/'build/native-build-inputs.json').write_text('{"app_built":true}')
    (root/'build/real.app.zip').write_bytes(b'X'*(21*1024*1024))
    assert main(['--qa-root',str(root),'--maximum-bytes',str(20*1024*1024)])==0
    receipt=root/'artifacts/receipts'
    assert (receipt/'build/native-build-inputs.json').is_file()
    selected=json.loads((receipt/'artifact-selection.json').read_text('utf8'))
    assert selected['withheld'][0]['path']=='build/real.app.zip'
    assert not (root/'artifacts/application').exists()


def test_real_startup_rejects_zero_exit_without_application_receipt_and_retains_error(tmp_path,monkeypatch):
    from scripts.macos_startup_contract import probe
    profile=tmp_path/'tmp/profile';out=tmp_path/'build';out.mkdir()
    def child(command,**kwargs):
        diagnostic=profile/'local/2ByteASR/logs';diagnostic.mkdir(parents=True)
        (diagnostic/'2byteasr-startup.log').write_text('STARTUP CRASH: missing dependency')
        class Result:returncode=0
        return Result()
    monkeypatch.setattr('scripts.macos_startup_contract.subprocess.run',child)
    record=probe(tmp_path/'relocated/App.app',profile,out/'startup-direct.log',finder=False,
                 environment={'PATH':'/usr/bin:/bin'},cwd=tmp_path)
    assert record['passed'] is False and record['launcher_exit_code']==0
    assert 'no startup result' in record['error']
    assert 'missing dependency' in (out/'startup-direct-2byteasr-startup.log').read_text()


def test_launch_services_psn_argument_does_not_disable_startup_smoke(tmp_path):
    from scripts.macos_launch import startup_smoke_argument
    for argv in (['App','--macos-startup-smoke',str(tmp_path)],
                 ['App','-psn_0_12345','--macos-startup-smoke',str(tmp_path)]):
        assert startup_smoke_argument(argv)==tmp_path.resolve()
    with pytest.raises(ValueError):startup_smoke_argument(['App','--macos-startup-smoke'])
    assert startup_smoke_argument(['App','movie.mp4']) is None


def test_startup_probe_unwinds_first_run_modal_before_application_loop():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QDialog,QWidget
    from twobyteasr.main_ui_dialogs import SpringDialog
    from scripts.macos_launch import finish_startup_event_loops
    app=QApplication.instance() or QApplication([])
    parent=QWidget();parent.show()
    dialog=SpringDialog(parent)
    QTimer.singleShot(0,lambda:finish_startup_event_loops(app,[dialog],0))
    assert dialog.exec()==QDialog.DialogCode.Rejected
    guard=QTimer();guard.setSingleShot(True)
    guard.timeout.connect(lambda:app.exit(42));guard.start(200)
    status=app.exec()
    guard.stop()
    parent.close()
    assert status==0


def test_timeout_preserves_visible_application_receipt_without_passing(tmp_path,monkeypatch):
    import subprocess
    from scripts.macos_startup_contract import probe
    profile=tmp_path/'tmp/profile';out=tmp_path/'build';out.mkdir()
    def child(command,**kwargs):
        saved=profile/'startup-smoke/result.json';saved.parent.mkdir(parents=True)
        saved.write_text('{"passed":true,"normal_entry_main_window_visible":true}')
        raise subprocess.TimeoutExpired(command,75)
    monkeypatch.setattr('scripts.macos_startup_contract.subprocess.run',child)
    record=probe(tmp_path/'relocated/App.app',profile,out/'startup-direct.log',finder=False,
                 environment={'PATH':'/usr/bin:/bin'},cwd=tmp_path)
    assert record['passed'] is False and 'timed out' in record['error']
    assert record['application_receipt']['normal_entry_main_window_visible'] is True


def test_desktop_audit_escape_waits_for_real_guided_setup_completion(tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QDialog,QWidget
    from twobyteasr.ui import GuidedSetupDialog
    from scripts.macos_launch import dismiss_first_wizard_for_desktop_audit
    app=QApplication.instance() or QApplication([])
    parent=QWidget();parent.show()
    dialog=GuidedSetupDialog(parent)
    dismiss_first_wizard_for_desktop_audit(app,tmp_path)
    guard=QTimer();guard.setSingleShot(True);guard.timeout.connect(dialog.reject);guard.start(3000)
    result=dialog.exec()
    guard.stop();app._macos_wizard_audit_timer.stop();parent.close()
    receipt=json.loads((tmp_path/'first-run-wizard.json').read_text('utf8'))
    assert result==QDialog.DialogCode.Rejected and receipt['dismissed'] is True
    assert receipt['dialog_result']==int(QDialog.DialogCode.Rejected)
    assert receipt['injected_model_or_transcript'] is False

def test_home_audit_uses_normal_return_refresh_and_keeps_failure_receipt(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QComboBox, QWidget
    from twobyteasr import home_release_flow_audit as audit
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    returned = []
    window._return_to_settings = lambda: returned.append("ordinary model refresh")
    window.primary_asr_backend = QComboBox(window)
    window.studio_page = SimpleNamespace(undo_stack=SimpleNamespace(setClean=lambda: None))
    window.worker = None
    (tmp_path / "home-flow.json").write_text("{}")
    # Dispatch the actual audit callback now; missing selector fails before ASR.
    original = QTimer.singleShot
    monkeypatch.setattr(QTimer, "singleShot", lambda delay, callback: original(0, callback))
    loop = QEventLoop()
    def finished():
        if (tmp_path / "result.json").is_file(): loop.quit()
    timer = QTimer(); timer.timeout.connect(finished); timer.start(10)
    guard = QTimer(); guard.setSingleShot(True); guard.timeout.connect(loop.quit); guard.start(3000)
    audit.start(window, tmp_path); loop.exec(); timer.stop(); guard.stop()
    result = json.loads((tmp_path / "result.json").read_text("utf8"))
    assert returned == ["ordinary model refresh"]
    assert not result["passed"] and not result["checks"]["available primary_asr_backend"]
    assert "AssertionError: available primary_asr_backend" in result["error"]


def test_ci_status_preserves_not_executed_export_instead_of_claiming_execution_failure(tmp_path):
    from scripts.macos_ci_status import summarize
    (tmp_path / "desktop-flow").mkdir()
    (tmp_path / "desktop-flow/export-validation.json").write_text('{"passed":false,"status":"not_executed"}')
    assert summarize(tmp_path)["export_decode"] == "not_executed"


def test_dmg_delivery_keeps_install_receipts_and_omits_duplicate_zip(tmp_path):
    root = tmp_path/'tmp/qa'
    for name, content in (
        ('build/real.app.zip', b'zip'),
        ('dmg/2ByteASR-Setup.dmg', b'dmg'),
        ('dmg/dmg-result.json', b'{"passed":true}'),
        ('blank-project/blank-project-summary.json', b'{"passed":true}'),
        ('blank-project/profile/settings.json', b'private'),
    ):
        path=root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
    assert main(['--qa-root', str(root), '--maximum-bytes', str(20*1024*1024)]) == 0
    receipts=root/'artifacts/receipts'
    selection=json.loads((receipts/'artifact-selection.json').read_text('utf8'))
    assert {row['path'] for row in selection['files']} == {
        'dmg/2ByteASR-Setup.dmg', 'dmg/dmg-result.json', 'blank-project/blank-project-summary.json'}
    assert selection['withheld'][0]['path'] == 'build/real.app.zip'
    assert (root/'artifacts/application/dmg/2ByteASR-Setup.dmg').read_bytes() == b'dmg'
    assert not (receipts/'blank-project/profile/settings.json').exists()


def test_setup_gate_requires_native_blank_checks_and_downloadable_installer(tmp_path):
    from scripts.macos_ci_status import main as status_main
    root=tmp_path/'tmp/qa'; root.mkdir(parents=True)
    record=dict(runtime_identity='passed', media='passed', app='passed', relocation='passed',
                startup='passed', dmg='passed', blank_project='failed', model_requested=False,
                test_step='success')
    saved=root/'ci-status.json'
    saved.write_text(json.dumps(record))
    assert status_main(['--qa-root', str(root), '--enforce']) == 1
    record['blank_project']='passed'; saved.write_text(json.dumps(record))
    assert status_main(['--qa-root', str(root), '--enforce']) == 1
    selection=root/'artifacts/receipts/artifact-selection.json'; selection.parent.mkdir(parents=True)
    selection.write_text(json.dumps({'files':[{'path':'dmg/2ByteASR-Setup.dmg'}]}))
    assert status_main(['--qa-root', str(root), '--enforce']) == 0
