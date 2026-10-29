"""Timeline toolbar in the real Studio window (2026-10-21).

User report: the timeline toolbar wraps onto two rows, the transport pill is not
centred under the video, and toolbar tooltips are cut off. For each window
width this records the command groups' real geometry (rows, transport centre
against the video centre), captures the window, then shows each toolbar
tooltip and compares the tip's width with its text. With the redesign it also
checks the 「…」 menu entries and the "+" above the track names.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        try:
            code = run(Path(output), window=window)
        except Exception:
            (Path(output) / 'result.json').write_text(json.dumps(dict(passed=False, error=traceback.format_exc())), 'utf8')
            code = 1
        window.result_exit_code = code

        def stopped():
            path = Path(output) / 'result.json'
            result = json.loads(path.read_text('utf8'))
            result['gui_shutdown'] = True
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(100, execute)


def run(output, *, window):
    from PySide6.QtCore import QCoreApplication, QEvent, QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QToolTip, QWidget
    from .blank_project_audit import _capture
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
                                           hydrate_media_contract, save_project)
    from ..studio.studio_helpers import probe_media_identity

    output = Path(output).resolve()
    if output != Path(os.environ['TWOBYTEASR_TEST_ROOT']).resolve():
        raise RuntimeError('isolated root required')
    theme = os.environ.get('TWOBYTEASR_TOOLBAR_THEME', 'grape')
    apply_theme(theme)
    expect_redesign = os.environ.get('TWOBYTEASR_TOOLBAR_EXPECT', 'after') == 'after'
    widths = [int(value) for value in os.environ.get('TWOBYTEASR_TOOLBAR_WIDTHS', '1280,1440,1600,1920').split(',')]
    media = Path(os.environ['TWOBYTEASR_TOOLBAR_MEDIA']).resolve()
    result = dict(passed=False, checks=[], widths=[], tooltips=[], theme=theme, expect_redesign=expect_redesign,
                  identity=load_build_identity().to_dict(), frozen=bool(getattr(sys, 'frozen', False)),
                  platform=QApplication.platformName(), pid=os.getpid())

    def receipt():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    def check(name, value, detail=None):
        result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
        receipt()

    def wait(fn, label, seconds=60):
        end = time.monotonic() + seconds
        while not fn():
            if time.monotonic() > end:
                raise TimeoutError(label)
            QTest.qWait(20)

    page = window.studio_page
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=10000, width=3840, height=2160),
                              cues=[StudioCue(f'c{i}', i * 1500, i * 1500 + 1300, f'第 {i + 1} 句字幕',
                                              speaker_id='S01' if i % 2 else 'S02') for i in range(6)])
    project.speakers = [StudioSpeaker(id='S01', name='mio'), StudioSpeaker(id='S02', name='mai')]
    hydrate_media_contract(project, probe_media_identity(str(media)))
    project.validate()
    path = output / 'toolbar.2byteproj'
    save_project(project, path)

    window.resize(1600, 1000)
    window.show()
    QTest.qWait(300)
    prior = page.project
    window.open_studio_project(str(path), mode='edit', source='timeline_toolbar_audit')
    wait(lambda: page.project is not None and page.project is not prior and page._readiness.ready, 'project readiness')
    wait(lambda: page.video.controller is not None, 'player')
    QTest.qWait(800)
    if not page.video._paused:
        page._toggle_playback()
    QTest.qWait(300)

    bar = page._timeline_command_bar

    def rect_in(widget, ancestor):
        origin = widget.mapTo(ancestor, widget.rect().topLeft())
        return (origin.x(), origin.y(), widget.width(), widget.height())

    for width in widths:
        window.resize(width, 1000)
        QTest.qWait(700)
        groups = []
        for group in page._timeline_group_widgets:
            if group.isVisible():
                groups.append(dict(role=group.property('commandGroup'), rect=rect_in(group, window)))
        # One row = vertical centres within 8 px (the transport pill is taller).
        rows = []
        for centre in sorted(g['rect'][1] + g['rect'][3] / 2 for g in groups):
            if not rows or centre - rows[-1] > 8:
                rows.append(centre)
        transport = next(g for g in groups if g['role'] == 'transport')
        video = rect_in(page.video, window)
        transport_centre = transport['rect'][0] + transport['rect'][2] / 2
        video_centre = video[0] + video[2] / 2
        overlaps = [(a['role'], b['role']) for i, a in enumerate(groups) for b in groups[i + 1:]
                    if a['rect'][1] == b['rect'][1]
                    and a['rect'][0] < b['rect'][0] + b['rect'][2] and b['rect'][0] < a['rect'][0] + a['rect'][2]]
        clipped = [g['role'] for g in groups if g['rect'][0] < 0 or g['rect'][0] + g['rect'][2] > window.width()]
        entry = dict(width=window.width(), bar=(bar.width(), bar.height()), rows=len(rows), groups=groups,
                     video=video, transport_offset=round(transport_centre - video_centre, 1),
                     overlaps=overlaps, clipped=clipped)
        shot = output / f'window-{window.width()}.png'
        _capture(window, shot)
        bar.grab().save(str(output / f'bar-{window.width()}.png'))
        entry['screenshot'] = shot.name
        result['widths'].append(entry)
        if expect_redesign:
            check(f'{window.width()}: one row', len(rows) == 1, entry['rows'])
            # Below 1440 the left tools need the room the centred pill would take.
            limit = 2 if window.width() >= 1440 else 40
            check(f'{window.width()}: transport centred on the video (<= {limit} px)',
                  abs(entry['transport_offset']) <= limit,
                  dict(offset=entry['transport_offset'], video=video, transport=transport['rect']))
        check(f'{window.width()}: no overlap or clipping', not overlaps and not clipped, dict(overlaps=overlaps, clipped=clipped))

    window.resize(1600, 1000)
    QTest.qWait(700)
    if expect_redesign:
        # Hiding / showing a side panel moves the video; the pill follows it.
        def offset():
            """Pill centre minus video centre, and whether the pill already
            sits right after the editing tools (it may not cover them)."""
            groups = {g.property('commandGroup'): g for g in page._timeline_group_widgets}
            t, v = rect_in(groups['transport'], window), rect_in(page.video, window)
            e = rect_in(groups['editing'], window)
            value = round(t[0] + t[2] / 2 - (v[0] + v[2] / 2), 1)
            return dict(offset=value, at_tools=t[0] - (e[0] + e[2]) <= page._timeline_command_layout.spacing() + 1)
        panels = {}
        for label, button in (('字幕列表', page.cue_list_toggle_button), ('工具面板', page.context_expand_button)):
            button.click()
            QTest.qWait(700)
            panels[label + ' hidden'] = offset()
            _capture(window, output / f'panel-{"cues" if label == "字幕列表" else "tools"}-hidden.png')
            button.click()
            QTest.qWait(700)
            panels[label + ' shown'] = offset()
        result['panels'] = panels
        check('pill follows the video when panels hide / show (or stops at the tools)',
              all(abs(item['offset']) <= 2 or (item['offset'] > 0 and item['at_tools']) for item in panels.values()), panels)
    names = ['add_subtitle_button', 'selection_tool_button', 'track_forward_tool_button', 'razor_tool_button',
             'merge_tool_button', 'cue_more_button', 'play_button', 'timecode_input', 'speed_box',
             'preview_scale_box', 'volume_slider', 'timeline_fit_button', 'waveform_toggle', 'filmstrip_toggle',
             'follow_playhead_toggle', 'snap_toggle', 'save_frame_button', 'make_cover_button',
             'timeline_options_button', 'media_pool_button', 'add_video_track_button', 'add_subtitle_track_button',
             'timeline_add_track_button']
    for name in names:
        widget = getattr(page, name, None)
        if not isinstance(widget, QWidget) or not widget.isVisible() or not widget.toolTip():
            result['tooltips'].append(dict(name=name, shown=False,
                                           visible=bool(isinstance(widget, QWidget) and widget.isVisible())))
            continue
        # A fresh tip each time, as real hovering creates: drop the last one.
        QToolTip.hideText()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QTest.qWait(80)
        text = widget.toolTip()
        QToolTip.showText(widget.mapToGlobal(QPoint(widget.width() // 2, widget.height())), text, widget)
        QTest.qWait(350)
        tips = [w for w in QApplication.topLevelWidgets()
                if w.metaObject().className() == 'QTipLabel' and w.isVisible()]
        if not tips:
            result['tooltips'].append(dict(name=name, shown=False, text=text))
            continue
        tip = tips[0]
        metrics = tip.fontMetrics()
        needed = max(metrics.horizontalAdvance(line) for line in text.split('\n'))
        margins = tip.contentsMargins()
        inner = tip.contentsRect().width()
        font = tip.font()
        item = dict(name=name, shown=True, text=text, size=(tip.width(), tip.height()), inner_width=inner,
                    text_width=needed, margins=(margins.left(), margins.right()),
                    font=dict(family=font.family(), pixels=font.pixelSize(), points=font.pointSizeF(),
                              weight=int(font.weight())),
                    tooltip_class_font=dict(family=QToolTip.font().family(), points=QToolTip.font().pointSizeF(),
                                            pixels=QToolTip.font().pixelSize()))
        tip.grab().save(str(output / f'tip-{name}.png'))
        result['tooltips'].append(item)
        check(f'tooltip {name}: whole text fits', inner >= needed, dict(inner=inner, text=needed, text_value=text))
    QToolTip.hideText()

    if expect_redesign:
        more = page.cue_more_button.menu()
        more.aboutToShow.emit()
        entries = [action.text() for action in more.actions()]
        submenus = [action.text() for action in more.actions() if action.menu() is not None]
        result['more_menu'] = dict(entries=entries, submenus=submenus)
        for label in ('打开媒体池', '新建字幕轨', '新建视频轨'):
            check(f'「…」 has {label}', any(label in entry for entry in entries), entries)
        check('「…」 has 转场', any('转场' in entry for entry in submenus), submenus)
        plus = getattr(page, 'timeline_add_track_button', None)
        check('"+" above track names', plus is not None and plus.isVisible(), None if plus is None else rect_in(plus, page.timeline))
        if plus is not None:
            plus.menu().aboutToShow.emit()
            plus_entries = [action.text() for action in plus.menu().actions()]
            result['plus_menu'] = plus_entries
            check('"+" offers subtitle and video tracks',
                  any('字幕轨' in e for e in plus_entries) and any('视频轨' in e for e in plus_entries), plus_entries)
            page.timeline.grab().save(str(output / 'timeline-corner.png'))
            by_text = {action.text(): action for action in plus.menu().actions()}
            videos, undo = len(page.project.video_tracks), page.undo_stack.count()
            next(action for text, action in by_text.items() if '视频轨' in text).trigger()
            QTest.qWait(300)
            check('"+" 新建视频轨 adds a video track', len(page.project.video_tracks) == videos + 1,
                  dict(before=videos, after=len(page.project.video_tracks)))
            undo = page.undo_stack.count()
            next(action for text, action in by_text.items() if '字幕轨' in text).trigger()
            QTest.qWait(300)
            check('"+" 新建字幕轨 adds an undoable step', page.undo_stack.count() == undo + 1,
                  dict(before=undo, after=page.undo_stack.count(), text=page.undo_stack.text(page.undo_stack.count() - 1)))
            QTest.qWait(300)
            _capture(window, output / 'after-new-tracks.png')
            # Leave the project as opened so closing asks nothing.
            page.undo_stack.undo()
            page.undo_stack.undo()
            page.save()
            QTest.qWait(800)
        # The three menus as the user sees them (popup windows, Qt-painted).
        for label, button in (('more', page.cue_more_button), ('plus', page.timeline_add_track_button),
                              ('options', page.timeline_options_button)):
            menu = button.menu()
            menu.popup(button.mapToGlobal(QPoint(0, button.height())))
            QTest.qWait(400)
            menu.grab().save(str(output / f'menu-{label}.png'))
            menu.hide()
            QTest.qWait(150)
        add = page.add_subtitle_button
        check('添加字幕 is an icon only', not add.text() or add.toolButtonStyle() == add.toolButtonStyle().ToolButtonIconOnly,
              dict(text=add.text(), style=str(add.toolButtonStyle())))
        for name in ('media_pool_button', 'add_video_track_button', 'add_subtitle_track_button'):
            widget = getattr(page, name)
            check(f'{name} left the toolbar', not widget.isVisible(), widget.isVisible())

    result['passed'] = all(item['passed'] for item in result['checks'])
    receipt()
    return 0 if result['passed'] else 1
