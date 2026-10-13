"""搜索功能与设置: type a word, jump to the place that changes it (2026-10-13).

Each entry names the place in plain words, lists the words people type for
it (Chinese, English and common product names) and opens it directly — a
settings page, a provider's setup guide, the shortcut editor, the MCP page,
the home controls or the workbench punctuation menu. Nothing here changes a
setting by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Entry:
    title: str
    keywords: tuple
    where: str
    run: Callable


def _settings(window, section):
    return lambda: window._open_application_settings(initial_section=section)


def _api(window, provider='', kind='asr'):
    return lambda: window._open_api_setup_guide(provider, kind)


def _focus_home(window, attribute):
    def run():
        window._switch_page(0)
        widget = getattr(window, attribute, None)
        if widget is not None:
            widget.setFocus()
            show = getattr(widget, 'showPopup', None)
            if callable(show):
                show()
    return run


def _studio_punctuation(window):
    def run():
        studio = window.built_page('studio')
        if studio is not None and getattr(studio, 'project', None) is not None:
            from .studio_punctuation import open_style_dialog
            window._open_subtitle_studio()
            open_style_dialog(studio)
            return
        from PySide6.QtWidgets import QMessageBox
        from .i18n import tr
        QMessageBox.information(window, tr('字幕标点'), tr('当前工程的标点在字幕工作台工具栏“标点”里切换；'
                                                          '新任务的默认值在首页“字幕语言与输出”最右边。'))
        _focus_home(window, 'subtitle_punctuation')()
    return run


def entries(window) -> list[Entry]:
    open_workshop = getattr(window, '_open_model_workshop', lambda: None)
    return [
        Entry('字幕标点（新任务默认）', ('标点', '逗号', '句号', 'punctuation', '不加标点', '添加标点', '符号'),
              '首页 → 字幕语言与输出', _focus_home(window, 'subtitle_punctuation')),
        Entry('字幕标点（当前工程）', ('标点', 'punctuation', '导出标点', '预览标点'),
              '字幕工作台 → 工具栏“标点”', _studio_punctuation(window)),
        Entry('Qwen Cloud（Qwen 官方 API）', ('qwen', 'qwen cloud', '通义', '千问', 'qwen-audio', '3.1', 'api key', '官网'),
              '申请与设置 API → Qwen Cloud', _api(window, 'qwen_cloud_filetrans')),
        Entry('阿里云百炼 · 录音文件识别', ('百炼', 'bailian', 'dashscope', 'qwen', '阿里云', 'oss', 'workspace'),
              '申请与设置 API → 阿里云百炼', _api(window, 'qwen31_filetrans')),
        Entry('MOSS Pro 云端（MOSI）', ('moss', 'mosi', '云端', '说话人'), '申请与设置 API → MOSI', _api(window, 'mosi_moss_pro')),
        Entry('申请与设置 API（所有服务商）', ('api', 'key', '密钥', '云端', '在线', '服务商', '测试连接'),
              '申请与设置 API', _api(window)),
        Entry('文字 AI（断句、校对、翻译）', ('ai', 'deepseek', 'openai', 'gemini', 'grok', '断句', '校对', '翻译', '文字ai'),
              'AI 智能断句设置', lambda: window._open_ai_settings_dialog()),
        Entry('识别方式（本机 / 云端 / 轻量）', ('方式', '方案', '识别', '模型', '显卡', 'cuda', 'nvidia', 'mac', 'cpu', '本机'),
              '说明 → 选择识别方式', lambda: window._next_step_action('choose_plan')),
        Entry('模型工坊（下载与管理模型）', ('模型', '下载', 'moss', 'firered', 'qwen', 'sensevoice', 'workshop'),
              '顶栏 → 模型工坊', open_workshop),
        Entry('快捷键', ('快捷键', '按键', 'shortcut', 'hotkey', '键盘', 'q/w', 'q', 'w', '改键'),
              '应用设置 → 快捷键', _settings(window, '快捷键')),
        Entry('外部 AI 连接（MCP）', ('mcp', 'claude', 'ai 助手', '外部 ai', 'chatgpt', 'cursor', '连接'),
              '应用设置 → 外部 AI（MCP）', _settings(window, '外部 AI（MCP）')),
        Entry('字幕语言与翻译 / 双语', ('语言', '日语', '翻译', '双语', 'bilingual', 'translation', 'japanese'),
              '首页 → 字幕语言与输出', _focus_home(window, 'recognition_language')),
        Entry('范例工程', ('范例', '示例', 'sample', 'demo', '试用', '体验'), '说明 → 打开范例工程',
              lambda: window._open_sample_project()),
        Entry('新手引导', ('引导', '教程', '新手', 'guide', 'tutorial', '帮助', '开始'), '说明 → 显示新手引导',
              lambda: window._next_step_action('show_guide')),
        Entry('界面主题与动画', ('主题', '外观', '深色', '浅色', 'theme', 'dark', '动画'), '应用设置 → 外观',
              _settings(window, '外观')),
        Entry('工程位置与自动保存', ('工程', '保存', '自动保存', '位置', '目录', 'project', 'autosave'), '应用设置 → 工程与保存',
              _settings(window, '工程与保存')),
        Entry('存储与缓存、模型目录', ('存储', '缓存', '清理', '磁盘', '空间', 'cache', '模型目录'), '应用设置 → 存储与缓存',
              _settings(window, '存储与缓存')),
        Entry('复制诊断信息（问题回报）', ('诊断', '问题', '回报', '日志', 'bug', 'report', '反馈'), '说明 → 复制诊断信息',
              lambda: window._open_diagnostics_dialog()),
        Entry('检查更新', ('更新', '版本', 'update', 'version'), '顶栏 → 检查更新', lambda: window._check_updates()),
        Entry('词库与术语', ('词库', '术语', '专有名词', 'glossary', '规范词'), '首页 → 内容与术语',
              lambda: window._manage_terms()),
    ]


def search(items: list[Entry], query: str) -> list[Entry]:
    from .i18n import tr
    text = str(query or '').strip().casefold()
    if not text:
        return list(items)
    scored = []
    for index, entry in enumerate(items):
        haystack = ' '.join((entry.title, str(tr(entry.title)), entry.where, *entry.keywords)).casefold()
        if text in haystack:
            exact = any(text == keyword.casefold() for keyword in entry.keywords) or text in entry.title.casefold()
            scored.append((0 if exact else 1, index, entry))
    return [entry for _rank, _index, entry in sorted(scored)]


def open_feature_search(window) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout
    from .i18n import bind_text, tr
    items = entries(window)
    dialog = QDialog(window)
    dialog.setObjectName('featureSearch')
    bind_text(dialog, '搜索功能与设置', property='windowTitle')
    dialog.resize(560, 420)
    layout = QVBoxLayout(dialog)
    field = QLineEdit(dialog)
    field.setObjectName('featureSearchField')
    bind_text(field, '输入想找的功能，例如：标点、Qwen、快捷键、MCP、显卡', property='placeholderText')
    layout.addWidget(field)
    results = QListWidget(dialog)
    results.setObjectName('featureSearchResults')
    layout.addWidget(results, 1)
    hint = QLabel(tr('按 Enter 打开第一项；只会打开对应位置，不会自动改设置。'))
    hint.setObjectName('muted')
    layout.addWidget(hint)

    def refresh():
        results.clear()
        for entry in search(items, field.text()):
            row = QListWidgetItem(f"{tr(entry.title)}　·　{tr(entry.where)}")
            row.setData(Qt.ItemDataRole.UserRole, entry.title)
            results.addItem(row)
        if results.count():
            results.setCurrentRow(0)

    def activate(row=None):
        row = row or results.currentItem()
        if row is None:
            return
        title = row.data(Qt.ItemDataRole.UserRole)
        entry = next((item for item in items if item.title == title), None)
        dialog.accept()
        if entry is not None:
            entry.run()

    field.textChanged.connect(lambda _text: refresh())
    field.returnPressed.connect(activate)
    results.itemActivated.connect(activate)
    refresh()
    dialog._entries = items  # for automated checks
    dialog.exec()
