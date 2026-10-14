"""Studio/secondary-page captures on a copy of the real run-01 profile.

Same boundary as showcase_run.py: a fresh copy of the run-01 profile (with
the real recognised project) under tmp; registered runtimes and repo models
are only read. Scenes drive the real widgets (mouse events on the timeline,
the speaker manager's own fields, candidate cards) and save native window
captures; recordings save timestamped frames for GIF encoding.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

REPO = Path(__file__).resolve().parents[2]
BASE = Path(os.environ.get('README_SHOWCASE_DIR') or Path(__file__).resolve().parents[2] / 'tmp' / 'readme-showcase').resolve()
sys.path.insert(0, str(Path(__file__).resolve().parent))


def outer(args):
    out = (BASE / 'runs' / args.name).resolve()
    if out.exists():
        raise SystemExit(f'{out} exists; choose a fresh name')
    source = (BASE / 'runs' / args.source).resolve()
    out.mkdir(parents=True)
    shutil.copytree(source / 'profile', out / 'profile')
    project = json.loads((source / 'result.json').read_text('utf8'))['project']
    project = str(out / Path(project).relative_to(source))
    spec = dict(project=project, size=args.size, theme=args.theme, lang=args.lang, scenes=args.scenes,
                final_preset=args.final_preset,
                started=time.strftime('%Y-%m-%dT%H:%M:%S'))
    (out / 'spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), 'utf8')
    profile = out / 'profile'
    # The copied profile's own settings decide language; keep it in sync.
    settings_path = profile / 'local' / '2ByteASR' / '2byteasr_settings.json'
    settings = json.loads(settings_path.read_text('utf8'))
    settings.setdefault('ui', {})['language'] = args.lang
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), 'utf8')
    env = {k: v for k, v in os.environ.items() if not k.endswith(('_API_KEY', '_ACCESS_TOKEN', '_AUTH_TOKEN'))}
    for key in ('TWOBYTEASR_TEST_ROOT', 'TWOBYTEASR_STARTUP_PROJECT', 'TWOBYTEASR_ACCEPTANCE_SCENARIO',
                'TWOBYTEASR_ACCEPTANCE_DIR', 'QT_SCALE_FACTOR', 'QT_ENABLE_HIGHDPI_SCALING', 'QT_FONT_DPI',
                'QT_SCALE_FACTOR_ROUNDING_POLICY'):
        env.pop(key, None)
    env.update(LOCALAPPDATA=str(profile / 'local'), APPDATA=str(profile / 'roaming'), TEMP=str(profile / 'temp'),
               TMP=str(profile / 'temp'), USERPROFILE=str(profile / 'home'), HF_HOME=str(profile / 'hf-cache'),
               MODELSCOPE_CACHE=str(profile / 'modelscope-cache'), TORCH_HOME=str(profile / 'torch-cache'),
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1', QT_QPA_PLATFORM='windows',
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               **{'2BYTEASR_USER_DATA_ROOT': str(profile / 'local'), '2BYTEASR_MODEL_ROOT': str(REPO / 'models')})
    env.update(QT_SCALE_FACTOR=args.scale, QT_ENABLE_HIGHDPI_SCALING='0', QT_FONT_DPI='96',
               QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough')
    sys.path.insert(0, str(REPO / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--inner', str(out)]
    code = run_on_desktop(command, cwd=REPO, env=env, output=out / 'process', timeout=args.timeout)
    result_path = out / 'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.is_file() else dict(error='no receipt')
    result['process_exit'] = code
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')
    print(json.dumps(dict(exit=code, shots=len(result.get('shots', [])), errors=result.get('errors', [])),
                     ensure_ascii=False, indent=1))
    return 0 if code == 0 else 1


def inner(out: Path):
    sys.path.insert(0, str(REPO))
    import faulthandler
    _fh = open(out / 'faulthandler.log', 'w')
    faulthandler.enable(file=_fh, all_threads=True)
    spec = json.loads((out / 'spec.json').read_text('utf8'))
    marks = open(out / 'marks.log', 'a', encoding='utf8')

    def mark(text):
        marks.write(time.strftime('%H:%M:%S') + ' ' + str(text) + chr(10))
        marks.flush()
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out / 'profile')
    from twobyteasr.test_isolation import install
    install()
    os.environ.pop('TWOBYTEASR_TEST_ROOT', None)
    os.environ['2BYTEASR_MODEL_ROOT'] = str(REPO / 'models')
    os.environ['USERPROFILE'] = str(out / 'profile' / 'home')
    from twobyteasr.blank_project_audit import install_offline_guards, _capture
    install_offline_guards()
    from PySide6.QtCore import QObject, QTimer, Qt, QPoint, QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    import moss_firered_pipeline
    import subtitle_core
    from twobyteasr import ui
    from twobyteasr.theme_manager import apply_application_theme
    from twobyteasr.i18n import save_language

    ui._configure_windows_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName('2ByteASR')
    app.setWindowIcon(ui._app_icon())
    app.setStyle('Fusion')
    save_language(spec['lang'])
    apply_application_theme(app, spec['theme'])
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())
    window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, {'id': 'readme-studio', 'checks': 0})
    width, height = (int(v) for v in spec['size'].split('x'))
    window.showNormal()
    window.resize(width, height)
    window.move(0, 0)
    window.show()
    result = dict(shots=[], errors=[], spec=spec, info={}, recordings={})
    t0 = time.monotonic()

    def write():
        (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    def grab(target, widget=None):
        widget = widget or window
        QApplication.processEvents()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            _capture(widget, target)
        except Exception:
            widget.grab().save(str(target), 'PNG')

    def shot(name, widget=None):
        grab(out / 'shots' / f'{name}.png', widget)
        result['shots'].append(dict(name=name, t=round(time.monotonic() - t0, 2)))
        write()

    class Recorder:
        def __init__(self, name):
            self.name = name
            self.dir = out / 'frames' / name
            self.stamps = []

        def frame(self):
            index = len(self.stamps)
            grab(self.dir / f'{index:04d}.png')
            self.stamps.append(round(time.monotonic(), 4))

        def hold(self, seconds, fps=8):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                self.frame()
                yield 1.0 / fps

        def finish(self):
            result['recordings'][self.name] = dict(frames=len(self.stamps), stamps=self.stamps)
            write()

    def top_dialog():
        candidates = [w for w in QApplication.topLevelWidgets()
                      if w is not window and w.isVisible() and w.isWindow() and w.width() > 120
                      and type(w).__name__ not in {'QMenu', 'QToolTip'}]
        return candidates[-1] if candidates else None

    def close_modals():
        for widget in QApplication.topLevelWidgets():
            if widget is not window and widget.isVisible() and widget.isWindow():
                if type(widget).__name__ in {'QMenu'}:
                    widget.close()
                elif hasattr(widget, 'reject'):
                    widget.reject()
                else:
                    widget.close()
        host = getattr(window, '_modal_host', None)
        if host is not None and host.isVisible():
            host.hide_content()

    def page():
        return window.studio_page

    def studio_ready():
        p = window.studio_page
        readiness = getattr(p, '_readiness', None)
        return bool(p.project is not None and readiness is not None and readiness.ready
                    and not readiness.active and p._project_view_state == 'open')

    def open_studio():
        if studio_ready():
            return
        window.open_studio_project(spec['project'])
        deadline = time.monotonic() + 60
        while not studio_ready() and time.monotonic() < deadline:
            yield 0.4
        yield 2.0

    def cue_by_text(prefix):
        for cue in sorted(page().project.cues, key=lambda c: c.start_ms):
            if cue.text.startswith(prefix):
                return cue
        raise LookupError(prefix)

    def cues_brief():
        return [dict(id=c.id, s=c.start_ms, e=c.end_ms, spk=c.speaker_id, text=c.text)
                for c in sorted(page().project.cues, key=lambda c: c.start_ms)]

    # --- timeline mouse helpers (logical coordinates of the timeline widget)
    def lane_y(speaker_id):
        lanes = page().timeline._track_layout()[0]
        rect = lanes[speaker_id]
        return rect.center().y()

    def tl_point(ms, speaker_id):
        tl = page().timeline
        return QPointF(tl._time_to_x(int(ms)), lane_y(speaker_id))

    def send_mouse(kind, pos, buttons):
        tl = page().timeline
        button = Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
        event = QMouseEvent(kind, pos, tl.mapToGlobal(pos.toPoint()).toPointF(), button, buttons,
                            Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(tl, event)

    def press(pos):
        send_mouse(QEvent.Type.MouseButtonPress, pos, Qt.MouseButton.LeftButton)

    def move(pos, held=True):
        send_mouse(QEvent.Type.MouseMove, pos, Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton)

    def release(pos):
        send_mouse(QEvent.Type.MouseButtonRelease, pos, Qt.MouseButton.NoButton)

    def word_boundaries(cue):
        """Snap candidates the razor uses (ms) inside a cue, from the project."""
        try:
            from twobyteasr.studio_split import word_boundaries_for_cue  # type: ignore
            return list(word_boundaries_for_cue(page().project, cue))
        except Exception:
            return []

    def show_window(start_ms, duration_ms):
        page().timeline.set_visible_window(int(start_ms), int(duration_ms))

    # ------------------------------------------------------------- scenes
    def scene_explore():
        yield from open_studio()
        p = page()
        shot('studio-open')
        result['info']['cues'] = cues_brief()
        result['info']['speakers'] = [dict(id=s.id, name=s.name, color=s.color) for s in p.project.speakers]
        info = result['info']
        for attr in ('style_preset', 'style_scope', 'effect_preset', 'context_drawer'):
            widget = getattr(p, attr, None)
            if widget is None:
                info[attr] = None
                continue
            if hasattr(widget, 'count') and hasattr(widget, 'itemText'):
                info[attr] = [widget.itemText(i) for i in range(widget.count())]
            elif hasattr(widget, 'count') and hasattr(widget, 'tabText'):
                info[attr] = [widget.tabText(i) for i in range(widget.count())]
            else:
                info[attr] = type(widget).__name__
        drawer = getattr(p, 'context_drawer', None)
        if drawer is not None:
            for index in range(drawer.count()):
                drawer.setCurrentIndex(index)
                yield 1.0
                shot(f'tab-{index}')
        write()
        # candidate cards for the line MOSS/FireRed and Qwen disagree on
        target = cue_by_text('他你从侧面打')
        p.select_cue(target.id)
        yield 1.2
        shot('select-tazhe')
        cands = getattr(p, '_review_candidates', ())
        info['candidates_tazhe'] = [dict(text=c.text, sources=list(c.sources), context=c.context_only) for c in cands]
        write()
        for name, opener in (('speakers', p._open_speaker_manager), ('find', getattr(p, '_open_find_replace', None)),
                             ('render', p._open_render_dialog)):
            if opener is None:
                continue
            QTimer.singleShot(0, opener)
            yield 2.5
            shot(f'dlg-{name}')
            dialog = top_dialog()
            if dialog is not None:
                shot(f'dlg-{name}-only', dialog)
            close_modals()
            yield 1.0
        export = getattr(p, '_export_subtitles', None)
        if export is not None:
            QTimer.singleShot(0, export)
            yield 2.0
            shot('dlg-export-subs')
            dialog = top_dialog()
            if dialog is not None:
                shot('dlg-export-subs-only', dialog)
            close_modals()
            yield 1.0
        info['tool_methods'] = sorted(n for n in dir(p) if any(k in n for k in ('tool', 'razor', 'merge', 'play', 'style_')))[:200]
        write()

    def scene_pages():
        window._open_model_workshop()
        yield 2.0
        shot('page-workshop')
        window._manage_terms()
        yield 2.0
        shot('page-terms')
        window._return_to_settings()
        yield 1.0

    # ------------------------------------------------ real editing scenes
    def pause():
        p = page()
        try:
            if not p.video.playback_position_snapshot().paused:
                p._toggle_playback()
        except Exception:
            result['errors'].append(dict(scene='pause', error=traceback.format_exc()[-600:]))

    def tool(mode):
        page()._set_timeline_tool(mode)

    def tall(share=0.5):
        sizes = page().workspace_splitter.sizes()
        total = sum(sizes)
        page().workspace_splitter.setSizes([round(total * share), total - round(total * share)])

    def split_target(cue, left_text):
        """Time range where the razor yields exactly ``left_text`` (same resolver as the timeline)."""
        from twobyteasr.studio_timing import resolve_split
        hits = []
        for ms in range(cue.start_ms + 20, cue.end_ms - 20, 5):
            preview = resolve_split(cue, ms, project=page().project)
            if preview is not None and preview.left_text == left_text:
                hits.append(ms)
        if not hits:
            raise LookupError(f'no razor point for {left_text!r} in {cue.text!r}')
        return hits[len(hits) // 2], hits

    def merge_drag(cue, rec=None, steps=6):
        p = page()
        tool('merge')
        yield 0.3
        mid = (cue.start_ms + cue.end_ms) // 2
        start = tl_point(mid, cue.speaker_id)
        move(start, held=False)
        press(start)
        if rec:
            rec.frame()
        for k in range(1, steps + 1):
            move(QPointF(start.x() + 7 * k, start.y()))
            yield 0.06
            if rec:
                rec.frame()
        if rec:
            yield from rec.hold(0.7)
        release(QPointF(start.x() + 7 * steps, start.y()))
        yield 0.5

    def razor_drag(cue, left_text, rec=None, steps=16):
        target, _hits = split_target(cue, left_text)
        tool('razor')
        yield 0.3
        begin_ms = cue.start_ms + int((target - cue.start_ms) * 0.25)
        origin = tl_point(begin_ms, cue.speaker_id)
        end = tl_point(target, cue.speaker_id)
        move(origin, held=False)
        press(origin)
        for k in range(1, steps + 1):
            x = origin.x() + (end.x() - origin.x()) * k / steps
            move(QPointF(x, origin.y()))
            yield 0.05
            if rec:
                rec.frame()
        if rec:
            yield from rec.hold(1.0)
        release(end)
        yield 0.5
        return target

    def scene_speakers():
        yield from open_studio()
        pause()
        p = page()
        mark('open speaker manager')
        QTimer.singleShot(0, p._open_speaker_manager)
        yield 2.0
        dialog = top_dialog()
        mark(f'dialog {type(dialog).__name__}')
        result['info']['speaker_dialog'] = type(dialog).__name__ if dialog else None
        if dialog is not None and hasattr(dialog, 'name_edit'):
            tabs = dialog.findChildren(__import__('PySide6.QtWidgets', fromlist=['QTabWidget']).QTabWidget)
            if tabs:
                tabs[0].setCurrentIndex(min(1, tabs[0].count() - 1))
                yield 0.6
            for speaker_id, name in (('S01', '河边探险家'), ('S02', '白兔')):
                mark(f'refresh {speaker_id}')
                dialog.refresh(speaker_id)
                yield 0.4
                mark('typing')
                dialog.name_edit.setFocus()
                dialog.name_edit.setText(name)
                dialog._commit_name()
                yield 0.6
            shot('speakers-dialog', dialog)
            dialog.accept()
            yield 1.0
        result['info']['speakers_after'] = [dict(id=s.id, name=s.name) for s in p.project.speakers]
        shot('speakers-after')

    def scene_razor():
        yield from open_studio()
        pause()
        tall(0.44)
        p = page()
        p._seek(5.6)
        show_window(3600, 7200)
        p.select_cue(cue_by_text('我拿到了你们先').id)
        yield 1.0
        rec = Recorder('razor')
        yield from rec.hold(1.0)
        yield from merge_drag(cue_by_text('我拿到了你们先'), rec)
        yield from rec.hold(1.2)
        merged = cue_by_text('我拿到了你们先走')
        yield from razor_drag(merged, '我拿到了你们先走', rec)
        yield from rec.hold(1.2)
        tool('selection')
        p.select_cue(cue_by_text('我在后面跟上').id)
        yield from rec.hold(1.4)
        rec.finish()
        result['info']['after_razor'] = cues_brief()
        write()

    def scene_review():
        yield from open_studio()
        pause()
        tall()
        p = page()
        show_window(14800, 7600)
        target = cue_by_text('他你从侧面打')
        rec = Recorder('review')
        yield from rec.hold(0.8)
        QTest.mouseClick(p.review_entry_button, Qt.MouseButton.LeftButton)
        yield 0.8
        p.select_cue(target.id)
        p._seek(target.start_ms / 1000.0)
        yield 0.2
        p._refresh_review_summary_strip()
        yield from rec.hold(2.0)
        from twobyteasr.studio_cards import ReviewCandidateCard
        cards = [c for c in p.findChildren(ReviewCandidateCard) if c.isVisible()]
        result['info']['review_cards'] = [dict(text=c._candidate.text, sources=list(c._candidate.sources)) for c in cards]
        qwen = next((c for c in cards if 'Qwen' in c._candidate.sources and len(c._candidate.sources) == 1), None)
        if qwen is not None:
            QTest.mouseMove(qwen)
            yield from rec.hold(0.6)
            QTest.mouseClick(qwen, Qt.MouseButton.LeftButton)
        yield from rec.hold(2.2)
        rec.finish()
        result['info']['after_review'] = cues_brief()
        QTest.mouseClick(p.review_entry_button, Qt.MouseButton.LeftButton)
        yield 0.8
        write()

    def scene_fixups():
        """Same real tools, not recorded: move the remaining awkward cut points."""
        yield from open_studio()
        pause()
        tall()
        p = page()
        for first, whole, left in (('小心右边的草丛好像', '小心右边的草丛好像有一只史莱姆', '小心右边的草丛'),
                                   ('看到了我先拉住', '看到了我先拉住它你从侧面打', '看到了我先拉住它'),
                                   ('下一关是首领先回', '下一关是首领先回营地补满状态吧', '下一关是首领')):
            try:
                cue = cue_by_text(first)
                show_window(max(0, cue.start_ms - 1500), 7600)
                yield 0.4
                yield from merge_drag(cue)
                merged = cue_by_text(whole)
                yield from razor_drag(merged, left)
            except Exception:
                result['errors'].append(dict(scene='fixups', cue=first, error=traceback.format_exc()[-900:]))
        tool('selection')
        result['info']['after_fixups'] = cues_brief()
        write()
        yield 0.5

    def scene_style():
        yield from open_studio()
        pause()
        p = page()
        cue = cue_by_text('好技能')
        p.select_cue(cue.id)
        p._seek((cue.start_ms + 900) / 1000.0)
        show_window(14000, 16000)
        p.context_drawer.setCurrentIndex(1)
        yield 1.4
        scope = p.style_scope
        index = scope.findData('all')
        if index >= 0:
            scope.setCurrentIndex(index)
        rec = Recorder('style')
        yield from rec.hold(1.0)
        order = [p.style_preset.findText(name) for name in ('游戏字幕', '双人对话 白', '直播切片', '双人对话 蓝', '简洁白字', '2Byte 默认')]
        for idx in [i for i in order if i >= 0]:
            p.style_preset.setCurrentIndex(idx)
            p.style_preset.activated.emit(idx)
            yield 0.5
            yield from rec.hold(1.3)
            shot(f'style-{p.style_preset.itemText(idx)}')
        rec.finish()
        final = p.style_preset.findText(spec.get('final_preset', '游戏字幕'))
        if final >= 0:
            p.style_preset.setCurrentIndex(final)
            p.style_preset.activated.emit(final)
            yield 1.0
        shot('style-final')

    def scene_style2(with_effect=True):
        yield from open_studio()
        pause()
        tall()
        p = page()
        cue = cue_by_text('好技能')
        p.select_cue(cue.id)
        p._seek((cue.start_ms + 1500) / 1000.0)
        show_window(17000, 13000)
        p.context_drawer.setCurrentIndex(1)
        yield 1.4
        index = p.style_scope.findData('all')
        if index >= 0:
            p.style_scope.setCurrentIndex(index)
        yield 0.4
        rec = Recorder('style')
        yield from rec.hold(1.0)
        size = p.style_font_size.value()
        result['info']['font_size_before'] = size
        for value in range(int(size) + 4, 89, 4):
            p.style_font_size.setValue(value)
            yield 0.12
            rec.frame()
        p._commit_style_now() if hasattr(p, '_commit_style_now') else None
        yield from rec.hold(1.2)
        effect = p.effect_preset.findText('柔和弹入') if with_effect else -1
        result['info']['effect_index'] = effect
        if effect >= 0:
            p.effect_preset.setCurrentIndex(effect)
        yield from rec.hold(0.8)
        p._seek((cue.start_ms - 250) / 1000.0)
        yield 0.3
        p._toggle_playback()
        yield from rec.hold(2.6, fps=10)
        pause()
        yield from rec.hold(1.0)
        rec.finish()
        result['info']['style_after'] = dict(size=p.style_font_size.value(), effect=p.effect_preset.currentText())
        shot('style-final')
        write()

    def scene_playback():
        yield from open_studio()
        pause()
        tall()
        p = page()
        p.context_drawer.setCurrentIndex(1)
        start = 12.6
        p._seek(start)
        show_window(10000, 16000)
        yield 1.2
        rec = Recorder('play')
        yield from rec.hold(0.6, fps=10)
        p._toggle_playback()
        yield from rec.hold(10.0, fps=10)
        pause()
        yield from rec.hold(0.5, fps=10)
        rec.finish()

    def scene_hero():
        yield from open_studio()
        pause()
        tall()
        p = page()
        cue = cue_by_text('好技能')
        p._seek((cue.start_ms + 1300) / 1000.0)
        show_window(13500, 17000)
        p.context_drawer.setCurrentIndex(1)
        yield 1.8
        other = cue_by_text('漂亮')
        p.select_cue(other.id)
        yield 0.6
        p.select_cue(cue.id)
        p._seek((cue.start_ms + 1300) / 1000.0)
        for index, delay in enumerate((0.3, 0.3, 0.3, 0.4)):
            yield delay
            shot(f'studio-hero-{index}')
        yield 2.0
        shot('studio-hero')

    def scene_export():
        yield from open_studio()
        pause()
        p = page()
        p._open_render_dialog()
        yield 2.5
        shot('export-setup')
        export = p.export_workspace
        from PySide6.QtWidgets import QPushButton
        start = next((b for b in export.findChildren(QPushButton) if b.isVisible() and b.text().strip() == '开始导出'), None)
        result['info']['export_start'] = bool(start)
        if start is None:
            return
        QTest.mouseClick(start, Qt.MouseButton.LeftButton)
        began = time.monotonic()
        index = 0
        while time.monotonic() - began < 420:
            yield 3.0
            index += 1
            if index % 4 == 1:
                shot(f'export-progress-{index:03d}')
            if getattr(export, '_completion_notified', False) or 'success' in type(export.pages.currentWidget()).__name__.lower():
                break
        yield 2.0
        result['info']['export_seconds'] = round(time.monotonic() - began, 1)
        shot('export-done')
        write()

    def scene_home():
        window._return_to_settings()
        yield 1.5
        window.settings_scroll.verticalScrollBar().setValue(0)
        yield 0.5
        shot('home-after')

    def scene_themes():
        for key in ('grape', 'warm', 'plum', 'lavender', 'slate'):
            apply_application_theme(app, key)
            yield 1.5
            window._return_to_settings()
            yield 1.2
            shot(f'theme-{key}-home')
            window.open_studio_project(spec['project'])
            deadline = time.monotonic() + 60
            yield 1.0
            while not studio_ready() and time.monotonic() < deadline:
                yield 0.4
            pause()
            yield 2.0
            shot(f'theme-{key}-studio')
        apply_application_theme(app, spec['theme'])
        yield 1.0

    def geometry():
        tl = page().timeline
        lanes = tl._track_layout()[0]
        video = tl._video_track_rects()
        return dict(lanes={k: [round(r.top()), round(r.bottom())] for k, r in lanes.items()},
                    video={k: [round(r.top()), round(r.bottom())] for k, r in video.items()},
                    height=tl.height(), duration=tl.visible_duration_ms,
                    splitter=page().workspace_splitter.sizes())

    def scene_lanecheck():
        yield from open_studio()
        pause()
        p = page()
        info = result['info'].setdefault('lanecheck', {})
        info['default'] = geometry()
        shot('lane-default')
        from PySide6.QtWidgets import QAbstractButton
        zoom = next(w for w in p.findChildren(QAbstractButton) if w.property('commandSource') == '放大时间轴 (Ctrl+滚轮)')
        for _ in range(4):
            QTest.mouseClick(zoom, Qt.MouseButton.LeftButton)
            yield 0.4
        yield 1.0
        info['zoomed'] = geometry()
        shot('lane-zoomed')
        sizes = p.workspace_splitter.sizes()
        total = sum(sizes)
        p.workspace_splitter.setSizes([round(total * 0.5), total - round(total * 0.5)])
        yield 1.2
        info['tall'] = geometry()
        shot('lane-tall')
        write()

    handlers = dict(lanecheck=scene_lanecheck, explore=scene_explore, pages=scene_pages, speakers=scene_speakers, razor=scene_razor,
                    review=scene_review, fixups=scene_fixups, style=scene_style, style2=scene_style2, **{'style-size': lambda: scene_style2(False)}, playback=scene_playback,
                    hero=scene_hero, export=scene_export, home=scene_home, themes=scene_themes)

    def steps():
        yield 2.0
        window.showNormal()
        window.resize(width, height)
        window.move(0, 0)
        yield 1.0
        screen = window.screen()
        result['info']['window'] = dict(size=[window.width(), window.height()], requested=[width, height],
                                        screen=[screen.geometry().width(), screen.geometry().height()],
                                        available=[screen.availableGeometry().width(), screen.availableGeometry().height()],
                                        dpr=window.devicePixelRatioF())
        mark(json.dumps(result['info']['window']))
        write()
        for name in spec['scenes']:
            mark(f'scene {name}')
            try:
                yield from handlers[name]()
            except Exception:
                result['errors'].append(dict(scene=name, error=traceback.format_exc()[-2000:]))
                close_modals()
            write()
        yield 0.3

    class Runner(QObject):
        def __init__(self):
            super().__init__(window)
            self.gen = steps()
            self.until = 0.0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(30)

        def tick(self):
            if time.monotonic() < self.until:
                return
            try:
                delay = next(self.gen)
                self.until = time.monotonic() + float(delay or 0)
            except StopIteration:
                self.timer.stop()
                result['finished'] = True
                write()
                os._exit(0)
            except Exception:
                result['errors'].append(dict(scene='runner', error=traceback.format_exc()[-1500:]))
                write()
                self.timer.stop()
                os._exit(3)

    runner = Runner()  # noqa: F841
    app.exec()
    write()
    os._exit(0)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--inner':
        return inner(Path(sys.argv[2]))
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True)
    parser.add_argument('--source', default='run-01')
    parser.add_argument('--size', default='1440x900')
    parser.add_argument('--scale', default='2')
    parser.add_argument('--theme', default='grape')
    parser.add_argument('--lang', default='zh')
    parser.add_argument('--scenes', type=lambda t: [s for s in t.split(',') if s], default=['explore'])
    parser.add_argument('--final-preset', default='游戏字幕')
    parser.add_argument('--timeout', type=int, default=1500)
    return outer(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
