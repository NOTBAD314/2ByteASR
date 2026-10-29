"""Real-window check: multi-track media import and the recognition track picker (2026-10-24).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=multi-audio-tracks`` (isolated
data; ``scripts/verify_multi_audio_tracks_headed.py``, source or frozen). The
runner passes test media whose audio streams say different things
(``TWOBYTEASR_MULTI_AUDIO``: paths, expected words, reference clips) and links
the local models it needs. In the real window this scenario:

1. drops a two-track MP4 into an empty project: both tracks appear under V1,
   each with its own waveform; only the file's default track is audible;
2. opens 识别字幕: the picker lists both tracks; a preview of track 2 decodes
   track 2; 取消 starts nothing;
3. recognizes track 2 only: the recognition input is track 2's audio and the
   captions say track 2's words, under A2 speakers;
4. recognizes tracks 1 and 2 together: two inputs, two caption groups, the
   earlier track-2 captions replaced, not doubled;
5. MKV with a subtitle stream between the audio streams and a dub that starts
   3 s late, after a 2 s ripple cut: the picked dub's captions land at their
   edited project time;
6. reopens the saved result; a stereo and a 5.1 file each stay one track and
   skip the picker; a file without audio says so.

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


def _pcm(path, rate=16000):
    import subprocess
    import numpy as np
    root = Path(__file__).resolve().parents[2]
    from ..system.platform_media import ffmpeg_tool
    ffmpeg = ffmpeg_tool(root=root)
    raw = subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(path), '-ac', '1', '-ar', str(rate), '-f', 's16le', '-'],
                         capture_output=True, creationflags=0x08000000 if os.name == 'nt' else 0).stdout
    return np.frombuffer(raw, dtype='<i2').astype(np.float32)


def _envelope(samples, rate=16000, step_ms=20):
    import numpy as np
    win = rate * step_ms // 1000
    usable = len(samples) // win * win
    return np.abs(samples[:usable]).reshape(-1, win).mean(axis=1) if usable else np.zeros(0)


def _best_correlation(probe, reference, max_lag=150):
    """Highest normalized correlation of two loudness envelopes over ±3 s lags."""
    import numpy as np
    best = 0.0
    for lag in range(-max_lag, max_lag + 1):
        a = probe[max(0, lag):]
        b = reference[max(0, -lag):]
        n = min(len(a), len(b))
        if n < 25:
            continue
        x, y = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
        denominator = float(np.linalg.norm(x) * np.linalg.norm(y))
        if denominator > 0:
            best = max(best, float(np.dot(x, y)) / denominator)
    return round(best, 3)


def _best_lag_ms(probe, reference, max_lag=300):
    """Offset (ms, 20 ms steps) at which ``reference`` best matches inside ``probe``."""
    import numpy as np
    best, lag_at = -2.0, 0
    for lag in range(0, max_lag + 1):
        a = probe[lag:]
        n = min(len(a), len(reference))
        if n < 25:
            break
        x, y = a[:n] - a[:n].mean(), reference[:n] - reference[:n].mean()
        denominator = float(np.linalg.norm(x) * np.linalg.norm(y))
        score = float(np.dot(x, y)) / denominator if denominator > 0 else -2.0
        if score > best:
            best, lag_at = score, lag
    return lag_at * 20


def start(window, output: Path):
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
        save_result()  # progress stays readable if a later step hangs
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

    def fit_timeline(studio):
        from ..timeline.studio_edit_sequence import timeline_duration_ms
        try:
            studio.timeline.set_visible_window(0, max(1000, int(timeline_duration_ms(studio.project)) + 400))
            studio.timeline.set_playhead(0)
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'fit timeline: {exc!r}')
        settle(400)

    def grab(widget, name):
        studio = window._studio_page_instance
        if studio is not None and studio.project is not None and (widget is window or widget is studio.timeline):
            fit_timeline(studio)  # the whole clip, so every lane's waveform shows
        try:
            widget.grab().save(str(output / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'grab {name}: {exc!r}')

    def close_message_boxes():
        # A blocking box during a run would freeze the scenario; record and close it.
        for widget in app.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible():
                result['dialogs'].append(widget.text())
                widget.done(0)

    watchdog = QTimer()
    watchdog.timeout.connect(close_message_boxes)
    watchdog.start(400)

    def page():
        return window._studio_page_instance

    def open_project(path):
        ready = {'v': False}
        window.open_studio_project(str(path), mode='edit', source='startup_audit',
                                   on_ready=lambda *a, **k: ready.__setitem__('v', True))
        wait_for(lambda: ready['v'], 90)
        settle(1500)
        studio = page()
        try:
            studio.video.set_paused(True)
            studio._sync_play_button(True)
        except Exception:  # noqa: BLE001
            pass
        return studio

    def drop(media):
        studio = page()
        before = len(studio.project.media_pool)
        studio._begin_media_drop([str(media)], 0)
        ok = wait_for(lambda: len(studio.project.media_pool) > before and studio.project.audio_tracks is not None, 60)
        settle(1200)
        studio.save()
        return ok

    def waveforms_ready(studio, streams):
        caches = studio.timeline.waveform_caches
        done = {c.metadata.audio_stream for c in caches.values()
                if not c.metadata.incomplete and c.metadata.sample_rate > 2000}
        return set(streams) <= done

    def waveform_envelope(studio, stream):
        """The drawn waveform as 20 ms loudness bins on the project clock."""
        import numpy as np
        cache = next(c for c in studio.timeline.waveform_caches.values() if c.metadata.audio_stream == stream
                     and c.metadata.sample_rate > 2000)
        level = min(cache.metadata.levels, key=lambda item: item.milliseconds_per_frame)
        pairs = np.fromfile(cache.root / level.file, dtype=np.float32)[: level.frames * 2].reshape(-1, 2)
        times = cache.metadata.sample_timeline_origin_ms + np.arange(len(pairs)) * level.milliseconds_per_frame
        bins = (times // 20).astype(int)
        weight = np.bincount(bins, weights=pairs[:, 1] - pairs[:, 0])
        count = np.bincount(bins)
        return np.divide(weight, np.maximum(count, 1))

    def waveform_offset_ms(studio, stream, reference):
        """Where the reference clip sits in the drawn waveform (project ms)."""
        return _best_lag_ms(waveform_envelope(studio, stream), references[reference])

    def set_models():
        primary, timeline, review = config['models']
        set_ok = [window._set_backend_combo(window.primary_asr_backend, primary),
                  window._set_backend_combo(window.firered_asr_backend, timeline),
                  window._set_backend_combo(window.qwen_asr_backend, review)]
        check(f'models set: {primary}/{timeline}/{review}', all(set_ok), set_ok)

    def open_picker(studio, tag):
        studio._open_recognition_sheet()
        settle(900)
        start = studio._recognition_controls['start']
        start.click()
        settle(900)
        from ..studio.audio_track_picker import AudioTrackPicker
        picker = window._modal_host._current_content
        check(f'{tag}: 识别字幕 opens 「选择要识别的音轨」', isinstance(picker, AudioTrackPicker),
              type(picker).__name__)
        return picker if isinstance(picker, AudioTrackPicker) else None

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

    def recognize(studio, picker, lanes, tag, timeout=900):
        for lane, box in picker.checks.items():
            box.setChecked(lane in lanes)
        settle(300)
        grab(window._modal_host.card, f'{tag}_picker')
        result['metrics'][f'{tag}_picker_texts'] = dict(count=picker.count_label.text(), note=picker.note.text(),
                                                        note_visible=picker.note.isVisible(),
                                                        impact=picker.impact.text())
        logs_before = newest_run_log()
        started = time.monotonic()
        picker.start_button.click()
        running = wait_for(lambda: window._run_in_progress or getattr(studio, '_recognition_running', False), 30)
        check(f'{tag}: recognition started', running)
        # Done = the run ended (success or not); a failure must not wait out the timeout.
        wait_for(lambda: not window._run_in_progress and not getattr(page(), '_recognition_running', False), timeout)
        finished = wait_for(lambda: '识别结果' in str(page().project_path or ''), 20)
        settle(2500)
        if not finished:
            label = getattr(page(), 'recognition_chip_label', None)
            result['metrics'][f'{tag}_failure_text'] = label.text() if label is not None else ''
            log_now = newest_run_log()
            if log_now:
                result['metrics'][f'{tag}_failure_events'] = [e for e in run_events(log_now)
                                                              if e.get('event') in {'queue_failed', 'media_failed',
                                                                                    'audio_lane_failed'}][-3:]
        result['metrics'][f'{tag}_seconds'] = round(time.monotonic() - started, 1)
        check(f'{tag}: recognition finished and the result opened in Studio', finished,
              dict(path=str(page().project_path), dialogs=result['dialogs'][-3:]))
        log = newest_run_log()
        events = run_events(log) if log and log != logs_before else []
        inputs = [e for e in events if e.get('event') == 'timeline_input_ready']
        result['metrics'][f'{tag}_inputs'] = [dict(lane=e.get('audio_lane'), ordinal=e.get('audio_stream_ordinal'),
                                                   index=e.get('audio_stream_index'), path=e.get('input_path'))
                                              for e in inputs]
        result['metrics'][f'{tag}_lane_events'] = [dict(event=e.get('event'), lane=e.get('audio_lane'),
                                                        label=e.get('label'), status=e.get('status'),
                                                        index=e.get('lane_index'), total=e.get('lane_total'))
                                                   for e in events if str(e.get('event', '')).startswith('audio_lane')]
        return inputs

    def input_matches(inputs, lane, own, others, tag):
        row = next((i for i in inputs if i.get('audio_lane') == lane), None)
        if not check(f'{tag}: {lane} got its own recognition input', row is not None and Path(row['input_path']).is_file(),
                     [i.get('audio_lane') for i in inputs]):
            return
        probe = _envelope(_pcm(row['input_path']))
        scores = {name: _best_correlation(probe, references[name]) for name in (own, *others)}
        result['metrics'][f'{tag}_{lane}_input_correlation'] = scores
        check(f'{tag}: the audio sent to the model for {lane} is {own}',
              scores[own] >= 0.8 and all(scores[own] > scores[o] + 0.3 for o in others), scores)

    def captions_by_source(studio):
        from ..recognition.audio_lane_results import SOURCES_KEY
        sources = studio.project.studio_state.get(SOURCES_KEY) or {}
        groups = {}
        for cue in studio.project.cues:
            lane = (sources.get(cue.speaker_id) or {}).get('lane_id', '(none)')
            groups.setdefault(lane, []).append(cue)
        return groups, sources

    def words_check(text, wanted, unwanted, tag):
        hits = [w for w in wanted if w.lower() in text.lower()]
        wrong = [w for w in unwanted if w.lower() in text.lower()]
        check(f'{tag}: captions say this track’s words', len(hits) >= max(1, len(wanted) // 2) and not wrong,
              dict(text=text[:200], hits=hits, wrong=wrong))

    def run_mp4():
        media = config['media']
        studio = open_project(config['projects']['mp4'])
        check('MP4: empty project opened', studio is not None and studio.project is not None)
        set_models()
        check('MP4: drop imports the file', drop(media['mp4']))
        lanes = [(t.id, t.stream_ordinal, t.muted, [c.stream_index for c in t.clips]) for t in studio.project.audio_tracks]
        result['metrics']['mp4_lanes'] = lanes
        check('MP4: both audio tracks are lanes under V1 (A1 plays, A2 muted)',
              lanes == [('A1', -1, False, [0]), ('A2', 1, True, [1])], lanes)
        rects = studio.timeline._audio_track_rects()
        check('MP4: both lanes are shown on the timeline', {'A1', 'A2'} <= set(rects)
              and all(rects[k].height() > 20 for k in ('A1', 'A2')), {k: [v.top(), v.height()] for k, v in rects.items()})
        check('MP4: each lane draws its own stream waveform', wait_for(lambda: waveforms_ready(studio, {0, 1}), 90))
        settle(800)
        try:
            scores = {f'A{stream + 1}': {name: _best_correlation(waveform_envelope(studio, stream), references[name])
                                          for name in ('track1', 'track2')} for stream in (0, 1)}
        except Exception as exc:  # noqa: BLE001
            scores = {'error': repr(exc)}
        result['metrics']['mp4_waveform_correlation'] = scores
        check('MP4: A1 waveform is track 1, A2 waveform is track 2',
              'error' not in scores and scores['A1']['track1'] > scores['A1']['track2'] + 0.3
              and scores['A2']['track2'] > scores['A2']['track1'] + 0.3, scores)
        offsets = {0: waveform_offset_ms(studio, 0, 'track1'), 1: waveform_offset_ms(studio, 1, 'track2')}
        check('MP4: each waveform sits where its speech is (1 s into the file)',
              all(abs(value - 1000) <= 60 for value in offsets.values()), offsets)
        from ..playback.audio_graph import capture_audio_graph
        heard = sorted({(s['track_id'], s['stream_index']) for s in capture_audio_graph(studio.project)['segments']})
        check('MP4: playback and export hear only the default track', heard == [('V1', 0)], heard)
        captions = {lane: str(studio.timeline._audio_lane_caption(t))
                    for lane, t in ((t.id, t) for t in studio.project.audio_tracks)}
        result['metrics']['mp4_lane_captions'] = captions
        check('MP4: lane headers name the tracks', '中文原音' in captions.get('A1', '') and '第二配音' in captions.get('A2', ''),
              captions)
        grab(window, 'mp4_1_window_two_lanes')
        grab(studio.timeline, 'mp4_1_timeline_two_lanes')

        # Picker, preview and cancel.
        picker = open_picker(studio, 'MP4')
        if picker is None:
            return
        rows = [(r['lane_id'], r['ordinal'], r['stream_index']) for r in picker.rows]
        check('MP4 picker: one row per track with its stream identity', rows == [('A1', 0, 1), ('A2', 1, 2)], rows)
        labels = [box.text() for box in picker.checks.values()]
        check('MP4 picker: rows read 音轨 N｜title｜language｜channels',
              labels == ['音轨 1｜中文原音｜中文｜立体声', '音轨 2｜第二配音｜中文｜立体声'], labels)
        check('MP4 picker: the file default track is preselected, not all',
              [lane for lane, box in picker.checks.items() if box.isChecked()] == ['A1'])
        grab(window._modal_host.card, 'mp4_2_picker_default')
        decoded = {}
        player = picker._ensure_player()
        original = player._start

        def capture(request_id, payload, original=original):
            decoded[player.cue_id] = bytes(payload)
            return original(request_id, payload)
        player._start = capture
        picker.preview_buttons['A2'].click()
        check('MP4 picker: preview of A2 starts', wait_for(lambda: player.cue_id == 'A2' and 'A2' in decoded, 30))
        grab(window._modal_host.card, 'mp4_3_picker_preview')
        if 'A2' in decoded:
            import numpy as np
            pcm = np.frombuffer(decoded['A2'], dtype='<i2').astype(np.float32).reshape(-1, 2).mean(axis=1)
            probe = _envelope(pcm, rate=48000)
            scores = {name: _best_correlation(probe, references[name]) for name in ('track1', 'track2')}
            result['metrics']['mp4_preview_correlation'] = scores
            check('MP4 picker: the preview plays track 2', scores['track2'] > scores['track1'] + 0.3, scores)
        picker.preview_buttons['A1'].click()
        check('MP4 picker: switching the preview stops A2 first', wait_for(lambda: player.cue_id == 'A1', 30),
              player.cue_id)
        picker.preview_buttons['A1'].click()
        check('MP4 picker: stop leaves nothing playing', wait_for(lambda: player.cue_id == '', 5))
        cache_root = Path(os.environ['LOCALAPPDATA']) / '2ByteASR' / 'cache'
        inputs_before = len(glob.glob(str(cache_root / '**' / 'timeline-inputs' / '*'), recursive=True))
        picker.cancel_button.click()
        settle(800)
        check('MP4 picker: 取消 returns to the sheet and starts nothing',
              window._modal_host._current_content is studio._recognition_sheet and not window._run_in_progress
              and len(glob.glob(str(cache_root / '**' / 'timeline-inputs' / '*'), recursive=True)) == inputs_before)
        window._modal_host.hide_content()
        settle(300)
        picker = open_picker(studio, 'MP4 empty choice')
        if picker is None:
            return
        for box in picker.checks.values():
            box.setChecked(False)
        settle(200)
        check('MP4 picker: no track ticked cannot start', not picker.start_button.isEnabled()
              and '至少勾选一条音轨' in picker.note.text(), picker.note.text())
        grab(window._modal_host.card, 'mp4_4_picker_none')

        # Track 2 only.
        inputs = recognize(studio, picker, {'A2'}, 'mp4_only_a2')
        input_matches(inputs, 'A2', 'track2', ('track1',), 'MP4 only A2')
        check('MP4 only A2: exactly one input, track 2 (ordinal 1, stream 2)',
              [(i.get('audio_lane'), i.get('audio_stream_ordinal'), i.get('audio_stream_index')) for i in inputs]
              == [('A2', 1, 2)], inputs)
        studio = page()
        groups, sources = captions_by_source(studio)
        text = ''.join(c.text for c in studio.project.cues)
        result['metrics']['mp4_only_a2_cues'] = [(c.start_ms, c.end_ms, c.speaker_id, c.text) for c in studio.project.cues]
        words_check(text, config['words']['track2'], config['words']['track1'], 'MP4 only A2')
        check('MP4 only A2: every caption belongs to an A2 speaker',
              set(groups) == {'A2'} and all(c.speaker_id.startswith('A2-') for c in studio.project.cues), list(groups))
        check('MP4 only A2: the speaker records stream identity',
              all(v.get('stream_index') == 2 and v.get('ordinal') == 1 for v in sources.values()), sources)
        from ..playback.audio_graph import capture_audio_graph
        heard = sorted({(s['track_id'], s['stream_index']) for s in capture_audio_graph(studio.project)['segments']})
        check('MP4 only A2: export routing is unchanged (A1 only)', heard == [('V1', 0)], heard)
        grab(window, 'mp4_5_result_only_a2')

        # Tracks 1 and 2 together on the result project.
        a2_count = len(studio.project.cues)
        picker = open_picker(studio, 'MP4 both')
        if picker is None:
            return
        check('MP4 both: the project remembers the previous choice (A2)',
              [lane for lane, box in picker.checks.items() if box.isChecked()] == ['A2'])
        picker.checks['A1'].setChecked(True)
        settle(200)
        check('MP4 both: two ticked tracks explain separate recognition',
              picker.note.isVisible() and picker.note.text() == '将分别识别所选音轨，并按来源保留字幕结果。'
              and str(a2_count) in picker.impact.text(), dict(note=picker.note.text(), impact=picker.impact.text()))
        inputs = recognize(studio, picker, {'A1', 'A2'}, 'mp4_both')
        input_matches(inputs, 'A1', 'track1', ('track2',), 'MP4 both')
        input_matches(inputs, 'A2', 'track2', ('track1',), 'MP4 both')
        lane_events = result['metrics'].get('mp4_both_lane_events') or []
        check('MP4 both: progress names each track in turn (1/2, 2/2)',
              [(e['index'], e['total']) for e in lane_events if e['event'] == 'audio_lane_started'] == [(1, 2), (2, 2)],
              lane_events)
        studio = page()
        groups, sources = captions_by_source(studio)
        result['metrics']['mp4_both_cues'] = [(c.start_ms, c.end_ms, c.speaker_id, c.text) for c in studio.project.cues]
        check('MP4 both: captions are grouped by source track', set(groups) == {'A1', 'A2'}, list(groups))
        words_check(''.join(c.text for c in groups.get('A1', [])), config['words']['track1'], config['words']['track2'],
                    'MP4 both A1')
        words_check(''.join(c.text for c in groups.get('A2', [])), config['words']['track2'], config['words']['track1'],
                    'MP4 both A2')
        check('MP4 both: the earlier A2 captions were replaced, not doubled',
              abs(len(groups.get('A2', [])) - a2_count) <= 1, dict(before=a2_count, after=len(groups.get('A2', []))))
        a1_speakers = {c.speaker_id for c in groups.get('A1', [])}
        a2_speakers = {c.speaker_id for c in groups.get('A2', [])}
        check('MP4 both: speaker 1 of one track is not merged with the other track',
              a1_speakers and a2_speakers and not (a1_speakers & a2_speakers), [sorted(a1_speakers), sorted(a2_speakers)])
        grab(window, 'mp4_6_result_both')
        grab(studio.timeline, 'mp4_6_timeline_both')
        result['metrics']['mp4_result_path'] = str(studio.project_path)
        return str(studio.project_path)

    def run_mkv():
        media = config['media']
        studio = open_project(config['projects']['mkv'])
        check('MKV: drop imports the file', drop(media['mkv']))
        lanes = [(t.id, t.stream_ordinal, [c.stream_index for c in t.clips]) for t in studio.project.audio_tracks]
        check('MKV: three audio streams → A1, A2, A3 (subtitle stream between them ignored)',
              lanes == [('A1', -1, [0]), ('A2', 1, [1]), ('A3', 2, [2])], lanes)
        wait_for(lambda: waveforms_ready(studio, {0, 1, 2}), 90)
        settle(600)
        late = waveform_offset_ms(studio, 1, 'track2')
        check('MKV: the dub that starts 3 s late is drawn from 3 s, not earlier or later',
              abs(late - 3000) <= 60, dict(offset=late, expected=3000))
        grab(studio.timeline, 'mkv_1_timeline_three_lanes')
        studio.timeline.set_stream_lanes_collapsed('V1', True)
        settle(400)
        check('MKV: folding hides A2/A3 and keeps A1', set(studio.timeline._audio_track_rects()) == {'A1'},
              list(studio.timeline._audio_track_rects()))
        grab(studio.timeline, 'mkv_2_timeline_folded')
        studio.timeline.set_stream_lanes_collapsed('V1', False)
        settle(300)
        # Ripple-delete the first 2 s: the dub (3 s late) now speaks at about 1.2 s.
        from ..timeline.studio_clip_edit import playhead_edit_command
        studio.undo_stack.push(playhead_edit_command(studio.project, 'ripple_start', 2000, page=studio))
        settle(800)
        studio.save()
        clip = studio.project.video_tracks[0].clips[0]
        check('MKV: 2 s ripple cut applied', (clip.source_in_ms, clip.timeline_in_ms) == (2000, 0),
              (clip.source_in_ms, clip.timeline_in_ms))
        picker = open_picker(studio, 'MKV')
        if picker is None:
            return
        rows = [(r['lane_id'], r['ordinal'], r['stream_index']) for r in picker.rows]
        check('MKV picker: absolute stream index skips the subtitle stream', rows == [('A1', 0, 1), ('A2', 1, 3), ('A3', 2, 4)],
              rows)
        labels = [box.text() for box in picker.checks.values()]
        check('MKV picker: an untitled mono track reads 语言未标示｜单声道', labels[2] == '音轨 3｜语言未标示｜单声道', labels)
        inputs = recognize(studio, picker, {'A2'}, 'mkv_a2_after_cut')
        input_matches(inputs, 'A2', 'track2', ('track1', 'track3'), 'MKV A2')
        check('MKV A2: the input names stream index 3', [i.get('audio_stream_index') for i in inputs] == [3], inputs)
        studio = page()
        cues = sorted(studio.project.cues, key=lambda c: c.start_ms)
        result['metrics']['mkv_cues'] = [(c.start_ms, c.end_ms, c.speaker_id, c.text) for c in cues]
        words_check(''.join(c.text for c in cues), config['words']['track2'], config['words']['track1'], 'MKV A2')
        expected = config['track2_speech_start_ms'] + 3000 - 2000
        check('MKV A2: first caption sits at the edited project time of the late dub',
              bool(cues) and abs(cues[0].start_ms - expected) <= 450, dict(first=cues[0].start_ms if cues else None,
                                                                            expected=expected))
        grab(window, 'mkv_3_result_a2_after_cut')
        return str(studio.project_path)

    def run_reopen(path):
        studio = open_project(path)
        lanes = [(t.id, t.stream_ordinal) for t in studio.project.audio_tracks]
        from ..recognition.audio_lane_results import SOURCES_KEY
        sources = studio.project.studio_state.get(SOURCES_KEY) or {}
        settle(1500)
        lanes_after = [(t.id, t.stream_ordinal) for t in studio.project.audio_tracks]
        check('Reopen: lanes and their streams are kept, nothing added twice',
              lanes == lanes_after == [('A1', -1), ('A2', 1)], [lanes, lanes_after])
        check('Reopen: every caption speaker still names its source track',
              all(cue.speaker_id in sources for cue in studio.project.cues), sorted(sources))

    def run_single_and_silent():
        media = config['media']
        from ..studio import studio_media_flow
        for name in ('stereo', 'surround'):
            studio = open_project(config['projects'][name])
            drop(media[name])
            lanes = [(t.id, t.stream_ordinal) for t in studio.project.audio_tracks]
            check(f'{name}: one source track, channels not split', lanes == [('A1', -1)], lanes)
            check(f'{name}: 识别字幕 keeps the old flow without a picker',
                  not studio._recognition_needs_track_picker(studio.project))
        studio = open_project(config['projects']['silent'])
        drop(media['silent'])
        shown = []
        original = studio_media_flow.studio_message_box
        studio_media_flow.studio_message_box = lambda _parent, _icon, title, text, *a, **k: shown.append((str(title), str(text)))
        try:
            studio._open_recognition_sheet()
            settle(400)
        finally:
            studio_media_flow.studio_message_box = original
        check('No audio: says 此素材没有可识别的音轨 and opens nothing',
              shown and '此素材没有可识别的音轨' in shown[0][1] and not window._modal_host.isVisible(), shown)

    def run_all():
        try:
            for dialog in [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]:
                QDialog.done(dialog, 0)
            window.showNormal()
            window.resize(1500, 940)
            settle(800)
            for step in (run_mp4, run_mkv):
                try:
                    path = step()
                    if step is run_mp4 and path:
                        run_reopen(path)
                except Exception:  # noqa: BLE001
                    result['errors'].append(traceback.format_exc())
                save_result()
            run_single_and_silent()
        except Exception:  # noqa: BLE001
            result['errors'].append(traceback.format_exc())
        watchdog.stop()
        result['passed'] = bool(result['checks']) and all(c['passed'] for c in result['checks']) and not result['errors']
        save_result()
        studio = page()
        if studio is not None and getattr(studio, 'project', None) is not None:
            try:
                studio.save()
            except Exception as exc:  # noqa: BLE001
                result['errors'].append(f'save before close: {exc!r}')
        window.close()
        QTimer.singleShot(500, app.quit)

    def shutdown():
        result['gui_shutdown'] = True
        save_result()

    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(2500, run_all)
