"""Tutorial chapters on their own: 编辑器 / 术语库 / 问问兔白 (2026-11-16).

User: the tutorial should also teach the editor's newer keys, adding a word to the glossary and
using 「问问兔白」. Each chapter runs in the same overlay, on demo data that does not stick: the
tutorial project, a throw-away 「兔白教学词库」 and 兔白's written demo answers.
"""
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QStackedWidget, QWidget

from twobyteasr.app import tutorial_chapters
from twobyteasr.app.home_tour import GuidedTour, TourStep, tutorial_steps


def _app():
    return QApplication.instance() or QApplication([])


def _until(condition, seconds=4.0):
    app = _app()
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


@pytest.mark.parametrize('part', ['editor', 'terms', 'bunny', 'render', 'how', 'speakers', 'style', 'audio'])
def test_each_chapter_is_its_own_short_part(part):
    window = SimpleNamespace(pages=QStackedWidget() if _app() else None, built_page=lambda _name: None)
    steps = tutorial_steps(window, part)
    assert 5 <= len(steps) <= 16
    chapter = {'editor': '编辑器', 'terms': '术语库', 'bunny': '问问兔白', 'render': '压制', 'how': '原理',
               'speakers': '说话人', 'style': '样式', 'audio': '声音剪辑'}[part]
    assert {step.chapter for step in steps} == {chapter}
    assert steps[-1].target is None and steps[-1].next_label == '完成'   # a last card closes it


def test_every_chapter_string_has_a_translation():
    catalogs = {lang: json.loads((Path('twobyteasr/locales') / f'{lang}.json').read_text('utf-8'))
                for lang in ('en', 'ja')}
    window = SimpleNamespace(pages=QStackedWidget() if _app() else None, built_page=lambda _name: None)
    missing = []
    for part in tutorial_chapters.CHAPTERS:
        for step in tutorial_steps(window, part):
            texts = [step.text, step.note, step.next_label] + [action.label for action in step.actions]
            for text in texts:
                if isinstance(text, str) and text:
                    missing += [(lang, text) for lang, table in catalogs.items() if text not in table]
    for title, _minutes in tutorial_chapters.CHAPTERS.values():
        missing += [(lang, title) for lang, table in catalogs.items() if title not in table]
    assert not missing


def test_demo_answers_need_no_ai_and_offer_a_harmless_do():
    to_terms = tutorial_chapters.demo_reply('带我去术语库')
    assert to_terms.do == ('open_page', 'terms') and len(to_terms.lines) == 1 and to_terms.steps
    timing = tutorial_chapters.demo_reply('怎么把整片字幕提前半秒？')
    assert any('Alt+←' in line for line in timing.lines) and not timing.do
    other = tutorial_chapters.demo_reply('随便问问')
    assert other.lines and not other.do


def test_the_demo_conversation_is_never_saved(monkeypatch):
    from twobyteasr.app import bunny_chat, bunny_memory
    saved = []
    monkeypatch.setattr(bunny_memory, 'save_chat', lambda *args: saved.append(args))
    bunny_chat.BunnyChat._save_chat(SimpleNamespace(stand_in=tutorial_chapters.demo_reply, _chat_key='p',
                                                    transcript=[('user', 'hi')]))
    assert saved == []


def test_the_glossary_chapter_removes_its_library(monkeypatch):
    _app()
    deleted, saved = [], []
    settings = {'glossary': {'enabled_glossary_ids': ['library:demo', 'library:mine']}}
    legacy = SimpleNamespace(delete_learned_game=deleted.append, RUNTIME_SETTINGS=settings)
    window = SimpleNamespace(legacy=legacy, _save_glossary_settings=lambda: saved.append(True),
                             term_library_page=None, game_box=None)
    window._tutorial_terms_library = 'library:demo'
    tutorial_chapters.cleanup(window, 'terms')
    assert deleted == ['library:demo'] and saved == [True]
    assert settings['glossary']['enabled_glossary_ids'] == ['library:mine']
    assert '_tutorial_terms_library' not in window.__dict__
    tutorial_chapters.cleanup(window, 'terms')            # twice: nothing more to do
    assert deleted == ['library:demo']


