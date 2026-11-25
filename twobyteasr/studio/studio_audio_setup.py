"""Prepare optional model files outside the Studio GUI process."""
import os
from pathlib import Path
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QInputDialog, QProgressDialog

from ..i18n import tr


def show(page):
    from ..media.vocal_enhancement import _run
    from ..runtime_paths import get_runtime_paths
    from ..system.processes import main_python_executable
    from ..system.runtime_registry import resolve_runtime_python

    if getattr(page, "_studio_audio_setup_active", False):
        page._show_studio_hint(tr("正在准备选用音频模型"))
        return
    paths = get_runtime_paths()
    python = resolve_runtime_python("main") or main_python_executable(paths.install_root)
    if not python:
        page._show_studio_hint(tr("请先准备本机识别运行环境"))
        return
    labels = {tr("已知歌词对齐（约 2.33 GB）"): "lyrics"}
    if os.name == "nt":
        labels.update({
            tr("人声增强 CPU（约 94 MB）"): "vocal-cpu",
            tr("人声增强 CUDA（约 873 MB）"): "vocal-cuda",
            tr("选区歌唱检测（约 22 MB）"): "scene",
        })
    label, accepted = QInputDialog.getItem(page, tr("准备选用音频模型"),
                                          tr("选择要下载并核验的组件"), list(labels), 0, False)
    if not accepted:
        return
    worker = Path(paths.install_root) / "scripts" / "prepare_studio_audio_models.py"
    if not worker.is_file():
        page._show_studio_hint(tr("找不到选用音频模型的安装程序"))
        return
    page._studio_audio_setup_active = True
    cancel = threading.Event()
    done = threading.Event()
    failures = []

    def prepare():
        try:
            _run([python, "-B", "-X", "utf8", str(worker), labels[label]],
                 "Prepare optional Studio audio model", cancel.is_set,
                 cwd=str(paths.install_root), timeout=3600)
        except Exception:
            failures.append(True)
        finally:
            done.set()

    progress = QProgressDialog(tr("正在下载及核验 {model}", model=label), tr("取消"), 0, 0, page)
    progress.setWindowModality(Qt.WindowModality.NonModal)
    progress.canceled.connect(cancel.set)
    page.destroyed.connect(lambda *_: cancel.set())
    timer = QTimer(progress, interval=150)

    def collect():
        if not done.is_set():
            return
        timer.stop()
        progress.deleteLater()
        page._studio_audio_setup_active = False
        if cancel.is_set():
            page._show_studio_hint(tr("已取消准备音频模型"))
        elif failures:
            page._show_studio_hint(tr("音频模型准备未完成，请检查下载记录"))
        else:
            page._show_studio_hint(tr("音频模型已准备完成"))

    timer.timeout.connect(collect)
    progress.show()
    timer.start()
    threading.Thread(target=prepare, daemon=True, name="studio-optional-audio-setup").start()
