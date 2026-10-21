"""P9A design-system contracts: tokens, polar shadow, evidence, controls."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDoubleSpinBox  # noqa: E402

from twobyteasr.design.components import (  # noqa: E402
    format_model_evidence_coverage,
    map_provider_ui_state,
)
from twobyteasr.design.control_qss import build_control_qss  # noqa: E402
from twobyteasr.design.controls import (  # noqa: E402
    AngleDisc,
    CompactNumericField,
    offset_to_polar,
    polar_to_offset,
)
from twobyteasr.design.tokens import SPACE_SCALE, TYPE_SCALE, p9a_tokens  # noqa: E402
from twobyteasr.design.studio_theme import build_studio_qss  # noqa: E402
from twobyteasr.design.ui_theme import theme_definition  # noqa: E402


REQUIRED_TOKEN_KEYS = {
    "bg.app",
    "bg.panel",
    "bg.card",
    "bg.control",
    "bg.control_hover",
    "bg.control_pressed",
    "bg.popup",
    "bg.modal",
    "border.subtle",
    "border.default",
    "border.focus",
    "text.primary",
    "text.secondary",
    "text.muted",
    "text.disabled",
    "accent.primary",
    "accent.hover",
    "accent.soft",
    "success",
    "warning",
    "danger",
    "info",
}


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_p9a_tokens_cover_surface_and_type_scale():
    tokens = p9a_tokens(theme_definition("plum"))
    assert REQUIRED_TOKEN_KEYS <= set(tokens)
    assert SPACE_SCALE == (4, 8, 12, 16, 24, 32)
    assert set(TYPE_SCALE) >= {
        "display",
        "heading1",
        "heading2",
        "section",
        "body",
        "small",
        "caption",
        "mono",
    }
    theme = theme_definition("plum")
    assert tokens["bg.app"] == theme.app_background
    assert tokens["bg.control"] == theme.surface_elevated
    assert tokens["accent.primary"] == theme.accent
    assert theme.bg_app == theme.app_background
    assert "bg_app" not in theme.__dataclass_fields__


def test_shadow_polar_converts_without_changing_offset_model():
    offset_x, offset_y = polar_to_offset(135.0, 10.0)
    angle, distance = offset_to_polar(offset_x, offset_y)
    assert abs(angle - 135.0) < 0.5
    assert abs(distance - 10.0) < 0.05
    down_x, down_y = polar_to_offset(90.0, 8.0)
    assert abs(down_x) < 1e-6
    assert abs(down_y - 8.0) < 1e-6


def test_model_evidence_never_guesses_missing_sources():
    single = format_model_evidence_coverage(
        [{"model": "MOSS"}, {"model": "Current"}]
    )
    assert single["headline"] == "单来源 无冲突证据"
    assert single["moss"] == "✓"
    assert single["firered"] == "—"
    assert single["qwen"] == "—"
    assert single["single_source"] is True

    empty = format_model_evidence_coverage([])
    assert empty["headline"] == "来源信息缺失／待恢复"
    assert empty["single_source"] is False
    assert empty["display"] == "MOSS —    FireRed —    Qwen3 —"

    two = format_model_evidence_coverage(
        [{"model": "MOSS"}, {"model": "FireRedASR2-AED"}]
    )
    assert two["headline"] == "2 路独立来源 · 一致性未提供"
    assert two["qwen"] == "—"

    three = format_model_evidence_coverage(
        [{"model": "MOSS"}, {"model": "FireRed"}, {"model": "Qwen3-ASR"}]
    )
    assert three["headline"] == "3 路独立来源 · 一致性未提供"

    unknown = format_model_evidence_coverage([{"model": "mystery-engine"}])
    assert unknown["moss"] == "—"
    assert unknown["firered"] == "—"
    assert unknown["qwen"] == "—"
    assert unknown["unknown"] == ("mystery-engine",)


def test_provider_status_mapping_keeps_generic_error_extensible():
    assert map_provider_ui_state("READY") == "READY"
    assert map_provider_ui_state("SESSION READY") == "SESSION READY"
    assert map_provider_ui_state("正在检测…") == "REQUESTING"
    assert map_provider_ui_state("OFFLINE") == "TIMEOUT"
    assert map_provider_ui_state("ERROR", "timeout after 8s") == "TIMEOUT"
    assert map_provider_ui_state("ERROR", "schema missing concept_name") == "SCHEMA ERROR"
    assert map_provider_ui_state("ERROR", "quality rejected") == "QUALITY LOW"
    assert map_provider_ui_state("ERROR", "connection refused") == "FAILURE"


def test_compact_numeric_field_and_angle_disc():
    _app()
    spin = QDoubleSpinBox()
    spin.setValue(6.4)
    field = CompactNumericField(spin, label="描边", unit="px")
    assert field.spin is spin
    assert spin.minimumHeight() == 28
    disc = AngleDisc()
    disc.setAngle(135)
    assert abs(disc.angle() - 135) < 0.05
    disc.setAngle(400)
    assert abs(disc.angle() - 40) < 0.05


def test_control_qss_uses_elevated_surface_without_gradients():
    theme = theme_definition("plum")
    qss = build_control_qss(theme)
    lowered = qss.lower()
    assert "qlineargradient" not in lowered
    assert "qradialgradient" not in lowered
    assert theme.surface_elevated in qss
    assert "QMenu" in qss
    assert "QToolTip" in qss
    assert "QAbstractItemView" in qss
    assert "QDialog" in qss
    studio = build_studio_qss()
    assert "P9A control system" in studio


def test_p9a_r5_build_id_and_polar_shadow_labels():
    from twobyteasr.diagnostics.build_identity import BUILD_ROUND_ID, build_id_text, launch_identity_payload

    payload = launch_identity_payload()
    assert payload["round_id"] == BUILD_ROUND_ID
    assert BUILD_ROUND_ID in build_id_text()
    assert "sys_executable" in payload
    assert "sys_frozen" in payload
