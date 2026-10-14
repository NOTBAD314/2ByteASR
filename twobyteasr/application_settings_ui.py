# SPDX-License-Identifier: GPL-3.0-only
"""A compact, sectioned settings surface; persistence stays in application_settings."""
from pathlib import Path
import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)
from .main_ui_dialogs import SpringDialog
from .studio_theme import StudioComboBox, apply_secondary_surface_theme
from .theme_manager import theme_key
from .ui_theme import theme_display_label
from .design.presentation import button_role, field_width
from .build_identity import about_build_text, load_build_identity

from .i18n import bind_text

from .i18n import tr


class ApplicationSettingsDialog(SpringDialog):
    # 高频即开入口：不做入场滑动/渐入动画，点击后立即可操作
    # （2026-09-19 用户反馈：弹窗动画带来约 1 秒等待感，且它是唯一带
    # 弹出动画的顶栏入口）。悬停/选中等常规控件反馈不受影响。
    ENTRY_ANIMATED = False

    def __init__(self, parent, preferences, project_root, *, browse, clear_recent, reset_layout, advanced_owner=None):
        super().__init__(parent)
        if advanced_owner is None and parent is not None and hasattr(parent.window(), 'advanced_disclosure'):
            advanced_owner = parent.window()
        self.setObjectName('applicationSettings')
        bind_text(self, '应用设置', property='windowTitle')
        self.setMinimumSize(480, 300)
        self.resize(860, 650)
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        header=QFrame();header.setObjectName('settingsHeader')
        h=QHBoxLayout(header);h.setContentsMargins(24,20,16,20)
        title=QLabel('应用设置');title.setProperty('typography','title');h.addWidget(title)
        h.addStretch()
        close=button_role(QPushButton('×'),'ghost');close.setFixedSize(32,32);bind_text(close, '关闭设置', property='toolTip')
        close.setStyleSheet('padding: 0; min-width: 0; min-height: 0; font-size: 22px;')
        close.clicked.connect(self.reject);h.addWidget(close);outer.addWidget(header)
        # Native system move retains Windows snapping without geometry animation.
        header.mousePressEvent=lambda e: self.windowHandle().startSystemMove() if e.button()==Qt.MouseButton.LeftButton and self.windowHandle() else None
        body=QHBoxLayout();body.setContentsMargins(0,0,0,0);body.setSpacing(0)
        self.navigation=QListWidget();self.navigation.setObjectName('settingsNavigation');self.navigation.setFixedWidth(160)
        self.navigation.addItems(['工程与保存','Studio 与维护','外观','关于'])
        self.navigation.setProperty('i18nItems', True)
        body.addWidget(self.navigation)
        self.pages=QStackedWidget();self.pages.setMinimumSize(0,0)
        from PySide6.QtWidgets import QSizePolicy
        self.pages.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        body.addWidget(self.pages,1);outer.addLayout(body,1)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)

        def page(title, description):
            scroll=QScrollArea();scroll.setObjectName('settingsScroll');scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame);scroll.viewport().setObjectName('settingsViewport')
            content=QWidget();content.setObjectName('settingsPage');lay=QVBoxLayout(content)
            lay.setContentsMargins(28,24,28,24);lay.setSpacing(16)
            name=QLabel(title);name.setProperty('typography','section');lay.addWidget(name)
            sub=QLabel(description);sub.setObjectName('settingsDescription');sub.setWordWrap(True);lay.addWidget(sub)
            scroll.setWidget(content);self.pages.addWidget(scroll)
            return lay

        def section(lay):
            frame=QFrame();frame.setObjectName('settingsSection')
            rows=QVBoxLayout(frame);rows.setContentsMargins(0,16,0,0);rows.setSpacing(16)
            lay.addWidget(frame)
            return rows

        def row(lay,title,control,note=''):
            line=QHBoxLayout();line.setSpacing(16)
            words=QVBoxLayout();words.setSpacing(4)
            label=QLabel(title);label.setObjectName('settingsRowTitle');words.addWidget(label)
            if note:
                hint=QLabel(note);hint.setObjectName('settingsDescription');hint.setWordWrap(True);words.addWidget(hint)
            line.addLayout(words,1);line.addWidget(control,0,Qt.AlignmentFlag.AlignVCenter);lay.addLayout(line)
            return control

        def toggle(checked):
            control=QCheckBox();control.setChecked(bool(checked));return control

        project=page('工程与保存','设置新工程的位置，以及工作中自动保存和恢复的方式。')
        startup=section(project)
        self.startup_page=field_width(StudioComboBox(),'preferred')
        for label,value in [('字幕识别主页','recognition'),('工程库','project_library')]:
            self.startup_page.addItem(label,value)
        self.startup_page.setCurrentIndex(max(0,self.startup_page.findData(str(preferences.get('startup_page','recognition')))))
        row(startup,'启动后显示',self.startup_page,'双击工程文件时直接打开该工程')
        repair=button_role(QPushButton('关联／修复工程文件关联'),'secondary')
        repair.clicked.connect(self._repair_project_association)
        row(startup,'工程文件关联',repair,'为 .2byteproj 注册当前程序；默认应用由 Windows 管理')
        storage=section(project)
        label=QLabel('默认工程位置');label.setObjectName('settingsRowTitle');storage.addWidget(label)
        rootrow=QHBoxLayout();rootrow.setSpacing(8)
        self.root_edit=field_width(QLineEdit(str(project_root)),'expanding');bind_text(self.root_edit, '默认工程保存位置', property='accessibleName')
        rootrow.addWidget(self.root_edit,1)
        choose=button_role(QPushButton('浏览…'),'secondary');choose.clicked.connect(lambda:browse(self,self.root_edit));rootrow.addWidget(choose)
        storage.addLayout(rootrow)
        reset=button_role(QPushButton('恢复默认位置'),'ghost')
        reset.clicked.connect(lambda:self.root_edit.setText(str(Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'2ByteASR'/'Projects')))
        storage.addWidget(reset,0,Qt.AlignmentFlag.AlignLeft)
        from PySide6.QtCore import QSettings
        frame_settings=QSettings('2ByteASR','2ByteASR')
        storage.addWidget(QLabel('保存当前帧的位置（独立于视频导出目录）'))
        frame_row=QHBoxLayout()
        self.frame_directory=QLineEdit(str(frame_settings.value('frame_export/directory','')))
        bind_text(self.frame_directory, '首次保存帧时选择', property='placeholderText')
        frame_row.addWidget(self.frame_directory,1)
        choose_frame=QPushButton('浏览…')
        choose_frame.clicked.connect(lambda:browse(self,self.frame_directory))
        frame_row.addWidget(choose_frame);storage.addLayout(frame_row)
        self.accepted.connect(lambda:frame_settings.setValue('frame_export/directory',self.frame_directory.text().strip()))
        saving=section(project)
        self.auto_save=toggle(preferences.get('autosave_enabled',True));bind_text(self.auto_save, '自动保存', property='accessibleName')
        row(saving,'自动保存',self.auto_save,'在后台保留工作进度')
        self.interval=field_width(StudioComboBox(),'compact')
        for label,value in [('30 秒',30),('1 分钟',60),('2 分钟',120),('5 分钟',300)]:self.interval.addItem(label,value)
        self.interval.setCurrentIndex(max(0,self.interval.findData(int(preferences.get('autosave_interval_seconds',60) or 60))))
        row(saving,'保存间隔',self.interval)
        self.interval.setEnabled(self.auto_save.isChecked());self.auto_save.toggled.connect(self.interval.setEnabled)
        self.recovery_policy=field_width(StudioComboBox(),'preferred')
        for label,value in [('每次询问','ask'),('恢复较新的自动保存','auto'),('打开正式保存','official')]:self.recovery_policy.addItem(label,value)
        self.recovery_policy.setCurrentIndex(max(0,self.recovery_policy.findData(str(preferences.get('recovery_policy','ask')))))
        row(saving,'打开工程时',self.recovery_policy)
        project.addStretch()

        studio=page('Studio 与维护','让工作区记住你的习惯。维护操作不会删除工程文件。')
        layout=section(studio)
        self.cover=toggle(preferences.get('auto_cover',True));bind_text(self.cover, '自动生成工程封面', property='accessibleName')
        row(layout,'生成工程封面',self.cover,'从素材中生成工程库缩略图')
        self.restore_layout_box=toggle(preferences.get('restore_layout',True));bind_text(self.restore_layout_box, '打开工程时恢复上次布局', property='accessibleName')
        row(layout,'恢复上次工作区',self.restore_layout_box,'记住面板和时间线的布局')
        maintenance=section(studio)
        clear=button_role(QPushButton('清除记录'),'secondary');clear.clicked.connect(clear_recent)
        row(maintenance,'最近使用记录',clear,'工程文件仍保留在原位置')
        if callable(reset_layout):
            reset_workspace=button_role(QPushButton('重置布局'),'secondary');reset_workspace.clicked.connect(reset_layout)
            row(maintenance,'Studio 布局',reset_workspace,'恢复默认的面板位置与尺寸')
        studio.addStretch()

        self.navigation.insertItem(2, '存储与缓存')
        cache_page = page('存储与缓存', '查看应用管理的占用，清理有明确归属的缓存。工程与模型分别保护。')
        from .runtime_paths import get_runtime_paths
        models = section(cache_page)
        model_title = bind_text(QLabel(), '模型下载目录')
        model_title.setObjectName('settingsRowTitle'); models.addWidget(model_title)
        model_row = QHBoxLayout()
        self.model_root_edit = QLineEdit(str(get_runtime_paths().model_root))
        self.model_root_edit.setObjectName('modelDownloadRoot')
        bind_text(self.model_root_edit, '模型下载目录', property='accessibleName')
        model_row.addWidget(self.model_root_edit, 1)
        self.model_root_browse = button_role(bind_text(QPushButton(), '浏览…'), 'secondary')
        self.model_root_browse.clicked.connect(lambda: browse(self, self.model_root_edit))
        model_row.addWidget(self.model_root_browse); models.addLayout(model_row)
        note = bind_text(QLabel(), '新下载的模型和下载临时文件保存在此目录。可选择其他磁盘；现有模型保留原位置，继续可用。')
        note.setObjectName('settingsDescription'); note.setWordWrap(True); models.addWidget(note)
        from .storage_ui import StoragePanel
        self.storage_panel = StoragePanel(self, owner=parent.window() if parent else None)
        cache_page.addWidget(self.storage_panel)
        cache_page.addStretch()

        appearance=page('外观','选择适合你的工作环境的主题与动态反馈。')
        appearance_rows=section(appearance)
        # 2026-10-14: grouped theme cards with a painted miniature each; a
        # click previews the whole app at once, Cancel restores the theme the
        # dialog opened with (done()), Save keeps it.
        from .theme_gallery import ThemeGallery
        self._theme_on_open=theme_key()
        theme_title=bind_text(QLabel(),'界面主题');theme_title.setObjectName('settingsRowTitle');appearance_rows.addWidget(theme_title)
        self.theme_gallery=ThemeGallery(self._theme_on_open)
        self.theme_gallery.themeChosen.connect(self._preview_theme)
        self.theme_gallery.languageRefreshed.connect(self._update_theme_hint)
        appearance_rows.addWidget(self.theme_gallery)
        self.theme_preview_hint=QLabel();self.theme_preview_hint.setObjectName('settingsDescription')
        self.theme_preview_hint.setWordWrap(True);self.theme_preview_hint.setProperty('i18nUserText',True)
        appearance_rows.addWidget(self.theme_preview_hint)
        self._update_theme_hint()
        self.reduce_motion_box=toggle(preferences.get('reduce_motion',False));bind_text(self.reduce_motion_box, '减少界面动画', property='accessibleName')
        row(appearance_rows,'减少动态效果',self.reduce_motion_box,'保留状态反馈，关闭进入与展开动画')
        appearance.addStretch()

        self.advanced_controls = {}
        if advanced_owner is not None:
            self.navigation.insertItem(4, '高级设置')
            advanced = page('高级设置', '调整本批识别、输出和缓存策略。保存后生效。')
            groups = (
                ('识别范围', (('dialogue_coverage', '对白覆盖', '控制角色与主播对白的保留范围'),
                            ('expected_speakers', '预计说话人数', '不确定时保留自动'))),
                ('额外输出', (('review_track', '疑似漏字复核轨', '单独保留需要人工核查的片段'),
                            ('jianying_txt', '剪映文稿 TXT', '输出到素材所在文件夹'),
                            ('speaker_tracks', '分主播 SRT', '按说话人分别导出字幕'))),
                ('缓存与覆盖', (('refresh_polish', '刷新字幕校对缓存', '重新校对，不复用此前结果'),
                              ('refresh_group', '刷新全文断句缓存', '重新进行 AI 断句'),
                              ('overwrite', '已有字幕', '选择遇到已有结果时的处理方式'))),
            )
            from PySide6.QtWidgets import QComboBox
            for group_name, entries in groups:
                group = section(advanced)
                group_title = QLabel(group_name); group_title.setProperty('typography', 'section'); group.addWidget(group_title)
                for key, title, note in entries:
                    source = getattr(advanced_owner, key)
                    if isinstance(source, QComboBox):
                        control = field_width(StudioComboBox(), 'preferred')
                        for i in range(source.count()): control.addItem(source.itemText(i), source.itemData(i))
                        control.setCurrentIndex(source.currentIndex())
                    else:
                        control = toggle(source.isChecked())
                    control.setEnabled(source.isEnabled())
                    control.setAccessibleName(title)
                    self.advanced_controls[key] = control
                    row(group, title, control, note)
            advanced.addStretch()

        self._build_shortcut_page(page)
        self._build_mcp_page(page, section, row, toggle, parent)

        about=page('2ByteASR','本地 AI 字幕与视频创作工具')
        build=load_build_identity()
        version=bind_text(QLabel(), '版本 {value0}', value0=build.app_version);version.setProperty('typography','title');about.addWidget(version)
        context=QLabel('构建信息可在排查问题时提供给支持人员。');context.setObjectName('settingsDescription');about.addWidget(context)
        info=QLabel(about_build_text());info.setObjectName('buildIdentityLabel')
        info.setWordWrap(True);info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);about.addWidget(info)
        copy=button_role(QPushButton('复制构建信息'),'secondary')
        from PySide6.QtWidgets import QApplication
        copy.clicked.connect(lambda:QApplication.clipboard().setText(about_build_text()))
        about.addWidget(copy,0,Qt.AlignmentFlag.AlignLeft)
        legal=bind_text(QLabel(), '项目自有代码采用 GPL-3.0-only，允许依照该许可商用与收费分发。历史生效分界保持为 0.2.6-test.3。')
        legal.setObjectName('projectLicenseLabel');legal.setWordWrap(True);about.addWidget(legal)
        third_party=bind_text(QLabel(),'第三方代码、工具和模型权重分别适用各自许可。历史版本的第三方许可记录继续保留；已移除的模型不随当前程序提供。')
        third_party.setObjectName('thirdPartyModelLicenseLabel');third_party.setWordWrap(True);about.addWidget(third_party)
        from .license_documents import show_document
        for label, filename, name in (
            ('GPL 许可全文', 'LICENSE', 'openProjectLicense'),
            ('第三方声明', 'THIRD_PARTY_NOTICES.md', 'openThirdPartyNotices'),
            ('对应源码交付', 'SOURCE_DELIVERY.md', 'openCorrespondingSource'),
        ):
            button=button_role(bind_text(QPushButton(), label),'secondary');button.setObjectName(name)
            button.clicked.connect(lambda checked=False, f=filename:show_document(self,f))
            about.addWidget(button,0,Qt.AlignmentFlag.AlignLeft)
        about.addStretch()
        self.navigation.setCurrentRow(0)

        footer=QFrame();footer.setObjectName('settingsFooter')
        f=QHBoxLayout(footer);f.setContentsMargins(24,16,24,16);f.setSpacing(8)
        hint=QLabel('保存后应用更改');hint.setProperty('typography','meta');f.addWidget(hint,1)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        save=self.buttons.button(QDialogButtonBox.StandardButton.Save);bind_text(save, '保存更改');button_role(save,'primary')
        cancel=self.buttons.button(QDialogButtonBox.StandardButton.Cancel);bind_text(cancel, '取消');button_role(cancel,'secondary')
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject)
        f.addWidget(self.buttons);outer.addWidget(footer)
        apply_secondary_surface_theme(self)
        self._saved_values = self._values()

    def _build_shortcut_page(self, page):
        """快捷键: every page's keys in one place, saved immediately (2026-10-13)."""
        from . import shortcut_registry
        from .studio_shortcuts import ShortcutSettingsPanel
        self.navigation.insertItem(self.navigation.count() - 1, '快捷键')
        lay = page('快捷键', '按自己的习惯改键：工作台、审核模式、首页、AI 词库校对页与界面缩放。'
                   '同一页面里重复的组合会提示是哪个功能；不同页面可以共用同一个组合。')
        self.shortcut_panel = ShortcutSettingsPanel(shortcut_registry.current_values(), self,
                                                    scopes=tuple(shortcut_registry.SCOPE_LABELS), embedded=True)
        self.shortcut_panel.setObjectName('applicationShortcutPanel')
        self.shortcut_panel.setMinimumHeight(520)
        self.shortcut_panel.cancel_button.hide()
        bind_text(self.shortcut_panel._save_button, '保存快捷键（立即生效）')
        self.shortcut_panel.accepted.connect(self._save_shortcuts)
        lay.addWidget(self.shortcut_panel, 1)
        self._shortcut_saved = dict(self.shortcut_panel.values())

    def _save_shortcuts(self) -> bool:
        from . import shortcut_registry
        panel = getattr(self, 'shortcut_panel', None)
        if panel is None:
            return True
        values = panel.values()
        if values == getattr(self, '_shortcut_saved', None):
            return True
        if shortcut_registry.blocking_conflicts(values):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr('快捷键'), tr('还有快捷键冲突，请先在“快捷键”页处理。'))
            self.navigation.setCurrentRow(self.navigation.count() - 3)
            return False
        shortcut_registry.save_values(values)
        self._shortcut_saved = dict(values)
        bind_text(panel.conflict_label, '已保存，立即生效。')
        return True

    def _build_mcp_page(self, page, section, row, toggle, parent):
        """外部 AI（MCP）: local access for desktop AI clients, off by default (2026-10-12).

        2026-10-13: what leaves the computer is said before access is turned on;
        one export folder can be authorized; Claude Desktop is connected by
        merging one entry into its config (backed up); the status tells
        "written" apart from "a client actually called a tool".
        """
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
        from . import mcp_clients, mcp_common
        self.navigation.insertItem(self.navigation.count() - 1, '外部 AI（MCP）')
        lay = page('外部 AI（MCP）', '让 Claude 等 AI 客户端帮你查字幕、改字幕、导出。每次修改都要你批准，可以撤销。')
        values = mcp_common.read_settings()
        self._mcp_acknowledged = bool(values.get('acknowledged') or values.get('enabled'))
        from .onboarding import emphasis_html
        from .theme_manager import theme_key
        from .ui_theme import theme_definition
        notice = QLabel(emphasis_html(str(tr('开启后，AI 客户端会读到授权范围内的**字幕内容**，并交给它使用的 AI 服务处理')),
                                      theme_definition(theme_key()).accent))
        notice.setObjectName('mcpDataNotice')
        notice.setWordWrap(True)
        notice.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(notice)
        access = section(lay)
        self.mcp_enabled = toggle(values['enabled'])
        bind_text(self.mcp_enabled, '开启本机 MCP 访问', property='accessibleName')
        row(access, '开启本机 MCP 访问', self.mcp_enabled, '关闭时不占资源')
        self.mcp_scope = field_width(StudioComboBox(), 'preferred')
        self.mcp_scope.addItem(tr('仅当前打开的工程'), 'current')
        self.mcp_scope.addItem(tr('工程库目录内的工程'), 'library')
        self.mcp_scope.setCurrentIndex(max(0, self.mcp_scope.findData(values['scope'])))
        row(access, '授权范围', self.mcp_scope, '读取和修改只针对工作台当前打开的工程')
        self.mcp_allow_edits = toggle(values['allow_edits'])
        row(access, '允许提出修改', self.mcp_allow_edits, '每次都要你在兔白里批准，可以撤销')
        self.mcp_allow_export = toggle(values['allow_export'])
        row(access, '允许导出字幕', self.mcp_allow_export, '只写到“MCP 导出”或下面的文件夹，不覆盖')
        folder = QWidget()
        folder_line = QHBoxLayout(folder)
        folder_line.setContentsMargins(0, 0, 0, 0)
        self.mcp_export_dir = QLineEdit(values.get('export_dir') or '')
        self.mcp_export_dir.setObjectName('mcpExportDir')
        self.mcp_export_dir.setReadOnly(True)
        self.mcp_export_dir.setPlaceholderText(tr('未授权（只用工程文件夹里的“MCP 导出”）'))
        self.mcp_export_dir.setMinimumWidth(260)
        choose = button_role(bind_text(QPushButton(), '选择…'), 'secondary')
        clear = button_role(bind_text(QPushButton(), '取消授权'), 'ghost')
        folder_line.addWidget(self.mcp_export_dir, 1)
        folder_line.addWidget(choose)
        folder_line.addWidget(clear)
        # Title and note above a full-width picker: a long path never squeezes the words.
        folder_words = QVBoxLayout()
        folder_words.setSpacing(4)
        folder_title = bind_text(QLabel(), '另外授权的导出文件夹')
        folder_title.setObjectName('settingsRowTitle')
        folder_note = bind_text(QLabel(), 'AI 只能往这里写字幕，不能读取里面的文件')
        folder_note.setObjectName('settingsDescription')
        folder_note.setWordWrap(True)
        folder_words.addWidget(folder_title)
        folder_words.addWidget(folder_note)
        folder_words.addWidget(folder)
        access.addLayout(folder_words)

        connect = section(lay)
        heading = QLabel(tr('连接 AI 客户端'))
        heading.setObjectName('settingsRowTitle')
        connect.addWidget(heading)
        self.mcp_client = field_width(StudioComboBox(), 'preferred')
        self.mcp_client.addItem(tr('Claude Desktop（推荐）'), 'claude_desktop')
        self.mcp_client.addItem(tr('Claude Code（命令行）'), 'claude_code')
        self.mcp_client.addItem(tr('其他支持 MCP 的客户端（复制配置）'), 'other')
        row(connect, '1. 选择客户端', self.mcp_client)
        actions = QHBoxLayout()
        self.mcp_write = button_role(bind_text(QPushButton(), '写入 Claude Desktop 配置'), 'primary')
        self.mcp_write.setObjectName('mcpWriteClaude')
        self.mcp_remove = button_role(bind_text(QPushButton(), '从 Claude Desktop 移除'), 'ghost')
        self.mcp_remove.setObjectName('mcpRemoveClaude')
        self.mcp_copy = button_role(bind_text(QPushButton(), '复制客户端配置'), 'secondary')
        self.mcp_copy.setObjectName('mcpCopyConfig')
        for widget in (self.mcp_write, self.mcp_remove, self.mcp_copy):
            actions.addWidget(widget)
        actions.addStretch(1)
        connect.addLayout(actions)
        self.mcp_steps = QLabel()
        self.mcp_steps.setObjectName('settingsDescription')
        self.mcp_steps.setWordWrap(True)
        self.mcp_steps.setTextFormat(Qt.TextFormat.PlainText)
        connect.addWidget(self.mcp_steps)
        self.mcp_status = QLabel()
        self.mcp_status.setObjectName('mcpStatus')
        self.mcp_status.setWordWrap(True)
        self.mcp_status.setTextFormat(Qt.TextFormat.PlainText)
        self.mcp_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        connect.addWidget(self.mcp_status)
        revoke_line = QHBoxLayout()
        self.mcp_revoke = button_role(bind_text(QPushButton(), '撤销授权（立即断开）'), 'secondary')
        revoke_line.addWidget(self.mcp_revoke)
        revoke_line.addStretch(1)
        connect.addLayout(revoke_line)
        tools = QLabel(tr('能做：查字幕、改字幕（要你批准）、导出。不能：执行命令或读写其他文件。'))
        tools.setObjectName('settingsDescription')
        tools.setWordWrap(True)
        lay.addWidget(tools)
        lay.addStretch()
        owner = parent.window() if parent is not None else None
        self._mcp_message = ''

        def bridge():
            if owner is None:
                return None
            from .mcp_bridge import _BRIDGE
            return _BRIDGE if _BRIDGE is not None and _BRIDGE.window is owner else None

        def location():
            return mcp_clients.claude_desktop_location()

        def steps():
            kind = self.mcp_client.currentData()
            claude = kind == 'claude_desktop'
            self.mcp_write.setVisible(claude)
            self.mcp_remove.setVisible(claude)
            self.mcp_copy.setText(tr('复制命令') if kind == 'claude_code' else tr('复制客户端配置'))
            if claude:
                place = location()
                if place is None or not place.installed:
                    text = tr('2. 先安装 Claude Desktop：{url}', url=mcp_clients.CLAUDE_DOWNLOAD_URL)
                else:
                    text = tr('2. 点“写入 Claude Desktop 配置”\n3. 完全退出 Claude 再打开\n'
                              '4. 在 Claude 里问“兔白里打开的是哪个工程？”')
            elif kind == 'claude_code':
                text = tr('2. 复制命令，在终端运行一次')
            else:
                text = tr('2. 复制配置，贴到客户端的 MCP 设置里')
            self.mcp_steps.setText(text)

        def refresh():
            current = bridge()
            listening = current is not None and current.listening()
            command, args = mcp_common.server_command()
            state = mcp_clients.entry_state(location(), command, args)
            lines = mcp_clients.connection_lines(current.stats if current is not None else {}, listening, state)
            if not listening:
                lines.insert(0, tr('状态：未开启') if not self.mcp_enabled.isChecked() else tr('状态：保存设置后开始监听'))
            elif current.stats.get('refused'):
                lines.append(tr('拒绝的请求：{refused} 次', refused=current.stats.get('refused', 0)))
            if self._mcp_message:
                lines.append(self._mcp_message)
            self.mcp_remove.setEnabled(state in ('written', 'outdated'))
            self.mcp_status.setText('\n'.join(lines))

        def enabled_changed(checked):
            if not checked or self._mcp_acknowledged:
                return
            answer = QMessageBox.question(
                self, tr('开启本机 MCP 访问'),
                tr('开启后，AI 客户端会读到授权范围内的字幕内容，并交给它使用的 AI 服务处理。\n\n确定开启吗？'))
            if answer == QMessageBox.StandardButton.Yes:
                self._mcp_acknowledged = True
            else:
                self.mcp_enabled.blockSignals(True)
                self.mcp_enabled.setChecked(False)
                self.mcp_enabled.blockSignals(False)

        def choose_folder():
            start = self.mcp_export_dir.text() or str(Path.home())
            chosen = QFileDialog.getExistingDirectory(self, tr('选择允许 AI 导出字幕的文件夹'), start)
            if chosen:
                if mcp_common.is_reparse_point(Path(chosen)):
                    QMessageBox.warning(self, tr('导出文件夹'), tr('这个文件夹是链接或联接点，请选择普通文件夹。'))
                    return
                self.mcp_export_dir.setText(str(Path(chosen)))

        def write_claude():
            place = location()
            if place is None or not place.installed:
                self._mcp_message = tr('没有找到 Claude Desktop，未写入。')
                refresh()
                return
            command, args = mcp_common.server_command()
            answer = QMessageBox.question(
                self, tr('写入 Claude Desktop 配置'),
                tr('会在下面的文件里加入一项 2byteasr，先备份，其他设置不变。\n\n{path}', path=str(place.path)))
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                backup = mcp_clients.write_entry(place, command, args)
            except (mcp_clients.ConfigError, OSError) as exc:
                self._mcp_message = tr('没有写入：{reason}', reason=str(exc))
            else:
                self._mcp_message = (tr('已写入。备份：{backup}', backup=str(backup)) if backup
                                     else tr('已写入（新建了配置文件）。'))
                if not self.mcp_enabled.isChecked():
                    self._mcp_message += tr('\n别忘了开启上面的“本机 MCP 访问”并保存，否则 Claude 的调用会被拒绝。')
            refresh()

        def remove_claude():
            place = location()
            if place is None:
                return
            try:
                backup = mcp_clients.remove_entry(place)
            except (mcp_clients.ConfigError, OSError) as exc:
                self._mcp_message = tr('没有修改：{reason}', reason=str(exc))
            else:
                self._mcp_message = tr('已从 Claude Desktop 配置移除 2byteasr。备份：{backup}', backup=str(backup)) \
                    if backup else tr('配置里本来就没有 2byteasr。')
            refresh()

        def copy_config():
            command, args = mcp_common.server_command()
            if self.mcp_client.currentData() == 'claude_code':
                QApplication.clipboard().setText(mcp_clients.claude_code_command(command, args))
                self._mcp_message = tr('已复制命令（配置已生成，尚未写入任何客户端）。')
            else:
                QApplication.clipboard().setText(mcp_common.client_config(command, args))
                self._mcp_message = tr('已复制配置（已生成，尚未写入任何客户端）。本程序需在运行且已开启访问。')
            refresh()

        def revoke():
            current = bridge()
            if current is not None:
                current.revoke()
            else:
                mcp_common.save_settings(dict(mcp_common.read_settings(), enabled=False))
                mcp_common.delete_key()
            self.mcp_enabled.setChecked(False)
            self._saved_values = self._values()
            self._mcp_message = tr('已撤销：访问已关闭，新的请求都会被拒绝。需要时可重新开启。')
            refresh()

        self.mcp_enabled.toggled.connect(enabled_changed)
        choose.clicked.connect(choose_folder)
        clear.clicked.connect(lambda: self.mcp_export_dir.setText(''))
        self.mcp_client.currentIndexChanged.connect(lambda *_: steps())
        self.mcp_write.clicked.connect(write_claude)
        self.mcp_remove.clicked.connect(remove_claude)
        self.mcp_copy.clicked.connect(copy_config)
        self.mcp_revoke.clicked.connect(revoke)
        timer = QTimer(self)
        timer.setInterval(1000)
        timer.timeout.connect(refresh)
        timer.start()
        steps()
        refresh()

    def mcp_values(self):
        return dict(enabled=self.mcp_enabled.isChecked(), scope=self.mcp_scope.currentData() or 'current',
                    allow_edits=self.mcp_allow_edits.isChecked(), allow_export=self.mcp_allow_export.isChecked(),
                    export_dir=self.mcp_export_dir.text().strip(),
                    acknowledged=bool(self._mcp_acknowledged or self.mcp_enabled.isChecked()))

    def _values(self):
        from PySide6.QtWidgets import QAbstractButton, QComboBox
        # The shortcut page keeps its own saved state (its search box and key
        # editors are not settings); unsaved key edits compare as bindings.
        panel = getattr(self, 'shortcut_panel', None)

        def counted(widget):
            return panel is None or not panel.isAncestorOf(widget)
        shortcuts = (tuple(sorted(panel.values().items())) != tuple(sorted(self._shortcut_saved.items()))
                     if panel is not None and hasattr(self, '_shortcut_saved') else False)
        return (tuple((w.objectName(), w.text()) for w in self.findChildren(QLineEdit) if counted(w)),
                tuple(w.currentIndex() for w in self.findChildren(QComboBox) if counted(w)),
                tuple(w.isChecked() for w in self.findChildren(QAbstractButton) if w.isCheckable() and counted(w)),
                shortcuts)

    def accept(self):
        from .model_root_settings import save_model_download_root
        from PySide6.QtWidgets import QMessageBox
        try:
            save_model_download_root(self.model_root_edit.text(), owner=self.parentWidget().window() if self.parentWidget() else None)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, tr('模型下载目录'), str(exc))
            return
        if not self._save_shortcuts():
            return
        super().accept()

    def _repair_project_association(self):
        from PySide6.QtWidgets import QMessageBox
        from .project_file_association import repair_project_association
        try:
            result = repair_project_association()
            QMessageBox.information(self, tr('工程文件关联'), tr('已注册工程打开入口：\n{path}', path=str(result)))
        except Exception as exc:
            QMessageBox.warning(self, tr('工程文件关联'), str(exc))

    @property
    def theme_combo(self):
        """Pre-2026-10-14 name of the theme selector (settings save and audits)."""
        return self.theme_gallery

    def _preview_theme(self, key):
        from PySide6.QtWidgets import QApplication
        from .theme_manager import apply_theme
        apply_theme(str(key), QApplication.instance())
        self._update_theme_hint()

    def _update_theme_hint(self):
        from .ui_theme import theme_definition
        chosen = self.theme_gallery.currentData() or self._theme_on_open
        if chosen == self._theme_on_open:
            text = tr('点选主题即可预览整个界面，保存后保留。')
        else:
            text = tr('正在预览「{name}」：保存后保留，取消则恢复「{original}」。',
                      name=theme_display_label(theme_definition(chosen)),
                      original=theme_display_label(theme_definition(self._theme_on_open)))
        self.theme_preview_hint.setText(str(text))

    def done(self, result):
        # A previewed theme that was not saved goes back to the opening one.
        from PySide6.QtWidgets import QApplication, QDialog
        if result != QDialog.DialogCode.Accepted and theme_key() != getattr(self, '_theme_on_open', theme_key()):
            from .theme_manager import apply_theme
            apply_theme(self._theme_on_open, QApplication.instance())
        super().done(result)

    def reject(self):
        if hasattr(self, '_saved_values') and self._values() != self._saved_values:
            from PySide6.QtWidgets import QMessageBox
            choice = QMessageBox.question(self, tr('未保存的更改'), tr('保存这些设置更改吗？'),
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
            if choice == QMessageBox.Cancel:
                return
            if choice == QMessageBox.Save:
                self.accept()
                return
        super().reject()
