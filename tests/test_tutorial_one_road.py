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
    # User 10-24: the plan (and the videos' language) is the very first step, before the video.
    assert plan == 0 and media == 1 and '主要语言' in _plain(steps[plan].text)
    assert steps[plan].enter is not None              # the demo video is prepared meanwhile
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
    assert plan < media < primary < timeline < ai < inside[0] <= inside[-1] < after < terms < spoken < output
    assert not steps[spoken].actions                   # the language was chosen with the plan: only where to change it
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
    third = [text for text in texts if text.startswith('工作台')]   # 2026-10-24: the workbench is its own part
    assert first[0].startswith('做字幕 · 1 / ') and second[0].startswith('改字幕 · 1 / ')
    assert third[0].startswith('工作台 · 1 / ')
    assert len(first) + len(second) + len(third) == len(steps)
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
    from twobyteasr.app.quick_setup import FOREIGN_LOCAL_GOOD, OTHER_SPOKEN, SPOKEN_CHOICES
    root = Path(__file__).resolve().parents[1] / 'twobyteasr' / 'locales'
    texts = set()
    for step in tutorial_steps(_window()):
        for value in (step.text, step.note):
            value = value() if callable(value) else value
            if value:
                texts.add(str(getattr(value, 'source', value)))   # a tr() result: its sentence (key names filled in)
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
        # 2026-10-24: the plan window's language row, the language-dependent notes, the new scenes' words
        '工作台', '视频里主要说什么话？', '其他语言',
        '{value0}：字幕时间用 **FireRedASR2**，每个字的时间最准（要 NVIDIA 显卡，没有就用 Qwen3 对齐）',
        '{value0}：字幕时间用 **Qwen3 对齐**，每个字词都对得准，不用显卡也能跑（FireRedASR2 只对中文）',
        '刚才选好了「{value0}」· {value1}；想换就点「比较两种方案」', '{value0}用 **Qwen3 对齐** 对准每个字词的时间',
        '中文用 **FireRedASR2** 对准每个字，时间最准', '用 **Qwen3 对齐** 对准每个字，不用 NVIDIA 显卡',
        '刚才选了「{value0}」；换别的视频时在这里改', '自动识别语言',
        '剃刀', '合并工具', '和上一段', '和下一段', '新建字幕', '未绑定',
    }
    texts.update(FOREIGN_LOCAL_GOOD)
    texts.update(name for _code, name in SPOKEN_CHOICES + OTHER_SPOKEN)
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


# ---------------------------------------------------------------- 2026-10-24

