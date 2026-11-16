"""Tutorial chapters beyond the first subtitle (2026-11-16).

User (2026-11-16): the tutorial should also teach the editor's newer keys, adding a word to
the glossary and using 「问问兔白」. Each chapter is a list of ``TourStep`` for the same
``GuidedTour`` overlay, started with ``start_home_tour(window, part=<chapter id>)``:

* ``editor``  - the workbench, on the tutorial project: Enter / Esc / Shift+Enter,
  Shift+F / A / D / E / S candidates, Shift+C at the text cursor, Ctrl+A then Alt+← / →,
  = / - zoom, I / O and 「只重新识别这一段字幕…」, J / K / L.
* ``terms``   - the glossary page, on a throw-away 「兔白教学词库」 (deleted when the chapter
  ends): the right spelling + what it is heard as, 「添加」, 「试一句」, 「本批字幕使用」.
* ``bunny``   - 「问问兔白」 with demo answers (``BunnyChat.stand_in``: no AI, nothing billed,
  nothing saved): asking, 「帮我做」, the checklist, 「兔白做过什么」, 「兔白权限」.

``cleanup(window, part)`` undoes what a chapter set up (the window's own ``_tutorial_finish``
already puts the tutorial project away).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import QRectF, QTimer
from PySide6.QtWidgets import QWidget

from ..i18n import tr

CHAPTERS = {
    'editor': ('编辑器新操作与快捷键', 4),
    'terms': ('术语库：加一个词、试一句', 2),
    'bunny': ('问问兔白', 2),
    'render': ('压制导出视频：编码、码率与 CQ', 5),
    'how': ('软件怎么做出字幕', 3),
    'speakers': ('说话人管理', 3),
    'style': ('样式、动效与 AI 设计', 4),
    'audio': ('声音与剪辑', 4),
}
TERMS_LIBRARY = '兔白教学词库'


@dataclass(frozen=True)
class Chapter:
    """One entry of the tutorial centre (2026-11-16, design C)."""
    id: str
    title: str
    minutes: int
    group: str                   # 基础 / 进阶 / 即将推出
    picture: str                 # assets/onboarding/tutorial/<picture>-<theme>-still.png
    learn: tuple
    new: bool = False            # added 2026-11-16: a 「新」 badge until it is finished
    soon: bool = False           # listed, not built yet


CATALOG = (
    Chapter('first', '做出第一份字幕', 3, '基础', 'drop',
            ('选识别方案和视频的语言', '放入示范视频，看三张模型卡', 'AI Key 是什么、要不要填', '开始生成、看结果、导出字幕')),
    Chapter('how', '软件怎么做出字幕', 3, '基础', 'firered',
            ('三个模型各管什么', '三份写法怎么比、哪些留给你挑', '术语库、AI 断句和本地规则', '怎样让字幕更准'), new=True),
    Chapter('fix', '改错字：AI 词库校对', 2, '基础', 'gl_ai',
            ('勾选词库，本机免费找错字', 'AI 校对找词库外的错字', '点建议改正，Ctrl+Z 撤销')),
    Chapter('studio', '字幕工作台基本功', 4, '基础', 'review',
            ('双击或按 E 改字，Enter 保存', '按 R 审核，1 / 2 / 3 选候选', 'C 剃刀、B 合并、Shift+Q / W 波纹合并',
             'T 新增一条、导出和压制')),
    Chapter('editor', '编辑器新操作与快捷键', 4, '进阶', 'edit',
            ('Shift+F / E / S 换人称', 'Shift+C 在光标处切开', 'Ctrl+A 再 Alt+← / → 整片微调',
             'I / O 框一段，只重新识别这一段', '= / - 缩放时间轴、J / K / L 播放'), new=True),
    Chapter('terms', '术语库：加一个词、试一句', 2, '进阶', 'glossary',
            ('用一本教学词库，学完自动删除', '写正确写法和常被听成的错字', '「试一句」马上看会改成什么',
             '本批字幕使用、AI 帮忙'), new=True),
    Chapter('bunny', '问问兔白', 2, '进阶', 'key_what',
            ('怎么问她（示范回答，不花钱）', '「帮我做」按了才会做', '步骤清单、兔白做过什么', '兔白权限三档'), new=True),
    Chapter('render', '压制导出视频：编码、码率与 CQ', 5, '进阶', 'burn',
            ('H.264、HEVC、AV1 怎么选', 'CRF / CQ 是什么、数字怎么定', '1080p 和 4K 该用多少码率',
             '预设、音频、预计大小、先导出一小段'), new=True),
    Chapter('speakers', '说话人管理', 3, '进阶', 'speakers',
            ('改名、换颜色、合并同一个人', '字幕前显示名字、分主播导出'), new=True),
    Chapter('style', '样式、动效与 AI 设计', 4, '进阶', 'punct',
            ('样式预设、只改译文或某个说话人', '在画面上拖字幕位置', '动效时间线、卡拉 OK', '一句话生成字幕设计'), new=True),
    Chapter('audio', '声音与剪辑', 4, '进阶', 'qw',
            ('播放音量、轨道调音台、工程响度', 'Ctrl+K 分割、波纹剪除、转场', '素材和剪辑助手'), new=True),
)
BY_ID = {chapter.id: chapter for chapter in CATALOG}
OWN_STEPS = ('editor', 'terms', 'bunny', 'render', 'how', 'speakers', 'style', 'audio')                 # steps written in this module
STANDALONE = ('fix', 'studio') + OWN_STEPS              # set up their own demo data, start where they are


def is_chapter(part: str) -> bool:
    """A chapter that runs on its own (no home page, no plan chooser, not the first-run tutorial)."""
    return part in STANDALONE


def steps(window, part: str) -> list:
    build = {'editor': editor_steps, 'terms': terms_steps, 'bunny': bunny_steps, 'render': render_steps,
             'how': how_steps, 'speakers': speakers_steps, 'style': style_steps, 'audio': audio_steps}[part]
    found = build(window)
    for step in found:
        step.chapter = {'editor': '编辑器', 'terms': '术语库', 'bunny': '问问兔白', 'render': '压制',
                        'how': '原理', 'speakers': '说话人', 'style': '样式', 'audio': '声音剪辑'}[part]
    return found


# ---------------------------------------------------------------- the workbench
def editor_steps(w) -> list:
    from .home_tour import TourAction, TourStep

    def studio():
        return w.built_page('studio') if hasattr(w, 'built_page') else None

    def studio_ready():
        page = studio()
        readiness = getattr(page, '_readiness', None)
        return (page is not None and w.pages.currentWidget() is page and page.project is not None
                and _is_tutorial_project(page) and (readiness is None or (readiness.ready and not readiness.active)))

    def open_demo():
        page = studio()
        if page is not None and page.project is not None and _is_tutorial_project(page):
            if w.pages.currentWidget() is not page:
                w._switch_page(page)
            return
        from .sample_project import ensure_tutorial_project
        w.open_studio_project(str(ensure_tutorial_project()))

    def editor():
        page = studio()
        inline = getattr(getattr(page, 'timeline', None), '_inline_editor', None)
        if inline is not None:
            return inline
        return getattr(page, 'subtitle_edit_card', None) if getattr(page, '_canvas_editor', None) is not None else None

    def editing_id():
        page = studio()
        draft = getattr(page, '_caption_draft', None)
        if page is None or draft is None or editor() is None:
            return ''
        try:
            cue = draft.target.resolve(page.project)
        except Exception:  # noqa: BLE001
            return ''
        return getattr(cue, 'id', '') or ''

    def cue(cue_id):
        project = getattr(studio(), 'project', None)
        return next((item for item in getattr(project, 'cues', ()) if item.id == cue_id), None)

    def block(cue_ids):
        page = studio()
        timeline = getattr(page, 'timeline', None)
        if timeline is None:
            return None
        rect = QRectF()
        try:
            rows, _track, _wave = timeline._track_layout()
            for item in getattr(timeline, '_cues_by_start', ()):
                if item.id not in cue_ids:
                    continue
                band = timeline._cue_band(item, rows[item.speaker_id])
                left = max(timeline.TRACK_HEADER_WIDTH, timeline._time_to_x(item.start_ms))
                right = min(timeline._content_right(), timeline._time_to_x(item.end_ms))
                piece = QRectF(left, band.top() + 7, max(4, right - left), band.height() - 14)
                rect = piece if rect.isNull() else rect.united(piece)
            return None if rect.isNull() else (timeline, rect.intersected(timeline._track_viewport()))
        except Exception:  # noqa: BLE001
            return None

    def part(name):
        return lambda: getattr(studio(), name, None)

    def pause():
        page = studio()
        video = getattr(page, 'video', None)
        if video is not None and not getattr(video, '_paused', True):
            try:
                video.set_paused(True)
                page._sync_play_button(True)
            except Exception:  # noqa: BLE001
                pass

    def close_editor():
        page = studio()
        if page is None:
            return
        if getattr(page.timeline, '_inline_editor', None) is not None:
            page.timeline._commit_inline_edit()
        elif getattr(page, '_canvas_editor', None) is not None:
            page._commit_canvas_inline_edit(advance=False)

    def edit(cue_id, caret_after=''):
        """Open the editor on a line, the text cursor just after ``caret_after``."""
        def run():
            pause()
            page = studio()
            if page is None or page.project is None:
                return
            if editing_id() != cue_id:
                close_editor()
                page.select_cue(cue_id)
                page._begin_canvas_inline_edit()
            # Keep the chosen practice cue while the guide owns focus and the
            # paused video clock still points at another line.
            page._lock_caption_editor()
            if caret_after:
                QTimer.singleShot(120, lambda: place_caret(caret_after))
        return run

    def place_caret(after):
        box = getattr(studio(), 'subtitle_edit_input', None)
        if box is None:
            return
        text = box.toPlainText()
        at = text.find(after)
        if at < 0:
            return
        cursor = box.textCursor()
        cursor.setPosition(at + len(after))
        box.setTextCursor(cursor)
        studio()._lock_caption_editor()
        box.setFocus()

    def editor_input():
        return getattr(studio(), 'subtitle_edit_input', None)

    def keys_here():
        return getattr(studio(), 'timeline', None)

    def split_done():
        project = getattr(studio(), 'project', None)
        return any(item.id.startswith('tutorial-6-split-') for item in getattr(project, 'cues', ()))

    def split_at_caret():
        # Clicking a guide button is outside the floating editor: its normal
        # focus rule commits it before this callback. Restore the practice
        # binding and insertion point before invoking the real split command.
        edit('tutorial-6')()
        place_caret('纪行的')
        studio()._split_caption_at_cursor()

    def change_pronoun():
        edit('tutorial-8')()
        place_caret('她')
        button = pronoun_button()
        if button is not None:
            button.click()

    mark = {'start': None, 'zoom': None}

    def remember_start():
        close_editor()
        pause()
        item = cue('tutorial-1')
        mark['start'] = item.start_ms if item is not None else None
        page = studio()
        if page is not None:
            page.select_cue('tutorial-1')

    def moved():
        item = cue('tutorial-1')
        return item is not None and mark['start'] is not None and item.start_ms != mark['start']

    def move_all_earlier():
        page = studio()
        page._select_all_timeline_cues()
        from ..studio.studio_shortcut_actions import _nudge
        _nudge(page, -100)

    def remember_zoom():
        pause()
        timeline = getattr(studio(), 'timeline', None)
        mark['zoom'] = getattr(timeline, 'visible_duration_ms', None)

    def zoomed():
        timeline = getattr(studio(), 'timeline', None)
        return timeline is not None and mark['zoom'] is not None and timeline.visible_duration_ms != mark['zoom']

    def range_set():
        project = getattr(studio(), 'project', None)
        if project is None:
            return False
        from ..projects.project_range import range_points
        start, end = range_points(project)
        return start is not None and end is not None

    def mark_range():
        page = studio()
        page._seek(6.4)
        page._mark_in()
        page._seek(11.8)
        page._mark_out()

    def key(action_id):
        from ..studio.shortcut_registry import tooltip_key
        name = str(tr(tooltip_key(action_id)))
        for word, arrow in (('Left', '←'), ('Right', '→'), ('Up', '↑'), ('Down', '↓')):
            name = name.replace(word, arrow)
        return name

    def pronoun_button():
        card = getattr(studio(), 'subtitle_edit_card', None)
        button = getattr(card, 'pronoun_button', None)
        return button if button is not None and button.isVisible() else editor()

    return [
        TourStep('这一章学工作台里==更快的改法==；用示范工程练，改坏了也没关系', None,
                 note='示范工程正在打开，看完这句它就好了', enter=open_demo, anim='studio_open'),
        TourStep('==双击==这条打开编辑（或按 **E**）', lambda: block(['tutorial-2']),
                 [TourAction('帮我做', edit('tutorial-2'))], show_next=False, interactive=True, enter=pause,
                 done=lambda: editing_id() != '', ready=studio_ready, focus=keys_here, anim='edit', page=open_demo,
                 patience=45000),
        TourStep('改完按 **Enter** 保存，**Esc** 取消', editor,
                 [TourAction('帮我做', close_editor)],
                 note='**Shift+Enter** 在这条里换行；编辑框上方会提示能用的按键', show_next=False, interactive=True,
                 done=lambda: editor() is None, ready=lambda: editor() is not None,
                 focus=editor_input, anim='edit'),
        TourStep('光标在「她」后面，按 **Shift+F** 换人称（他 / 她 / 它）', pronoun_button,
                 [TourAction('帮我按 Shift+F', change_pronoun)],
                 note='**Shift+E** 采纳，**Shift+S** 回到正文；高亮的修改候选用 **Shift+A / D** 切换', interactive=True,
                 enter=edit('tutorial-8', '她'), ready=lambda: studio_ready() and editing_id() == 'tutorial-8',
                 focus=editor_input, anim='edit', page=open_demo),
        TourStep('光标放在「纪行的」后面，按 **Shift+C** ==在光标处切成两条==',
                 editor, [TourAction('帮我切开', split_at_caret)],
                 note='切错了按 **Ctrl+Z** 撤销', show_next=False, interactive=True,
                 enter=edit('tutorial-6', '纪行的'), done=split_done,
                 ready=lambda: studio_ready() and editing_id().startswith('tutorial-6'), focus=editor_input,
                 anim='razor', page=open_demo),
        TourStep('按 **Enter** 保存，**Esc** 取消', editor,
                 [TourAction('帮我做', close_editor)], show_next=False, interactive=True,
                 done=lambda: editor() is None, optional=True),
        TourStep(lambda: tr('整片都差一点：先按 **{value0}** 全选，再按 **{value1}** 提前 0.1 秒',
                            value0=key('select_all'), value1=key('nudge_earlier')),
                 part('timeline'), [TourAction('帮我做', move_all_earlier)],
                 note=lambda: tr('**{value0}** 推后；字幕晚了半秒就按 5 次', value0=key('nudge_later')),
                 show_next=False, interactive=True, enter=remember_start, done=moved, ready=studio_ready,
                 focus=keys_here, anim='qw', page=open_demo),
        TourStep(lambda: tr('字幕挤在一起看不清：按 **{value0}** 放大时间轴，**{value1}** 缩小',
                            value0=key('timeline_zoom_in'), value1=key('timeline_zoom_out')),
                 part('timeline'), [TourAction('帮我做', lambda: studio()._zoom_timeline(0.8))],
                 note=lambda: tr('**{value0}** 一眼看到整部片；按住 Ctrl 滚轮也行', value0=key('timeline_fit')),
                 show_next=False, interactive=True, enter=remember_zoom, done=zoomed, ready=studio_ready,
                 focus=keys_here, page=open_demo),
        TourStep(lambda: tr('播放头放到一段开头按 **{value0}**，结尾按 **{value1}**，把这一段框起来',
                            value0=key('mark_in'), value1=key('mark_out')),
                 part('timeline'), [TourAction('帮我框', mark_range)],
                 note='同一位置再按一次就取消', show_next=False, interactive=True, enter=pause, done=range_set,
                 ready=studio_ready, focus=keys_here, page=open_demo),
        TourStep('框好后在时间轴上**右键** →「==只重新识别这一段字幕…==」：只重做这一段，别的字幕不动',
                 part('timeline'), note='中间一段没字幕、或这一段识别得很差时用；教学里先不真的跑',
                 ready=studio_ready, page=open_demo),
        TourStep(lambda: tr('**{value0} / {value1} / {value2}** 倒放、暂停、快放；**{value3} / {value4}** 上一条、下一条字幕',
                            value0=key('reverse'), value1=key('pause'), value2=key('forward'),
                            value3=key('previous_cue'), value4=key('next_cue')),
                 part('video'), note=lambda: tr('**{value0}** 播放 / 暂停，**{value1}** 循环播放当前这条',
                                                value0=key('play_pause'), value1=key('loop_cue')),
                 ready=studio_ready, enter=pause, page=open_demo),
        TourStep('编辑器学会啦！所有按键都能在「==设置 → 快捷键==」改', next_label='完成'),
    ]


def _is_tutorial_project(page) -> bool:
    import os
    from .sample_project import tutorial_project_path
    path = str(getattr(page, 'project_path', '') or '')
    if not path:
        return False
    return os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(str(tutorial_project_path())))


# ---------------------------------------------------------------- shared by the workbench chapters
class _Studio:
    """The workbench on the tutorial project, for the chapters below (2026-11-16)."""

    def __init__(self, w):
        self.w = w

    def page(self):
        return self.w.built_page('studio') if hasattr(self.w, 'built_page') else None

    def ready(self):
        page = self.page()
        readiness = getattr(page, '_readiness', None)
        return (page is not None and self.w.pages.currentWidget() is page and page.project is not None
                and _is_tutorial_project(page) and (readiness is None or (readiness.ready and not readiness.active)))

    def open(self):
        page = self.page()
        if page is not None and page.project is not None and _is_tutorial_project(page):
            if self.w.pages.currentWidget() is not page:
                self.w._switch_page(page)
            return
        from .sample_project import ensure_tutorial_project
        self.w.open_studio_project(str(ensure_tutorial_project()))

    def part(self, name):
        def find():
            widget = getattr(self.page(), name, None)
            return widget if widget is not None and widget.isVisible() else None
        return find

    def tab(self, attribute_or_index):
        """Show a tab of the right-hand tool panel (样式 1, 动效, AI设计 0, 素材, 剪辑助手)."""
        def run():
            page = self.page()
            if page is None or not hasattr(page, '_toggle_drawer'):
                return
            index = attribute_or_index if isinstance(attribute_or_index, int) else getattr(page, attribute_or_index, None)
            if index is not None:
                page._toggle_drawer(int(index))
        return run

    def pause(self):
        page = self.page()
        video = getattr(page, 'video', None)
        if video is not None and not getattr(video, '_paused', True):
            try:
                video.set_paused(True)
                page._sync_play_button(True)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------- 说话人管理
def speakers_steps(w) -> list:
    """说话人管理 (2026-11-16): rename, colour, merge, names before lines, per-speaker export.
    The manager is opened without blocking (``show``) so the tutorial's buttons keep working;
    it is closed when the chapter ends."""
    from .home_tour import TourAction, TourStep
    s = _Studio(w)
    names = {}

    def dialog():
        found = w.__dict__.get('_tutorial_speakers')
        try:
            return found if found is not None and found.isVisible() else None
        except RuntimeError:
            return None

    def open_manager():
        if dialog() is not None or not s.ready():
            return
        from ..studio.studio_speaker_manager import SpeakerManagerDialog
        page = s.page()
        names.update({speaker.id: speaker.name for speaker in page.project.speakers})
        manager = SpeakerManagerDialog(page)
        manager.setModal(False)
        w._tutorial_speakers = manager
        manager.show()

    def card(key='S00'):
        def find():
            manager = dialog()
            if manager is None:
                return None
            try:
                widget = manager.cards[key]
            except Exception:  # noqa: BLE001
                return None
            return widget if widget is not None and widget.isVisible() else None
        return find

    def card_part(name, key='S00'):
        def find():
            widget = getattr(card(key)(), name, None)
            return widget if widget is not None and widget.isVisible() else None
        return find

    def renamed():
        page = s.page()
        speaker = next((item for item in getattr(page.project, 'speakers', ()) if item.id == 'S00'), None) \
            if page is not None and page.project is not None else None
        return speaker is not None and bool(names) and speaker.name != names.get('S00')

    def rename():
        found = card()()
        if found is None:
            return
        found.name_edit.setText(str(tr('兔白主播')))
        dialog()._card_commit_name(found)

    def show_names_box():
        box = getattr(dialog(), 'show_names', None)
        return box if box is not None and box.isVisible() else None

    def tick_names():
        box = show_names_box()
        if box is not None and not box.isChecked():
            box.setChecked(True)

    def speaker_button():
        page = s.page()
        button = getattr(page, 'speaker_manager_button', None)
        if button is not None and button.isVisible():
            return button
        toolbar = getattr(page, 'studio_toolbar', None)   # a narrow window keeps it in 「…」
        for child in toolbar.findChildren(QWidget) if toolbar is not None else ():
            if child.property('commandSource') == '更多工作区操作' and child.isVisible():
                return child
        return None

    host = dialog
    return [
        TourStep('这一章学==说话人管理==：改名、换颜色、合并同一个人、字幕前带名字', None,
                 note='用示范工程练习；它有「主播」和「嘉宾」两位', enter=s.open, anim='speakers'),
        TourStep('点「==说话人管理==」打开', speaker_button,
                 [TourAction('帮我打开', open_manager)], show_next=False, interactive=True,
                 click=TourAction('', open_manager), done=lambda: dialog() is not None,
                 ready=s.ready, page=s.open, patience=45000,
                 anim='speakers'),
        TourStep('识别出来的名字是「说话人1」这类标签：==直接改成真名==，按 Enter 保存', card_part('name_edit'),
                 [TourAction('帮我改', rename)], show_next=False, interactive=True, done=renamed,
                 ready=lambda: card_part('name_edit')() is not None, focus=card_part('name_edit'), host=host),
        TourStep('点色块==换颜色==：时间轴和字幕列表都用这个颜色认人', card_part('swatch'),
                 ready=lambda: card_part('swatch')() is not None, host=host),
        TourStep('同一个人被分成两个时，用「==合并到==」把字幕并过去', card_part('merge_button'),
                 note='分错的单条字幕，也可以在时间轴上拖到另一位的轨道', ready=lambda: card_part('merge_button')() is not None,
                 host=host, optional=True),
        TourStep('勾「==字幕前显示名字==」：每句前面带上名字（兔白主播：你好）', show_names_box,
                 [TourAction('帮我勾', tick_names)], note='预览、导出的字幕都会带上；先把名字改好再勾',
                 show_next=False, interactive=True, done=lambda: bool(show_names_box() and show_names_box().isChecked()),
                 ready=lambda: show_names_box() is not None, host=host, optional=True),
        TourStep('导出字幕时可以==每个说话人一份==；样式也能按说话人分开设', None,
                 note='「导出字幕」里选说话人分开；「样式」的应用到选「说话人」。首页「高级设置」可以先填预计说话人数'),
        TourStep('说话人管理学会啦！', next_label='完成', note='名字改好再导出，剪辑软件里一眼就分得清谁在说'),
    ]


def _close_speakers(w) -> None:
    manager = w.__dict__.pop('_tutorial_speakers', None)
    if manager is not None:
        try:
            manager.close()
            manager.deleteLater()
        except RuntimeError:
            pass


# ---------------------------------------------------------------- 样式、动效与 AI 设计
def style_steps(w) -> list:
    """样式、动效与 AI 设计 (2026-11-16): presets, the language layer, apply-to scope, dragging the
    caption on the picture, the motion timeline and AI design. Nothing is generated or saved."""
    from .home_tour import TourStep
    s = _Studio(w)
    on = s.ready
    return [
        TourStep('这一章学==字幕样式==、==动效==和 ==AI 设计==', None,
                 note='用示范工程练习，改了也不会影响你的工程', enter=s.open, anim='punct'),
        TourStep('右边「样式」的==样式预设==：一键换整套字体、颜色、描边', s.part('style_preset'),
                 note='复制 / 粘贴一条字幕的样式：**Ctrl+Shift+C / Ctrl+Shift+V**', enter=s.tab(1),
                 ready=lambda: on() and s.part('style_preset')() is not None, page=s.tab(1), patience=45000),
        TourStep('双语时先选==改哪一层==：原文、译文或整组', s.part('style_layer'),
                 note='例如只让译文有黄色描边：这里选「译文」再改', enter=s.tab(1), ready=on, page=s.tab(1),
                 optional=True),
        TourStep('「应用到」：当前这条、已选的、==该说话人==或全部', s.part('style_scope'),
                 note='给某一位说话人一种颜色，就选「说话人」', enter=s.tab(1), ready=on, page=s.tab(1)),
        TourStep('字幕位置：在画面上==按住字幕直接拖==，松手才生效', s.part('video'),
                 note='双语时按住哪一层就拖哪一层；拖错了按 Esc 取消', enter=s.pause, ready=on, page=s.open),
        TourStep('「动效」：时间线分入场、停留、出场；==拖把手改长短==', s.part('motion_panel'),
                 note='一次拖动可以一步撤销。卡拉 OK 类效果会让颜色沿着语音一个字一个字扫过', enter=s.tab('motion_tab_index'),
                 ready=on, page=s.tab('motion_tab_index'), optional=True),
        TourStep('「AI设计」：用一句话描述想要的样子', s.part('ai_prompt'),
                 note='例如「可爱的粉色圆体，白色粗描边」；要先设置文字 AI', enter=s.tab(0), ready=on, page=s.tab(0),
                 optional=True),
        TourStep('点「==生成字幕设计==」出几套方案，选一套应用；满意就==保存样式==', s.part('ai_generate'),
                 note='教学里先不生成；保存后的样式会出现在样式预设里', enter=s.tab(0), ready=on, page=s.tab(0),
                 optional=True),
        TourStep('样式学会啦！', next_label='完成', note='SRT 只有文字；要带样式就导出 ASS，或直接压制成片'),
    ]


# ---------------------------------------------------------------- 声音与剪辑
def audio_steps(w) -> list:
    """声音与剪辑 (2026-11-16): playback volume vs track gain vs project loudness, Ctrl+K, ripple
    cuts, transitions, the media pool and the clip assistant. Only pointed at; nothing is cut."""
    from .home_tour import TourStep
    s = _Studio(w)
    on = s.ready

    def key(action_id):
        from ..studio.shortcut_registry import tooltip_key
        return str(tr(tooltip_key(action_id)))

    return [
        TourStep('这一章学==声音==和==剪辑==：三种音量分清楚，再学几下剪辑', None,
                 note='用示范工程，只看不真的剪', enter=s.open, anim='qw'),
        TourStep('这是==播放音量==：只影响你自己耳朵听到的，==不改导出==', s.part('volume_slider'),
                 enter=s.pause, ready=lambda: on() and s.part('volume_slider')() is not None, page=s.open,
                 patience=45000),
        TourStep(lambda: tr('按 **{value0}** 打开==轨道音量==调音台：每条音轨一个推子', value0=key('track_gain')),
                 s.part('timeline'), note='例如游戏声小 6 分贝、麦克风不动；范围 -60 到 +24 分贝，一次应用可整体撤销',
                 ready=on, page=s.open),
        TourStep('==工程音量 / 响度==：一段很轻一段很吵时用', s.part('project_loudness_button'),
                 note='先「重新测量」，再选目标（面板里有平台建议的 LUFS），最后一键匹配；试听音量另外调',
                 ready=on, page=s.open, optional=True),
        TourStep(lambda: tr('**{value0}** 在播放头把视频切开（所有没锁的视频轨）', value0=key('split_at_playhead')),
                 s.part('timeline'), ready=on, page=s.open),
        TourStep(lambda: tr('选中视频片段按 **{value0} / {value1}**：==波纹剪除==播放头前面 / 后面那段',
                            value0=key('trim_start'), value1=key('trim_end')),
                 s.part('timeline'), note='后面的会自动往前补上。剪掉开头的废片：播放头放到要留的第一帧，选中视频按前面那个键',
                 ready=on, page=s.open),
        TourStep(lambda: tr('**{value0} / {value1}** 加默认的视频 / 音频转场', value0=key('video_transition'),
                            value1=key('audio_transition')), s.part('timeline'), ready=on, page=s.open),
        TourStep('「素材」分页：加别的素材，拖到时间轴上', s.part('context_drawer'),
                 note='双击素材在「源素材」里预览，设好入点出点再加进视频或音频', enter=s.tab('media_pool_tab_index'),
                 ready=on, page=s.tab('media_pool_tab_index'), optional=True),
        TourStep('「剪辑助手」：找值得剪的片段、压缩口播停顿', s.part('context_drawer'),
                 note='能读字幕和 B 站弹幕 XML 找直播切片候选，挑好后生成剪辑', enter=s.tab('highlight_tab_index'),
                 ready=on, page=s.tab('highlight_tab_index'), optional=True),
        TourStep('声音与剪辑学会啦！', next_label='完成', note='想只导出中间一段，用 I / O 设入点出点，导出时选「入点到出点」'),
    ]


# ---------------------------------------------------------------- how the subtitles are made
def how_steps(w) -> list:
    """软件怎么做出字幕 (2026-11-16, user): how the recognition works and why it is accurate, so the
    settings make sense: the three models' roles, the vote between their writings, the glossary,
    AI that only chooses the breaks, the local rules, the timing finish, and what helps most.
    Written from the default local plan (README 「运作方式」); the home page's cards are pointed at."""
    from .home_tour import TourStep

    def home():
        if w.pages.currentWidget() is not w.__dict__.get('settings_scroll'):
            w._return_to_settings()

    def on_home():
        return w.pages.currentWidget() is w.__dict__.get('settings_scroll')

    def role_card(role):
        return lambda: (getattr(w.__dict__.get('recognition_plan'), 'cards', None) or {}).get(role)

    def get(name):
        return lambda: w.__dict__.get(name)

    return [
        TourStep('这一章讲软件==怎么做出这么准的字幕==：懂了原理，就知道哪里该调', None,
                 note='以默认的本机方案（MOSS + FireRed + Qwen）来讲；换别的方案时分工一样', enter=home, anim='moss'),
        TourStep('① **主力转写**先听完整段：==写出文字、分出谁在说话==', role_card('primary'),
                 note='它是整份字幕的骨架：句子和说话人以它为准。同时人声检测找出真正有人说话的区间',
                 ready=on_home, page=home, anim='moss'),
        TourStep('② **字幕时间轴**给==每个字==标上起止时间', role_card('timeline'),
                 note='中文用 FireRedASR2，日语、英语等用 Qwen3 对齐。断句和切分都沿着字的边界，所以字幕出现、消失都准',
                 ready=on_home, page=home, anim='firered'),
        TourStep('③ **文字复核**用另一个模型==再听一遍==，另写一份', role_card('review'),
                 note='关掉它也能用，只是少了一份对照', ready=on_home, page=home, anim='qwen'),
        TourStep('④ 三份写法比一比：==另外两个模型写法一致==、又通过安全检查，才自动换掉', None,
                 note='其余写法不同的地方留作候选，在工作台按 **R** 审核时由你挑。结果页说「有需复核项」就是这个，不是出错',
                 anim='review'),
        TourStep('⑤ 再按==术语库==纠错：只照你确认过的写法改', get('batch_glossary_card'),
                 note='识别成「常被听成」的写法时才改。填对游戏名、打开词库，人名和专有名词就写对了',
                 ready=on_home, page=home, anim='glossary', optional=True),
        TourStep('⑥ 断句：==本地规则==或 ==AI==；AI 只决定在哪里断开，==不能改字==', get('home_process_card'),
                 note='中文一条最多 14 个字，一句完整的话尽量放在一条；英语一条最多 40 个字符。AI 断句失败的地方自动退回本地规则，结果页可以重试',
                 ready=on_home, page=home, anim='ai_lock', optional=True),
        TourStep('⑦ 最后整理时间：按阅读速度补足显示、对齐画面帧，==不拖到下一句开口==', None,
                 note='真正开口、收尾以逐字时间为准；可能漏掉的人声会标出来让你试听，不会自己乱补'),
        TourStep('想要更准：选对==视频语言==、填==游戏名==、常错的名字加进==术语库==', get('spoken_language_field'),
                 note='「识别方案」选质量优先最准，快速轻量最快，拿不准就用推荐。声音清楚、背景音乐小也会更准',
                 ready=on_home, page=home, anim='spoken', optional=True),
        TourStep('用云端识别时：服务商只负责写文字，==逐字时间==由本机对齐模型补上', None,
                 note='只回传句段时间的云端服务，字幕时间会标「估算」；本机识别不上传，文字 AI 只发送字幕文字'),
        TourStep('原理学会啦！识别完先按 **R** 看候选，再导出', next_label='完成',
                 note='想知道某一步具体怎么调，可以直接问兔白'),
    ]


