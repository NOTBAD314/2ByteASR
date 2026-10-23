"""One tutorial, in the user's order, pointing into AI 设置 (2026-10-22).

User: right after the video the plan (cloud or local, with what each is good
for); then AI 智能断句 and its key, shown in the real AI settings window with
the 申请教程 and the choice to switch it on; only then the glossary and the
languages; and no separate 进阶 part. The outline must not stutter or lag, and
opening the workbench must not flash.
"""
import re
import time
from types import SimpleNamespace

import pytest


def _window():
    noop = lambda *a, **k: None  # noqa: E731
    return SimpleNamespace(_tutorial_prepare_demo=noop, _tutorial_add_demo_media=noop,
                           _tutorial_demo_completion=noop, _open_api_key_explainer=noop)


def _plain(value):
    return re.sub(r'\*\*', '', str(value() if callable(value) else value))


def test_one_tutorial_in_the_users_order():
    from twobyteasr.app.home_tour import tutorial_steps
    steps = tutorial_steps(_window())
    assert steps == steps and len(steps) == len(tutorial_steps(_window(), 'basic'))   # no separate parts any more

    def first(condition):
        return next(index for index, step in enumerate(steps) if condition(step))
    media = first(lambda s: s.anim == 'drop')
    plan = first(lambda s: s.anim == 'plan_compare')
    primary = first(lambda s: s.anim in ('moss_signup', 'plan_ok'))
    timeline = first(lambda s: s.anim == 'timeline_mg')
    ai = first(lambda s: s.anim == 'ai_lock' and s.host is None)
    inside = [index for index, step in enumerate(steps) if step.host is not None]
    after = first(lambda s: s.name == 'after_ai')
    terms = first(lambda s: '术语库校对' in _plain(s.text))
    spoken = first(lambda s: s.anim == 'spoken')
    output = first(lambda s: s.anim == 'subtitle_lang')
    proofread = first(lambda s: s.anim == 'gl_check')
    studio = first(lambda s: s.anim == 'studio_open')
    assert media < plan < primary < timeline < ai < inside[0] <= inside[-1] < after < terms < spoken < output
    assert output < proofread < studio < len(steps) - 1
    assert inside == list(range(inside[0], inside[-1] + 1)) and len(inside) == 5
    # The plan window opens by itself a moment after the step appears.
    assert steps[plan].auto is not None and steps[plan].auto.modal and steps[plan].auto.advance
    # AI: the key is needed for all three, the real settings window is the main button, skipping is possible.
    note = _plain(steps[ai].note)
    assert all(word in note for word in ('AI 断句', '翻译', '术语库校对', '用不了', 'DeepSeek'))
    labels = [action.label for action in steps[ai].actions]
    assert labels[0] == '打开 AI 设置看看' and steps[ai].actions[0].big and steps[ai].actions[-1].goto == 'after_ai'
    inner = [_plain(steps[index].text) for index in inside]
    assert 'DeepSeek' in inner[0] and '申请教程' in inner[1] and 'API Key' in inner[2] and '测试连接' in inner[3]
    enable = steps[inside[-1]]
    assert [action.label for action in enable.actions] == ['保存并开启', '先不开'] and not enable.show_next
    assert '不开' in _plain(enable.note) and '用不了' in _plain(enable.note)
    # Locked or not, the glossary and output steps say so.
    assert '灰' in _plain(steps[terms].note) and '灰' in _plain(steps[output].note)
    texts = [_plain(step.text) + _plain(step.note) + ''.join(a.label for a in step.actions) for step in steps]
    assert not any('进阶' in text for text in texts)
    assert not any('不填 API Key' in text or '不填也能' in text for text in texts)
    short = steps[:proofread]   # the home steps stay one short line each
    assert all(len(_plain(step.text)) <= 34 for step in short), [_plain(s.text) for s in short if len(_plain(s.text)) > 34]


def test_the_counter_reads_as_two_short_chapters(app):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app.home_tour import GuidedTour, tutorial_steps
    steps = tutorial_steps(_window())
    holder = QWidget()
    tour = GuidedTour(holder, steps)
    texts = []
    for index, step in enumerate(steps):
        tour.index = index
        texts.append(tour._progress_text(step))
    first = [text for text in texts if text.startswith('做字幕')]
    second = [text for text in texts if text.startswith('改字幕')]
    assert first[0].startswith('做字幕 · 1 / ') and second[0].startswith('改字幕 · 1 / ')
    assert len(first) + len(second) == len(steps)
    assert all(int(text.rsplit('/', 1)[1]) <= 20 for text in texts)   # never "x / 40"
    primary = [texts[i] for i, step in enumerate(steps) if step.group == 'primary']
    assert len(primary) == 3 and len(set(primary)) == 1          # one of three ways of saying ③ counts once
    tour.close_tour(False)
    holder.deleteLater()