def test_the_bubble_fades_in_without_square_corners(app):
    """User: square corners flashed at the bubble's four corners on every step (grab() filled them)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app.home_tour import GuidedTour, TourStep
    window = QWidget()
    window.resize(1400, 900)
    window.show()
    tour = GuidedTour(window, [TourStep('卡片', None)])
    tour.index = 0
    tour._prepare_bubble(tour.steps[0])
    tour._placement = tour._place(QRectF())
    image = tour._bubble_picture().toImage()
    w, h = image.width(), image.height()
    for x, y in ((1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)):
        assert image.pixelColor(x, y).alpha() == 0, (x, y)
    assert image.pixelColor(w // 2, h // 2).alpha() == 255          # the bubble itself is opaque
    assert image.pixelColor(1, h // 2).alpha() == 255               # ...up to its border
    tour.close_tour(False)
    window.close()


def test_the_plan_follows_the_language_the_videos_speak():
    from twobyteasr.app.quick_setup import default_spoken, language_advice, plan_backends, plan_models
    from twobyteasr.recognition.recognition_plans import matching_plan
    assert plan_backends('cloud', 'zh', 'local') == ('api', 'local', 'off')
    assert plan_backends('cloud', 'zh-Hant', 'local') == ('api', 'local', 'off')
    assert plan_backends('cloud', 'ja', 'local') == ('api', 'qwen_aligner', 'off')
    assert plan_backends('cloud', 'zh', 'qwen_aligner') == ('api', 'qwen_aligner', 'off')   # no NVIDIA card
    assert plan_backends('local', 'zh', '') == ('moss', 'local', 'local')
    assert plan_backends('local', 'en', '') == ('moss', 'qwen_aligner', 'local')
    assert plan_backends('apple', 'ja', '') == ('mlx_qwen3_asr', 'mlx_qwen_aligner', 'off')
    # The same models the home page's plan menu calls 本地识别 / 日语 / 外语 / API 转写.
    assert matching_plan(*plan_backends('local', 'zh'), 'zh') == 'quality'
    assert matching_plan(*plan_backends('local', 'ja'), 'ja') == 'japanese'
    assert matching_plan(*plan_backends('local', 'ko'), 'ko') == 'english'
    assert matching_plan(*plan_backends('cloud', 'ja', 'local'), 'ja', provider='mosi_moss_pro') == 'moss_pro_qwen'
    assert plan_models('cloud', 'local') == ('MOSS Pro', 'FireRedASR2')
    assert plan_models('cloud', 'qwen_aligner') == ('MOSS Pro', 'Qwen3 对齐')
    assert plan_models('local', 'qwen_aligner') == ('MOSS', 'Qwen3', 'Qwen3 对齐')
    assert 'FireRedASR2' in language_advice('zh') and 'Qwen3 对齐' in language_advice('ja')
    assert default_spoken('', 'ja') == 'ja' and default_spoken('auto', 'de') == 'de'
    assert default_spoken('zh-Hant', 'en') == 'zh-Hant' and default_spoken('', 'xx') == 'zh'


def test_the_plan_window_shows_and_returns_the_models_for_the_language(app, monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.system import hardware
    from twobyteasr.app.quick_setup import QuickSetupDialog
    monkeypatch.setattr(hardware, 'detect_cuda_runtime',
                        lambda: SimpleNamespace(ready=True, code='ok', gpu_name='NVIDIA RTX'))
    sizes = {('api', 'local', 'off'): 4.4, ('api', 'qwen_aligner', 'off'): 1.8,
             ('moss', 'local', 'local'): 10.8, ('moss', 'qwen_aligner', 'local'): 8.2}
    dialog = QuickSetupDialog(compare=True, plan_keys=['cloud', 'local'], spoken='ja',
                              size_of=lambda backends: sizes.get(tuple(backends), 0.0))
    _until(app, lambda: dialog._cuda is not None)
    assert dialog.spoken == 'ja' and dialog.spoken_buttons['ja'].isChecked()
    cloud, local = dialog.cards['cloud'], dialog.cards['local']
    assert cloud.models.text() == 'MOSS Pro · Qwen3 对齐' and local.models.text() == 'MOSS · Qwen3 · Qwen3 对齐'
    assert '1.8 GB' in cloud.status.text() and '8.2 GB' in local.status.text()
    assert 'Qwen3 对齐' in dialog.spoken_advice.text()
    assert any('两个模型' in label.text() for label in local.points)
    dialog.set_spoken('zh')
    assert cloud.models.text() == 'MOSS Pro · FireRedASR2' and local.models.text() == 'MOSS · FireRed · Qwen3'
    assert '4.4 GB' in cloud.status.text() and '10.8 GB' in local.status.text()
    assert any('三个模型' in label.text() for label in local.points) and len(local.points) == 6
    dialog.spoken_other.setCurrentIndex(dialog.spoken_other.findData('de'))   # 其他语言 → 德语
    assert dialog.spoken == 'de' and not any(button.isChecked() for button in dialog.spoken_buttons.values())
    dialog.select('cloud')
    dialog._go()
    assert dialog.backends == ('api', 'qwen_aligner', 'off') and dialog.spoken == 'de'
    dialog.close()


def test_the_first_step_waits_when_the_plan_was_just_chosen():
    from twobyteasr.app.home_tour import tutorial_steps
    window = _window()
    assert tutorial_steps(window)[0].auto is not None          # from 说明 → 新手教学: the comparison opens
    window._tutorial_plan_chosen = True                         # right after the first-run chooser
    steps = tutorial_steps(window)
    assert steps[0].auto is None and steps[0].show_next and steps[0].actions
    assert not hasattr(window, '_tutorial_plan_chosen')          # once


def test_the_workbench_teaches_cut_merge_ripple_and_a_new_line(monkeypatch):
    from twobyteasr.app import tour_motion
    from twobyteasr.app.home_tour import tutorial_steps
    from twobyteasr.studio import shortcut_registry
    values = dict(shortcut_registry.platform_defaults(), razor_tool='X', merge_previous='Alt+Q')
    monkeypatch.setattr(shortcut_registry, 'current_values', lambda: values)
    steps = tutorial_steps(_window())
    anims = [step.anim for step in steps]
    order = [anims.index(name) for name in ('qw', 'razor', 'merge_tool', 'ripple', 'add_cue', 'punct')]
    assert order == sorted(order) and order[-1] - order[0] == 6        # T is followed by its Enter / Esc step
    by = {step.anim: step for step in steps}
    assert all(by[name].chapter == '工作台' and by[name].interactive and by[name].actions
               and by[name].done is not None and name in tour_motion.SCENES
               for name in ('razor', 'merge_tool', 'ripple', 'add_cue'))
    assert '**X**' in str(by['razor'].text()) and '点两下' in str(by['razor'].text())     # keys as set
    assert '**B**' in str(by['merge_tool'].text())
    assert '**Alt+Q**' in str(by['ripple'].text()) and '**Shift+W**' in str(by['ripple'].text())
    assert '**T**' in str(by['add_cue'].text())
    assert by['merge_tool'].optional and by['ripple'].optional        # nothing left to merge: skipped
    tour_motion.refresh_keys()
    assert tour_motion.key_name('razor_tool', 'C') == 'X' and tour_motion.key_name('merge_tool', 'B') == 'B'


def test_the_next_step_waits_until_the_page_holds_still(app):
    """Real window 10-24: the demo video loaded and the 「还差一步」 banner answered a moment after the
    click, moving ③'s card 125 px while its bubble showed. The next step now waits under the shade."""
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app.home_tour import GuidedTour, TourAction, TourStep
    window = QWidget()
    window.resize(1400, 900)
    first = QPushButton('放入', window)
    first.setGeometry(60, 100, 160, 44)
    card = QPushButton('主力转写', window)
    card.setGeometry(60, 300, 300, 80)
    window.show()
    page = dict(still=False, chosen=False)
    tour = GuidedTour(window, [
        TourStep('放入视频', lambda: first, [TourAction('放入', lambda: None, advance=True)], show_next=False,
                 settle=lambda: page['still']),
        # An optional step that only applies once the page has answered (like ③ by the chosen plan).
        TourStep('主力转写', lambda: card, optional=True, ready=lambda: page['chosen']),
        TourStep('之后'),
    ])
    tour.start()
    _until(app, lambda: _shown(tour) and tour.index == 0)
    tour._run_action(tour.steps[0].actions[0])
    for _ in range(10):
        app.processEvents()
    assert tour.index == 1 and tour.mode == 'wait' and not tour.bubble.isVisible() and tour.hole.isNull()
    card.move(60, 425)                                 # the page is still moving...
    page.update(still=True, chosen=True)               # ...then holds still, and ③ applies
    _until(app, lambda: _shown(tour) and tour.index == 1)
    assert abs(tour.hole.center().y() - tour._rect_of(card).center().y()) < 3
    tour.close_tour(False)
    window.close()