# ---------------------------------------------------------------- burning subtitles into a video
def render_steps(w) -> list:
    """压制成片 (2026-11-16, user): the export workspace on the tutorial project, plus what people
    usually do not know: H.264 / HEVC / AV1, CRF / CQ, and the bitrate a 1080p or 4K video needs.
    Nothing is exported; the workspace is closed when the chapter ends (``cleanup``)."""
    from .home_tour import TourAction, TourStep

    def studio():
        return w.built_page('studio') if hasattr(w, 'built_page') else None

    def project_ready():
        page = studio()
        readiness = getattr(page, '_readiness', None)
        return (page is not None and page.project is not None and _is_tutorial_project(page)
                and (readiness is None or (readiness.ready and not readiness.active)))

    def open_demo():
        page = studio()
        if page is not None and page.project is not None and _is_tutorial_project(page):
            if w.pages.currentWidget() is not page:
                w._switch_page(page)
            return
        from .sample_project import ensure_tutorial_project
        w.open_studio_project(str(ensure_tutorial_project()))

    def workspace():
        found = getattr(studio(), 'export_workspace', None)
        try:
            return found if found is not None and found.isVisible() else None
        except RuntimeError:
            return None

    def open_workspace():
        if workspace() is None and project_ready():
            studio()._open_render_dialog()

    def part(name):
        def find():
            widget = getattr(workspace(), name, None)
            return widget if widget is not None and widget.isVisible() else None
        return find

    def advanced_open():
        card = getattr(workspace(), 'advanced_card', None)
        if card is not None:
            try:
                card.set_expanded(True, notify=False)
            except TypeError:
                card.set_expanded(True)

    def studio_button():
        page = studio()
        button = getattr(page, 'studio_render_button', None)
        return button if button is not None and button.isVisible() else None

    on_page = lambda: workspace() is not None   # noqa: E731

    return [
        TourStep('这一章学==压制成片==：把字幕烧进视频，顺便弄懂编码、码率和 CQ', None,
                 note='用示范工程练习，教学里不会真的导出', enter=open_demo, anim='burn'),
        TourStep('点「==导出音视频==」打开压制（快捷键 **Ctrl+Shift+E**）', studio_button,
                 [TourAction('帮我打开', open_workspace)], show_next=False, interactive=True,
                 done=on_page, ready=lambda: project_ready() and studio_button() is not None,
                 page=open_demo, patience=45000, anim='burn'),
        TourStep('先挑==预设==：拿不准就用「推荐」', part('preset_chips'),
                 note='「快速导出」先看效果，「高质量」画质优先，「小体积」省空间，「AV1 高压缩」最小但最慢',
                 ready=on_page, page=open_workspace, patience=15000),
        TourStep('==H.264==：哪里都能播（手机、剪辑软件、所有网站），最稳妥', part('codec'),
                 note='不知道选什么，选 H.264 就不会错', ready=on_page, page=open_workspace),
        TourStep('==HEVC / H.265==：同样画质，文件约小三到五成；较新的电脑和手机才播得顺', part('codec'),
                 note='有的老电视、老手机和网页播放器不支持', ready=on_page, page=open_workspace),
        TourStep('==AV1==：画质最好、文件最小，但==压得最慢==', part('codec'),
                 note='适合存档或上传支持 AV1 的平台；显卡支持 AV1 编码时会快很多，老设备可能放不了',
                 ready=on_page, page=open_workspace),
        TourStep('分辨率一般选「==跟随源视频==」', part('resolution'),
                 note='1080p 放大成 4K 不会更清楚，只会更大；想省空间可以降到 1080p', ready=on_page,
                 page=open_workspace),
        TourStep('「质量」：推荐就够；要更清楚选高质量，要文件小选体积优先', part('quality'),
                 ready=on_page, page=open_workspace),
        TourStep('「高级编码」里是==质量控制方式==：按画质压（CRF / CQ）还是按码率压', part('rate_control_choice'),
                 note='CRF / CQ：画质固定，文件大小随画面变；目标码率：大小可预估，适合有上传大小限制时',
                 enter=advanced_open, ready=on_page, page=open_workspace, optional=True),
        TourStep('CRF / CQ ==数字越小越清楚、文件越大==', part('quality_value'),
                 note='常用：H.264 约 18～23，HEVC 约 20～28，AV1 约 25～35；每加 6 左右文件约小一半。'
                      '显卡编码器的 CQ 和 CRF 同一个数字画质不一样',
                 enter=advanced_open, ready=on_page, page=open_workspace, optional=True),
        TourStep('按码率压时参考（H.264）：==1080p 约 8～12 Mbps==，==4K 约 35～45 Mbps==', part('rate_control_choice'),
                 note='60 帧要多约一半（1080p 12～16、4K 50～68）；1440p 约 16～24。HEVC 约用七成、AV1 约一半就同样清楚。'
                      '平台还会再压一次，传得再高也看不出',
                 enter=advanced_open, ready=on_page, page=open_workspace, optional=True),
        TourStep('音频：「直接复制」最快、不损失；要统一格式就选 AAC 192 kbps', part('audio'),
                 ready=on_page, page=open_workspace),
        TourStep('这里显示设置摘要和==预计文件大小==，改设置会跟着变', part('estimated_size'),
                 note='恒定质量（CRF / CQ）时没法预先算出大小', ready=on_page, page=open_workspace, optional=True),
        TourStep('都好了点「==开始导出==」；不确定就先导出一小段看看', part('export_button'),
                 note='先用 I / O 设好入点出点，范围选「入点到出点」；「加入队列」可以排好几个一起压',
                 ready=on_page, page=open_workspace),
        TourStep('压制学会啦！拿不准就用「推荐」＋ H.264', next_label='完成',
                 note='想要文件小、画质好又不赶时间，试试 AV1'),
    ]


