"""兔白 points at (almost) any control on screen, found in the live widget tree (2026-11-22).

User (2026-11-22): 「基本所有按钮都要能指才好，带用户点的东西也要能是正确的而不是乱点。」

Before, ``point_to`` knew a dozen hand-mapped feature keys. Now every target comes from the real
widget tree (the same tree ``bunny_ui_control`` snapshots): buttons, check boxes, drop-downs, tabs,
list rows, group boxes and the visible words on the main window's pages, its dialogs and the
completion page (its 兔白 bubble included). A target that is not on screen is looked up on the
main window's other built pages first (go to that page, then point), then in the feature registry
(open that place, then point once it is open).

Every point is checked before it is drawn: the control still exists, is shown, is not scrolled or
covered away, sits inside its window, and its name still matches what was asked; a grey control is
pointed at with its reason. When nothing fits, the receipt says so and names the closest controls,
so she says "找不到" instead of pointing somewhere else. ``covered`` checks afterwards that the
outline really sits on the control (the audit in ``acceptance/bunny_point_audit.py``).
"""
from __future__ import annotations

import dataclasses
import difflib
import re
import time
import weakref

TEXT_LIMIT = 40
LABEL_LIMIT = 30                 # visible words longer than this are prose, not a place to point at
OPEN_WAIT_S = 5.0                # a place opened for a point (settings) has this long to appear
GENERIC = re.compile(r'(那个|这个|一下|按钮|按键|选项|开关|下拉框|下拉菜单|输入框|文字框|页签|标签页|菜单|图标|在哪里?|在哪儿|位置)$')
PUNCT = re.compile(r'[\s「」“”"\'『』《》【】()（）:：,，.。!！?？~～…·]+')
NAV_PAGES = ('home', 'workshop', 'terms', 'history', 'studio')
WORDS_ONLY = 45                  # a score below this matched only a tooltip / object name, not the control's words
PAGE_OFFER = {'workshop': 'model_workshop', 'terms': 'glossary'}     # feature keys for 「带我去」


class PointError(Exception):
    """Nothing to point at; the message says why, in words she can repeat."""


@dataclasses.dataclass
class Target:
    widget: object
    kind: str                    # bunny_ui_control kinds, plus 'label' and 'group'
    label: str
    where: str = ''              # window title or page name
    index: int = -1              # a tab's index or a list row
    page: str = ''               # NAV_PAGES key when the control is on a page not shown now
    hints: str = ''

    def describe(self) -> str:
        from .bunny_ui_control import KIND_WORDS
        kind = {'label': '文字', 'group': '区域'}.get(self.kind) or KIND_WORDS.get(self.kind, '控件')
        return f'{kind}「{self.label[:TEXT_LIMIT]}」' + (f'（{self.where}）' if self.where else '')


# ------------------------------------------------------------------ the tree
def _alive(widget) -> bool:
    try:
        from shiboken6 import isValid
        return widget is not None and isValid(widget)
    except Exception:  # noqa: BLE001 - no shiboken: trust the object
        return widget is not None


def page_roots(window) -> list[tuple[str, str, object]]:
    """(key, name, root widget) for the main window's pages that exist now (lazy pages are never built here)."""
    pages = getattr(window, 'pages', None)
    built = getattr(window, 'built_page', lambda _name: None)
    rows = [('home', '首页', getattr(window, 'settings_scroll', None)),
            ('progress', '识别进度', pages.widget(1) if pages is not None and pages.count() > 1 else None),
            ('completion', '识别完成的结果页', pages.widget(2) if pages is not None and pages.count() > 2 else None),
            ('terms', '术语库', getattr(window, 'term_library_page', None)),
            ('workshop', '模型工坊', built('workshop')), ('history', '识别记录', built('history')),
            ('studio', '字幕工作台', built('studio'))]
    return [(key, name, widget) for key, name, widget in rows if widget is not None]


def page_of(window, widget) -> tuple[str, str]:
    node = widget
    roots = {id(root): (key, name) for key, name, root in page_roots(window)}
    while node is not None:
        if id(node) in roots:
            return roots[id(node)]
        node = node.parentWidget()
    return '', ''


