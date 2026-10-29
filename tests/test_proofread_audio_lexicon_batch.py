"""User examples, actual library overlays, scoped bulk review and audio races."""
import copy
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import subtitle_core as legacy
from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage, _StandalonePage, _issue
from twobyteasr.glossary.proofread_batch import adoption_text
from twobyteasr.glossary.proofread_rules import normalize_occurrence, DECISIONS_KEY
from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
from twobyteasr.glossary.term_editing import library_terms, edit_term
from twobyteasr.glossary.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry, TermResolver, snapshot_glossaries
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia, StudioSpeaker, load_project, save_project
from twobyteasr.studio.studio_text_tools import TextOccurrence

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def snapshot():
    return GlossarySnapshot((GlossaryLibrary("selected", "已选库", "r1",
        tuple(TermEntry(n) for n in ("泥浆铠甲", "降灵", "减益", "骨龙"))),))


@pytest.mark.parametrize("source,target,text,start", [
    ("泥浆铠甲啊", "泥浆铠甲", "泥浆铠甲啊", 0),
    ("精灵", "降灵", "这个精灵有意思", 2),
    ("减一", "减益", "啊 属性减一", 4),
    ("降一", "降益", "等级降一", 2),
    ("三次", "山刺", "再打三次", 2),
])
@pytest.mark.parametrize("kind", ["local_review", "ai_review", "ai_accepted"])
def test_inferred_false_corrections_never_enter_page(snapshot, source, target, text, start, kind):
    resolver = TermResolver(snapshot)
    hit = TextOccurrence("id", 0, source, target, (start, start+len(source)), source=kind)
    assert normalize_occurrence(hit, text, resolver) is None


def test_local_and_ai_service_share_guard_and_keep_one_wrong_char_in_full_word(snapshot, monkeypatch):
    import twobyteasr.providers.asr_provider_snapshot as provider
    import twobyteasr.subtitle_rules.polishing as polish
    monkeypatch.setattr(provider, "resolve_provider_snapshot", lambda *_a, **_k: SimpleNamespace(
        public_identity=lambda: {"model": "offline-test"}, timeout_policy=SimpleNamespace(total=120)))
    targets = {1: "泥浆铠甲", 2: "这个降灵有意思", 3: "啊 属性减益", 4: "骨龙来了"}
    monkeypatch.setattr(polish, "prepare_correction_request", lambda *_a, **_k: None)
    monkeypatch.setattr(polish, "call_correction_api", lambda *_a, **_k: polish.PolishBatchResult(targets))
    p = SubtitleProject(StudioMedia(""), cues=[StudioCue(str(i), i*3000, i*3000+2000, t)
        for i,t in enumerate(("泥浆铠甲啊", "这个精灵有意思", "啊 属性减一", "骨笼来了"), 1)])
    for ai in (False, True):
        result = preview_glossary_correction(p, [c.id for c in p.cues], snapshot, {}, use_ai=ai)
        assert not any(h.cue_id in {"1", "2", "3"} for h in result.hits)
        assert any(h.original == "骨笼" and h.replacement == "骨龙" for h in result.hits)


def test_numeric_alias_and_consistency_are_context_guarded():
    from twobyteasr.glossary.terminology import snapshot_from_pairs
    from twobyteasr.subtitle_rules.stutter_cleanup import consistency_occurrences
    resolver = TermResolver(snapshot_from_pairs([("减一", "减益")]))
    assert resolver.resolve("属性减一").text == "属性减一"
    assert not consistency_occurrences([("a", 0, "减益"), ("b", 1000, "属性减一")], preferred=("减益",))
    assert consistency_occurrences([("a", 0, "源石"), ("b", 1000, "原石")], preferred=("源石",))


@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path/"terms.json"))
    monkeypatch.setattr(legacy, "load_game_profiles", lambda: {"test": {"identity": "test", "terms": [
        {"canonical": "骨龙", "aliases": ["古龙", "骨笼"], "replacement_mode": "global"}]}})
    monkeypatch.setattr(legacy, "_profile_lexicon_paths_for", lambda *_: [])
    return tmp_path


