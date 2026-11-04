"""User workflow regressions: projected selection and repeated library entry."""
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QPlainTextEdit
from PySide6.QtGui import QImage
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.timeline.studio_edit_sequence import sequence_of, projected_cues
from twobyteasr.studio.studio_ai_flow import StudioAIFlowMixin
from twobyteasr.studio.studio_hub import StudioHubMixin

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

def design_page(project):
    class Page(StudioAIFlowMixin):
        def _ai_start_feedback(self, context, status, message):
            self.feedback = status, message
        def _launch_ai_suggestion(self, **kwargs):
            self.launches.append(kwargs)
    p = Page()
    p.project = project
    p.session = SimpleNamespace(generation=3)
    p.selected_cue_id = projected_cues(project)[0].id
    p._ai_request_active = False
    p.launches = []
    p._ai_needs_key = lambda settings: False   # a configured design service (no-key note, 2026-10-15)
    return p

def edited_project():
    p = SubtitleProject(media=StudioMedia(path='source.mp4', duration_ms=20000),
        cues=[StudioCue('spoken', 10000, 12000, '这里是万物伊始和终')])
    p.validate()
    seg = sequence_of(p).segments[0]
    seg.source_in_ms, seg.timeline_out_ms = 5000, 15000
    return p

def test_projected_selection_launches_without_mutating_canonical(app):
    project = edited_project()
    p = design_page(project)
    assert '#' in p.selected_cue_id
    p._request_ai_suggestion()
    app.processEvents()
    assert p.launches, p.feedback
    assert project.cues[0].start_ms == 10000

def test_click_snapshot_rejects_edit_before_preparation(app):
    p = design_page(edited_project())
    p._request_ai_suggestion()
    p.project.cues[0].text = '已被编辑'
    app.processEvents()
    assert not p.launches
    assert '改变' in p.feedback[1]

def test_library_second_entry_uses_decoded_cover(app, tmp_path):
    path = tmp_path / '中文 封面.png'
    image = QImage(120, 60, QImage.Format.Format_RGB32)
    image.fill(0xffe34020)
    assert image.save(str(path))
    p = StudioHubMixin()
    p._library_cover_labels = {}
    first = QLabel()
    record = {'cover_path': str(path)}
    p._enqueue_library_cover(record, 100, 60, first)
    p._on_library_cover_ready(str(path), 100, 60, image)
    assert first.pixmap() and not first.pixmap().isNull()
    p._library_cover_labels = {}  # production rebuild destroys prior labels
    second = QLabel()
    p._enqueue_library_cover(record, 100, 60, second)
    assert second.pixmap() and not second.pixmap().isNull()

def test_relative_cover_resolves_against_project_not_cwd(app, tmp_path):
    folder = tmp_path / '工程 中文'
    folder.mkdir()
    path = folder / 'custom.png'
    image = QImage(120,60,QImage.Format.Format_RGB32)
    image.fill(0xffaabbcc)
    image.save(str(path))
    p = StudioHubMixin()
    p._library_cover_labels = {}
    label = QLabel()
    p._enqueue_library_cover({'path':str(folder/'项目.2byteproj'),'cover_path':'custom.png'},100,60,label)
    assert not p._library_cover_queue.empty()

def test_replaced_cover_rejects_old_inflight_pixels(app,tmp_path):
    path=tmp_path/'cover.png'
    image=QImage(20,20,QImage.Format.Format_RGB32);image.fill(0xffff0000);image.save(str(path))
    stat=path.stat();image.setText('source_stamp',f'{stat.st_mtime_ns}:{stat.st_size}')
    p=StudioHubMixin();p._library_cover_labels={};label=QLabel()
    p._enqueue_library_cover({'cover_path':str(path)},20,20,label)
    p._library_cover_queue.get()
    other=QImage(30,30,QImage.Format.Format_RGB32);other.fill(0xff00ff00);other.save(str(path))
    p._on_library_cover_ready(str(path),20,20,image)
    assert not getattr(p,'_library_cover_images',{})
    assert not p._library_cover_queue.empty()
