"""Same-name danmaku XML discovery and per-source binding (2026-10-11)."""
import unicodedata

from twobyteasr.danmaku_binding import (
    apply_discovery, bind_manual, binding_of, describe, discover_for_source,
    effective_path, needs_discovery, unbind)
from twobyteasr.studio_edit_sequence import sequence_of
from twobyteasr.studio_project import StudioMedia, SubtitleProject

XML = '<?xml version="1.0" encoding="UTF-8"?><i><d p="1.5,1,25,16777215">哈哈哈</d><d p="3.0,1,25,1">好</d></i>'


def _recording(folder, name, xml_name=None, xml=XML):
    folder.mkdir(parents=True, exist_ok=True)
    media = folder / name
    media.write_bytes(b"flv")
    if xml_name:
        (folder / xml_name).write_text(xml, encoding="utf-8")
    return media


def _project(media):
    project = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=10_000))
    project.validate()
    return project


def test_same_name_xml_binds_with_upper_case_extension_spaces_and_cjk(tmp_path):
    media = _recording(tmp_path / "录播 文件夹", "2026-10-11 18-10-10 洛克S4开门！8点.flv",
                       "2026-10-11 18-10-10 洛克S4开门！8点.XML")
    found = discover_for_source(media)
    assert found.status == "automatic" and found.count == 2 and found.duration_ms == 3000
    project = _project(media)
    assert needs_discovery(project) and apply_discovery(project, found)
    assert effective_path(project) == found.path
    assert describe(project)[0] == "automatic"


def test_composed_and_decomposed_names_match(tmp_path):
    name = "Café live"
    media = _recording(tmp_path, unicodedata.normalize("NFC", name) + ".flv",
                       unicodedata.normalize("NFD", name) + ".xml")
    assert discover_for_source(media).status == "automatic"


def test_several_candidates_never_auto_bind(tmp_path):
    media = _recording(tmp_path, "a b.flv", "a b.xml")
    (tmp_path / "a_b.xml").write_text(XML, encoding="utf-8")
    found = discover_for_source(media)
    assert found.status == "ambiguous" and len(found.candidates) == 2 and not found.path
    project = _project(media)
    apply_discovery(project, found)
    assert effective_path(project) == "" and describe(project)[0] == "ambiguous"


def test_broken_or_empty_xml_is_reported_not_bound(tmp_path):
    media = _recording(tmp_path, "rec.flv", "rec.xml", xml="<i><d p='1'>")
    found = discover_for_source(media)
    assert found.status == "invalid" and found.error
    project = _project(media)
    apply_discovery(project, found)
    assert effective_path(project) == "" and describe(project)[0] == "invalid"
    empty = _recording(tmp_path / "e", "rec.flv", "rec.xml", xml="<i></i>")
    assert discover_for_source(empty).status == "invalid"


def test_missing_xml_says_which_name_was_looked_for(tmp_path):
    media = _recording(tmp_path, "rec.flv")
    project = _project(media)
    apply_discovery(project, discover_for_source(media))
    state, name, _ = describe(project)
    assert state == "none" and name == "rec.xml"


def test_same_basename_in_two_folders_binds_each_folders_own_xml(tmp_path):
    first = _recording(tmp_path / "one", "rec.flv", "rec.xml")
    second = _recording(tmp_path / "two", "rec.flv", "rec.xml")
    a, b = _project(first), _project(second)
    apply_discovery(a, discover_for_source(first))
    apply_discovery(b, discover_for_source(second))
    assert effective_path(a).startswith(str(tmp_path / "one"))
    assert effective_path(b).startswith(str(tmp_path / "two"))
    # A result made for another source is never applied.
    assert not apply_discovery(a, discover_for_source(second))


def test_manual_choice_and_unbind_are_not_overwritten(tmp_path):
    media = _recording(tmp_path, "rec.flv", "rec.xml")
    other = tmp_path / "chosen.xml"
    other.write_text(XML, encoding="utf-8")
    project = _project(media)
    bind_manual(project, str(other), 2, 3000)
    assert not needs_discovery(project)
    assert not apply_discovery(project, discover_for_source(media))
    assert effective_path(project) == str(other.resolve())
    unbind(project)
    assert not needs_discovery(project) and effective_path(project) == ""
    assert not apply_discovery(project, discover_for_source(media))


def test_binding_of_previous_source_is_not_used_after_media_changes(tmp_path):
    first = _recording(tmp_path / "one", "rec.flv", "rec.xml")
    second = _recording(tmp_path / "two", "other.flv")
    project = _project(first)
    apply_discovery(project, discover_for_source(first))
    project.media.path = str(second)
    assert effective_path(project) == ""
    assert needs_discovery(project)


def test_discovery_uses_the_original_source_not_a_proxy_folder(tmp_path):
    original = _recording(tmp_path / "rec", "live.flv", "live.xml")
    proxy = _recording(tmp_path / "cache", "optimized.mkv")
    project = _project(original)
    project.media_pool = []
    assert discover_for_source(project.media.path).status == "automatic"
    assert discover_for_source(proxy).status == "none"


def test_legacy_manual_path_without_record_is_kept(tmp_path):
    media = _recording(tmp_path, "rec.flv", "rec.xml")
    chosen = tmp_path / "old.xml"
    chosen.write_text(XML, encoding="utf-8")
    project = _project(media)
    sequence_of(project).danmaku_path = str(chosen)
    assert not binding_of(project) and not needs_discovery(project)
    assert describe(project)[0] == "manual"
