"""兔白 on the recognition progress page, the finished page, AI proofreading and the video export (2026-11-27).

User (2026-11-27): while recognising, give her more scenes and moves so there is something to
watch; the same on the result page, the AI glossary proofreading and the video export; she should
report the progress on her own, suggest what to do next and hop over there to play.
"""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _until(app, condition, seconds=6.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return condition()


class _Preview:
    def __init__(self):
        self.lines = []

    def rows(self):
        return [('00:01', text, '', '') for text in self.lines]


@pytest.fixture
def window(app, monkeypatch):
    """Home, the progress page and the result page, with the parts she uses on them."""
    from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QPushButton, QStackedWidget, QWidget
    from twobyteasr.app import bunny_chat, bunny_errands, bunny_puck, bunny_scenes
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'DeepSeek · deepseek-chat'))
    monkeypatch.setattr(bunny_puck, 'REST_BEFORE_HOME_MS', 50)
    monkeypatch.setattr(bunny_puck, 'SETTLE_MS', 60)
    monkeypatch.setattr(bunny_errands, 'PACE', 0.05)
    monkeypatch.setattr(bunny_scenes, 'EVENT_GAP_S', 0.0)
    win = QWidget()
    win.resize(1200, 800)
    win.pages = QStackedWidget(win)
    win.pages.setGeometry(0, 0, 1200, 800)
    win.settings_scroll = QWidget()
    win.start_button = QPushButton('开始生成字幕', win.settings_scroll)
    win.start_button.setGeometry(700, 640, 200, 44)
    progress = QWidget()
    win.progress_percent = QLabel('0%', progress)
    win.progress_stage = QLabel('正在准备任务', progress)
    win.stage_elapsed = QLabel('00:00', progress)
    win.progress_bar = QProgressBar(progress)
    win.progress_bar.setGeometry(40, 220, 1100, 14)
    win.progress_bar.setRange(0, 100)
    win.progress_bar.setTextVisible(False)
    win.phase_cards = []
    for index in range(4):
        card = QFrame(progress)
        card.setGeometry(40 + index * 280, 260, 260, 70)
        win.phase_cards.append(card)
    win.current_stage_card = QFrame(progress)
    win.current_stage_card.setGeometry(40, 380, 460, 130)
    win.recognition_preview = _Preview()
    cancel = QPushButton('安全取消', progress)
    cancel.setObjectName('danger')
    cancel.setGeometry(1000, 700, 90, 30)
    win.cancel_run_button = cancel
    result = QWidget()
    win.result_title = QLabel('字幕已生成', result)
    win.result_summary = QLabel('', result)
    names = ('result_ai_card', 'open_studio_result_button', 'export_result_button', 'result_return_button')
    for index, name in enumerate(names):
        card = QPushButton(name, result)
        card.setGeometry(90 + index * 280, 360, 260, 200)
        setattr(win, name, card)
    for page in (win.settings_scroll, progress, result):
        win.pages.addWidget(page)
    win.show()
    app.processEvents()
    yield win
    chat = getattr(win, '_bunny_chat', None)
    if chat is not None:
        chat.close_chat()
    win.close()
    win.deleteLater()
    app.processEvents()


def _folded(win):
    from twobyteasr.app import bunny_chat
    chat = bunny_chat.show_bunny(win)
    if chat is None:
        pytest.skip('no mascot pictures in this build')
    assert chat.collapsed
    return chat


def test_how_far_and_how_long_left_read_from_the_page():
    from twobyteasr.app.bunny_scenes import eta_words, percent_of, seconds_of
    assert percent_of('45%') == 45 and percent_of('已完成 100 %') == 100 and percent_of('') is None
    assert seconds_of('03:20') == 200 and seconds_of('已用时 1:02:03') == 3723 and seconds_of('—') is None
    assert eta_words(60, 25) == '大约 3 分钟' and eta_words(10, 50) == '' and eta_words(600, 2) == ''
    assert eta_words(90, 90) == '不到一分钟' and eta_words(7200, 50).endswith('小时')