def _norm(text) -> str:
    return PUNCT.sub('', str(text or '')).casefold()


def _hints(widget) -> str:
    from .bunny_ui_control import _plain
    return ' '.join((str(widget.objectName()), _plain(widget.toolTip()), _plain(widget.accessibleName()),
                     _plain(getattr(widget, 'placeholderText', lambda: '')()))).casefold()


def _extras(top, title: str, shown) -> list[Target]:
    """Group boxes and short visible words: places to point at that are not controls."""
    from PySide6.QtWidgets import QGroupBox, QLabel
    from .bunny_ui_control import _own, _plain
    found = []
    for widget in top.findChildren(QGroupBox):
        if shown(widget) and _own(widget) and _plain(widget.title()):
            found.append(Target(widget, 'group', _plain(widget.title())[:TEXT_LIMIT], title, hints=_hints(widget)))
    for widget in top.findChildren(QLabel):
        text = _plain(widget.text())
        if '<' in text:                                  # rich text: its words without the tags
            text = _plain(re.sub(r'<[^>]+>', ' ', text))
        if not text or len(text) > LABEL_LIMIT or not shown(widget) or not _own(widget):
            continue
        found.append(Target(widget, 'label', text, title, hints=_hints(widget)))
    return found


def visible_targets(window, *, where: str = '') -> list[Target]:
    """Every place on screen she may point at: controls first (the dialog to answer first), then words."""
    from .bunny_ui_control import _tops, elements, _plain
    rows = [Target(item.widget, item.kind, item.label, item.window, item.tab, hints=_hints(item.widget))
            for item in elements(window, where=where)]
    for top in _tops(window):
        title = _plain(top.windowTitle()) if top is not window else '主窗口'
        if where and where not in title:
            continue

        def shown(widget, top=top):
            return (widget.isVisible() and widget.width() >= 4 and widget.height() >= 4
                    and widget.window() is top and not widget.visibleRegion().isEmpty())
        rows += _extras(top, title, shown)
    for row in rows:                                     # say which page of the main window it is on
        if row.where == '主窗口':
            _key, name = page_of(window, row.widget)
            row.where = name or '主窗口'
    return rows


def hidden_page_targets(window) -> list[Target]:
    """Controls on the main window's built pages that are not shown now (point after going there)."""
    from PySide6.QtWidgets import QWidget
    from .bunny_ui_control import _kind, _label_for, _own, _plain
    pages = getattr(window, 'pages', None)
    current = pages.currentWidget() if pages is not None else None
    rows = []
    for key, name, root in page_roots(window):
        if key not in NAV_PAGES:
            continue
        coming = root is current         # the page shown now but still coming up (2026-11-22 live run: opened
                                         # by open_place in the same round, behind its transition cover)

        def shown(widget, root=root, coming=coming):
            if not (widget.isVisibleTo(root) and widget.width() >= 4 and widget.height() >= 4):
                return False
            return not coming or not widget.isVisible() or widget.visibleRegion().isEmpty()
        for widget in root.findChildren(QWidget):
            if not shown(widget) or not _own(widget):
                continue
            kind = _kind(widget)
            if kind in ('', 'tabs', 'list'):
                continue
            rows.append(Target(widget, kind, _label_for(widget)[:TEXT_LIMIT], name, page=key, hints=_hints(widget)))
        for extra in _extras(root, name, shown):
            extra.page = key
            rows.append(extra)
    return rows


# ------------------------------------------------------------------ matching
def _score(target: Target, wanted: str) -> int:
    label = _norm(target.label)
    if not label or not wanted:
        return 0
    if label == wanted:
        score = 100
    elif label.startswith(wanted) and len(wanted) >= 2:
        score = 80
    elif wanted in label and len(wanted) >= 2:
        score = 65
    elif len(label) >= 2 and label in wanted and len(label) * 2 >= len(wanted):
        score = 45
    elif len(wanted) >= 3 and wanted in target.hints:
        score = 35
    else:
        return 0
    if target.kind not in ('label', 'group'):
        score += 6                                   # a control beats the same words printed beside it
    if target.kind == 'group':
        score += 2
    try:
        if target.widget.isEnabled():
            score += 1
    except RuntimeError:
        return 0
    return score


