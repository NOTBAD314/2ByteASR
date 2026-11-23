"""Track header cards (2026-11-23, header draft B)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.studio.studio_track_header import header_card_color


def _close(a: QColor, b: QColor, tolerance=6):
    return max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue())) <= tolerance


def test_subtitle_tracks_get_separate_cards_and_video_shares_one_with_its_audio():
    app = QApplication.instance() or QApplication([])
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=10_000),
        speakers=[StudioSpeaker("S00", "兔白"), StudioSpeaker("S01", "嘉賓")],
        cues=[StudioCue("a", 0, 2_000, "一", speaker_id="S00"), StudioCue("b", 3_000, 5_000, "二", speaker_id="S01")],
    )
    project.validate()
    timeline = WaveformTimeline()
    timeline.resize(980, 460)
    timeline.set_project(project)
    timeline.show()
    app.processEvents()
    try:
        palette = timeline._timeline_palette()
        image = timeline.grab().toImage()
        ratio = image.devicePixelRatio()
        pixel = lambda x, y: image.pixelColor(round(x * ratio), round(y * ratio))
        card = header_card_color(palette)
        header = QColor(palette.header)
        speakers = timeline._track_layout()[0]
        first, second = sorted((speakers["S00"], speakers["S01"]), key=lambda rect: rect.top())
        assert _close(pixel(100, first.center().y() + 8), card)
        assert not _close(card, header, 3)
        # Between two subtitle tracks the header shows through: no shared card.
        assert _close(pixel(100, first.bottom()), header)
        video = timeline._video_track_rect("V1")
        audio = timeline._audio_track_rects()["A1"]
        assert abs(video.bottom() - audio.top()) < 1.5
        # V1 and its linked A1 share one card across their boundary (sampled
        # left of the colour rail, clear of the dashed divider).
        assert _close(pixel(7.5, video.bottom()), card)
        assert _close(pixel(60, video.bottom() - 6), card)
    finally:
        timeline.close()
        timeline.deleteLater()
