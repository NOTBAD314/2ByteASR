import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_dependency_lock_has_pinned_public_components():
    lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    assert lock["python"] == {"main": "3.10", "moss": "3.12"}
    assert lock["runtime"] == {
        "torch": "2.11.0",
            "torchaudio": "2.11.0",
            "cuda_wheel": "cu126",
            "cuda_wheel_modern": "cu128",
        "setuptools": "80.9.0",
        "wheel": "0.45.1",
    }
    assert set(lock["sources"]) == {"moss", "firered"}
    assert set(lock["models"]) == {
        "moss",
        "firered_vad",
        "firered_aed",
        "qwen_asr",
        "speaker_embedding",
        "qwen_aligner",
        "whisper_turbo",
        "sensevoice",
        "paraformer",
        "funasr_nano",
        "firered_llm",
        "glm_asr_nano",
        "canary_qwen",
        "canary_qwen_tokenizer",
        "omni_asr_llm_7b",
        "ja_ctc_aligner",
    }
    for group in (lock["sources"], lock["models"]):
        for item in group.values():
            assert len(item["revision"]) == 40
            int(item["revision"], 16)
            assert item["license"]
    for item in (*lock["sources"].values(), *(lock["models"][key] for key in (
        "moss", "firered_vad", "firered_aed", "qwen_asr", "speaker_embedding", "qwen_aligner"
    ))):
        assert item["license"] == "Apache-2.0"


def test_launcher_never_falls_back_to_path_python():
    launcher = (ROOT / "2ByteASR.bat").read_text(encoding="utf-8")
    assert "MAIN_PY" not in launcher
    assert ".venv-main" in launcher
    assert "setup_environment.bat" in launcher


def test_p74c_official_entries_prefer_packaged_exe():
    bat = (ROOT / "2ByteASR.bat").read_text(encoding="utf-8")
    assert r"dist\2ByteASR\2ByteASR.exe" in bat
    assert bat.index("PACKAGED") < bat.index("pythonw")
    assert "Developer / source mode" in bat
    source = (ROOT / "launcher" / "2ByteASRLauncher.cs").read_text(encoding="utf-8")
    assert 'Path.Combine(root, "dist", "2ByteASR", "2ByteASR.exe")' in source
    assert "if (File.Exists(packagedApp))" in source
    assert "SetupMarkerName)) || !File.Exists(entrypoint)" not in source
    quick = (ROOT / "quick_start.py").read_text(encoding="utf-8")
    assert "Developer / source-mode" in quick
    assert 'setdefault("TWOBYTEASR_LAUNCH_MODE", "source-dev")' in quick


def test_gitignore_covers_private_and_large_runtime_state():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for entry in (
        "archive/",
        "backups/",
        "models/",
        "outputs/",
        "reports/",
        "review_tracks/",
        "dist/",
        "2ByteASR.exe",
        "scripts/ShortcutIdentity.exe",
        "design-qa.md",
        "third_party/MOSS-Transcribe-Diarize/",
        "third_party/FireRedASR2S/",
        "*.wav",
        "*.mp4",
    ):
        assert entry in ignored


