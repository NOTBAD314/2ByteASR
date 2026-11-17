"""Fixed teardown phase names and elapsed seconds only."""
API_VERSION=1
def setup(api):
    import functools,json,threading,time
    from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage
    from twobyteasr.playback.cue_player import CuePlayer
    root=api.data_dir;start=time.monotonic();lock=threading.Lock()
    def note(stage):
        with lock:
            with (root/'exit-phases.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(dict(stage=stage,seconds=round(time.monotonic()-start,4)))+'\n')
    def wrap(owner,name,label):
        original=getattr(owner,name)
        @functools.wraps(original)
        def observed(*args,**kwargs):
            note(label+':start')
            try:value=original(*args,**kwargs)
            except BaseException:
                note(label+':error');raise
            note(label+':end');return value
        setattr(owner,name,observed)
    wrap(type(api.window),'closeEvent','window-close')
    wrap(GlossaryProofreadPage,'shutdown','review-shutdown')
    wrap(GlossaryProofreadPage,'_leave_review','review-leave')
    wrap(GlossaryProofreadPage,'_flush_save','review-save')
    wrap(CuePlayer,'shutdown','player-shutdown')
    wrap(CuePlayer,'stop','player-stop')
    api.app.aboutToQuit.connect(lambda:note('application-about-to-quit'))
    (root/'exit-phase-started.json').write_text(json.dumps(dict(started=True)),encoding='utf-8')
