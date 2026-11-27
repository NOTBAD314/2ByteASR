"""Basic tutorial chapters for people who never used an editor (2026-11-27).

User (2026-11-27): many people do not know how to add subtitles and tracks, what the red and
grey on the timeline mean, how to open the folded speakers and scroll down to them, how to
apply a change to a range of subtitles, how AI makes and repairs subtitles, translation,
sentence breaks and video editing; someone who never used an editing program should be able to
work after the tutorial. Four chapters, each on the tutorial project (made fresh every time,
nothing kept; since 2026-11-27 it also has two minor speakers, so the folded row shows):

* ``timeline`` 看懂时间轴 - what the rows are, the speaker colour, the playhead (a red line in
  most themes), the review strip above the ruler (grey fine / yellow suggested / red check),
  the wheel (time; over the track names or with Shift: the rows), the folded 「次要角色」 row,
  the track buttons, 「+」 for a new track, T for a new subtitle, dragging to another speaker.
* ``select`` 选字幕与套用范围 - click, Ctrl+click, a box, Ctrl+A; 「应用到」; the AI menu's
  selected half; batch replace's scope; I / O.
* ``ai`` AI 生成与修复 - the 「AI 工具」 menu: making subtitles (home page, or one stretch),
  repairs (校对 / 清理 / 优化 / 修轴 / 重新识别), AI 断句, translation and 双语 display.
  Only pointed at; nothing is sent or billed.
* ``cut`` 剪视频入门 - Ctrl+K at the playhead, select a piece, Delete, closing the gap, Q / W,
  dragging, transitions, the media tab, exporting a range.

Written from the code as it is on 2026-11-27 (``studio_timeline``, ``timeline_overview``,
``studio_ai_menu``, ``studio_track_delete``); every step that waits for the person also has a
「帮我做」 that does it.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QWidget

from ..i18n import tr
from .tutorial_chapters import _Studio

TITLES = {'timeline': '时间轴', 'select': '选范围', 'ai': 'AI 工具', 'cut': '剪视频'}


def steps(window, part: str) -> list:
    build = {'timeline': timeline_steps, 'select': select_steps, 'ai': ai_steps, 'cut': cut_steps}[part]
    found = build(window)
    for step in found:
        step.chapter = TITLES[part]
    return found


# ---------------------------------------------------------------- shared helpers
class _Bench(_Studio):
    """The workbench on the tutorial project, with the timeline parts the basic chapters point at."""

    def timeline(self):
        return getattr(self.page(), 'timeline', None)

    def key(self, action_id):
        from ..studio.shortcut_registry import tooltip_key
        name = str(tr(tooltip_key(action_id)))
        for word, arrow in (('Left', '←'), ('Right', '→'), ('Up', '↑'), ('Down', '↓')):
            name = name.replace(word, arrow)
        return name

    def quiet(self, then=None):
        def run():
            self.pause()
            if then is not None:
                then()
        return run

    def rows(self):
        timeline = self.timeline()
        try:
            return list(timeline._row_layout()[3]) if timeline is not None else []
        except Exception:  # noqa: BLE001
            return []

    def seen(self, rect):
        """(timeline, the visible part of ``rect``) or None when it is scrolled away."""
        timeline = self.timeline()
        if timeline is None or rect is None:
            return None
        try:
            part = QRectF(rect).intersected(timeline._track_viewport())
        except Exception:  # noqa: BLE001
            return None
        return None if part.isEmpty() else (timeline, part)

    def whole(self):
        timeline = self.timeline()
        return timeline if timeline is not None and timeline.isVisible() else None

    def names_column(self):
        timeline = self.timeline()
        if timeline is None:
            return None
        view = timeline._track_viewport()
        return timeline, QRectF(0, view.top(), timeline.TRACK_HEADER_WIDTH, view.height())

    def blocks(self, cue_ids):
        timeline = self.timeline()
        if timeline is None:
            return None
        rect = QRectF()
        try:
            rows, _track, _wave = timeline._track_layout()
            for item in getattr(timeline, '_cues_by_start', ()):
                if item.id not in cue_ids or item.speaker_id not in rows:
                    continue
                band = timeline._cue_band(item, rows[item.speaker_id])
                left = max(timeline.TRACK_HEADER_WIDTH, timeline._time_to_x(item.start_ms))
                right = min(timeline._content_right(), timeline._time_to_x(item.end_ms))
                piece = QRectF(left, band.top() + 7, max(4, right - left), band.height() - 14)
                rect = piece if rect.isNull() else rect.united(piece)
        except Exception:  # noqa: BLE001
            return None
        return None if rect.isNull() else self.seen(rect)

    def reveal(self, cue_id):
        """Bring a line into view: its row (up / down) and its time (left / right)."""
        def run():
            timeline = self.timeline()
            project = getattr(self.page(), 'project', None)
            if timeline is None or project is None:
                return
            timeline.reveal_cue(cue_id)
            cue = next((item for item in project.cues if item.id == cue_id), None)
            left, width = timeline.visible_start_ms, timeline.visible_duration_ms
            if cue is not None and not (cue.start_ms >= left and cue.end_ms <= left + width):
                width = max(width, cue.end_ms - cue.start_ms + 4000)
                timeline.set_visible_window(max(0, cue.start_ms - (width - (cue.end_ms - cue.start_ms)) // 2), width)
        return run

    def scroll(self):
        timeline = self.timeline()
        return getattr(timeline, 'vertical_scrollbar', None)

    def editor(self):
        page = self.page()
        inline = getattr(getattr(page, 'timeline', None), '_inline_editor', None)
        if inline is not None:
            return inline
        return getattr(page, 'subtitle_edit_card', None) if getattr(page, '_canvas_editor', None) is not None else None

    def close_editor(self):
        page = self.page()
        if page is None:
            return
        if getattr(page.timeline, '_inline_editor', None) is not None:
            page.timeline._commit_inline_edit()
        elif getattr(page, '_canvas_editor', None) is not None:
            page._commit_canvas_inline_edit(advance=False)

    def tool(self, name):
        """A toolbar button, or 「…」 when a narrow window keeps it there."""
        def find():
            page = self.page()
            button = getattr(page, name, None)
            if button is not None and button.isVisible():
                return button
            toolbar = getattr(page, 'studio_toolbar', None)
            for child in toolbar.findChildren(QWidget) if toolbar is not None else ():
                if child.property('commandSource') == '更多工作区操作' and child.isVisible():
                    return child
            return None
        return find

    def range_set(self):
        project = getattr(self.page(), 'project', None)
        if project is None:
            return False
        from ..projects.project_range import range_points
        start, end = range_points(project)
        return start is not None and end is not None

    def mark_range(self):
        page = self.page()
        page._seek(6.4)
        page._mark_in()
        page._seek(11.8)
        page._mark_out()

    def selected(self):
        page = self.page()
        try:
            return set(page.selected_cue_ids()) if page is not None and page.project is not None else set()
        except Exception:  # noqa: BLE001
            return set()


# ---------------------------------------------------------------- 看懂时间轴
def timeline_steps(w) -> list:
    from .home_tour import TourAction, TourStep
    s = _Bench(w)
    on = s.ready
    mark = {'scroll': None, 'speakers': 0}

    def group_row():
        return next((rect for kind, _key, rect in s.rows() if kind != 'speaker'), None)

    def group_header():
        row = group_row()
        timeline = s.timeline()
        if row is None or timeline is None:
            return None
        return s.seen(QRectF(0, row.top(), timeline.TRACK_HEADER_WIDTH, row.height()))

    def group_button():
        row = group_row()
        if row is None:
            return None
        from ..studio.studio_track_header import button_rect
        return s.seen(button_rect('subtitle', 'more', row).adjusted(-4, -4, 4, 4))

    def group_with_members():
        timeline = s.timeline()
        if timeline is None:
            return None
        members = set(getattr(timeline, '_group_members', ()))
        rect = QRectF()
        for kind, key, row in s.rows():
            if kind != 'speaker' or key in members:
                rect = row if rect.isNull() else rect.united(row)
        return None if rect.isNull() else s.seen(QRectF(0, rect.top(), timeline.TRACK_HEADER_WIDTH, rect.height()))

    def expanded():
        return bool(getattr(s.timeline(), '_group_expanded', False))

    def expand():
        timeline = s.timeline()
        if timeline is not None:
            timeline.set_group_expanded(True)

    def to_top():
        bar = s.scroll()
        if bar is not None:
            bar.setValue(bar.minimum())

    def to_bottom():
        bar = s.scroll()
        if bar is not None:
            bar.setValue(bar.maximum())

    def remember_scroll(then=None):
        def run():
            s.pause()
            if then is not None:
                then()
            bar = s.scroll()
            mark['scroll'] = bar.value() if bar is not None else None
        return run

    def scrolled(up):
        bar = s.scroll()
        if bar is None or mark['scroll'] is None:
            return False
        return bar.value() < mark['scroll'] if up else bar.value() > mark['scroll']

    def folded_row_shown():
        return group_header() is not None

    def playhead():
        timeline = s.timeline()
        if timeline is None:
            return None
        x = timeline._time_to_x(timeline.playhead_ms)
        return timeline, QRectF(x - 18, 0, 36, timeline._track_viewport().bottom())

    def seek_a_little():
        s.pause()
        page = s.page()
        if page is not None:
            page._seek(1.5)

    def overview():
        found = getattr(s.page(), 'timeline_overview', None)
        return found if found is not None and found.isVisible() else None

    def track_buttons():
        timeline = s.timeline()
        if timeline is None:
            return None
        rows, _track, _wave = timeline._track_layout()
        row = rows.get('S00')
        if row is None:
            return None
        from ..studio.studio_track_header import pill_rect
        return s.seen(pill_rect('subtitle', row).adjusted(-4, -4, 4, 4))

    def add_button():
        found = getattr(s.page(), 'timeline_add_track_button', None)
        return found if found is not None and found.isVisible() else None

    def speaker_count():
        project = getattr(s.page(), 'project', None)
        return len(getattr(project, 'speakers', ()) or ())

    def remember_speakers():
        s.pause()
        mark['speakers'] = speaker_count()

    def add_track():
        button = getattr(s.page(), 'add_subtitle_track_button', None)
        if button is not None:
            button.click()

    def before_new_line():
        page = s.page()
        s.pause()
        page._set_timeline_tool('selection')
        page.select_cue('tutorial-7')
        try:
            page._seek(21.05)
        except Exception:  # noqa: BLE001
            pass
        s.reveal('tutorial-7')()

    return [
        TourStep('这一章看懂==时间轴==：每一行是什么、颜色代表什么、怎么上下滑', None,
                 note='用示范工程练习：两位主角（主播、嘉宾）和两位配角，改坏了也没关系',
                 enter=s.open, anim='studio_open'),
        TourStep('时间轴从左到右是==时间==；每一横行是一条==轨道==，名字写在最左边', s.whole,
                 note='上面几行是==字幕轨==：每位说话人一行。==V1== 是视频画面，==A1== 是视频的声音',
                 enter=s.pause, ready=lambda: on() and s.whole() is not None, page=s.open, patience=45000),
        TourStep('彩色方块就是一条==字幕==：左边缘是出现，右边缘是消失', lambda: s.blocks({'tutorial-1', 'tutorial-3'}),
                 note='方块的颜色就是==说话人的颜色==。拖两端改时间，按住中间左右拖可以整条挪动',
                 enter=s.quiet(s.reveal('tutorial-1')), ready=on, page=s.open, anim='qw'),
        TourStep('这条竖线是==播放头==（多数主题是==红色==）：画面现在播到这里', playhead,
                 note='在最上面的时间刻度上点一下、或按住拖动，就跳到那个时间；按 **Space** 播放 / 暂停',
                 enter=seek_a_little, ready=on, page=s.open),
        TourStep('时间刻度上面那条细带是==复核标记==：==灰色==没问题、==黄色==建议确认、==红色==需要检查', overview,
                 note='点一下就跳过去。左边字幕列表的「建议」「检查」分页是同一个意思；按 **R** 审核会一条条带你看',
                 ready=lambda: on() and overview() is not None, page=s.open, optional=True),
        TourStep('在时间轴上==滚动滚轮==是==左右移动==时间；按住 **Ctrl** 再滚是==放大缩小==', s.whole,
                 note=lambda: tr('也可以按 **{value0}** / **{value1}** 放大缩小，**{value2}** 一眼看到整部片；下面的横条也能拖',
                                 value0=s.key('timeline_zoom_in'), value1=s.key('timeline_zoom_out'),
                                 value2=s.key('timeline_fit')),
                 interactive=True, focus=s.whole, ready=on, page=s.open),
        TourStep('轨道放不下时：鼠标放在==左边轨道名字==上滚滚轮，就能==上下滑==；现在==往上滑==看看', s.names_column,
                 [TourAction('帮我往上滑', to_top)],
                 note='在时间区按住 **Shift** 再滚也行，或拖最右边的细滚动条。时间轴太矮，可以把它上面的分隔线往上拖',
                 interactive=True, focus=s.whole, enter=remember_scroll(to_bottom), done=lambda: scrolled(True),
                 ready=on, page=s.open),
        TourStep('配角多时会==折叠成一行==「次要角色 · 2」：两位配角挤在这一行，字幕前面写着是谁', group_header,
                 note='字幕最多的两位各占一行，其他人合在这里，时间轴才不会太长', enter=s.quiet(to_top),
                 ready=lambda: on() and folded_row_shown(), page=s.quiet(to_top)),
        TourStep('点这个==小箭头 ▸== 就==展开==：每位配角各占一行', group_button,
                 [TourAction('帮我展开', expand)], show_next=False, interactive=True, focus=s.whole,
                 click=TourAction('', expand), enter=s.quiet(to_top), done=expanded,
                 ready=lambda: on() and group_button() is not None, page=s.quiet(to_top)),
        TourStep('展开后再点 ==▾== 就==收起来==', group_with_members,
                 note='想让某位配角一直单独一行：在「说话人管理」里把他设成主角', enter=s.quiet(to_top),
                 ready=lambda: on() and expanded(), optional=True),
        TourStep('现在轨道变多了：在轨道名字上==往下滑==，找回主播和嘉宾', s.names_column,
                 [TourAction('帮我往下滑', to_bottom)], interactive=True, focus=s.whole,
                 enter=remember_scroll(to_top), done=lambda: scrolled(False), ready=on, page=s.open),
        TourStep('每条轨道右边三个按钮：==眼睛==隐藏、==锁==锁定、==垃圾桶==删掉这条轨', track_buttons,
                 note='隐藏：画面上先不显示这一轨；锁定：这一轨拖不动也改不了，防止误改；删错了按 **Ctrl+Z**',
                 enter=s.quiet(s.reveal('tutorial-1')), ready=lambda: on() and track_buttons() is not None,
                 page=s.open),
        TourStep('点左上角的「==+==」==新建轨道==：选「新建字幕轨」或「新建视频轨」', add_button,
                 [TourAction('帮我新建字幕轨', add_track)],
                 note='字幕轨就是多一位说话人（也能放歌词、注释）；视频轨可以在画面上再叠一层图片或视频',
                 show_next=False, interactive=True, enter=remember_speakers,
                 done=lambda: speaker_count() > mark['speakers'], ready=lambda: on() and add_button() is not None,
                 page=s.open),
        TourStep(lambda: tr('==加一条字幕==：先点一下那一行的字幕，把播放头放到要开始的地方，按 **{value0}**',
                            value0=s.key('add_subtitle')),
                 s.tool('add_subtitle_button'), [TourAction('帮我加一条', lambda: s.page()._add_subtitle_at_playhead())],
                 note='新字幕加在选中字幕的那一行，长 2 秒，直接打字；工具栏最左边的 **T** 也是它',
                 show_next=False, interactive=True, enter=before_new_line, done=lambda: s.editor() is not None,
                 ready=on, focus=s.whole, page=s.open, anim='edit'),
        TourStep('打好字按 **Enter** 保存，**Esc** 取消', s.editor,
                 [TourAction('帮我做', s.close_editor)], show_next=False, interactive=True,
                 done=lambda: s.editor() is None, optional=True),
        TourStep('时间轴看懂啦！说话人分错时，把字幕方块==按住往上或往下拖==到另一行就行', next_label='完成',
                 note='下一章学怎么一次选好多条字幕、只改其中一部分'),
    ]


# ---------------------------------------------------------------- 选字幕与套用范围
def select_steps(w) -> list:
    from .home_tour import TourAction, TourStep
    from ..timeline.studio_selection import ClipSelection
    s = _Bench(w)
    on = s.ready

    def start_on_first():
        page = s.page()
        if page is None or page.project is None:
            return                      # still opening: the step waits, the first line is selected anyway
        s.pause()
        s.close_editor()
        page._set_timeline_tool('selection')
        page.select_cue('tutorial-1')
        s.reveal('tutorial-2')()

    def pick(cue_ids):
        def run():
            page = s.page()
            if len(cue_ids) == 1:
                page.select_cue(next(iter(cue_ids)))
            else:
                page.timeline._publish_clip_selection(ClipSelection(cue_ids=set(cue_ids)))
        return run

    def all_ids():
        project = getattr(s.page(), 'project', None)
        return {cue.id for cue in getattr(project, 'cues', ())}

    return [
        TourStep('这一章学==选字幕==和==套用范围==：改样式、跑 AI 之前，先决定要改哪些', None,
                 note='用示范工程练习；先选好，再动手', enter=s.open, anim='replace'),
        TourStep('==点一下==字幕方块就选中它，外面会有一圈亮框', lambda: s.blocks({'tutorial-2'}),
                 [TourAction('帮我选', pick({'tutorial-2'}))], show_next=False, interactive=True,
                 click=TourAction('', pick({'tutorial-2'})), enter=start_on_first,
                 done=lambda: s.page().selected_cue_id == 'tutorial-2', ready=on, focus=s.whole, page=s.open,
                 patience=45000),
        TourStep('按住 **Ctrl** 再点另一条：==多选==；再点一次就取消那一条', lambda: s.blocks({'tutorial-2', 'tutorial-4'}),
                 [TourAction('帮我多选', pick({'tutorial-2', 'tutorial-4'}))], show_next=False, interactive=True,
                 done=lambda: len(s.selected()) >= 2, ready=on, focus=s.whole, page=s.open),
        TourStep('在==没有字幕的空白处==按住鼠标==拖一个框==：框到的字幕全部选上', s.whole,
                 note='拖的时候按住 Ctrl 或 Shift，会加进已经选的里面。左边字幕列表里按住 **Shift** 点两条，中间的全部选上',
                 interactive=True, focus=s.whole, ready=on, page=s.open),
        TourStep(lambda: tr('按 **{value0}** ==全选==；点一下时间轴的空白处就取消', value0=s.key('select_all')),
                 s.whole, [TourAction('帮我全选', lambda: s.page()._select_all_timeline_cues())],
                 note=lambda: tr('工具栏的 **→** 工具（**{value0}**）：点一条就选中它和后面的全部，整段往后挪很方便',
                                 value0=s.key('track_forward_tool')),
                 show_next=False, interactive=True, done=lambda: bool(all_ids()) and s.selected() >= all_ids(),
                 ready=on, focus=s.whole, page=s.open),
        TourStep('改样式时，「==应用到==」决定改哪些：==当前==这条、==已选==的、这位==说话人==的、==全片==',
                 s.part('style_scope'), note='例如先多选几条、点「已选」再换颜色，就只改这几条；只改某个人就选「说话人」',
                 enter=s.tab(1), ready=lambda: on() and s.part('style_scope')() is not None, page=s.tab(1)),
        TourStep('「==AI 工具==」菜单的下半部分只处理==选中的字幕==', s.part('cue_ai_button'),
                 note='例如只翻译选中的几条、只对选中的重新识别或 AI 断句；上半部分是整个工程',
                 ready=lambda: on() and s.part('cue_ai_button')() is not None, page=s.open),
        TourStep('「==批量替换==」也能选范围：全部、==选中字幕==或==当前时间范围==', s.tool('studio_find_replace_button'),
                 note='先预览再替换，可以一步撤销', ready=on, page=s.open, optional=True),
        TourStep(lambda: tr('只处理==一段时间==：播放头放到开头按 **{value0}**，结尾按 **{value1}**',
                            value0=s.key('mark_in'), value1=s.key('mark_out')),
                 s.whole, [TourAction('帮我框', s.mark_range)], note='同一位置再按一次就取消',
                 show_next=False, interactive=True, enter=s.pause, done=s.range_set, ready=on, focus=s.whole,
                 page=s.open),
        TourStep('框好的这一段：可以「==只重新识别这一段字幕==」，导出或压制时也能只要「==入点到出点==」', s.whole,
                 note='在「AI 工具 → 入点到出点」里，或时间轴上点右键', ready=on, page=s.open),
        TourStep('选范围学会啦！==先选好，再动手==', next_label='完成',
                 note='改错了随时按 **Ctrl+Z** 撤销'),
    ]


# ---------------------------------------------------------------- AI 生成与修复
def ai_steps(w) -> list:
    from .home_tour import TourStep
    s = _Bench(w)
    on = s.ready
    menu = s.part('cue_ai_button')
    shown = lambda: on() and menu() is not None   # noqa: E731

    return [
        TourStep('这一章认识「==AI 工具==」：生成字幕、修错字、断句、翻译都在这里', None,
                 note='用示范工程，只介绍、不真的跑，不联网也不花钱', enter=s.open, anim='gl_ai'),
        TourStep('所有 AI 功能都在字幕列表上方的「==AI 工具==」菜单', menu,
                 note='菜单分三段：==整个工程==、==当前 / 选中的字幕==、==入点到出点==',
                 enter=s.pause, ready=shown, page=s.open, patience=45000),
        TourStep('==AI 生成字幕==：新视频在==首页==放进去，点「开始生成字幕」', None,
                 note='已经在工作台、只缺一段或某段识别得很差：用 I / O 框好，选「AI 工具 → ==只重新识别这一段字幕==」'),
        TourStep('==修错字==：「AI 校对」照术语库找写错的人名和专有名词', menu,
                 note='找到的都是建议，你勾选了才改；「新手教学 → 改错字」那一章可以完整练一次', ready=shown, page=s.open),
        TourStep('==清理口癖==：「AI 清理」去掉「嗯、那个」、重复的字和多余的标点', menu,
                 note='一页列出所有改动，逐条确认后才应用', ready=shown, page=s.open),
        TourStep('一条写得不顺：选中它用「==AI 优化==」润色；时间不准用「==智能修轴==」按声音重新对齐', menu,
                 note='整句听错了用「==重新识别==」；背景音乐太吵可以选「增强人声后重新识别」（要先下载人声增强模型）',
                 ready=shown, page=s.open),
        TourStep('==AI 断句==：把太长或断得奇怪的字幕，重新断成好读的句子', menu,
                 note='AI ==只决定在哪里断开、不改字==；可以整个工程跑，也可以只跑选中的。失败的地方保持原样，可以「重试断句失败的范围」',
                 ready=shown, page=s.open),
        TourStep('==翻译==：「翻译整个工程」或「翻译所选字幕」生成译文', menu,
                 note='已有的译文会保留。首页「字幕显示」选「原文 + 翻译」，生成字幕时就会一起翻好', ready=shown, page=s.open),
        TourStep('顶栏「==双语 / 翻译==」：切换显示==原文==、==译文==或==双语==', s.tool('bilingual_toggle_button'),
                 note='双语时可以在「样式」里只改译文那一层', ready=on, page=s.open, optional=True),
        TourStep('字幕列表的「==建议==」「==检查==」分页：只看要确认（黄）和要检查（红）的字幕', s.part('cue_filter_track'),
                 note='和时间轴上方那条细带同一个意思；按 **R** 审核时，**1 / 2 / 3** 选用三份识别结果中的一份',
                 ready=lambda: on() and s.part('cue_filter_track')() is not None, page=s.open, optional=True),
        TourStep('AI 校对、清理、优化、断句和翻译要先连好==文字 AI==：首页「AI 智能断句」卡填 API Key、测试连接', None,
                 note='用你自己的 Key，按用量计费；重新识别用的是首页选的识别方案。本机识别、剪辑、样式、导出都不花钱'),
        TourStep('AI 工具认识啦！AI 改的每一步都能按 **Ctrl+Z** 撤销', next_label='完成',
                 note='拿不准就先选几条试试，满意再跑整个工程'),
    ]


# ---------------------------------------------------------------- 剪视频入门
def cut_steps(w) -> list:
    from .home_tour import TourAction, TourStep
    from ..timeline.studio_selection import ClipSelection
    s = _Bench(w)
    on = s.ready
    mark = {'pieces': 0}

    def pieces():
        project = getattr(s.page(), 'project', None)
        if project is None:
            return []
        try:
            from ..timeline.studio_edit_sequence import sequence_of
            return sorted(sequence_of(project).segments, key=lambda item: item.timeline_in_ms)
        except Exception:  # noqa: BLE001
            return []

    def video_lane():
        timeline = s.timeline()
        if timeline is None:
            return None
        try:
            rect = timeline._video_tracks_rect()
        except Exception:  # noqa: BLE001
            return None
        left = timeline.TRACK_HEADER_WIDTH
        part = QRectF(left, rect.top(), timeline._content_right() - left, rect.height()).intersected(
            QRectF(timeline.rect()))
        return None if part.isEmpty() else (timeline, part)

    def first_piece():
        timeline = s.timeline()
        found = pieces()
        lane = video_lane()
        if timeline is None or not found or lane is None:
            return lane
        item = found[0]
        left = max(timeline.TRACK_HEADER_WIDTH, timeline._time_to_x(item.timeline_in_ms))
        right = min(timeline._content_right(), timeline._time_to_x(item.timeline_out_ms))
        rect = lane[1]
        return timeline, QRectF(left, rect.top(), max(8, right - left), rect.height())

    def split_here():
        page = s.page()
        s.pause()
        page._seek(8.0)
        page._split_video_at_playhead()

    def ready_to_split():
        s.pause()
        page = s.page()
        page._set_timeline_tool('selection')
        page._seek(8.0)
        mark['pieces'] = len(pieces())

    def select_first():
        found = pieces()
        if found:
            s.page().timeline._publish_clip_selection(ClipSelection(video_ids={found[0].id}))
            s.page().timeline.setFocus()

    def piece_selected():
        timeline = s.timeline()
        if timeline is None:
            return False
        return bool(getattr(timeline, 'selected_segment_ids', None) or timeline.clip_selection().video_ids)

    def remember_pieces():
        s.pause()
        mark['pieces'] = len(pieces())

    def delete_selected():
        page = s.page()
        if not piece_selected():
            select_first()
        page._delete_current()

    def key(action_id):
        return s.key(action_id)

    return [
        TourStep('这一章学==剪视频==：切开、删掉不要的、剪掉头尾', None,
                 note='用示范工程练，改坏了按 **Ctrl+Z**；示范工程下次会重新生成', enter=s.open, anim='qw'),
        TourStep('==V1== 这一行是视频，长条就是==视频片段==；下面 ==A1== 是它的声音', video_lane,
                 note='剪视频就是把这些长条切开、删掉、挪位置', enter=s.pause,
                 ready=lambda: on() and video_lane() is not None, page=s.open, patience=45000),
        TourStep(lambda: tr('播放头放在要切的地方，按 **{value0}**：==在播放头把视频切成两段==',
                            value0=key('split_at_playhead')),
                 video_lane, [TourAction('帮我切', split_here)],
                 note='所有没锁的视频轨都会在播放头切开；切错了按 **Ctrl+Z**', show_next=False, interactive=True,
                 enter=ready_to_split, done=lambda: len(pieces()) > max(1, mark['pieces']), ready=on,
                 focus=s.whole, page=s.open, anim='razor'),
        TourStep('==点一下==前面那一段，选中它', first_piece, [TourAction('帮我选', select_first)],
                 show_next=False, interactive=True, click=TourAction('', select_first), enter=s.pause,
                 done=piece_selected, ready=lambda: on() and len(pieces()) >= 2, focus=s.whole, page=s.open),
        TourStep('按 **Delete** ==删掉选中的这一段==', first_piece, [TourAction('帮我删', delete_selected)],
                 note='删掉后那里会空出一段（黑画面）', show_next=False, interactive=True, enter=remember_pieces,
                 done=lambda: len(pieces()) < mark['pieces'], ready=on, focus=s.whole, page=s.open),
        TourStep('==点那段空白==再按 **Delete**：后面的往前接上，不留黑画面', video_lane,
                 note='这叫==波纹删除==，跟着剪辑的字幕也会一起往前挪', interactive=True, focus=s.whole,
                 ready=on, page=s.open),
        TourStep(lambda: tr('更快的剪法：选中片段，播放头放到要留的第一帧，按 **{value0}**：==前面那段直接剪掉==',
                            value0=key('trim_start')),
                 video_lane, note=lambda: tr('**{value0}** 剪掉播放头后面那段（结尾的废片），后面的都会自动接上',
                                             value0=key('trim_end')),
                 ready=on, page=s.open),
        TourStep('按住片段==左右拖==换位置；拖片段的==两端==改长短', video_lane,
                 note='按住 **Alt** 拖，会连同选中的字幕一起挪', ready=on, page=s.open, optional=True),
        TourStep(lambda: tr('两段之间加==转场==：选中片段按 **{value0}**', value0=key('video_transition')),
                 video_lane, note=lambda: tr('声音的转场是 **{value0}**：让两段之间柔和地过渡，不会突然一跳',
                                             value0=key('audio_transition')),
                 ready=on, page=s.open, optional=True),
        TourStep('右边「==素材==」分页：加别的视频、图片、音乐，拖到时间轴上', s.part('context_drawer'),
                 note='双击素材先在「源素材」里看，设好入点出点再加进去', enter=s.tab('media_pool_tab_index'),
                 ready=on, page=s.tab('media_pool_tab_index'), optional=True),
        TourStep('只要其中一段：用 **I / O** 框好，导出时选「==入点到出点==」', s.tool('studio_render_button'),
                 note='都剪好了，点右上角「导出音视频」压制成片；「压制」那一章讲怎么选画质', ready=on, page=s.open),
        TourStep('剪视频入门学会啦！', next_label='完成', note='任何一步都能按 **Ctrl+Z** 撤销'),
    ]
