from dataclasses import asdict
from types import SimpleNamespace
import copy
import pytest

from twobyteasr.media.media_ingest import MediaIngestResult
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project, load_project
from twobyteasr.projects.link_import import LinkImportCommand, interval_pairs, target_matches
from twobyteasr.projects.subtitle_consistency import validate_project
from twobyteasr.timeline.link_timing import cue_start_anchors
from twobyteasr.recognition.cue_word_alignment import cue_words
from twobyteasr.subtitle_rules.sentence_refine import allocate_split_times
from twobyteasr.subtitle_rules.subtitle_translation import cue_status, NEEDS_UPDATE


def bundle():
    rows = [dict(start_ms=1000, end_ms=3000, text="hello world", events=["event:0"],
                 anchors=[dict(text="hello ",char_start=0,char_end=6,start_ms=1000,precision="segment_start"),
                          dict(text="world",char_start=6,char_end=11,start_ms=2000,precision="segment_start")],
                 precision="segment_start"),
            dict(start_ms=3500,end_ms=4500,text="yes",events=["event:1"],anchors=[],precision="sentence")]
    track = dict(track_id="primary", platform="Youtube",video_id="BaW_jenozKc", language="en",source="automatic")
    tr = dict(track_id="translation",platform="Youtube",video_id="BaW_jenozKc",language="zh-Hans",source="translated")
    return dict(manifest_path="/download/download.2byte-download.json",media_path="/video.mp4",
        manifest=dict(task_id="task1",platform="Youtube",video_id="BaW_jenozKc",source_url="",
            primary_track_id="primary",translation_track_id="translation",subtitles=[dict(track=track),dict(track=tr)]),
        captions={"primary":dict(parser_version="1",captions=rows),
                  "translation":dict(parser_version="1",captions=[
                      dict(start_ms=1000,end_ms=1900,text="你好"),dict(start_ms=1900,end_ms=3000,text="世界"),
                      dict(start_ms=3500,end_ms=4500,text="是")])})


def media():
    return MediaIngestResult(generation=0,project_token="",source_path="/video.mp4",
        duration_ms=6000,has_video=True,has_audio=True,width=320,height=240)


def test_atomic_import_nonzero_undo_idempotence_and_reopen(tmp_path):
    project=SubtitleProject(media=StudioMedia(path=""))
    project.validate()
    original=copy.deepcopy(project.to_dict())
    command=LinkImportCommand(project,bundle(),media(),position_ms=10000)
    command.redo()
    assert [(c.start_ms,c.end_ms) for c in project.cues] == [(11000,13000),(13500,14500)]
    assert project.generation_metadata["translations"][project.cues[0].id]=="你好\n世界"
    assert validate_project(project).ok
    assert project.generation_metadata["language"]["code"]=="en"
    # Each word has a source onset: they are the caption's words (2026-10-26).
    assert [(w.text,w.start_ms,w.end_ms) for w in cue_words(project,project.cues[0])[0]]==[
        ("hello",11000,12000),("world",12000,13000)]
    assert allocate_split_times(project.cues[0],[5],project=project) == ([(11000,12000),(12000,13000)],False)
    count=len(project.video_tracks[0].clips)
    duplicate=LinkImportCommand(project,bundle(),media(),position_ms=10000)
    assert duplicate.result["status"]=="already_imported" and duplicate.isObsolete()
    path=tmp_path/"download.2byteproj"
    save_project(project,path)
    reopened=load_project(path)
    assert [(c.text,c.start_ms) for c in reopened.cues]==[("hello world",11000),("yes",13500)]
    assert len(reopened.video_tracks[0].clips)==count
    assert validate_project(reopened).ok
    command.undo()
    assert project.cues==[] and project.media.path==""
    assert project.asr_evidence=={} and "link_imports" not in project.studio_state
    command.redo()
    assert len(project.cues)==2 and validate_project(project).ok


