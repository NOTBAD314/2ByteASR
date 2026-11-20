"""Opening a project keeps disk scans, noise fields and repeated full timeline
redraws off the GUI thread (2026-11-19, user: opening a project in the
workbench froze it; GUI stalls of 0.5-3 s while a long recording opened)."""
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


def _app():
    return QApplication.instance() or QApplication([])


def test_highlight_panel_never_searches_skill_folders_on_its_own_thread(monkeypatch):
    _app()
    from twobyteasr.studio import studio_highlight_analyzer as analyzer
    from twobyteasr.studio.studio_highlight_ui import HighlightAssistantPanel

    gui = threading.get_ident()
    searched_on = []
    release = threading.Event()

    def slow_discover(cls, roots=None):
        searched_on.append(threading.get_ident())
        release.wait(5)
        found = cls(path='x', prompt='p', found=True)
        if roots is None:
            analyzer._remember_skill(found)
        return found

    monkeypatch.setattr(analyzer.HighlightSkillAdapter, 'discover', classmethod(slow_discover))
    monkeypatch.setitem(analyzer._SKILL_STATE, 'adapter', None)
    monkeypatch.setitem(analyzer._SKILL_STATE, 'at', 0.0)
    started = time.perf_counter()
    panel = HighlightAssistantPanel()
    panel._refresh_skill()
    panel._refresh_skill()
    assert time.perf_counter() - started < 2.0
    assert gui not in searched_on
    assert '内置规则' in panel.skill_label.text() or 'built-in' in panel.skill_label.text().lower()
    release.set()
    deadline = time.monotonic() + 5
    while panel._skill_search_pending and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert len(searched_on) == 1  # concurrent requests share one search
    assert analyzer.cached_skill_adapter().found
    assert '本地切片规则' in panel.skill_label.text() or 'rules found' in panel.skill_label.text().lower()
    # A later project opening reads the remembered answer and starts no search.
    panel._refresh_skill()
    assert len(searched_on) == 1 and not panel._skill_search_pending
    panel.close()


def test_explicit_roots_do_not_replace_the_remembered_default_search(tmp_path, monkeypatch):
    from twobyteasr.studio import studio_highlight_analyzer as analyzer
    remembered = analyzer.HighlightSkillAdapter(path='keep', prompt='p', found=True)
    monkeypatch.setitem(analyzer._SKILL_STATE, 'adapter', remembered)
    monkeypatch.setitem(analyzer._SKILL_STATE, 'at', time.monotonic())
    assert not analyzer.HighlightSkillAdapter.discover([tmp_path]).found
    assert analyzer.cached_skill_adapter() is remembered


def test_repeated_waveform_refinements_redraw_the_timeline_once_per_interval(monkeypatch):
    app = _app()
    from twobyteasr.studio import studio_timeline
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    timeline = WaveformTimeline()
    timeline.thumbnail_requests_enabled = False
    timeline.resize(900, 300)
    timeline.show()
    app.processEvents()
    timeline.grab()
    renders = []
    original = timeline._render_static
    monkeypatch.setattr(timeline, '_render_static', lambda *a, **k: (renders.append(1), original(*a, **k)))
    timeline.set_waveform_state('LOADING', 'decoding 1%')  # a new state redraws at once
    timeline.grab()
    assert len(renders) == 1
    for percent in range(2, 30):  # the loading text counting up is a refinement
        timeline.set_waveform_state('LOADING', f'decoding {percent}%')
        timeline.grab()
    assert len(renders) == 1
    assert timeline._refinement_throttle_timer.isActive()
    deadline = time.monotonic() + 3
    while timeline._refinement_throttle_timer.isActive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    timeline.grab()
    assert len(renders) == 2 and timeline.waveform_message == 'decoding 29%'
    timeline.set_waveform_state('READY')  # finishing is a new state again
    timeline.grab()
    assert len(renders) == 3
    # An expensive picture waits proportionally longer before the next refinement.
    timeline._static_render_seconds = 0.5
    timeline._static_rendered_at = time.perf_counter()
    assert timeline._throttle_refinement()
    assert timeline._refinement_throttle_timer.remainingTime() > studio_timeline.REFINEMENT_MIN_INTERVAL_S * 1000
    timeline.close()


