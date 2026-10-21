"""Validated model download destination; existing weights stay in place."""
from pathlib import Path
import tempfile


def save_model_download_root(value, *, owner=None):
    from ..runtime_paths import get_runtime_paths, set_model_root
    from ..storage.storage_ui import app_busy
    text = str(value).strip()
    if not text:
        raise ValueError('请选择模型下载目录')
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ValueError('模型下载目录必须是绝对路径')
    path = path.resolve()
    current = get_runtime_paths()
    if path == current.model_root.resolve():
        return current
    if app_busy(owner, manual=True):
        raise ValueError('请等待识别、模型下载、安装或修复结束后再更改目录')
    path.mkdir(parents=True, exist_ok=True)
    # Test actual write access, rather than relying on ACL guesses.
    with tempfile.TemporaryFile(dir=path) as probe:
        probe.write(b'2ByteASR model directory probe')
        probe.flush()
    return set_model_root(path)
