"""Consume A's shared contract using B's selected export scope and saved edits."""
import copy
import json

import pytest

from twobyteasr.exports.export_consistency import SubtitleDataError
from twobyteasr.exports.studio_subtitle_export import (SubtitleExportOptions, SubtitleExportArtifact,
    export_subtitle_artifacts, export_language_layers, verify_subtitle_artifact)
from twobyteasr.exports.subtitle_rescue import rescue_subtitles
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project


def project():
    p=SubtitleProject(StudioMedia("missing.mp4",duration_ms=5000),
       cues=[StudioCue("c",1000,1800,"最后手工修改\n","S02",original_text="ASR 原文")],
       speakers=[StudioSpeaker("S02","S02")])
    p.validate();p.render_settings["_cue_domain"]="timeline"
    p.studio_state["caption_timeline"]={"version":1,"instances":{"c":{
        "text":"ASR 原文","words":[{"text":"ASR 原文","start_ms":99999,"end_ms":99999,"char_start":0,"char_end":100}]}}}
    return p


def test_stale_words_do_not_block_srt_or_export_invalid_word_json(tmp_path):
    p=project();before=copy.deepcopy(p.to_dict())
    artifacts=export_subtitle_artifacts(p,tmp_path,"edited",SubtitleExportOptions(frozenset({"srt","json"}),"per_speaker"))
    srt=next(a.path for a in artifacts if a.format=="srt").read_text(encoding="utf-8")
    row=json.loads(next(a.path for a in artifacts if a.format=="json").read_text(encoding="utf-8"))["cues"][0]
    assert "最后手工修改\n" in srt and "00:00:01,000 --> 00:00:01,800" in srt
    assert row["text"]==row["original_text"]=="最后手工修改\n"
    assert row["word_timing"]["pieces"]==[] and "stale_word_alignment" in row["word_timing"]["basis"]
    assert p.to_dict()==before


def test_rescue_records_nonblocking_warnings_without_reverting_manual_text(tmp_path):
    p=project();source=save_project(p,tmp_path/"old.2byteproj")
    out=rescue_subtitles(source,tmp_path/"out")
    data=json.loads((out/"rescue-manifest.json").read_text(encoding="utf-8"))
    assert data["consistency"]["ok"]
    assert data["consistency"]["warnings"][0]["code"]=="stale_word_alignment"
    assert "最后手工修改\n" in next(out.glob("*_S02.srt")).read_text(encoding="utf-8")


def test_hidden_invalid_source_is_outside_normal_export_scope(tmp_path):
    p=project();p.speakers.append(StudioSpeaker("HIDDEN","隐藏",hidden=True))
    p.cues.append(StudioCue("hidden",1000,1800,"不可用来源","HIDDEN",evidence_refs=["missing-ref"]))
    artifacts=export_subtitle_artifacts(p,tmp_path,"selected",SubtitleExportOptions(frozenset({"srt"}),"per_speaker"))
    assert len(artifacts)==1 and artifacts[0].cue_count==1 and artifacts[0].speaker_id=="S02"


def test_conflicting_source_in_selected_scope_is_not_silently_dropped(tmp_path):
    p=project();p.cues[0].evidence_refs=["missing-ref"]
    with pytest.raises(SubtitleDataError) as error:
        export_subtitle_artifacts(p,tmp_path,"conflict",SubtitleExportOptions())
    assert error.value.result.errors[0].cue_id=="c"
    assert not list(tmp_path.glob("*.srt"))


def test_bilingual_export_compares_selected_layer_and_speaker_only(tmp_path):
    p=project();p.generation_metadata["translations"]={"c":"日本語の翻訳\n"}
    artifacts=export_language_layers(p,tmp_path,"bilingual",("original","translation","bilingual","json"),speaker_mode="per_speaker").artifacts
    assert len(artifacts)==4 and all(a.cue_count==1 for a in artifacts)
    assert "最后手工修改" in next(a.path for a in artifacts if a.layer=="original").read_text(encoding="utf-8")
    assert "日本語の翻訳" in next(a.path for a in artifacts if a.layer=="translation").read_text(encoding="utf-8")


