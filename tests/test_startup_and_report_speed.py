"""2026-11-19: the report window and export are fast and say the same as before; the launch picture
is used only while it is true; qtawesome loads two icon fonts; rounded windows keep their shadow."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from twobyteasr.diagnostics import support_bundle
from twobyteasr.diagnostics.event_log import Sanitizer


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ collecting the records
def _stamp(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(timespec='milliseconds')


def _session(root, name, status, rows):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / 'session.json').write_text(json.dumps({'session_id': name, 'status': status, 'pid': 1,
                                                     'started': _stamp(600), 'losses': {'rotated_files': 1}}), 'utf8')
    lines = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, bytes):
            lines.append(row)
            continue
        base = {'format_version': 1, 'time': _stamp(5), 'session_id': name, 'pid': 1, 'project_id': None,
                'task_id': None, 'module': 'test', 'result': 'observed', 'event_name': 'test.event', 'level': 'INFO',
                'message': 'm', 'sequence': index}
        base.update(row)
        lines.append((json.dumps(base, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf8'))
    (folder / 'events.jsonl').write_bytes(b''.join(lines))
    return folder


@pytest.fixture
def records(tmp_path):
    root = tmp_path / 'diagnostic-sessions'
    project = 'project-0123456789abcdef'
    _session(root, 'session-old', 'clean', [
        {'time': _stamp(300), 'project_id': project, 'task_id': 'task-a', 'event_name': 'project.loaded'},
        {'time': _stamp(299), 'task_id': 'task-a', 'event_name': 'background.result', 'media_path': 'C:\\Users\\someone\\a.mp4'},
        {'time': _stamp(298), 'event_name': 'other.project', 'project_id': 'project-ffffffffffffffff'},
        {'time': _stamp(297), 'result': 0},                              # a record the scrub refuses
        b'{"not finished": ',                                            # a line cut off by a crash
    ])
    _session(root, 'session-previous', 'not_cleanly_ended', [
        {'time': _stamp(120), 'event_name': 'last.words', 'sequence': index} for index in range(1, 6)])
    _session(root, 'session-now', 'clean', [
        {'time': _stamp(4), 'project_id': project, 'event_name': 'operation.start', 'api_key': 'sk-abcdef1234567'},
        {'time': _stamp(3), 'project_id': project, 'event_name': 'operation.end', 'error': 'secret words'},
        {'time': _stamp(40), 'event_name': 'too.old'},
    ])
    old = time.time() - 4 * 3600
    import os
    os.utime(root / 'session-old' / 'events.jsonl', (old, old))
    support_bundle.forget_scans()
    yield root
    support_bundle.forget_scans()


def _names(rows):
    return [row['event_name'] for row in rows]


def test_only_what_is_kept_is_scrubbed_and_the_result_is_the_usual_one(records, monkeypatch):
    scrubbed = []
    original = Sanitizer.clean

    def counting(self, value, key='', depth=0):
        if depth == 0 and isinstance(value, dict) and 'event_name' in value:
            scrubbed.append(value['event_name'])
        return original(self, value, key, depth)
    monkeypatch.setattr(Sanitizer, 'clean', counting)
    data = support_bundle.collect(records)
    assert _names(data['events']) == ['operation.start', 'operation.end']
    assert data['events'][0]['api_key'] == '<omitted>' and data['events'][1]['error'] == '<omitted>'
    # This project's and its task's records from the old session, and the unclean session's last ones.
    context = data['context_events']
    assert sorted(_names(context)) == ['background.result'] + ['last.words'] * 5 + ['project.loaded']
    assert all(row['context_only'] for row in context)
    assert next(row for row in context if row['event_name'] == 'background.result')['media_path'].startswith('path-')
    assert data['context_count'] == len(context)
    # Not scrubbed: the other project's record and the one outside the range.
    assert 'other.project' not in scrubbed and 'too.old' not in scrubbed
    # Unreadable records are reported whether or not they were in the range.
    assert {(row['session'], row['line']) for row in data['missing'] if row.get('reason') == 'invalid_or_partial_line'} \
        == {('session-old', 4), ('session-old', 5)}


def test_the_viewer_reads_only_recent_sessions_and_counts_instead_of_returning_background(records):
    full = support_bundle.collect(records)
    viewer = support_bundle.collect(records, context_records=False, recent_only=True)
    assert viewer['events'] == full['events']
    assert [row for row in viewer['context_events'] if not row.get('previous_abnormal_tail')] == []
    assert len([row for row in viewer['context_events'] if row.get('previous_abnormal_tail')]) == 5
    assert viewer['scanned_bytes'] < full['scanned_bytes']             # session-old was not opened
    assert not [row for row in viewer['missing'] if row.get('session') == 'session-old']
    counted = support_bundle.collect(records, context_records=False)
    assert counted['context_count'] == full['context_count'] and len(counted['context_events']) == 5


def test_a_kept_scan_gives_the_same_result_and_is_read_again_when_the_session_changed(records, monkeypatch):
    first = support_bundle.collect(records, reuse_scans=True)
    reads = []
    original = support_bundle._session_files
    monkeypatch.setattr(support_bundle, '_session_files', lambda directory, missing: reads.append(directory.name) or original(directory, missing))
    second = support_bundle.collect(records, reuse_scans=True)
    assert reads == []                                                  # every session came from its kept scan
    for part in ('events', 'context_events', 'sessions', 'missing'):
        assert second[part] == first[part]
    second['events'][0]['event_name'] = 'changed by the caller'        # a caller's change stays the caller's
    assert _names(support_bundle.collect(records, reuse_scans=True)['events'])[0] == 'operation.start'
    with (records / 'session-now' / 'events.jsonl').open('ab') as stream:
        row = {'format_version': 1, 'time': _stamp(1), 'session_id': 'session-now', 'pid': 1, 'result': 'observed',
               'event_name': 'just.now', 'level': 'INFO', 'message': 'm', 'sequence': 9}
        stream.write((json.dumps(row) + '\n').encode('utf8'))
    third = support_bundle.collect(records, reuse_scans=True)
    assert reads == ['session-now'] and _names(third['events'])[-1] == 'just.now'
    support_bundle.forget_scans()
    assert support_bundle._SCANS == {}


def test_the_scrub_remembers_names_and_short_texts_without_mixing_their_meaning():
    scrub = Sanitizer(b'0' * 32)
    row = {'media_path': 'C:\\Users\\someone\\clip.mp4', 'note': 'C:\\Users\\someone\\clip.mp4', 'api-key': 'value',
           'item_count': 3, 'level': 'INFO', 'project_id': 'my project', 'headers': {'Content-Type': 'a', 'Cookie': 'b'}}
    first = scrub.clean(row)
    assert first == scrub.clean(row) == Sanitizer(b'0' * 32).clean(row)
    assert first['media_path'].startswith('path-') and first['media_path'].endswith('.mp4')
    assert first['note'].startswith('path-') and first['api-key'] == '<omitted>' and first['item_count'] == 3
    assert first['project_id'].startswith('project-')
    assert first['headers'] == {'Content-Type': 'a', 'Cookie': '<omitted>'}
    # The same short text under a private name and a plain one, in either order.
    assert scrub.clean('INFO', 'password') == '<omitted>' and scrub.clean('INFO', 'level') == 'INFO'
    assert scrub.string('sk-abcdef1234567') == scrub.string('sk-abcdef1234567') == '<credential>'


# ------------------------------------------------------------------ the launch picture
def test_the_launch_picture_is_used_only_while_it_is_true(app, tmp_path, monkeypatch):
    from twobyteasr.app import launch_picture
    monkeypatch.setattr(launch_picture, '_directory', lambda: tmp_path)
    monkeypatch.setenv('TWOBYTEASR_LAUNCH_PICTURE', '1')
    assert launch_picture.read() is None and launch_picture.usable(None, app) == ''
    meta = dict(format=launch_picture.FORMAT, program=launch_picture.program_stamp(),
                screens=launch_picture.screens_signature(app), client=[100, 80, 1320, 880], scale=1.0, maximized=False,
                next_page='recognition', picture=True, background='#19151c', foreground='#a69ba6',
                theme='grape', language='zh', zoom=100)
    (tmp_path / 'meta.json').write_text(json.dumps(meta), 'utf8')
    assert launch_picture.usable(launch_picture.read(), app) == 'plain'        # no picture file yet
    (tmp_path / 'home.bmp').write_bytes(b'BM')
    assert launch_picture.usable(meta, app) == 'picture'
    assert launch_picture.usable(meta, app, arguments=['clip.mp4']) == ''       # opened with a file
    assert launch_picture.usable(dict(meta, next_page='project_library'), app) == ''
    # 2026-11-19 (user picked option A): a picture survives an update; the real window fades in over it.
    assert launch_picture.usable(dict(meta, program='another build'), app) == 'picture'
    assert launch_picture.usable(dict(meta, screens=[[0, 0, 800, 600, 2.0]]), app) == ''
    assert launch_picture.usable(dict(meta, client=[0, 0, 10, 10]), app) == ''
    assert launch_picture.usable(dict(meta, picture=False, background=''), app) == ''
    (tmp_path / 'meta.json').write_text(json.dumps(dict(meta, format=1)), 'utf8')
    assert launch_picture.read() is None                                       # an older layout of the file


def test_the_launch_picture_stays_out_of_audits_and_tests(monkeypatch):
    from twobyteasr.app import launch_picture
    monkeypatch.delenv('TWOBYTEASR_LAUNCH_PICTURE', raising=False)
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT', 'x')
    assert not launch_picture.enabled()
    monkeypatch.setenv('TWOBYTEASR_LAUNCH_PICTURE', '1')
    assert launch_picture.enabled()
    monkeypatch.setenv('TWOBYTEASR_LAUNCH_PICTURE', '0')
    assert not launch_picture.enabled()
    launch_picture.dismiss()                                                    # nothing shown: no error
    assert not launch_picture.showing()


# ------------------------------------------------------------------ icon fonts
def test_two_icon_fonts_at_once_and_the_others_when_asked(app):
    import qtawesome as qta
    from twobyteasr.design import icon_fonts
    kept = qta._resource.get('iconic')
    qta._resource['iconic'] = None
    try:
        assert icon_fonts.install()
        assert sorted(qta._instance().fontids) == ['fa5s', 'ph']
        assert not qta.icon('fa5s.check', color='#ffffff').isNull() and not qta.icon('ph.gear').isNull()
        assert not icon_fonts.install()                                 # qtawesome is up: left alone
        assert not qta.icon('mdi6.account').isNull() and 'mdi6' in qta._instance().fontids
        with pytest.raises(Exception, match='Invalid font prefix'):
            qta.icon('nosuch.thing')
    finally:
        if kept is not None:                # else ours stays, as in the app (its fonts are loaded)
            qta._resource['iconic'] = kept


# ------------------------------------------------------------------ the rounded window's shadow
def test_the_shadow_is_drawn_once_per_size(app):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from twobyteasr.app import rounded_window
    from twobyteasr.app.rounded_window import RoundedWindow
    rounded_window._SHADOWS.clear()
    window = QWidget()
    content = QWidget(window)
    QVBoxLayout(window).addWidget(content)
    window.resize(420, 300)
    rounded = RoundedWindow(window, content)
    drawn = []
    original = rounded._draw_shadow
    rounded._draw_shadow = lambda painter, rect: drawn.append(1) or original(painter, rect)
    image = QImage(420, 300, QImage.Format.Format_ARGB32_Premultiplied)
    for _ in range(3):
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        rounded._shadow_layers(painter, QRectF(rounded.content_rect()))
        painter.end()
    assert len(drawn) == 1
    margin = rounded.margin()
    assert image.pixelColor(margin // 2, 150).alpha() > 0 and image.pixelColor(0, 0).alpha() < image.pixelColor(margin - 1, 150).alpha()
    window.resize(460, 300)
    painter = QPainter(image)
    rounded._shadow_layers(painter, QRectF(rounded.content_rect()))
    painter.end()
    assert len(drawn) == 2
    window.close()


def test_a_window_opened_again_reuses_the_shadow_of_its_size(app):
    """2026-11-19: a dialog opened again (a new window of the same size) does not draw its shadow
    layers again inside its first paint (40-117 ms under its opening motion)."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from twobyteasr.app import rounded_window
    from twobyteasr.app.rounded_window import RoundedWindow
    rounded_window._SHADOWS.clear()
    drawn, windows, images = [], [], []
    for _ in range(2):
        window = QWidget()
        content = QWidget(window)
        QVBoxLayout(window).addWidget(content)
        window.resize(436, 312)
        rounded = RoundedWindow(window, content)
        original = rounded._draw_shadow
        rounded._draw_shadow = lambda painter, rect, original=original: drawn.append(1) or original(painter, rect)
        image = QImage(436, 312, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        rounded._shadow_layers(painter, QRectF(rounded.content_rect()))
        painter.end()
        windows.append(window)
        images.append(image)
    assert len(drawn) == 1 and images[0] == images[1]
    for window in windows:
        window.close()
