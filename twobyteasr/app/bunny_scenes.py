"""兔白 on the pages where people wait or decide what to do next (2026-11-27).

User (2026-11-27): while recognising, give her more scenes and moves, so there is something to
watch and it is never boring; the same on the finished-result page, the AI glossary proofreading
page and the video export. She should also report on her own where things stand and suggest what
to do next, hop over there to play and draw the eye; on Home too.

``SceneErrands`` is mixed into ``bunny_errands.BunnyErrands`` and uses its steps (Hop, Leap, Wait)
and helpers. Four scenes besides Home and the studio:

- 'progress' — the recognition progress page: she rides the progress bar (hopping on as it
  grows), hops along the four phase cards, reads the newest recognised line from a book on the
  "current step" card; every so often, at a phase change and at 25/50/75/90 % she says how far it
  is and roughly how long is left.
- 'result' — the finished page: a cheer on arrival with what came out, hops over the action cards,
  then goes to the card worth doing next (AI glossary proofreading when it is ready, else the
  studio, then export) and knocks on it with a suggestion.
- 'proofread' — AI glossary proofreading: points at what to press (AI 校对 / 按词库匹配 / 套用),
  rides its progress bar while the AI works and reports the count.
- 'export' — the studio's video export: rides the render bar, reports the percentage, cheers
  when the file is out and suggests opening its folder.

On Home ``_suggestion('home')`` is the next step there (choose a file, then start).
Nothing here presses anything: the suggestions are words, a knock and a wobble.

A scene of its own, 'loading' (2026-11-27, user: while a project opened she still roamed as on
Home, and a second bunny sat on the loading card): while the studio's loading card shows she
does no errands, fidgets or pounces. She hops over and sits on the card's top edge where its own
little bunny sat (that one steps aside while she is there), watches it, and is sad with the
card when opening fails; when the card goes she is free again.
"""
from __future__ import annotations

import math
import random
import re
import time

from PySide6.QtCore import QPointF

PROGRESS_PAGE, RESULT_PAGE = '识别进度', '识别完成的结果页'
SCENES = ('progress', 'result', 'proofread', 'export')
LOADING = 'loading'              # the studio's loading card: she sits on it and stays put
LOADING_LOOK_S = 0.5             # how often she checks the card while sitting on it
REPORT_GAP_S = 32.0              # between two "how far" reports while something runs
EVENT_GAP_S = 7.0                # between two lines about events (a phase changed, a milestone)
MILESTONES = (25, 50, 75, 90)
SCENE_GAP_S = (4.0, 8.0)         # between her scene errands on these pages (they are for watching)
SUGGEST_GAP_S = 45.0             # a suggestion is knocked on at most this often
HOME_SUGGEST_IDLE_S = 40.0       # on Home, this long without input before she points at the next step


def percent_of(text) -> int | None:
    match = re.search(r'(\d{1,3})\s*%', str(text or ''))
    return max(0, min(100, int(match.group(1)))) if match else None


def seconds_of(text) -> float | None:
    match = re.search(r'(\d+):(\d{2})(?::(\d{2}))?', str(text or ''))
    if not match:
        return None
    a, b, c = match.group(1), match.group(2), match.group(3)
    return int(a) * 3600 + int(b) * 60 + int(c) if c is not None else int(a) * 60 + int(b)


def eta_words(elapsed: float | None, percent: int | None) -> str:
    """Roughly how long is left, from the time spent and the share done ('' when too early to say)."""
    if elapsed is None or percent is None or percent < 4 or percent >= 100 or elapsed < 20:
        return ''
    left = elapsed * (100 - percent) / percent
    if left < 60:
        return '不到一分钟'
    if left < 3600:
        return f'大约 {max(1, round(left / 60))} 分钟'
    return f'大约 {left / 3600:.1f} 小时'


def _shown(widget) -> bool:
    try:
        return widget is not None and widget.isVisible() and widget.width() > 4 and widget.height() > 4
    except RuntimeError:
        return False


def _text(widget) -> str:
    try:
        return ' '.join(str(widget.text() or '').split()) if widget is not None else ''
    except (RuntimeError, AttributeError):
        return ''


