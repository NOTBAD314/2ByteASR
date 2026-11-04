"""Single-video identities and subtitles outside YouTube."""
import json
from pathlib import Path

import pytest

from twobyteasr.media import link_download as ld
from twobyteasr.media.link_catalog import media_url, video_catalog, subtitle_tracks, public_track
from twobyteasr.media.link_choices import find_video_link, default_selection, video_label, quality_summary, duration_text
from twobyteasr.media.link_manifest import load_bundle

SRT = "1\n00:00:01,250 --> 00:00:03,500\n第一句字幕\n"


def bili_info(part=1):
    return dict(id=f"BV1JZnr6TEMd_p{part}", extractor_key="BiliBili", title="测试分 P",
        webpage_url="https://www.bilibili.com/video/BV1JZnr6TEMd", duration=20,
        subtitles={"ai-zh": [dict(ext="srt", data=SRT)],
                   "zh-Hant": [dict(ext="srt", data=SRT)],
                   "danmaku": [dict(ext="xml", url="https://example.test/danmaku")]},
        formats=[dict(format_id="v", vcodec="avc1", acodec="aac", height=360)])


@pytest.mark.parametrize("value,expected", [
    ("https://m.bilibili.com/video/BV1JZnr6TEMd/?p=2&share_source=copy_link", "https://www.bilibili.com/video/BV1JZnr6TEMd?p=2"),
    ("https://www.bilibili.com/video/av12345", "https://www.bilibili.com/video/av12345?p=1"),
    ("https://b23.tv/abc123", "https://b23.tv/abc123"),
    ("https://vimeo.com/12345?token=a%2Fb#t=3", "https://vimeo.com/12345?token=a%2Fb#t=3"),
    ("https://youtu.be/BaW_jenozKc?list=ignored", "https://www.youtube.com/watch?v=BaW_jenozKc"),
])
def test_normalization_preserves_other_sites_queries_and_bili_parts(value, expected):
    assert media_url(value) == expected


@pytest.mark.parametrize("value", ["file:///C:/secret", "javascript:alert(1)", "https://a:b@site.test/video",
    "https://site.test:bad/video", "https:///missing", "https://site.test/a\n--output=x",
    "https://youtube.com/playlist?list=1", "https://www.bilibili.com/",
    "https://www.bilibili.com/video/BV1JZnr6TEMd?p=0"])
def test_invalid_and_collection_links_are_rejected(value):
    with pytest.raises(ValueError):
        media_url(value)


def test_bilibili_share_text_and_generic_video_open_quick_card():
    assert find_video_link("【视频标题】 https://b23.tv/abc123（分享）") == "https://b23.tv/abc123"
    assert find_video_link("https://vimeo.com/12345") == "https://vimeo.com/12345"


def test_bili_inline_auto_subtitles_exclude_danmaku_and_keep_part_identity():
    catalog = video_catalog(bili_info(2), source_url="https://b23.tv/abc123")
    assert catalog["url"].endswith("?p=2") and catalog["platform"] == "BiliBili"
    assert catalog["subtitle_status"] == "available" and len(catalog["tracks"]) == 2
    automatic = next(t for t in catalog["tracks"] if t["source"] == "automatic")
    assert automatic["language"] == "zh"
    assert automatic["representations"][0]["data"] == SRT
    assert "data" not in json.dumps(public_track(automatic))
    p1 = video_catalog(bili_info(1))
    assert {t["track_id"] for t in catalog["tracks"]}.isdisjoint(t["track_id"] for t in p1["tracks"])
    with pytest.raises(ValueError, match="分 P"):
        video_catalog(bili_info(2), source_url="https://www.bilibili.com/video/BV1JZnr6TEMd?p=3")


def test_generic_subtitle_headers_and_automatic_container_are_honored():
    info = dict(id="123", extractor_key="Vimeo", webpage_url="https://vimeo.com/123",
        http_headers={"Referer": "https://vimeo.com/123", "User-Agent": "video-agent"},
        automatic_captions={"en": [dict(ext="vtt", url="https://cdn.test/sub.vtt", http_headers={"User-Agent": "sub-agent"})]})
    catalog = video_catalog(info)
    track = catalog["tracks"][0]
    assert track["source"] == "automatic"
    assert track["representations"][0]["http_headers"] == {"Referer": "https://vimeo.com/123", "User-Agent": "sub-agent"}
    assert catalog["subtitle_status"] == "available"
    assert video_catalog(dict(info, automatic_captions={})) ["subtitle_status"] == "none"


def test_bili_short_link_p1_identity_matches_explicit_part_on_retry():
    short = video_catalog(dict(bili_info(), id="BV1JZnr6TEMd"), source_url="https://b23.tv/short")
    explicit = video_catalog(bili_info(), source_url=short["url"])
    assert short["video_id"] == explicit["video_id"] == "BV1JZnr6TEMd_p1"
    assert [t["track_id"] for t in short["tracks"]] == [t["track_id"] for t in explicit["tracks"]]


@pytest.mark.parametrize("kind", ["playlist", "multi_video", "url"])
def test_unsupported_collection_never_becomes_a_single_video(kind):
    with pytest.raises(ValueError):
        video_catalog(dict(bili_info(), _type=kind))