def test_a_chapter_starts_where_it_is_and_records_when_finished(monkeypatch):
    _app()
    from twobyteasr.app import home_tour, onboarding
    from twobyteasr.app.ui import MainWindow
    state = {'fresh': True, 'tour_done': False, 'first_task_done': False}
    monkeypatch.setattr(onboarding, 'load_state', lambda: dict(state))
    monkeypatch.setattr(onboarding, 'save_state', lambda new: state.update(new))
    calls, cleaned = [], []
    monkeypatch.setattr(home_tour, 'start_home_tour', lambda window, on_finished=None, part='all', **kw:
                        calls.append(dict(on_finished=on_finished, part=part, **kw)))
    monkeypatch.setattr(tutorial_chapters, 'cleanup', lambda window, part: cleaned.append(part))
    studio = QWidget()
    pages = QStackedWidget()
    pages.addWidget(QWidget())
    pages.addWidget(studio)
    pages.setCurrentWidget(studio)                         # not on the home page
    finished = []
    window = SimpleNamespace(pages=pages, settings_scroll=pages.widget(0), _first_run_required=True,
                             findChild=lambda _cls: None, _tutorial_finish=finished.append,
                             _choose_plan_in_tutorial=lambda: (_ for _ in ()).throw(AssertionError('plan')),
                             _switch_page=lambda _w: (_ for _ in ()).throw(AssertionError('went home')))
    MainWindow._start_home_tour(window, 'terms')
    assert calls and calls[0]['part'] == 'terms' and calls[0]['required'] is False
    calls[0]['on_finished'](True)
    assert cleaned == ['terms'] and state['chapters_done'] == ['terms'] and finished == [True]
    assert state['tour_done'] is False                      # a chapter alone does not end the first tutorial


def test_a_slow_page_gets_its_patience_before_the_window_is_given_back(monkeypatch):
    _app()
    monkeypatch.setattr(GuidedTour, 'STUCK_MS', 100)
    monkeypatch.setattr(GuidedTour, 'FLOATING', False)
    window = QWidget()
    window.resize(1200, 800)
    first = QPushButton('一', window)
    first.setGeometry(50, 50, 120, 40)
    window.show()
    tour = GuidedTour(window, [TourStep('看这里', lambda: first),
                               TourStep('工程打开中', lambda: None, ready=lambda: False, patience=1200)])
    tour.start()
    _until(lambda: tour.mode == 'shown')
    tour.next.click()
    _until(lambda: tour.index == 1)
    deadline = time.monotonic() + 0.6
    while time.monotonic() < deadline:
        _app().processEvents()
        time.sleep(0.01)
    assert tour.mode == 'wait'                              # still waiting: the project is opening
    _until(lambda: tour.mode == 'away', seconds=3)
    tour.close_tour(False)
    window.close()


def test_a_target_in_a_window_of_its_own_is_not_taken_as_covered(monkeypatch):
    """The workbench's caption editor card is its own window over the video."""
    _app()
    monkeypatch.setattr(GuidedTour, 'FLOATING', True)
    window = QWidget()
    window.resize(1200, 800)
    cover = QWidget(window)                                 # like the native video under the card
    cover.setGeometry(0, 0, 1200, 800)
    window.show()
    card = QWidget()
    card.setGeometry(window.geometry().left() + 300, window.geometry().top() + 300, 300, 120)
    button = QPushButton('切割', card)
    button.setGeometry(20, 20, 120, 40)
    card.show()
    tour = GuidedTour(window, [TourStep('点切割', lambda: button), TourStep('完成')])
    tour.start()
    _until(lambda: tour.mode == 'shown')
    assert tour.index == 0 and not tour.hole.isNull()
    tour.close_tour(False)
    card.close()
    window.close()


def _plain_window():
    noop = lambda *a, **k: None  # noqa: E731
    return SimpleNamespace(_tutorial_prepare_demo=noop, _tutorial_add_demo_media=noop,
                           _tutorial_demo_completion=noop, _open_api_key_explainer=noop)


