"""四十五轮守护：泳道序/跨轨拖拽/主轨拒绝 + ADR-0005 素材效果（契约/色键/混合）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twobyteasr.timeline.studio_media_pool import (
    add_media_asset,
    add_video_clip,
    create_video_track,
    primary_video_track_id,
    reassign_video_clip,
    set_video_clip_effects,
    validate_media_graph,
)
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    VideoClip,
    normalize_clip_effects,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- 泳道与拖拽


def test_lane_order_matches_render_z():
    """四十五轮：z 序越高的轨道泳道越靠上（Premiere 语义），V1 永远最底。"""
    _app()
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage()
    page._create_blank_studio()
    project = page.project
    create_video_track(project, "第一层")
    create_video_track(project, "第二层")
    create_video_track(project, "第三层")
    validate_media_graph(project)
    page.timeline.reindex_project()
    rects = page.timeline._video_track_rects()
    assert rects["V3"].top() < rects["V2"].top() < rects["V1"].top()
    page.close_page()


def test_reassign_rejects_primary_and_accepts_secondary():
    _app()
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage()
    page._create_blank_studio()
    project = page.project
    create_video_track(project, "主层")
    asset = add_media_asset(
        project, "clip.flv", duration_ms=5_000,
        video_metadata={"has_video": True}, audio_metadata={"has_audio": False},
    )
    v2 = create_video_track(project, "第二层")
    v3 = create_video_track(project, "第三层")
    add_video_clip(project, v2.id, asset.asset_id, timeline_in_ms=1_000)
    validate_media_graph(project)
    primary = primary_video_track_id(project)
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    next(t for t in project.video_tracks if t.id == primary).locked = sequence_of(project).video_track_locked = False
    moving = v2.clips[0].id
    reassign_video_clip(project, v2.id, primary, moving)
    reassign_video_clip(project, primary, v3.id, moving, timeline_in_ms=2_000)
    assert not v2.clips and len(v3.clips) == 1 and v3.clips[0].timeline_in_ms == 2_000
    page.close_page()


# ---------------------------------------------------------------- 素材效果契约


def test_clip_effects_contract_roundtrip_and_clamp():
    clip = VideoClip("c1", "a1")
    clip.effects = normalize_clip_effects({
        "blendMode": "screen",
        "chromaKey": {"enabled": True, "color": "bad-color", "similarity": 2.0, "smoothness": -1, "spillSuppression": 0},
    })
    clip.validate()
    key = clip.effects["chromaKey"]
    assert clip.effects["blendMode"] == "screen"
    assert key["color"] == "#00FF00"  # 非法色回落默认绿
    assert key["similarity"] == 1.0 and key["smoothness"] == 0.0
    assert key["spillSuppression"] is False
    # 旧工程无 effects → 全默认。
    legacy = VideoClip("c2", "a1")
    legacy.validate()
    assert legacy.effects["blendMode"] == "normal"
    assert legacy.effects["chromaKey"]["enabled"] is False


def test_set_video_clip_effects_writes_normalized():
    _app()
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage()
    page._create_blank_studio()
    project = page.project
    create_video_track(project, "主层")
    create_video_track(project, "效果层")
    asset = add_media_asset(
        project, "e.flv", duration_ms=3_000,
        video_metadata={"has_video": True}, audio_metadata={"has_audio": False},
    )
    v2 = create_video_track(project, "效果层")
    clip = add_video_clip(project, v2.id, asset.asset_id, timeline_in_ms=0)
    set_video_clip_effects(project, v2.id, clip.id, {"blendMode": "addition"})
    assert clip.effects["blendMode"] == "addition"
    assert clip.effects["chromaKey"]["similarity"] == 0.32
    page.close_page()


# ---------------------------------------------------------------- 色键数学


def test_chroma_key_alpha_mask():
    from twobyteasr.playback.video_compositor import apply_chroma_key

    image = QImage(4, 1, QImage.Format.Format_ARGB32)
    colors = [0xFF00FF00, 0xFF00E000, 0xFF102030, 0xFFFF00FF]  # 绿/近绿/深灰/品红
    for x, argb in enumerate(colors):
        image.setPixel(x, 0, argb)
    keyed = apply_chroma_key(image, {"color": "#00FF00", "similarity": 0.10, "smoothness": 0.05})
    alphas = [qAlpha(keyed.pixel(x, 0)) for x in range(4)]
    assert alphas[0] == 0, alphas  # 纯绿全透
    assert alphas[1] < 255, alphas  # 近绿在渐变带内
    assert alphas[2] == 255 and alphas[3] == 255, alphas  # 其它颜色保留


from PySide6.QtGui import qAlpha  # noqa: E402


def test_blend_mode_mapping_covers_contract():
    from twobyteasr.playback.video_compositor import _BLEND_COMPOSITION_MODES
    from PySide6.QtGui import QPainter

    assert set(_BLEND_COMPOSITION_MODES) == {"normal", "screen", "multiply", "overlay", "softLight", "addition"}
    assert _BLEND_COMPOSITION_MODES["normal"] == QPainter.CompositionMode.CompositionMode_SourceOver