def test_every_new_tutorial_string_has_a_translation():
    import json
    from pathlib import Path
    from twobyteasr.app.home_tour import tutorial_steps
    from twobyteasr.app.quick_setup import POINTS
    root = Path(__file__).resolve().parents[1] / 'twobyteasr' / 'locales'
    texts = set()
    for step in tutorial_steps(_window()):
        for value in (step.text, step.note):
            if value and not callable(value):
                texts.add(str(value))
        texts.update(action.label for action in step.actions if action.label)
        texts.add(step.next_label)
    texts |= {  # callables' answers, both ways
        '马上会弹出比较：云端不挑电脑，本机免费不上传', '现在用的是「{value0}」；马上会弹出两种方案的比较',
        '模型会在教学结束后开始下载', '点这张卡可以换模型', '这一套服务同时做 AI 断句、翻译和校对',
        '上面管校对和翻译，「更多选项」里管 AI 断句；两边都要填', '右边的「联网补充核验」会再上网查一遍（可选）',
        '要先连接 AI（填 API Key 并测试连接）才能用，现在是灰的', '翻译也是 AI 做的，会用上面的 API Key',
        '没连接 AI 时只能选“只显示原文”，翻译是灰的',
        # the plan window in compare mode, the home page lock
        '识别方案：用云端还是本机？', '两种都能做字幕。看看好处和要注意的，选一个；以后在模型工坊随时能换',
        '先不换', '用这个方案', '需要先填 API Key 并测试连接才能用', '需要先测试 AI 连接才能用',
        'AI 连接测试没通过，暂时不能用', 'AI 已关闭，打开后才能用', '去设置 AI', '测试连接', '正在测试连接…',
        '用已保存的服务和 Key 测试一次；通过后才能用翻译和术语库校对', '{value0}（需要 API Key）',
        '你选的翻译要先连接 AI（填 API Key 并测试连接）才会生效，现在只显示原文。',
        # the counter's chapters, the guide button the tutorial names, the chooser's tutorial box
        '做字幕', '改字幕', '申请教程', '选好后带我走一遍新手教学（推荐，约 6 分钟）',
    }
    for good, care in POINTS.values():
        texts.update(good)
        texts.update(care)
    texts -= {'中文', '日本語', 'English'}   # language names stay as they are
    languages = ('en', 'ja', 'ko', 'zh-Hant', 'es', 'de', 'fr', 'pt', 'it', 'ru')
    missing = {}
    for language in languages:
        catalog = json.loads((root / f'{language}.json').read_text(encoding='utf-8'))
        lost = sorted(text for text in texts if text not in catalog)
        if lost:
            missing[language] = lost
    assert missing == {}


# ---------------------------------------------------------------- the overlay

