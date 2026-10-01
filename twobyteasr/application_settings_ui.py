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
            self.navigation.insertItem(3, '高级设置')
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
        legal=bind_text(QLabel(), '自有代码：GPL-3.0-only；允许商用和收费分发。第三方条件另见声明。')
        legal.setObjectName('projectLicenseLabel');legal.setWordWrap(True);about.addWidget(legal)
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

    def _values(self):
        from PySide6.QtWidgets import QAbstractButton, QComboBox
        return (tuple((w.objectName(), w.text()) for w in self.findChildren(QLineEdit)),
                tuple(w.currentIndex() for w in self.findChildren(QComboBox)),
                tuple(w.isChecked() for w in self.findChildren(QAbstractButton) if w.isCheckable()))

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