def _close_render_workspace(w) -> None:
    page = w.built_page('studio') if hasattr(w, 'built_page') else None
    if page is not None and getattr(page, 'export_workspace', None) is not None:
        page._close_export_workspace()


# ---------------------------------------------------------------- the glossary
def terms_steps(w) -> list:
    from .home_tour import TourAction, TourStep

    def library():
        shell = getattr(w, 'term_library_page', None)
        return getattr(shell, 'library', None) if shell is not None else None

    def on_page():
        shell = getattr(w, 'term_library_page', None)
        return shell is not None and w.pages.currentWidget() is shell and library() is not None

    def part(name):
        return lambda: getattr(library(), name, None)

    def open_library():
        w._manage_terms()
        shell = w.term_library_page
        page = shell._ensure_library()
        identity = w.__dict__.get('_tutorial_terms_library')
        if not identity:
            identity = w.legacy.create_learned_content(TERMS_LIBRARY, create_new=True)
            w._tutorial_terms_library = identity
        page.add_game_item(TERMS_LIBRARY, select=True, library_id=identity)

    def selected():
        page = library()
        item = page.game_list.currentItem() if page is not None else None
        return on_page() and item is not None and str(item.data(256) or item.text()) == TERMS_LIBRARY

    def library_item():
        page = library()
        if page is None:
            return None
        for row in range(page.game_list.count()):
            item = page.game_list.item(row)
            if str(item.data(256) or item.text()) == TERMS_LIBRARY:
                page.game_list.scrollToItem(item)
                return page.game_list.viewport(), QRectF(page.game_list.visualItemRect(item))
        return page.game_list

    def text_of(name):
        box = getattr(library(), name, None)
        return box.text().strip() if box is not None else ''

    def fill(name, value):
        def run():
            box = getattr(library(), name, None)
            if box is not None:
                box.setText(value)
                box.setFocus()
        return run

    def word_saved():
        identity = w.__dict__.get('_tutorial_terms_library')
        if not identity:
            return False
        try:
            mappings = w.legacy.learned_mappings_for_game(identity)
        except Exception:  # noqa: BLE001
            return False
        return '派蒙' in json.dumps(mappings, ensure_ascii=False, default=str)

    def open_try():
        page = library()
        if page is not None and page.term_try_panel.isHidden():
            page._toggle_try_panel()

    def try_line():
        page = library()
        if page is None:
            return
        open_try()
        page.term_try_input.setText('派门又在旁边说个不停')   # the demo words are the data, not UI text
        page.try_sentence()

    def tried():
        page = library()
        return page is not None and page.term_try_panel.isVisible() and bool(page.term_try_result.text().strip())

    return [
        TourStep('这是**术语库**：每个游戏一本「==正确写法小本本==」，识别和校对都照着改',
                 library_item, note='教学先用一本「兔白教学词库」，学完会自动删掉',
                 enter=open_library, ready=selected, page=open_library, anim='glossary'),
        TourStep('在这里写==正确写法==：「派蒙」', part('term_editor'),
                 [TourAction('帮我填', fill('term_editor', '派蒙'))], show_next=False, interactive=True,
                 done=lambda: text_of('term_editor') == '派蒙', ready=selected, focus=part('term_editor'),
                 page=open_library),
        TourStep('再写它==常被听成==什么：「派门」', part('term_alias_editor'),
                 [TourAction('帮我填', fill('term_alias_editor', '派门'))],
                 note='识别成「派门」时就会自动改成「派蒙」；可以写好几个，用逗号分开', show_next=False,
                 interactive=True, done=lambda: '派门' in text_of('term_alias_editor'), ready=selected,
                 focus=part('term_alias_editor'), page=open_library),
        TourStep('点「==添加==」存进词库', part('add_term_button'),
                 [TourAction('帮我点', lambda: library().add_term_button.click())], show_next=False,
                 interactive=True, done=word_saved, ready=selected, page=open_library),
        TourStep('点「==试一句==」：写一句字幕，马上看会改成什么', part('term_try_toggle'),
                 [TourAction('帮我点', open_try)], show_next=False, interactive=True,
                 done=lambda: library() is not None and library().term_try_panel.isVisible(),
                 ready=selected, page=open_library),
        TourStep('写「派门又在旁边说个不停」按 Enter，看看结果', part('term_try_panel'),
                 [TourAction('帮我试', try_line)], note='只在本机比对，不联网、不花钱', show_next=False,
                 interactive=True, done=tried, enter=lambda: _clear(library(), 'term_try_result'),
                 ready=lambda: selected() and library().term_try_panel.isVisible(),
                 focus=part('term_try_input'), page=open_library),
        TourStep('结果写着会改成「==派蒙==」：词库生效啦', part('term_try_result'),
                 ready=tried, optional=True, page=open_library),
        TourStep('要让这一批字幕用这本词库，打开「==本批字幕使用==」', part('use_game'),
                 note='首页的「游戏 / 内容名称」选这个游戏，也会用上它', ready=selected, page=open_library),
        TourStep('「==AI 帮忙==」能从一段攻略文字里挑词、补上新版本的词、加外语名', part('ai_menu_button'),
                 note='要先设置文字 AI（用你自己的 Key）', ready=selected, optional=True, page=open_library),
        TourStep('术语库学会啦！「兔白教学词库」现在会删掉，去建你自己的游戏词库吧', next_label='完成'),
    ]


