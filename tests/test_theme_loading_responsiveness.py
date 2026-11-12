"""Ownership and stale-result regressions for the normal loading/theme paths."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
from PySide6.QtCore import QThread
from PySide6.QtGui import QFontDatabase, QFontInfo, QRawFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QStackedWidget, QVBoxLayout, QWidget


def app():
    return QApplication.instance() or QApplication([])


def test_loading_font_registered_once_and_real_glyphs(monkeypatch):
    application = app()
    from twobyteasr.design.loading_font import loading_font
    if hasattr(application, '_loading_status_font'):
        del application._loading_status_font
    original = QFontDatabase.addApplicationFont
    calls = []
    def add(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(QFontDatabase, 'addApplicationFont', add)
    first, second = loading_font(), loading_font()
    font_id, families, _ = application._loading_status_font
    assert len(calls) == 1 and font_id >= 0 and families
    assert first.family() == second.family() == families[0]
    assert 'Maoken' in families[0] or '猫啃' in families[0]
    assert QFontInfo(first).family() == families[0]
    raw = QRawFont.fromFont(first)
    # OS/2 Unicode-range flags under-report this font. Glyph IDs are the
    # actual shaping evidence, including Chinese, Latin and punctuation.
    assert all(raw.glyphIndexesForString('正在准备播放器ABC123，。！？'))


def test_missing_loading_font_keeps_readable_fallback_and_logs_once(monkeypatch, caplog):
    application = app()
    from twobyteasr.design.loading_font import loading_font
    monkeypatch.setattr(application, '_loading_status_font', None, raising=False)
    calls = []
    monkeypatch.setattr(QFontDatabase, 'addApplicationFont', lambda path: calls.append(path) or -1)
    first, second = loading_font(), loading_font()
    assert first.family() == second.family() == application.font().family()
    assert len(calls) == 1 and 'registration failed' in caplog.text


def test_latest_theme_request_wins_and_hidden_page_updates_before_paint(monkeypatch):
    application = app()
    from twobyteasr.design import theme_manager as themes
    from twobyteasr.design.theme_scopes import refresh
    window = QWidget()
    window.setObjectName('subtitleStudio')
    layout = QVBoxLayout(window)
    stack = QStackedWidget(window)
    layout.addWidget(stack)
    pages = []
    for index in range(2):
        page = QWidget()
        QVBoxLayout(page).addWidget(QLabel('Theme '+str(index)))
        stack.addWidget(page)
        pages.append(page)
    window.show()
    themes.apply_theme('sand')
    refresh(window)
    hidden = pages[1]
    calls = []
    original = themes.apply_theme
    def apply(key, target=None):
        calls.append(key)
        return original(key, target)
    monkeypatch.setattr(themes, 'apply_theme', apply)
    for key in ('grape', 'warm', 'graphite'):
        themes.request_theme(key)
    until = time.monotonic()+5
    while (themes.theme_key() != 'graphite' or getattr(application,'_theme_update_pending',False)) and time.monotonic()<until:
        QTest.qWait(10)
    assert calls == ['graphite']
    stack.setCurrentWidget(hidden)
    QTest.qWait(20)
    from PySide6.QtGui import QColor, QPalette
    assert hidden.findChild(QLabel).palette().color(QPalette.ColorRole.WindowText) == QColor(themes.theme_definition('graphite').text)
    window.close()


def test_stage_updates_keep_mascot_clock_and_surface():
    application = app()
    from twobyteasr.studio.studio_loading import StudioLoadingSession
    from twobyteasr.studio.loading_faces import STAGE_LINES, READY_LINE
    host = QWidget()
    session = StudioLoadingSession(host)
    mascot = session.view.perch
    clock = mascot._started
    session.view.set_mode(library=False, path='sample.2byteproj')
    for stage in ('读取工程','准备播放器','准备音频','准备字幕','首屏绘制'):
        session.view.show_progress(set(), stage)
        assert session.view.cover.line == STAGE_LINES[stage]
        assert session.view.perch is mascot and mascot._started == clock
    assert STAGE_LINES['准备播放器'] == '正在准备播放器'
    assert READY_LINE == '准备好了'
    session.view.show_progress(set(), '', failed='读取工程', error='工程文件不存在')
    assert session.view.cover.line == '工程文件不存在'
    host.close()


def test_scaled_mascot_resources_publish_on_gui_and_are_bounded():
    application = app()
    from twobyteasr.design.mascot_assets import provider, MAX_BYTES
    assets = provider()
    threads = []
    assets.ready.connect(lambda key: threads.append(QThread.currentThread()))
    key = assets.request(151, 1.5)
    until = time.monotonic()+5
    while key not in assets.cache and time.monotonic()<until:
        time.sleep(.005)  # Release the GIL for the Python decoder worker.
        QTest.qWait(10)
    assert key in assets.cache
    assert threads and all(thread is application.thread() for thread in threads)
    assert assets.bytes <= MAX_BYTES and len(assets.cache) <= 4
    images, offsets, size = assets.cache[key]
    assert images and set(images) == set(offsets) and size < 2 * 1024 * 1024


def test_late_library_style_target_is_themed_before_first_paint():
    from PySide6.QtGui import QColor, QPalette
    from twobyteasr.design.theme_manager import apply_theme, theme_definition
    application = app()
    window = QWidget()
    window.setObjectName('subtitleStudio')
    layout = QVBoxLayout(window)
    scope = QWidget()
    body = QVBoxLayout(scope)
    body.addWidget(QLabel('existing'))
    layout.addWidget(scope)
    window.show()
    apply_theme('graphite')
    QTest.qWait(10)
    added = QLabel('late library metadata')
    added.setObjectName('muted')
    body.addWidget(added)
    added.show()
    QTest.qWait(20)
    assert added.palette().color(QPalette.ColorRole.WindowText) == QColor(theme_definition('graphite').text_muted)
    window.close()


def test_media_probe_reuses_only_a_current_independent_caption_index(monkeypatch):
    app()
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
    from twobyteasr.projects.studio_runtime_state import state_for
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions
    project = SubtitleProject(StudioMedia(''), cues=[StudioCue('one',0,1000,'测试字幕')])
    ensure_independent_captions(project)
    timeline = WaveformTimeline()
    timeline.set_project(project)
    state = state_for(project)
    before = (id(project.cues), state.language_source_revision)
    original = timeline._rebuild_cue_index
    calls = []
    monkeypatch.setattr(timeline, '_rebuild_cue_index', lambda: calls.append(True) or original())
    state.language_source_revision += 1  # A linked media-sequence update.
    timeline.refresh_media_graph(unchanged_caption_token=before)
    assert not calls and timeline._timeline_cue_by_id['one'] is project.cues[0]
    # An edit already pending before the probe must not reuse that old index.
    state.language_source_revision += 1
    timeline.refresh_media_graph(unchanged_caption_token=(id(project.cues),state.language_source_revision))
    assert calls == [True]
    timeline.close()


def test_show_translation_skips_hidden_pages_but_explicit_language_change_keeps_them():
    app()
    from twobyteasr.i18n_widgets import apply
    from twobyteasr.i18n import translate
    root = QWidget()
    layout = QVBoxLayout(root)
    stack = QStackedWidget()
    layout.addWidget(stack)
    labels = []
    for _ in range(2):
        page = QWidget()
        label = QLabel('返回主页')
        QVBoxLayout(page).addWidget(label)
        stack.addWidget(page)
        labels.append(label)
    root.show()
    apply(root, 'en', visible_only=True)
    assert labels[0].text() == translate('返回主页','en')
    assert labels[1].text() == '返回主页'
    apply(root, 'en')
    assert labels[1].text() == translate('返回主页','en')
    root.close()


def test_studio_theme_geometry_keeps_existing_application_zoom_exclusion(monkeypatch):
    import re
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.design.theme_manager import apply_theme
    from twobyteasr.app import ui_zoom
    application = app()
    root = QWidget()
    root.setObjectName('subtitleStudio')
    button = QPushButton('Preview')
    button.setObjectName('studioTool')
    QVBoxLayout(root).addWidget(button)
    root.show()
    apply_theme('sand')
    lengths = re.findall(r'\b[\d.]+px', button.styleSheet())
    size = button.font().pixelSize()
    monkeypatch.setattr(ui_zoom, 'zoom_percent', lambda: 120)
    apply_theme('graphite')
    assert re.findall(r'\b[\d.]+px', button.styleSheet()) == lengths
    assert button.font().pixelSize() == size
    root.close()


def test_source_monitor_cooperative_build_keeps_synchronous_controls_and_ownership():
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.studio.studio_source_monitor import StudioSourceMonitor
    app()
    page = QWidget()
    page.project = None
    normal = StudioSourceMonitor(page, parent=page)
    deferred = StudioSourceMonitor(page, parent=page, deferred_build=True)
    assert not hasattr(deferred, 'surface')
    list(deferred.build_steps())
    assert deferred.parentWidget() is page and deferred._control_steps is None
    for name in ('title','stream','video_target','audio_target','insert_button','surface'):
        assert hasattr(normal, name) and hasattr(deferred, name)
    assert normal.insert_button.text() == deferred.insert_button.text()
    assert len(normal.findChildren(QPushButton)) == len(deferred.findChildren(QPushButton))
    assert normal.controller is deferred.controller is None
    normal.reset()
    deferred.reset()
    page.deleteLater()