def test_edit_builtin_alias_uses_persistent_overlay_and_undo(storage):
    old = snapshot_glossaries(legacy, ["test"])
    record = library_terms(old)[0]
    change = edit_term(legacy, record, "骨龙", ["骨笼"])
    fresh = snapshot_glossaries(legacy, ["test"])
    assert library_terms(fresh)[0].aliases == ("骨笼",)
    resolver = TermResolver(fresh)
    assert resolver.resolve("古龙来了").text == "古龙来了"
    assert resolver.resolve("骨笼来了").text == "骨龙来了"
    # Reload all data from disk, then restore only this library's original entry.
    assert json.loads((storage/"terms.json").read_text("utf-8"))["games"]["test"]["hidden_reference_terms"] == ["骨龙"]
    change.undo(legacy)
    assert TermResolver(snapshot_glossaries(legacy, ["test"])).resolve("古龙来了").text == "骨龙来了"


def test_delete_and_rename_term_are_distinct_and_stale_edit_refuses(storage):
    record = library_terms(snapshot_glossaries(legacy, ["test"]))[0]
    change = edit_term(legacy, record, "骨龙王", ["骨笼"])
    with pytest.raises(ValueError, match="更新"):
        edit_term(legacy, record, delete=True)
    fresh = library_terms(snapshot_glossaries(legacy, ["test"]))
    assert [(r.canonical, r.aliases) for r in fresh] == [("骨龙王", ("骨笼",))]
    deletion = edit_term(legacy, fresh[0], delete=True)
    assert not library_terms(snapshot_glossaries(legacy, ["test"]))
    deletion.undo(legacy)
    change.undo(legacy)
    assert library_terms(snapshot_glossaries(legacy, ["test"]))[0].canonical == "骨龙"


def test_same_term_from_two_selected_libraries_does_not_merge_provenance(snapshot):
    second = GlossaryLibrary("other", "另一个库", "r2", (TermEntry("降灵", ("降玲",)),))
    records = [r for r in library_terms(GlossarySnapshot((*snapshot.libraries, second))) if r.canonical == "降灵"]
    assert len(records) == 2 and {r.library_id for r in records} == {"selected", "other"}


def test_unconfirmed_ai_targets_never_join_real_normative_list(snapshot):
    guessed=GlossaryLibrary("guess","未确认的库","r",(TermEntry("临时猜测",confirmed=False,provenance="candidate"),))
    assert not library_terms(GlossarySnapshot((guessed,)))


def test_library_undo_preserves_other_library_and_refuses_later_changes(storage):
    record=library_terms(snapshot_glossaries(legacy,["test"]))[0]
    change=edit_term(legacy,record,"骨龙",["骨笼"])
    other=legacy.create_learned_content("别处资料",create_new=True)
    legacy.add_learned_mapping(other,"dragon","dragon")
    change.undo(legacy)
    assert TermResolver(snapshot_glossaries(legacy,[other])).resolve("DRAGON").text=="dragon"
    record=library_terms(snapshot_glossaries(legacy,["test"]))[0]
    change=edit_term(legacy,record,"骨龙",["骨笼"])
    legacy.add_learned_mapping("test","新别名","骨龙")
    with pytest.raises(ValueError,match="别处修改"):
        change.undo(legacy)


def test_canonical_can_be_edited_only_in_case(storage):
    identity=legacy.create_learned_content("选手库",create_new=True)
    legacy.add_learned_mapping(identity,"NameID","NameID")
    record=library_terms(snapshot_glossaries(legacy,[identity]))[0]
    edit_term(legacy,record,"NAMEid",[])
    assert TermResolver(snapshot_glossaries(legacy,[identity])).resolve("nameid").text=="NAMEid"