def test_an_open_editor_keeps_the_keyboard_when_its_step_shows(app, monkeypatch):
    """Real window 10-24: T opened the new line's editor, then the "Enter 保存" step took the keys back."""
    from PySide6.QtWidgets import QApplication, QLineEdit, QWidget
    from twobyteasr.app.home_tour import GuidedTour, TourStep
    # A child overlay: offscreen, showing the tool window would move the active window by itself.
    monkeypatch.setattr(GuidedTour, 'FLOATING', False)
    window = QWidget()
    window.resize(1400, 900)
    editor = QLineEdit(window)
    editor.setGeometry(300, 300, 300, 40)
    window.show()
    window.activateWindow()
    editor.setFocus()
    app.processEvents()
    if QApplication.focusWidget() is not editor:
        pytest.skip('no keyboard focus on this platform plugin')
    tour = GuidedTour(window, [TourStep('按 Enter 保存', lambda: editor, interactive=True, show_next=False,
                                        done=lambda: False)])
    tour.start()
    _until(app, lambda: _shown(tour))
    assert QApplication.focusWidget() is editor
    editor.hide()                                      # Enter closed it: nothing stays on the old spot,
    assert not tour.bubble.isVisible() and tour.hole.isNull()   # not even until the next 60 ms check
    tour.close_tour(False)
    window.close()
