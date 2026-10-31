"""Real project / real window reproduction, opt-in and isolated."""
import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt, QEvent, QObject
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..studio.studio_speaker_manager import SpeakerManagerDialog
    from ..test_isolation import require_isolated_paths
    require_isolated_paths('review-speaker')
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    page = window.studio_page
    result = dict(checks=[], measures={}, passed=False)
    heartbeats = []
    heartbeat = QTimer(window)
    heartbeat.setInterval(10)
    last_tick = [time.perf_counter()]
    def beat():
        now = time.perf_counter()
        heartbeats.append((last_tick[0], now, (now-last_tick[0])*1000))
        last_tick[0] = now
    heartbeat.timeout.connect(beat)
    window._review_heartbeat = heartbeat
    heartbeat.start()
    log = (output / 'operations.jsonl').open('w', encoding='utf-8')

    def event(kind, **values):
        log.write(json.dumps(dict(t=time.perf_counter(), kind=kind, **values), ensure_ascii=False, default=str) + '\n')
        log.flush()

    def check(name, ok):
        result['checks'].append(dict(name=name, passed=bool(ok)))
        if not ok:
            raise AssertionError(name)

    def write():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')

    def flow():
        window.showMaximized()
        window.open_studio_project(spec['project'], mode='edit', source='review_speaker_audit')
        deadline = time.monotonic() + 150
        def interactive():
            gate = getattr(page, '_readiness', None)
            return bool(page.project and page.video._startup_state == 'READY' and gate and gate.ready
                        and not gate.active and not gate.loading.active and page.isVisible())
        while not interactive():
            if time.monotonic() > deadline:
                raise TimeoutError('Studio loading')
            yield .2
        yield 2
        check('normal loading cover retired before input', interactive())
        event('loaded', cues=len(page.project.cues), speakers=len(page.project.speakers))
        if spec.get('phase') == 'language-project':
            yield from language_project_flow()
            return
        if spec.get('phase') in ('workflow', 'performance'):
            yield from workflow()
            return
        QTimer.singleShot(0, page._open_speaker_manager)
        yield .4
        dialog = next(d for d in page.findChildren(SpeakerManagerDialog) if d.isVisible())
        window._review_test_dialog = dialog
        yield .5
        _capture(dialog, output / 'before.png')
        role_costs = []
        role_paints = []
        original_set_role = dialog._set_role
        def timed_role(label, role):
            began = time.perf_counter()
            original_set_role(label, role)
            role_costs.append(dict(label=label,role=role,ms=(time.perf_counter()-began)*1000))
        dialog._set_role = timed_role
        def all_texts():
            values = {c.id: c.text for c in page.project.cues}
            snapshot = page.project.generation_metadata['speaker_recovery']
            for label, role in snapshot['roles'].items():
                if role == 'ignore':
                    values.update({c['id']: c['text'] for c in snapshot.get('cue_cache', {}).get(label, ())})
            return values
        original_texts = all_texts()
        for label in spec.get('labels', ['R001_S06']):
            if dialog._roles().get(label) == 'ignore':
                if hasattr(dialog,'role_filter'):dialog.role_filter.setCurrentIndex(1)
                dialog.cards[label].restore_button.click()
                yield .3
            if hasattr(dialog,'role_filter'):dialog.role_filter.setCurrentIndex(2)
            card = dialog.cards[label]
            cue = next((c for c in page.project.cues if c.speaker_id == label), None)
            if cue is not None:
                page.select_cue(cue.id)
            yield .2
            event('click_ignore', label=label)
            started = time.perf_counter()
            class RolePaint(QObject):
                def __init__(self, card, key, click):
                    super().__init__(dialog)
                    self.key,self.click,self.measured=key,click,False
                    card.installEventFilter(self)
                def eventFilter(self, watched, event):
                    if event.type()==QEvent.Type.Paint and not self.measured and dialog._roles().get(self.key)=='ignore':
                        role_paints.append(dict(label=self.key,ms=(time.perf_counter()-self.click)*1000))
                        self.measured=True
                    return False
            probe = RolePaint(card,label,started)
            QTest.mouseClick(card.roles.buttons['ignore'], Qt.MouseButton.LeftButton)
            event('click_returned', label=label, ms=(time.perf_counter()-started)*1000)
            yield .3
            check('ignored '+label, dialog._roles()[label] == 'ignore')
            _capture(dialog, output / ('ignored-'+label+'.png'))
            event('restore', label=label)
            if hasattr(dialog,'role_filter'):dialog.role_filter.setCurrentIndex(1)
            restore = getattr(dialog.cards[label],'restore_button',None) or dialog.cards[label].roles.buttons['ignore']
            QTest.mouseClick(restore, Qt.MouseButton.LeftButton)
            yield .2
            check('restored '+label, dialog._roles()[label] == 'unconfirmed')
        dialog.close()
        yield .5
        check('unchanged captions including recoverable ignored', all_texts() == original_texts)
        result['measures'].update(role_commits=role_costs,ignore_to_card_paint=role_paints)
        result['passed'] = True
        page.undo_stack.setClean()

    def workflow():
        from ..recognition.service import MediaResult, QueueResult
        from ..projects.studio_project import load_project
        report = str(output / 'report.json')
        item = MediaResult(page.project.media.path, 'success', project_path=spec['project'], report_json_path=report)
        event('completion_begin')
        window._handle_result(QueueResult((item,), 687.539))
        yield .2
        notice = getattr(window, '_completion_dialog', None)
        if notice is not None:
            notice.accept()
        event('completion_ready')
        yield .5
        _capture(window, output / 'completion.png')
        event('proofread_begin')
        window._open_glossary_proofread()
        yield 1
        review = window.glossary_proofread_page
        event('proofread_ready')
        yield 1
        review._play('219')
        deadline = time.monotonic()+60
        while review._player.state not in ('playing', 'failed'):
            if time.monotonic()>deadline:raise TimeoutError('first audio')
            yield .02
        yield 1
        event('audio_state', state=review._player.state)
        review._player.stop()
        original = review._by_id['219']['base']
        review._edit_committed('219', original+'验收')
        yield .2
        event('return_begin')
        started = time.perf_counter()
        class PaintProbe(QObject):
            def eventFilter(self, watched, event):
                if event.type() == QEvent.Type.Paint and watched.isVisible():
                    result['measures'].setdefault('return_first_paint_ms', (time.perf_counter()-started)*1000)
                return False
        probe = PaintProbe(window)
        window.pages.widget(2).installEventFilter(probe)
        review._back()
        result['measures']['return_call_ms'] = (time.perf_counter()-started)*1000
        while window.pages.currentWidget() is review:
            if time.perf_counter()-started>60:raise TimeoutError('return save')
            yield .02
        result['measures']['return_navigation_ms'] = (time.perf_counter()-started)*1000
        event('return_finished', ms=result['measures']['return_call_ms'])
        yield .1
        if review._save_thread is not None:
            check('pending save shown accurately', '正在保存' in window.result_task_summary.text())
            check('export waits for durable save', not window.export_result_button.isEnabled())
        while review._save_thread is not None or review._save_timer.isActive() or review._save_again:
            if time.perf_counter()-started>60:raise TimeoutError('durable save')
            yield .02
        yield .03
        result['measures']['durable_save_ms'] = (time.perf_counter()-started)*1000
        ended = time.perf_counter()
        samples = [(min(b,ended)-max(a,started))*1000 for a,b,v in heartbeats if b>started and a<ended]
        (output/'return-ui-intervals.json').write_text(json.dumps(samples),'utf-8')
        result['measures']['return_save_ui_samples'] = len(samples)
        result['measures']['return_save_ui_gap_max_ms'] = max(samples) if samples else None
        check('return timer produced real samples', bool(samples))
        _capture(window, output / 'returned.png')
        reopened = load_project(spec['project'])
        if spec.get('phase') == 'performance':
            result['measures']['text_saved'] = next(c.text for c in reopened.cues if c.id=='219')==original+'验收'
            page.undo_stack.setClean()
            result['passed'] = True
            return
        check('edit durably saved after pending indicator', next(c.text for c in reopened.cues if c.id=='219')==original+'验收')
        check('result page returned', window.pages.currentWidget() is window.pages.widget(2))
        check('export enabled after save', window.export_result_button.isEnabled())
        yield .3
        _capture(window, output / 'saved-completion.png')
        QTimer.singleShot(0, window._show_completion_review_details)
        yield .3
        details = window._current_review_dialog
        current = window._completion_task_evidence[window._completion_task_key(item)]['display_payload']['_current_review']
        tree = details._review_tabs.widget(0)
        check('badge matches exactly locatable review rows', tree.topLevelItemCount() == len(current['items']))
        check('every counted item has a destination', all(row.get('cue_ids') or row.get('target') == 'speakers' for row in current['items']))
        _capture(details, output / 'current-review.png')
        details.accept()
        window._open_glossary_proofread()
        yield .3
        check('reopened proofreading keeps saved text', review._by_id['219']['base'] == original+'验收')
        review._back()
        yield .3
        window.open_studio_project(spec['project'], mode='edit', source='review_full_roundtrip')
        deadline = time.monotonic()+100
        while not (page.project and page._readiness.ready and not page._readiness.active
                   and not page._readiness.loading.active and page.isVisible()):
            if time.monotonic()>deadline:raise TimeoutError('reopen workbench')
            yield .05
        yield .3
        check('workbench text matches saved edit', next(c.text for c in page.project.cues if c.id=='219')==original+'验收')
        QTimer.singleShot(0, page._open_speaker_manager)
        yield .4
        manager = next(d for d in page.findChildren(SpeakerManagerDialog) if d.isVisible())
        initial = {c.id: (c.text,c.start_ms,c.end_ms) for c in reopened.cues}
        auto = page.project.generation_metadata['speaker_organization']['low_share_policy']['ignored']
        check('final logical low-share policy selects four speakers', set(auto) == {'R001_S06','R001_S07','R001_S09','R001_S10'})
        check('nine captions recoverable after automatic ignore', sum(v['cues'] for v in auto.values()) == 9)
        manager.role_filter.setCurrentIndex(1)
        yield .1
        _capture(manager, output / 'ignored-list.png')
        # Repeated input is one consistent role commit; preview is stopped by
        # the same production path before the selected speaker disappears.
        for cycle in range(4):
            label = 'R001_S06'
            if manager._roles()[label] == 'ignore':
                manager.cards[label].restore_button.click()
                yield .2
            manager.role_filter.setCurrentIndex(2)
            cue = next(c for c in page.project.cues if c.speaker_id == label)
            page.select_cue(cue.id)
            manager._card_preview(manager.cards[label])
            index = page.undo_stack.index()
            manager.cards[label].roles.buttons['ignore'].click()
            manager.cards[label].roles.buttons['ignore'].click()
            yield .3
            check('idempotent previewing ignore '+str(cycle), page.undo_stack.index() == index+1
                  and manager._roles()[label] == 'ignore' and not manager._preview_timer.isActive())
        # The last visible speaker and reopening a manager with no active
        # speakers must still expose its recoverable ignored list.
        for speaker in list(page.project.speakers):
            manager.role_filter.setCurrentIndex(2)
            manager.cards[speaker.id].roles.buttons['ignore'].click()
            yield .15
        check('all active speakers can be ignored without dangling cues', not page.project.cues and not page.project.speakers)
        manager.close()
        QTimer.singleShot(0, page._open_speaker_manager)
        yield .3
        manager = next(d for d in page.findChildren(SpeakerManagerDialog) if d.isVisible())
        manager.role_filter.setCurrentIndex(1)
        yield .1
        _capture(manager, output / 'all-ignored.png')
        for label, role in list(manager._roles().items()):
            if role == 'ignore':
                manager.cards[label].restore_button.click()
                yield .15
        check('restore retains every authored subtitle and time',
              {c.id:(c.text,c.start_ms,c.end_ms) for c in page.project.cues} == initial)
        page.undo_stack.undo()
        yield .1
        page.undo_stack.redo()
        yield .1
        check('undo redo restores the same content', {c.id:(c.text,c.start_ms,c.end_ms) for c in page.project.cues} == initial)
        manager.close()
        page.project_controller.save()
        yield .3
        from ..rendering.ass_compiler import compile_ass
        ass = compile_ass(page.project)
        (output/'roundtrip.ass').write_text(ass,'utf-8')
        check('production ASS exports all restored captions', ass.count('Dialogue: ') == len(initial))
        from ..exports.studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions
        from ..exports.srt_codec import parse_srt
        artifacts = export_subtitle_artifacts(page.project, output/'srt-export', 'roundtrip',
            SubtitleExportOptions(formats=frozenset({'srt'}), speaker_mode='both'))
        combined = next(a for a in artifacts if not a.speaker_id)
        rows, errors = parse_srt(combined.path.read_text('utf-8-sig'))
        check('SRT export parses all current captions', not errors and len(rows) == len(initial))
        check('speaker split has no duplicate or ignored lanes', len([a for a in artifacts if a.speaker_id]) == len(page.project.speakers))
        window.open_studio_project(spec['project'], mode='edit', source='review_final_reopen')
        deadline = time.monotonic()+100
        while not (page.project and page._readiness.ready and not page._readiness.active
                   and not page._readiness.loading.active and page.isVisible()):
            if time.monotonic()>deadline:raise TimeoutError('final reopen')
            yield .05
        check('saved reopen retains manual restores', {c.id:(c.text,c.start_ms,c.end_ms) for c in page.project.cues} == initial)
        from ..projects.low_share_speakers import apply_low_share_policy
        check('reopen does not re-ignore restored speakers', apply_low_share_policy(page.project) is None)
        _capture(window, output/'final-reopened.png')
        # Audit edits only belong to the owned copy.
        page.undo_stack.setClean()
        result['passed'] = True

    if spec.get('profile'):
        import cProfile
        from ..glossary.glossary_proofread import GlossaryProofreadPage, _SaveThread
        for owner, name in [(window, '_refresh_completion_preview'), (window, '_glossary_proofread_applied'),
                            (GlossaryProofreadPage, '_edit_committed'), (GlossaryProofreadPage, '_save_now'),
                            (_SaveThread, '__init__'), (_SaveThread, 'run')]:
            original_method = getattr(owner, name)
            def measured(*args, _name=name, _original=original_method, **kwargs):
                profile = cProfile.Profile()
                try:
                    return profile.runcall(_original, *args, **kwargs)
                finally:
                    profile.dump_stats(str(output / (_name+'.prof')))
            setattr(owner, name, measured)

    def settings_flow():
        import copy
        from ..providers.endpoint_editor_ui import PromptDialog
        from ..subtitle_rules.segmentation_profiles import prompt_languages
        from ..subtitle_rules.grouping_request import word_grouping_system_prompt
        from ..recognition.run_context import RuntimeContext,activate_runtime_context
        from ..storage.settings import load_runtime_settings
        window.showMaximized()
        values=window.legacy.RUNTIME_SETTINGS
        values.setdefault('grouping_prompts',{})['zh']='保留中文自定义'
        values['grouping_prompts']['it']='Italian task snapshot'
        old=copy.deepcopy(values)
        dialog=PromptDialog(window,values)
        window._language_settings_audit_dialog=dialog
        dialog.show()
        yield .2
        check('all effective languages and locale entries visible',dialog.language.count()==len(prompt_languages()))
        dialog.language.setCurrentIndex(dialog.language.findData('it'))
        yield .1
        check('Italian fixed policy is not Chinese16', '84' in dialog.fixed_note.text() and '16' not in dialog.fixed_note.text())
        dialog.editor.setPlainText("Conserva l'auto, dell'America e Kimi Antonelli.")
        dialog.language.setCurrentIndex(dialog.language.findData('fr'))
        dialog.editor.setPlainText("Conserver l'équipe et Jean-Luc.")
        dialog.language.setCurrentIndex(dialog.language.findData('it'))
        check('language switch keeps unsaved Italian draft',dialog.editor.toPlainText()=="Conserva l'auto, dell'America e Kimi Antonelli.")
        _capture(dialog,output/'italian-settings.png')
        dialog.restore.click()
        dialog.language.setCurrentIndex(dialog.language.findData('fr'))
        check('restore current language leaves French draft',dialog.editor.toPlainText()=="Conserver l'équipe et Jean-Luc.")
        dialog.language.setCurrentIndex(dialog.language.findData('it'))
        dialog.editor.setPlainText('Preferisci frasi complete e pause reali.')
        dialog.save()
        yield .2
        loaded=load_runtime_settings();loaded=loaded[0] if isinstance(loaded,tuple) else loaded
        check('Italian setting persisted',loaded['grouping_prompts']['it']=='Preferisci frasi complete e pause reali.')
        check('Chinese and French remain independent',loaded['grouping_prompts']['zh']=='保留中文自定义'
              and loaded['grouping_prompts']['fr']=="Conserver l'équipe et Jean-Luc.")
        with activate_runtime_context(RuntimeContext(task_language='it',asr_settings_snapshot=copy.deepcopy(loaded))):
            check('new runtime request immediately reads Italian setting','Preferisci frasi complete e pause reali.' in word_grouping_system_prompt('it'))
        with activate_runtime_context(RuntimeContext(task_language='it',asr_settings_snapshot=old)):
            check('running request keeps frozen old setting','Italian task snapshot' in word_grouping_system_prompt('it'))
        again=PromptDialog(window,loaded);again.show()
        again.language.setCurrentIndex(again.language.findData('it'))
        yield .2
        check('reopened editor restores saved Italian text',again.editor.toPlainText()=='Preferisci frasi complete e pause reali.')
        again.language.setCurrentIndex(again.language.findData('ko'))
        check('Korean shows weighted32 policy','32' in again.fixed_note.text() and '0.5' in again.fixed_note.text())
        _capture(again,output/'korean-settings.png')
        again.close()
        result['passed']=True

    def language_project_flow():
        import copy
        from ..projects.studio_project import save_project, load_project
        from ..subtitle_rules.language_rules import project_language
        from ..subtitle_rules.segmentation_profiles import profile_for
        from ..subtitle_rules import subtitle_translation as st
        from ..studio.studio_bilingual import set_manual_translation
        st.migrate(page.project)
        initial = {c.id:(c.text,c.start_ms,c.end_ms,c.speaker_id) for c in page.project.cues}
        records = copy.deepcopy(st.records_of(page.project))
        check('real Italian project resolves Italian84 policy',
              project_language(page.project)=='it' and profile_for(project_language(page.project)).hard_max==84)
        check('Chinese translation keeps its own target',st.container_target(page.project).startswith('zh'))
        check('translations use existing stable cue IDs',bool(records) and set(records)<=set(initial))
        cue_id = next(key for key in records if key in initial)
        page.select_cue(cue_id)
        yield .3
        _capture(window,output/'italian-existing-project.png')
        old = records[cue_id].get('text','')
        check('manual target edit uses current cue identity',set_manual_translation(page,cue_id,old+'验收'))
        page.undo_stack.undo()
        check('translation undo restores original records',st.records_of(page.project)==records)
        page.undo_stack.redo();page.undo_stack.undo()
        check('source content and timing remain unchanged',
              {c.id:(c.text,c.start_ms,c.end_ms,c.speaker_id) for c in page.project.cues}==initial)
        target=output/'italian-roundtrip.2byteproj'
        save_project(page.project,target)
        loaded=load_project(target)
        check('Italian save/reopen keeps source and translation identities',
              {c.id:(c.text,c.start_ms,c.end_ms,c.speaker_id) for c in loaded.cues}==initial
              and st.records_of(loaded)==records)
        result['measures'].update(cues=len(initial),translation_records=len(records),live_requests=0)
        page.undo_stack.setClean()
        result['passed']=True

    steps = settings_flow() if spec.get('phase')=='language-settings' else flow()
    state = dict(until=0., ticking=False)
    timer = QTimer(window)
    timer.setInterval(20)

    def tick():
        if state['ticking'] or time.monotonic() < state['until']:
            return
        state['ticking'] = True
        try:
            state['until'] = time.monotonic() + next(steps)
        except StopIteration:
            timer.stop(); write(); QApplication.instance().quit()
        except BaseException:
            result['error'] = traceback.format_exc()
            event('error', error=result['error'])
            page.undo_stack.setClean()
            timer.stop(); write(); QApplication.instance().quit()
        finally:
            state['ticking'] = False

    def shutdown():
        result['gui_shutdown'] = True
        write()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick)
    timer.start()