def best_matches(targets, text: str) -> list[tuple[int, Target]]:
    wanted = _norm(text)
    scored = [(score, target) for target in targets if (score := _score(target, wanted))]
    if not scored:
        stripped = _norm(GENERIC.sub('', str(text or '').strip()))
        if stripped and stripped != wanted:
            scored = [(score, target) for target in targets if (score := _score(target, stripped))]
    scored.sort(key=lambda pair: -pair[0])
    return scored


def _same_place(a: Target, b: Target) -> bool:
    return a.widget is b.widget and a.index == b.index


def _unique(scored) -> list[tuple[int, Target]]:
    kept = []
    for score, target in scored:
        if any(_same_place(target, other) for _s, other in kept):
            continue
        # The words of a button's own label printed inside it are the button.
        if target.kind == 'label' and any(other.kind not in ('label', 'group') and _inside(target.widget, other.widget)
                                          for _s, other in kept):
            continue
        kept.append((score, target))
    return kept


def _inside(child, parent) -> bool:
    node = child
    while node is not None:
        if node is parent:
            return True
        node = node.parentWidget()
    return False


def closest_names(targets, text: str, limit: int = 4) -> list[str]:
    names = []
    for target in targets:
        if target.label and target.label not in names:
            names.append(target.label)
    by_norm = {_norm(name): name for name in names}
    picked = difflib.get_close_matches(_norm(text), list(by_norm), n=limit, cutoff=0.34)
    return [by_norm[name] for name in picked]


# ------------------------------------------------------------------ checks
def sub_rect(target: Target):
    """The control's own rectangle in its widget's coordinates (a tab or a list row is part of a bar)."""
    from PySide6.QtCore import QRect
    widget = target.widget
    if target.kind == 'tab' and target.index >= 0:
        return widget.tabRect(target.index)
    if target.kind == 'item' and target.index >= 0:
        item = widget.item(target.index)
        if item is not None:
            rect = widget.visualItemRect(item)
            return QRect(widget.viewport().mapTo(widget, rect.topLeft()), rect.size())
    return widget.rect()


def global_rect(target: Target):
    from PySide6.QtCore import QRect
    rect = sub_rect(target)
    return QRect(target.widget.mapToGlobal(rect.topLeft()), rect.size())


def current_label(target: Target) -> str:
    from .bunny_ui_control import _label_for, _plain
    widget = target.widget
    if target.kind == 'tab':
        return _plain(widget.tabText(target.index)) or _plain(widget.tabToolTip(target.index))
    if target.kind == 'item':
        item = widget.item(target.index)
        return _plain(item.text())[:TEXT_LIMIT] if item is not None else ''
    if target.kind == 'group':
        return _plain(widget.title())[:TEXT_LIMIT]
    if target.kind == 'label':
        text = _plain(widget.text())
        return _plain(re.sub(r'<[^>]+>', ' ', text)) if '<' in text else text
    return _label_for(widget)[:TEXT_LIMIT]