def test_on_the_progress_page_she_reports_milestones_phases_and_what_she_heard(app, window, monkeypatch):
    from twobyteasr.app import bunny_scenes
    window.pages.setCurrentIndex(1)
    chat = _folded(window)
    errands = chat.errands
    assert errands.context() == 'progress'
    bubble = lambda: chat.puck.carrier.bubble     # noqa: E731
    errands.scene_report('progress')
    assert bubble().isVisible() and '陪你' in bubble().text or '告诉你' in bubble().text
    errands.scene_report('progress')               # nothing new: quiet
    window.progress_percent.setText('26%')
    window.stage_elapsed.setText('01:00')
    errands.scene_report('progress')
    assert '26%' in bubble().text and '大约 3 分钟' in bubble().text, bubble().text
    window.progress_stage.setText('字幕校对')
    errands.scene_report('progress')
    window.progress_stage.setText('全文断句')
    errands.scene_report('progress')
    assert '全文断句' in bubble().text
    window.recognition_preview.lines = ['大家好欢迎来到今天的直播']
    monkeypatch.setattr(bunny_scenes, 'REPORT_GAP_S', 0.0)
    monkeypatch.setattr(bunny_scenes.random, 'random', lambda: 0.0)
    errands.scene_report('progress')
    assert '刚刚听到' in bubble().text and '大家好' in bubble().text


def test_she_rides_the_progress_bar_and_hops_on_as_it_grows(app, window):
    window.pages.setCurrentIndex(1)
    window.progress_percent.setText('20%')
    window.progress_bar.setValue(20)
    chat = _folded(window)
    errands, puck, mascot = chat.errands, chat.puck, chat.mascot
    found = dict(errands.candidates())
    assert 'ride_bar' in found and 'watch_log' in found
    assert window.cancel_run_button not in errands._buttons(), 'never plays with 安全取消'
    assert errands.start('ride_bar', found['ride_bar'])
    assert _until(app, lambda: mascot.current_move == 'sit', seconds=4)
    from twobyteasr.app.bunny_errands import SEAT
    seat = puck.window_point(SEAT)
    bar = window.progress_bar.geometry()
    assert abs(seat.y() - bar.top()) < 12 and abs(seat.x() - (bar.left() + bar.width() * .2)) < 40, (seat, bar)
    window.progress_percent.setText('70%')
    window.progress_bar.setValue(70)
    assert _until(app, lambda: puck.window_point(SEAT).x() > seat.x() + 300, seconds=4), 'she hops on along it'
    assert _until(app, lambda: not errands.busy(), seconds=6)


def test_on_the_finished_page_she_cheers_then_knocks_on_what_to_do_next(app, window):
    window.pages.setCurrentIndex(2)
    chat = _folded(window)
    errands = chat.errands
    assert errands.context() == 'result'
    errands.scene_report('result')
    bubble = chat.puck.carrier.bubble
    assert '字幕已生成' in bubble.text
    card, words = errands._suggestion('result')
    assert card is window.result_ai_card and 'AI 词库校对' in words
    window.result_ai_card.setEnabled(False)                   # no AI set up: the studio comes first
    picks = {errands._suggestion('result')[0] for _ in range(30)}
    assert window.result_ai_card not in picks and window.open_studio_result_button in picks
    found = dict(errands.candidates())
    assert 'suggest' in found and 'card_hop' in found
    target = (window.open_studio_result_button, '打开「字幕工作台」看看吧')
    assert errands.start('suggest', target)
    assert _until(app, lambda: errands.fx.moving(window.open_studio_result_button), seconds=4), 'the card gives under her'
    assert _until(app, lambda: '字幕工作台' in bubble.text, seconds=4)
    assert _until(app, lambda: not errands.busy(), seconds=8)


def test_on_home_after_a_quiet_while_she_points_at_the_next_step(app, window, monkeypatch):
    chat = _folded(window)
    errands = chat.errands
    button, words = errands._suggestion('home')
    assert button is window.start_button and '开始生成字幕' in words
    errands.input_at = time.monotonic() - 999
    assert 'suggest' in dict(errands.candidates())
    errands.input_at = time.monotonic()
    assert 'suggest' not in dict(errands.candidates()), 'not while they are busy themselves'


