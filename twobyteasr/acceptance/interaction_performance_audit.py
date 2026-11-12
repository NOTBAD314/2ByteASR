"""Opt-in normal-window timings. Paint completion is not monitor scanout."""
from __future__ import annotations
import cProfile
from collections import defaultdict, deque
import json
import math
import os
import platform
import statistics
import sys
import time
import traceback

_PAINT_COSTS = deque(maxlen=12000)


def distribution(values):
    values = sorted(values)
    return dict(n=len(values), median=round(statistics.median(values), 2),
        p95=round(values[max(0, math.ceil(.95*len(values))-1)], 2), max=round(max(values), 2)) if values else {}


def instrument():
    from ..diagnostics.navigation_timing import timed
    from ..local_models import model_workshop as mw, model_registry as mr
    from ..recognition import recognition_history as rh
    from ..glossary import main_ui_glossary as gl, term_library_ui as tl
    from ..app import home_tour as ht, ui
    from ..design.bunny_mascot import BunnyMascot
    original_paint = BunnyMascot.paintEvent
    def measured_paint(mascot, event):
        begin = time.perf_counter()
        try: return original_paint(mascot, event)
        finally: _PAINT_COSTS.append((id(mascot), begin, (time.perf_counter()-begin)*1000))
    BunnyMascot.paintEvent = measured_paint
    if os.environ.get('TWOBYTEASR_DIAGNOSE_NO_SUMMARY') == '1':
        def skip_summary(self):
            self._batch_queued = None
            self._batch_running = False
        gl.TermLibraryDialog._start_batch_summary = skip_summary
    for owner, names in (
        (mw.ModelWorkshopPage, ('__init__', '_build', 'refresh', '_refresh', '_apply_filter', '_model_state', '_refresh_detail')),
        (mw.ModelPickerPanel, ('__init__', '_build', 'refresh', 'begin_session')),
        (mr, ('scan_model_registry',)), (mw, ('installed_model_keys', '_runtime_role_available')),
        (rh.RecognitionHistoryPage, ('__init__', '_build', '_reload', '_render', '_apply_filter', '_on_parsed')),
        (rh, ('list_report_files', 'parse_listed_report')),
        (gl.TermLibraryDialog, ('__init__', 'refresh_current_game', 'refresh_learned', 'refresh_learning_suggestions', 'add_game_item')),
        (tl.TermLibraryPage, ('_ensure_library', 'prepare_for_show')),
        (ht.GuidedTour, ('_shake_window', '_shake_step', '_shake_done', '_puck_step', '_edge_hit', '_sync_geometry', '_relayout', '_apply_mask', 'paintEvent')),
        (ui.MainWindow, ('_open_model_picker', '_construct_lazy_page', '_open_model_workshop', '_manage_terms', '_open_recognition_history'))):
        for name in names:
            original = getattr(owner, name, None)
            if original is not None:
                setattr(owner, name, timed(f'{getattr(owner, "__name__", type(owner).__name__)}.{name}')(original))