def test_existing_edits_survive_append_and_only_selected_source_can_replace():
    project=SubtitleProject(media=StudioMedia(path="/old.mp4",duration_ms=6000),
        cues=[StudioCue(id="edited",start_ms=100,end_ms=1000,text="用户改过的字幕")])
    project.validate()
    command=LinkImportCommand(project,bundle(),media(),position_ms=6000)
    command.redo()
    assert next(c for c in project.cues if c.id=="edited").text=="用户改过的字幕"
    added=next(c for c in project.cues if c.text=="hello world")
    added.text="a manual edit"
    repeat=LinkImportCommand(project,bundle(),media())
    assert repeat.result["status"]=="already_imported"
    assert added.text=="a manual edit"
    replace=LinkImportCommand(project,bundle(),clip_id=command.result["clip_id"],replace_source=True)
    replace.redo()
    assert len(project.cues)==3
    assert next(c for c in project.cues if c.id=="edited").text=="用户改过的字幕"
    replace.undo()
    assert any(c.text=="a manual edit" for c in project.cues)


def test_segment_start_mapping_is_invalid_after_text_edit_and_translation_is_stale():
    from twobyteasr.projects.subtitle_consistency import word_receipt_problem
    project=SubtitleProject(media=StudioMedia(path=""))
    project.validate()
    LinkImportCommand(project,bundle(),media()).redo()
    cue=project.cues[0]
    assert cue_start_anchors(project,cue)
    cue.text="hello changed"
    assert not cue_start_anchors(project,cue)
    # The replaced word keeps its source word's span, like recognized captions.
    assert [(w.text,w.start_ms,w.end_ms) for w in cue_words(project,cue)[0]]==[("hello",1000,2000),("changed",2000,3000)]
    assert cue_status(project,cue)==NEEDS_UPDATE
    assert allocate_split_times(cue,[5],project=project)==([(1000,2000),(2000,3000)],False)
    receipts=project.studio_state["caption_timeline"]["instances"]
    assert word_receipt_problem(receipts[cue.id],cue.text)[0]=="stale_word_alignment"
    # Onsets that do not reach every word stay segment anchors, invalidated by an edit.
    partial=bundle()
    partial["captions"]["primary"]["captions"][0]["anchors"]=partial["captions"]["primary"]["captions"][0]["anchors"][1:]
    project=SubtitleProject(media=StudioMedia(path=""))
    project.validate()
    LinkImportCommand(project,partial,media()).redo()
    cue=project.cues[0]
    assert cue_start_anchors(project,cue) and not cue_words(project,cue)[0]
    cue.text="hello changed"
    assert allocate_split_times(cue,[5],project=project)==([],True)
    receipts=project.studio_state["caption_timeline"]["instances"]
    assert word_receipt_problem(receipts[cue.id],cue.text)[0]=="stale_subtitle_anchors"
    # An uploaded (manual) track's row is sentence-only: no word indexes to invalidate.
    manual=bundle()
    manual["manifest"]["subtitles"][0]["track"]["source"]="manual"
    project=SubtitleProject(media=StudioMedia(path=""))
    project.validate()
    LinkImportCommand(project,manual,media()).redo()
    sentence=project.cues[1]
    assert not cue_words(project,sentence)[0]
    sentence.text="edited sentence"
    receipts=project.studio_state["caption_timeline"]["instances"]
    assert word_receipt_problem(receipts[sentence.id],sentence.text) is None


def test_subtitles_only_requires_explicit_identity_and_maps_trimmed_fast_instance():
    project=SubtitleProject(media=StudioMedia(path="/video.mp4",duration_ms=6000))
    project.validate()
    clip=project.video_tracks[0].clips[0]
    clip.source_in_ms=1000;clip.source_out_ms=5000
    clip.timeline_in_ms=10000;clip.timeline_out_ms=12000;clip.playback_rate=2
    with pytest.raises(ValueError,match="身份"):
        LinkImportCommand(project,bundle(),clip_id=clip.id)
    command=LinkImportCommand(project,bundle(),clip_id=clip.id,confirmed_media=True)
    command.redo()
    assert [(c.start_ms,c.end_ms) for c in project.cues]==[(10000,11000),(11250,11750)]
    assert cue_start_anchors(project,project.cues[0])[1]["start_ms"]==10500


