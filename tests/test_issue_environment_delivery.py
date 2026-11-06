"""Issue #12/#15: runtime ownership and recoverable delivery failures."""
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import venv

import pytest

import subtitle_core as core
from twobyteasr.projects import studio_project as projects


def test_gui_does_not_require_selected_worker_packages(monkeypatch):
    checked = []
    def version(name):
        checked.append(name)
        if name in {'qwen-asr', 'transformers', 'funasr'}:
            raise importlib.metadata.PackageNotFoundError(name)
        return '1.0'
    monkeypatch.setattr(importlib.metadata, 'version', version)
    monkeypatch.setattr(core, 'PRIMARY_ASR_BACKEND', 'qwen_local')
    monkeypatch.setattr(core, 'QWEN_ASR_BACKEND', 'sensevoice')
    monkeypatch.setattr(core, 'FIRERED_ASR_BACKEND', 'qwen_aligner')
    monkeypatch.setattr(core.shutil, 'which', lambda name: name)
    monkeypatch.setattr(core, 'run_hidden_subprocess', lambda *a, **k: subprocess.CompletedProcess(a, 0))
    core.check_runtime()
    assert not set(checked) & {'qwen-asr', 'transformers', 'funasr'}


def test_pillow_is_checked_before_recognition(monkeypatch):
    def version(name):
        if name == 'Pillow':
            raise importlib.metadata.PackageNotFoundError(name)
        return '1.0'
    monkeypatch.setattr(importlib.metadata, 'version', version)
    with pytest.raises(RuntimeError, match='Pillow') as caught:
        core.check_runtime()
    assert sys.executable in str(caught.value)
    assert 'requirements-main.txt' in str(caught.value)


@pytest.mark.parametrize('failure', [ModuleNotFoundError("No module named 'PIL'"), OSError('disk full'), ValueError('layout failed')])
def test_layout_or_write_failure_preserves_recovery_and_prior_project(tmp_path, monkeypatch, failure):
    from twobyteasr.caption_style import subtitle_stacking
    media = tmp_path / 'media.mp4'
    media.write_bytes(b'fixture')
    target = tmp_path / 'delivery' / 'project.2byteproj'
    old = projects.project_from_runtime_cues(str(media), [core.SubtitleCue(1, 0, 1, '原字幕')], initialize_layout=False)
    projects.save_project(old, target)
    before = target.read_bytes()
    def fail(*_a, **_k):
        raise failure
    if isinstance(failure, OSError):
        monkeypatch.setattr(projects, 'save_project', fail)
    else:
        monkeypatch.setattr(subtitle_stacking, 'initialize_project_layout', fail)
    outputs = projects.create_studio_outputs(str(media), [core.SubtitleCue(1, 1, 2, '已完成识别')],
        txt_path='', target_project_path=str(target))
    assert outputs['project'] == ''
    assert outputs['project_error'] == str(failure)
    assert target.read_bytes() == before
    recovered = projects.load_project(outputs['recovery_project'])
    assert [c.text for c in recovered.cues] == ['已完成识别']
    assert recovered.generation_metadata['delivery_recovery']['state'] == 'awaiting_save'


def test_worker_presence_probe_uses_its_interpreter_without_loading_engine(tmp_path):
    from twobyteasr.system.environment import check_worker_dependencies
    env_root = tmp_path / 'worker'
    venv.EnvBuilder(with_pip=False).create(env_root)
    python = env_root / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    with pytest.raises(RuntimeError, match='qwen-asr') as caught:
        check_worker_dependencies('main', str(python), {'qwen-asr': 'qwen_asr'})
    assert str(python) in str(caught.value)
    assert '模型工坊' in str(caught.value)
    site = env_root / ('Lib/site-packages' if sys.platform == 'win32' else f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
    (site / 'qwen_asr.py').write_text("raise AssertionError('preflight loaded engine')\n", 'utf8')
    info = site / 'qwen_asr-1.0.dist-info'
    info.mkdir()
    (info / 'METADATA').write_text('Name: qwen-asr\nVersion: 1.0\n', 'utf8')
    result = check_worker_dependencies('main', str(python), {'qwen-asr': 'qwen_asr'})
    assert result.ok and Path(result.detail['interpreter']) == python
    assert result.detail['prefix'] == str(env_root)


def test_pillow_has_compatible_windows_and_macos_wheels():
    root = Path(__file__).resolve().parents[1]
    assert 'Pillow==12.3.0' in (root/'requirements-main.txt').read_text('utf8')
    assert 'Pillow==12.3.0' in (root/'packaging/macos/requirements-gui.txt').read_text('utf8')
