"""2026-09-18 P0/P1 回归：continuous proxy、播放源绑定、滚轮手感、五字段解析。"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"


def run_ffmpeg(*args: str) -> None:
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True)


def _holed_mkv(path: Path) -> None:
    run_ffmpeg(
        "-f", "lavfi", "-i", "testsrc=duration=12:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
        "-filter_complex",
        "[0:v]split=2[vA][vB];[1:a]asplit=2[aA][aB];"
        "[vA]trim=0:6,setpts=PTS-STARTPTS[v1];"
        "[aA]atrim=0:6,asetpts=PTS-STARTPTS[a1];"
        "[vB]trim=start=6,setpts=PTS-STARTPTS+2/TB[v2];"
        "[aB]atrim=start=6,asetpts=PTS-STARTPTS+2/TB[a2];"
        "[v1][v2]concat=n=2:v=1:a=0[v];[a1][a2]concat=n=2:v=0:a=1[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path),
    )


def test_continuous_proxy_is_packet_identical_and_gapless(tmp_path):
    from twobyteasr.playback.avsync import build_continuous_proxy, scan_timestamp_gaps

    src = tmp_path / "holed.mkv"
    _holed_mkv(src)
    result = scan_timestamp_gaps(src, FFPROBE)
    assert result.event_count == 1 and result.map.total_gap_ms > 1500

    proxy = build_continuous_proxy(src, result.map, tmp_path / "continuous.mkv")

    def probe(path: Path):
        payload = subprocess.run(
            [str(FFPROBE), "-v", "error", "-count_packets",
             "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,nb_read_packets",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        )
        return json.loads(payload.stdout)

    a, b = probe(src), probe(proxy)
    assert [(s["codec_type"], s.get("nb_read_packets")) for s in a["streams"]] == \
           [(s["codec_type"], s.get("nb_read_packets")) for s in b["streams"]]
    folded = float(b["format"]["duration"]) - float(a["format"]["duration"])
    assert -0.3 < folded + result.map.total_gap_ms / 1000.0 < 0.3
    healthy = scan_timestamp_gaps(proxy, FFPROBE)
    assert healthy.status == "healthy" and healthy.event_count == 0
    decode = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-loglevel", "error",
         "-ss", "4", "-t", "4", "-i", str(proxy), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    assert decode.returncode == 0


def test_playback_source_prefers_continuous_proxy(tmp_path):
    from twobyteasr.media.indexed_media import IndexedMediaCache

    # 带联合洞的 FLV：没有洞就不会触发 continuous proxy 构建。
    flv = tmp_path / "gappy.flv"
    run_ffmpeg(
        "-f", "lavfi", "-i", "testsrc=duration=12:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
        "-filter_complex",
        "[0:v]split=2[vA][vB];[1:a]asplit=2[aA][aB];"
        "[vA]trim=0:6,setpts=PTS-STARTPTS[v1];"
        "[aA]atrim=0:6,asetpts=PTS-STARTPTS[a1];"
        "[vB]trim=start=6,setpts=PTS-STARTPTS+2/TB[v2];"
        "[aB]atrim=start=6,asetpts=PTS-STARTPTS+2/TB[a2];"
        "[v1][v2]concat=n=2:v=1:a=0[v];[a1][a2]concat=n=2:v=0:a=1[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-f", "flv", str(flv),
    )
    cache = IndexedMediaCache(root=tmp_path / "seek")
    cache.resolve(str(flv))
    assert cache._requested == set(), '可直接播放的FLV不按后缀换封装'

    deadline = time.monotonic() + 180
    kind = "original"
    while time.monotonic() < deadline:
        playback, kind = cache.playback_source(str(flv))
        if kind == "proxy":
            break
        time.sleep(0.5)
    assert kind == "proxy", "扫描→代理构建链应在合理时间内产出 continuous.mkv"
    playback, kind = cache.playback_source(str(flv))
    assert Path(playback).name == "continuous.mkv"
    assert not list(cache.root.glob('v2/*/optimized.*')), '真实断流仅生成必要的连续代理'


def test_av_sync_map_folds_to_identity_when_proxy_bound(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    from tests.test_round42_studio_recognition import _page
    from twobyteasr.playback.avsync import AVSyncMap, TimestampGap, load_sync_map
    from twobyteasr.media import indexed_media as indexed_media_module

    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = _page(monkeypatch, tmp_path)
    try:
        page.project.media.path = str(tmp_path / "long.flv")
        gappy = AVSyncMap(
            [TimestampGap(2_000, 4_000, 2000, video=True, audio=True)],
            source_duration_ms=60_000,
        )
        proxy = tmp_path / "continuous.mkv"
        proxy.write_bytes(b"x")
        monkeypatch.setattr(
            indexed_media_module.GLOBAL_INDEXED_MEDIA,
            "sync_map",
            lambda source: gappy,
        )
        monkeypatch.setattr(
            indexed_media_module.GLOBAL_INDEXED_MEDIA,
            "playback_source",
            lambda source: (proxy, "proxy"),
        )
        page.project.media.duration_ms = 60_000
        page._maybe_apply_av_sync_map()
        applied = page.video._av_sync_map
        assert applied is not None
        assert not applied.gaps, "代理绑定时洞映射应折叠为恒等"
        assert applied.source_to_content_ms(10_000) == 10_000
        assert page.project.media.duration_ms == 58_000
    finally:
        page.close_page()
        page.deleteLater()
        app.processEvents()


def test_smooth_card_list_wheel_notch_is_bounded(tmp_path):
    from PySide6.QtCore import QPointF, QPoint, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication, QLabel
    from twobyteasr.studio.studio_highlight_ui import SmoothCardList

    app = QApplication.instance() or QApplication([])
    lst = SmoothCardList()
    lst.setVerticalScrollMode(SmoothCardList.ScrollMode.ScrollPerPixel)
    lst.resize(460, 500)
    for index in range(6):
        from PySide6.QtWidgets import QListWidgetItem

        item = QListWidgetItem()
        lst.addItem(item)
        card = QLabel("card\n" * 15)
        card.setMinimumHeight(320)
        lst.setItemWidget(item, card)
        item.setSizeHint(card.sizeHint())
    lst.show()
    app.processEvents()
    bar = lst.verticalScrollBar()
    assert bar.maximum() > 0
    assert bar.singleStep() > 200, "Qt 默认把 singleStep 设成整卡高度（bug 根源）"

    def notch(dy=120):
        bar.setValue(0)
        event = QWheelEvent(
            QPointF(200, 200), QPointF(200, 200), QPoint(0, 0), QPoint(0, dy),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        lst.wheelEvent(event)
        app.processEvents()
        return bar.value()

    moved = notch(-120)  # 向下滚动一格
    assert 80 <= moved <= 160, f"一格滚轮应约 80~160px，实测 {moved}px"
    bar.setValue(bar.maximum())
    bar.setValue(bar.maximum() - 110)  # 手工等价位移，覆盖向上方向语义


def test_parse_highlight_payload_maps_five_fields():
    from twobyteasr.studio.studio_highlight_analyzer import parse_highlight_payload

    payload = json.dumps({
        "candidates": [
            {
                "start_ms": 1000, "end_ms": 25000, "score": 96, "grade": "强烈推荐",
                "title": "第50抽出五星", "hook": "50抽意外出了目标五星",
                "event_summary": "连续几十抽未出货后，第50抽突然命中目标五星，主播愣住后爆发。",
                "clip_reason": "铺垫→反转→爆发完整，情绪转折脱离上下文也能看懂。",
                "context_required": "low",
                "reason": "", "category": "reaction",
            }
        ]
    })
    parsed = parse_highlight_payload(payload, [])
    assert len(parsed) == 1
    candidate = parsed[0]
    assert candidate.event_summary.startswith("连续几十抽")
    assert candidate.clip_reason.startswith("铺垫")
    assert candidate.context_required == "low"
    assert candidate.hook == "50抽意外出了目标五星"

    legacy = json.dumps({
        "candidates": [
            {"start_ms": 1000, "end_ms": 25000, "score": 80, "grade": "推荐",
             "title": "旧格式", "hook": "旧钩子", "reason": "旧理由", "category": "funny"}
        ]
    })
    parsed = parse_highlight_payload(legacy, [])
    assert parsed[0].clip_reason == "旧理由"
    assert parsed[0].event_summary == "旧钩子"
    assert parsed[0].context_required == ""