def test_interval_pairing_does_not_force_many_source_rows_to_one_translation():
    primary=[dict(start_ms=0,end_ms=1000),dict(start_ms=1000,end_ms=2000)]
    pairs,unmatched=interval_pairs(primary,[dict(start_ms=0,end_ms=2000)])
    assert pairs=={} and unmatched==[0]


def test_large_interval_matching_does_not_scan_every_pair():
    import time
    rows=[dict(start_ms=i*1000,end_ms=i*1000+800) for i in range(5000)]
    start=time.monotonic()
    pairs,unmatched=interval_pairs(rows,rows)
    assert len(pairs)==5000 and unmatched==[] and pairs[4999]==[4999]
    assert time.monotonic()-start<1.0


def test_explicit_segment_duration_maps_with_onset_and_ends_that_word():
    data=bundle()
    data["captions"]["primary"]["captions"][0]["anchors"][0].update(end_ms=1100,precision="segment_interval")
    project=SubtitleProject(media=StudioMedia(path=""));project.validate()
    LinkImportCommand(project,data,media(),position_ms=10000).redo()
    anchor=cue_start_anchors(project,project.cues[0])[0]
    assert (anchor["start_ms"],anchor["end_ms"],anchor["source_end_ms"])==(11000,11100,1100)
    assert [(w.start_ms,w.end_ms) for w in cue_words(project,project.cues[0])[0]]==[(11000,11100),(12000,13000)]


def test_target_generation_and_project_identity_both_required():
    page=SimpleNamespace(project=SimpleNamespace(project_id="a"),session=SimpleNamespace(generation=3))
    assert target_matches(page,dict(project_id="a",generation=3))
    assert not target_matches(page,dict(project_id="b",generation=3))
    assert not target_matches(page,dict(project_id="a",generation=2))
    page._close_requested=True
    assert not target_matches(page,dict(project_id="a",generation=3))
    page._close_requested=False
    page.project=None
    assert not target_matches(page,dict(project_id="a",generation=3))
    from PySide6.QtCore import QObject
    from shiboken6 import delete
    destroyed=QObject()
    destroyed.project=SimpleNamespace(project_id="a")
    destroyed.session=SimpleNamespace(generation=3)
    delete(destroyed)
    assert not target_matches(destroyed,dict(project_id="a",generation=3))


def test_download_caption_follows_its_clip_move_and_razor_with_undo():
    from twobyteasr.timeline.studio_clip_edit import clip_edit_command
    project=SubtitleProject(media=StudioMedia(path=""))
    project.validate()
    LinkImportCommand(project,bundle(),media()).redo()
    lane=project.video_tracks[0]
    clip=lane.clips[0]
    move=clip_edit_command(project,lane.id,"move",clip_id=clip.id,start=10000)
    move.redo()
    assert [(c.start_ms,c.end_ms) for c in project.cues]==[(11000,13000),(13500,14500)]
    assert cue_start_anchors(project,project.cues[0])[1]["start_ms"]==12000
    split=clip_edit_command(project,lane.id,"split",clip_id=clip.id,time_ms=12000)
    split.redo()
    assert [(c.start_ms,c.end_ms) for c in project.cues]==[(11000,13000),(13500,14500)]
    split.undo();move.undo()
    assert [(c.start_ms,c.end_ms) for c in project.cues]==[(1000,3000),(3500,4500)]