@pytest.fixture
def page(tmp_path):
    p = SubtitleProject(StudioMedia("", duration_ms=3000000), cues=[
        StudioCue(f"stable-{i}", i*3000, i*3000+2000, "古龙和火龙来了", speaker_id="B" if i%2 else "A")
        for i in range(744)], speakers=[StudioSpeaker("A", "甲"), StudioSpeaker("B", "乙")],
        generation_metadata={"translations": {"stable-0": "日本語"}})
    p.validate()
    widget = GlossaryProofreadPage(SimpleNamespace(studio_page=None))
    widget._project = p
    widget._project_path = str(tmp_path/"work.2byteproj")
    widget._standalone = _StandalonePage(p)
    widget._bind_stack(widget._standalone.session.undo_stack)
    widget._build_rows(p, start_checks=False)
    for row in widget._rows:
        row["issues"] = [_issue("term", (0, 2), "古龙", "骨龙王", checked=False),
                         _issue("near", (3, 5), "火龙", "火笼", checked=False)]
    widget._apply_filter()
    yield widget, p
    widget._save_timer.stop(); widget._rematch_timer.stop()
    if hasattr(widget, "_local_timer"): widget._local_timer.stop()
    widget.shutdown(); widget.close(); widget.deleteLater(); APP.processEvents()


def test_batch_filter_scope_stable_ids_all_rows_not_only_viewport(page):
    widget,p = page
    widget.speaker_filter.setCurrentIndex(widget.speaker_filter.findData("A"))
    widget._batch_select_all()
    assert len(widget._batch_selected) == 372
    assert "744" in widget.batch_count.text()
    widget.search.setText("no matches"); widget._apply_filter()
    assert not widget._batch_selected
    widget.search.clear(); p.speakers[1].hidden = True
    widget.speaker_filter.setCurrentIndex(0); widget._apply_filter(); widget._batch_select_all()
    assert widget._batch_selected == {f"stable-{i}" for i in range(0,744,2)}
    widget._rows.reverse(); widget._row_indexes = {r['cue_id']:n for n,r in enumerate(widget._rows)}
    widget.list.set_rows(widget._rows); widget._apply_filter()
    assert widget._batch_selected == {f"stable-{i}" for i in range(0,744,2)}


def test_batch_ignore_all_issues_one_undo_persistence_no_text_change(page, tmp_path):
    widget,p = page
    before = copy.deepcopy((p.cues,p.generation_metadata))
    widget.filter_buttons["suggested"].setChecked(True); widget._apply_filter()
    widget._batch_select_all(); widget._batch_ignore()
    assert not widget.list.visible
    assert len(p.studio_state[DECISIONS_KEY]) == 744
    assert (p.cues,p.generation_metadata) == before
    assert widget.proposal_counts()["ignored"] == 744
    assert widget._stack.count() == 1
    path=tmp_path/"reopen.2byteproj"; save_project(p,path)
    assert len(load_project(path).studio_state[DECISIONS_KEY]) == 744
    widget._undo(); assert len(widget.list.visible) == 744
    widget._redo(); assert not widget.list.visible


def test_batch_adopt_multiple_length_changes_preserves_other_fields_and_undo(page):
    widget,p = page
    times=[(c.id,c.start_ms,c.end_ms,c.speaker_id) for c in p.cues]
    widget.search.setText("古龙"); widget._apply_filter()
    widget._batch_selected={"stable-0","stable-1"}; widget._batch_adopt()
    assert [c.text for c in p.cues[:3]] == ["骨龙王和火笼来了", "骨龙王和火笼来了", "古龙和火龙来了"]
    assert times == [(c.id,c.start_ms,c.end_ms,c.speaker_id) for c in p.cues]
    assert p.generation_metadata["translations"]["stable-0"] == "日本語"
    assert widget._stack.count() == 1
    widget._undo(); assert all(c.text == "古龙和火龙来了" for c in p.cues)
    widget._redo(); assert p.cues[0].text == "骨龙王和火笼来了"


