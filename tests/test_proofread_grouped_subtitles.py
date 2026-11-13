"""One visual subtitle, two independently addressed/editable text fields."""
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker
from twobyteasr.subtitle_rules.subtitle_translation import set_manual, records_of
from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage, _StandalonePage, _issue
from twobyteasr.glossary.terminology import GlossarySnapshot

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def review(monkeypatch, tmp_path):
    p = SubtitleProject(StudioMedia('',duration_ms=10000), speakers=[StudioSpeaker('A','甲'),StudioSpeaker('B','乙')],
        cues=[StudioCue('second-speaker',1000,2200,'同時にね','B'),
              StudioCue('stable-source',1000,2200,'あーギリギリセーフ','A'),
              StudioCue('missing',3500,5000,'まだだよ','A')],
        generation_metadata={'language':{'code':'ja'}})
    p.validate()
    set_manual(p,'stable-source','啊——勉强赶上了',target='zh-Hans')
    set_manual(p,'second-speaker','同时呀',target='zh-Hans')
    w = GlossaryProofreadPage(SimpleNamespace(studio_page=None))
    monkeypatch.setattr(w,'_run',lambda *_a,**_k:None)
    monkeypatch.setattr(w,'_persist_soon',lambda *_a,**_k:None)
    monkeypatch.setattr(w,'_schedule_local_checks',lambda *_a,**_k:None)
    w._project=p;w._project_path=str(tmp_path/'copy.2byteproj')
    w._standalone=_StandalonePage(p);w._bind_stack(w._standalone.session.undo_stack)
    w._snapshot=GlossarySnapshot()
    w._build_rows(p,start_checks=False)
    w.text_targets.mode.setCurrentIndex(w.text_targets.mode.findData('both'))
    w._apply_filter()
    yield w,p
    w._save_timer.stop();w._rematch_timer.stop();w.shutdown();w.close()
    from twobyteasr.design.widget_teardown import delete_tree_before_collection
    delete_tree_before_collection(w)


def test_same_timestamp_different_speakers_pair_only_by_id_and_count_once(review):
    w,p=review
    assert len(w._group_indices)==3 and len(w._rows)==5
    assert w._filter_counts['all']==3 and w.proposal_counts()['captions']==3
    for group,indices in w._group_indices.items():
        rows=[w._rows[i] for i in indices]
        assert all(row['audio_cue_id']==group for row in rows)
        assert rows[0]['target'].layer=='original'
        if group != 'missing':
            assert rows[1]['target'].layer=='translation' and rows[1]['target'].cue_id==group
    assert w._by_id['missing']['translation_missing']


def test_search_displays_both_fields_and_visits_every_hit(review):
    w,p=review
    w.search.setText('勉强');w._apply_filter()
    assert len(w.list.visible)==2
    assert {w._rows[i]['group_id'] for i in w.list.visible}=={'stable-source'}
    assert len(w._hits)==1 and w._by_id[w._hits[0][0]]['target'].layer=='translation'
    w.search.setText('ー');w._apply_filter()
    assert len(w.list.visible)==2
    w._step_hit(1)
    assert w.list.find['current'][0]=='stable-source'


def test_edit_replace_undo_and_bulk_translation_use_their_own_address(review):
    w,p=review
    translated=next(row for row in w._rows if row['target'].storage=='translation' and row['group_id']=='stable-source')
    key=translated['cue_id']
    original=w._by_id['stable-source']['base']
    w._edit_committed(key,'啊——成功赶上了')
    assert records_of(p)['stable-source']['text']=='啊——成功赶上了'
    assert w._by_id['stable-source']['base']==original
    w._undo()
    assert records_of(p)['stable-source']['text']=='啊——勉强赶上了'
    translated['issues']=[_issue('ai_review',(3,5),'勉强','成功',checked=False)]
    translated['issues'].append(_issue('ai_review',(5,7),'赶上','追上',checked=False))
    w._by_id['stable-source']['issues']=[_issue('ai_review',(2,6),'ギリギリ','なんとか',checked=False)]
    w._apply_filter()
    assert w._filter_counts['suggested']==1
    assert w.proposal_counts()['proposals']==3
    w._batch_toggle_row('stable-source')
    assert w._batch_selected=={'stable-source',key}
    w._batch_ignore()
    assert not w._unresolved(translated)
    assert p.cues[1].text==original
    w._undo()
    assert w._unresolved(translated)


def test_painted_group_has_one_play_and_checkbox_and_separate_editors(review):
    w,p=review
    w.resize(1500,1000);w.show();APP.processEvents();w.list.repaint();APP.processEvents()
    play=[hit for hit in w.list._hit_boxes if hit[1]=='play']
    boxes=[hit for hit in w.list._hit_boxes if hit[1]=='rowcheck']
    assert len(play)==len(boxes)==3
    ids={hit[2] for hit in w.list._hit_boxes if hit[1]=='edit'}
    assert ids==set(w._by_id)
    translated=next(r for r in w._rows if r['group_id']=='stable-source' and r['target'].storage=='translation')
    w._edit(translated['cue_id']);APP.processEvents()
    assert w.list.editor.text()==translated['base']
    source=w.list._painted_text['stable-source']
    if w.list.paired:  # 2026-11-13 bilingual design A: the translation edits beside its caption
        assert w.list.editor.x()>source.right()-1 and abs(w.list.editor.y()-source.y())<2
    else:
        assert w.list.editor.y()>source.y()


def test_reordering_rebuilds_group_indices_without_pairing_by_position(review):
    w,p=review
    translated=next(r for r in w._rows if r['group_id']=='stable-source' and r['target'].storage=='translation')
    w.list.current=translated['cue_id']
    w._rows.reverse();w._row_indexes={r['cue_id']:n for n,r in enumerate(w._rows)}
    w.list.set_rows(w._rows);w._apply_filter()
    for owner,indices in w._group_indices.items():
        fields=[w._rows[i] for i in indices]
        assert fields[0]['target'].layer=='original'
        assert all(row['group_id']==owner for row in fields)
    assert w.list.current==translated['cue_id']
    assert w._by_id[translated['cue_id']] is translated


def test_either_field_uses_one_original_audio_target_and_one_button_state(review,monkeypatch):
    w,p=review
    translated=next(r for r in w._rows if r['group_id']=='stable-source' and r['target'].storage=='translation')
    calls=[]
    def play(project,cue_id):
        calls.append(cue_id);w._player.cue_id=cue_id;w._player.state='playing'
        w._playing_changed(cue_id,'playing')
    monkeypatch.setattr(w._player,'play',play)
    monkeypatch.setattr(w._player,'pause',lambda:calls.append('pause'))
    w._play(translated['cue_id'])
    assert calls==['stable-source'] and w.list.playing==('stable-source','playing')
    w._play('stable-source');assert calls==['stable-source','pause']
