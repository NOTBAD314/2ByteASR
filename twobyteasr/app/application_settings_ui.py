# SPDX-License-Identifier: GPL-3.0-only
"""A compact, sectioned settings surface; persistence stays in application_settings.

2026-10-25: a category is built the first time it is shown (opening used to
build all eight, ~2 s); edits made in categories visited earlier are kept.
"""
from pathlib import Path
import os
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)
from ..design.main_ui_dialogs import SpringDialog
from ..design.studio_theme import StudioComboBox, apply_secondary_surface_theme
from ..design.theme_manager import theme_key
from ..design.ui_theme import theme_display_label
from ..design.presentation import button_role, field_width
from ..diagnostics.build_identity import about_build_text, load_build_identity
from ..diagnostics.navigation_timing import phase as navigation_phase, timed as navigation_timed

from ..i18n import bind_text

from ..i18n import tr

# Controls that settings saving, audits and older callers read directly;
# reading one builds its category first (without showing it).
_SECTION_CONTROLS = {
    '工程与保存': ('startup_page', 'root_edit', 'frame_directory', 'auto_save', 'interval', 'recovery_policy'),
    'Studio 与维护': ('cover', 'restore_layout_box', 'speaker_tracks', 'caption_pause_on_edit', 'caption_default_layer'),
    '存储与缓存': ('model_root_edit', 'model_root_browse', 'storage_panel'),
    '外观': ('theme_gallery', 'theme_preview_hint', 'reduce_motion_box'),
    '高级设置': ('advanced_controls',),
    '快捷键': ('shortcut_panel', '_shortcut_saved'),
    '外部 AI（MCP）': ('mcp_enabled', 'mcp_scope', 'mcp_allow_edits', 'mcp_allow_export', 'mcp_allow_glossary',
                     'mcp_export_dir', 'mcp_client', 'mcp_write', 'mcp_remove', 'mcp_copy', 'mcp_steps',
                     'mcp_status', 'mcp_revoke', '_mcp_acknowledged', '_mcp_message', '_mcp_refresh', '_mcp_timer'),
    '关于': ('update_reminder_box',),
}
_CONTROL_SECTION = {name: label for label, names in _SECTION_CONTROLS.items() for name in names}


