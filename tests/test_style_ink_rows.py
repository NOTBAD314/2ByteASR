"""Style tab 外观: ink-wash wells, a switch on every row, the shadow stage (2026-11-13)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDoubleSpinBox

from tests.test_studio_background_toggle import _shown_style_tab
from tests.test_studio_style_controller import _app, _finish, _page
from twobyteasr.caption_style.style_resolution import resolve_cue_visual
from twobyteasr.caption_style.studio_style_widgets import InkCapsule
from twobyteasr.design import ink_wash
from twobyteasr.design.ink_controls import PillSlider, ShadowStage


def _style(page, cue_id="a"):
    return resolve_cue_visual(page.session.project, page.session._cue_lookup[cue_id]).style


def test_wash_is_dense_at_the_brush_point_and_thins_to_the_right():
    alpha = ink_wash.wash_alpha(200, 38, level=1.0, t=2.0, seed=11.0)
    assert alpha.shape == (19, 100)
    assert alpha[:, :6].min() > 0.7  # the pool of full colour
    assert alpha[:, 30:50].mean() > alpha[:, 75:95].mean() > 0.0
    assert alpha[:, -1].max() < 0.02  # never a cut line at the well's right edge
    assert alpha.max() <= 0.93


def test_switched_off_wash_is_only_the_drop_at_the_left():
    alpha = ink_wash.wash_alpha(200, 38, level=0.0, t=2.0, seed=11.0)
    assert alpha[:, :6].min() > 0.7
    assert alpha[:, 25:].max() < 0.02


def test_black_ink_thins_to_a_cool_tone_and_coloured_ink_keeps_its_hue():
    # 2026-11-13 (user): thinned black read as dirt on the warm paper.
    def pale_pixels(color):
        image = ink_wash.wash_image(200, 38, [QColor(color)], level=1.0, t=2.0, seed=11.0)
        found = []
        for x in range(image.width()):
            pixel = image.pixelColor(x, image.height() // 2)
            if 40 < pixel.alpha() < 120:
                found.append(pixel)
        return found

    black = pale_pixels("#000000")
    assert black and all(p.blue() > p.red() + 8 for p in black)
    red = pale_pixels("#E8473C")
    assert red and all(p.red() > p.blue() + 60 for p in red)
    assert ink_wash.neutrality(QColor("#000000")) > 0.95
    assert ink_wash.neutrality(QColor("#E8473C")) == 0.0
    assert ink_wash.neutrality(QColor("#FFFFFF")) == 0.0


def test_every_appearance_row_has_a_capsule_and_a_switch(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    x = _shown_style_tab(page, app)
    rows = page._appearance_rows
    switches = [page.style_fill_switch, page.style_outline_switch, page.style_background,
                page.style_shadow_switch, page.style_glow]
    assert all(switch.isVisibleTo(page) and switch.objectName() == "styleSwitch" for switch in switches)
    assert len({x(switch) for switch in switches}) == 1
    wells = [page.style_fill_button, page.style_outline_button, page.style_back_button,
             page.style_shadow_button, page.style_glow_button]
    for row, well in zip(rows.values(), wells):
        assert isinstance(row.capsule, InkCapsule) and row.capsule.isAncestorOf(well)
        assert well._ink_role
    # Capsules start in the control column and end together, before the switches.
    assert len({x(row.capsule) for row in rows.values()}) == 1
    assert len({x(row.capsule) + row.capsule.width() for row in rows.values()}) == 1
    # The number of a row sits inside its capsule: width, opacity, radius.
    for name, spin in (("outline", page.style_outline_width), ("shadow", page.style_shadow_opacity),
                       ("glow", page.style_glow_strength)):
        assert rows[name].capsule.isAncestorOf(spin) and spin.isVisibleTo(page)
    assert page.style_shadow_opacity.suffix() == " %"
    _finish(page)


def test_fill_switch_makes_the_fill_transparent_and_brings_it_back(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    _shown_style_tab(page, app)
    page._set_style_color(page.style_fill_color, "#FF3366CC")
    assert page.style_fill_switch.isChecked() and page.style_fill_button._enabled_state
    steps = page.undo_stack.count()

    page.style_fill_switch.click()
    app.processEvents()
    assert QColor(_style(page).primary_color).alpha() == 0
    assert QColor(_style(page).primary_color).name() == "#3366cc"  # the colour itself is kept
    assert page.undo_stack.count() == steps + 1
    assert not page.style_fill_switch.isChecked() and not page.style_fill_button._enabled_state

    page.style_fill_switch.click()
    app.processEvents()
    assert QColor(_style(page).primary_color).alpha() == 255
    assert QColor(_style(page).primary_color).name() == "#3366cc"
    assert page.style_fill_switch.isChecked() and page.style_fill_button._enabled_state

    # A style that arrives transparent shows as off, and switches on to opaque.
    page.style_fill_switch.click()
    app.processEvents()
    page._fill_before_off = None
    page._load_style_inspector()
    assert not page.style_fill_switch.isChecked()
    page.style_fill_switch.click()
    app.processEvents()
    assert QColor(_style(page).primary_color).alpha() == 255
    _finish(page)


def test_outline_switch_removes_the_stroke_and_restores_its_width(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    _shown_style_tab(page, app)
    page.style_outline_width.setValue(4.5)
    page._commit_style_now()
    assert page.style_outline_switch.isChecked() and page.style_outline_button._enabled_state

    page.style_outline_switch.click()
    app.processEvents()
    assert _style(page).outline_width == 0
    assert not page.style_outline_switch.isChecked() and not page.style_outline_button._enabled_state

    page.style_outline_switch.click()
    app.processEvents()
    assert _style(page).outline_width == 4.5
    assert page.style_outline_switch.isChecked() and page.style_outline_button._enabled_state

    # Width typed down to 0 is the same off state.
    page.style_outline_width.setValue(0)
    page._commit_style_now()
    assert not page.style_outline_switch.isChecked()
    _finish(page)


def test_shadow_switch_is_on_the_row_and_follows_opacity(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    _shown_style_tab(page, app)
    page.style_shadow_opacity.setValue(48)
    page.style_shadow_distance.setValue(6)
    page._commit_style_now()
    assert page.style_shadow_switch.isChecked() and page.style_shadow_button._enabled_state

    page.style_shadow_switch.click()
    app.processEvents()
    assert page.style_shadow_opacity.value() == 0
    assert not page.style_shadow_button._enabled_state

    page.style_shadow_switch.click()
    app.processEvents()
    assert page.style_shadow_opacity.value() == 48
    assert page.style_shadow_switch.isChecked() and page.style_shadow_button._enabled_state
    _finish(page)


def test_shadow_editor_is_the_stage_over_four_sliders(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    _shown_style_tab(page, app)
    row = page._appearance_rows["shadow"]
    row.set_expanded(True)
    app.processEvents()
    stage = page.style_shadow_angle
    assert isinstance(stage, ShadowStage) and stage.isVisibleTo(page)
    sliders = page.style_shadow_sliders
    assert set(sliders) == {"distance", "blur", "spread", "opacity"}

    def pos(item):
        return item.mapTo(row, QPoint(0, 0))

    assert all(isinstance(s, PillSlider) and s.isVisibleTo(page) for s in sliders.values())
    assert len({pos(s).x() for s in sliders.values()}) == 2 and len({pos(s).y() for s in sliders.values()}) == 2
    assert all(pos(s).y() >= pos(stage).y() + stage.height() for s in sliders.values())
    # The spin boxes stay the value holders; only the opacity one is on screen (in the capsule).
    for name in ("distance", "blur", "spread"):
        assert not getattr(page, "style_shadow_" + name).isVisibleTo(page)
    # Stage and distance follow each other.
    page.style_shadow_distance.setValue(11)
    assert stage.distance() == 11
    page.style_shadow_offset_x.setValue(0)
    page.style_shadow_offset_y.setValue(7)
    assert round(stage.angle()) == 90 and stage.distance() == 7
    _finish(page)


def test_dragging_the_stage_sets_direction_and_distance_as_one_scrub():
    app = _app()
    stage = ShadowStage()
    stage.resize(280, 74)
    stage.show()
    events = []
    stage.scrubStarted.connect(lambda: events.append("start"))
    stage.scrubFinished.connect(lambda: events.append("finish"))
    stage.angleChanged.connect(lambda value: events.append(("angle", round(value))))
    stage.distanceChanged.connect(lambda value: events.append(("distance", value)))
    centre = QPoint(140, 37)
    unit = stage.PIXELS_PER_UNIT
    QTest.mousePress(stage, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     centre + QPoint(round(10 * unit), 0))
    QTest.mouseRelease(stage, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       centre + QPoint(0, round(10 * unit)))
    app.processEvents()
    assert events[0] == "start" and events[-1] == "finish"
    assert round(stage.angle()) == 90 and stage.distance() == 10
    assert ("angle", 0) in events and ("distance", 10.0) in events
    # Programmatic values only show; they do not come back as edits.
    events.clear()
    stage.setDistance(22)
    assert stage.distance() == 22 and events == []
    stage.grab()  # paints without errors
    stage.deleteLater()


def test_pill_slider_drives_its_spin_box():
    app = _app()
    spin = QDoubleSpinBox()
    spin.setRange(0, 40)
    spin.setDecimals(0)
    slider = PillSlider(spin, "模糊", "px")
    slider.resize(160, slider.HEIGHT)
    slider.show()
    events = []
    slider.scrubStarted.connect(lambda: events.append("start"))
    slider.scrubFinished.connect(lambda: events.append("finish"))
    inset = slider.HEIGHT // 2
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(inset, 15))
    assert spin.value() == 0
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(80, 15))
    assert spin.value() == 20 and events == ["start", "finish"]
    QTest.keyClick(slider, Qt.Key.Key_Right)
    assert spin.value() == 21
    spin.setValue(40)
    assert slider.fraction() == 1.0
    spin.setEnabled(False)  # a web theme switches the shadow fields off
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(inset, 15))
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(inset, 15))
    assert spin.value() == 40
    slider.grab()
    slider.deleteLater()
    spin.deleteLater()


def test_ink_well_settles_like_a_liquid_and_stops(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    _shown_style_tab(page, app)
    well = page.style_back_button
    assert not well._enabled_state and well._ink_level == 0.0
    page._set_style_color(page.style_back_color, "#FFFF0000")
    app.processEvents()
    # Offscreen the wash does not animate: it is at its end state at once.
    assert well._enabled_state and well._ink_level == 1.0
    # Driven by hand, it runs towards the target, overshoots a little and comes to rest.
    well._ink_level = 0.0
    seen = []
    for _ in range(200):
        well._ink_tick(1 / 30)
        seen.append(well._ink_level)
    assert max(seen) > 1.0 and abs(seen[-1] - 1.0) < 0.002
    assert well._ink_velocity == 0.0
    image = well.grab().toImage()
    pool = image.pixelColor(5, image.height() // 2)
    assert pool.red() > 200 and pool.green() < 70
    # Dark text on a light ink, light text on a dark one; the icon reads in the pool.
    page._set_style_color(page.style_back_color, "#FFFFEE88")
    assert well.value_ink().lightness() < 80 and well.value_ink(pool=True).lightness() < 80
    page._set_style_color(page.style_back_color, "#FF112233")
    assert well.value_ink().lightness() > 200 and well.value_ink(pool=True).lightness() > 200
    _finish(page)


def test_white_ink_gets_a_toned_sheet(tmp_path, monkeypatch):
    from twobyteasr.caption_style.studio_style_widgets import ink_paper
    from twobyteasr.design.theme_manager import theme_key
    from twobyteasr.design.ui_theme import theme_definition

    theme = theme_definition(theme_key())
    plain, _edge = ink_paper(theme, QColor("#E8473C"))
    toned, _edge = ink_paper(theme, QColor("#FFFFFF") if theme.is_light else QColor("#000000"))
    assert plain != toned
    assert abs(ink_wash.luminance(toned) - ink_wash.luminance(plain)) > 8