def _clear(page, name) -> None:
    label = getattr(page, name, None)
    if label is not None:
        label.setText('')


def _remove_terms_library(w) -> None:
    identity = w.__dict__.pop('_tutorial_terms_library', None)
    if not identity:
        return
    try:
        w.legacy.delete_learned_game(identity)
        settings = w.legacy.RUNTIME_SETTINGS.setdefault('glossary', {})
        enabled = [item for item in settings.get('enabled_glossary_ids', []) if item != identity]
        if enabled != settings.get('enabled_glossary_ids', []):
            settings['enabled_glossary_ids'] = enabled
            w._save_glossary_settings()
        box = getattr(w, 'game_box', None)
        if box is not None and box.currentText() == TERMS_LIBRARY:
            box.setCurrentText('')
        page = getattr(getattr(w, 'term_library_page', None), 'library', None)
        if page is not None:
            for row in reversed(range(page.game_list.count())):
                item = page.game_list.item(row)
                if str(item.data(256) or item.text()) == TERMS_LIBRARY:
                    page.game_list.takeItem(row)
            notify = getattr(page, '_notify_library_changed', None)
            if callable(notify):
                notify()
    except Exception:  # noqa: BLE001 - leaving the tutorial must never fail
        import traceback
        traceback.print_exc()


