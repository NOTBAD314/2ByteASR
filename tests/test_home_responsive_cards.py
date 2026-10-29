"""Responsive profile regressions for the three home recognition cards."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QSizePolicy, QVBoxLayout, QWidget  # noqa: E402

from twobyteasr.app.ui import APP_QSS  # noqa: E402
from twobyteasr.app.ui_recognition import RecognitionPlanWidget  # noqa: E402


def _app():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_QSS)
    return app


def test_recognition_cards_use_bounded_height_profiles_without_repolish_storm():
    app = _app()
    plan = RecognitionPlanWidget()
    plan.show()

    # Home C′ (2026-10-17): compact tiles, icon beside the model name;
    # layout A (2026-10-18): the model name one size larger.
    expected = (
        (140, "compact", 40, 12, 20),
        (165, "normal", 44, 13, 22),
        (200, "large", 50, 13, 26),
        (260, "extra_large", 54, 14, 28),
    )
    for height, profile, icon_size, role_size, model_size in expected:
        plan.resize(1200, height)
        app.processEvents()
        plan._update_responsive_profile()
        assert plan._responsive_profile == profile
        for card in plan.cards.values():
            assert card.property("density") == profile
            assert card.icon_label.width() == icon_size
            assert card.icon_label.height() == icon_size
            assert card.role_label.font().pixelSize() == role_size
            assert card.model_label.font().pixelSize() == model_size
            assert card.description_label.isVisible()

    apply_counts = {
        role: card._responsive_apply_count for role, card in plan.cards.items()
    }
    for _ in range(20):
        plan.resize(1200, 520)
        plan._update_responsive_profile()
    assert {
        role: card._responsive_apply_count for role, card in plan.cards.items()
    } == apply_counts

    plan.close()
    plan.deleteLater()


def test_recognition_cards_use_actual_card_width_even_when_window_is_tall():
    app = _app()
    plan = RecognitionPlanWidget()
    plan.show()

    plan.resize(720, 520)
    app.processEvents()
    plan._update_responsive_profile()

    assert plan._responsive_profile == "normal"
    assert {card.property("density") for card in plan.cards.values()} == {"normal"}
    assert all(card._identity_centered for card in plan.cards.values())
    for card in plan.cards.values():
        layout = card.layout()
        assert layout.stretch(card._leading_space_index) == 1
        assert layout.stretch(card._body_stretch_index) == 1

    plan.close()
    plan.deleteLater()


def test_recognition_cards_keep_shared_identity_and_bottom_row_tracks():
    app = _app()
    plan = RecognitionPlanWidget()
    plan.cards["primary"].set_state("MOSS-Transcribe-Diarize", "本地", "已就绪", "good")
    plan.cards["timeline"].set_state("FireRedASR2-AED", "本地", "已就绪", "good")
    plan.cards["review"].set_state("Qwen3-ASR 1.7B", "本地", "已就绪", "good")
    plan.show()
    for width, height in ((980, 360), (980, 520), (1500, 520)):
        plan.resize(width, height)
        app.processEvents()
        plan._update_responsive_profile()
        app.processEvents()

        cards = tuple(plan.cards.values())
        assert len({card.model_label.height() for card in cards}) == 1
        for card in cards:
            label = card.model_label
            metrics = QFontMetrics(label.font())
            required = metrics.boundingRect(0, 0, label.width(), 2000,
                                             Qt.TextFlag.TextWordWrap, label.text()).height()
            assert label.height() >= max(required, metrics.lineSpacing())
        for attr in ("icon_label", "role_label", "model_label", "status_badge", "change_hint"):
            assert len({getattr(card, attr).mapTo(plan, getattr(card, attr).rect().topLeft()).y() for card in cards}) == 1

    plan.close()
    plan.deleteLater()


def test_stepped_down_names_keep_their_size_through_a_zoom_pass(monkeypatch):
    # 2026-10-21 (user at 120% interface zoom): back on home from Studio, a zoom
    # pass scaled the stepped-down name size a second time, so the names grew
    # over the description line ("• moss-transcribe-…", "Aligner", "已关闭").
    from twobyteasr.app import ui_zoom
    # In memory only: set_zoom_percent would save to QSettings.
    monkeypatch.setitem(ui_zoom._state, "percent", 120)
    monkeypatch.setitem(ui_zoom._state, "touched", True)
    app = _app()
    plan = RecognitionPlanWidget()
    for role, name in (("primary", "MOSS Pro 云端 · moss-transcribe-diarize-pro-long-name"),
                       ("timeline", "Qwen3 ForcedAligner"), ("review", "已关闭")):
        plan.cards[role].set_state(name, "在线", "已配置", "success")
    plan.resize(760, 200)
    plan.show()
    app.processEvents()
    ui_zoom.apply_to(plan)
    app.processEvents()
    plan._sync_identity_height()
    stepped = {role: card._name_px for role, card in plan.cards.items()}
    assert all(stepped.values()), stepped                 # the long name made all three step down
    for _ in range(2):                                     # e.g. the page switch, then a theme change
        ui_zoom.apply_to(plan)
        app.processEvents()
    for role, card in plan.cards.items():
        assert card.model_label.styleSheet() == f"font-size: {card._name_px}px;", role
        assert card.model_label.font().pixelSize() == card._name_px, role
        assert card._name_px == stepped[role], role
    plan.close()
    plan.deleteLater()


class _NestingPlan(RecognitionPlanWidget):
    """Records how deep its resize events nest; stops at 8 so a regression fails instead of overflowing."""

    def __init__(self):
        self.depth = self.deepest = 0
        super().__init__()

    def resizeEvent(self, event):
        self.depth += 1
        self.deepest = max(self.deepest, self.depth)
        try:
            if self.depth > 8:
                QWidget.resizeEvent(self, event)
                return
            super().resizeEvent(event)
        finally:
            self.depth -= 1


def test_cards_settle_when_the_larger_profile_squeezes_its_neighbours():
    # 2026-10-22 (the app closed with a stack overflow, 0xC00000FD, on home
    # with an 1100 px window on the 175% monitor): at a 765 px plan the large
    # profile's wider timeline card left its neighbours 247 px (normal below
    # 250) and the normal profile left them 251 px (large), and each apply
    # showed a chip, which re-laid the window out and resized the plan from
    # inside the apply, so the two profiles called each other until the stack
    # ran out. Offscreen fonts are smaller, so the timeline card gets that
    # wider, taller large-profile minimum explicitly and a chip that shows
    # again on every apply; home's height band and Fixed policy do the rest.
    from twobyteasr.local_models.model_workshop import model_for_backend, model_role_line
    app = _app()
    host = QWidget()
    outer = QVBoxLayout(host)
    outer.setContentsMargins(0, 0, 0, 0)
    plan = _NestingPlan()
    columns = plan.layout()
    columns.setSpacing(0)
    for index in range(columns.count()):
        columns.setStretch(index, 1)
    policy = plan.sizePolicy()
    policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)  # as home: its size hint, inside the band
    plan.setSizePolicy(policy)
    plan.setMinimumHeight(180)
    plan.setMaximumHeight(240)
    outer.addWidget(plan)
    outer.addStretch(1)
    for (role, name), backend in zip((("primary", "MOSS-Transcribe-Diarize"), ("timeline", "FireRedASR2-AED"),
                                      ("review", "Qwen3-ASR 1.7B")), ("moss", "firered", "qwen")):
        card = plan.cards[role]
        card.set_state(name, "本地", "已就绪", "good")
        model = model_for_backend(role, backend)
        card.set_model(model, model_role_line(model, role) if model is not None else None)
    timeline = plan.cards["timeline"]
    taller = QWidget()
    timeline.layout().addWidget(taller)
    apply = timeline.apply_responsive_profile

    def squeezing_apply(profile):
        large = profile == "large"
        timeline.setMinimumWidth(330 if large else 0)
        taller.setFixedHeight(24 if large else 0)
        timeline.status_badge.hide()  # shown again inside the apply
        return apply(profile)

    timeline.apply_responsive_profile = squeezing_apply
    host.resize(900, 600)
    host.show()
    app.processEvents()

    def applied():
        return sum(card._responsive_apply_count for card in plan.cards.values())

    undone = []
    for width in range(700, 904, 6):
        before = applied()
        plan.deepest = 0
        host.setFixedWidth(width)
        for _ in range(4):
            app.processEvents()
        # The resize from inside an apply only asks for another look.
        assert plan.deepest <= 2, (width, plan.deepest)
        settled = applied()
        for _ in range(4):
            app.processEvents()
        assert applied() == settled, width  # no flipping back and forth afterwards
        assert {card.property("density") for card in plan.cards.values()} == {plan._responsive_profile}
        if settled - before > len(plan.cards):  # more than one profile change at this width
            undone.append(width)
            assert plan._responsive_profile == "normal", width  # the profile that fits
    assert undone, "the squeeze never made the profiles undo each other"
    assert plan._responsive_profile == "large"  # a wider window drops the cap

    host.close()
    host.deleteLater()
