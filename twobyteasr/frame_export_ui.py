from pathlib import Path
import threading
from PySide6.QtCore import QObject,Signal,QSettings,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog,QToolButton,QMenu

from .i18n import bind_text

from .i18n import tr


class FrameCaptureController(QObject):
    completed=Signal(object)
    failed=Signal(str)

    def __init__(self,page):
        super().__init__(page);self.page=page;self.busy=False;self.last=None
        self.settings=QSettings('2ByteASR','2ByteASR')
        self.completed.connect(self._completed);self.failed.connect(self._failed)

    def choose_directory(self):
        directory=QFileDialog.getExistingDirectory(self.page,tr('选择保存当前帧的目录'),str(self.settings.value('frame_export/directory','')))
        if directory:self.settings.setValue('frame_export/directory',directory)
        return directory

    def save(self):
        if self.busy:
            bind_text(self.page.save_state, '正在保存已捕获的帧，请稍候。');return
        p=self.page.project
        if p is None:return
        # Freeze before any directory dialog: continuing playback cannot change
        # what this click requested, even on the first use.
        from .export_timeline import export_project_snapshot
        from .video_export import capture_video_graph
        project=export_project_snapshot(p);graph=capture_video_graph(p)
        milliseconds=int(self.page.timeline.playhead_ms)
        directory=str(self.settings.value('frame_export/directory',''))
        if not directory or not Path(directory).is_dir():
            if directory:bind_text(self.page.save_state, '原保存帧目录不可用，请重新选择。')
            directory=self.choose_directory()
        if not directory:return
        subtitles=str(self.settings.value('frame_export/subtitles','true')).lower() not in {'false','0'}
        extension=str(self.settings.value('frame_export/format','png'))
        name=p.studio_state.get('project_name') or Path(str(getattr(self.page,'project_path','') or p.media.path)).stem
        from .platform_media import ffmpeg_tool
        ffmpeg=ffmpeg_tool(root=Path(__file__).resolve().parents[1])
        self.busy=True;bind_text(self.page.save_state, '正在后台保存当前帧…')
        def work():
            try:
                from .frame_export import save_project_frame
                self.completed.emit(save_project_frame(project,graph,milliseconds,directory,name,
                    subtitles=subtitles,extension=extension,ffmpeg=ffmpeg))
            except RuntimeError as exc:
                if 'deleted' not in str(exc):self.failed.emit(str(exc))
            except Exception as exc:
                try:self.failed.emit(str(exc))
                except RuntimeError:pass  # Window may have closed during decoding.
        threading.Thread(target=work,name='save-project-frame',daemon=True).start()

    def _completed(self,receipt):
        self.busy=False;self.last=receipt
        bind_text(self.page.save_state, '已保存帧：{value0}（菜单可打开）', value0=Path(receipt['path']).name)

    def _failed(self,error):
        self.busy=False
        bind_text(self.page.save_state, '保存帧失败：{value0}；可在保存帧菜单更换目录。', value0=error)

    def open_last(self,folder=False):
        if self.last:
            path=Path(self.last['path'])
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if folder else path)))


def install_frame_button(page,layout):
    controller=FrameCaptureController(page);page.frame_capture=controller
    button=QToolButton();bind_text(button, '保存当前帧');bind_text(button, '保存工程画布原分辨率图片（Ctrl+Alt+F）', property='toolTip')
    button.setPopupMode(QToolButton.MenuButtonPopup);button.clicked.connect(controller.save)
    menu=QMenu(button)
    subtitles=menu.addAction('包含软件字幕');subtitles.setCheckable(True)
    subtitles.setChecked(str(controller.settings.value('frame_export/subtitles','true')).lower() not in {'false','0'})
    subtitles.toggled.connect(lambda value:controller.settings.setValue('frame_export/subtitles',value))
    jpeg=menu.addAction('保存为 JPEG（默认 PNG）');jpeg.setCheckable(True)
    jpeg.setChecked(controller.settings.value('frame_export/format','png')=='jpg')
    jpeg.toggled.connect(lambda value:controller.settings.setValue('frame_export/format','jpg' if value else 'png'))
    menu.addAction('更改保存帧目录…',controller.choose_directory)
    menu.addSeparator();menu.addAction('打开最近保存的图片',controller.open_last)
    menu.addAction('打开所在文件夹',lambda:controller.open_last(True))
    button.setMenu(menu);layout.addWidget(button);page.save_frame_button=button
