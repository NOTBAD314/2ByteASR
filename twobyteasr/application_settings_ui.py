# SPDX-License-Identifier: GPL-3.0-only
"""A compact, sectioned settings surface; persistence stays in application_settings."""
from pathlib import Path
import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)
from .main_ui_dialogs import SpringDialog
from .studio_theme import StudioComboBox, apply_secondary_surface_theme
from .theme_manager import available_themes, theme_key
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
        self.theme_combo=field_width(StudioComboBox(),'preferred')
        for theme in available_themes():self.theme_combo.addItem(theme_display_label(theme),theme.key)
        self.theme_combo.setCurrentIndex(max(0,self.theme_combo.findData(theme_key())))
        row(appearance_rows,'界面主题',self.theme_combo)
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

    def _build_mcp_page(self, page, section, row, toggle, parent):
        """外部 AI（MCP）: local access for desktop AI clients, off by default (2026-10-12)."""
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from . import mcp_common
        self.navigation.insertItem(self.navigation.count() - 1, '外部 AI（MCP）')
        lay = page('外部 AI（MCP）', '让本机的 AI 客户端（支持 MCP 的桌面应用）读取当前工程、提出修改建议并导出。'
                   '修改只会在你于本程序内点击“批准”后套用，并可撤销。默认关闭。')
        values = mcp_common.read_settings()
        access = section(lay)
        self.mcp_enabled = toggle(values['enabled'])
        bind_text(self.mcp_enabled, '开启本机 MCP 访问', property='accessibleName')
        row(access, '开启本机 MCP 访问', self.mcp_enabled, '只接受本机当前用户的连接；关闭时不监听、不占资源')
        self.mcp_scope = field_width(StudioComboBox(), 'preferred')
        self.mcp_scope.addItem(tr('仅当前打开的工程'), 'current')
        self.mcp_scope.addItem(tr('工程库目录内的工程'), 'library')
        self.mcp_scope.setCurrentIndex(max(0, self.mcp_scope.findData(values['scope'])))
        row(access, '授权范围', self.mcp_scope, '列出工程与导出都限制在此范围内；读取和修改只针对 Studio 当前打开的工程')
        self.mcp_allow_edits = toggle(values['allow_edits'])
        row(access, '允许提出修改', self.mcp_allow_edits, '文字、译文、主要/次要角色、双语排版；每次都需在本程序内批准')
        self.mcp_allow_export = toggle(values['allow_export'])
        row(access, '允许导出字幕', self.mcp_allow_export, '写入工程文件夹下的“MCP 导出”，从不覆盖已有文件')
        status = section(lay)
        self.mcp_status = QLabel()
        self.mcp_status.setObjectName('mcpStatus')
        self.mcp_status.setWordWrap(True)
        self.mcp_status.setTextFormat(Qt.TextFormat.PlainText)
        status.addWidget(self.mcp_status)
        buttons = QHBoxLayout()
        self.mcp_copy = button_role(QPushButton(tr('复制客户端配置')), 'secondary')
        self.mcp_revoke = button_role(QPushButton(tr('撤销授权（立即断开）')), 'secondary')
        buttons.addWidget(self.mcp_copy)
        buttons.addWidget(self.mcp_revoke)
        buttons.addStretch(1)
        status.addLayout(buttons)
        tools = QLabel(tr('提供的工具：状态、工程列表、分页读取字幕与译文、搜索、说话人与角色、字词时间来源；'
                          '预览修改（文字/译文、角色分组、双语排版）→ 程序内批准 → 套用 / 撤销；导出 SRT/JSON。'
                          '不提供命令行、任意文件读写或直接改工程文件的工具。'))
        tools.setObjectName('settingsDescription')
        tools.setWordWrap(True)
        lay.addWidget(tools)
        lay.addStretch()
        owner = parent.window() if parent is not None else None

        def bridge():
            if owner is None:
                return None
            from .mcp_bridge import _BRIDGE
            return _BRIDGE if _BRIDGE is not None and _BRIDGE.window is owner else None

        def refresh():
            current = bridge()
            if current is None or not current.listening():
                text = tr('状态：未开启') if not self.mcp_enabled.isChecked() else tr('状态：保存设置后开始监听')
            else:
                stats = current.stats
                last = stats.get('last_method') or tr('暂无')
                text = tr('状态：正在监听（{pipe}）。请求 {count} 次，拒绝 {refused} 次，最近：{last}',
                          pipe=mcp_common.pipe_name(), count=stats.get('requests', 0),
                          refused=stats.get('refused', 0), last=last)
            self.mcp_status.setText(text)

        def copy_config():
            command, args = mcp_common.server_command()
            QApplication.clipboard().setText(mcp_common.client_config(command, args))
            self.mcp_status.setText(tr('已复制。把它加入 AI 客户端的 MCP 配置（stdio）；本程序需在运行且已开启访问。'))

        def revoke():
            current = bridge()
            if current is not None:
                current.revoke()
            else:
                mcp_common.save_settings(dict(mcp_common.read_settings(), enabled=False))
                mcp_common.delete_key()
            self.mcp_enabled.setChecked(False)
            self._saved_values = self._values()
            self.mcp_status.setText(tr('已撤销：访问已关闭，新的请求都会被拒绝。需要时可重新开启。'))

        self.mcp_copy.clicked.connect(copy_config)
        self.mcp_revoke.clicked.connect(revoke)
        timer = QTimer(self)
        timer.setInterval(1000)
        timer.timeout.connect(refresh)
        timer.start()
        refresh()

    def mcp_values(self):
        return dict(enabled=self.mcp_enabled.isChecked(), scope=self.mcp_scope.currentData() or 'current',
                    allow_edits=self.mcp_allow_edits.isChecked(), allow_export=self.mcp_allow_export.isChecked())

    def _values(self):
        from PySide6.QtWidgets import QAbstractButton, QComboBox
        return (tuple((w.objectName(), w.text()) for w in self.findChildren(QLineEdit)),
                tuple(w.currentIndex() for w in self.findChildren(QComboBox)),
                tuple(w.isChecked() for w in self.findChildren(QAbstractButton) if w.isCheckable()))

    def accept(self):
        from .model_root_settings import save_model_download_root
        from PySide6.QtWidgets import QMessageBox
        try:
            save_model_download_root(self.model_root_edit.text(), owner=self.parentWidget().window() if self.parentWidget() else None)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, tr('模型下载目录'), str(exc))
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
