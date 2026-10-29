import json
from twobyteasr.acceptance.ai_design_call_budget import install_acceptance_budget


def test_render_repair_does_not_consume_an_unstarted_direction(tmp_path,monkeypatch):
    from twobyteasr.providers import provider_service
    from twobyteasr.acceptance import studio_acceptance_audit
    class Client:
        provider_id='test';model='exact-id'
        def complete(self,*a,**k):return 'actual fake transport result'
        def invocation_trace(self):return {}
    monkeypatch.setattr(provider_service,'AIClient',Client)
    monkeypatch.setattr(studio_acceptance_audit,'audit_tmp_root',lambda:tmp_path)
    path=tmp_path/'budget.json'
    path.write_text(json.dumps(dict(limits=dict(generation=4,repair=6,redo=0),calls=[])))
    install_acceptance_budget(path)
    client=Client()
    for kind in ['design_directions','one_candidate','one_candidate','render_repair','one_candidate','implementation_completion']:
        client.complete([],operation_kind='generate',input_scope={'kind':kind})
    data=json.loads(path.read_text())
    assert [c['bucket'] for c in data['calls']]==['generation']*3+['repair','generation','repair']
    assert data['calls'][3]['input_scope']=={'kind':'render_repair'}
