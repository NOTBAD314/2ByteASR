"""Real-window visual tour of the desktop UI (development tool, no product logic).

Runs the normal ``MainWindow`` on a private Windows desktop with an isolated
profile under ``tmp/`` and offline guards, replays retained real task data
(progress events / completion report / Studio project) and saves native
window captures.  No ASR, provider request, user profile or project is
touched: fixtures are copied into the fresh output directory first.

    .venv-main\\Scripts\\python.exe scripts\\visual_tour.py --output tmp\\<fresh>
        --fixtures tmp\\visual-refresh-20261007\\fixtures [--scenes home,progress,...]
        [--size 1920x1080 --size 1366x768] [--lang zh] [--theme grape] [--scale 1]
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

ROOT = Path(__file__).resolve().parents[1]
SCENES = ('home', 'home-media', 'home-collapsed', 'home-gallery', 'home-terms', 'home-ai', 'progress-moss', 'progress-evidence',
          'progress-cancel', 'progress', 'progress-log', 'completion', 'completion-open', 'proofread', 'export', 'export-success',
          'history', 'workshop', 'workshop-detail', 'terms', 'library', 'studio', 'studio-narrow',
          'studio-style', 'studio-table', 'studio-range', 'studio-tall',
          'settings', 'storage', 'design')

# Console lines visible in the retained real GE run screenshot (stdout is not
# persisted by the pipeline); used only to populate the log surface.
CONSOLE_LINES = (
    '[阶段 1/11] 统一 16k 音频采样时钟 (CPU)',
    '[阶段完成] 统一 16k 音频采样时钟: 0秒',
    '[阶段 2/11] MOSS 全局说话人与粗时间转写 (GPU)',
    '   [缓存写入] moss',
    '[阶段完成] MOSS 全局说话人与粗时间转写: 56秒',
    '   [稳定优先] FireRed 与 Qwen3 同为本地 GPU 重模型，串行加载以避免 meta/并发初始化失败。',
    '[阶段 4/11] FireRedASR2-AED 独立文字证据 (GPU)',
    '[阶段完成] FireRedASR2-AED 独立文字证据: 38秒',
    '[阶段 5/11] 筛选 MOSS 主播并建立主稿 (CPU)',
    '   [说话人候选] raw_label=S01 label_source=MOSS timeline_span_ratio=0.9988 candidate_min_span_ratio=0.60 identity_confirmed=false',
    '   [说话人候选] raw_label=S02 label_source=MOSS timeline_span_ratio=0.7766 candidate_min_span_ratio=0.60 identity_confirmed=false',
    '   [主播筛选] 自动筛选，暂用 S01(跨2分钟窗/100%)；未确认的标签保存在工程候选中，不自动认定为节目角色声。',
    '   [完成] MOSS 对白主稿: 50 段; 覆盖模式 host_priority; 未再补入 8 个段外 FireRed 字词。',
    '   [缓存写入] firered_primary',
    '[阶段完成] 筛选 MOSS 主播并建立主稿: 0秒',
    '[阶段 6/11] Qwen3-ASR VAD短块复核 (GPU)',
    '[阶段完成] Qwen3-ASR VAD短块复核: 31秒',
    '   [完成] Qwen3-ASR 复核: 50/50 段获得独立文字证据。',
    '   [三路仲裁] 本地双模型共识核对 50 段 (每 40 段报告一次进度) …',
    '[阶段 7/11] FireRedASR2-LLM 争议片段复核 (可选远程/高显存 GPU)',
    '[阶段完成] FireRedASR2-LLM 争议片段复核: 0秒',
    '[阶段 8/11] 云端模型受限校对 (grok_oauth/grok-4.7 · grok_cli+本地安全裁决)',
    '[校对] grok_oauth/grok-4.7 对照 FireRed-AED/MOSS/Qwen3/争议 LLM 与上下文，再由本地规则裁决...',
    '   已读取 9 个弱参考专名。',
    '   [项目背景] domain=瓦罗兰特; source=user_selected; type=game_commentary; language=zh-CN; glossaries=瓦罗兰特@53',
    '   校对批次 1/1',
    '[警告] 云端校对失败，当前批次保留 ASR 原文: AI CLI 达到单次总预算; 已接收的过程与来源保留，请按检查点继续。',
    '      [逐批缓存跳过] polished 当前批次使用回退。',
    '   [缓存跳过] polished 使用了回退结果，下次仍会重试。',
    '[阶段完成] 云端模型受限校对: 2分01秒',
    '[阶段 9/11] 云端模型全文智能断句 (grok_oauth/grok-4.7 · grok_cli+说话人插话保护)',
    '   云端模型阅读全稿并选择同一说话人内部的语义断点，不修改任何字幕文字...',
    '   断句批次 1/1, 说话人 mixed',
    '   [断句] grok_oauth/grok-4.7 · grok_cli (数字 boundaries, 原文不可变)',
)


def _parse_size(text):
    width, height = text.lower().split('x')
    return int(width), int(height)


def outer(args):
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp') or output.exists():
        raise SystemExit('Choose a fresh output directory under repository tmp')
    output.mkdir(parents=True)
    fixtures = output / 'fixtures'
    shutil.copytree(args.fixtures.resolve(), fixtures)
    spec = dict(scenes=args.scenes, sizes=args.size or ['1920x1080'], lang=args.lang, theme=args.theme,
                scale=args.scale, fixtures=str(fixtures), started=time.strftime('%Y-%m-%dT%H:%M:%S'))
    (output / 'spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), 'utf8')
    # Non-secret UI/settings/glossary copies so pages show the operator's real
    # configuration shape. Credentials (secrets.dat) are never copied.
    user_root = Path(os.environ.get('LOCALAPPDATA', '')) / '2ByteASR'
    seeded = output / 'profile' / 'local' / '2ByteASR'
    seeded.mkdir(parents=True, exist_ok=True)
    for name in ('2byteasr_settings.json', 'learned_game_terms.json', 'content_profiles.json',
                 'profiles.json', 'glossary-update-history.json'):
        if (user_root / name).is_file() and not args.no_seed:
            shutil.copy2(user_root / name, seeded / name)
    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_PROJECT', 'TWOBYTEASR_ACCEPTANCE_SCENARIO', 'TWOBYTEASR_ACCEPTANCE_DIR'):
        env.pop(key, None)
    env.update(TWOBYTEASR_TEST_ROOT=str(output / 'profile'), TWOBYTEASR_VISUAL_TOUR=str(output),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               PYTHONUTF8='1', QT_QPA_PLATFORM='windows', TWOBYTEASR_STARTUP_TRACE=str(output / 'startup.jsonl'))
    for key in ('QT_SCALE_FACTOR', 'QT_ENABLE_HIGHDPI_SCALING', 'QT_FONT_DPI', 'QT_SCALE_FACTOR_ROUNDING_POLICY'):
        env.pop(key, None)
    if args.scale != 'natural':
        env.update(QT_SCALE_FACTOR=args.scale, QT_ENABLE_HIGHDPI_SCALING='0', QT_FONT_DPI='96',
                   QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough')
    sys.path.insert(0, str(ROOT / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--inner', str(output)]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=args.timeout)
    result_path = output / 'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.is_file() else dict(error='no receipt')
    result['process_exit'] = code
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(exit=code, shots=len(result.get('shots', [])), errors=result.get('errors', [])),
                     ensure_ascii=False, indent=1))
    return 0 if code == 0 else 1


def inner(output: Path):
    sys.path.insert(0, str(ROOT))
    spec = json.loads((output / 'spec.json').read_text('utf8'))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.acceptance.blank_project_audit import install_offline_guards
    install_offline_guards()
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    import moss_firered_pipeline
    import subtitle_core
    from twobyteasr.app import ui
    from twobyteasr.design.theme_manager import apply_application_theme
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
    window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, {'id': 'visual-tour', 'checks': 0})
    window.show()
    fixtures = Path(spec['fixtures'])
    result = dict(shots=[], errors=[], dpr=None, spec=spec, pid=os.getpid())

    def write():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')

    def min_heights(widget, depth=0, limit=3):
        """Children whose minimum height drives the page minimum (diagnostic)."""
        rows = []
        for child in widget.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            if not child.isVisible():
                continue
            hint = child.minimumSizeHint()
            rows.append(dict(cls=type(child).__name__, name=child.objectName(), min_h=hint.height(),
                             min_w=hint.width(), h=child.height()))
            if depth < limit and hint.height() > 300:
                rows[-1]['children'] = min_heights(child, depth + 1, limit)
        return sorted(rows, key=lambda row: -row['min_h'])[:4]

    def shot(name, widget=None):
        from twobyteasr.acceptance.blank_project_audit import _capture
        widget = widget or window
        QApplication.processEvents()
        if widget is window:
            page = window.pages.currentWidget()
            result.setdefault('geometry', []).append(dict(
                name=name, window=[window.width(), window.height()],
                window_min_hint=[window.minimumSizeHint().width(), window.minimumSizeHint().height()],
                window_min=[window.minimumWidth(), window.minimumHeight()],
                hfw={label: (lay.hasHeightForWidth(), lay.totalHeightForWidth(owner.width()) if lay.hasHeightForWidth() else None, owner.height())
                     for label, owner in (('window', window), ('page', page), ('left', getattr(window, 'progress_left_column', page)),
                                          ('stage', getattr(window, 'current_stage_card', page)))
                     for lay in [owner.layout()] if lay is not None},
                page=type(page).__name__, page_min_hint=[page.minimumSizeHint().width(), page.minimumSizeHint().height()],
                drivers=min_heights(page)))
            export = getattr(getattr(window, 'studio_page', None), 'export_workspace', None)
            if export is not None and export.isVisible():
                def box(widget):
                    top_left = widget.mapTo(window, widget.rect().topLeft())
                    return [top_left.x(), top_left.y(), widget.width(), widget.height(), widget.isVisible()]
                result['geometry'][-1]['export'] = {name: box(widget) for name, widget in (
                    ('workspace', export), ('pages', export.pages), ('setup', export.setup_page),
                    ('splitter', export.splitter), ('footer', export.queue_button.parentWidget()))}
                export.grab().save(str(output / 'shots' / f'{name}-qtgrab.png'))
                import ctypes
                from ctypes import wintypes as W
                native = []
                for item in [export, *export.findChildren(QWidget)]:
                    if item.testAttribute(Qt.WidgetAttribute.WA_NativeWindow) or item.internalWinId():
                        rect = W.RECT(); ctypes.windll.user32.GetWindowRect(W.HWND(int(item.winId())), ctypes.byref(rect))
                        top_left = item.mapTo(window, item.rect().topLeft())
                        native.append((type(item).__name__, item.objectName(), [top_left.x(), top_left.y(), item.width(), item.height()],
                                       [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top], item.isVisible()))
                win_rect = W.RECT(); ctypes.windll.user32.GetWindowRect(W.HWND(int(window.winId())), ctypes.byref(win_rect))
                result['geometry'][-1]['native'] = dict(window=[win_rect.left, win_rect.top], widgets=native[:30])
                result['geometry'][-1]['export']['siblings'] = [
                    (type(child).__name__, child.objectName(), box(child)) for child in
                    export.parentWidget().findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
                    if child.isVisible()]
            if page is getattr(window, 'settings_scroll', None):
                content = page.widget()
                widest = sorted(
                    ((child.minimumSizeHint().width(), type(child).__name__, child.objectName(), child.width())
                     for child in content.findChildren(QWidget) if child.isVisible()),
                    reverse=True)[:12]
                result['geometry'][-1].update(viewport_w=page.viewport().width(), content_w=content.width(),
                                              content_min_w=content.minimumSizeHint().width(), widest=widest)
                plan = getattr(window, 'recognition_plan_widget', None) or next(
                    (w for w in content.findChildren(QWidget) if type(w).__name__ == 'RecognitionPlanWidget'), None)
                if plan is not None:
                    result['geometry'][-1]['cards'] = [dict(
                        role=role, profile=card._responsive_profile, w=card.width(), h=card.height(),
                        min_w=card.minimumSizeHint().width(), wrapped=getattr(card, '_status_wrapped', None),
                        status_min_w=card._status_layout.minimumSize().width(),
                        model_min_w=card.model_label.minimumSizeHint().width(),
                        role_min_w=card.role_label.minimumSizeHint().width(),
                        rec_min=card.recovery.minimumWidth(), rec_hint=card.recovery.sizeHint().width(),
                        rec_vis=not card.recovery.isHidden(), kind_min=card.kind_badge.minimumSizeHint().width(),
                        status_hint=card.status_badge.minimumSizeHint().width(), rec_text=card.recovery.text())
                        for role, card in plan.cards.items()]
        target = output / 'shots' / f"{name}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            _capture(widget, target)
        except Exception:
            widget.grab().save(str(target), 'PNG')
        result['shots'].append(dict(name=name, path=str(target), logical=[widget.width(), widget.height()],
                                    dpr=widget.devicePixelRatioF()))
        write()

    def close_modals():
        for widget in QApplication.topLevelWidgets():
            if widget is not window and widget.isVisible() and widget.isWindow():
                if type(widget).__name__ in {'QMenu'}:
                    widget.close()
                elif hasattr(widget, 'reject'):
                    widget.reject()
                elif type(widget).__name__ == 'CompletionDialog':
                    widget.close()
        host = getattr(window, '_modal_host', None)
        if host is not None and host.isVisible():
            host.hide_content()

    report_path = fixtures / 'ge-report.json'
    project_path = fixtures / 'ge-project.2byteproj'

    def replay_progress(stop_after_index=9):
        from twobyteasr.recognition.service import _event_from_payload
        rows = [json.loads(line) for line in (fixtures / 'ge-run.jsonl').read_text('utf8').splitlines() if line.strip()]
        window._switch_page(window.pages.widget(1)) if hasattr(window, '_switch_page') else None
        window.pages.setCurrentIndex(1)
        window._active_job_id = ''
        window.started_at = time.perf_counter() - 390
        state = dict(media_path='', media_index=1, media_total=1, job_id='')
        console = list(CONSOLE_LINES)
        for row in rows:
            kind = row.get('event')
            payload = dict(row)
            payload.pop('event', None)
            payload.pop('job_id', None)
            try:
                window._handle_event(_event_from_payload(kind, payload, state))
            except Exception:
                result['errors'].append(dict(scene='progress-replay', event=kind, error=traceback.format_exc()[-800:]))
            if kind == 'stage_started' and int(row.get('index') or 0) == stop_after_index:
                break
        for line in console:
            window._append_console_line(line)
        window._update_progress_clock()

    def replay_until(stop):
        """Replay the retained real run from a clean progress page until
        ``stop(row)`` is true (that row included). Stage start times are
        shifted to the recorded durations so live facts read realistically;
        no model runs."""
        from twobyteasr.recognition.service import _event_from_payload
        rows = [json.loads(line) for line in (fixtures / 'ge-run.jsonl').read_text('utf8').splitlines() if line.strip()]
        window.pages.setCurrentIndex(1)
        window._active_job_id = ''
        window.token = None
        window._recognition_terminal = ''
        for name in ('_active_stages',):
            getattr(window, name).clear()
        window._completed_stages.clear()
        window._failed_stages.clear()
        window._skipped_stages = set()
        window._phase_degraded = {}
        window._feed_stage_rows = {}
        window._recognition_live_work = {}
        window._reset_progress_presentation()
        window.event_log.clear()
        window.console_log.clear()
        window._console_lines, window._console_levels, window._console_fragments = [], [], []
        first = None
        media = json.loads(report_path.read_text('utf8'))['media']['path']
        state = dict(media_path=media, media_index=1, media_total=1, job_id='')
        stopped_at = None
        for row in rows:
            kind = row.get('event')
            first = first if first is not None else float(row.get('monotonic_seconds') or 0)
            payload = dict(row)
            payload.pop('event', None)
            payload.pop('job_id', None)
            try:
                window._handle_event(_event_from_payload(kind, payload, state))
            except Exception:
                result['errors'].append(dict(scene='progress-replay', event=kind, error=traceback.format_exc()[-800:]))
            if stop(row):
                stopped_at = row
                break
        # Shift the clocks so "已运行" reads the recorded durations.
        now = time.perf_counter()
        last = float((stopped_at or rows[-1]).get('monotonic_seconds') or 0)
        window.started_at = now - max(0.0, last - (first or last))
        for stage, item in window._active_stages.items():
            started = [float(r.get('monotonic_seconds') or 0) for r in rows
                       if r.get('event') == 'stage_started' and int(r.get('index') or 0) == stage]
            if started:
                item['started'] = now - max(0.0, last - started[0])
                for (_media, row_stage, _label), card in window._feed_stage_rows.items():
                    if row_stage == stage and card is not None:
                        card._started_at = item['started']
        for line in CONSOLE_LINES[:4]:
            window._append_console_line(line)
        window._last_clock_second = -1
        window._update_progress_clock()
        window._refresh_progress_cards()

    def complete():
        from twobyteasr.recognition.service import MediaResult, QueueResult
        report = json.loads(report_path.read_text('utf8'))
        actual = MediaResult(media_path=report['media']['path'], status=report['status'],
                             project_path=str(project_path), report_json_path=str(report_path),
                             elapsed_seconds=float(report['result'].get('elapsed_seconds', 0)))
        for line in CONSOLE_LINES:
            window._append_console_line(line)
        window._handle_result(QueueResult((actual,), actual.elapsed_seconds))

    def sized(scene_gen):
        for size in spec['sizes']:
            width, height = _parse_size(size)
            window.showNormal()
            window.resize(width, height)
            window.move(0, 0)
            yield 0.35
            yield from scene_gen(f'{size}')

    def scene_home(tag):
        window._return_to_settings() if hasattr(window, '_return_to_settings') else window.pages.setCurrentIndex(0)
        yield 0.5
        window.settings_scroll.verticalScrollBar().setValue(0)
        yield 0.2
        shot(f'home_{tag}')

    def scene_home_media(tag):
        media = json.loads(report_path.read_text('utf8'))['media']['path']
        if Path(media).is_file() and not window.media_paths:
            window.import_media([media], replace=True)
        window._return_to_settings()
        yield 1.5
        window.settings_scroll.verticalScrollBar().setValue(0)
        yield 0.3
        shot(f'home-media_{tag}')
        window.settings_scroll.verticalScrollBar().setValue(window.settings_scroll.verticalScrollBar().maximum())
        yield 0.3
        shot(f'home-media-bottom_{tag}')
        window.settings_scroll.verticalScrollBar().setValue(0)

    def scene_home_collapsed(tag):
        # A configured profile keeps the AI panel folded; fold it the way a
        # user click on the tile does, then capture the home page.
        window._return_to_settings()
        tile = window.setting_tiles.get('ai')
        if tile is not None and tile.isChecked():
            tile.setChecked(False)
        window.ai_panel.set_expanded(False, animate=False)
        window.ai_panel.setVisible(False)
        yield 0.8
        window.settings_scroll.verticalScrollBar().setValue(0)
        yield 0.3
        shot(f'home-collapsed_{tag}')

    def scene_home_gallery(tag):
        # Isolated copies of the fixture project as recent projects, so the
        # home gallery is captured with a realistic number of entries.
        from twobyteasr.projects.studio_project import studio_settings_path
        settings_path = studio_settings_path()
        payload = json.loads(settings_path.read_text('utf-8-sig')) if settings_path.is_file() else {}
        records = []
        for index in range(8):
            folder = output / 'gallery' / f'tour-project-{index + 1}'
            if not folder.exists():
                (folder / 'preview').mkdir(parents=True)
                shutil.copy2(project_path, folder / project_path.name)
                shutil.copy2(fixtures / 'preview' / 'project-cover.jpg', folder / 'preview' / 'project-cover.jpg')
            records.append({'path': str(folder / project_path.name), 'name': f'tour-project-{index + 1}',
                            'cue_count': 9, 'last_opened': f'2026-10-08T0{8 - index}:00:00+00:00'})
        payload['recent_projects'] = records
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(payload, ensure_ascii=False), 'utf-8')
        window._return_to_settings()
        tile = window.setting_tiles.get('ai')
        if tile is not None and tile.isChecked():
            tile.setChecked(False)
        window.ai_panel.set_expanded(False, animate=False)
        window.ai_panel.setVisible(False)
        window._refresh_studio_entry_card()
        yield 1.2
        window.settings_scroll.verticalScrollBar().setValue(0)
        yield 0.3
        shot(f'home-gallery_{tag}')

    def scene_home_terms(tag):
        # The content card's term panel in its ON state: pick the first
        # recent content chip and switch on glossary correction (isolated).
        window._return_to_settings()
        names = getattr(window, '_content_quick_names', [])
        if names:
            window._pick_recent_content(names[0])
        window.terms.setChecked(True)
        yield 1.0
        window.settings_scroll.verticalScrollBar().setValue(0)
        yield 0.3
        shot(f'home-terms_{tag}')

    def scene_home_ai(tag):
        # AI settings open in a dialog (the 设置 AI button), then Cancel.
        window._return_to_settings()
        QTest.mouseClick(window.ai_settings_button, Qt.MouseButton.LeftButton)
        yield 1.4
        shot(f'home-ai-open_{tag}')
        dialog = getattr(window, '_ai_settings_dialog', None)
        if dialog is not None:
            shot(f'home-ai-dialog_{tag}', dialog)
            editor = window.group_editor if window.group_editor.isVisible() else window.polish_editor
            editor.advanced_toggle.setChecked(True)
            yield 0.6
            shot(f'home-ai-dialog-advanced_{tag}', dialog)
            dialog.reject()
        yield 0.8
        shot(f'home-ai-closed_{tag}')

    def moss_generating(row):
        return (row.get('event') == 'asr_worker_progress' and row.get('backend') == 'moss'
                and row.get('phase') == 'generation' and int(row.get('generated_tokens') or 0) >= 400)

    def scene_progress_moss(tag):
        replay_until(moss_generating)
        yield 0.6
        shot(f'progress-moss_{tag}')
        # Same real payload, 80 s later with no new output: every clock
        # (task, step, record row) moves on together; the last output stays.
        live = window._stage_live.get(2)
        if live and live.get('at'):
            window.started_at -= 80
            for item in window._active_stages.values():
                if item.get('started'):
                    item['started'] -= 80
            for card in window._feed_stage_rows.values():
                if card is not None and getattr(card, '_started_at', 0):
                    card._started_at -= 80
            live['at'] -= 80
            window._last_clock_second = -1
            window._update_progress_clock()
            window._refresh_progress_cards()
            yield 0.4
            shot(f'progress-moss-quiet_{tag}')

    def scene_progress_evidence(tag):
        replay_until(lambda row: row.get('event') == 'asr_evidence_delta')
        yield 0.6
        shot(f'progress-evidence_{tag}')

    def scene_progress_cancel(tag):
        from twobyteasr.recognition.service import CancellationToken, PipelineEvent
        replay_until(moss_generating)
        window.token = CancellationToken()
        window._cancel_run()
        window._cancel_requested_at -= 4
        window._last_clock_second = -1
        window._update_progress_clock()
        yield 0.6
        shot(f'progress-cancel_{tag}')
        window._handle_event(PipelineEvent(kind='asr_worker_exited', timestamp='', payload=dict(backend='moss', model_id='moss')))
        window._handle_event(PipelineEvent(kind='media_cancelled', timestamp='', media_path='2026-10-07 GE vs EDG.mp4'))
        yield 0.4
        shot(f'progress-cancel-stopped_{tag}')
        window._recognition_terminal = 'cancelled'
        window._active_stages.clear()
        window._finish_progress_presentation()
        window._refresh_progress_cards()
        yield 0.4
        shot(f'progress-cancelled_{tag}')
        window.token = None
        window._recognition_terminal = ''
        window._cancel_requested_at = 0.0
        window._tour_progress_ready = False

    def scene_proofread(tag):
        # AI glossary workspace on the isolated fixture copy: add terms,
        # review the real local suggestions, play one cue, apply, return.
        if not getattr(window, '_tour_completion_ready', False):
            complete()
            window._tour_completion_ready = True
        close_modals()
        window.pages.setCurrentIndex(2)
        yield 0.6
        window._open_glossary_proofread()
        page = window.glossary_proofread_page
        for _ in range(40):
            if page._worker is None:
                break
            yield 0.25
        yield 0.4
        shot(f'proofread-open_{tag}')
        page.term_input.setPlainText('CHIOCHOO → CHICHOO\nAutumn')
        page.target_combo.setEditText('无畏契约选手')
        page.category_combo.setCurrentIndex(page.category_combo.findData('选手 ID'))
        page._add_terms()
        for _ in range(40):
            if page._worker is None:
                break
            yield 0.25
        yield 0.5
        shot(f'proofread-added_{tag}')
        # 瓦罗兰特 already spells CHIOCHOO / autumn its own way: the
        # conflicts are shown and decided here (M15), not skipped silently.
        result.setdefault('proofread', {})['conflicts'] = [
            dict(key=row['key'], options=[(o['target'], o['names']) for o in row['options']])
            for row in page._conflict_rows]
        page.conflicts.header.setChecked(True)
        yield 0.5
        shot(f'proofread-conflicts_{tag}')
        mine = next((page.library_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(page.library_list.count())
                     if page.library_list.item(i).text() == '无畏契约选手'), '')
        for row in list(page._conflict_rows):
            option = next((o for o in row['options'] if mine in o['library_ids']), None)
            if option is not None:
                page.conflicts._choose(row['key'], (mine, option['target']))
                for _ in range(40):
                    if page._worker is None:
                        break
                    yield 0.25
        page.conflicts.header.setChecked(False)
        yield 0.5
        shot(f'proofread-suggestions_{tag}')
        result.setdefault('proofread', {})['entries'] = [
            dict(kind=e['kind'], before=e['before'], after=e['after'], checked=e['checked'], info=e['info'],
                 speaker=e['speaker'][0], source=e['source'])
            for e in page._entries]
        result['proofread']['added'] = page.add_status.text()
        result['proofread']['hint'] = page.hint_label.text()
        if page._entries:
            page._play(0)
            yield 1.2
            shot(f'proofread-playing_{tag}')
            page._player.stop()
        page._apply()
        for _ in range(40):
            if page._worker is None:
                break
            yield 0.25
        yield 0.5
        shot(f'proofread-applied_{tag}')
        result['proofread']['status'] = page.status_label.text()
        page._back()
        yield 0.8
        shot(f'proofread-result_{tag}')
        result['proofread']['preview'] = [row[3] for row in window.result_preview.rows()]

    def scene_export_success(tag):
        # The real export workspace's result page, filled with a receipt in
        # the shape the renderer writes (layout check; nothing is encoded).
        from types import SimpleNamespace
        open_studio()
        deadline = time.monotonic() + 45
        while not studio_ready() and time.monotonic() < deadline:
            yield 0.4
        page = window.studio_page
        if getattr(page, 'export_workspace', None) is None or not page.export_workspace.isVisible():
            page._open_render_dialog()
            yield 1.2
        export = page.export_workspace
        folder = output / 'export-result'
        folder.mkdir(exist_ok=True)
        video = folder / (Path(json.loads(report_path.read_text('utf8'))['media']['path']).stem + ' 成片.mp4')
        video.write_bytes(b'tour')
        poster = folder / 'poster.jpg'
        shutil.copy2(fixtures / 'preview' / 'project-cover.jpg', poster)
        receipt = dict(output_path=str(video.resolve()), elapsed_seconds=72.9, duration_seconds=164.0,
                       size_bytes=214_400_000, average_bitrate_bps=10_400_000,
                       requested_video_bitrate_bps=10_000_000, video_bitrate=dict(average_bitrate_bps=10_219_000),
                       actual_rate_control='target', bitrate_target_met=True,
                       streams=[dict(codec_type='video', codec_name='h264', width=1920, height=1080, avg_frame_rate='60/1')])
        export._last_job = SimpleNamespace(completion_metadata=receipt, completion_preview_path=str(poster), settings=None)
        export._completion_notified = True
        export._show_success(str(video))
        yield 1.0
        shot(f'export-success_{tag}')

    def scene_progress(tag):
        if not getattr(window, '_tour_progress_ready', False):
            replay_until(lambda row: row.get('event') == 'stage_started' and int(row.get('index') or 0) == 9)
            window._tour_progress_ready = True
        window.pages.setCurrentIndex(1)
        yield 0.6
        shot(f'progress_{tag}')

    def scene_completion(tag):
        if not getattr(window, '_tour_completion_ready', False):
            complete()
            window._tour_completion_ready = True
            yield 1.2
            close_modals()
        window.pages.setCurrentIndex(2)
        yield 0.6
        shot(f'completion_{tag}')
        result['completion'] = dict(count=window.result_stat_values['count'].text(),
                                    caption=window.result_stat_captions['count'].text(),
                                    pill_action=window.result_title.qualifier_action(),
                                    preview_rows=len(window.result_preview.rows()))

    def scene_completion_retry(tag):
        # Retry is only offered for retryable outcomes with the original run
        # options; give the replay the options object the real run would hold.
        from twobyteasr.recognition.service import RunOptions
        window._last_run_options = RunOptions.from_legacy(subtitle_core)
        window._tour_completion_ready = False
        yield from scene_completion(tag)
        window._last_run_options = None

    def scene_completion_open(tag):
        if not getattr(window, '_tour_completion_ready', False):
            yield from scene_completion(tag)
        window.pages.setCurrentIndex(2)
        for panel in (window.result_files_panel, window.result_log_panel):
            panel.set_mode('summary')
        yield 0.5
        shot(f'completion-open_{tag}')
        window.result_log_panel.set_mode('full')  # 查看全部
        yield 0.6
        shot(f'completion-log_{tag}')
        for panel in (window.result_files_panel, window.result_log_panel):
            panel.set_mode('collapsed')

    def scene_history(tag):
        history = window.history_page
        history.report_root = fixtures / 'reports'
        history.extra_roots = []
        getattr(history, '_record_cache', {}).clear()
        window._open_recognition_history()
        yield 1.0
        shot(f'history_{tag}')

    def scene_workshop(tag):
        window._open_model_workshop()
        yield 1.2
        shot(f'workshop_{tag}')

    def scene_terms(tag):
        window._manage_terms()
        yield 1.5
        shot(f'terms_{tag}')

    def open_studio():
        # Reopen after the library scene returned to the project library.
        if getattr(window, '_tour_studio_open', False) and studio_ready():
            return
        window._tour_studio_open = True
        window.open_studio_project(str(project_path))

    def studio_ready():
        page = window.studio_page
        readiness = getattr(page, '_readiness', None)
        return bool(page.project is not None and readiness is not None and readiness.ready
                    and not readiness.active and page._project_view_state == 'open')

    def scene_studio_loading(tag):
        window._tour_studio_open = True
        window.open_studio_project(str(project_path))
        yield 0.35
        shot(f'studio-loading_{tag}')
        deadline = time.monotonic() + 45
        while not studio_ready() and time.monotonic() < deadline:
            yield 0.4

    def scene_studio(tag):
        open_studio()
        deadline = time.monotonic() + 45
        while not studio_ready() and time.monotonic() < deadline:
            yield 0.4
        yield 2.5
        shot(f'studio_{tag}')
        result.setdefault('studio', {})['default'] = studio_geometry(window.studio_page)

    def studio_select_first():
        page = window.studio_page
        cues = sorted(page.project.cues, key=lambda cue: (cue.start_ms, cue.end_ms))
        if cues:
            page.select_cue(cues[min(1, len(cues) - 1)].id)

    def studio_geometry(page):
        timeline = page.timeline
        lanes = timeline._track_layout()[0]
        video = timeline._video_track_rects()
        audio = timeline._audio_track_rects()
        return dict(canvas_bottom=timeline._canvas_bottom(), stack_bottom=timeline._stack_bottom(),
                    subtitle=[round(r.height()) for r in lanes.values()], subtitle_top=[round(r.top()) for r in lanes.values()],
                    video=[[round(r.top()), round(r.height())] for r in video.values()],
                    audio=[[round(r.top()), round(r.height())] for r in audio.values()],
                    range_bar_visible=page.project_range_bar.isVisible(),
                    cue_view=page.cue_table.property('cueView'), cue_row_height=page.cue_table.rowHeight(0) if page.cue_model.rowCount() else 0)

    def scene_studio_style(tag):
        # Style tab with a line selected: scope on top, preview of that line.
        open_studio()
        deadline = time.monotonic() + 45
        while not studio_ready() and time.monotonic() < deadline:
            yield 0.4
        page = window.studio_page
        studio_select_first()
        yield 0.6
        page.context_drawer.setCurrentIndex(1)
        yield 1.0
        shot(f'studio-style_{tag}')
        result.setdefault('studio', {})['style'] = dict(
            preview_text=page.style_preview.display_text(), scope=page.style_scope.currentData(),
            scope_height=page.style_scope.height(), preview_height=page.style_preview.height(),
            geometry=studio_geometry(page))
        page.style_preview.sample_toggle.setChecked(True)
        yield 0.4
        shot(f'studio-style-sample_{tag}', page.style_preview)
        page.style_preview.sample_toggle.setChecked(False)
        page._appearance_rows['outline'].set_expanded(True)
        yield 0.5
        shot(f'studio-style-outline_{tag}')
        page._appearance_rows['outline'].set_expanded(False)

    def scene_studio_tall(tag):
        # A taller timeline panel (dragged splitter): lanes stay under the
        # ruler, spare height grows the waveform and subtitle lanes, the
        # rest stays below the last lane (M16).
        open_studio()
        deadline = time.monotonic() + 45
        while not studio_ready() and time.monotonic() < deadline:
            yield 0.4
        page = window.studio_page
        sizes = page.workspace_splitter.sizes()
        total = sum(sizes)
        page.workspace_splitter.setSizes([round(total * 0.52), total - round(total * 0.52)])
        yield 1.2
        shot(f'studio-tall_{tag}')
        result.setdefault('studio', {})['tall'] = studio_geometry(page)
        page.workspace_splitter.setSizes(sizes)
        yield 0.6

    def scene_studio_table(tag):
        open_studio()
        deadline = time.monotonic() + 45
        while not studio_ready() and time.monotonic() < deadline:
            yield 0.4
        page = window.studio_page
        page.cue_view_button.setChecked(True)
        yield 0.8
        shot(f'studio-table_{tag}')
        result.setdefault('studio', {})['table'] = studio_geometry(page)
        page.cue_view_button.setChecked(False)
        yield 0.5

    def scene_studio_range(tag):
        # I / O on the ruler, then the timeline context menu naming the range.
        open_studio()
        deadline = time.monotonic() + 45
        while not studio_ready() and time.monotonic() < deadline:
            yield 0.4
        page = window.studio_page
        page._seek(2.0)
        yield 0.5
        page._mark_in()
        page._seek(9.0)
        yield 0.5
        page._mark_out()
        yield 0.5
        shot(f'studio-range_{tag}')
        captured = {}

        def grab_menu():
            menu = QApplication.activePopupWidget()
            if menu is not None:
                path = output / 'shots' / f'studio-range-menu_{tag}.png'
                menu.grab().save(str(path))
                captured['menu'] = [action.text() for action in menu.actions()]
                menu.close()

        timeline = page.timeline
        point = timeline.mapToGlobal(timeline.rect().center())
        # The menu runs its own event loop: open it from a timer (not inside
        # this generator) and capture it a moment later.
        QTimer.singleShot(800, grab_menu)
        QTimer.singleShot(0, lambda: page._show_timeline_menu('', point))
        yield 1.6
        # The same key at the same place clears that point.
        page._mark_out()
        yield 0.3
        result.setdefault('studio', {})['range'] = dict(menu=captured.get('menu'), status=page.save_state.text(),
                                                        geometry=studio_geometry(page))
        page._clear_range()
        yield 0.3

    def scene_library(tag):
        open_studio()
        deadline = time.monotonic() + 45
        while not studio_ready() and time.monotonic() < deadline:
            yield 0.4
        page = window.studio_page
        page._request_return_library()
        yield 1.2
        shot(f'library_{tag}')

    def scene_settings(tag):
        QTimer.singleShot(0, window._open_application_settings)
        yield 1.5
        modal = QApplication.activeModalWidget() or next((w for w in QApplication.topLevelWidgets()
                                                          if w is not window and w.isVisible() and w.isWindow()), None)
        shot(f'settings_{tag}', window if modal is None else window)
        if modal is not None and modal is not window:
            shot(f'settings-dialog_{tag}', modal)
        close_modals()
        yield 0.4

    def scene_export(tag):
        if not getattr(window, '_tour_completion_ready', False):
            yield from scene_completion(tag)
        window.pages.setCurrentIndex(2)
        yield 0.3
        QTimer.singleShot(0, window._export_completion_result)
        yield 1.5
        modal = QApplication.activeModalWidget()
        shot(f'export_{tag}')
        if modal is not None:
            shot(f'export-dialog_{tag}', modal)
        close_modals()
        yield 0.4

    def top_dialog():
        candidates = [w for w in QApplication.topLevelWidgets()
                      if w is not window and w.isVisible() and w.isWindow() and w.width() > 120
                      and type(w).__name__ not in {'QMenu', 'QToolTip'}]
        return candidates[-1] if candidates else None

    def dialog_scene(name, opener, settle=1.6):
        def scene(tag):
            if name.startswith('studio') or name in {'render', 'speakers', 'find', 'shortcuts'}:
                open_studio()
                deadline = time.monotonic() + 45
                while not studio_ready() and time.monotonic() < deadline:
                    yield 0.4
                yield 1.0
            QTimer.singleShot(0, opener)
            yield settle
            shot(f'{name}_{tag}')
            dialog = top_dialog()
            if dialog is not None:
                shot(f'{name}-dialog_{tag}', dialog)
            close_modals()
            yield 0.5
        return scene

    def open_ai_tab():
        window.studio_page.context_drawer.setCurrentIndex(0)

    def open_concepts():
        # Retained real AI design concepts (tests/fixtures, earlier generation);
        # chrome check only: no generation, previews only if the fixture has them.
        from twobyteasr.caption_design.theme_concept_dialog import ThemeConceptDialog
        concepts = json.loads((ROOT / 'tests/fixtures/death_stranding_concepts.json').read_text('utf8'))
        concepts = concepts.get('concepts', concepts) if isinstance(concepts, dict) else concepts
        window._tour_concepts = ThemeConceptDialog(concepts, {}, window.studio_page)
        window._tour_concepts.show()

    def open_technical():
        workshop = window.workshop_page
        window._open_model_workshop()
        QTimer.singleShot(400, workshop._show_technical_details)

    handlers = {'studio-loading': scene_studio_loading, 'home': scene_home, 'home-media': scene_home_media, 'home-collapsed': scene_home_collapsed, 'home-gallery': scene_home_gallery, 'home-terms': scene_home_terms, 'home-ai': scene_home_ai, 'progress': scene_progress,
                'progress-moss': scene_progress_moss, 'progress-evidence': scene_progress_evidence, 'progress-cancel': scene_progress_cancel,
                'export-success': scene_export_success, 'proofread': scene_proofread,
                'completion': scene_completion, 'completion-open': scene_completion_open, 'completion-retry': scene_completion_retry,
                'history': scene_history, 'workshop': scene_workshop, 'terms': scene_terms,
                'studio': scene_studio, 'library': scene_library, 'settings': scene_settings,
                'studio-style': scene_studio_style, 'studio-table': scene_studio_table, 'studio-range': scene_studio_range,
                'studio-tall': scene_studio_tall,
                'export': scene_export,
                'studio-ai': dialog_scene('studio-ai', open_ai_tab),
                'render': dialog_scene('render', lambda: window.studio_page._open_render_dialog(), 2.5),
                'render-late': dialog_scene('render-late', lambda: window.studio_page._open_render_dialog(), 7.0),
                'speakers': dialog_scene('speakers', lambda: window.studio_page._open_speaker_manager()),
                'find': dialog_scene('find', lambda: window.studio_page._open_find_replace()),
                'shortcuts': dialog_scene('shortcuts', lambda: window.studio_page._show_shortcut_settings()),
                'storage': dialog_scene('storage', lambda: window._open_application_settings(initial_section='存储与缓存'), 2.5),
                'appearance': dialog_scene('appearance', lambda: window._open_application_settings(initial_section='外观')),
                'technical': dialog_scene('technical', open_technical, 2.4),
                'studio-concepts': dialog_scene('studio-concepts', open_concepts, 2.0)}

    def steps():
        yield 1.5
        result['dpr'] = window.devicePixelRatioF()
        for name in spec['scenes']:
            handler = handlers.get(name)
            if handler is None:
                result['errors'].append(dict(scene=name, error='unknown scene'))
                continue
            try:
                yield from sized(handler)
            except Exception:
                result['errors'].append(dict(scene=name, error=traceback.format_exc()[-1500:]))
                close_modals()
            write()
        yield 0.2

    class Runner(QObject):
        def __init__(self):
            super().__init__(window)
            self.gen = steps()
            self.until = 0.0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(50)

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
                QTimer.singleShot(200, app.quit)

    runner = Runner()  # noqa: F841
    code = app.exec()
    result['exit'] = code
    write()
    os._exit(0)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--inner':
        return inner(Path(sys.argv[2]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--scenes', type=lambda text: [item for item in text.split(',') if item],
                        default=list(SCENES))
    parser.add_argument('--size', action='append')
    parser.add_argument('--lang', default='zh')
    parser.add_argument('--theme', default='grape')
    parser.add_argument('--scale', default='1')
    parser.add_argument('--timeout', type=int, default=420)
    parser.add_argument('--no-seed', action='store_true')
    return outer(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