def test_the_whole_tutorial_also_runs_as_three_chapters():
    """2026-11-16: 做出第一份字幕 / 改错字 / 工作台 each on its own; the whole one is kept."""
    whole = tutorial_steps(_plain_window())
    first = tutorial_steps(_plain_window(), 'first')
    fix = tutorial_steps(_plain_window(), 'fix')
    studio = tutorial_steps(_plain_window(), 'studio')
    assert first[-1].target is None and first[-1].next_label == '完成'
    assert {step.chapter for step in first} == {'做字幕'}
    assert {step.chapter for step in fix} == {'改字幕'} and {step.chapter for step in studio} == {'工作台'}
    assert fix[0].enter is not None and studio[0].enter is not None      # each sets up its own demo data
    assert studio[1].patience >= 30000                                     # opening the project takes a while
    texts = [str(step.text) for step in fix]
    assert not any('字幕工作台==：逐条修改' in text for text in texts)        # opening the workbench is the next chapter
    assert len(first) - 1 + len(fix) - 2 + len(studio) - 1 == len(whole) - 1


def test_the_centre_lists_the_chapters_and_suggests_the_next_one(monkeypatch):
    _app()
    from twobyteasr.app import onboarding, tutorial_centre
    state = {'chapters_done': ['first'], 'tasks_done': ['export'], 'first_task_done': True}
    monkeypatch.setattr(onboarding, 'load_state', lambda: dict(state))
    window = QWidget()
    window._ai_unlocked = lambda: False
    centre = tutorial_centre.TutorialCentre(window)
    assert centre.pick == 'how'                                            # the first one not learned yet
    assert list(centre.rows) == [chapter.id for chapter in tutorial_chapters.CATALOG]
    assert centre.start_button.isEnabled()
    assert not any(chapter.soon for chapter in tutorial_chapters.CATALOG)  # every listed chapter is built now
    assert centre.tasks_done == {'export', 'first_subtitle'}
    assert tutorial_centre.chapter_status(tutorial_chapters.BY_ID['first'], centre.learned) == 'done'
    assert tutorial_centre.chapter_status(tutorial_chapters.BY_ID['editor'], centre.learned) == 'new'
    centre.select('editor')
    centre.start_button.click()
    assert centre.chosen == 'editor' and centre.result() == 1
    centre.deleteLater()


def test_a_task_card_teaches_its_chapter(monkeypatch):
    _app()
    from twobyteasr.app import onboarding, tutorial_centre
    monkeypatch.setattr(onboarding, 'load_state', lambda: {})
    centre = tutorial_centre.TutorialCentre(QWidget(), tab='tasks')
    assert centre.stack.currentIndex() == 1
    card = centre.task_cards['add_term']
    teach = next(button for button in card.findChildren(QPushButton) if button.objectName() == 'taskTeach')
    teach.click()
    assert centre.chosen == 'terms'
    centre.deleteLater()


def test_tasks_tick_once_and_not_while_practising(monkeypatch):
    from twobyteasr.app import newbie_tasks, onboarding
    state = {}
    monkeypatch.setattr(onboarding, 'load_state', lambda: dict(state))
    monkeypatch.setattr(onboarding, 'save_state', lambda new: state.update(new))
    monkeypatch.setattr(GuidedTour, 'live', 1)
    assert not newbie_tasks.mark('cut')                                    # practice in a tutorial
    monkeypatch.setattr(GuidedTour, 'live', 0)
    assert newbie_tasks.mark('cut') and not newbie_tasks.mark('cut')
    assert not newbie_tasks.mark('no-such-task')
    assert state['tasks_done'] == ['cut']
    window = SimpleNamespace(_ai_unlocked=lambda: True)
    assert newbie_tasks.done_keys(window, dict(state, first_task_done=True)) == {'cut', 'first_subtitle', 'set_ai'}


def test_every_centre_string_has_a_translation():
    from twobyteasr.app import newbie_tasks
    catalogs = {lang: json.loads((Path('twobyteasr/locales') / f'{lang}.json').read_text('utf-8'))
                for lang in ('en', 'ja')}
    texts = []
    for chapter in tutorial_chapters.CATALOG:
        texts += [chapter.title, chapter.group, *chapter.learn]
    for task in newbie_tasks.TASKS:
        texts += [task.title, task.hint]
    missing = [(lang, text) for text in texts for lang, table in catalogs.items() if text not in table]
    assert not missing