def test_batch_adoption_keeps_manual_translation_and_derives_update_status(page):
    from twobyteasr.subtitle_rules import subtitle_translation as st
    widget,p=page
    st.set_manual(p,"stable-0","手动译文")
    before=copy.deepcopy(st.records_of(p)["stable-0"])
    assert st.cue_status(p,p.cues[0])==st.MANUAL
    widget._batch_selected={"stable-0"};widget._batch_adopt()
    assert st.records_of(p)["stable-0"]["text"]=="手动译文"
    assert st.cue_status(p,p.cues[0])==st.NEEDS_UPDATE
    widget._undo()
    assert st.records_of(p)["stable-0"]==before and st.cue_status(p,p.cues[0])==st.MANUAL


def test_bulk_ignore_preserves_unaffected_scroll_anchor(page):
    widget,p=page
    widget.resize(1500,900);widget.show();widget.filter_buttons["suggested"].click();APP.processEvents()
    widget.list.ensure_visible("stable-300");APP.processEvents()
    anchor=widget.list._top_anchor()[0]
    widget._batch_selected={f"stable-{i}" for i in range(12)};widget._batch_ignore();APP.processEvents()
    assert widget.list._top_anchor()[0]==anchor


def test_audio_finished_status_does_not_overwrite_other_feedback(page):
    widget,p=page
    widget._playing_changed("stable-0","playing");widget._playing_changed("stable-0","")
    assert "已结束" in widget.status_label.text()
    widget._playing_changed("stable-0","playing");widget._set_status("工程已保存")
    widget._playing_changed("stable-0","")
    assert widget.status_label.text()=="工程已保存"


def test_library_scope_switch_discards_old_pending_sources_but_keeps_written_text(page,monkeypatch):
    widget,p=page;row=widget._rows[0];before=[c.text for c in p.cues]
    row["issues"] += [_issue("consistency",(0,2),"古龙","旧库规范",checked=False),
                      _issue("ai",(3,5),"火龙","用户确认",checked=True)]
    monkeypatch.setattr(widget,"_read_snapshot",lambda:setattr(widget,"_snapshot",GlossarySnapshot()))
    monkeypatch.setattr(widget,"_run",lambda *_a,**_k:None)
    monkeypatch.setattr(widget,"_schedule_local_checks",lambda *_a,**_k:None)
    widget._reset_library_proposals()
    assert all(i["checked"] for i in row["issues"]) and [c.text for c in p.cues]==before


def test_overlap_and_stale_proposals_are_reported_without_finishing(page):
    widget,p=page
    row=widget._rows[0]
    row["issues"].append(_issue("near",(1,4),row["base"][1:4],"错词",checked=False))
    widget._apply_filter(); widget._batch_selected={row["cue_id"]}; widget._batch_adopt()
    assert "未处理" in widget.status_label.text()
    assert any(not i["checked"] for i in row["issues"])
    with pytest.raises(ValueError,match="重叠"):
        adoption_text("abcd",[{"span":(0,2),"original":"ab","replacement":"x"},
                              {"span":(1,3),"original":"bc","replacement":"y"}])
    with pytest.raises(ValueError,match="原文"):
        adoption_text("abcd",[{"span":(0,2),"original":"zz","replacement":"x"}])