# ---------------------------------------------------------------- 问问兔白
def demo_reply(question: str):
    """What 兔白 says in the tutorial: written answers, no AI, nothing billed."""
    from .bunny_persona import BunnyReply
    asked = lambda source: question.strip() == str(tr(source)).strip()   # noqa: E731 - the tutorial's own questions
    if asked('带我去术语库') or any(word in question for word in ('术语库', '带我去', '詞庫', '術語庫')):
        return BunnyReply(lines=[str(tr('好呀～按下面的「帮我做」我就带你去术语库，你按了我才会动手哦'))],
                          do=('open_page', 'terms'), mood='happy',
                          steps=(str(tr('打开术语库')), str(tr('加一个词')), str(tr('试一句'))), step_now=0)
    if asked('怎么把整片字幕提前半秒？') or any(word in question for word in ('提前', '推后', '整片', '慢', '快')):
        return BunnyReply(lines=[str(tr('先按 **Ctrl+A** 全选字幕')),
                                 str(tr('再按 **Alt+←**，每按一次提前 0.1 秒；慢半秒就按 5 次～')),
                                 str(tr('推后是 **Alt+→**。（这是教学里的示范回答，不联网、不花钱）'))], mood='happy')
    return BunnyReply(lines=[str(tr('（这是教学里的示范回答）')),
                             str(tr('正式用的时候，我会照你问的内容回答，也会带你去对的地方～'))], mood='happy')