def test_windows_installer_and_release_workflow_are_present():
    installer = (ROOT / "installer" / "2ByteASR.iss").read_text(encoding="utf-8")
    bootstrap = (ROOT / "scripts" / "bootstrap_install.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in installer
    assert "AppId={{D2CA55A8-6992-4C39-BAF1-2D790E9B5E26}" in installer
    assert 'Source: "..\\2byteasr_settings.json"; DestDir: "{app}"; Flags: onlyifdoesntexist' in installer
    assert 'Source: "..\\game_profiles.json"; DestDir: "{app}"; Flags: onlyifdoesntexist' in installer
    assert 'Source: "..\\glossary.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist' in installer
    assert "2ByteASR-Configure.exe" in installer
    assert 'Filename: "{app}\\2ByteASR-Configure.exe"' in installer
    assert 'Filename: "{cmd}"' not in installer
    assert "astral-sh.uv" in bootstrap
    assert "Gyan.FFmpeg" in bootstrap
    # Releases are uploaded as drafts by scripts/release_pipeline.py on the build
    # machine. The workflow is manual, credential-free verification only: pushing
    # or creating a tag must never build or publish anything.
    assert "workflow_dispatch" in workflow and "push:" not in workflow and "tags:" not in workflow
    assert "gh release" not in workflow and "permissions: {}" in workflow
    pipeline = (ROOT / "scripts" / "release_pipeline.py").read_text(encoding="utf-8")
    assert "--clobber" not in pipeline and "never replaced" in pipeline


def test_versioned_self_update_assets_and_metadata_are_present():
    metadata = json.loads((ROOT / "2byteasr_version.json").read_text(encoding="utf-8-sig"))
    builder = (ROOT / "scripts" / "build_hotfix.ps1").read_text(encoding="utf-8-sig")
    installer_builder = (ROOT / "scripts" / "build_installer.ps1").read_text(encoding="utf-8-sig")
    assert re.fullmatch(r"\d+\.\d+\.\d+", metadata["version"])
    assert metadata["repository"] == "NOTBAD314/2ByteASR"
    assert '"2ByteASR-Update-$Version.zip"' in builder
    assert 'version = $Version' in builder
    assert '"twobyteasr\\updater.py"' in builder
    assert '"twobyteasr\\asr.py"' in builder
    assert '"twobyteasr\\llm_config.py"' in builder
    assert '"auto_asr.py"' in builder
    assert '"scripts\\apply_update.ps1"' in builder
    assert '"2byteasr_version.json"' in builder
    assert "2byteasr_version.json" in installer_builder
    # P1-1：wheels 清单从 dependencies.lock.json 动态推导（不再硬编码版本；
    # 旧断言 '"wheels\setuptools-80.9.0-...whl"' 维护的正是该硬编码缺陷）。
    assert "$dependencyLock.runtime.setuptools" in builder
    assert "$dependencyLock.runtime.wheel" in builder
    assert "wheels\\setuptools-$setuptoolsVersion-py3-none-any.whl" in builder
    # Routine in-app updates stay small and reuse the installed runtime.  Large
    # PyTorch wheels belong to the full Setup, not every code/UI hotfix.
    assert '"wheels\\torch-2.11.0+cpu-cp310-cp310-win_amd64.whl"' not in builder
    assert '"twobyteasr\\output.py"' in builder
    assert '"wheels\\torch-2.11.0+cpu-cp312-cp312-win_amd64.whl"' not in builder
    assert '"wheels\\setuptools-83.0.0-py3-none-any.whl"' in builder
    assert '"wheels\\torch-2.13.0+cpu-cp312-cp312-win_amd64.whl"' in builder


def test_installer_shortcuts_share_the_runtime_taskbar_identity():
    installer = (ROOT / "installer" / "2ByteASR.iss").read_text(encoding="utf-8")
    assert '#define MyAppUserModelId "2ByteASR.Desktop.2026"' in installer
    assert installer.count('AppUserModelID: "{#MyAppUserModelId}"') == 2


def test_python_installer_waits_and_records_diagnostics():
    script = (ROOT / "scripts" / "setup_environment.ps1").read_text(encoding="utf-8")
    assert "Start-Process -FilePath $Installer" in script
    assert "-Wait -PassThru -WindowStyle Hidden" in script
    assert "2byteasr-python-$Version-install.log" in script
    assert "Get-PythonInstallerSha256" in script
    assert "3.12.10" in script
    assert "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb" in script


def test_successful_environment_setup_cleans_only_project_uv_cache():
    script = (ROOT / "scripts" / "setup_environment.ps1").read_text(encoding="utf-8")
    assert '$ProjectUvCache = Join-Path $ProjectRoot ".uv-cache"' in script
    assert "$UsingProjectUvCache = -not [bool]$env:UV_CACHE_DIR" in script
    assert "$resolvedCache.Equals($expectedCache" in script
    assert "Remove-Item -LiteralPath $resolvedCache -Recurse -Force" in script
    assert "用户自定义 UV_CACHE_DIR，不自动清理" in script


def test_cuda_torch_stack_is_pinned_to_driver_compatible_matching_versions():
    setup = (ROOT / "scripts" / "setup_environment.ps1").read_text(encoding="utf-8")
    backend_setup = (ROOT / "scripts" / "setup_model_backend.ps1").read_text(encoding="utf-8")
    bundle = (ROOT / "scripts" / "build_offline_bundle.ps1").read_text(encoding="utf-8")
    assert '$CudaTorchVersion = [string]$Lock.runtime.torch' in setup
    assert '$CudaAudioVersion = [string]$Lock.runtime.torchaudio' in setup
    assert '$CudaTorchTag = [string]$Lock.runtime.cuda_wheel' in setup
    assert '$CudaTorchModernTag = [string]$Lock.runtime.cuda_wheel_modern' in setup
    assert 'nvidia-smi --query-gpu=compute_cap' in setup
    assert '$SetuptoolsVersion = [string]$Lock.runtime.setuptools' in setup
    assert '$WheelVersion = [string]$Lock.runtime.wheel' in setup
    assert '"setuptools==$SetuptoolsVersion", "wheel==$WheelVersion"' in setup
    assert "Test-CompatibleCudaTorch" in setup
    assert "torch.__version__ == '$CudaTorchVersion+$CudaTorchTag'" in setup
    assert "torchaudio.__version__ == '$CudaAudioVersion+$CudaTorchTag'" in setup
    assert "torch.empty(1, device='cuda')" in setup
    assert "Remove-IncompleteTorchInstallation" in setup
    assert "--reinstall-package torch --reinstall-package torchaudio" in setup
    assert "--index-strategy unsafe-best-match" in setup
    assert "PyTorch 文件正在被占用" in setup
    assert "Install-CompatibleCudaTorch $MainPython" in backend_setup
    assert "pytorch-wheels/cu130" not in setup
    assert '"torch-$torchCpuVersion%2Bcpu"' in bundle
    assert '"torchaudio-$audioCpuVersion%2Bcpu"' in bundle
    assert "setuptools==$setuptoolsVersion" in bundle
    assert "wheel==$wheelVersion" in bundle
    assert "setuptools==|wheel==" in bundle
    assert "if ($RefreshWheels -and (Test-Path -LiteralPath $WheelsDir" in bundle
    assert "Remove-Item -LiteralPath $WheelsDir -Recurse -Force" in bundle
    assert "Copy-Item -LiteralPath $WheelsDir -Destination $projectWheels" in bundle


def test_model_downloader_switches_are_forwarded_as_named_parameters():
    script = (ROOT / "scripts" / "bootstrap_install.ps1").read_text(encoding="utf-8")
    assert '$downloadArgs = @("-Yes")' not in script
    assert "& $DownloadModelScript -Yes -IncludeQwen -Minimal" in script
    assert "& $DownloadModelScript -Yes -IncludeQwen" in script
    assert "& $DownloadModelScript -Yes -Minimal" in script
    assert "& $DownloadModelScript -Yes" in script


def test_model_dependencies_are_installed_only_after_workshop_selection():
    requirements = (ROOT / "requirements-main.txt").read_text(encoding="utf-8")
    base_setup = (ROOT / "scripts" / "setup_environment.ps1").read_text(encoding="utf-8")
    backend_setup = (ROOT / "scripts" / "setup_model_backend.ps1").read_text(encoding="utf-8")
    downloader = (ROOT / "scripts" / "download_models.ps1").read_text(encoding="utf-8")
    assert "funasr==" not in requirements
    assert "qwen-asr==" not in requirements
    assert "创建 MOSS Python" not in base_setup
    assert '"funasr==1.4.1"' in backend_setup
    assert "setup_model_backend.ps1" in downloader
    assert "-ModelKey $backendKeys" in downloader


def test_release_packages_do_not_ship_runtime_markers_or_dev_artifacts():
    bundle = (ROOT / "scripts" / "build_offline_bundle.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "installer" / "2ByteASR.iss").read_text(encoding="utf-8")
    for excluded in ("2byteasr.setup-complete", "2byteasr.first-run-done", "artifacts", "tests"):
        assert excluded in bundle
    assert "recursesubdirs createallsubdirs" in installer
    assert '"2ByteASR-Lite"' in bundle
    assert '"2ByteASR-Portable"' in bundle
    assert '"$output.sha256"' in bundle
    assert "请求打包版本 $Version 与项目版本 $metadataVersion 不一致" in bundle
    assert "复用项目已验证 wheels/" in bundle
    assert "[switch]$RefreshWheels" in bundle
    assert "& $sevenZipPath @zipArgs" in bundle
    assert "Start-Process -FilePath $sevenZipPath" not in bundle


def test_model_downloader_can_adopt_existing_huggingface_revision_metadata():
    downloader = (ROOT / "scripts" / "download_models.ps1").read_text(encoding="utf-8")
    assert "Test-ModelRevisionMetadata" in downloader
    assert "Test-AllRequiredFilesHashed" in downloader
    assert ".cache\\huggingface\\trees" in downloader
    assert "[跳过]" in downloader