def test_resting_ink_wash_is_built_once_per_size_and_colour(monkeypatch):
    _app()
    from twobyteasr.design import ink_wash
    ink_wash._REST_CACHE.clear()
    built = []
    original = ink_wash._wash_image
    monkeypatch.setattr(ink_wash, '_wash_image', lambda *a, **k: (built.append(1), original(*a, **k))[1])
    color = [QColor('#d04040')]
    first = ink_wash.wash_image(220, 38, color, level=1.0, t=0.0, seed=11.0, hover=(-99, -99, 0.0), ripples=[])
    again = ink_wash.wash_image(220, 38, [QColor('#d04040')], level=1.0, t=0.0, seed=11.0,
                                hover=(-99, -99, 0.0), ripples=[])
    assert again is first and len(built) == 1
    ink_wash.wash_image(240, 38, color, level=1.0, t=0.0, seed=11.0, hover=(-99, -99, 0.0), ripples=[])
    ink_wash.wash_image(220, 38, [QColor('#40d040')], level=1.0, t=0.0, seed=11.0, hover=(-99, -99, 0.0), ripples=[])
    assert len(built) == 3
    # A live wash (pointer over it, ripples) is drawn fresh every frame.
    ink_wash.wash_image(220, 38, color, level=1.0, t=0.0, seed=11.0, hover=(30, 10, 0.8), ripples=[])
    ink_wash.wash_image(220, 38, color, level=1.0, t=0.0, seed=11.0, hover=(-99, -99, 0.0), ripples=[(5, 5, 0.1)])
    assert len(built) == 5


def test_theme_key_reuses_one_read_but_a_saved_theme_is_seen_at_once(tmp_path, monkeypatch):
    _app()
    from twobyteasr.design import theme_manager
    reads = []
    ini = str(tmp_path / 'theme.ini')

    def settings():
        reads.append(1)
        return QSettings(ini, QSettings.Format.IniFormat)

    monkeypatch.setattr(theme_manager, '_settings', settings)
    theme_manager.save_theme_key('grape')
    reads.clear()
    for _ in range(20):
        assert theme_manager.theme_key() == 'grape'
    assert len(reads) == 1
    theme_manager.save_theme_key('sand')
    assert theme_manager.theme_key() == 'sand'
    other = tmp_path / 'other.ini'
    monkeypatch.setattr(theme_manager, '_settings', lambda: QSettings(str(other), QSettings.Format.IniFormat))
    assert theme_manager.theme_key() == theme_manager.DEFAULT_THEME_KEY  # a replaced store is read anew


def test_audio_only_sources_get_no_ffmpeg_cover_attempt(tmp_path, monkeypatch):
    from twobyteasr.projects import studio_project_controller as module
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
    media = tmp_path / 'stream.m4a'
    media.write_bytes(b'audio')
    project = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=60_000))
    calls = []
    monkeypatch.setattr(module, 'run_hidden_subprocess', lambda *a, **k: calls.append(a))
    ffmpeg = Path(module.__file__).resolve().parents[2] / 'tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'
    controller = module.StudioProjectController.__new__(module.StudioProjectController)
    assert controller._ensure_project_cover(tmp_path / 'p.2byteproj', project) is None
    assert calls == []
    # A video container whose probe found no picture is remembered after one try.
    video = tmp_path / 'radio.mp4'
    video.write_bytes(b'no picture')
    project.media.path = str(video)
    if not ffmpeg.is_file():
        return
    monkeypatch.setattr(module, 'run_hidden_subprocess', lambda *a, **k: (calls.append(a), SimpleNamespace(
        returncode=-22, stderr='[out#0/image2] Output file does not contain any stream'))[1])
    for _ in range(3):
        assert controller._ensure_project_cover(tmp_path / 'p.2byteproj', project) is None
    assert len(calls) == 1