def _until(app, condition, seconds=4.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


def _shown(tour):
    return tour.mode == 'shown' and tour.reveal >= 1.0 and tour.bubble.isVisible()


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_outline_sets_off_at_once_and_the_bubble_fades_in_as_one_picture(app):
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app.home_tour import GuidedTour, TourStep
    window = QWidget()
    window.resize(1400, 900)
    button = QPushButton('目标', window)
    button.setGeometry(60, 380, 160, 44)
    window.show()
    tour = GuidedTour(window, [TourStep('点目标', lambda: button), TourStep('完成')])
    tour.start()
    assert tour.mode == 'glide'                       # no waiting for the target to hold still first
    _until(app, lambda: tour.mode == 'shown')
    assert tour._reveal_pixmap is not None and not tour.bubble.isVisible()   # the picture fades in...
    assert not tour._reveal_pixmap.isNull()
    _until(app, lambda: _shown(tour))
    assert tour._reveal_pixmap is None                # ...then the real bubble is there
    assert tour.bubble.graphicsEffect() is None
    tour.close_tour(True)
    window.close()


def test_a_moving_target_is_followed_during_the_glide(app):
    from PySide6.QtCore import QRectF
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app.home_tour import GuidedTour, TourStep
    window = QWidget()
    window.resize(1400, 900)
    button = QPushButton('目标', window)
    button.setGeometry(60, 380, 160, 44)
    window.show()
    tour = GuidedTour(window, [TourStep('点目标', lambda: button), TourStep('完成')])
    tour.start()
    button.move(500, 600)                              # the page is still settling
    _until(app, lambda: _shown(tour))
    expected = tour._rect_of(button)
    assert abs(tour.hole.center().x() - expected.center().x()) < 3
    assert abs(tour.hole.center().y() - expected.center().y()) < 3
    assert not QRectF(tour.bubble.geometry()).intersects(tour.hole)
    tour.close_tour(True)
    window.close()


def test_a_click_that_opens_a_page_keeps_the_shade_and_lets_clicks_through(app):
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app.home_tour import GuidedTour, TourStep
    window = QWidget()
    window.resize(1400, 900)
    button = QPushButton('打开', window)
    button.setGeometry(60, 380, 160, 44)
    window.show()
    opened = []
    tour = GuidedTour(window, [TourStep('点这里', lambda: button, interactive=True, show_next=False,
                                        done=lambda: bool(opened)), TourStep('完成')])
    tour.FLOATING = False
    tour.start()
    _until(app, lambda: _shown(tour))
    button.hide()                                      # the page answers the click (the workbench opening)
    tour._follow_target()
    assert tour.mode == 'pending' and tour.isVisible() # the shade stays: no flash of the bright window
    assert tour._click_through
    button.show()
    tour._follow_target()
    assert tour.mode == 'wait' and not tour._click_through
    tour.close_tour(True)
    window.close()


def test_steps_inside_a_window_point_into_it_and_go_on_when_it_closes(app):
    from PySide6.QtWidgets import QDialog, QLineEdit, QPushButton, QVBoxLayout, QWidget
    from twobyteasr.app.home_tour import GuidedTour, TourAction, TourStep
    window = QWidget()
    window.resize(1400, 900)
    window.show()
    dialog = QDialog(window)
    dialog.setObjectName('aiSettingsDialog')           # a window the tutorial would otherwise step aside for
    layout = QVBoxLayout(dialog)
    key = QLineEdit(dialog)
    save = QPushButton('保存设置', dialog)
    layout.addWidget(key)
    layout.addWidget(save)
    dialog.resize(600, 300)
    save.clicked.connect(dialog.accept)
    host = lambda: dialog if dialog.isVisible() else None  # noqa: E731
    tour = GuidedTour(window, [
        TourStep('打开设置', None, [TourAction('打开', dialog.show, advance=True)], show_next=False),
        TourStep('贴 Key', lambda: key, host=host, optional=True, interactive=True),
        TourStep('保存', lambda: save, [TourAction('保存并开启', save.click, big=True)], host=host, optional=True,
                 show_next=False),
        TourStep('之后', None, name='after'),
    ])
    if not tour.floating:
        pytest.skip('a child overlay cannot cover another window (macOS): those steps are skipped')
    tour.start()
    _until(app, lambda: _shown(tour) and tour.index == 0)
    tour._run_action(tour.steps[0].actions[0])
    _until(app, lambda: _shown(tour) and tour.index == 1)
    assert tour.isVisible() and tour._foreign_dialog() is None   # not stepping aside for its own window
    target = tour._rect_of(key)
    assert abs(target.center().x() - tour.hole.center().x()) < 3
    assert not tour.back.isVisible()                   # never back across the window's edge
    tour.go(2)
    _until(app, lambda: _shown(tour) and tour.index == 2)
    tour._run_action(tour.steps[2].actions[0])         # saved: the window closes...
    _until(app, lambda: tour.index == 3)               # ...and the tutorial goes on after its steps
    tour.close_tour(True)
    window.close()


def test_without_the_window_its_steps_are_skipped(app):
    from PySide6.QtWidgets import QDialog, QPushButton, QWidget
    from twobyteasr.app.home_tour import GuidedTour, TourStep
    window = QWidget()
    window.resize(1400, 900)
    window.show()
    dialog = QDialog(window)
    button = QPushButton('x', dialog)
    tour = GuidedTour(window, [
        TourStep('开始'),
        TourStep('窗口里', lambda: button, host=lambda: dialog if dialog.isVisible() else None, optional=True),
        TourStep('之后'),
    ])
    tour.start()
    _until(app, lambda: _shown(tour) and tour.index == 0)
    tour.go(1)
    assert tour.index == 2
    tour.close_tour(True)
    window.close()