def verify(target: Target, *, wanted: str = '') -> tuple[list[str], list[str]]:
    """(problems that stop the point, notes to say with it). Scrolls the control into view first."""
    problems, notes = [], []
    widget = target.widget
    if not _alive(widget):
        return ['这个控件已经不在了（界面变了）'], notes
    try:
        visible = widget.isVisible() and widget.window().isVisible() and not widget.window().isMinimized()
    except RuntimeError:
        return ['这个控件已经不在了（界面变了）'], notes
    if not visible:
        return [f'{target.describe()} 现在不在屏幕上'], notes
    try:
        from .bunny_chat import reveal_widget
        reveal_widget(widget)
    except Exception:  # noqa: BLE001 - scrolling into view is a nicety
        pass
    rect = sub_rect(target)
    painter, painted = widget, rect                  # a list row is painted by the list's viewport
    if target.kind == 'item' and hasattr(widget, 'viewport'):
        from PySide6.QtCore import QPoint
        painter = widget.viewport()
        painted = rect.translated(-painter.mapTo(widget, QPoint(0, 0)))
    if rect.width() < 4 or rect.height() < 4:
        problems.append(f'{target.describe()} 太小或被收起来了，看不到')
    elif painter.visibleRegion().intersected(painted).isEmpty():
        problems.append(f'{target.describe()} 被别的东西挡住或滚出去了')
    else:
        top = widget.window()
        on_window = global_rect(target).intersected(top.frameGeometry())
        area = rect.width() * rect.height()
        if on_window.width() * on_window.height() * 2 < area:
            problems.append(f'{target.describe()} 大半在窗口外面')
    now = current_label(target)
    if target.label and _norm(now) != _norm(target.label):
        problems.append(f'这个控件现在叫「{now[:20]}」，不是「{target.label[:20]}」了')
    elif wanted and not best_matches([target], wanted):
        problems.append(f'找到的是「{now[:20]}」，和「{wanted[:20]}」对不上')
    if not problems and target.kind not in ('label', 'group'):
        enabled = (widget.isEnabled() and widget.isTabEnabled(target.index)) if target.kind == 'tab' else widget.isEnabled()
        if not enabled:
            from .bunny_ui_control import _plain
            reason = _plain(widget.toolTip())[:50]
            notes.append('它现在是灰的、按不了' + (f'（{reason}）' if reason else ''))
    return problems, notes


def covered(spot_global, target: Target) -> tuple[bool, str]:
    """Does the outline drawn at ``spot_global`` (a global QRect) sit on the control? (center inside, encloses)"""
    rect = global_rect(target)
    if spot_global is None or spot_global.isNull():
        return False, '没画外框'
    center_in = rect.contains(spot_global.center())
    encloses = spot_global.adjusted(-2, -2, 2, 2).contains(rect)
    return center_in and encloses, (f'外框 {spot_global.getRect()} 控件 {rect.getRect()}'
                                    + ('' if center_in else '；外框中心不在控件里') + ('' if encloses else '；外框没框住控件'))


# ------------------------------------------------------------------ locating
@dataclasses.dataclass
class Located:
    target: Target | None = None
    go_page: str = ''            # NAV_PAGES key to show first
    open_entry: object = None    # feature_search.Entry to open first (a dialog); point once it is open
    notes: list = dataclasses.field(default_factory=list)


def _feature_for(window, text: str):
    from .feature_search import entries
    wanted = _norm(GENERIC.sub('', str(text or '').strip())) or _norm(text)
    if len(wanted) < 2:
        return None
    best, best_score = None, 0
    for entry in entries(window):
        if not entry.key:
            continue
        title = _norm(entry.title.split('（')[0])
        words = [_norm(word) for word in entry.keywords]
        score = (90 if title == wanted else 70 if wanted in title and len(wanted) >= 2
                 else 50 if any(word == wanted for word in words) else 0)
        if score > best_score:
            best, best_score = entry, score
    return best


