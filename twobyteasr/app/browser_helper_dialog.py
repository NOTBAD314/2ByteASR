"""Installation and connection guidance for supported browsers."""
import subprocess

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from ..design.studio_theme import StudioComboBox, apply_secondary_surface_theme
from ..i18n import tr
from ..runtime_paths import get_runtime_paths
from .browser_helper_setup import SHARED_CHROMIUM_HOST, detect, registration
from .link_download_widgets import button


def show_wizard(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr("兔白助手"))
    layout = QVBoxLayout(dialog)
    root = get_runtime_paths().install_root
    extension = root / "assets/browser-helper"
    logo = QLabel()
    image = QPixmap(str(extension / "icon.png"))
    logo.setPixmap(image.scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    layout.addWidget(logo)
    chromium_instructions = "1. 打开浏览器的扩展管理，开启「开发者模式」。\n"
    chromium_instructions += ("2. 选择「加载已解压的扩展程序」，选中兔白助手文件夹。\n"
        "3. 在浏览器打开助手，点击「测试连接」。更新后可在扩展卡片中点击「重新加载」。")
    instructions = QLabel(tr(chromium_instructions))
    instructions.setWordWrap(True)
    layout.addWidget(instructions)
    paths = detect()
    browsers = StudioComboBox()
    for name in paths:
        browsers.addItem(name, name)
    layout.addWidget(browsers)
    status = QLabel()
    status.setWordWrap(True)
    layout.addWidget(status)

    def refresh():
        name = browsers.currentData()
        guidance = tr(
            "在 Firefox 调试页选择「临时载入附加组件」，选择助手文件夹里的 manifest.json。暂时安装会在退出 Firefox 后移除。"
            if name == "Firefox" else chromium_instructions)
        if name in SHARED_CHROMIUM_HOST:
            guidance += "\n" + tr("Chrome 和 Brave 共用本机通信。修复或解除连接会同时作用于两者。")
        instructions.setText(guidance)
        if not name:
            status.setText(tr("未检测到受支持的浏览器。"))
            return
        try:
            ready = registration(root, name)
            status.setText(tr("本机通信已注册。请在扩展中测试实际连接。") if ready else tr("尚未注册本机通信。"))
        except OSError:
            status.setText(tr("无法读取当前浏览器的通信注册。"))

    def repair(change):
        if not browsers.currentData():
            return
        try:
            registration(root, browsers.currentData(), change=change)
        except (ValueError, OSError) as exc:
            status.setText(tr(str(exc)))
        else:
            refresh()

    def open_browser():
        name = browsers.currentData()
        if name:
            address = {"Chrome": "chrome://extensions/", "Edge": "edge://extensions/",
                       "Brave": "brave://extensions/", "Firefox": "about:debugging#/runtime/this-firefox"}[name]
            try:
                subprocess.Popen([str(paths[name]), address],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                status.setText(tr("无法打开浏览器扩展管理。"))

    for actions in (
        (("打开扩展管理 / 更新扩展", open_browser), ("打开助手文件夹", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(extension))))),
        (("配置 / 修复本机通信", lambda: repair("install")), ("检查注册", refresh),
         ("解除连接", lambda: repair("remove")))):
        row = QHBoxLayout()
        for label, callback in actions:
            action = button(tr(label))
            action.clicked.connect(callback)
            row.addWidget(action)
        layout.addLayout(row)
    browsers.currentIndexChanged.connect(refresh)
    refresh()
    apply_secondary_surface_theme(dialog)
    dialog.resize(550, 300)
    dialog.exec()
