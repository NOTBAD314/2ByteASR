"""Diagnostic stage enums and elapsed time only; no arguments or runtime data."""
API_VERSION=1

def setup(api):
    import functools, json, subprocess, threading, time
    from twobyteasr.glossary import terminology, summary_process, main_ui_glossary
    from twobyteasr.system import processes
    output=api.data_dir
    started=time.monotonic();lock=threading.Lock();count=0
    allowed={'snapshot:start','snapshot:end','snapshot:error','serialize:start','serialize:end','serialize:error',
             'summary:start','summary:end','summary:error','spawn:start','spawn:end','spawn:error',
             'communicate:start','communicate:wait','communicate:end','communicate:error',
             'coordinator:start','coordinator:end','coordinator:error','receive:start','receive:end','receive:error'}
    def note(stage):
        nonlocal count
        assert stage in allowed
        with lock:
            if count>=1000:return
            count+=1
            with (output/'phase-events.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(dict(stage=stage,seconds=round(time.monotonic()-started,4)))+'\n')
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
    wrap(terminology,'snapshot_glossaries','snapshot')
    wrap(terminology.GlossarySnapshot,'to_dict','serialize')
    wrap(summary_process,'summarize','summary')
    wrap(main_ui_glossary.TermLibraryDialog,'_start_batch_summary','coordinator')
    wrap(main_ui_glossary.TermLibraryDialog,'_receive_batch_summary','receive')
    original_spawn=processes.popen_hidden_subprocess
    def spawn(*args,**kwargs):
        if kwargs.get('purpose')!='glossary summary':return original_spawn(*args,**kwargs)
        note('spawn:start')
        try:process=original_spawn(*args,**kwargs)
        except BaseException:
            note('spawn:error');raise
        note('spawn:end')
        communicate=process.communicate
        def observed_communicate(*args,**kwargs):
            note('communicate:start')
            try:value=communicate(*args,**kwargs)
            except subprocess.TimeoutExpired:
                note('communicate:wait');raise
            except BaseException:
                note('communicate:error');raise
            note('communicate:end');return value
        process.communicate=observed_communicate
        return process
    processes.popen_hidden_subprocess=spawn
    (output/'phase-state.json').write_text(json.dumps(dict(started=True)),encoding='utf-8')