def locate(window, args) -> Located:
    """The place a point_at call means. Raises PointError with the closest names when there is none."""
    from .bunny_ui_control import _REFS, _plain
    ref = _plain(args.get('ref'))
    if ref:
        held = _REFS.get(ref)
        widget = held[0]() if held else None
        if widget is None or not _alive(widget):
            raise PointError(f'编号 {ref} 已经过期了（界面变了），先 ui_snapshot 再用新的编号')
        target = Target(widget, held[2], held[3], index=held[1])
        _key, name = page_of(window, widget)
        target.where = name or _plain(widget.window().windowTitle())
        return Located(target)
    text = _plain(args.get('text') or args.get('name'))
    if not text:
        raise PointError('要给 text（控件上的字）或 ref（ui_snapshot 的编号）')
    where = _plain(args.get('window'))
    visible = visible_targets(window, where=where)
    scored = _unique(best_matches(visible, text))
    page = _plain(args.get('page'))
    if scored and scored[0][0] < WORDS_ONLY:
        # 2026-11-22 live run: 「快捷键」 matched only the 说明 button's tooltip; the settings section of that
        # name (or a control named so on another page) is what was meant.
        hidden = [target for target in hidden_page_targets(window) if not page or target.page == page]
        strong = [(score, target) for score, target in _unique(best_matches(hidden, text)) if score >= WORDS_ONLY]
        if strong:
            return Located(strong[0][1], go_page=strong[0][1].page)
        entry = _feature_for(window, text)
        if entry is not None:
            return Located(None, open_entry=entry)
    if scored:
        top_score = scored[0][0]
        tied = [target for score, target in scored if score == top_score]
        controls = [target for target in tied if target.kind not in ('label', 'group')]
        if len(tied) > 1 and len({target.where for target in tied}) == 1 and (len(controls) > 1 or not controls):
            from .bunny_ui_control import _ref, Element
            rows = []
            for target in tied[:5]:
                key = _ref(Element(target.widget, target.kind if target.kind in ('tab', 'item') else target.kind,
                                   target.label, tab=target.index))
                rows.append(f'{key} {target.describe()}')
            raise PointError(f'「{text}」对得上好几个，用 ref 指定是哪一个：' + '；'.join(rows))
        return Located(controls[0] if controls else tied[0])
    hidden = hidden_page_targets(window)
    if page:
        hidden = [target for target in hidden if target.page == page] or hidden
    scored = _unique(best_matches(hidden, text))
    if scored:
        return Located(scored[0][1], go_page=scored[0][1].page)
    if page in NAV_PAGES and not any(key == page for key, _name, _root in page_roots(window)):
        return Located(None, go_page=page)                  # a page never opened yet: go, then look
    entry = _feature_for(window, text)
    if entry is not None:
        return Located(None, open_entry=entry)
    names = closest_names([*visible, *hidden], text)
    built = {key for key, _name, _root in page_roots(window)}
    from .bunny_actions import PAGES
    unseen = [PAGES[key] for key in NAV_PAGES if key not in built and key in PAGES]
    raise PointError(f'界面上没有找到「{text}」' + (f'；最像的是：{"、".join("「" + name + "」" for name in names)}'
                                                  if names else '')
                     + (f'；还没打开过的页面（{"、".join(unseen)}）没找过，确定在那里的话带 page 再试' if unseen else '')
                     + '。不要指别的地方，照实告诉小兔纸')


# ------------------------------------------------------------------ the request the chat draws
def request(window, target: Target | None = None, *, text: str = '', where: str = '', wait_open: bool = False) -> None:
    """Leave the point for the chat to draw with her answer (her words and the outline arrive together)."""
    data = {'text': text, 'where': where, 'deadline': time.monotonic() + OPEN_WAIT_S if wait_open else 0.0}
    if target is not None:
        data.update(widget=weakref.ref(target.widget), kind=target.kind, label=target.label, index=target.index,
                    target_where=target.where)
    try:
        window._bunny_point = data
    except Exception:  # noqa: BLE001 - a window that takes no attributes cannot be pointed at later
        pass


def take(window) -> dict | None:
    data = getattr(window, '_bunny_point', None)
    try:
        window._bunny_point = None
    except Exception:  # noqa: BLE001
        pass
    return data


def resolve_request(window, data: dict) -> tuple[Target | None, list[str], list[str]]:
    """The target of a stored request, checked again now: (target, problems, notes)."""
    target = None
    held = data.get('widget')
    widget = held() if held is not None else None
    if widget is not None and _alive(widget):
        target = Target(widget, data['kind'], data['label'], data.get('target_where', ''), data.get('index', -1))
    elif data.get('text'):
        try:
            found = locate(window, {'text': data['text'], 'window': data.get('where', '')})
        except PointError as exc:
            return None, [str(exc)], []
        target = found.target if found.target is not None and not found.go_page and found.open_entry is None else None
        if target is None:
            return None, [f'「{data["text"]}」现在不在屏幕上'], []
    else:
        return None, ['要指的控件已经不在了'], []
    problems, notes = verify(target, wanted=data.get('text', ''))
    return (None if problems else target), problems, notes


def resolve_text(window, text: str) -> tuple[Target | None, list[str], list[str]]:
    """A ``point_to`` that names a control by its words instead of a feature key (on screen only)."""
    try:
        found = locate(window, {'text': text})
    except PointError as exc:
        return None, [str(exc)], []
    if found.target is None or found.go_page or found.open_entry is not None:
        return None, [f'「{text}」现在不在屏幕上'], []
    problems, notes = verify(found.target, wanted=text)
    return (None if problems else found.target), problems, notes