def test_the_help_menu_opens_the_centre_and_starts_the_chosen_chapter(monkeypatch):
    _app()
    from twobyteasr.app import tutorial_centre
    from twobyteasr.app.ui import MainWindow
    monkeypatch.setattr(tutorial_centre, 'open_tutorial_centre', lambda window, **kw: 'terms')
    started = []
    window = SimpleNamespace(_start_home_tour=started.append)
    MainWindow._open_tutorial_menu(window)
    assert started == ['terms']
    monkeypatch.setattr(tutorial_centre, 'open_tutorial_centre', lambda window, **kw: '')
    MainWindow._open_tutorial_menu(window)
    assert started == ['terms']


def test_a_target_under_the_fixed_bottom_bar_is_scrolled_into_view(monkeypatch):
    """Home page: the 「开始生成字幕」 bar is fixed under a scrolling page; a target behind it is not a dialog."""
    _app()
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout
    monkeypatch.setattr(GuidedTour, 'FLOATING', True)   # Windows: a tool window over the page
    window = QWidget()
    window.resize(900, 600)
    scroll = QScrollArea(window)
    scroll.setGeometry(0, 0, 900, 600)
    scroll.setWidgetResizable(True)
    content = QWidget()
    column = QVBoxLayout(content)
    filler = QWidget()
    filler.setMinimumHeight(520)
    column.addWidget(filler)
    target = QPushButton('内容与术语')
    target.setMinimumHeight(60)
    column.addWidget(target)
    tail = QWidget()
    tail.setMinimumHeight(500)
    column.addWidget(tail)
    scroll.setWidget(content)
    bar = QWidget(window)                                   # the fixed bottom bar over the page
    bar.setGeometry(0, 480, 900, 120)
    bar.setAutoFillBackground(True)
    window.show()
    bar.raise_()
    tour = GuidedTour(window, [TourStep('填游戏名', lambda: target), TourStep('完成')])
    tour.start()
    _until(lambda: tour.mode == 'shown')
    assert tour.index == 0 and scroll.verticalScrollBar().value() > 0
    tour.close_tour(False)
    window.close()


def test_the_export_chapter_teaches_codecs_quality_and_bitrate():
    """User (2026-11-16): people do not know what bitrate 1080p / 4K need, what CQ is, that H.264
    plays everywhere and AV1 is slowest but smallest and best."""
    window = SimpleNamespace(pages=QStackedWidget() if _app() else None, built_page=lambda _name: None)
    steps = tutorial_steps(window, 'render')
    words = ' '.join(f'{step.text} {step.note}' for step in steps)
    for needed in ('H.264', 'HEVC', 'AV1', 'CRF / CQ', '1080p 约 8～12 Mbps', '4K 约 35～45 Mbps', '压得最慢', '预计文件大小'):
        assert needed in words, needed
    assert steps[1].patience >= 30000                       # the project may still be opening
    assert tutorial_chapters.BY_ID['render'].new and not tutorial_chapters.BY_ID['render'].soon
    from twobyteasr.app import newbie_tasks
    assert newbie_tasks.BY_KEY['render'].chapter == 'render'


def test_the_export_chapter_closes_the_export_workspace():
    closed = []
    page = SimpleNamespace(export_workspace=object(), _close_export_workspace=lambda: closed.append(True))
    window = SimpleNamespace(built_page=lambda name: page if name == 'studio' else None)
    tutorial_chapters.cleanup(window, 'render')
    assert closed == [True]


def test_the_how_it_works_chapter_explains_the_pipeline():
    """User (2026-11-16): explain how the software works and why it is accurate (the vote, local rules...)."""
    window = SimpleNamespace(pages=QStackedWidget() if _app() else None, built_page=lambda _name: None)
    words = ' '.join(f'{step.text} {step.note}' for step in tutorial_steps(window, 'how'))
    for needed in ('主力转写', '字幕时间轴', '文字复核', '另外两个模型写法一致', '术语库', '本地规则', '不能改字',
                   '14 个字', '有需复核项', '估算'):
        assert needed in words, needed
    assert tutorial_chapters.CATALOG[1].id == 'how'          # right after the first subtitle


