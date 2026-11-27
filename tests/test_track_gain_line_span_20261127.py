"""The track volume line sits on the clips, not across the whole lane (2026-11-27).

User: on Subtitle Studio's A1 track the yellow volume line and its handle ran past the end of
the audio clip to the timeline's right edge. It is drawn only within each clip's span now, and
only grabbed there.
"""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import AudioClip, AudioTrack, StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio import timeline_track_gain
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.timeline.studio_media_pool import add_media_asset


@pytest.fixture
def timeline(tmp_path):
    QApplication.instance() or QApplication([])
    project = SubtitleProject(media=StudioMedia(str(tmp_path / 'source.mp4'), duration_ms=60_000, width=160, height=90),
                              speakers=[StudioSpeaker('S1')], cues=[StudioCue('one', 0, 2000, '字幕', 'S1')])
    project.validate()
    asset = add_media_asset(project, tmp_path / 'voice.wav', duration_ms=20_000, audio_metadata={'has_audio': True})
    asset.offline = False
    project.audio_tracks.append(AudioTrack('AX', '独立音频', [AudioClip('ax-1', asset.asset_id, 0, 5000, 4000, 9000),
                                                            AudioClip('ax-2', asset.asset_id, 5000, 11000, 14000, 20000)]))
    widget = WaveformTimeline()
    widget.resize(1400, 520)
    widget.set_project(project)
    widget.set_waveform_visible(True)
    widget.visible_start_ms = 0
    widget.visible_duration_ms = 60_000
    widget.show()
    QApplication.processEvents()
    yield widget
    widget.close()


def _clip_spans(timeline):
    track = next(item for item in timeline.project.audio_tracks if item.id == 'AX')
    return [(timeline._time_to_x(clip.timeline_in_ms), timeline._time_to_x(clip.timeline_out_ms)) for clip in track.clips]


def test_line_segments_sit_inside_the_clips(timeline):
    row = timeline._audio_track_rects()['AX']
    spans = _clip_spans(timeline)
    pieces = timeline_track_gain.segments(timeline, 'AX', row)
    assert len(pieces) == len(spans) == 2
    for piece, (left, right) in zip(pieces, spans):
        assert left <= piece.left() < piece.right() <= right
    assert pieces[-1].right() < timeline._content_right() - 100      # nowhere near the right edge


def test_painted_line_stays_within_the_clips(timeline):
    row = timeline._audio_track_rects()['AX']
    spans = _clip_spans(timeline)
    image = QImage(timeline.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.black)
    timeline.render(image)
    line_y = round(timeline_track_gain.geometry(timeline, 'AX', row).center().y())
    yellow = []
    for x in range(timeline.TRACK_HEADER_WIDTH, round(timeline._content_right())):
        for y in (line_y - 1, line_y, line_y + 1):
            color = image.pixelColor(x, y)
            if abs(color.red() - 0xe6) < 24 and abs(color.green() - 0xbf) < 24 and abs(color.blue() - 0x7b) < 30:
                yellow.append(x)
                break
    assert yellow, 'the volume line was not painted'
    assert all(any(left - 1 <= x <= right + 1 for left, right in spans) for x in yellow), \
        (min(yellow), max(yellow), spans)


def test_line_is_only_grabbed_on_a_clip(timeline):
    row = timeline._audio_track_rects()['AX']
    y = timeline_track_gain.geometry(timeline, 'AX', row).center().y()
    (left, right), _second = _clip_spans(timeline)
    assert timeline_track_gain.hit(timeline, QPointF((left + right) / 2, y)) == 'AX'
    assert timeline_track_gain.hit(timeline, QPointF(right + 40, y)) == ''
    assert timeline_track_gain.hit(timeline, QPointF(timeline._content_right() - 20, y)) == ''