@pytest.mark.parametrize("field,value,code", [
    ("start_ms",1000.4,"sentence_time_invalid"),
    ("start_ms",True,"sentence_time_invalid"),
    ("text",123,"cue_text_invalid"),
    ("evidence_refs",[""],"source_reference_invalid"),
    ("speaker_id","  ","speaker_id_invalid"),
])
def test_pre_normalization_errors_are_not_coerced_away(field,value,code,tmp_path):
    p=project();setattr(p.cues[0],field,value)
    for layers in (False,True):
        with pytest.raises(SubtitleDataError) as caught:
            if layers:export_language_layers(p,tmp_path,"bad",("original",))
            else:export_subtitle_artifacts(p,tmp_path,"bad",SubtitleExportOptions())
        assert any(issue.code==code for issue in caught.value.result.errors)
        assert getattr(p.cues[0],field)==value
    assert not list(tmp_path.glob("*.srt"))


def test_raw_saved_references_cannot_be_cleaned_away_by_rescue_loader(tmp_path):
    payload=project().to_dict();payload["cues"][0]["evidence_refs"]=[""]
    source=tmp_path/"raw.json";source.write_text(json.dumps(payload),encoding="utf-8")
    with pytest.raises(SubtitleDataError) as caught:rescue_subtitles(source,tmp_path/"out")
    assert caught.value.result.errors[0].code=="source_reference_invalid"
    assert not (tmp_path/"out").exists()


def test_hidden_invalid_sentence_is_outside_normal_scope(tmp_path):
    p=project();p.speakers.append(StudioSpeaker("HIDDEN","隐藏",hidden=True))
    p.cues.append(StudioCue("hidden",-1,-2,"不在选择范围","HIDDEN"))
    artifacts=export_subtitle_artifacts(p,tmp_path,"visible",SubtitleExportOptions())
    assert len(artifacts)==1 and artifacts[0].cue_count==1


@pytest.mark.parametrize("content", ['{"cues":[', '{"cues":null}', '{"cues":{}}'])
def test_bad_json_readback_reports_structural_failure(tmp_path,content):
    path=tmp_path/"broken.json";path.write_text(content,encoding="utf-8")
    result=verify_subtitle_artifact(SubtitleExportArtifact(path,"json","S02",1),project())
    assert not result.valid and not result.structure_valid
    assert result.expected_cue_count==1 and result.cue_count==0
    assert result.first_mismatch["cue_id"]=="c" and result.first_mismatch["field"]=="structure"


@pytest.mark.parametrize("kind", ["invalid_word_time","invalid_acoustic_index","stale_alignment_text"])
def test_json_never_reuses_invalid_direct_alignment_rows(tmp_path,kind):
    p=project();p.studio_state.pop("caption_timeline",None)
    word={"text":"最","start_ms":1000,"end_ms":1200,"char_start":0,"char_end":1,"evidence_ref":"cue-align:c"}
    row={"cue_alignment":{},"text":p.cues[0].text,"words":[copy.deepcopy(word)]}
    if kind=="invalid_word_time":row["words"][0]["end_ms"]=1000
    elif kind=="invalid_acoustic_index":row["caption_arbitration"]={"acoustic_words":[dict(word,char_end=999)]}
    else:row["text"]="已过期的旧正文"
    p.asr_evidence["cue-align:c"]=row  # Direct lookup is legal without evidence_refs.
    before=copy.deepcopy(p.to_dict())
    artifacts=export_subtitle_artifacts(p,tmp_path,"words",SubtitleExportOptions(frozenset({"srt","json"})))
    result=json.loads(next(a.path for a in artifacts if a.format=="json").read_text(encoding="utf-8"))["cues"][0]
    assert result["word_timing"]["pieces"]==[]
    assert result["word_timing"]["basis"].startswith("unavailable:")
    assert result["original_text"]==p.cues[0].text and p.to_dict()==before