class SceneErrands:
    """Mixed into BunnyErrands: the waiting-and-deciding pages."""

    # ------------------------------------------------------------ where she is
    def scene(self) -> str:
        """'loading', 'progress', 'result', 'proofread', 'export' or ''."""
        window = self.window
        try:
            if self.loading_view() is not None:
                return LOADING
            pages = getattr(window, 'pages', None)
            current = pages.currentWidget() if pages is not None else None
            if current is not None and current is getattr(window, 'glossary_proofread_page', None):
                return 'proofread'
            page = self.page()
            if page == PROGRESS_PAGE:
                return 'progress'
            if page == RESULT_PAGE:
                return 'result'
            studio = self._studio() if page == '字幕工作台' else None
            if studio is not None and _shown(getattr(studio, 'export_workspace', None)):
                return 'export'
        except RuntimeError:
            return ''
        return ''

    def loading_view(self):
        """The studio's loading card while it shows (opening a project, or its failure), else None."""
        session = getattr(self.window, '_studio_loading_session', None)
        view = getattr(session, 'view', None) if session is not None else None
        if view is None or getattr(session, 'state', '') not in ('preparing', 'failed'):
            return None
        return view if _shown(view) else None

    def _loading_seat_spot(self, view):
        """Her card-sized top-left sitting on the loading card's top edge where its bunny sits."""
        from PySide6.QtCore import QPoint
        from .bunny_errands import SEAT
        card, perch = view.card, getattr(view, 'perch', None)
        if not _shown(card):
            return None
        top_left = card.mapTo(self.window, QPoint(0, 0))
        left, right = top_left.x(), top_left.x() + card.width()
        if perch is not None:
            x = perch.mapTo(self.window, QPoint(perch.width() // 2, 0)).x()
        else:
            x = right - 140
        x = max(left + 60, min(x, right - 60))
        spot = self.puck.spot_for(SEAT, QPointF(x, top_left.y() + 3))
        # A card high in a small window leaves no room above it: she sits a little lower, over the
        # card's empty top-right corner, rather than nowhere.
        return spot if self._fits(spot) else self.puck._clamp(spot)

    def _loading_seat(self, view):
        """The 'loading' errand: over to the card, sit on it, stay there until the card goes."""
        from .bunny_errands import Hop, Leap
        mascot, puck = self.mascot, self.puck
        session = getattr(self.window, '_studio_loading_session', None)
        seated = False
        sad = False
        try:
            while True:
                spot = self._loading_seat_spot(view)
                if spot is not None and math.hypot(spot.x() - puck.pos.x(), spot.y() - puck.pos.y()) > 3:
                    if seated:                         # the card moved (the window was resized)
                        mascot.stop_move('sit')
                        view.set_live_bunny(False)
                        seated = False
                    if math.hypot(spot.x() - puck.pos.x(), spot.y() - puck.pos.y()) > 260:
                        side = 1 if spot.x() >= puck.pos.x() else -1
                        yield Hop(self, QPointF(spot.x() - 90 * side, spot.y() + 60))
                    yield Leap(self, spot, height=36)
                    self._face(False)
                    mascot.play('sit')
                    view.set_live_bunny(True)          # the card's own little bunny steps aside
                    self.home = QPointF(puck.pos)
                    seated = True
                failed = getattr(session, 'state', '') == 'failed'
                if failed != sad:
                    sad = failed
                    mascot.set_mood('sad' if failed else 'idle')
                    if failed:
                        self._line(random.choice(('没打开……按「重试」再试一次？', '呜，没能打开工程')))
                self._focus((-.3, .55) if seated else None)   # looking down at the card
                yield LOADING_LOOK_S
        finally:
            self._focus(None)
            mascot.stop_move('sit')
            mascot.set_mood('idle')
            try:
                view.set_live_bunny(False)
            except RuntimeError:
                pass
            self.home = QPointF(puck.pos)

    def _proofread_page(self):
        return getattr(self.window, 'glossary_proofread_page', None)

    def _export_page(self):
        studio = self._studio()
        return getattr(studio, 'export_workspace', None) if studio is not None else None

    def _scene_bar(self, context):
        """The progress bar of this scene, when it is shown (and something runs)."""
        if context == 'progress':
            bar = getattr(self.window, 'progress_bar', None)
        elif context == 'proofread':
            page = self._proofread_page()
            bar = getattr(page, 'ai_progress_bar', None)
        elif context == 'export':
            page = self._export_page()
            bar = getattr(page, 'progress', None) if page is not None and getattr(page, '_running', False) else None
        else:
            bar = None
        return bar if _shown(bar) and bar.width() >= 120 else None

    def scene_cards(self, context) -> list:
        window = self.window
        if context == 'progress':
            return list(getattr(window, 'phase_cards', []) or [])
        if context == 'result':
            names = ('result_ai_card', 'open_studio_result_button', 'export_result_button', 'result_return_button')
            return [getattr(window, name, None) for name in names]
        return []

    def _bar_percent(self, context) -> int | None:
        if context == 'progress':
            value = percent_of(_text(getattr(self.window, 'progress_percent', None)))
            if value is not None:
                return value
        bar = self._scene_bar(context)
        if bar is None:
            return None
        try:
            span = bar.maximum() - bar.minimum()
            return round(100 * (bar.value() - bar.minimum()) / span) if span > 0 else None
        except (RuntimeError, AttributeError):
            return None

    # ------------------------------------------------------------ what she can do here
    def scene_candidates(self, context) -> list:
        found = []
        bar = self._scene_bar(context)
        if bar is not None and self._seat_spot(bar) is not None:
            found += [('ride_bar', (bar, context))] * 2       # the favourite while something runs
        if context == 'progress':
            card = getattr(self.window, 'current_stage_card', None)
            if _shown(card) and self._seat_spot(card, point=self._feet()) is not None:
                found.append(('watch_log', card))
        suggestion = self._suggestion(context)
        if suggestion is not None and time.monotonic() - getattr(self, '_suggested_at', -1e9) > SUGGEST_GAP_S:
            found += [('suggest', suggestion)] * 2
        return found

    @staticmethod
    def _feet():
        from .bunny_errands import FEET
        return FEET

    def _suggestion(self, context):
        """(widget, words) worth doing next here, or None."""
        window = self.window

        def usable(widget):
            return _shown(widget) and widget.isEnabled()
        if context == 'result':
            ai = getattr(window, 'result_ai_card', None)
            if usable(ai):
                return ai, random.choice(('下一步推荐「AI 词库校对」：让 AI 找出写错的人名和术语，你勾选的才会改～',
                                          '先做一次「AI 词库校对」吧，角色名写错的话一下就能找出来！'))
            studio = getattr(window, 'open_studio_result_button', None)
            export = getattr(window, 'export_result_button', None)
            if usable(studio) and (not usable(export) or random.random() < .65):
                return studio, random.choice(('打开「字幕工作台」看看吧：可以逐句检查、调时间轴和换字幕样式～',
                                              '想做成带字幕的视频？先去「字幕工作台」，样式调好就能导出！'))
            if usable(export):
                return export, '急着用的话，按「导出字幕」就能存成 SRT、ASS 这些文件～'
            return None
        if context == 'proofread':
            page = self._proofread_page()
            if page is None:
                return None
            adopt = getattr(page, 'batch_adopt', None)
            if usable(adopt):
                return adopt, '看过的改法勾上以后，按「采用所选」才会写进字幕哦～'
            ai = getattr(page, 'ai_button', None)
            if usable(ai) and not self._scene_running('proofread'):
                return ai, random.choice(('按「AI 校对」，兔白帮你把写错的人名、术语都找出来！',
                                          '词库里有的词，也可以先按「按词库匹配」免费查一遍～'))
            return None
        if context == 'export':
            page = self._export_page()
            if page is None or getattr(page, '_running', False):
                return None
            folder = getattr(page, 'open_folder_button', None)
            if usable(folder):
                return folder, '视频导出好啦！按「打开文件夹」去看看成品吧～'
            go = getattr(page, 'export_button', None)
            if usable(go):
                return go, '格式和画质选好了就按「导出」，兔白在这里帮你盯着进度！'
            return None
        if context == 'home':
            start = getattr(window, 'start_button', None)
            if usable(start):
                return start, random.choice(('素材准备好了！按「开始生成字幕」就出发吧～', '一切就绪，开始生成字幕吧！'))
            button = getattr(window, 'choose_media_button', None)
            if usable(button):
                return button, '先把视频拖进来，或者按「选择素材」挑一个～'
        return None

    def _scene_running(self, context) -> bool:
        if context == 'progress':
            return True
        if context == 'proofread':
            page = self._proofread_page()
            return _shown(getattr(page, 'ai_progress_bar', None))
        if context == 'export':
            page = self._export_page()
            return bool(page is not None and getattr(page, '_running', False))
        return False

    # ------------------------------------------------------------ what she says on her own
    def scene_report(self, context: str) -> None:
        """Called on every check: progress and outcome lines in the bubble over her head."""
        now = time.monotonic()
        state = self.__dict__.setdefault('_scene_state', {})
        if state.get('context') != context:
            state.clear()
            state.update(context=context, entered=now, said=-1e9, event=-1e9, milestone=0, stage='', done=False)
            self._scene_entered(context)
            return
        if context == 'progress':
            self._report_progress(state, now)
        elif context in ('proofread', 'export'):
            self._report_work(context, state, now)

    def _say_scene(self, state, words: str, now: float, event: bool = True) -> None:
        if not words or not self._may_talk():
            return
        self._line(words)
        state['said'] = now
        if event:
            state['event'] = now

    def _may_talk(self) -> bool:
        chat, puck = self.chat, self.puck
        try:
            return (puck is not None and not puck.docked and chat.collapsed and self.window.isVisible()
                    and not self.window.isMinimized() and not chat.busy)
        except RuntimeError:
            return False

    def _scene_entered(self, context) -> None:
        state = self._scene_state
        now = time.monotonic()
        self.next_at = min(self.next_at, now + random.uniform(2.0, 3.5))   # something to watch soon
        if context == 'progress':
            self._say_scene(state, random.choice(('开始做字幕咯！兔白在这里陪你等～', '出发！做好了兔白第一个告诉你')), now)
        elif context == 'result':
            title = _text(getattr(self.window, 'result_title', None)) or '字幕做好了'
            summary = _text(getattr(self.window, 'result_summary', None))
            words = f'{title}！{summary}' if summary else f'{title}！辛苦啦～'
            self._say_scene(state, words[:60], now)
            mascot = self.mascot
            if mascot is not None and not mascot.current_move:
                mascot.act('cheer')
                mascot.stick('confetti')
            self.next_at = min(self.next_at, now + random.uniform(3.0, 4.5))
        elif context == 'proofread':
            self._say_scene(state, '这里是 AI 词库校对：找出写错的人名和术语，采用后才会改～', now)
        elif context == 'export':
            self._say_scene(state, '要导出视频啦？兔白帮你盯着进度！', now)

    def _report_progress(self, state, now: float) -> None:
        window = self.window
        percent = self._bar_percent('progress')
        stage = _text(getattr(window, 'progress_stage', None))
        elapsed = seconds_of(_text(getattr(window, 'stage_elapsed', None)))
        if stage and stage != state['stage']:
            first = not state['stage']
            state['stage'] = stage
            if not first and now - state['event'] >= EVENT_GAP_S:
                self._say_scene(state, f'现在到「{stage}」了～', now)
                return
        if percent is not None:
            passed = [mark for mark in MILESTONES if percent >= mark > state['milestone']]
            if passed:
                state['milestone'] = passed[-1]
                if now - state['event'] >= EVENT_GAP_S:
                    eta = eta_words(elapsed, percent)
                    cheer = {25: '四分之一了！', 50: '过半啦！', 75: '只剩四分之一！', 90: '快好了快好了！'}[passed[-1]]
                    self._say_scene(state, f'{cheer}已经 {percent}%' + (f'，还要{eta}' if eta else ''), now)
                    return
        if now - state['said'] >= REPORT_GAP_S and percent is not None:
            eta = eta_words(elapsed, percent)
            heard = self._latest_heard()
            if heard and random.random() < .4:
                self._say_scene(state, f'刚刚听到：「{heard}」', now, event=False)
            else:
                where = f'正在「{stage}」，' if stage else ''
                self._say_scene(state, f'{where}进度 {percent}%' + (f'，大概还要{eta}' if eta else '，慢慢来～'),
                                now, event=False)

    def _latest_heard(self) -> str:
        preview = getattr(self.window, 'recognition_preview', None)
        try:
            rows = preview.rows() if preview is not None else []
        except RuntimeError:
            return ''
        text = rows[-1][1].strip() if rows else ''
        return text[:22] + ('…' if len(text) > 22 else '') if text else ''

    def _report_work(self, context, state, now: float) -> None:
        running = self._scene_running(context)
        was = state.get('running', False)
        state['running'] = running
        if running and not was:
            self._say_scene(state, 'AI 开始校对了，兔白帮你看着～' if context == 'proofread' else '开始导出！兔白盯着呢～', now)
            return
        if was and not running:
            if context == 'export':
                page = self._export_page()
                finished = _shown(getattr(page, 'open_folder_button', None))
                cancel = getattr(page, '_cancelled', None)
                was_cancelled = cancel is not None and cancel.is_set()
                if finished:
                    self._say_scene(state, '视频导出好啦！🎉', now)
                elif was_cancelled:
                    self._say_scene(state, '导出已取消。', now)
                else:
                    self._say_scene(state, '导出好像没成功…看看下面的提示？', now)
                if finished and self.mascot is not None:
                    self.mascot.act('cheer')
                    self.mascot.stick('confetti')
            else:
                page = self._proofread_page()
                words = {
                    'complete': '校对好了！先检查建议，采用要改的用词～',
                    'partial': '有些字幕还没校对完，可以先看已有的建议。',
                    'failed': '这次 AI 校对没完成，可以看看页面上的提示。',
                    'cancelled': 'AI 校对已取消，已有建议会保留。',
                }
                self._say_scene(state, words.get(getattr(page, 'ai_review_outcome', ''), ''), now)
            self.next_at = min(self.next_at, now + random.uniform(2.5, 4.0))
            return
        if running and now - state['said'] >= REPORT_GAP_S:
            percent = self._bar_percent(context)
            if percent is not None:
                what = '导出' if context == 'export' else 'AI 校对'
                self._say_scene(state, f'{what}进度 {percent}%，继续加油～', now, event=False)

    # ------------------------------------------------------------ the scene errands
    def _ride_bar(self, target):
        """Sit on the progress bar where it has got to and hop on along it as it grows."""
        from .bunny_errands import Hop, Leap
        bar, context = target
        mascot = self.mascot

        def seat_x():
            rect = self._rect(bar)
            percent = self._bar_percent(context)
            share = .5 if percent is None else max(.04, min(.96, percent / 100))
            return rect.left() + rect.width() * share

        def landed():
            self.fx.kick(bar, pivot=(.5, .5), y=36, squash=1.6)
        def seat_near(x):
            rect = self._rect(bar)
            center = rect.center().x()
            for part in (0.0, .25, .5, .75, 1.0):
                spot = self._seat_spot(bar, x + part * (center - x))
                if spot is not None:
                    return spot
            return None

        spot = seat_near(seat_x())
        if spot is None:
            return
        self._line(random.choice(('坐到进度条上看～', '进度条，冲呀！', '兔白搭个顺风车～')))
        try:
            here = self.puck.pos
            if math.hypot(spot.x() - here.x(), spot.y() - here.y()) > 300:
                yield Hop(self, QPointF(spot.x() - 60, spot.y() + 60))
            yield Leap(self, spot, height=44, on_land=landed)
            mascot.play('sit')
            self._focus((random.choice((-.6, .6)), .4))
            last_x = seat_x()
            for beat in range(1, random.randint(8, 12) + 1):
                if self._scene_bar(context) is not bar:
                    break                                     # done (or the page changed)
                yield 1.2
                x = seat_x()
                if abs(x - last_x) >= 14:                     # it grew: hop on to the new end
                    moved = seat_near(x)
                    if moved is not None:
                        mascot.stop_move('sit')
                        yield Leap(self, moved, height=26, crouch=.1, on_land=landed)
                        mascot.play('sit')
                        last_x = x
                        if random.random() < .4:
                            mascot.stick(random.choice(('notes', 'sparkle')))
                elif beat % 3 == 0:
                    self.fx.kick(bar, pivot=(.5, .5), y=14)   # a kick of her feet sets it swaying
                    if random.random() < .35:
                        mascot.stop_move('sit')
                        mascot.act(random.choice(('yes', 'hmm', 'stretch')))
                        yield 1.4
                        mascot.play('sit')
            mascot.stop_move('sit')
            yield Leap(self, self.home, height=46)
        finally:
            self._cleanup(bar, moves=('sit',), prop=False)
        yield .3

    def _watch_log(self, card):
        """Sit on the "current step" card with a book and read out the newest recognised line."""
        from .bunny_errands import FEET, Leap
        mascot = self.mascot
        spot = self._seat_spot(card, point=FEET)
        if spot is None:
            return
        side = random.choice((-1, 1))

        def sat():
            self.fx.kick(card, pivot=(.5, 1.0), squash=1.4, y=30, angle=4 * side)
        try:
            yield Leap(self, spot, height=50, on_land=sat)
            mascot.hold('book')
            mascot.play('read')
            self._focus((0.0, .75))
            yield 2.2
            heard = self._latest_heard()
            stage = _text(getattr(self.window, 'progress_stage', None))
            self._line(f'刚刚听到：「{heard}」' if heard else (f'现在在{stage}，认真听着呢' if stage else '让兔白看看做到哪了…'))
            yield 2.6
            mascot.stop_move('read')
            mascot.put_away('book')
            self._focus(None)
            mascot.act(random.choice(('yes', 'idea', 'hmm')))
            yield 1.0
            yield Leap(self, self.home, height=50)
        finally:
            self._cleanup(card, moves=('read',))
        yield .3

    def _suggest(self, target):
        """Go to what is worth doing next, knock on it so it wobbles, and say why."""
        from .bunny_errands import FEET, Hop, Leap
        from ..design.bunny_moves import KNOCK_PAW
        widget, words = target
        mascot = self.mascot
        self._suggested_at = time.monotonic()
        try:
            big = widget.height() >= 120
            if big and self._seat_spot(widget, point=FEET) is not None:
                spot = self._seat_spot(widget, point=FEET)                # a card: hop on it and bounce
                side = random.choice((-1, 1))

                def bounce(power):
                    def hit():
                        self.fx.kick(widget, pivot=(.5, 1.0), squash=2.4 * power, y=55 * power, angle=10 * side * power)
                    return hit
                here = self.puck.pos
                if math.hypot(spot.x() - here.x(), spot.y() - here.y()) > 280:
                    yield Hop(self, QPointF(spot.x() - 70 * side, spot.y() + 60))
                yield Leap(self, spot, height=50, on_land=bounce(1.0))
                yield Leap(self, spot, height=28, crouch=.1, on_land=bounce(.8), face=False)
                mascot.stick('exclaim')
                self._line(words)
                mascot.act(random.choice(('idea', 'excited', 'yes')))
                yield 2.6
                mascot.play('wave')
                yield 1.6
                mascot.stop_move('wave')
                yield Leap(self, self.home, height=48)
            else:
                side = yield from self._approach(widget, self._contact(KNOCK_PAW))
                if not side:
                    return
                yield from self._knocks(widget, 2, side)
                self._line(words)
                mascot.stick('bulb')
                mascot.act('idea')
                yield 2.0
                self.fx.shake(widget, .5, self.clock(), px=2.0, degrees=4, pivot=(.5, .5))
                mascot.play('wave')
                yield 1.6
                mascot.stop_move('wave')
                yield Hop(self, self.home)
        finally:
            self._cleanup(widget, moves=('wave', 'knock'), prop=False)
        yield .3


__all__ = ['SceneErrands', 'eta_words', 'percent_of', 'seconds_of']
