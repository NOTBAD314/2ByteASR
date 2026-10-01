# SPDX-License-Identifier: GPL-3.0-only
import json
import platform
import subprocess
import sys
from pathlib import Path
import pytest
import yaml
from scripts import macos_build

ROOT=Path(__file__).resolve().parents[1]


def test_manual_workflow_is_bounded_read_only_and_pinned_to_trusted_source():
    # BaseLoader avoids YAML 1.1 interpreting GitHub's `on` as boolean True.
    workflow=yaml.load((ROOT/".github/workflows/macos-experimental.yml").read_text(encoding="utf8"),Loader=yaml.BaseLoader)
    assert set(workflow["on"])=={"workflow_dispatch"}
    assert workflow["permissions"]=={"contents":"read"}
    assert workflow["concurrency"]["cancel-in-progress"]=="false"
    job=workflow["jobs"]["native-arm64"]
    assert job["runs-on"]=="macos-15"
    assert int(job["timeout-minutes"])<=60
    checkout=next(step for step in job["steps"] if "uses" in step and "actions/checkout@" in step["uses"])
    assert checkout["with"]["ref"]=="${{ inputs.source_sha }}"
    assert checkout["with"]["persist-credentials"]=="false"
    for step in job["steps"]:
        if "uses" in step: assert len(step["uses"].split("@")[-1])==40
    upload=next(step for step in job["steps"] if "uses" in step and "actions/upload-artifact@" in step["uses"])
    assert int(upload["with"]["retention-days"])<=3
    text=(ROOT/".github/workflows/macos-experimental.yml").read_text(encoding="utf8")
    assert "secrets." not in text
    assert "gh release" not in text and "docker push" not in text
    names=[step.get('name','') for step in job['steps']]
    assert names.index('Acquire, pour and verify pinned official native media')<names.index('Prepare isolated native CPU runtime and build dependencies')
    assert names.index('Fresh native .app, archive, relocate and normal-entry startup')<names.index('Actual native video hardware probe with no software fallback')


def test_app_build_exit_success_does_not_hide_captured_startup_failure(tmp_path,monkeypatch):
    from scripts.macos_ci_status import main,summarize
    root=tmp_path/'tmp/qa';(root/'build').mkdir(parents=True)
    (root/'media').mkdir();(root/'media/media-install.json').write_text('{"passed":true}')
    (root/'build/native-build-inputs.json').write_text(json.dumps(dict(native_validation=dict(app_built=True,
        relocation=dict(bytes_permissions_symlinks_match=True),packaged_normal_entry_startup_smoke=dict(passed=False,error='Captured native crash',artifact_preserved=True)))))
    monkeypatch.setenv('TEST_OUTCOME','success')
    assert summarize(root)['app']=='passed' and summarize(root)['startup']=='failed'
    assert summarize(root)['home_studio']=='not_executed'
    assert main(['--qa-root',str(root),'--enforce'])==1


def test_mac_dependencies_are_target_specific_and_have_official_arm64_evidence():
    text=(ROOT/"packaging/macos/requirements-gui.txt").read_text(encoding="utf8")
    packages=[line for line in text.splitlines() if line and not line.startswith("#")]
    assert not any(line.startswith(("pycaw","comtypes")) for line in packages)
    lock=json.loads((ROOT/"packaging/macos/native-dependencies.lock.json").read_text(encoding="utf8"))
    assert lock["target"]=="darwin-arm64"
    assert lock["node"]["sha256"]=="1d7f34ec4c03e12d8b33481e5c4560432d7dc31a0ef3ff5a4d9a8ada7cf6ecc9"
    assert lock["platform_materials_complete"] is False
    for package in ("torch","torchaudio","PySide6","PyInstaller","av"):
        assert lock["critical_wheel_availability"][package]["arm64_cp310_or_universal"]


def test_native_source_snapshot_does_not_copy_host_binaries_or_private_config(tmp_path):
    for name in ("renderer/src/index.ts","renderer/node_modules/win.dll","tools/mpv/mpv.exe","scripts/macos_build.py",
                 "twobyteasr/platform_macos.py","assets/public.svg","assets/secrets.dat","models/weights.pt",
                 "private.2byteproj","2byteasr_version.json","2byteasr_settings.json"):
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text("owned input",encoding="utf8")
    selected=[path.relative_to(tmp_path).as_posix() for path in macos_build.input_paths(tmp_path)]
    assert selected==["2byteasr_version.json","assets/public.svg","renderer/src/index.ts","scripts/macos_build.py","twobyteasr/platform_macos.py"]
    output=tmp_path/"snapshot"
    rows=macos_build.copy_snapshot(tmp_path,output)
    assert [row["path"] for row in rows]==selected
    assert all(macos_build.sha256(output/row["path"])==row["sha256"] for row in rows)


def test_non_mac_builder_refuses_before_creating_artifact_directory(tmp_path):
    if sys.platform=="darwin" and platform.machine()=="arm64":pytest.skip("This rejection applies to other hosts")
    output=tmp_path/"unexecuted-app-build"
    with pytest.raises(SystemExit,match="Native Apple Silicon"):
        macos_build.main(["--source-sha","0"*40,"--output",str(output)])
    assert not output.exists()


def test_real_app_spec_selects_arm64_and_does_not_claim_universal_or_developer_id():
    text=(ROOT/"packaging/macos/2byteasr_macos.spec").read_text(encoding="utf8")
    compile(text,str(ROOT/"packaging/macos/2byteasr_macos.spec"),"exec")
    assert "target_arch='arm64'" in text
    assert "codesign_identity=None" in text
    assert "universal2" not in text
    assert "BUNDLE(coll,name='2ByteASR.app'" in text