def test_dark_themes_put_white_text_on_all_four_result_cards(monkeypatch):
    """User (2026-11-16): on the dark theme three result cards had black text and one white."""
    _app()
    from twobyteasr.app import completion_widgets
    from twobyteasr.design.ui_theme import contrast_ratio, theme_definition
    dark = theme_definition('grape')
    monkeypatch.setattr(completion_widgets, 'theme_definition', lambda _key: dark)
    cards = [completion_widgets.CompletionActionCard('标题', '说明', 'fa5s.star', hue=hue)
             for hue in ('ai', 'brand', 'export', 'finish')]
    for card in cards:
        title = card.ink_colors()[0]
        assert completion_widgets.QColor(title).lightnessF() > 0.8, (card.hue, title)
        background = card.card_colors()[0]
        assert contrast_ratio(title, background) >= 4.5, (card.hue, title, background)


def test_the_speaker_chapter_closes_its_manager():
    closed = []
    manager = SimpleNamespace(close=lambda: closed.append('close'), deleteLater=lambda: closed.append('delete'))
    window = SimpleNamespace(_tutorial_speakers=manager)
    tutorial_chapters.cleanup(window, 'speakers')
    assert closed == ['close', 'delete'] and '_tutorial_speakers' not in window.__dict__
    from twobyteasr.app import newbie_tasks
    assert newbie_tasks.BY_KEY['speakers'].chapter == 'speakers'


@pytest.mark.parametrize('floating', [False, True])
def test_speaker_practice_uses_a_host_the_tour_can_cover(monkeypatch, floating):
    from PySide6.QtWidgets import QDialog, QLineEdit, QVBoxLayout
    from twobyteasr.studio import studio_speaker_manager
    _app()
    monkeypatch.setattr(GuidedTour, 'FLOATING', floating)
    window = QWidget()
    window.resize(1280, 900)
    page = QWidget(window)
    page.setGeometry(window.rect())
    page.project = SimpleNamespace(speakers=[SimpleNamespace(id='S00', name='主播')])
    monkeypatch.setattr(tutorial_chapters._Studio, 'ready', lambda _self: True)
    monkeypatch.setattr(tutorial_chapters._Studio, 'page', lambda _self: page)
    class PracticeManager(QDialog):
        def __init__(self, parent):
            super().__init__(parent)
            card = QWidget(self)
            card.name_edit = QLineEdit('主播', card)
            card_layout = QVBoxLayout(card)
            card_layout.addWidget(card.name_edit)
            layout = QVBoxLayout(self)
            layout.addWidget(card)
            self.cards = {'S00': card}
            self.resize(700, 500)
    monkeypatch.setattr(studio_speaker_manager, 'SpeakerManagerDialog', PracticeManager)
    window.show()
    steps = tutorial_chapters.speakers_steps(window)
    steps[1].actions[0].run()
    manager = window._tutorial_speakers
    _until(lambda: manager.isVisible() and manager.cards['S00'].name_edit.isVisible())
    tour = GuidedTour(window, steps)
    assert tour._is_ready(2)
    assert manager.isWindow() is floating
    if not floating:
        assert manager.parentWidget() is window and steps[2].host is None
        assert manager.cards['S00'].name_edit.window() is window
    else:
        assert steps[2].host() is manager
    tour.close_tour(False)
    tutorial_chapters.cleanup(window, 'speakers')
    assert '_tutorial_speakers' not in window.__dict__
    window.close()


def test_the_sound_chapter_tells_the_three_volumes_apart():
    window = SimpleNamespace(pages=QStackedWidget() if _app() else None, built_page=lambda _name: None)
    words = ' '.join(f'{step.text() if callable(step.text) else step.text} {step.note}'
                     for step in tutorial_steps(window, 'audio'))
    for needed in ('播放音量', '不改导出', '轨道音量', '工程音量', 'LUFS', '波纹剪除', '剪辑助手'):
        assert needed in words, needed