def test_row_area_toggles_but_play_and_details_do_not(page, monkeypatch):
    widget,p=page
    widget.resize(1500,900); widget.show(); APP.processEvents()
    widget.list.repaint(); row=widget._rows[0]
    point=next(rect.center().toPoint() for rect,action,c,_ in widget.list._hit_boxes
               if action=='rowcheck' and c==row['cue_id'])
    QTest.mouseClick(widget.list,Qt.MouseButton.LeftButton,pos=point)
    assert widget._batch_selected == {row["cue_id"]}
    plays=[]; widget.list.play_requested.disconnect(); widget.list.play_requested.connect(plays.append)
    widget.list.repaint()
    box=next(r for r,a,c,_ in widget.list._hit_boxes if a=="play" and c==row["cue_id"])
    QTest.mouseClick(widget.list,Qt.MouseButton.LeftButton,pos=box.center().toPoint())
    assert plays == [row["cue_id"]] and widget._batch_selected == {row["cue_id"]}
    row["issues"][0]["provenance"] = {"source":"真实词库", "rule":"已确认别名"}
    row.pop("_groups",None); widget.list._layout_cache.clear(); widget.list.refresh_row(row["cue_id"]); widget.list.repaint()
    detail=next(r for r,a,c,_ in widget.list._hit_boxes if a=="detail" and c==row["cue_id"])
    QTest.mouseClick(widget.list,Qt.MouseButton.LeftButton,pos=detail.center().toPoint()); APP.processEvents()
    assert widget._batch_selected == {row["cue_id"]}
    lines=widget.list._detail_lines(row,widget._groups(row)[0])
    assert any("真实词库" in l["text"] for l in lines) and any("命中规则" in l["text"] for l in lines)


def test_pause_during_decode_never_autostarts_and_stale_callback_is_ignored(monkeypatch):
    from twobyteasr.playback.cue_player import CuePlayer
    player=CuePlayer(); player.request_id="new"; player.cue_id="a"; player.state="loading"; player._wants_play=True
    monkeypatch.setattr(player,"_ensure_sink",lambda: pytest.fail("paused or stale decode must not open output"))
    player.pause(); player._start("old",b"\0"*19200); player._start("new",b"\0"*19200)
    assert player.state == "paused" and player._payload and not player._end_timer.isActive()
    player.stop(); player._start("new",b"\0"*19200)
    assert not player.cue_id


def test_audio_cache_identity_and_late_boundary_change(tmp_path):
    import wave,weakref
    from twobyteasr.playback.cue_audio_preview import plan_cue_preview,preview_cache_key
    from twobyteasr.playback.cue_player import CuePlayer
    source=tmp_path/"sound.wav"
    with wave.open(str(source),"wb") as stream:
        stream.setnchannels(2);stream.setsampwidth(2);stream.setframerate(48000);stream.writeframes(b"\0"*192000)
    p=SubtitleProject(StudioMedia(str(source),duration_ms=1000),cues=[StudioCue("a",100,500,"当前字幕")],render_settings={"_cue_domain":"timeline"})
    p.validate();plan=plan_cue_preview(p,"a");key=preview_cache_key(plan)
    stream_plan=copy.deepcopy(plan);stream_plan.layers[0]["stream_index"]=2
    gain_plan=copy.deepcopy(plan);gain_plan.layers[0]["gain_db"]=-10
    assert key!=preview_cache_key(stream_plan) and key!=preview_cache_key(gain_plan)
    player=CuePlayer();player._project_ref=weakref.ref(p);player._key=key
    player.cue_id="a";player.request_id="r";player.state="loading";player._wants_play=True
    errors=[];player.failed.connect(errors.append)
    p.cues[0].end_ms=600
    assert key!=preview_cache_key(plan_cue_preview(p,"a"))
    player._start("r",b"\0"*19200)
    assert player.state=="failed" and errors and player._sink is None
    player.shutdown()


def test_natural_audio_end_drains_tail_while_explicit_stop_discards_it():
    from twobyteasr.playback.cue_player import CuePlayer
    from PySide6.QtMultimedia import QAudio
    calls=[]
    player=CuePlayer();player.request_id="r";player.cue_id="a";player._expected_ms=1000
    player._sink=SimpleNamespace(processedUSecs=lambda:1000000,state=lambda:QAudio.State.IdleState,
        error=lambda:QAudio.Error.NoError,bufferSize=lambda:7680,stop=lambda:calls.append("drain"),reset=lambda:calls.append("discard"))
    player._check_finished()
    assert calls==[] and player._drain_deadline is not None and player.cue_id=="a"
    player._drain_deadline=0;player._check_finished()
    assert calls==["drain"] and not player.cue_id
    player.stop();assert calls==["drain","discard"]
