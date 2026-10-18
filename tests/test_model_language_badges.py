"""Language badges: one data source, the same six badges on every card (2026-10-18)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from twobyteasr.model_languages import (  # noqa: E402
    BADGE_LANGUAGES, LANGUAGE_SUPPORT, TIERS, language_support, more_text,
)


def _app():
    return QApplication.instance() or QApplication([])


def test_every_catalog_model_has_language_data_with_known_tiers():
    from twobyteasr.model_workshop import MODELS

    for model in MODELS:
        support = language_support(model.key)
        assert support is not None, model.key
        assert tuple(support["tiers"]) == BADGE_LANGUAGES
        assert set(support["tiers"].values()) <= set(TIERS), model.key
    for key, record in LANGUAGE_SUPPORT.items():
        assert set(record.get("tiers", {})) <= set(BADGE_LANGUAGES), key
        # Every rated model names the official source it was checked against.
        assert not record.get("tiers") or record["source"].startswith("https://"), key


def test_tiers_follow_the_official_sources():
    tiers = lambda key: language_support(key)["tiers"]  # noqa: E731
    # MOSS claims 50+ languages; it is not a Chinese-only model.
    assert tiers("moss")["en"] == "strong" and tiers("moss")["ja"] == "usable"
    assert language_support("moss")["more"] == "50+"
    assert set(tiers("canary_qwen").values()) == {"strong", "no"} and tiers("canary_qwen")["en"] == "strong"
    assert tiers("spark_asr_v2")["ja"] == "no" and tiers("spark_asr_v2")["dialects"] == "strong"
    assert tiers("firered")["ja"] == "no"
    assert tiers("qwen_aligner")["ja"] == "strong" and tiers("qwen_aligner")["dialects"] == "no"
    assert tiers("glm_asr_nano")["ko"] == "no"
    # An unconfirmed model ID or a user-configured service is never guessed.
    assert set(tiers("mai_latest").values()) == {"unknown"}
    assert set(tiers("custom_asr_api").values()) == {"unknown"}


def test_more_badge_text():
    assert more_text(None) == ""
    assert more_text(25) == "+{count} 种" and more_text(25, short=True) == "+{count}"
    assert more_text("50+") == "共 {count} 种" and more_text("50+", short=True) == "50+"


def test_badge_row_marks_each_tier_and_more():
    _app()
    from twobyteasr.model_language_badges import LanguageBadgeRow

    row = LanguageBadgeRow()
    row.set_support(language_support("glm_asr_nano"))
    assert [row.tier(code) for code in BADGE_LANGUAGES] == ["strong", "strong", "usable", "strong", "usable", "no"]
    assert [row.badges[code].text() for code in BADGE_LANGUAGES] == ["中文", "粤语", "方言", "英语", "日语", "韩语"]
    assert row.badges["ko"].toolTip() == "韩语：不支持"
    assert not row.more.isHidden() and row.more.text() == "+13 种"

    row.set_support(language_support("sensevoice"))
    assert row.tier("dialects") == "unknown" and row.more.isHidden()

    short = LanguageBadgeRow(short=True)
    short.set_support(language_support("moss"))
    assert [short.badges[code].text() for code in BADGE_LANGUAGES] == ["中", "粤", "方", "英", "日", "韩"]
    assert short.more.text() == "50+"
    assert "50+ 种语言" in short.more.toolTip()

    short.set_support(None)
    assert {short.tier(code) for code in BADGE_LANGUAGES} == {"unknown"} and short.more.isHidden()


def test_home_tile_draws_the_logo_or_the_glyph():
    """The home card tile finds the logo from the install root (flat daily layout too)."""
    _app()
    from twobyteasr.ui_recognition import model_tile_pixmap
    from twobyteasr.model_workshop import MODELS

    by_key = {model.key: model for model in MODELS}
    moss = model_tile_pixmap(by_key["moss"], 44).toImage()
    assert moss.pixelColor(3, 22).name() == "#ffffff"  # white tile behind the logo
    assert moss.pixelColor(22, 22).name() != "#ffffff"  # the logo itself
    spark = model_tile_pixmap(by_key["spark_asr_v2"], 44).toImage()
    assert spark.pixelColor(3, 22).name() == "#1f6fe5"  # glyph on iFlytek blue
