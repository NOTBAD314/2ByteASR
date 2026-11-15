"""Host intake: privacy, persisted chat ownership, and configured billing identity."""
from types import SimpleNamespace

def test_new_read_and_memory_tools_obey_disabled_permissions():
    from twobyteasr.app import bunny_permissions as p
    from twobyteasr.app.bunny_tools import TOOLS
    for name in ['edit_cue', 'merge_cues', 'refine_cues', 'learned_edits']:
        assert p.refusal(TOOLS[name],dict(p.DEFAULTS,read_subtitles=False))
    for name in ['save_recipe','use_recipe']:
        assert p.refusal(TOOLS[name],dict(p.DEFAULTS,remember=False))
        assert p.refusal(TOOLS[name],dict(p.DEFAULTS,level='guide'))

def test_estimate_uses_real_endpoint_and_stage(monkeypatch):
    from twobyteasr.app import bunny_subtitle_tools as t
    from twobyteasr.providers import llm_config, usage_ledger
    stages=[]
    monkeypatch.setattr(t,'_settings',lambda:{})
    monkeypatch.setattr(llm_config,'endpoint_from_settings',lambda settings,stage:stages.append(stage) or dict(model='deepseek-chat',base_url='https://example.invalid/v1'))
    model,price=t._rates('polish')
    assert model=='deepseek-chat' and not price['known'] and stages==['polish']

def test_malformed_saved_chat_is_ignored_and_clear_invalidates_live_copy(tmp_path,monkeypatch):
    from twobyteasr.app import bunny_memory as m
    monkeypatch.setattr(m,'store_path',lambda:tmp_path/'memory.json')
    m.save_chat('project',[('user','你好')]);path=m._chat_path('project')
    path.write_text('{"items":[1,["user"],["user",3],["user","ok"]]}','utf8')
    assert m.load_chat('project')==[('user','ok')]
    before=m.CHAT_EPOCH;m.clear_chats()
    assert m.CHAT_EPOCH==before+1 and m.load_chat('project')==[]

def test_trial_is_bounded_before_allocating_and_reports_cannot_cross_projects():
    from twobyteasr.app import bunny_subtitle_tools as t
    from twobyteasr.app.bunny_tools import ToolError
    import pytest,time
    project=SimpleNamespace(cues=[SimpleNamespace(start_ms=0,end_ms=100,text='x')])
    with pytest.raises(ToolError):t._numbers(project,{'count':10**12})
    page=SimpleNamespace(project=project,_bunny_refine_watch=dict(project=object(),started=time.monotonic()-5))
    assert t.refine_report(page)==[]

def test_cleared_chat_cannot_be_saved_again_and_new_project_syncs_before_send(monkeypatch):
    from twobyteasr.app import bunny_chat as c,bunny_memory as m,bunny_permissions as p
    token=(True,True,m.CHAT_EPOCH)
    card=SimpleNamespace(_chat_key='A',_chat_token=token,transcript=[('user','PRIVATE_A')])
    monkeypatch.setattr(p,'load',lambda:dict(p.DEFAULTS))
    saved=[];monkeypatch.setattr(m,'save_chat',lambda *args:saved.append(args))
    monkeypatch.setattr(m,'CHAT_EPOCH',m.CHAT_EPOCH+1)
    c.BunnyChat._save_chat(card)
    assert not saved
    calls=[]
    card._project_key=lambda:'B'
    card._save_chat=lambda:calls.append('save')
    card._restore_chat=lambda key:calls.append(key)
    c.BunnyChat._sync_chat_context(card)
    assert calls==['save','B']

def test_retired_bubble_is_hidden_before_deferred_deletion():
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app.bunny_chat import ThreadView
    app=QApplication.instance() or QApplication([])
    view=ThreadView();view.resize(400,300);view.show()
    label,row=view.add_bubble('bunny','旧气泡');app.processEvents()
    frame=label.parentWidget()
    view.remove_row(row)
    assert frame.isHidden()
    view.close()

def test_recipe_failure_restores_earlier_style_step(monkeypatch):
    from twobyteasr.app import bunny_subtitle_tools as t,bunny_memory as m,bunny_tools as bt
    import pytest
    state=[]
    monkeypatch.setattr(t,'_studio',lambda window:SimpleNamespace(project=SimpleNamespace(speakers=[])))
    monkeypatch.setattr(m,'load',lambda:[dict(kind='recipe',text='配方',data=dict(style={'bold':True},break_rule='新的'))])
    def style(*args):
        state.append('style')
        return 'done',bt.UndoRecord('call',lambda:state.clear() or '',0)
    monkeypatch.setattr(bt,'_apply_style',style)
    monkeypatch.setattr(t,'break_language',lambda *args:'zh')
    monkeypatch.setattr(t,'current_rules',lambda code:'旧的')
    def rejected(*args):raise bt.ToolError('指引太长，原指引保持')
    monkeypatch.setattr(t,'_set_break_rule',rejected)
    with pytest.raises(bt.ToolError,match='指引太长'):t._use_recipe(None,{'name':'配方'})
    assert not state
