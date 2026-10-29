"""Real-window check: the home page asks which audio tracks to recognize (2026-10-24).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=home-audio-tracks`` (isolated
data; ``scripts/verify_home_audio_tracks_headed.py``, source or frozen). The
runner passes the media of ``verify_multi_audio_tracks_headed`` (streams that
say different things, ``TWOBYTEASR_MULTI_AUDIO``) and links the local models.
On the home page, without Studio, this scenario:

1. queues a two-track MP4 and presses 开始识别: 「选择要识别的音轨」 lists both
   tracks with the file default ticked; the preview of track 2 plays track 2;
   取消 starts nothing;
2. recognizes track 2 only: the shared 16 kHz audio and the incremental
   chunks the model reads are track 2, the result names its source and
   nothing is written next to the video;
3. recognizes both tracks: two inputs with their own caches, one combined
   result grouped by source, which Studio opens with both lanes;
4. MKV with a subtitle stream between the audio streams and a dub that starts
   3 s late: the picked dub's captions sit 3 s later, as in the video;
5. a stereo and a 5.1 file each start at once without a picker.

Every recognition uses the local models chosen in ``TWOBYTEASR_MULTI_AUDIO``;
nothing contacts the network or a paid service.
"""
from __future__ import annotations

import glob
import json
import os
import time
import traceback
from pathlib import Path

from .multi_audio_tracks_audit import _best_correlation, _best_lag_ms, _envelope, _pcm