class ApplicationSettingsDialog(SpringDialog):
    UNIFIED_TRANSITION = True
    SURFACE_MOTION = True
    # 高频即开入口：不做入场滑动/渐入动画，点击后立即可操作
    # （2026-09-19 用户反馈：弹窗动画带来约 1 秒等待感，且它是唯一带
    # 弹出动画的顶栏入口）。悬停/选中等常规控件反馈不受影响。
    ENTRY_ANIMATED = False
    # 关闭同样不等淡出（2026-10-25：窗口留着下次直接再显示）。
    EXIT_ANIMATED = False

    @navigation_timed('settings.construct')
    def __init__(self, parent, preferences, project_root, *, browse, clear_recent, reset_layout, advanced_owner=None, repaired_fields=()):
        super().__init__(parent)
        from .settings_lifecycle import normalized_preferences
        preferences, repaired = normalized_preferences(preferences)
        repaired = list(repaired_fields) + repaired
        if advanced_owner is None and parent is not None and hasattr(parent.window(), 'advanced_disclosure'):
            advanced_owner = parent.window()
        # A window shown again calls the callbacks of the opening that shows it.
        self._callbacks = dict(clear_recent=clear_recent, reset_layout=reset_layout)
        self.setObjectName('applicationSettings')
        from ..design.theme_scopes import SHELL_QSS
        self.setStyleSheet(SHELL_QSS)
        bind_text(self, '应用设置', property='windowTitle')
        from .rounded_window import SHADOW, RoundedWindow
        from .settings_widgets import Bunny, ChoiceCards, ChoiceChips, PillSwitch, question
        self.setMinimumSize(560 + 2 * SHADOW, 420 + 2 * SHADOW)
        self.resize(900 + 2 * SHADOW, 660 + 2 * SHADOW)
        # 2026-11-12 (user, design C): a rounded window of its own; chunky
        # sidebar tiles, one light sheet with the bunny's tip, question headings.
        self.setAutoFillBackground(False)
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        self.root=QWidget();self.root.setObjectName('settingsRoot')
        self.root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True);outer.addWidget(self.root)
        body=QHBoxLayout(self.root);body.setContentsMargins(10,10,10,10);body.setSpacing(10)
        sidebar=QFrame();sidebar.setObjectName('settingsSidebar')
        side=QVBoxLayout(sidebar);side.setContentsMargins(6,12,4,8);side.setSpacing(6)
        brand=bind_text(QLabel(),'设置');brand.setObjectName('settingsSidebarTitle');side.addWidget(brand)
        self.navigation=QListWidget();self.navigation.setObjectName('settingsNavigation');self.navigation.setFixedWidth(184)
        self.navigation.setProperty('i18nItems', True)
        self.navigation.setIconSize(QSize(32, 32))
        self.navigation.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        side.addWidget(self.navigation,1)
        body.addWidget(sidebar)
        sheet=QWidget();sheet.setObjectName('settingsSheet')
        sheet.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column=QVBoxLayout(sheet);column.setContentsMargins(0,0,0,0);column.setSpacing(0)
        header=QFrame();header.setObjectName('settingsHeader')
        h=QHBoxLayout(header);h.setContentsMargins(24,16,16,8);h.setSpacing(10)
        h.addWidget(Bunny(46),0,Qt.AlignmentFlag.AlignVCenter)
        self.page_tip=QLabel();self.page_tip.setObjectName('settingsTip');self.page_tip.setWordWrap(True)
        h.addWidget(self.page_tip,1,Qt.AlignmentFlag.AlignVCenter)
        h.addSpacing(24)
        close=QPushButton('×');close.setObjectName('settingsClose');bind_text(close, '关闭设置', property='toolTip')
        close.setAccessibleName('×');close.setAutoDefault(False)
        close.clicked.connect(self.reject);h.addWidget(close,0,Qt.AlignmentFlag.AlignTop)
        column.addWidget(header)
        self.pages=QStackedWidget();self.pages.setMinimumSize(0,0)
        from PySide6.QtWidgets import QSizePolicy
        self.pages.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        column.addWidget(self.pages,1)
        body.addWidget(sheet,1)
        self._page_tips={}

        def page(title, description):
            scroll=QScrollArea();scroll.setObjectName('settingsScroll');scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame);scroll.viewport().setObjectName('settingsViewport')
            content=QWidget();content.setObjectName('settingsPage');lay=QVBoxLayout(content)
            lay.setContentsMargins(26,8,26,20);lay.setSpacing(22)
            # The page's description is the bunny's tip in the sheet header.
            self._page_tips[self._building_section]=description
            scroll.setWidget(content);self._place_page(scroll)
            return lay

        def section(lay, ask=''):
            frame=QFrame();frame.setObjectName('settingsSection')
            rows=QVBoxLayout(frame);rows.setContentsMargins(0,0,0,0);rows.setSpacing(12)
            if ask:
                rows.addWidget(question(ask))
            lay.addWidget(frame)
            return rows

        def words(title, note=''):
            box=QVBoxLayout();box.setSpacing(3)
            label=QLabel(title);label.setObjectName('settingsRowTitle');box.addWidget(label)
            if note:
                hint=QLabel(note);hint.setObjectName('settingsDescription');hint.setWordWrap(True);box.addWidget(hint)
            return box

        def row(lay,title,control,note=''):
            line=QHBoxLayout();line.setSpacing(16)
            line.addLayout(words(title,note),1);line.addWidget(control,0,Qt.AlignmentFlag.AlignVCenter);lay.addLayout(line)
            return control

        def stacked(lay,title,control,note=''):
            """Title and note above a wide control (chips, cards, paths)."""
            box=words(title,note);box.addSpacing(4);box.addWidget(control);lay.addLayout(box)
            return control

        def toggle(checked):
            return PillSwitch(checked)

        def path_field(edit, change, reset=None):
            from ..design.themed_icons import cached_icon_pixmap
            from ..design.theme_manager import theme_definition, theme_key
            field=QFrame();field.setObjectName('settingsPathField')
            line=QHBoxLayout(field);line.setContentsMargins(14,6,6,6);line.setSpacing(8)
            mark=QLabel();mark.setPixmap(cached_icon_pixmap('fa5s.folder-open',theme_definition(theme_key()).accent,QSize(18,18)))
            line.addWidget(mark);line.addWidget(edit,1)
            if reset is not None:
                reset.setObjectName('settingsPathReset');line.addWidget(reset)
            change.setObjectName('settingsPathChange');line.addWidget(change)
            for button in (change, reset):
                if button is not None:
                    button.setAutoDefault(False);button.setCursor(Qt.CursorShape.PointingHandCursor)
            return field

        def build_project():
            project=page('工程与保存','这些只影响新工程，已有工程不会被搬走。')
            if repaired:
                warning = QLabel(tr('部分旧设置无效，已使用默认值。保存前会备份原文件；取消不会修改文件。'))
                warning.setObjectName('settingsDescription')
                warning.setWordWrap(True)
                project.addWidget(warning)
            startup=section(project,'打开软件后，先看到哪里？')
            self.startup_page=field_width(StudioComboBox(),'preferred')
            for label,value in [('字幕识别主页','recognition'),('工程库','project_library')]:
                self.startup_page.addItem(label,value)
            self.startup_page.setCurrentIndex(max(0,self.startup_page.findData(str(preferences.get('startup_page','recognition')))))
            bind_text(self.startup_page, '启动后显示', property='accessibleName')
            startup.addWidget(ChoiceCards(self.startup_page,[('马上开始识别新素材','lines'),('先挑一个工程继续','grid')]))
            double_click=QLabel('双击工程文件时直接打开该工程');double_click.setObjectName('settingsDescription')
            startup.addWidget(double_click)
            repair=button_role(QPushButton('关联／修复工程文件关联'),'secondary')
            repair.clicked.connect(self._repair_project_association)
            row(startup,'工程文件关联',repair,'为 .2byteproj 注册当前程序；默认应用由 Windows 管理')
            storage=section(project,'新工程放在哪里？')
            self.root_edit=field_width(QLineEdit(str(project_root)),'expanding');bind_text(self.root_edit, '默认工程保存位置', property='accessibleName')
            choose=QPushButton('浏览…');choose.clicked.connect(lambda:browse(self,self.root_edit))
            reset=QPushButton('恢复默认位置')
            reset.clicked.connect(lambda:self.root_edit.setText(str(Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'2ByteASR'/'Projects')))
            storage.addWidget(path_field(self.root_edit,choose,reset))
            from PySide6.QtCore import QSettings
            frame_settings=QSettings('2ByteASR','2ByteASR')
            self.frame_directory=QLineEdit(str(frame_settings.value('frame_export/directory','')))
            bind_text(self.frame_directory, '首次保存帧时选择', property='placeholderText')
            choose_frame=QPushButton('浏览…')
            choose_frame.clicked.connect(lambda:browse(self,self.frame_directory))
            stacked(storage,'保存当前帧的位置（独立于视频导出目录）',path_field(self.frame_directory,choose_frame))
            self.accepted.connect(lambda:frame_settings.setValue('frame_export/directory',self.frame_directory.text().strip()))
            saving=section(project)
            self.auto_save=toggle(preferences.get('autosave_enabled',True));bind_text(self.auto_save, '自动保存', property='accessibleName')
            ask=QHBoxLayout();ask.setSpacing(12)
            ask.addWidget(question('要帮你自动保存吗？'));ask.addWidget(self.auto_save);ask.addStretch(1)
            saving.addLayout(ask)
            self.interval=field_width(StudioComboBox(),'compact')
            for label,value in [('30 秒',30),('1 分钟',60),('2 分钟',120),('5 分钟',300)]:self.interval.addItem(label,value)
            self.interval.setCurrentIndex(max(0,self.interval.findData(int(preferences.get('autosave_interval_seconds',30) or 30))))
            bind_text(self.interval, '保存间隔', property='accessibleName')
            saving.addWidget(ChoiceChips(self.interval,prefix='每隔',suffix='保存一次'))
            self.interval.setEnabled(self.auto_save.isChecked());self.auto_save.toggled.connect(self.interval.setEnabled)
            self.recovery_policy=field_width(StudioComboBox(),'preferred')
            # 2026-11-15 (user): opening the newer autosave is the default; asking is a choice here.
            from .application_settings import effective_recovery_policy
            for label,value in [('恢复较新的自动保存','auto'),('每次询问','ask'),('打开正式保存','official')]:self.recovery_policy.addItem(label,value)
            self.recovery_policy.setCurrentIndex(max(0,self.recovery_policy.findData(effective_recovery_policy(preferences))))
            stacked(saving,'打开工程时',ChoiceChips(self.recovery_policy))
            project.addStretch()

        def build_studio():
            studio=page('Studio 与维护','让工作区记住你的习惯。维护操作不会删除工程文件。')
            editing=section(studio,'按 E 编辑字幕时，要怎样？')
            self.caption_pause_on_edit=toggle(preferences.get('caption_pause_on_edit',True))
            bind_text(self.caption_pause_on_edit, '按 E 编辑时暂停播放', property='accessibleName')
            row(editing,'按 E 时暂停播放',self.caption_pause_on_edit,'关闭后可边播边改；开始输入后仍锁定当前字幕')
            self.caption_default_layer=field_width(StudioComboBox(),'preferred')
            self.caption_default_layer.addItem(tr('译文优先'),'translation')
            self.caption_default_layer.addItem(tr('原文优先'),'original')
            self.caption_default_layer.setCurrentIndex(max(0,self.caption_default_layer.findData(str(preferences.get('caption_default_layer','translation')))))
            stacked(editing,'E 默认编辑内容',ChoiceChips(self.caption_default_layer),'双语时优先使用所选内容；没有译文时打开原文，直接选定某层仍编辑该层')
            layout=section(studio,'打开工程时，要帮你准备什么？')
            self.cover=toggle(preferences.get('auto_cover',True));bind_text(self.cover, '自动生成工程封面', property='accessibleName')
            row(layout,'生成工程封面',self.cover,'从素材中生成工程库缩略图')
            self.restore_layout_box=toggle(preferences.get('restore_layout',True));bind_text(self.restore_layout_box, '打开工程时恢复上次布局', property='accessibleName')
            row(layout,'恢复上次工作区',self.restore_layout_box,'记住面板和时间线的布局')
            # 2026-10-22 (user): how many speakers keep an own subtitle track by default.
            self.speaker_tracks=field_width(StudioComboBox(),'compact')
            for count in (1,2,3,5,8):self.speaker_tracks.addItem(tr('{count} 位',count=count),count)
            self.speaker_tracks.setCurrentIndex(max(0,self.speaker_tracks.findData(int(preferences.get('speaker_main_tracks',2) or 2))))
            stacked(layout,'默认独立字幕轨',ChoiceChips(self.speaker_tracks),'字幕最多的几位说话人各占一条轨，其余合成一条；工程里手动选过的不变')
            maintenance=section(studio,'需要整理一下吗？')
            usage=button_role(QPushButton('查看用量与估算费用'),'secondary')
            from ..studio.usage_dialog import open_usage
            usage.clicked.connect(lambda:open_usage(self, project=getattr(getattr(advanced_owner, '_studio_page_instance', None), 'project', None)))
            row(maintenance,'API 用量',usage,'按任务、工程与步骤查看 API 回传用量及当时费率')
            clear=button_role(QPushButton('清除记录'),'secondary');clear.clicked.connect(lambda:self._callbacks['clear_recent']())
            row(maintenance,'最近使用记录',clear,'工程文件仍保留在原位置')
            if callable(reset_layout):
                reset_workspace=button_role(QPushButton('重置布局'),'secondary')
                reset_workspace.clicked.connect(lambda:self._callbacks['reset_layout']())
                row(maintenance,'Studio 布局',reset_workspace,'恢复默认的面板位置与尺寸')
            studio.addStretch()

        def build_storage():
            cache_page = page('存储与缓存', '查看应用管理的占用，清理有明确归属的缓存。工程与模型分别保护。')
            from ..runtime_paths import get_runtime_paths
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
            from ..storage.storage_ui import StoragePanel
            self.storage_panel = StoragePanel(self, owner=parent.window() if parent else None)
            cache_page.addWidget(self.storage_panel)
            cache_page.addStretch()

        def build_appearance():
            appearance=page('外观','选择适合你的工作环境的主题与动态反馈。')
            appearance_rows=section(appearance)
            # 2026-10-14: grouped theme cards with a painted miniature each; a
            # click previews the whole app at once, Cancel restores the theme the
            # dialog opened with (done()), Save keeps it.
            from ..design.theme_gallery import ThemeGallery
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

        def build_advanced():
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
            self.advanced_controls = {}
            for group_name, entries in groups:
                group = section(advanced, group_name)
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

        def build_about():
            about=page('2ByteASR','本地 AI 字幕与视频创作工具')
            build=load_build_identity()
            version=bind_text(QLabel(), '版本 {value0}', value0=build.app_version);version.setProperty('typography','title');about.addWidget(version)
            context=QLabel('构建信息可在排查问题时提供给支持人员。');context.setObjectName('settingsDescription');about.addWidget(context)
            # 2026-10-24 (user): check at every start and pop up a newer version; can be turned off.
            updates=section(about)
            self.update_reminder_box=toggle(preferences.get('update_reminder',True))
            self.update_reminder_box.setObjectName('updateReminderSetting')
            bind_text(self.update_reminder_box, '打开软件时检查更新并提醒', property='accessibleName')
            row(updates,'打开软件时检查更新并提醒',self.update_reminder_box,
                '有新版本时自动弹出更新说明；关闭后只在顶栏「检查更新」按钮上标出新版本')
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

        self._theme_on_open=theme_key()
        self._section_builders=[('工程与保存',build_project),('Studio 与维护',build_studio),
                                ('存储与缓存',build_storage),('外观',build_appearance)]
        if advanced_owner is not None:
            self._section_builders.append(('高级设置',build_advanced))
        else:
            self.advanced_controls = {}
        def build_bunny():
            # 2026-11-15 (user): how much 问问兔白 may do and read, and how hard she thinks.
            from . import bunny_permissions
            from .bunny_chat import REASONING_CHIPS, REASONING_KEY, REASONING_LEVELS
            from .onboarding import load_state
            values = bunny_permissions.load()
            bunny = page('兔白权限', '决定「问问兔白」能帮你做多少、能看哪些东西。上传、删除、开始识别或导出视频，兔白都不会替你按；会计费的 AI 补救默认也先问你。')
            doing = section(bunny)
            self.bunny_level = field_width(StudioComboBox(), 'preferred')
            for value in bunny_permissions.LEVELS:
                self.bunny_level.addItem(bunny_permissions.CHIP_LABELS[value], value)
            self.bunny_level.setCurrentIndex(max(0, self.bunny_level.findData(values['level'])))
            stacked(doing, '兔白能做多少', ChoiceChips(self.bunny_level),
                    '只指路：只看、只讲，不动手。修改先问我：换页面、跳播放头、选字幕、设入出点、开面板和窗口直接做，'
                    '整体偏移、改说话人名字、改样式、首页语言设置要你按「帮我做」。能撤销的直接做：这些修改也直接做，事后可以一键撤销。')
            reading = section(bunny)
            self.bunny_read_subtitles = toggle(values['read_subtitles'])
            bind_text(self.bunny_read_subtitles, '让兔白读字幕原文', property='accessibleName')
            row(reading, '让兔白读字幕原文', self.bunny_read_subtitles, '查问题时一次读一小段，会发给你设置的文字 AI')
            self.bunny_read_diagnostics = toggle(values['read_diagnostics'])
            bind_text(self.bunny_read_diagnostics, '让兔白读诊断和识别记录', property='accessibleName')
            row(reading, '让兔白读诊断和识别记录', self.bunny_read_diagnostics, '已经隐藏 Key 和个人路径，帮她找出错原因')
            self.bunny_allow_paid = toggle(values['allow_paid'])
            bind_text(self.bunny_allow_paid, '会计费的 AI 处理也直接做', property='accessibleName')
            row(reading, '会计费的 AI 处理也直接做', self.bunny_allow_paid,
                '例如重跑失败的 AI 断句、补做没跑完的 AI 校对；用你自己的 Key 计费。只在「能撤销的直接做」时生效，关着就每次先问你')
            self._build_bunny_screen(reading, row, toggle, values)
            self._build_bunny_folders(bunny, section, values, row, toggle)
            # 2026-11-16 (user): now and then she teaches a little trick on her own.
            from .bunny_tips import idle_allowed
            self.bunny_idle_tips = toggle(idle_allowed())
            self.bunny_idle_tips.setObjectName('bunnyIdleTipsSetting')
            bind_text(self.bunny_idle_tips, '兔白不定期说小窍门', property='accessibleName')
            row(reading, '兔白不定期说小窍门', self.bunny_idle_tips,
                '聊天框开着、你一阵子没动时，兔白偶尔冒个小气泡教你一招（几分钟最多一次，不会盖掉要你按的按钮）；点兔白也会说')
            # 2026-11-18 (user): she is in the window by default and speaks up; both can be turned off.
            from . import bunny_events
            hints = bunny_events.load()
            self.bunny_resident = toggle(hints['resident'])
            self.bunny_resident.setObjectName('bunnyResidentSetting')
            bind_text(self.bunny_resident, '启动时让兔白待在窗口里', property='accessibleName')
            row(reading, '启动时让兔白待在窗口里', self.bunny_resident,
                '窗口右下角的小兔白：点一下聊天，可以拖到别处，右键能让她今天先别出来。关掉后顶栏「问问兔白」照常能用')
            self.bunny_hint_mode = field_width(StudioComboBox(), 'preferred')
            self.bunny_hint_mode.setObjectName('bunnyHintModeSetting')
            for value in bunny_events.MODES:
                self.bunny_hint_mode.addItem(tr(bunny_events.MODE_LABELS[value]), value)
            self.bunny_hint_mode.setCurrentIndex(max(0, self.bunny_hint_mode.findData(hints['mode'])))
            bind_text(self.bunny_hint_mode, '兔白主动提醒', property='accessibleName')
            row(reading, '兔白主动提醒', self.bunny_hint_mode,
                '识别做完、出错、跳出报错时，小兔白会冒一个气泡。气泡里的话是本机写好的，不花 Key；你按了气泡上的按钮才会去问 AI。'
                '同一类提醒被你关掉两次，她一周内不再提')
            # 2026-11-18 (user: every few words needed another click): she goes on by herself now;
            # the old one-sentence-per-click box stays for those who liked it.
            from .bunny_chat import click_lines
            self.bunny_click_lines = toggle(click_lines())
            self.bunny_click_lines.setObjectName('bunnyClickLinesSetting')
            bind_text(self.bunny_click_lines, '兔白一句一句说，点一下才说下一句', property='accessibleName')
            row(reading, '兔白一句一句说，点一下才说下一句', self.bunny_click_lines,
                '关着时兔白会自己把话说完，点一下对话框就全部显示；打开就回到每句都等你点一下的样子')
            self._build_bunny_memory(bunny, section, row, toggle, values)
            thinking = section(bunny)
            self.bunny_reasoning = field_width(StudioComboBox(), 'preferred')
            for value in REASONING_LEVELS:
                self.bunny_reasoning.addItem(REASONING_CHIPS[value], value)
            current = load_state().get(REASONING_KEY, 'high')
            self.bunny_reasoning.setCurrentIndex(max(0, self.bunny_reasoning.findData(current)))
            stacked(thinking, '思考深度', ChoiceChips(self.bunny_reasoning),
                    '快速：不思考，回得最快。深思（默认）：先想再答。最深：难题用，会慢一点；难的问题兔白也会自己换成最深。'
                    '聊天框输入栏右边的小按钮也能换')
            bunny.addStretch()

        self._section_builders.append(('兔白权限', build_bunny))
        self._section_builders.append(('我的改动', lambda: self._build_overlay_page(page, section, row, toggle)))
        self._section_builders+=[('快捷键',self._build_shortcut_page),
                                 ('外部 AI（MCP）',lambda:self._build_mcp_page(page, section, row, toggle, parent)),
                                 ('关于',build_about)]
        self._section_built=set();self._sections_building=set();self._building_section=None
        self._input_baseline={}
        from PySide6.QtWidgets import QListWidgetItem
        from .settings_widgets import section_icon
        for label,_build in self._section_builders:
            self.navigation.addItem(QListWidgetItem(section_icon(label),label));self.pages.addWidget(QWidget())
        self._icons_theme=theme_key()
        self.navigation.currentRowChanged.connect(self._select_section)

        footer=QFrame();footer.setObjectName('settingsFooter')
        f=QHBoxLayout(footer);f.setContentsMargins(26,10,18,16);f.setSpacing(10)
        self._footer=f
        f.addStretch(1)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        save=self.buttons.button(QDialogButtonBox.StandardButton.Save);bind_text(save, '保存更改');button_role(save,'primary')
        cancel=self.buttons.button(QDialogButtonBox.StandardButton.Cancel);bind_text(cancel, '取消');button_role(cancel,'secondary')
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject)
        f.addWidget(self.buttons);column.addWidget(footer)
        apply_secondary_surface_theme(self)
        self.chrome=RoundedWindow(self, self.root, title_areas=[brand, header], radius=26, maximizable=False)
        # The rounded window resizes from its edges; the bounds' corner grip
        # would sit in the transparent shadow.
        from PySide6.QtWidgets import QSizeGrip
        for grip in self.findChildren(QSizeGrip):
            grip.setMaximumSize(0, 0)
        self.navigation.setCurrentRow(0)
        # _values() lists only inputs changed since their category was built.
        self._saved_values = ()

    def __getattr__(self, name):
        # Only reached for attributes not set yet: a control of a category not
        # built yet. Internal "is it built?" checks read self.__dict__ instead.
        label = _CONTROL_SECTION.get(name)
        builders = self.__dict__.get('_section_builders')
        if label is not None and builders is not None:
            index = next((i for i, (title, _build) in enumerate(builders) if title == label), None)
            if index is not None:
                self._build_section(index)
                if name in self.__dict__:
                    return self.__dict__[name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def _place_page(self, widget):
        """The page of the category being built; it joins the window once built."""
        self._section_page = widget

    def _build_section(self, index):
        if index in self._section_built or index in self._sections_building:
            return
        label, build = self._section_builders[index]
        self._sections_building.add(index)
        previous = self._building_section, self.__dict__.pop('_section_page', None)
        self._building_section = index
        try:
            with navigation_phase('settings.section:' + label):
                build()
            page = self.__dict__.pop('_section_page')
        finally:
            self._building_section, self._section_page = previous
            self._sections_building.discard(index)
        # What construction and showing the window did for every category
        # when all were built up front: control widths before the window's
        # style sheet polishes them (classified after polishing, a combo box
        # keeps 36 px instead of the zoomed sheet's height), then, once
        # shown, the interface zoom and the language pass, in that order.
        from ..design.presentation import prepare_controls
        prepare_controls(page)
        placeholder = self.pages.widget(index)
        self.pages.insertWidget(index, page)
        self.pages.removeWidget(placeholder)
        placeholder.deleteLater()
        self._section_built.add(index)
        # New inputs start from what they show now; edits elsewhere stay edits.
        for widget, value in self._input_values(page):
            self._input_baseline.setdefault(widget, value)
        if self.isVisible():
            from .ui_zoom import apply_to
            from ..i18n import apply_ui_language, current_language
            apply_to(page)
            apply_ui_language(page, current_language())

    def add_report_button(self, text):
        """回报问题／导出诊断 as a quiet link at the footer's left (2026-11-12)."""
        button = bind_text(QPushButton(), text)
        button.setObjectName('settingsReport')
        button.setAutoDefault(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._footer.insertWidget(0, button)
        return button

    def _show_tip(self, index):
        label = self._section_builders[index][0]
        bind_text(self.page_tip, self._page_tips.get(index) or label)

    def _refresh_section_icons(self):
        if self.__dict__.get('_icons_theme') in (None, theme_key()):
            return
        from .settings_widgets import section_icon
        self._icons_theme = theme_key()
        for index, (label, _build) in enumerate(self._section_builders):
            item = self.navigation.item(index)
            if item is not None:
                item.setIcon(section_icon(label))

    def changeEvent(self, event):
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self._refresh_section_icons()
        super().changeEvent(event)

    def paintEvent(self, event):
        # The rounded window paints its own shadow and corners; no square fill.
        from PySide6.QtWidgets import QDialog
        QDialog.paintEvent(self, event)

    def showEvent(self, event):
        super().showEvent(event)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._refresh_section_icons()

    def _select_section(self, index):
        if index < 0:
            return
        # 2026-11-20 (user: a black frame on every page switch): the old page is copied while it
        # is still shown, then fades over the new one. Taken later (at its Hide, the app-wide
        # page fade) a translucent window has only an empty sheet to give, or black.
        from ..design.transitions import capture_page, start_page_crossfade
        picture = (capture_page(self.pages)
                   if self.isVisible() and self.pages.currentIndex() not in (-1, index) else None)
        self._build_section(index)
        self.pages.setCurrentIndex(index)
        start_page_crossfade(self.pages, picture)
        self._show_tip(index)
        timer = self.__dict__.get('_mcp_timer')
        if timer is not None:
            if self._section_builders[index][0] == '外部 AI（MCP）':
                self._mcp_refresh()
                timer.start()
            else:
                timer.stop()

    def ensure_section(self, label) -> bool:
        """Show one category by name (source or current language); deep links use it."""
        for index, (name, _build) in enumerate(self._section_builders):
            if label in (name, str(tr(name))):
                if self.navigation.currentRow() == index:
                    self._select_section(index)
                else:
                    self.navigation.setCurrentRow(index)
                return True
        return False

    def section_built(self, label) -> bool:
        return any(name == label and index in self._section_built
                   for index, (name, _build) in enumerate(self._section_builders))

    def prepare_reuse(self, *, clear_recent, reset_layout):
        """Shown again: this opening's callbacks, first category, centred like a new window."""
        self._callbacks.update(clear_recent=clear_recent, reset_layout=reset_layout)
        if 'mcp_enabled' in self.__dict__:
            from ..local_mcp import mcp_common
            values = mcp_common.read_settings()
            self._mcp_acknowledged = bool(values.get('acknowledged') or values.get('enabled'))
            self._mcp_message = ''
        self.navigation.setCurrentRow(0)
        self.setAttribute(Qt.WidgetAttribute.WA_Moved, False)

    def reusable(self) -> bool:
        """Closed without edits and without background storage work."""
        panel = self.__dict__.get('storage_panel')
        if panel is not None and (panel.worker is not None or panel.scan_result is not None):
            return False
        return not self._values()

    @navigation_timed('settings.shortcuts')
    def _build_shortcut_page(self):
        """快捷键: every page's keys in one place (2026-10-13).

        2026-10-17: the page does not scroll itself; the panel's grouped list
        is the one scroll area (the old table sat in the page's scroll and
        showed four rows). 保存更改 below saves the keys with everything else.
        2026-10-25: rows are built in batches while the page is shown.
        """
        from ..studio import shortcut_registry
        from ..studio.studio_shortcuts import ShortcutSettingsPanel
        content = QWidget(); content.setObjectName('settingsPage')
        lay = QVBoxLayout(content); lay.setContentsMargins(26, 8, 20, 16); lay.setSpacing(12)
        # The bunny's tip in the sheet header says how keys are changed.
        self._page_tips[self._building_section] = '点一下按键，再按新的组合；按 Esc 取消。同一页面里不能重复，不同页面可以共用。'
        self._place_page(content)
        self.shortcut_panel = ShortcutSettingsPanel(shortcut_registry.current_values(), self,
                                                    scopes=tuple(shortcut_registry.SCOPE_LABELS), embedded=True,
                                                    incremental=True)
        self.shortcut_panel.setObjectName('applicationShortcutPanel')
        lay.addWidget(self.shortcut_panel, 1)
        self._shortcut_saved = dict(self.shortcut_panel.values())

    def _save_shortcuts(self) -> bool:
        from ..studio import shortcut_registry
        panel = self.__dict__.get('shortcut_panel')
        if panel is None:
            return True
        values = panel.values()
        if values == self._shortcut_saved:
            return True
        if shortcut_registry.blocking_conflicts(values):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr('快捷键'), tr('还有快捷键冲突，请先在“快捷键”页处理。'))
            self.ensure_section('快捷键')
            return False
        shortcut_registry.save_values(values)
        self._shortcut_saved = dict(values)
        panel.show_message(tr('已保存，立即生效。'))
        return True

    @navigation_timed('settings.mcp')
    def _build_mcp_page(self, page, section, row, toggle, parent):
        """外部 AI（MCP）: local access for desktop AI clients, off by default (2026-10-12).

        2026-10-13: what leaves the computer is said before access is turned on;
        one export folder can be authorized; Claude Desktop is connected by
        merging one entry into its config (backed up); the status tells
        "written" apart from "a client actually called a tool".
        """
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
        from ..local_mcp import mcp_clients, mcp_common
        lay = page('外部 AI（MCP）', '让 AI 客户端查字幕、制作工程和导出。制作工具按下方权限直接执行；旧版预览计划仍需逐次批准。')
        mcp_page = self._section_page
        values = mcp_common.read_settings()
        self._mcp_acknowledged = bool(values.get('acknowledged') or values.get('enabled'))
        from .onboarding import emphasis_html
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
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
        row(access, '授权范围', self.mcp_scope, '当前工程范围不切换工程；工程库范围可创建和打开库内工程')
        self.mcp_allow_edits = toggle(values['allow_edits'])
        row(access, '允许制作和修改', self.mcp_allow_edits, '可直接创建、打开、保存工程、识别和编辑；字幕与剪切可撤销，旧预览计划仍需批准')
        self.mcp_allow_export = toggle(values['allow_export'])
        row(access, '允许导出字幕和视频', self.mcp_allow_export, '只写到“MCP 导出”或下面的文件夹，不覆盖')
        self.mcp_allow_glossary = toggle(values['allow_glossary'])
        row(access, '允许查看和修改术语库', self.mcp_allow_glossary, '术语库对所有工程通用；修改同样要你在兔白里批准')
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
        tools = QLabel(tr('制作工具可独立识别、AI校对、断句、文字口吃整理、检测与剪切停顿；AI使用软件中已保存的服务配置。术语库条目修改和旧预览计划仍需批准。不能执行命令或任意写入文件。'))
        tools.setObjectName('settingsDescription')
        tools.setWordWrap(True)
        lay.addWidget(tools)
        lay.addStretch()
        owner = parent.window() if parent is not None else None
        self._mcp_message = ''

        def bridge():
            if owner is None:
                return None
            from ..local_mcp.mcp_bridge import _BRIDGE
            return _BRIDGE if _BRIDGE is not None and _BRIDGE.window is owner else None

        def client():
            return mcp_clients.CODE if self.mcp_client.currentData() == 'claude_code' else mcp_clients.DESKTOP

        def location():
            if client() == mcp_clients.CODE:
                return mcp_clients.claude_code_location()
            return mcp_clients.claude_desktop_location()

        # 2026-10-17: Claude Desktop rewrites its config from memory while it runs,
        # so whether it runs decides if writing can work (checked at most every 3 s).
        claude_check = {'at': -10.0, 'started': None}

        def claude_started(fresh=False):
            import time
            now = time.monotonic()
            if fresh or now - claude_check['at'] > 3:
                claude_check.update(at=now, started=mcp_clients.claude_desktop_started_at())
            return claude_check['started']

        def steps():
            kind = self.mcp_client.currentData()
            claude, code = kind == 'claude_desktop', kind == 'claude_code'
            self.mcp_write.setVisible(claude or code)
            self.mcp_remove.setVisible(claude or code)
            bind_text(self.mcp_write, '写入 Claude Code 配置' if code else '写入 Claude Desktop 配置')
            bind_text(self.mcp_remove, '从 Claude Code 移除' if code else '从 Claude Desktop 移除')
            bind_text(self.mcp_copy, '复制命令' if code else '复制客户端配置')
            if claude:
                place = location()
                if place is None or not place.installed:
                    text = tr('2. 先安装 Claude Desktop：{url}', url=mcp_clients.CLAUDE_DOWNLOAD_URL)
                else:
                    text = tr('2. 完全退出 Claude（任务栏托盘图标 → 退出，只关窗口不算）\n'
                              '3. 点“写入 Claude Desktop 配置”\n4. 打开 Claude，在对话里问“兔白里打开的是哪个工程？”\n'
                              'Claude 的对话和 Code 页都会读这一项。')
            elif code:
                text = tr('2. 点“写入 Claude Code 配置”（或复制命令，在终端运行一次）\n'
                          '3. 新开一个 Claude Code 会话，问“兔白里打开的是哪个工程？”')
            else:
                text = tr('2. 复制配置，贴到客户端的 MCP 设置里')
            self.mcp_steps.setText(text)

        def refresh():
            steps()                     # Claude may be installed while this page is open
            current = bridge()
            listening = current is not None and current.listening()
            command, args = mcp_common.server_command()
            kind, place = client(), location()
            state = mcp_clients.entry_state(place, command, args, kind)
            lines = mcp_clients.connection_lines(current.stats if current is not None else {}, listening, state,
                                                 client=kind, written=mcp_clients.written_at(kind, place),
                                                 started=claude_started() if kind == mcp_clients.DESKTOP else None)
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
            kind, place = client(), location()
            code = kind == mcp_clients.CODE
            if place is None or not place.installed:
                self._mcp_message = tr('没有找到 Claude Code，未写入。') if code else tr('没有找到 Claude Desktop，未写入。')
                refresh()
                return
            if not code and claude_started(fresh=True):
                QMessageBox.warning(
                    self, tr('写入 Claude Desktop 配置'),
                    tr('Claude 正在运行，现在写入会被它覆盖：Claude 只在打开时读这个文件，运行中改自己的设置时会把旧设置整份写回去。\n\n'
                       '请先完全退出 Claude（任务栏托盘图标 → 退出，只关窗口不算），再回来点“写入”。'))
                self._mcp_message = tr('Claude 正在运行，没有写入。完全退出 Claude 后再点“写入”。')
                refresh()
                return
            command, args = mcp_common.server_command()
            answer = QMessageBox.question(
                self, tr('写入 Claude Code 配置') if code else tr('写入 Claude Desktop 配置'),
                tr('会在下面的文件里加入一项 2byteasr，先备份，其他设置不变。\n\n{path}', path=str(place.path)))
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                backup = mcp_clients.write_entry(place, command, args, kind)
            except (mcp_clients.ConfigError, OSError) as exc:
                self._mcp_message = tr('没有写入：{reason}', reason=str(exc))
            else:
                self._mcp_message = (tr('已写入。备份：{backup}', backup=str(backup)) if backup
                                     else tr('已写入（新建了配置文件）。'))
                if code:
                    self._mcp_message += tr('\n之后新开的 Claude Code 会话可用；已经开着的会话要重开。')
                if not self.mcp_enabled.isChecked():
                    self._mcp_message += tr('\n别忘了开启上面的“本机 MCP 访问”并保存，否则 Claude 的调用会被拒绝。')
            refresh()

        def remove_claude():
            kind, place = client(), location()
            if place is None:
                return
            try:
                backup = mcp_clients.remove_entry(place, kind)
            except (mcp_clients.ConfigError, OSError) as exc:
                self._mcp_message = tr('没有修改：{reason}', reason=str(exc))
            else:
                if not backup:
                    self._mcp_message = tr('配置里本来就没有 2byteasr。')
                elif kind == mcp_clients.CODE:
                    self._mcp_message = tr('已从 Claude Code 配置移除 2byteasr。备份：{backup}', backup=str(backup))
                else:
                    self._mcp_message = tr('已从 Claude Desktop 配置移除 2byteasr。备份：{backup}', backup=str(backup))
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
            # Already saved: closing must not ask to save it again (other edits still count).
            self.accept_external_value(self.mcp_enabled)
            self._mcp_message = tr('已撤销：访问已关闭，新的请求都会被拒绝。需要时可重新开启。')
            refresh()

        self.mcp_enabled.toggled.connect(enabled_changed)
        choose.clicked.connect(choose_folder)
        clear.clicked.connect(lambda: self.mcp_export_dir.setText(''))
        self.mcp_client.currentIndexChanged.connect(lambda *_: refresh())
        self.mcp_write.clicked.connect(write_claude)
        self.mcp_remove.clicked.connect(remove_claude)
        self.mcp_copy.clicked.connect(copy_config)
        self.mcp_revoke.clicked.connect(revoke)
        # Process discovery is unrelated to opening Settings: it runs when this
        # page is selected (_select_section) and every second while it is shown.
        timer = QTimer(self)
        timer.setInterval(1000)
        timer.timeout.connect(lambda: refresh() if self.isVisible() and mcp_page.isVisible() else None)
        self._mcp_timer = timer
        self._mcp_refresh = refresh
        bind_text(self.mcp_status, '打开此页后检查客户端连接状态。')

    def mcp_values(self):
        return dict(enabled=self.mcp_enabled.isChecked(), scope=self.mcp_scope.currentData() or 'current',
                    allow_edits=self.mcp_allow_edits.isChecked(), allow_export=self.mcp_allow_export.isChecked(),
                    export_dir=self.mcp_export_dir.text().strip(),
                    acknowledged=bool(self._mcp_acknowledged or self.mcp_enabled.isChecked()),
                    allow_glossary=self.mcp_allow_glossary.isChecked())

    def _input_values(self, root=None):
        from PySide6.QtWidgets import QAbstractButton, QComboBox
        # The shortcut page keeps its own saved state (its search box and key
        # editors are not settings); unsaved key edits compare as bindings.
        panel = self.__dict__.get('shortcut_panel')
        for kind, read in ((QLineEdit, QLineEdit.text), (QComboBox, QComboBox.currentIndex),
                           (QAbstractButton, QAbstractButton.isChecked)):
            for widget in (self if root is None else root).findChildren(kind):
                if (panel is None or not panel.isAncestorOf(widget)) and (kind is not QAbstractButton or widget.isCheckable()):
                    yield widget, read(widget)

    def _values(self):
        """The inputs changed since their category was built, plus unsaved keys.

        Compared input by input (2026-10-25), so building or browsing
        categories is never a change; empty when there is nothing to save.
        """
        changed = tuple((widget, value) for widget, value in self._input_values()
                        if value != self._input_baseline.get(widget, value))
        panel = self.__dict__.get('shortcut_panel')
        if panel is not None and panel.values() != self._shortcut_saved:
            changed += (('shortcuts', tuple(sorted(panel.values().items()))),)
        return changed

    def accept_external_value(self, widget):
        """A value saved by an action on the page itself (storage move, MCP revoke)."""
        for control, value in self._input_values():
            if control is widget:
                self._input_baseline[control] = value
                return

    def accept(self):
        from ..local_models.model_root_settings import save_model_download_root
        from PySide6.QtWidgets import QMessageBox
        model_root = self.__dict__.get('model_root_edit')
        try:
            if model_root is not None:
                save_model_download_root(model_root.text(), owner=self.parentWidget().window() if self.parentWidget() else None)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, tr('模型下载目录'), str(exc))
            return
        if not self._save_shortcuts():
            return
        self._save_bunny_permissions()
        super().accept()

    def _build_overlay_page(self, page, section, row, toggle):
        """「我的改动」 (2026-11-16, user_overlay): every change the user or 兔白 made, kept out of the
        program folder so updates never overwrite it. Actions apply at once, like the memory list."""
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QComboBox, QListWidgetItem
        from . import user_overlay, user_overlay_runtime
        lay = page('我的改动', '你自己或兔白替你做的改动都存在这台电脑的用户资料里，软件更新不会覆盖。每条都能单独关掉、删掉，'
                   '也能回到之前的样子。启动时按住 Shift，这次就先不套用任何改动。')
        rows = section(lay)
        self.overlay_status = QLabel()
        self.overlay_status.setObjectName('settingsDescription')
        self.overlay_status.setWordWrap(True)
        rows.addWidget(self.overlay_status)
        self.overlay_list = QListWidget()
        self.overlay_list.setObjectName('userOverlayList')
        self.overlay_list.setMinimumHeight(170)
        self.overlay_list.setWordWrap(True)
        self.overlay_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.overlay_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.overlay_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        rows.addWidget(self.overlay_list)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.overlay_edit = button_role(bind_text(QPushButton(), '查看 / 修改'), 'secondary')
        self.overlay_remove = button_role(bind_text(QPushButton(), '删掉选中的'), 'secondary')
        self.overlay_new_script = button_role(bind_text(QPushButton(), '新建扩展脚本'), 'secondary')
        self.overlay_folder = button_role(bind_text(QPushButton(), '打开文件夹'), 'secondary')
        for button in (self.overlay_edit, self.overlay_remove, self.overlay_new_script):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.overlay_folder)
        rows.addLayout(actions)
        scripts = section(lay)
        self.overlay_scripts = toggle(bool(user_overlay.load().get('scripts_allowed')))
        self.overlay_scripts.setObjectName('userOverlayScriptsSetting')
        bind_text(self.overlay_scripts, '允许运行我的扩展脚本', property='accessibleName')
        row(scripts, '允许运行我的扩展脚本', self.overlay_scripts,
            '扩展脚本是 Python 程序，能做软件能做的任何事（包括读写文件、上网），只打开你看过、信得过的脚本。'
            '兔白写的脚本存下来时是关着的，要你看过再打开。脚本出错会自动停用；启动时出问题按住 Shift 就能先不加载。'
            '停用会停止 api.every 定时器；脚本已做的其他操作和代码修改，需要重启程序才能完全停止或重新加载')
        history = section(lay)
        title = QLabel()
        bind_text(title, '回到之前的样子')
        title.setObjectName('settingsRowTitle')
        history.addWidget(title)
        line = QHBoxLayout()
        self.overlay_history = field_width(QComboBox(), 'preferred')
        self.overlay_history.setObjectName('userOverlayHistory')
        self.overlay_restore = button_role(bind_text(QPushButton(), '回到这次改动之前'), 'secondary')
        line.addWidget(self.overlay_history, 1)
        line.addWidget(self.overlay_restore)
        history.addLayout(line)

        def apply_now():
            try:
                user_overlay_runtime.reapply()
            except Exception as exc:  # noqa: BLE001 - said on the page
                self.overlay_status.setText(str(tr('改动已保存，但这次没能马上套用：{why}')).format(why=f'{type(exc).__name__}: {exc}'))

        def refresh(message: str = ''):
            self.overlay_list.blockSignals(True)
            self.overlay_list.clear()
            items = user_overlay.entries()
            for entry in items:
                item = QListWidgetItem(user_overlay.describe(entry))
                item.setData(Qt.ItemDataRole.UserRole, entry['id'])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if entry.get('enabled') else Qt.CheckState.Unchecked)
                tip = [entry.get('note') or '', entry.get('detail') or '', f'{entry.get("created", "")} · {entry.get("app_version", "")}']
                item.setToolTip('\n'.join(part for part in tip if part.strip(' ·')))
                self.overlay_list.addItem(item)
            if not items:
                placeholder = QListWidgetItem(tr('还没有改动。可以让兔白帮你改（她会先问你），或者自己新建扩展脚本。'))
                placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                self.overlay_list.addItem(placeholder)
            self.overlay_list.blockSignals(False)
            self.overlay_history.clear()
            for snap in user_overlay.snapshots()[:20]:
                self.overlay_history.addItem(f'{snap["when"]} · {snap["reason"]}（之前有 {snap["count"]} 条）', snap['id'])
            self.overlay_restore.setEnabled(self.overlay_history.count() > 0)
            paused = [entry for entry in items if entry.get('status')]
            runtime = user_overlay_runtime.runtime()
            words = [message] if message else []
            if runtime is not None and runtime.safe:
                words.append(str(tr('这次是安全模式启动，改动都没有套用。')))
            if paused:
                words.append(str(tr('{n} 条改动被程序暂停了（把勾打上就会再试一次）：')).format(n=len(paused))
                             + '；'.join(f'{entry["id"]} {user_overlay.STATUS_LABELS.get(entry["status"], entry["status"])}'
                                        for entry in paused[:4]))
            self.overlay_status.setText('\n'.join(words) or str(tr('改动存放在：{path}')).format(path=user_overlay.root()))

        def selected_id():
            item = self.overlay_list.currentItem()
            return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

        def checked(item):
            entry_id = item.data(Qt.ItemDataRole.UserRole)
            if not entry_id:
                return
            try:
                user_overlay.set_enabled(entry_id, item.checkState() == Qt.CheckState.Checked)
            except user_overlay.OverlayError as exc:
                refresh(str(exc))
                return
            apply_now()
            QTimer.singleShot(0, self, refresh)

        def remove():
            entry_id = selected_id()
            if not entry_id:
                return
            user_overlay.remove(entry_id)
            apply_now()
            refresh(str(tr('删掉了 {id}；想要回来可以用下面的「回到之前的样子」。')).format(id=entry_id))

        def edit():
            entry_id = selected_id()
            entry = user_overlay.find(entry_id) if entry_id else None
            if entry is None:
                return
            if entry['kind'] == 'script':
                text = user_overlay.script_path(entry).read_text('utf-8') if user_overlay.script_path(entry).is_file() else ''
            else:
                text = entry['value']
            changed = self._edit_overlay_text(entry, text)
            if changed is None:
                return
            try:
                if entry['kind'] == 'script':
                    user_overlay.set_code(entry_id, changed)
                else:
                    user_overlay.update(entry_id, value=changed)
            except user_overlay.OverlayError as exc:
                refresh(str(exc))
                return
            apply_now()
            refresh(str(tr('{id} 改好了。')).format(id=entry_id))

        def new_script():
            template = (f'API_VERSION = {user_overlay.API_VERSION}\n\n\n'
                        'def setup(api):\n'
                        '    """软件窗口出来后运行一次。api.window 是主窗口，api.find("控件名") 找控件，\n'
                        '    api.log("…") 记一行，api.data_dir 是这个脚本自己的文件夹，api.every(毫秒, 函数) 定时运行。"""\n'
                        '    api.log("我的脚本开始运行了")\n')
            code = self._edit_overlay_text({'kind': 'script', 'id': '新脚本', 'value': ''}, template)
            if code is None:
                return
            try:
                entry, _snap = user_overlay.add('script', '', '我自己写的脚本', code=code, by='user',
                                                app_version=user_overlay_runtime.program_identity())
            except user_overlay.OverlayError as exc:
                refresh(str(exc))
                return
            apply_now()
            refresh(str(tr('存好了 {id}。打开上面的「允许运行我的扩展脚本」后才会运行。')).format(id=entry['id']))

        def scripts_toggled(on):
            user_overlay.set_scripts_allowed(on)
            apply_now()
            refresh()

        def restore():
            snapshot = self.overlay_history.currentData()
            if not snapshot:
                return
            try:
                user_overlay.restore(snapshot)
            except user_overlay.OverlayError as exc:
                refresh(str(exc))
                return
            self.overlay_scripts.blockSignals(True)
            self.overlay_scripts.setChecked(bool(user_overlay.load().get('scripts_allowed')))
            self.overlay_scripts.blockSignals(False)
            apply_now()
            refresh(str(tr('回去了。刚才的样子也存了一份，想反悔可以再选回来。')))

        def open_folder():
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            user_overlay.root().mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(user_overlay.root())))

        self.overlay_list.itemChanged.connect(checked)
        self.overlay_list.itemDoubleClicked.connect(lambda _item: edit())
        self.overlay_remove.clicked.connect(remove)
        self.overlay_edit.clicked.connect(edit)
        self.overlay_new_script.clicked.connect(new_script)
        self.overlay_scripts.toggled.connect(scripts_toggled)
        self.overlay_restore.clicked.connect(restore)
        self.overlay_folder.clicked.connect(open_folder)
        self.overlay_refresh = refresh
        refresh()
        lay.addStretch()

    def _edit_overlay_text(self, entry: dict, text: str):
        """A small editor for one change (a script's code, a style, a sentence); None when cancelled."""
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout
        dialog = QDialog(self)
        dialog.setObjectName('userOverlayEditor')
        dialog.setWindowTitle(str(tr('我的改动')) + f' · {entry.get("id", "")}')
        dialog.resize(720 if entry['kind'] == 'script' else 520, 520 if entry['kind'] == 'script' else 220)
        layout = QVBoxLayout(dialog)
        hint = QLabel(str(tr({'script': '扩展脚本（Python）。保存前会检查语法，并要有 API_VERSION 和 setup(api)。',
                              'style': '样式：写成「属性: 值;」，例如 font-size: 16px; color: #333333;',
                              'text': '这句界面文字要换成的说法：',
                              'note': '给兔白的长期说明：'}.get(entry['kind'], ''))))
        hint.setWordWrap(True)
        hint.setObjectName('settingsDescription')
        layout.addWidget(hint)
        editor = QPlainTextEdit()
        editor.setObjectName('userOverlayCode')
        editor.setPlainText(text)
        if entry['kind'] == 'script':
            editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bind_text(buttons.button(QDialogButtonBox.StandardButton.Save), '保存')
        bind_text(buttons.button(QDialogButtonBox.StandardButton.Cancel), '取消')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        apply_secondary_surface_theme(dialog)
        self._overlay_editor = dialog
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return editor.toPlainText()

    def _build_bunny_screen(self, rows, row, toggle, values):
        """2026-11-16 (user): 兔白 may take a picture of 2ByteASR's own windows; off by default, explained once."""
        from PySide6.QtWidgets import QMessageBox
        from . import bunny_permissions, bunny_vision
        from .bunny_chat import runtime_settings
        owner = self.parentWidget().window() if self.parentWidget() else None
        try:
            able, advice = bunny_vision.support(runtime_settings(owner) if owner is not None else None)
        except Exception:  # noqa: BLE001 - the note only
            able, advice = False, ''
        self.bunny_see_screen = toggle(values.get('see_screen', False))
        self.bunny_see_screen.setObjectName('bunnySeeScreenSetting')
        bind_text(self.bunny_see_screen, '让兔白截图看 2ByteASR 的画面', property='accessibleName')
        note = ('只截 2ByteASR 自己的窗口，不截桌面和其他程序；截图发给你设置的文字 AI，不存到电脑上。'
                + ('现在的 AI 能看图。' if able else '现在的 AI 看不了图，要换成能看图的模型（' + bunny_vision.SEEING_MODELS + '）才用得上。'))
        row(rows, '让兔白截图看 2ByteASR 的画面', self.bunny_see_screen, note)

        def changed(on):
            if not on or bunny_permissions.screen_explained():
                return
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle(str(tr('让兔白截图看画面')))
            box.setText(str(tr('让兔白截图看 2ByteASR 的画面？')))
            box.setInformativeText(str(tr(bunny_vision.PRIVACY_NOTE)) + ('' if able else '\n\n' + advice))
            yes = box.addButton(str(tr('打开')), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(str(tr('先不要')), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is yes:
                bunny_permissions.mark_screen_explained()
            else:
                self.bunny_see_screen.setChecked(False)
        self.bunny_see_screen.toggled.connect(changed)

    def _build_bunny_folders(self, lay, section, values, row=None, toggle=None):
        """2026-11-16 (harness plan P3): folders 兔白 may list, read and write new files in; saved at once.
        2026-11-20 (user): she changes existing files there too, and 「让兔白读写整台电脑的文件」 (off by default)."""
        from PySide6.QtWidgets import QFileDialog, QListWidget, QListWidgetItem
        from . import bunny_permissions
        rows = section(lay)
        title = QLabel()
        bind_text(title, '兔白可以看的文件夹')
        title.setObjectName('settingsRowTitle')
        rows.addWidget(title)
        note = QLabel()
        bind_text(note, '只在这些文件夹里列文件、读文件（术语表、字幕、文档、Word、Excel），读到的内容会发给你设置的文字 AI；'
                        '写新文件、改已有的文件，每次都要你按「帮我做」，改之前的样子会另存一份、可以撤销；不删除文件。默认一个都没有')
        note.setObjectName('settingsDescription')
        note.setWordWrap(True)
        rows.addWidget(note)
        self.bunny_folder_list = QListWidget()
        self.bunny_folder_list.setObjectName('bunnyFolderList')
        self.bunny_folder_list.setMinimumHeight(64)
        self.bunny_folder_list.setMaximumHeight(132)
        rows.addWidget(self.bunny_folder_list)

        def refresh(folders=None):
            self.bunny_folder_list.clear()
            folders = bunny_permissions.load()['folders'] if folders is None else folders
            for folder in folders:
                item = QListWidgetItem(folder)
                item.setData(Qt.ItemDataRole.UserRole, folder)
                self.bunny_folder_list.addItem(item)
            if not folders:
                placeholder = QListWidgetItem(tr('还没有授权文件夹。'))
                placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                self.bunny_folder_list.addItem(placeholder)

        def add_folder():
            path = QFileDialog.getExistingDirectory(self, str(tr('选一个兔白可以看的文件夹')))
            if path:
                current = bunny_permissions.load()['folders']
                refresh(bunny_permissions.save({'folders': [*current, str(Path(path))]})['folders'])

        def remove_selected():
            chosen = {item.data(Qt.ItemDataRole.UserRole) for item in self.bunny_folder_list.selectedItems()}
            current = bunny_permissions.load()['folders']
            refresh(bunny_permissions.save({'folders': [f for f in current if f not in chosen]})['folders'])

        actions = QHBoxLayout()
        actions.setSpacing(8)
        add = button_role(QPushButton(), 'secondary')
        bind_text(add, '添加文件夹…')
        remove = button_role(QPushButton(), 'secondary')
        bind_text(remove, '移除选中的')
        actions.addWidget(add)
        actions.addWidget(remove)
        actions.addStretch(1)
        rows.addLayout(actions)
        add.clicked.connect(add_folder)
        remove.clicked.connect(remove_selected)
        self.bunny_folder_add, self.bunny_folder_remove = add, remove
        refresh(values.get('folders') or [])
        if row is None or toggle is None:
            return
        self.bunny_files_anywhere = toggle(values.get('files_anywhere', False))
        self.bunny_files_anywhere.setObjectName('bunnyFilesAnywhereSetting')
        bind_text(self.bunny_files_anywhere, '让兔白读写整台电脑的文件', property='accessibleName')
        row(rows, '让兔白读写整台电脑的文件', self.bunny_files_anywhere,
            '不只上面的文件夹：你给完整路径，她就能读、写新文件和改文件（写和改每次都要你按「帮我做」）。'
            '读到的内容会发给你设置的文字 AI。通过此开关访问时，Windows 和程序文件夹禁止写入，2ByteASR 自己的资料禁止读写')

        def anywhere_changed(on):
            bunny_permissions.save({'files_anywhere': bool(on)})
        self.bunny_files_anywhere.toggled.connect(anywhere_changed)

    def _build_bunny_memory(self, lay, section, row, toggle, values):
        """兔白's memory of the user and the user's knowledge base for her (2026-11-15). Entries are
        added and removed at once (like the MCP page's actions); the on/off switch saves with the page."""
        from PySide6.QtWidgets import QListWidget, QListWidgetItem, QPlainTextEdit
        from . import bunny_memory
        rows = section(lay)
        self.bunny_remember = toggle(values['remember'])
        bind_text(self.bunny_remember, '让兔白记住我的习惯', property='accessibleName')
        row(rows, '让兔白记住我的习惯', self.bunny_remember,
            '她会把你的长期习惯和喜好记成一句话，下次也照着配合你；和知识库一起发给你设置的文字 AI。不记密钥、密码和账号')
        self.bunny_memory_list = QListWidget()
        self.bunny_memory_list.setObjectName('bunnyMemoryList')
        self.bunny_memory_list.setMinimumHeight(140)
        self.bunny_memory_list.setWordWrap(True)
        rows.addWidget(self.bunny_memory_list)

        def refresh():
            self.bunny_memory_list.clear()
            entries = bunny_memory.load()
            for entry in entries:
                kind = tr({'memory': '兔白记的', 'knowledge': '知识库', 'recipe': '配方'}.get(entry['kind'], '知识库'))
                item = QListWidgetItem(f'[{kind}] {entry["text"]}')
                item.setData(Qt.ItemDataRole.UserRole, entry['id'])
                item.setToolTip(entry['text'])
                self.bunny_memory_list.addItem(item)
            if not entries:
                placeholder = QListWidgetItem(tr('还没有记忆，也还没教过兔白什么。'))
                placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                self.bunny_memory_list.addItem(placeholder)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        remove = button_role(QPushButton(), 'secondary')
        bind_text(remove, '删掉选中的')
        clear_memory = button_role(QPushButton(), 'secondary')
        bind_text(clear_memory, '清空兔白记的')
        actions.addWidget(remove)
        actions.addWidget(clear_memory)
        actions.addStretch(1)
        rows.addLayout(actions)
        # 2026-11-16: each project's chat stays on this computer and comes back with the project.
        self.bunny_keep_chat = toggle(values.get('keep_chat', True))
        bind_text(self.bunny_keep_chat, '每个工程的聊天留在这台电脑上', property='accessibleName')
        row(rows, '每个工程的聊天留在这台电脑上', self.bunny_keep_chat,
            '聊天保存在本机；最近几轮会和新问题一起发送给文字 AI。关闭记忆或此开关后不再保存和恢复')
        clear_chats = button_role(QPushButton(), 'secondary')
        bind_text(clear_chats, '清空保存的聊天')
        chats_line = QHBoxLayout()
        chats_line.addWidget(clear_chats)
        chats_line.addStretch(1)
        rows.addLayout(chats_line)
        self.bunny_clear_chats = clear_chats
        clear_chats.clicked.connect(lambda: (bunny_memory.clear_chats(), self.bunny_teach_status.setText(tr('保存的聊天清空了。'))))
        teach_title = QLabel()
        bind_text(teach_title, '教兔白一件事（知识库）')
        teach_title.setObjectName('settingsRowTitle')
        rows.addWidget(teach_title)
        self.bunny_teach = QPlainTextEdit()
        self.bunny_teach.setObjectName('bunnyTeach')
        self.bunny_teach.setFixedHeight(72)
        bind_text(self.bunny_teach, '例如：我的频道叫二字节，主播叫阿明，嘉宾叫小雨；字幕统一用黄色字黑色描边', property='placeholderText')
        rows.addWidget(self.bunny_teach)
        add = button_role(QPushButton(), 'primary')
        bind_text(add, '加进知识库')
        self.bunny_teach_status = QLabel()
        self.bunny_teach_status.setObjectName('settingsDescription')
        self.bunny_teach_status.setWordWrap(True)
        line = QHBoxLayout()
        line.addWidget(add)
        line.addWidget(self.bunny_teach_status, 1)
        rows.addLayout(line)

        def add_entry():
            try:
                bunny_memory.add(self.bunny_teach.toPlainText(), 'knowledge', source='user')
            except ValueError as exc:
                self.bunny_teach_status.setText(str(exc))
                return
            self.bunny_teach.clear()
            self.bunny_teach_status.setText(tr('加好了，兔白下次回答就会照着来。'))
            refresh()

        def remove_selected():
            for item in self.bunny_memory_list.selectedItems():
                bunny_memory.remove(item.data(Qt.ItemDataRole.UserRole))
            refresh()

        def clear_hers():
            bunny_memory.clear('memory')
            refresh()
        add.clicked.connect(add_entry)
        remove.clicked.connect(remove_selected)
        clear_memory.clicked.connect(clear_hers)
        self.bunny_memory_add, self.bunny_memory_remove, self.bunny_memory_clear = add, remove, clear_memory
        refresh()

    def _save_bunny_permissions(self):
        """「兔白权限」, when its page was opened (2026-11-15)."""
        level = self.__dict__.get('bunny_level')
        if level is None:
            return
        from . import bunny_permissions
        from .bunny_chat import REASONING_KEY
        from .onboarding import load_state, save_state
        bunny_permissions.save({'level': level.currentData(), 'read_subtitles': self.bunny_read_subtitles.isChecked(),
                                'read_diagnostics': self.bunny_read_diagnostics.isChecked(),
                                'allow_paid': self.bunny_allow_paid.isChecked(),
                                'remember': self.bunny_remember.isChecked(),
                                'keep_chat': self.bunny_keep_chat.isChecked(),
                                'see_screen': self.bunny_see_screen.isChecked(),
                                **({'files_anywhere': self.bunny_files_anywhere.isChecked()}
                                   if self.__dict__.get('bunny_files_anywhere') is not None else {})})
        from .bunny_tips import set_idle_allowed
        set_idle_allowed(self.bunny_idle_tips.isChecked())
        from .bunny_chat import set_click_lines
        set_click_lines(self.bunny_click_lines.isChecked())
        from . import bunny_events, bunny_resident
        hints = {'resident': self.bunny_resident.isChecked(), 'mode': self.bunny_hint_mode.currentData() or 'all'}
        if hints['resident'] and not bunny_events.load()['resident']:
            hints['quiet_day'] = ''                      # asked back: today's 「今天先别出来」 is over too
        bunny_events.save(hints)
        owner = self.parentWidget().window() if self.parentWidget() else None
        if owner is not None and bunny_resident.auto_start_allowed():
            bunny_resident.refresh(owner)
        reasoning = self.bunny_reasoning.currentData()
        if reasoning:
            save_state(dict(load_state(), **{REASONING_KEY: reasoning}))
        chat = getattr(self.parentWidget().window() if self.parentWidget() else None, '_bunny_chat', None)
        if chat is not None and reasoning:
            chat.reasoning = reasoning
            chat._sync_reasoning_button()

    def _repair_project_association(self):
        from PySide6.QtWidgets import QMessageBox
        from ..projects.project_file_association import repair_project_association
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
        from ..design.theme_manager import request_theme
        self._update_theme_hint()
        request_theme(str(key), QApplication.instance())

    def _update_theme_hint(self):
        from ..design.ui_theme import theme_definition
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
        app = QApplication.instance()
        app._theme_request_generation = getattr(app, '_theme_request_generation', 0) + 1
        if result != QDialog.DialogCode.Accepted and theme_key() != getattr(self, '_theme_on_open', theme_key()):
            from ..design.theme_manager import apply_theme
            apply_theme(self._theme_on_open, QApplication.instance())
        timer = self.__dict__.get('_mcp_timer')
        if timer is not None:
            timer.stop()
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
