"""Studio entry: freeze the existing full-frame route, then edit static assets."""
from pathlib import Path
import tempfile
import time

from PySide6.QtCore import QObject, QSettings
from PySide6.QtWidgets import QDialog, QFileDialog, QMenu, QToolButton

from .cover_document import CoverDocument
from .cover_editor import CoverEditor, CoverJob

from .i18n import bind_text

from .i18n import tr


class StudioCoverController(QObject):
    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.settings = QSettings('2ByteASR', '2ByteASR')
        self.editor = None
        self.local_editor = None
        self.editors = []
        self.busy = False
        self.last_receipt = None
        self._capture_generation = 0
        self._update_editor = None

    def show_editor(self, document=None, *, local=False):
        # Keep an edited cover intact when another screenshot or template opens.
        if self.editor is not None and document is None:
            self.editor.show()
            self.editor.raise_()
            self.editor.activateWindow()
            return self.editor
        editor = CoverEditor(document, self.page.window())
        self.editor = editor
        self.local_editor = editor
        self.editors.append(editor)
        update=editor.toolbar.addAction('使用 / 更新当前帧')
        update.triggered.connect(lambda:self.begin_frame_update(editor))
        editor.destroyed.connect(lambda:self._editor_closed(editor))
        editor.show()
        return editor

    def _editor_closed(self,editor):
        if editor in self.editors:self.editors.remove(editor)
        if self.editor is editor:self.editor=None
        if self.local_editor is editor:self.local_editor=None
        if self._update_editor is editor:self._update_editor=None

    def begin_frame_update(self, editor):
        self._update_editor=editor
        editor.hide()
        bind_text(self.page.save_state, '请定位新画面，再点“制作封面 → 当前截图”更新此封面的底图。')

    def new_cover(self):
        return self.show_editor(CoverDocument())

    def select_template(self):
        if self._update_editor is not None:
            self._update_editor.show()
            self._update_editor=None
        if getattr(self.page,'project',None) is not None and getattr(self.page.project,'media',None):
            return self.create(choose_template=True)
        return self._pick_template(None)

    def _pick_template(self, frame):
        from .cover_local_library import LocalCoverLibrary
        from .cover_templates_ui import TemplatePicker
        picker=TemplatePicker(LocalCoverLibrary(),self.settings,self.page,local=True,has_frame=frame is not None)
        if picker.exec()!=QDialog.Accepted:return
        editor=self.show_editor(frame if frame is not None else CoverDocument())
        if not picker.selected.get('blank'):
            editor.apply_template(picker.selected,replace=picker.replace.isChecked())

    def create(self, *, choose_template=False):
        if self.busy:
            bind_text(self.page.save_state, '正在准备已冻结的高清底图…')
            return
        if (self.page.project is None or not getattr(self.page.project, 'media', None)
                or not str(getattr(self.page.project.media, 'path', '')).strip()):
            bind_text(self.page.save_state, '当前没有可截图的视频；可选择“新建封面”或“选择模板”。')
            if choose_template:self._pick_template(None)
            return
        # Capture before opening any chooser or waiting for a video seek ACK.
        from .export_timeline import export_project_snapshot
        from .video_export import capture_video_graph
        started = time.perf_counter()
        project = export_project_snapshot(self.page.project)
        graph = capture_video_graph(self.page.project)
        milliseconds = int(self.page.timeline.playhead_ms)
        subtitles = str(self.settings.value('cover/subtitles', 'true')).lower() not in ('false', '0')
        self._capture_generation += 1
        generation=self._capture_generation
        project_id=project.project_id
        source_project=self.page.project
        target=self._update_editor if not choose_template else None
        document_id=target.session.document.id if target is not None else None
        source_path = str(getattr(self.page, 'project_path', '') or '')
        self.page.video.set_paused(True)
        self.busy = True
        bind_text(self.page.save_state, '正在制作封面：后台读取高清底图…')
        job = CoverJob(self)
        def work():
            from .frame_export import save_project_frame
            from .platform_media import ffmpeg_tool
            with tempfile.TemporaryDirectory(prefix='2byte-cover-frame-') as directory:
                receipt = save_project_frame(project, graph, milliseconds, directory, '封面底图',
                    subtitles=subtitles, require_video_frame=True,
                    ffmpeg=ffmpeg_tool(root=Path(__file__).resolve().parents[1]))
                data = Path(receipt['path']).read_bytes()
            document = CoverDocument(width=receipt['width'], height=receipt['height'])
            document.source = dict(project_id=project.project_id, project_path=source_path,
                                   milliseconds=milliseconds, subtitles=subtitles,
                                   captured_at=document.created_at, decode=receipt['decode'])
            document.add_image(data, '冻结当前帧.png', (document.width, document.height), background=True)
            return document, receipt
        def complete(result):
            self.busy = False
            job.deleteLater()
            document, receipt = result
            receipt['open_elapsed_seconds'] = time.perf_counter()-started
            self.last_receipt = receipt
            if generation!=self._capture_generation or self.page.project is not source_project:
                bind_text(self.page.save_state, '工程已切换，已丢弃旧取帧结果。')
                return
            if choose_template:
                self._pick_template(document)
            elif target is not None:
                if target not in self.editors or target.session.document.id!=document_id:
                    bind_text(self.page.save_state, '封面已关闭或切换，已丢弃旧取帧结果。')
                    return
                target.use_frozen_frame(document)
                target.show();target.raise_()
                self._update_editor=None
            else:
                self.show_editor(document)
            bind_text(self.page.save_state, '封面底图已冻结；字幕如已包含，则为图片像素。')
        def failed(message):
            self.busy = False
            job.deleteLater()
            if generation!=self._capture_generation or self.page.project is not source_project:return
            bind_text(self.page.save_state, '制作封面失败：{value0}；可重试或从本地图片新建。', value0=message)
            if target in self.editors:target.show()
            if choose_template:self._pick_template(None)
        job.finished.connect(complete)
        job.failed.connect(failed)
        job.start(work)

    def from_image(self):
        from .cover_render import image_filter,load_image_file
        path,_=QFileDialog.getOpenFileName(self.page,tr('从图片制作封面'),str(self.settings.value('cover/image_directory','')),image_filter())
        if not path:return
        try:
            data,image=load_image_file(path)
            document=CoverDocument(width=image.width(),height=image.height())
            document.add_image(data,Path(path).name,(image.width(),image.height()),background=True)
            self.show_editor(document)
        except (ValueError,OSError) as exc:bind_text(self.page.save_state, '读取封面底图失败：{value0}', value0=str(exc))

    def open_document(self):
        path, _ = QFileDialog.getOpenFileName(self.page, tr('打开封面工程'),
            str(self.settings.value('cover/project_directory', '')), '封面 (*.psd *.2bytecover)')
        if path:
            editor = self.new_cover()
            editor.open_document(path)


def install_cover_button(page, layout):
    controller = StudioCoverController(page)
    page.cover_controller = controller
    button = QToolButton()
    bind_text(button, '制作封面')
    bind_text(button, '本地封面编辑：当前截图、新建封面或选择模板', property='toolTip')
    button.setPopupMode(QToolButton.InstantPopup)
    menu = QMenu(button)
    menu.addAction('当前截图', controller.create)
    menu.addAction('新建封面', controller.new_cover)
    menu.addAction('选择模板', controller.select_template)
    button.setMenu(menu)
    layout.addWidget(button)
    page.make_cover_button = button
