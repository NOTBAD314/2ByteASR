"""2026-11-02 loading pages: poster face for projects, bunny + recent fan for the library."""
from __future__ import annotations

import pytest

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def _entries(tmp_path, count=6):
    rows = []
    for index in range(count):
        project = tmp_path / f'p{index}' / 'project.2byteproj'
        project.parent.mkdir(parents=True, exist_ok=True)
        project.write_text('{}', encoding='utf-8')
        rows.append(dict(path=str(project), name=f'工程 {index}', cover='', count=100 + index,
                         edited='昨天', duration_ms=2538000))
    return rows


def _session(app, entries):
    from twobyteasr.studio.studio_loading import StudioLoadingSession
    host = QWidget()
    host.resize(1400, 860)
    session = StudioLoadingSession(host)
    session.recent_entries = entries
    return host, session


def test_library_steps_follow_the_real_build_reports():
    from twobyteasr.studio.studio_loading import LIBRARY_TASKS, library_step_state
    assert library_step_state(set(), '') == (set(), LIBRARY_TASKS[0])
    done, current = library_step_state(set(), '字幕编辑区')
    assert done == {LIBRARY_TASKS[0]} and current == LIBRARY_TASKS[1]
    done, current = library_step_state(set(), '时间轴工具栏')
    assert done == set(LIBRARY_TASKS[:2]) and current == LIBRARY_TASKS[2]
    assert library_step_state({'创建工作台界面'}, '') == (set(LIBRARY_TASKS[:4]), LIBRARY_TASKS[4])
    assert library_step_state({'创建工作台界面', '首屏绘制'}, '') == (set(LIBRARY_TASKS), '')


def test_project_poster_uses_the_library_record_and_real_stage_times(app, tmp_path):
    entries = _entries(tmp_path)
    host, session = _session(app, entries)
    card = session.view.card
    session.begin(entries[2]['path'])
    view = session.view
    assert not view.library_mode and view.faces.currentWidget() is view.project_face
    assert view.project_name.text() == '工程 2'
    chips = [chip.text() for chip in view.meta_chips if not chip.isHidden()]
    assert chips[0].startswith('102') and '42:18' in chips
    assert view.cover.right_chip == '42:18' and view.cover.left_chip
    assert view.bar.maximum() == 7
    session.mark('创建工作台界面')
    session.mark('读取工程')
    session.stage('准备播放器')
    assert view.bar.value() == 2
    assert set(view.steps_view.times) == {'创建工作台界面', '读取工程'}
    assert view.cover.line and view.steps_view.current == '准备播放器'
    session.fail('准备播放器', 'missing fixture')
    assert view.card is card and view.cover.failed and view.bar.failed
    assert view.eyebrow.property('state') == 'failed' and view.perch.mood == 'sad'
    assert view.retry.isVisible() or not view.isVisible()
    assert 'missing fixture' in view.label.text()
    host.deleteLater()


def test_library_face_picks_a_recent_project_only_when_armed(app, tmp_path):
    entries = _entries(tmp_path)
    host, session = _session(app, entries)
    card = session.view.card
    session.begin('')
    view = session.view
    assert view.library_mode and view.faces.currentWidget() is view.library_face
    assert view.card is card
    assert len(view.fan.entries) == 5
    assert session.picked_project() == ''
    view.fan.set_armed(True, 3)
    view._sync_pick()
    assert session.picked_project() == entries[3]['path']
    assert view.pick_toggle.isChecked() and '工程 3' in view.pick_toggle.text()
    view.pick_toggle.setChecked(False)
    assert session.picked_project() == ''
    session.stage('创建工作台界面', '时间轴工具栏')
    assert view.library_steps.current == '铺时间轴'
    session.fail('创建工作台界面', 'boom')
    assert view.library_steps.failed == '铺时间轴' and view.library_bunny.mood == 'sad'
    assert session.picked_project() == ''
    host.deleteLater()


def test_clicking_a_fanned_card_arms_it(app, tmp_path):
    entries = _entries(tmp_path, 3)
    host, session = _session(app, entries)
    session.begin('')
    fan = session.view.fan
    fan.resize(700, 460)
    index, transform = fan._transforms()[-1]  # the card painted on top
    width, height = fan._card_size()
    centre = transform.map(QPoint(int(width / 2), int(height / 2)))
    from PySide6.QtTest import QTest
    QTest.mouseClick(fan, Qt.MouseButton.LeftButton, pos=centre)
    assert fan.armed and fan.selected == index
    assert session.picked_project() == entries[index]['path']
    host.deleteLater()


def test_library_without_recent_projects_shows_the_hint(app):
    host, session = _session(app, [])
    session.begin('')
    view = session.view
    assert view.fan.isHidden() and not view.recent_empty.isHidden() and view.pick_toggle.isHidden()
    assert session.picked_project() == ''
    host.deleteLater()


def test_bunny_assets_load_and_missing_assets_degrade(app, tmp_path, monkeypatch):
    from twobyteasr.design import bunny_mascot
    bunny_mascot.load_rig.cache_clear()
    rig = bunny_mascot.load_rig()
    assert rig is not None and len(rig[0]['layers']) == 26
    roles = {layer['role'] for layer in rig[0]['layers']}
    assert {'eyes', 'blink', 'mouthOpen', 'mouthClosed'} <= roles
    widget = bunny_mascot.BunnyMascot(height=120)
    assert widget.available
    widget.set_mood('sad')
    widget.talk(.5)
    assert not widget.grab().isNull()
    assert not bunny_mascot.bunny_face_pixmap(32).isNull()
    monkeypatch.setattr(bunny_mascot, 'mascot_root', lambda: tmp_path / 'missing')
    bunny_mascot.load_rig.cache_clear()
    try:
        empty = bunny_mascot.BunnyMascot(height=120)
        assert not empty.available
        empty.grab()  # paints nothing, raises nothing
    finally:
        monkeypatch.undo()
        bunny_mascot.load_rig.cache_clear()