def bunny_steps(w) -> list:
    from .bunny_chat import _floating
    from .home_tour import TourAction, TourStep

    def chat():
        found = getattr(w, '_bunny_chat', None)
        try:
            return found if found is not None and found.isVisible() else None
        except RuntimeError:
            return None

    host = chat if _floating() else None

    def part(name):
        return lambda: getattr(chat(), name, None)

    def visible(name):
        def find():
            widget = getattr(chat(), name, None)
            return widget if widget is not None and widget.isVisible() else None
        return find

    def open_chat():
        found = w._open_bunny_chat()
        found.stand_in = demo_reply

    def demo_on():
        found = chat()
        if found is not None:
            found.stand_in = demo_reply

    def ask(question):
        def run():
            found = chat()
            if found is None:
                return
            found.stand_in = demo_reply
            found.input.setText(str(tr(question)))
            found.send()
        return run

    mark = {'said': 0}

    def remember():
        demo_on()
        found = chat()
        mark['said'] = len(getattr(found, 'transcript', ()) or ())

    def answered():
        found = chat()
        said = list(getattr(found, 'transcript', ()) or ())
        return len(said) > mark['said'] + 1 and said[-1][0] == 'bunny'

    return [
        TourStep('不会用、找不到按钮时，点「==问问兔白==」', lambda: getattr(w, 'ask_bunny_button', None),
                 [TourAction('帮我打开', open_chat)], show_next=False, interactive=True,
                 done=lambda: chat() is not None, anim=''),
        TourStep('在这里打字问她，按 **Enter** 发送', part('input'),
                 [TourAction('帮我问', ask('怎么把整片字幕提前半秒？'))],
                 note='教学里是示范回答：不联网、不花钱。她说完一句，点一下对话框看下一句', show_next=False,
                 interactive=True,
                 enter=remember, done=answered, ready=lambda: chat() is not None, focus=part('input'), host=host),
        TourStep('她要动手时会出现「==帮我做==」：==你按了才会做==', visible('do_button'),
                 note='这里按下去会切到术语库；不按也行', enter=ask('带我去术语库'),
                 ready=lambda: visible('do_button')() is not None, host=host, patience=12000),
        TourStep('要好几步的事，她会在上面列出==步骤清单==，一次讲一步', visible('steps_label'),
                 ready=lambda: visible('steps_label')() is not None, host=host, optional=True),
        TourStep('这个时钟是「==兔白做过什么==」：她改过的都能逐项撤销', part('log_button'),
                 ready=lambda: chat() is not None, host=host),
        TourStep('在「设置 → ==兔白权限==」决定她能做多少：只指路、小操作直接做、修改也直接做',
                 note='没填文字 AI 的 Key 时，她只能帮你指出功能在哪里', next_label='完成'),
    ]


def _close_demo_chat(w) -> None:
    found = getattr(w, '_bunny_chat', None)
    if found is None:
        return
    try:
        if getattr(found, 'stand_in', None) is not None:
            found.close_chat()          # the demo conversation is not kept (stand_in: _save_chat skips it)
    except RuntimeError:
        pass


def cleanup(window, part: str) -> None:
    """Undo what a chapter set up; never raises."""
    try:
        if part == 'terms':
            _remove_terms_library(window)
        elif part == 'bunny':
            _close_demo_chat(window)
        elif part == 'render':
            _close_render_workspace(window)
        elif part == 'speakers':
            _close_speakers(window)
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
