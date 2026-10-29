"""New daily features must survive the proofread delta's older shared base."""
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

APP=QApplication.instance() or QApplication([])


def test_builtin_spelling_edit_keeps_correction_and_emphasis_flags(monkeypatch,tmp_path):
    import subtitle_core as legacy
    from twobyteasr.glossary.terminology import snapshot_glossaries,TermResolver
    from twobyteasr.glossary.term_editing import library_terms,edit_term
    monkeypatch.setattr(legacy,"LEARNED_TERMS_PATH",str(tmp_path/"terms.json"))
    monkeypatch.setattr(legacy,"load_game_profiles",lambda:{"库":{"identity":"flagtest","terms":[
        {"canonical":"骨龙","aliases":["古龙"],"replacement_mode":"global","correction_enabled":False,"emphasis_enabled":True}]}})
    monkeypatch.setattr(legacy,"_profile_lexicon_paths_for",lambda *_:[])
    record=library_terms(snapshot_glossaries(legacy,["flagtest"]))[0]
    edit_term(legacy,record,"骨龙",["骨笼"])
    snapshot=snapshot_glossaries(legacy,["flagtest"])
    term=next(t for l in snapshot.libraries for t in l.terms if t.canonical=="骨龙")
    assert not term.correction_enabled and term.emphasis_enabled
    assert TermResolver(snapshot).resolve("骨笼来了").text=="骨笼来了"


def test_track_picker_play_plan_api_uses_same_cancellable_player(monkeypatch,tmp_path):
    import twobyteasr.playback.cue_player as module
    from twobyteasr.playback.cue_audio_preview import CuePreviewPlan
    source=tmp_path/"lane.wav";source.write_bytes(b"fixture")
    class Decoder(QObject):
        decoded=Signal(str,bytes);failed=Signal(str,str);finished=Signal()
        def __init__(self,request_id,plan,parent):super().__init__(parent);self.started=False;self.cancelled=False
        def start(self):self.started=True
        def cancel(self):self.cancelled=True
        def wait(self,_ms):return True
    monkeypatch.setattr(module,"_PreviewThread",Decoder)
    plan=CuePreviewPlan("request-lane","project","revision","lane:A","A","timeline",(100,400),(100,400),
                        [{"source_path":str(source),"timeline_in_ms":0,"timeline_out_ms":1000,
                          "source_in_ms":0,"source_out_ms":1000}])
    player=module.CuePlayer();player.play_plan(plan,"picker-lane-A")
    assert player.cue_id=="picker-lane-A" and player._thread.started and player._still_current()
    worker=player._thread;player.pause();player._start("request-lane",b"\0"*19200)
    assert player.state=="paused" and player._sink is None
    player.stop();assert worker.cancelled and not player.request_id
    player.shutdown()