def test_in_ai_proofreading_she_points_at_what_to_press_and_reports_the_run(app, window):
    from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QWidget
    page = QWidget()
    page.ai_button = QPushButton('AI 校对', page)
    page.ai_button.setGeometry(600, 160, 100, 32)
    page.batch_adopt = QPushButton('采用所选', page)
    page.batch_adopt.setGeometry(1000, 700, 100, 32)
    page.batch_adopt.setEnabled(False)
    page.cancel_button = QPushButton('取消', page)
    page.cancel_button.setGeometry(720, 160, 80, 32)
    page.cancel_button.hide()
    page.ai_progress_bar = QProgressBar(page)
    page.ai_progress_bar.setGeometry(200, 240, 800, 10)
    page.ai_progress_bar.hide()
    page.count_label = QLabel('找到 12 处', page)
    window.glossary_proofread_page = page
    window.pages.addWidget(page)
    window.pages.setCurrentWidget(page)
    chat = _folded(window)
    errands, bubble = chat.errands, lambda: chat.puck.carrier.bubble    # noqa: E731
    assert errands.context() == 'proofread'
    errands.scene_report('proofread')
    assert 'AI 词库校对' in bubble().text
    widget, words = errands._suggestion('proofread')
    assert widget in (page.ai_button,) and ('AI 校对' in words or '按词库匹配' in words)
    page.cancel_button.show()
    app.processEvents()
    errands.scene_report('proofread')
    assert 'AI 开始校对' not in bubble().text
    page.ai_progress_bar.show()
    page.ai_progress_bar.setRange(0, 8)
    page.ai_progress_bar.setValue(3)
    app.processEvents()
    errands.scene_report('proofread')
    assert 'AI 开始校对' in bubble().text
    assert errands._bar_percent('proofread') == 38
    page.cancel_button.hide()
    page.ai_progress_bar.hide()
    page.ai_review_outcome = 'complete'
    page.batch_adopt.setEnabled(True)
    app.processEvents()
    errands.scene_report('proofread')
    assert '校对好了' in bubble().text
    assert errands._suggestion('proofread')[0] is page.batch_adopt
    page.ai_progress_bar.show()
    app.processEvents()
    errands.scene_report('proofread')
    page.ai_progress_bar.hide()
    page.ai_review_outcome = 'cancelled'
    app.processEvents()
    errands.scene_report('proofread')
    assert '已取消' in bubble().text


def test_at_the_video_export_she_watches_the_render_and_cheers_when_it_is_out(app, window):
    from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QWidget
    studio = QWidget()
    export = QWidget(studio)
    export.setGeometry(0, 0, 1200, 800)
    export._running = False
    export.progress = QProgressBar(export)
    export.progress.setGeometry(100, 600, 900, 12)
    export.progress.setRange(0, 100)
    export.export_button = QPushButton('导出', export)
    export.export_button.setGeometry(1000, 700, 100, 34)
    export.open_folder_button = QPushButton('打开文件夹', export)
    export.open_folder_button.setGeometry(880, 700, 110, 34)
    export.open_folder_button.hide()
    export.status = QLabel('', export)
    studio.export_workspace = export
    window.pages.addWidget(studio)
    window.pages.setCurrentWidget(studio)
    window.built_page = lambda name: studio if name == 'studio' else None
    chat = _folded(window)
    errands, bubble = chat.errands, lambda: chat.puck.carrier.bubble    # noqa: E731
    assert errands.context() == 'export'
    errands.scene_report('export')
    assert '导出视频' in bubble().text
    assert errands._suggestion('export')[0] is export.export_button
    export._running = True
    export.progress.setValue(30)
    errands.scene_report('export')
    assert '开始导出' in bubble().text
    assert 'ride_bar' in dict(errands.candidates())
    export._running = False
    export.open_folder_button.show()
    app.processEvents()
    errands.scene_report('export')
    assert '导出好啦' in bubble().text
    assert errands._suggestion('export')[0] is export.open_folder_button