def start(window, output: Path):
    import numpy as np
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    app = QApplication.instance()
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads(os.environ['TWOBYTEASR_MULTI_AUDIO'])
    result = dict(checks=[], metrics={}, errors=[], dialogs=[], passed=False, pid=os.getpid(),
                  executable=os.path.realpath(__import__('sys').executable))
    references = {name: _envelope(_pcm(path)) for name, path in config['references'].items()}

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        save_result()
        return bool(ok)

    def save_result():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def settle(ms=300):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def wait_for(predicate, timeout=40.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            app.processEvents()
            try:
                if predicate():
                    return True
            except Exception:  # noqa: BLE001 - keep polling
                pass
            time.sleep(0.05)
        return False

    def grab(widget, name):
        try:
            widget.grab().save(str(output / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'grab {name}: {exc!r}')

    def close_message_boxes():
        for widget in app.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible():
                result['dialogs'].append(widget.text())
                widget.done(0)

    watchdog = QTimer()
    watchdog.timeout.connect(close_message_boxes)
    watchdog.start(400)

    def picker_now():
        from ..studio.audio_track_picker import AudioTrackPicker
        content = window._modal_host._current_content
        return content if isinstance(content, AudioTrackPicker) and window._modal_host.isVisible() else None

    def set_models():
        primary, timeline, review = config['models']
        set_ok = [window._set_backend_combo(window.primary_asr_backend, primary),
                  window._set_backend_combo(window.firered_asr_backend, timeline),
                  window._set_backend_combo(window.qwen_asr_backend, review)]
        check(f'models set: {primary}/{timeline}/{review}', all(set_ok), set_ok)

    def queue(media):
        window._switch_page(0)
        settle(300)
        window.import_media([str(media)], replace=True)
        wanted = [str(Path(media).resolve())]
        ok = wait_for(lambda: [str(Path(p).resolve()) for p in window.media_paths] == wanted, 30)
        settle(600)
        return ok

    def press_start(tag, expect_picker=True):
        window.start_button.click()
        if expect_picker:
            found = wait_for(lambda: picker_now() is not None, 20)
            check(f'{tag}: 开始识别 opens 「选择要识别的音轨」', found,
                  type(window._modal_host._current_content).__name__)
            settle(500)
            return picker_now()
        started = wait_for(lambda: window._run_in_progress, 20)
        check(f'{tag}: 开始识别 starts at once without a picker', started and picker_now() is None,
              dict(run=window._run_in_progress, modal=type(window._modal_host._current_content).__name__))
        return None

    def newest_run_log():
        logs = sorted(glob.glob(str(Path(os.environ['LOCALAPPDATA']) / '2ByteASR' / 'logs' / 'auto_asr_*.jsonl')),
                      key=os.path.getmtime)
        return Path(logs[-1]) if logs else None

    def run_events(path):
        rows = []
        for line in Path(path).read_text('utf-8', errors='replace').splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
        return rows

    def wait_run(tag, logs_before, timeout=900):
        started = time.monotonic()
        running = wait_for(lambda: window._run_in_progress, 30)
        check(f'{tag}: recognition started', running)
        wait_for(lambda: not window._run_in_progress and window.worker is not None and not window.worker.isRunning(),
                 timeout)
        settle(2500)
        result['metrics'][f'{tag}_seconds'] = round(time.monotonic() - started, 1)
        log = newest_run_log()
        events = run_events(log) if log and log != logs_before else []
        result['metrics'][f'{tag}_lane_events'] = [
            {k: e.get(k) for k in ('event', 'audio_stream_ordinal', 'audio_stream_index', 'label', 'status',
                                   'lane_index', 'lane_total', 'error')}
            for e in events if str(e.get('event', '')).startswith(('audio_lane', 'audio_stream'))]
        failed = [e for e in events if e.get('event') in {'queue_failed', 'media_failed', 'audio_streams_combine_failed'}]
        if failed:
            result['metrics'][f'{tag}_failures'] = failed[-3:]
        return events

    def completion():
        return list(getattr(window, '_completion_tasks', []) or [])

    def selected(events):
        return [e for e in events if e.get('event') == 'audio_stream_selected']

    def heard_input(row, own, others, tag, *, lag_ms=None):
        """The shared audio (and first chunk) the model read for this track."""
        cache = Path(str(row.get('cache_dir') or ''))
        npy = cache / 'audio_16k.npy'
        if not check(f'{tag}: the track has its own shared-audio cache', npy.is_file(), str(cache)):
            return
        audio = np.load(npy, mmap_mode='r')
        probe = _envelope(np.asarray(audio, dtype=np.float32) * 32768.0)
        scores = {name: _best_correlation(probe, references[name]) for name in (own, *others)}
        result['metrics'][f'{tag}_input_correlation'] = scores
        check(f'{tag}: the audio sent to the model is {own}',
              scores[own] >= 0.8 and all(scores[own] > scores[o] + 0.3 for o in others), scores)
        if lag_ms is not None:
            lag = _best_lag_ms(probe, references[own])
            result['metrics'][f'{tag}_input_lag_ms'] = lag
            check(f'{tag}: the track sits {lag_ms} ms into the video in that audio', abs(lag - lag_ms) <= 80, lag)
        chunks = sorted(glob.glob(str(cache / 'incremental-asr' / '*' / 'chunks' / '*.wav')))
        if chunks:
            piece = _envelope(_pcm(chunks[0]))
            chunk_scores = {name: _best_correlation(piece, references[name]) for name in (own, *others)}
            result['metrics'][f'{tag}_chunk_correlation'] = chunk_scores
            check(f'{tag}: the incremental chunk is {own} too',
                  chunk_scores[own] >= 0.8 and all(chunk_scores[own] > chunk_scores[o] + 0.3 for o in others),
                  chunk_scores)

    def groups_of(project):
        from ..recognition.audio_lane_results import SOURCES_KEY
        sources = project.studio_state.get(SOURCES_KEY) or {}
        groups = {}
        for cue in project.cues:
            lane = (sources.get(cue.speaker_id) or {}).get('lane_id', '(none)')
            groups.setdefault(lane, []).append(cue)
        return groups, sources

    def words_check(text, wanted, unwanted, tag):
        hits = [w for w in wanted if w.lower() in text.lower()]
        wrong = [w for w in unwanted if w.lower() in text.lower()]
        check(f'{tag}: captions say this track’s words', len(hits) >= max(1, len(wanted) // 2) and not wrong,
              dict(text=text[:200], hits=hits, wrong=wrong))

    def pick(picker, lanes, tag):
        for lane, box in picker.checks.items():
            box.setChecked(lane in lanes)
        settle(300)
        grab(window, f'{tag}_window_picker')
        grab(window._modal_host.card, f'{tag}_picker')
        result['metrics'][f'{tag}_picker_texts'] = dict(count=picker.count_label.text(), note=picker.note.text(),
                                                        note_visible=picker.note.isVisible())
        logs_before = newest_run_log()
        picker.start_button.click()
        return logs_before

    def written_next_to(media):
        # Recognition keeps its output in the project; export is the user's step.
        return sorted(p.name for p in Path(media).parent.glob(f'{Path(media).stem}_*'))

    words = config['words']

    def run_mp4():
        media = config['media']['mp4']
        set_models()
        check('MP4: queued on the home page', queue(media))
        grab(window, 'mp4_0_home_queued')
        picker = press_start('MP4')
        if picker is None:
            return None
        rows = [(r['lane_id'], r['ordinal'], r['stream_index']) for r in picker.rows]
        check('MP4 picker: one row per track with its stream identity', rows == [('A1', 0, 1), ('A2', 1, 2)], rows)
        labels = [box.text() for box in picker.checks.values()]
        check('MP4 picker: rows read 音轨 N｜title｜language｜channels',
              labels == ['音轨 1｜中文原音｜中文｜立体声', '音轨 2｜第二配音｜中文｜立体声'], labels)
        check('MP4 picker: the file default track is preselected, not all',
              [lane for lane, box in picker.checks.items() if box.isChecked()] == ['A1'])
        check('MP4 picker: no impact line about existing captions (nothing to replace)', not picker.impact.isVisible())
        from PySide6.QtWidgets import QLabel
        details = [label.text() for label in picker.findChildren(QLabel, 'audioTrackDetails')]
        check('MP4 picker: no timeline mute note on the home page', details and not any('静音' in t for t in details),
              details)
        grab(window, 'mp4_1_window_picker')
        decoded = {}
        player = picker._ensure_player()
        original = player._start

        def capture(request_id, payload, original=original):
            decoded[player.cue_id] = bytes(payload)
            return original(request_id, payload)
        player._start = capture
        picker.preview_buttons['A2'].click()
        check('MP4 picker: preview of A2 starts', wait_for(lambda: player.cue_id == 'A2' and 'A2' in decoded, 30))
        if 'A2' in decoded:
            pcm = np.frombuffer(decoded['A2'], dtype='<i2').astype(np.float32).reshape(-1, 2).mean(axis=1)
            scores = {name: _best_correlation(_envelope(pcm, rate=48000), references[name]) for name in ('track1', 'track2')}
            result['metrics']['mp4_preview_correlation'] = scores
            check('MP4 picker: the preview plays track 2', scores['track2'] > scores['track1'] + 0.3, scores)
        picker.preview_buttons['A2'].click()
        check('MP4 picker: stop leaves nothing playing', wait_for(lambda: player.cue_id == '', 5))
        logs_before = newest_run_log()
        cache_root = Path(os.environ['LOCALAPPDATA']) / '2ByteASR' / 'cache'
        caches_before = len(glob.glob(str(cache_root / '**' / 'audio_16k.npy'), recursive=True))
        picker.cancel_button.click()
        settle(1200)
        check('MP4 picker: 取消 closes it and starts nothing',
              picker_now() is None and not window._run_in_progress and window.worker is None
              and newest_run_log() == logs_before
              and len(glob.glob(str(cache_root / '**' / 'audio_16k.npy'), recursive=True)) == caches_before,
              dict(run=window._run_in_progress, worker=repr(window.worker)))
        check('MP4 picker: the start button is usable again', window.start_button.isEnabled())

        # Track 2 only.
        picker = press_start('MP4 again')
        if picker is None:
            return None
        logs_before = pick(picker, {'A2'}, 'mp4_only_a2')
        events = wait_run('mp4_only_a2', logs_before)
        from ..recognition.audio_stream_choice import parse_request
        request = parse_request(window._last_run_options.audio_streams_json)
        check('MP4 only A2: the run asks for track 2 only (ordinal 1, stream 2)',
              list(request.values()) == [[{'ordinal': 1, 'stream_index': 2}]], request)
        rows = selected(events)
        check('MP4 only A2: exactly one input, track 2',
              [(e.get('audio_stream_ordinal'), e.get('audio_stream_index')) for e in rows] == [(1, 2)],
              [(e.get('audio_stream_ordinal'), e.get('audio_stream_index')) for e in rows])
        if rows:
            heard_input(rows[0], 'track2', ('track1',), 'MP4 only A2', lag_ms=1000)
        tasks = completion()
        check('MP4 only A2: one finished result with a project',
              len(tasks) == 1 and tasks[0][0].status in {'success', 'degraded_success'} and tasks[0][1] is not None,
              [(t[0].status, t[0].error) for t in tasks])
        grab(window, 'mp4_2_completion_only_a2')
        if tasks and tasks[0][1] is not None:
            groups, sources = groups_of(tasks[0][1])
            check('MP4 only A2: every caption comes from A2', set(groups) == {'A2'}, sorted(groups))
            words_check(''.join(c.text for c in groups.get('A2', [])), words['track2'], words['track1'], 'MP4 only A2')
            names = sorted({s.name for s in tasks[0][1].speakers})
            check('MP4 only A2: speakers carry the track name', names and all('第二配音' in n for n in names), names)
        check('MP4 only A2: nothing written next to the video', not written_next_to(media), written_next_to(media))

        # Both tracks: the picker remembers track 2.
        window._switch_page(0)
        settle(400)
        picker = press_start('MP4 both')
        if picker is None:
            return None
        check('MP4 both: the picker preselects the previous choice (A2)',
              [lane for lane, box in picker.checks.items() if box.isChecked()] == ['A2'])
        logs_before = pick(picker, {'A1', 'A2'}, 'mp4_both')
        check('MP4 both: the picker says the tracks are recognized apart',
              '分别识别' in result['metrics']['mp4_both_picker_texts']['note'], result['metrics']['mp4_both_picker_texts'])
        events = wait_run('mp4_both', logs_before, timeout=1500)
        rows = selected(events)
        check('MP4 both: two inputs, track 1 then track 2, each with its own cache',
              [(e.get('audio_stream_ordinal'), e.get('audio_stream_index')) for e in rows] == [(0, 1), (1, 2)]
              and len({e.get('cache_dir') for e in rows}) == 2,
              [(e.get('audio_stream_ordinal'), e.get('cache_dir')) for e in rows])
        if len(rows) == 2:
            heard_input(rows[0], 'track1', ('track2',), 'MP4 both A1')
            heard_input(rows[1], 'track2', ('track1',), 'MP4 both A2')
        tasks = completion()
        check('MP4 both: one combined result', len(tasks) == 1 and tasks[0][0].status in {'success', 'degraded_success'}
              and tasks[0][1] is not None, [(t[0].status, t[0].error) for t in tasks])
        grab(window, 'mp4_3_completion_both')
        path = None
        if tasks and tasks[0][1] is not None:
            groups, sources = groups_of(tasks[0][1])
            check('MP4 both: captions grouped by source A1 and A2', set(groups) == {'A1', 'A2'}, sorted(groups))
            words_check(''.join(c.text for c in groups.get('A1', [])), words['track1'], words['track2'], 'MP4 both A1')
            words_check(''.join(c.text for c in groups.get('A2', [])), words['track2'], words['track1'], 'MP4 both A2')
            owners = {}
            for sid, row in sources.items():
                owners.setdefault(row.get('lane_id'), set()).add(sid)
            check('MP4 both: the two tracks never share a speaker',
                  owners.get('A1') and owners.get('A2') and not (owners['A1'] & owners['A2']), owners)
            path = str(tasks[0][0].project_path)
        if path:
            folder = Path(path).parent / 'subtitles'
            result['metrics']['mp4_both_project_subtitles'] = sorted(p.name for p in folder.glob('*.srt'))
        check('MP4 both: nothing written next to the video', not written_next_to(media), written_next_to(media))
        return path

    def run_studio_open(path):
        ready = {'v': False}
        window.open_studio_project(str(path), mode='edit', source='startup_audit',
                                   on_ready=lambda *a, **k: ready.__setitem__('v', True))
        check('Studio: the combined home result opens', wait_for(lambda: ready['v'], 90))
        settle(2000)
        studio = window._studio_page_instance
        try:
            studio.video.set_paused(True)
            studio._sync_play_button(True)
        except Exception:  # noqa: BLE001
            pass
        from ..recognition.audio_lane_results import CHOICE_KEY
        from ..timeline.audio_stream_lanes import recognizable_lanes, source_key
        lanes = {row['lane_id']: source_key(row) for row in recognizable_lanes(studio.project)}
        groups, sources = groups_of(studio.project)
        check('Studio: both tracks are lanes and the captions keep their source lanes',
              {'A1', 'A2'} <= set(lanes) and set(groups) == {'A1', 'A2'}
              and all(row.get('source_key') == lanes.get(row.get('lane_id')) for row in sources.values()),
              dict(lanes=lanes, groups=sorted(groups)))
        check('Studio: 识别字幕 would preselect both tracks',
              sorted(studio.project.studio_state.get(CHOICE_KEY) or []) == sorted(lanes[k] for k in ('A1', 'A2')))
        grab(window, 'studio_combined_result')
        window._switch_page(0)
        settle(600)

    def run_mkv():
        media = config['media']['mkv']
        check('MKV: queued on the home page', queue(media))
        picker = press_start('MKV')
        if picker is None:
            return
        rows = [(r['lane_id'], r['ordinal'], r['stream_index']) for r in picker.rows]
        check('MKV picker: three tracks, subtitle stream skipped in the ordinals',
              rows == [('A1', 0, 1), ('A2', 1, 3), ('A3', 2, 4)], rows)
        labels = [box.text() for box in picker.checks.values()]
        check('MKV picker: an untitled track shows only what the file says',
              labels[2] == '音轨 3｜语言未标示｜单声道', labels)
        logs_before = pick(picker, {'A2'}, 'mkv_dub')
        events = wait_run('mkv_dub', logs_before)
        rows = selected(events)
        check('MKV dub: one input, ordinal 1 = stream 3, 3 s late',
              [(e.get('audio_stream_ordinal'), e.get('audio_stream_index'), round(float(e.get('offset_ms') or 0)))
               for e in rows] == [(1, 3, 3000)], rows)
        if rows:
            heard_input(rows[0], 'track2', ('track1', 'track3'), 'MKV dub', lag_ms=3000)
        tasks = completion()
        check('MKV dub: finished with a project', len(tasks) == 1 and tasks[0][1] is not None,
              [(t[0].status, t[0].error) for t in tasks])
        grab(window, 'mkv_completion_dub')
        if tasks and tasks[0][1] is not None:
            project = tasks[0][1]
            groups, _sources = groups_of(project)
            words_check(''.join(c.text for c in project.cues), words['track2'], words['track1'] + words['track3'],
                        'MKV dub')
            first = min((c.start_ms for c in project.cues), default=-1)
            expected = 3000 + int(config['track2_speech_start_ms'])
            result['metrics']['mkv_first_caption_ms'] = dict(first=first, expected=expected)
            check('MKV dub: the first caption sits where the dub speaks in the video (≈3 s later)',
                  first >= 0 and abs(first - expected) <= 600, dict(first=first, expected=expected))

    def run_single_tracks():
        for name in ('stereo', 'surround'):
            media = config['media'][name]
            check(f'{name}: queued on the home page', queue(media))
            logs_before = newest_run_log()
            press_start(name, expect_picker=False)
            check(f'{name}: the run asks for no track choice', window._last_run_options.audio_streams_json == '')
            events = wait_run(name, logs_before)
            check(f'{name}: no stream selected (whole-file run as before)', not selected(events)
                  and not any(e.get('event') == 'audio_streams_planned' for e in events),
                  [e.get('event') for e in events if str(e.get('event', '')).startswith('audio_')])
            tasks = completion()
            from ..recognition.audio_lane_results import SOURCES_KEY
            check(f'{name}: a plain result without track sources',
                  len(tasks) == 1 and tasks[0][1] is not None and SOURCES_KEY not in tasks[0][1].studio_state,
                  [(t[0].status, t[0].error) for t in tasks])
            grab(window, f'{name}_completion')

    def run_all():
        try:
            for dialog in [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]:
                QDialog.done(dialog, 0)
            window.showNormal()
            window.resize(1500, 940)
            settle(800)
            path = None
            try:
                path = run_mp4()
            except Exception:  # noqa: BLE001
                result['errors'].append(traceback.format_exc())
            save_result()
            if path:
                try:
                    run_studio_open(path)
                except Exception:  # noqa: BLE001
                    result['errors'].append(traceback.format_exc())
            for step in (run_mkv, run_single_tracks):
                try:
                    step()
                except Exception:  # noqa: BLE001
                    result['errors'].append(traceback.format_exc())
                save_result()
        except Exception:  # noqa: BLE001
            result['errors'].append(traceback.format_exc())
        watchdog.stop()
        result['passed'] = bool(result['checks']) and all(c['passed'] for c in result['checks']) and not result['errors']
        save_result()
        window.close()
        QTimer.singleShot(500, app.quit)

    def shutdown():
        result['gui_shutdown'] = True
        save_result()

    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(2500, run_all)