# ------------------------------------------------------------------ the tool
NAV_WAIT_S = 3.0                 # a page she went to has this long to come up (lazy build, transition cover)


def _after_going(window, args, text: str, page_name: str) -> Located:
    """Look again once the page she went to is up (2026-11-22 live run: the history page was still being
    built right after the switch, and the first look found nothing)."""
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication
    from .bunny_tools import ToolError
    deadline = time.monotonic() + NAV_WAIT_S
    error = ''
    while True:
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            again = locate(window, {**args, 'page': ''})
            if again.target is not None and not again.go_page and again.open_entry is None \
                    and not verify(again.target, wanted=text)[0]:
                return again
            error = f'那里没有「{text}」'
        except PointError as exc:
            error = str(exc)
        if time.monotonic() >= deadline:
            raise ToolError(f'切到「{page_name}」了，但是{error}')
        time.sleep(0.03)


HINT_INTENT = re.compile(r'在哪|哪里|哪儿|哪个按钮|指(给|一下|出|指)|位置在|怎么找到|找不到.{0,8}(按钮|选项|开关)')
HINT_QUOTED = re.compile(r'[「“"『]([^」”"』]{1,30})[」”"』]')
HINT_BEFORE = re.compile(r'([^\s，。？！,.?!「」“”]{2,24}?)(?:的)?(?:按钮|按键|开关|选项|输入框|框|那一页|页面|那个|这个)?(?=在哪|在哪里|在哪儿|在什么地方)')
HINT_LIMIT = 4
HINT_PREFIX = re.compile(r'^(请问|那个|这个窗口|这个页面|这个对话框|这个|我想知道|帮我看看|帮我指一下|帮我找|一下|这里|这页|这一页|窗口|页面|对话框)+')


def hint_names(question: str) -> list[tuple[str, bool]]:
    """(name, quoted) for a "where is X" question; a quoted name is the user's exact words."""
    text = str(question or '')
    if not HINT_INTENT.search(text):
        return []
    names = [(name.strip(), True) for name in HINT_QUOTED.findall(text)]
    if not names:
        guessed = [GENERIC.sub('', name).strip() for name in HINT_BEFORE.findall(text)]
        names = []
        for name in guessed:
            name = HINT_PREFIX.sub('', name)
            names.append((name, False))
            tail = re.split(r'里面|里的|里|中的|上的', name)[-1]     # 「术语库里添加词条」 -> 「添加词条」
            if tail and tail != name:
                names.append((HINT_PREFIX.sub('', tail), False))
    seen = []
    for name, quoted in names:
        if len(name) >= 2 and name not in [old for old, _q in seen]:
            seen.append((name, quoted))
    return seen[:HINT_LIMIT]


def hint_for(window, question: str) -> str:
    """2026-11-22 (live run: asked for 「交给兔白」 on the completion page, she guessed it did not exist):
    for a "where is X" question the live widget tree is searched before she answers; what was found
    (or that nothing was) goes with the question. No AI request, nothing is pointed at yet."""
    rows = []
    names = hint_names(question)
    if HINT_INTENT.search(str(question or '')):
        try:                     # 2026-11-22 live run: asked about "this window", she did not know one was open
            from PySide6.QtWidgets import QDialog
            from .bunny_ui_control import _plain, _tops
            open_now = []
            for top in _tops(window):
                if top is window:
                    continue
                title = _plain(top.windowTitle())
                if title or isinstance(top, QDialog):
                    open_now.append(title or '对话框')
        except Exception:  # noqa: BLE001
            open_now = []
        if open_now:
            rows.append(f'- 现在开着的窗口：{"、".join("「" + title + "」" for title in open_now[:3])}（在主窗口上面，“这个窗口”多半指它）')
    for name, quoted in names:
        try:
            found = locate(window, {'text': name})
        except PointError as exc:
            if quoted:            # a guessed name that matches nothing says nothing about the screen
                rows.append(f'- 「{name}」：{str(exc).split("。")[0]}')
            continue
        if found.open_entry is not None:
            rows.append(f'- 「{name}」：在「{found.open_entry.where}」（现在没打开；point_at 会先打开再指，只指路时用 offer_open={found.open_entry.key}）')
        elif found.go_page:
            from .bunny_actions import PAGES
            label = found.target.describe() if found.target is not None else f'「{name}」'
            short = found.target.label if found.target is not None else name
            rows.append(f'- 「{name}」：{label} 在「{PAGES.get(found.go_page, found.go_page)}」页，现在看不到；'
                        f'point_at(text={short}, page={found.go_page}) 会先切过去再指（只指路时改用「带我去」）')
        elif found.target is not None:
            rows.append(f'- 「{name}」：{found.target.describe()}，现在就在屏幕上')
    if not rows:
        return ''
    return ('【兔白先在屏幕上找了一下】\n' + '\n'.join(rows)
            + '\n小兔纸问在哪，找到了就一定要指给他看（point_at 或 point_to），光用嘴说路不算；写着“没有”的就照实说没有，不要指别的。')