def start(window, out):
    import psutil
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, Qt, QTimer, QVariantAnimation
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    from ..diagnostics import navigation_timing
    from ..app.home_tour import GuidedTour, TourStep
    app = QApplication.instance()

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = dict(pid=os.getpid(), entries=[], collisions=[], checks=[], resources=[], environment=dict(
                platform=platform.platform(), cpu=platform.processor(), cores=os.cpu_count(), python=sys.version,
                executable=sys.executable, frozen=bool(getattr(sys, 'frozen', False)), dpr=window.devicePixelRatioF()),
                measurement='queued GUI trigger to handler / Qt Paint completed / useful-control input; not physical input or scanout')
            self.active = None
            self.save()
            self.mascot = None
            self.paint_times = deque(maxlen=12000)
            self.paint_segment = 0
            self.impact_starts = []
            self.impact_ends = []
            self.edge_hits = []
            self.request_impact_navigation = False
            self.frames = deque(maxlen=12000)
            self.last = time.perf_counter()
            self.deadline = self.last + 310
            self.heartbeat = QTimer(self)
            self.heartbeat.setTimerType(Qt.TimerType.PreciseTimer)
            self.heartbeat.setInterval(8)
            self.heartbeat.timeout.connect(self.beat)
            self.heartbeat.start()
            app.installEventFilter(self)
            self.profiler = cProfile.Profile() if os.environ.get('TWOBYTEASR_INTERACTION_PROFILE') == '1' else None
            if self.profiler: self.profiler.enable()
            self.sequence = self.run()
            self.pending = 0
            self.driver = QTimer(self)
            self.driver.setInterval(10)
            self.driver.timeout.connect(self.tick)
            self.driver.start()
            app.aboutToQuit.connect(self.save)

        def beat(self):
            now = time.perf_counter()
            self.frames.append((now, (now-self.last)*1000))
            self.last = now

        def eventFilter(self, obj, event):
            if obj is self.mascot:
                if event.type() == QEvent.Type.Paint:
                    self.paint_times.append((self.paint_segment,time.perf_counter()))
                elif event.type() == QEvent.Type.Hide:
                    self.paint_segment += 1
            cur = self.active
            if cur and event.type() == QEvent.Type.Paint and obj is cur.get('target', lambda: None)():
                ready = cur['ready']()
                def painted(cur=cur, ready=ready):
                    now = time.perf_counter()
                    cur.setdefault('first_paint', now)
                    if ready: cur.setdefault('content', now)
                QTimer.singleShot(0, painted)
            return False

        def collision_metrics(self, begin):
            paints = [(segment,at) for segment,at in self.paint_times if at>=begin]
            intervals = [(b[1]-a[1])*1000 for a,b in zip(paints,paints[1:]) if a[0]==b[0]]
            costs = [cost for identifier,at,cost in _PAINT_COSTS if identifier==id(self.mascot) and at>=begin]
            tour = self.mascot.parentWidget()
            return dict(paint_intervals_ms=intervals,paint_interval_distribution=distribution(intervals),
                paint_cost_distribution=distribution(costs),paint_frames_over_50ms=sum(x>50 for x in intervals),
                qualifying_hits=sum(at>=begin for at,_side in self.edge_hits),
                animation_starts=sum(at>=begin for at in self.impact_starts),
                animation_durations_ms=[(end-start)*1000 for start,end in self.impact_ends if start>=begin],
                controllers=dict(shake_object=id(tour._shake),puck_timer_object=id(tour._puck),
                    flash_timer_object=id(tour._flash_timer),shake_running=(tour._shake.state()==QVariantAnimation.State.Running),
                    puck_running=tour._puck.isActive(),flash_running=tour._flash_timer.isActive()))

        def resource(self, label):
            process = psutil.Process()
            mem = process.memory_info()
            self.result['resources'].append(dict(label=label, rss_mib=mem.rss/2**20,
                private_mib=mem.private/2**20, widgets=len(app.allWidgets()), timers=len(window.findChildren(QTimer)),
                animations=len(window.findChildren(QVariantAnimation)), threads=process.num_threads(), handles=process.num_handles()))

        def target(self, kind):
            if kind == 'picker': return window.__dict__.get('_model_picker_primary_panel')
            if kind == 'terms': return window.term_library_page
            return window.built_page(kind)

        def ready(self, kind):
            page = self.target(kind)
            if page is None or not page.isVisible(): return False
            def actual(card):
                return card.__dict__.get('_card') if '_card' in card.__dict__ else card
            if kind == 'picker':
                top = [page.cards[key] for key in page.ordered_keys()[:2]]
                return bool(page.current_badge.text()) and all(actual(c) is not None for c in top) and any(
                    actual(c).action.isEnabled() for c in top)
            if kind == 'workshop':
                top = [page.card_layout.itemAt(i).widget() for i in (1,2)]
                return bool(page.available_badge.text()) and all(actual(c) is not None for c in top)
            if kind == 'history': return bool(page._cards) and page._cards[0].isVisible() and bool(page.records)
            library = page.library
            minimum = max(1, int(os.environ.get('TWOBYTEASR_INTERACTION_TERMS','0')))
            return bool(library and library.state['game'] and library.listing.model().rowCount() >= minimum and library.listing.isEnabled())

        def background(self, kind):
            page = self.target(kind)
            if page is None: return False
            if kind == 'picker': page = page.controller
            if kind == 'terms' and page.library is not None:
                library = page.library
                if not hasattr(library, '_sidebar_count_cursor'): return True
                return not getattr(library,'_row_build_running',False) and (
                    getattr(library,'_sidebar_count_cursor',0) >= library.game_list.count()) and not (
                    getattr(library,'_batch_running',False) or getattr(library,'_batch_queued',None))
            return not (getattr(page, 'background_busy', lambda: False)())

        def operation(self, kind, cycle):
            self.resource(kind+':before')
            cur = dict(kind=kind, cycle=cycle, start=time.perf_counter(), ready=lambda: self.ready(kind), target=lambda: self.target(kind))
            self.active = cur
            self.result['pending'] = dict(kind=kind, cycle=cycle)
            self.save()
            def invoke():
                cur['handler_start'] = time.perf_counter()
                if kind == 'picker': QTest.mouseClick(window.recognition_plan.cards['primary'], Qt.MouseButton.LeftButton)
                elif kind == 'workshop': window.model_workshop_button.click()
                elif kind == 'history': window._open_recognition_history()
                else: window._manage_terms()
                cur['handler_end'] = time.perf_counter()
            QTimer.singleShot(0, invoke)
            yield lambda: cur.get('content') is not None
            control = self.target(kind)
            # Exercise the real search/list input, then restore it without changing data.
            if kind == 'terms': control = control.library.listing
            elif kind == 'history': control = control.search
            elif kind == 'picker': control = control.scroll
            else: control = control.search
            control.setFocus()
            QTest.keyClick(control, Qt.Key.Key_Down)
            cur['interactive'] = time.perf_counter()
            yield lambda: self.background(kind)
            if kind == 'terms' and hasattr(self.target(kind).library,'_batch_summary_cache'):
                library = self.target(kind).library
                self.result['checks'].append(dict(name='exact term statistics completed', passed=(
                    library._batch_request_key in library._batch_summary_cache)))
            end = time.perf_counter()
            rows = navigation_timing.snapshot(cur['start'])
            phases = defaultdict(lambda: [0, 0.0, 0.0])
            for row in rows:
                stats = phases[row['phase']]; stats[0] += 1; stats[1] += row['ms']; stats[2] = max(stats[2], row['ms'])
            gaps = [gap for at, gap in self.frames if cur['start'] <= at <= end]
            self.result['entries'].append(dict(kind=kind, cycle=cycle,
                **{key+'_ms': round((cur[key]-cur['start'])*1000, 3) for key in ('handler_start','handler_end','first_paint','content','interactive')},
                background_ms=(end-cur['start'])*1000, longest_gui_interval_ms=max(gaps, default=0), long_frames=sum(x>50 for x in gaps),
                longest_gui_delay_ms=max(0,max(gaps,default=0)-8),delays_over_50ms=sum(x>58 for x in gaps),
                long_calls=[dict(phase=r['phase'],ms=r['ms']) for r in rows if r['thread']=='MainThread' and r['ms']>50],
                phases=dict(phases), rows=len(getattr(self.target(kind), 'records', []))))
            self.active = None
            self.save()
            if cycle == 0: window.grab().save(str(out/f'{kind}.png'))
            if kind == 'picker':
                window._modal_host._request_close()
                yield lambda: not window._modal_host.isVisible()
            else: window._return_to_settings()
            yield .15

        def run(self):
            yield lambda: not window._recognition_page_deferred and window.isVisible()
            game = os.environ.get('TWOBYTEASR_INTERACTION_GAME')
            if game:
                window.game_box.setCurrentText(game)
            self.resource('home')
            # No audit warm-up of the destination. Record whether startup idle preload ran.
            self.result['home_at_perf_counter'] = time.perf_counter()
            self.result['home_observed_ms'] = (time.time()-psutil.Process().create_time())*1000
            self.result['startup_cache_present'] = '_preloaded_installed_model_keys' in window.__dict__
            slow = int(os.environ.get('TWOBYTEASR_SLOW_STATUS_MS','0'))
            if slow:
                from ..local_models import model_registry
                original = model_registry.scan_model_registry
                def slow_scan(*args, **kwargs):
                    time.sleep(slow/1000)  # deliberate slow-disk fault injection, not product behavior
                    return original(*args, **kwargs)
                model_registry.scan_model_registry = navigation_timing.timed('injected.slow_registry')(slow_scan)
                try:
                    from ..local_models.model_status_cache import request_registry
                    from ..app.main_ui_helpers import APP_ROOT
                    request_registry(APP_ROOT, force=True)
                except ImportError:
                    pass
            first = os.environ.get('TWOBYTEASR_INTERACTION_FIRST', 'picker')
            order = [first] + [x for x in ('workshop','history','terms','picker') if x != first]
            for cycle in range(int(os.environ.get('TWOBYTEASR_INTERACTION_CYCLES','8'))+1):
                for kind in order: yield from self.operation(kind, cycle)
            self.resource('repeated')
            tour = GuidedTour(window, [TourStep('角色碰撞测量', lambda: window.recognition_plan)])
            self.mascot = tour.bubble.mascot
            original_hit = tour._edge_hit
            def hit(side,power):
                self.edge_hits.append((time.perf_counter(),side))
                result = original_hit(side,power)
                if self.request_impact_navigation and tour._shake.state()==QVariantAnimation.State.Running:
                    self.request_impact_navigation=False
                    QTimer.singleShot(0, impact_navigation)
                return result
            def impact_navigation():
                button=window.model_workshop_button
                point=tour.mapFromGlobal(button.mapToGlobal(button.rect().center()))
                allowed=not tour.mask().contains(point)
                active=tour._shake.state()==QVariantAnimation.State.Running
                before=time.perf_counter()
                QTest.mouseClick(button,Qt.MouseButton.LeftButton)
                self.result.setdefault('navigation_during_impact',[]).append(dict(
                    active=active,mask_allows_input=allowed,handler_ms=(time.perf_counter()-before)*1000,
                    arrived=window.pages.currentWidget() is window.built_page('workshop')))
                def back():
                    QTest.mouseClick(window.return_recognition_button,Qt.MouseButton.LeftButton)
                QTimer.singleShot(50,window,back)
            tour._edge_hit = hit
            def animation_state(new,old):
                now=time.perf_counter()
                if new==QVariantAnimation.State.Running: self.impact_starts.append(now)
                elif old==QVariantAnimation.State.Running and self.impact_starts:
                    self.impact_ends.append((self.impact_starts[-1],now))
            tour._shake.stateChanged.connect(animation_state)
            tour.start()
            yield lambda: tour.mode == 'shown' or tour.mode == 'away'
            tour._typer.finish()
            tour._undock_mascot()
            for maximized in (False, True):
                if maximized: window.showMaximized()
                else: window.showNormal()
                yield .3
                limits = tour._puck_limits()
                tour._puck_pos = QPointF(limits.center())
                tour._place_puck(tour._puck_pos)
                begin = time.perf_counter()
                tour._edge_hit('right', .8)
                yield lambda: tour._shake.state() != QVariantAnimation.State.Running
                self.result['collisions'].append(dict(kind='single', maximized=maximized,
                    actual_ms=(time.perf_counter()-begin)*1000, configured_ms=tour.SHAKE_MS,
                    frames=[gap for at,gap in self.frames if at>=begin],
                    phases=navigation_timing.snapshot(begin),**self.collision_metrics(begin)))
                yield .4
            window.showNormal()
            yield .3
            # The first two trials keep the teaching mask. The free-input
            # trial opens its hole over the whole window so navigation can
            # actually receive the same native hit, outside the bubble.
            tour.steps[0].target=lambda:window
            tour._relayout()
            duration = int(os.environ.get('TWOBYTEASR_COLLISION_SECONDS','35'))
            begin = time.perf_counter()
            throws = 0
            def mouse(kind, point, held):
                mascot = tour.bubble.mascot
                local = QPointF(mascot.mapFromGlobal(point.toPoint()))
                QCoreApplication.sendEvent(mascot, QMouseEvent(kind, local, point,
                    Qt.MouseButton.LeftButton, held, Qt.KeyboardModifier.NoModifier))
            while time.perf_counter()-begin < duration:
                if throws and throws%14==0:
                    self.request_impact_navigation=True
                mascot = tour.bubble.mascot
                start = QPointF(mascot.mapToGlobal(mascot.rect().center()))
                direction = ((1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,-1))[throws%6]
                mouse(QEvent.Type.MouseButtonPress,start,Qt.MouseButton.LeftButton)
                for step in range(1,6):
                    yield .02
                    end = start+QPointF(direction[0]*step*65,direction[1]*step*65)
                    mouse(QEvent.Type.MouseMove,end,Qt.MouseButton.LeftButton)
                mouse(QEvent.Type.MouseButtonRelease,end,Qt.MouseButton.NoButton)
                throws += 1
                yield .5
            self.result['collisions'].append(dict(kind='continuous', seconds=time.perf_counter()-begin,
                throws=throws, frames=[gap for at,gap in self.frames if at>=begin], phases=navigation_timing.snapshot(begin),
                **self.collision_metrics(begin)))
            # Rapid close/reopen and current config are checked through the cached panel.
            tour.close_tour(False)
            yield .1
            if int(os.environ.get('TWOBYTEASR_SLOW_STATUS_MS','0')):
                try:
                    from ..local_models.model_status_cache import request_registry
                    from ..app.main_ui_helpers import APP_ROOT
                    request_registry(APP_ROOT,force=True)
                except ImportError: pass
            for _ in range(3):
                window._open_model_picker('primary')
                panel=window._model_picker_primary_panel
                expected=panel.controller._selected_model_key_for_role('primary')
                self.result['checks'].append(dict(name='current selection', passed=expected is None or
                    panel.cards[expected].property('selected') or not panel.controller._installed))
                window._modal_host._request_close()
                yield lambda:not window._modal_host.isVisible()
            window.showMinimized();yield .1;window.showNormal();yield .2
            self.resource('final')
            for row in self.result.get('navigation_during_impact',[]):
                self.result['checks'].append(dict(name='navigation receives input during feedback',
                    passed=row['mask_allows_input'] and row['arrived']))
            self.result['passed'] = all(check['passed'] for check in self.result['checks'])

        def tick(self):
            try:
                if time.perf_counter()>self.deadline: raise TimeoutError('Interaction benchmark timeout')
                if callable(self.pending):
                    if not self.pending(): return
                elif time.perf_counter()<self.pending: return
                step = next(self.sequence)
                self.pending = step if callable(step) else time.perf_counter()+step
            except StopIteration: self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc(); self.result['passed'] = False; self.finish()

        def save(self):
            self.result['summary'] = {f'{kind}:{"first" if cycle==0 else "repeat"}': distribution([
                row['interactive_ms'] for row in self.result['entries'] if row['kind']==kind and (row['cycle']==0)==(cycle==0)])
                for kind in ('workshop','history','terms','picker') for cycle in (0,1)}
            (out/'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

        def finish(self):
            self.driver.stop(); self.heartbeat.stop(); app.removeEventFilter(self)
            if self.profiler:
                self.profiler.disable(); self.profiler.dump_stats(str(out/'gui.prof'))
            self.save()
            window.close()
    window._interaction_audit = Audit()
