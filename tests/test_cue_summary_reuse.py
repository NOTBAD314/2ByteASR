from types import SimpleNamespace
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.subtitle_rules.studio_qc import QCResult
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.studio import studio_cue_table

class Widget:
    def setText(self,value):self.text=value
    def setVisible(self,value):pass
    def setRange(self,*a):pass
    def blockSignals(self,*a):pass

def test_summary_reuses_canonical_jump_rows_and_one_risk_table(monkeypatch):
    p=SubtitleProject(StudioMedia('',duration_ms=10000),cues=[StudioCue(str(i),i*10,i*10+8,'字幕'+str(i)) for i in range(100)])
    p.validate();p.render_settings['_cue_domain']='timeline';p._qc_result=QCResult({})
    store=StudioRevisionStore(p)
    page=SimpleNamespace(project=p,_revision_store=store,jump_spin=Widget(),cue_total_label=Widget(),
        _sync_jump_position=lambda:None,cue_filter_buttons={key:Widget() for key in ('all','priority','critical','pending','issue','done')},
        cue_table=Widget(),cue_zero_state=Widget(),cue_empty_state=Widget(),cue_model=SimpleNamespace(filter_status='all',rowCount=lambda:100))
    SubtitleStudioPage._refresh_cue_list_summary(page)
    previous_order=page._cue_jump_order;previous_index=page._cue_jump_index
    monkeypatch.setattr(studio_cue_table,'_source_key',lambda *a:(_ for _ in ()).throw(AssertionError('jump index rebuilt')))
    monkeypatch.setattr(studio_cue_table,'cached_review_risks',lambda *a:(_ for _ in ()).throw(AssertionError('per-cue risk table lookup')))
    p.cues[3].text='已编辑的新文字'
    SubtitleStudioPage._refresh_cue_list_summary(page)
    assert page._cue_jump_order is previous_order and page._cue_jump_index is previous_index
    assert page.cue_filter_buttons['done'].text.endswith(' 1')
    assert page._cue_jump_order[3].text=='已编辑的新文字'