def _guide() -> bool:
    try:
        from . import bunny_permissions
        return bunny_permissions.load().get('level') == 'guide'
    except Exception:  # noqa: BLE001
        return False


def _point_at(window, args) -> str:
    from .bunny_tools import ToolError
    try:
        found = locate(window, args)
    except PointError as exc:
        raise ToolError(str(exc)) from None
    text = str(args.get('text') or '').strip()
    if found.open_entry is not None:
        entry = found.open_entry
        if _guide():
            raise ToolError(f'「{text}」在「{entry.where}」，现在没打开。只指路模式兔白不替小兔纸打开：'
                            f'用 offer_open={entry.key} 让他按「带我去」，到了再指')
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, entry.run)
        request(window, text=text, wait_open=True)
        return f'「{text}」在「{entry.where}」，现在帮小兔纸打开，打开后外框会框住它（打开后可以再 point_at 确认）'
    if found.go_page:
        from .bunny_actions import PAGES, _open_page
        page = found.go_page
        pages = getattr(window, 'pages', None)
        already = pages is not None and page_of(window, pages.currentWidget())[0] == page
        if _guide() and not already:
            offer = PAGE_OFFER.get(page, '')
            raise ToolError(f'「{text or found.target.label}」在「{PAGES.get(page, page)}」页，现在看不到。只指路模式兔白不切页面'
                            + (f'：用 offer_open={offer} 让小兔纸按「带我去」' if offer else '：告诉小兔纸先去那一页'))
        if not already:
            try:
                _open_page(window, page)
            except Exception as exc:  # noqa: BLE001
                raise ToolError(f'「{PAGES.get(page, page)}」页现在打不开：{exc}') from None
        found = _after_going(window, args, text or found.target.label, PAGES.get(page, page))
        gone_to = '' if already else f'先切到「{PAGES.get(page, page)}」页，'
    else:
        gone_to = ''
    target = found.target
    problems, notes = verify(target, wanted=text)
    if problems:
        raise ToolError('；'.join(problems) + '。没有指，照实告诉小兔纸')
    request(window, target, text=text)
    target.where = page_of(window, target.widget)[1] or target.where
    return f'{gone_to}指好了：{target.describe()}' + (f'；{"；".join(notes)}' if notes else '') + '。回答时外框会框住它'


def tools():
    from .bunny_tools import Tool
    return (
        Tool('point_at', '{"text": "保存更改", "window": "", "page": ""}',
             '把外框框到屏幕上任何一个按钮、勾选、下拉、页签、列表项或一段字上，指给小兔纸看（只看不按，只指路也能用）：'
             'text 填控件上的字（或 ref 填 ui_snapshot 的编号），window 只找某个窗口，page 填它所在的页面（home / workshop / terms / '
             'history / studio）。会先检查它在不在、看不看得到、能不能按、名字对不对；不在当前页时先切过去、在设置里时先打开再指；'
             '回执说“指好了”才算指到，没指到就照实说，不要说“看这里”', _point_at),
    )


__all__ = ['Located', 'PointError', 'Target', 'covered', 'global_rect', 'hidden_page_targets', 'locate', 'page_roots',
           'request', 'resolve_request', 'resolve_text', 'take', 'tools', 'verify', 'visible_targets']