def test_analyze_asks_extractors_for_subtitles_without_writing_files(monkeypatch):
    calls = []
    def run(tools, args, **kwargs):
        calls.append(args)
        return json.dumps(bili_info()), ["[BiliBili] Extracting subtitles"]
    monkeypatch.setattr(ld, "run_ytdlp", run)
    engine = ld.DownloadEngine(tools={"versions": {}})
    assert engine.analyze("https://b23.tv/abc")["subtitle_status"] == "available"
    assert all(flag in calls[0] for flag in ("--simulate", "--write-subs", "--write-auto-subs"))
    monkeypatch.setattr(ld, "run_ytdlp", lambda *a, **k: (json.dumps(bili_info()), ["WARNING: Subtitles require login"]))
    assert engine.analyze("https://b23.tv/abc")["subtitle_status"] == "incomplete"


def test_inline_subtitle_download_roundtrip_needs_no_subtitle_http_request(tmp_path):
    catalog = video_catalog(bili_info())
    selected = next(t for t in catalog["tracks"] if t["source"] == "automatic")
    task = ld.make_task(catalog, str(tmp_path), mode="subtitles", track_ids=[selected["track_id"]], primary_track_id=selected["track_id"])
    engine = ld.DownloadEngine(tools={"versions": {"yt_dlp": "fixture"}})
    engine.analyze = lambda *a, **k: catalog
    path = Path(engine.download(task))
    bundle = load_bundle(path)
    assert bundle["manifest"]["platform"] == "BiliBili"
    cue = bundle["captions"][selected["track_id"]]["captions"][0]
    assert (cue["start_ms"], cue["end_ms"], cue["text"]) == (1250, 3500, "第一句字幕")
    assert selected["representations"][0]["data"] not in path.read_text("utf-8")


def test_inline_subtitle_endpoint_failure_still_offers_video_with_warning(monkeypatch):
    calls = []
    def run(tools, args, **kwargs):
        calls.append(args)
        if "--write-subs" in args:
            raise ld.classify_error("ERROR: subtitle endpoint HTTP Error 403")
        return json.dumps(dict(bili_info(), subtitles={})), []
    monkeypatch.setattr(ld, "run_ytdlp", run)
    catalog = ld.DownloadEngine(tools={"versions": {}}).analyze("https://b23.tv/example")
    assert len(calls) == 2 and "--no-write-subs" in calls[1]
    assert catalog["formats"] and catalog["subtitle_status"] == "incomplete"


def test_primary_video_failure_does_not_retry_as_subtitle_failure(monkeypatch):
    calls = []
    def run(*args, **kwargs):
        calls.append(1)
        raise ld.classify_error("ERROR: Private video requires login")
    monkeypatch.setattr(ld, "run_ytdlp", run)
    with pytest.raises(ld.LinkDownloadError):
        ld.DownloadEngine(tools={"versions": {}}).analyze("https://vimeo.com/123")
    assert len(calls) == 1


@pytest.mark.parametrize("changed", [dict(video_id="other"), dict(platform="Vimeo")])
def test_download_rejects_identity_change_before_writing_media(tmp_path, monkeypatch, changed):
    catalog = video_catalog(bili_info())
    task = ld.make_task(catalog, str(tmp_path), **default_selection(catalog))
    engine = ld.DownloadEngine(tools={"versions": {}})
    engine.analyze = lambda *a, **k: dict(catalog, **changed)
    monkeypatch.setattr(ld, "run_ytdlp", lambda *a, **k: pytest.fail("must not download mismatched media"))
    with pytest.raises(ld.LinkDownloadError) as error:
        engine.download(task)
    assert error.value.category == "identity"


@pytest.mark.parametrize("video", ["../../outside", "x/%(title)s", "CON", "a:b", "相同标题"])
def test_extractor_id_cannot_control_paths_or_output_template(tmp_path, video):
    catalog = video_catalog(dict(id=video, extractor_key="Generic", webpage_url="https://site.test/video"))
    task = ld.make_task(catalog, str(tmp_path), mode="video")
    path = Path(task["directory"])
    assert path.parent == tmp_path
    assert task["video_id"] == video
    assert "%" not in path.name and ":" not in path.name


def test_other_website_preview_does_not_contact_youtube(monkeypatch):
    monkeypatch.setattr(ld, "fetch_image", lambda *a, **k: pytest.fail("must not fetch YouTube thumbnail"))
    assert ld.quick_preview("https://www.bilibili.com/video/BV1JZnr6TEMd") == {}


@pytest.mark.parametrize("extension,expected_video", [("mp4", "unknown"), ("mp3", "none")])
def test_generic_direct_media_with_unknown_codecs_remains_selectable(extension, expected_video):
    catalog = video_catalog(dict(id="sample", extractor_key="Generic", webpage_url="https://site.test/media",
        formats=[dict(format_id="http", ext=extension, url="https://cdn.test/file")]))
    assert catalog["formats"][0]["vcodec"] == expected_video
    assert catalog["formats"][0]["acodec"] == "unknown"
    selection = default_selection(catalog, mode="audio" if extension == "mp3" else "both")
    assert selection["audio_format" if extension == "mp3" else "video_format"] == "http"
    if extension == "mp4":
        assert video_label(catalog["formats"][0]) == "MP4 · 大小未知"
        assert quality_summary(catalog) == ""
        assert duration_text(catalog["duration"]) == "—"


def test_unsupported_and_bili_risk_errors_have_actionable_categories():
    assert ld.classify_error("ERROR: Unsupported URL").category == "unsupported"
    assert ld.classify_error("HTTP Error 412: Precondition Failed").category == "restricted"
