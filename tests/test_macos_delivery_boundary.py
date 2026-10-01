# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
import pytest
from scripts.macos_build import bundle_inventory, finder_environment
from scripts.macos_collect_artifacts import main, selected_files
from scripts.macos_dependency_contract import verify_native_wheels


def test_artifact_selection_does_not_expose_runtime_models_or_nested_build_source(tmp_path):
    root=tmp_path/"tmp/qa"
    for name in ("runtime/secrets.json","models/model.pt","build/source/private.json",
                 "desktop-flow/local/settings.json","build/app.app.zip","build/native-build-inputs.json",
                 "desktop-flow/exports/中文.srt"):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text("owned test")
    assert {p.relative_to(root).as_posix() for p in selected_files(root)}=={
        "build/app.app.zip","build/native-build-inputs.json","desktop-flow/exports/中文.srt"}
    with pytest.raises(SystemExit,match="storage cap exceeded"):
        main(["--qa-root",str(root),"--maximum-bytes","16"])
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