def test_collapsed_font_field_reads_installed_fonts_on_a_worker(monkeypatch):
    _app()
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QFont, QImage, QPainter
    from twobyteasr.caption_style import font_metadata
    from twobyteasr.caption_style.font_picker_preview import FontPreviewRequest, draw_font_preview
    warmed = []
    monkeypatch.setattr(font_metadata, 'local_faces_ready', lambda: False)
    monkeypatch.setattr(font_metadata, 'warm_local_faces', lambda: warmed.append(threading.get_ident()))
    image = QImage(300, 40, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        state = draw_font_preview(painter, QRectF(0, 0, 300, 40), 'Arial', FontPreviewRequest('Arial'), QFont(),
                                  QColor('#000000'), name_first=True, defer_metadata=True)
    finally:
        painter.end()
    assert state['loading'] and warmed


def test_full_cue_list_does_not_compute_every_status(monkeypatch):
    _app()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
    from twobyteasr.studio import studio_cue_table
    project = SubtitleProject(media=StudioMedia(path=''), cues=[
        StudioCue(id=f'c{i}', start_ms=i * 1000, end_ms=i * 1000 + 800, text=f'第{i}句') for i in range(50)])
    counted = []
    original = studio_cue_table._cue_status
    monkeypatch.setattr(studio_cue_table, '_cue_status', lambda *a, **k: (counted.append(1), original(*a, **k))[1])
    model = studio_cue_table.CueTableModel()
    model.set_project(project)
    assert model.rowCount() == 50 and counted == []
    model.set_filter('pending')
    assert len(counted) == 50


def test_visible_timeline_is_painted_without_relaying_out_the_window():
    """grab() of a visible widget re-ran the whole window's layout, other
    hidden pages included; a visible timeline paints itself instead."""
    from types import SimpleNamespace as NS
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QWidget
    from twobyteasr.studio.studio_readiness import StudioReadiness
    app = _app()
    timeline = QWidget()
    timeline.resize(640, 180)
    timeline.show()
    app.processEvents()
    failures = []
    gate = NS(page=NS(timeline=timeline), painted=False, generation=1, profile={},
              _owns_request=lambda epoch: epoch == 1, fail=lambda *a: failures.append(a))

    class PaintObserver(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Paint:
                gate.painted = True
            return False
    observer = PaintObserver(timeline)
    timeline.installEventFilter(observer)
    grabbed = []
    timeline.grab = lambda *a: grabbed.append(a)
    try:
        assert StudioReadiness._prepare_timeline_surface(gate)
        assert gate.painted and not grabbed and not failures
        assert gate.profile['timeline_prepared_hidden'] is False
    finally:
        timeline.close()
        timeline.deleteLater()

def test_covered_timeline_is_prepared_off_screen_instead_of_grabbed():
    """While the loading transition holds updates, repaint() paints nothing;
    the timeline then builds its picture off-screen, never via grab()."""
    from types import SimpleNamespace as NS
    from twobyteasr.studio.studio_readiness import StudioReadiness
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
    app = _app()
    timeline = WaveformTimeline()
    timeline.thumbnail_requests_enabled = False
    timeline.resize(900, 300)
    timeline.set_project(SubtitleProject(media=StudioMedia(path='', duration_ms=60_000),
                                         cues=[StudioCue('a', 0, 1000, 'x')]))
    timeline.show()
    app.processEvents()
    timeline._static_timeline_dirty = True
    grabbed = []
    timeline.grab = lambda *a: grabbed.append(a)
    timeline.repaint = lambda *a: None  # a repaint Qt does not deliver
    failures = []
    gate = NS(page=NS(timeline=timeline), painted=False, generation=1, profile={},
              _owns_request=lambda epoch: epoch == 1, fail=lambda *a: failures.append(a))
    try:
        assert StudioReadiness._prepare_timeline_surface(gate)
        assert gate.painted and not grabbed and not failures
        assert gate.profile['timeline_prepared_offscreen']
        assert not timeline._static_timeline_dirty and timeline._static_timeline_cache is not None
    finally:
        timeline.close()


def test_hidden_workshop_page_does_not_lay_out_its_cards():
    """Any grab() flushes posted layout requests of hidden pages too; the
    workshop's card list waits until the page shows."""
    from PySide6.QtWidgets import QLabel
    app = _app()
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage
    page = ModelWorkshopPage(Path(__file__).parents[1], {'models': {}})
    page.resize(1000, 700)
    try:
        assert not page.card_layout.isEnabled()
        page.show()
        app.processEvents()
        assert page.card_layout.isEnabled()
        page.hide()
        assert not page.card_layout.isEnabled()
        probe = QLabel('x')
        probe.show()
        later = QLabel('later')
        page.card_layout.insertWidget(1, later)
        probe.grab()  # must not lay out the hidden list
        assert not page.card_layout.isEnabled() and later.geometry().y() == 0
        page.show()
        app.processEvents()
        assert page.card_layout.isEnabled()
        assert later.geometry().y() > 0 and later.geometry().width() == page.list_header.width()
        probe.close()
    finally:
        page.close()
        page.deleteLater()