def test_saved_project_recovers_entire_moved_task_folder_without_replacing_edits(tmp_path):
    import json
    from dataclasses import replace
    from twobyteasr.media.link_catalog import subtitle_tracks
    from twobyteasr.media.link_manifest import preserve_subtitle,file_receipt,atomic_json,load_bundle
    folder=tmp_path/"original";folder.mkdir()
    video=folder/"BaW_jenozKc.mp4";video.write_bytes(b"exact original media")
    track=subtitle_tracks(dict(id="BaW_jenozKc",subtitles={"en":[
        dict(ext="json3",url="https://youtube.com/api/timedtext?lang=en")]}))[0]
    sub=preserve_subtitle(folder,track,json.dumps(dict(events=[
        dict(tStartMs=1000,dDurationMs=1000,segs=[dict(utf8="before edit")])])).encode(),"json3")
    manifest=folder/"download.2byte-download.json"
    atomic_json(manifest,dict(version=1,task_id="portable",platform="Youtube",video_id="BaW_jenozKc",
        primary_track_id=track["track_id"],subtitles=[sub],media=file_receipt(folder,video)))
    project=SubtitleProject(media=StudioMedia(path=""));project.validate()
    LinkImportCommand(project,load_bundle(manifest),replace(media(),source_path=str(video))).redo()
    project.cues[0].text="user edited"
    path=save_project(project,folder/"project/portable.2byteproj")
    moved=tmp_path/"moved";folder.rename(moved)
    reopened=load_project(moved/"project/portable.2byteproj")
    assert reopened.media.path==str(moved/video.name)
    assert reopened.media_pool[0].canonical_source==str(moved/video.name)
    assert reopened.cues[0].text=="user edited" and validate_project(reopened).ok


def test_edited_merge_keeps_both_translation_parents_and_undo(tmp_path):
    from twobyteasr.timeline.studio_commands import merge_cues_command
    from twobyteasr.subtitle_rules.subtitle_translation import split_merge_candidates,records_of
    project=SubtitleProject(media=StudioMedia(path=""));project.validate()
    LinkImportCommand(project,bundle(),media()).redo()
    ids=[cue.id for cue in project.cues]
    project.cues[0].text="Changed spelling"
    merge=merge_cues_command(project,ids);merge.redo()
    candidates=split_merge_candidates(project)
    assert len(candidates)==1
    assert {parent["cue_id"] for parent in candidates[0]["parents"]}==set(ids)
    records = records_of(project)
    assert set(records) == {project.cues[0].id} and validate_project(project).ok
    assert {part["cue_id"] for part in records[project.cues[0].id]["merge_sources"]} == set(ids)
    assert all(part["download_track"] for part in records[project.cues[0].id]["merge_sources"])
    reopened = load_project(save_project(project, tmp_path/"merged.2byteproj"))
    assert {parent["cue_id"] for parent in split_merge_candidates(reopened)[0]["parents"]} == set(ids)
    merge.undo()
    assert len(project.cues)==2 and project.cues[0].text=="Changed spelling"
    assert set(ids)<=set(records_of(project))


def test_audio_only_copy_of_a_video_already_here_is_new_media():
    project=SubtitleProject(media=StudioMedia(path=""))
    video=bundle()
    video["manifest"]["media"]=dict(path="video.mp4",sha256="video-sha")
    LinkImportCommand(project,video,media(),position_ms=0).redo()
    assert len(project.cues)==2 and len(project.media_pool)==1
    audio=dict(manifest_path="/download2/download.2byte-download.json",media_path="/audio.m4a",
        manifest=dict(task_id="task2",platform="Youtube",video_id="BaW_jenozKc",source_url="",
            primary_track_id="",translation_track_id="",subtitles=[],media=dict(path="audio.m4a",sha256="audio-sha")),
        captions={})
    sound=MediaIngestResult(generation=0,project_token="",source_path="/audio.m4a",
        duration_ms=6000,has_video=False,has_audio=True)
    command=LinkImportCommand(project,audio,sound,position_ms=7000)
    command.redo()
    assert len(project.media_pool)==2 and command.result["clip_id"]
    assert any(not asset.video_metadata["has_video"] for asset in project.media_pool)
    assert len(project.cues)==2 and validate_project(project).ok
    command.undo()
    assert len(project.media_pool)==1
