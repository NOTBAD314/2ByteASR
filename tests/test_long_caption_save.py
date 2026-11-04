"""Formal long-caption saves retain exact schema/text and avoid heavy thaw."""
import copy
from pathlib import Path
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project_revision,load_project
from twobyteasr.projects.studio_revisions import StudioRevisionStore,freeze_json

class Plain:
    def __init__(self,revision):self.revision=revision;self.generation=revision.generation
    def to_payload(self,**kwargs):return self.revision.to_payload(**kwargs)

def test_frozen_caption_archive_writer_matches_full_writer_and_reopens(tmp_path,monkeypatch):
    p=SubtitleProject(StudioMedia('',duration_ms=1000),cues=[StudioCue('a',0,800,'正文')]);p.validate()
    p.render_settings['_cue_domain']='timeline'
    p.studio_state['caption_timeline']={'version':1,'source_archive':[{'text':'原档案','tags':[]}],
        'instances':{'a':{'text':'正文','words':[{'text':'正','start_ms':0,'end_ms':400}]}}}
    p.studio_state['term_word_overrides']={'a':{'text':'正文','words':[]}}
    p.studio_state['review_risks']={'a':{'transient':True}}
    store=StudioRevisionStore(p);revision=store.refresh_persistence(1,deep=True)
    first,_=save_project_revision(revision,tmp_path/'frozen.2byteproj')
    second,_=save_project_revision(Plain(revision),tmp_path/'plain.2byteproj')
    assert first.read_bytes()==second.read_bytes()
    reopened=load_project(first)
    assert reopened.studio_state['caption_timeline']==p.studio_state['caption_timeline']
    assert reopened.studio_state['term_word_overrides']==p.studio_state['term_word_overrides']
    assert 'review_risks' not in reopened.studio_state


def test_caption_words_are_not_thawed_into_validation_copy(tmp_path,monkeypatch):
    import twobyteasr.projects.studio_revisions as revisions
    p=SubtitleProject(StudioMedia('',duration_ms=1000),cues=[StudioCue('a',0,800,'正文')]);p.validate()
    p.studio_state['caption_timeline']={'version':1,'instances':{'a':{'words':[{'text':'正'}]}}}
    revision=StudioRevisionStore(p).persistence
    heavy=dict(revision.studio_state.items)['caption_timeline']
    original=revisions.thaw_json
    def thaw(value):
        assert value is not heavy,'caption tree thawed into mutable validation payload'
        return original(value)
    monkeypatch.setattr(revisions,'thaw_json',thaw)
    save_project_revision(revision,tmp_path/'no-copy.2byteproj')
