"""Protocol/attribution/UI wiring tests; these are not real model inference."""
import copy
import json
from pathlib import Path
from dataclasses import replace
import pytest
from twobyteasr.optional_speaker_evidence import normalize_intervals,assign_segments,parse_streaming_chunks

import os
ROOT=Path(os.environ.get('WORKSHOP_SOURCE_ROOT', str(Path(__file__).resolve().parents[1])))

@pytest.fixture
def qtbot():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    class Owner:
        def __init__(self):self.widgets=[]
        def addWidget(self,widget):self.widgets.append(widget)
    owner=Owner();yield owner
    for widget in owner.widgets:widget.close();widget.deleteLater()
    app.processEvents()

def intervals(rows):return normalize_intervals(rows,task_id='a',source='diarizen',duration=60)

def test_more_than_four_global_identities_and_unknown_confidence():
    rows=intervals([dict(start=i*3,end=i*3+2,speaker=f'S{i}') for i in range(7)])
    assert len({r['speaker'] for r in rows})==7
    assert all(r['confidence'] is None and r['confidence_kind']=='unknown' for r in rows)

def test_mixed_asr_label_is_attributed_per_segment():
    native=intervals([dict(start=0,end=2,speaker='a'),dict(start=3,end=5,speaker='b')])
    rows,evidence=assign_segments([dict(start=.1,end=1.9,text='甲',speaker='S00'),dict(start=3.1,end=4.9,text='乙',speaker='S00')],native)
    assert rows[0]['speaker']!=rows[1]['speaker']
    assert [r['original_speaker'] for r in evidence['mapping']]==['S00','S00']

def test_overlap_never_uses_majority_or_duplicates_text():
    native=intervals([dict(start=0,end=5,speaker='a'),dict(start=1,end=2,speaker='b'),dict(start=1,end=1.5,speaker='c')])
    original=[dict(start=.1,end=4.9,text='不可猜给谁',speaker='S00')]
    rows,evidence=assign_segments(original,native)
    assert len(rows)==1 and rows[0]['text']=='不可猜给谁'
    assert rows[0]['speaker']=='SPEAKER_UNCONFIRMED'
    assert len(evidence['activity_without_reliable_text'])==3
    assert len(native[0]['overlaps'])==2
    assert original[0]['speaker']=='S00'

def test_split_only_on_actual_existing_tokens():
    native=intervals([dict(start=0,end=1,speaker='a'),dict(start=1,end=2,speaker='b')])
    row=dict(start=0,end=2,text='甲乙',speaker='S00',tokens=[dict(start=.1,end=.9,text='甲'),dict(start=1.1,end=1.9,text='乙')])
    rows,_=assign_segments([row],native)
    assert ''.join(r['text'] for r in rows)=='甲乙' and len(rows)==2
    row['tokens'][0]['text']='错'
    rows,_=assign_segments([row],native)
    assert len(rows)==1 and rows[0]['speaker']=='SPEAKER_UNCONFIRMED'

def test_streaming_repeats_native_labels_and_tail_retained():
    chunks=[dict(index=0,text='Speaker 0: 20 20'),dict(index=1,text='对 对'),dict(index=2,text='Speaker 1: 尾字')]
    rows=parse_streaming_chunks(chunks,duration=6.1,chunk_seconds=2.933333333,source='vibevoice_1_5b')
    assert [r['text'] for r in rows]==['20 20','对 对','尾字']
    assert rows[0]['speaker']==rows[1]['speaker'] and rows[-1]['speaker']=='S01'
    assert rows[-1]['end']==6.1 and all(not r['tokens'] and r['timing_precision']=='chunk' for r in rows)

def test_duplicate_protocol_id_is_error_not_text_dedup():
    with pytest.raises(ValueError):parse_streaming_chunks([dict(index=0,text='甲'),dict(index=0,text='甲')],duration=3,chunk_seconds=3,source='vv')

def test_padded_native_tail_is_traceable_and_clipped():
    raw=[dict(start=17,end=18.112,speaker='a')]
    rows=normalize_intervals(raw,task_id='t',source='diarizen',duration=18,clip_to_audio=True)
    assert rows[0]['end']==18 and rows[0]['native_end']==18.112
    assert rows[0]['boundary_correction']=='padded_window_clipped_to_task_audio'
    assert raw[0]['end']==18.112

def test_metadata_versions_and_auxiliary_licenses():
    from twobyteasr.recognition.optional_models import metadata,consent_identity
    meta=metadata(ROOT)
    assert meta['components']['diarizen']['repository'].endswith('-v2')
    assert meta['components']['diarizen_embedding']['weights_license']=='CC-BY-4.0'
    small=meta['components']['vibevoice_1_5b'];large=meta['components']['vibevoice_7b']
    assert small['revision']!=large['revision'] and small['path']!=large['path']
    assert small['weights_license']==large['weights_license']=='MIT'
    assert all(set(c['required_files'])==set(c['sha256']) for c in meta['components'].values())
    assert len(consent_identity(ROOT))==64

def test_follow_primary_and_explicit_source_preserved():
    from twobyteasr.recognition.speaker_strategy import resolve
    from twobyteasr.storage.settings import _merge_known_settings,DEFAULT_SETTINGS
    for key in ('vibevoice_1_5b','vibevoice_7b'):
        settings={'models':{'primary_asr_backend':key,'speaker_source':'diarizen'}}
        assert resolve(settings)=='diarizen'
        assert resolve(settings,'native')=='native'
        value,_=_merge_known_settings(DEFAULT_SETTINGS,settings)
        assert value['models']['primary_asr_backend']==key and value['models']['speaker_source']=='diarizen'
    assert resolve({'models':{'primary_asr_backend':'moss','speaker_source':'native'}})=='moss'

def test_family_card_single_entry_and_two_real_bindings(qtbot):
    from twobyteasr.local_models.model_workshop import MODELS,ModelCard
    families=[m for m in MODELS if m.key=='vibevoice'];assert len(families)==1
    card=ModelCard(families[0]);qtbot.addWidget(card)
    assert families[0].variants == ('vibevoice_1_5b', 'vibevoice_7b')
    assert not hasattr(card, 'version_combo')
    assert not hasattr(card, 'license_button')
    assert card._row.indexOf(card.action_host) == 2
    assert card._root.indexOf(card.action_host) == -1
    assert not next(m for m in MODELS if m.key=='diarizen').recommended

def test_strict_alignment_never_swaps_main_text_or_spreads_words():
    from twobyteasr.recognition.optional_timing import exact_tokens
    row=dict(start=0,end=3,text='20 20')
    wrong=[dict(start=.2,end=2,text='对对')]
    assert exact_tokens(row,wrong)==[]
    correct=[dict(start=.2,end=1,text='20'),dict(start=1.2,end=2,text='20')]
    assert exact_tokens(row,correct)==correct

def test_version_view_picker_and_selected_task_do_not_drift(qtbot,monkeypatch,tmp_path):
    from PySide6.QtCore import QSettings
    from twobyteasr.recognition import optional_models
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage,ModelPickerPanel
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,str(tmp_path))
    monkeypatch.setattr(optional_models,'readiness',lambda key:'installed' if key=='vibevoice_1_5b' else 'missing')
    settings={'models':{'primary_asr_backend':'vibevoice_1_5b','speaker_source':'native','firered_asr_backend':'off','qwen_asr_backend':'off'}}
    original=copy.deepcopy(settings)
    page=ModelWorkshopPage(ROOT,settings);qtbot.addWidget(page)
    picker=ModelPickerPanel(page,'primary');qtbot.addWidget(picker)
    assert page._selected_model_key_for_role('primary')=='vibevoice'
    page._view_variant('vibevoice','vibevoice_7b')
    assert page._cards['vibevoice'].model.download_key=='vibevoice_7b'
    assert picker.cards['vibevoice'].model.download_key=='vibevoice_7b'
    assert page._model_state(page._cards['vibevoice'].model,'primary')=='missing'
    assert picker.cards['vibevoice'].action.text() == '使用'
    assert '7B' in picker.cards['vibevoice'].state_badge.text()
    assert '1.5B' in picker.current_badge.text()
    assert settings==original
    page._view_variant('vibevoice','vibevoice_1_5b')
    assert page._model_state(page._cards['vibevoice'].model,'primary')=='selected'
    assert page._selection_target(page._cards['vibevoice'].model,'primary')==('primary','vibevoice_1_5b')

def test_about_uses_retained_license_text_and_original_documents(qtbot,monkeypatch,tmp_path):
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    from PySide6.QtWidgets import QLabel,QPushButton
    dialog=ApplicationSettingsDialog(None,{},ROOT,browse=lambda:None,clear_recent=lambda:None,reset_layout=lambda:None)
    qtbot.addWidget(dialog)
    assert 'GPL-3.0-only' in dialog.findChild(QLabel,'projectLicenseLabel').text()
    assert '0.2.6-test.3' in dialog.findChild(QLabel,'projectLicenseLabel').text()
    assert 'CC-BY-NC-4.0' in dialog.findChild(QLabel,'thirdPartyModelLicenseLabel').text()
    assert any('可选模型许可' in b.text() for b in dialog.findChildren(QPushButton))
    assert (ROOT/'licenses/optional-models/diarizen/UPSTREAM_README.md').read_bytes()==(ROOT/'third_party/DiariZen/README.md').read_bytes()
    from twobyteasr.recognition.optional_models import license_details
    details=license_details(ROOT)
    assert '60d858b518b4e19d404af3737f848fc185b30177' in details and 'CC-BY-NC-4.0' in details

def test_license_cancel_writes_no_consent(qtbot,monkeypatch,tmp_path):
    from twobyteasr.recognition import optional_models as models
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(models,'_consent_path',lambda:tmp_path/'consent.json')
    monkeypatch.setattr(QMessageBox,'warning',lambda *a,**kw:QMessageBox.StandardButton.Cancel)
    assert not models.confirm_license(None,ROOT)
    assert not (tmp_path/'consent.json').exists()

def test_license_confirmation_bound_to_revision_and_repeat_quiet(qtbot,monkeypatch,tmp_path):
    from twobyteasr.recognition import optional_models as models
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(models,'_consent_path',lambda:tmp_path/'consent.json')
    calls=[]
    monkeypatch.setattr(QMessageBox,'warning',lambda *a,**kw:calls.append(1) or QMessageBox.StandardButton.Ok)
    assert models.confirm_license(None,ROOT) and models.confirm_license(None,ROOT)
    assert len(calls)==1
    assert json.loads((tmp_path/'consent.json').read_text('utf8'))['model']['revision']==models.component('diarizen',ROOT)['revision']

def test_unaligned_streaming_finalization_retains_long_text_and_native_bounds():
    from types import SimpleNamespace
    from twobyteasr.recognition.optional_timing import finalize_streaming
    from twobyteasr.recognition.transcript_data import SpeechSegment,SubtitleCue
    segment=SpeechSegment(1,0,2.933333,'这是一条超过旧断句显示长度限制但没有可靠字级对齐的完整流式文字',0,[],speaker='S_UNKNOWN',primary_source='vibevoice_1_5b')
    reviews=[];events=[]
    legacy=SimpleNamespace(SubtitleCue=SubtitleCue,add_review_item=lambda *a,**kw:reviews.append(a),record_run_event=lambda *a,**kw:events.append((a,kw)))
    def forbidden(*a):raise AssertionError('Unaligned chunk reached a word-time repair')
    cues=finalize_streaming([SubtitleCue(1,0,2.933333,segment.text,speaker=segment.speaker)], [segment],[],[],3,30,legacy,forbidden)
    assert len(cues)==1 and cues[0].text==segment.text and cues[0].end==2.933333
    assert cues[0].timing_locked and reviews and events[-1][1]['uniform_timestamps_created'] is False

def test_streaming_term_context_keeps_case_digits_and_task_identity(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.recognition import optional_model_process as bridge, run_context as runtime, cache
    from twobyteasr.glossary import terminology
    context=SimpleNamespace(job_id='frozen-job',media_identity={})
    monkeypatch.setattr(runtime,'get_runtime_context',lambda:context)
    monkeypatch.setattr(terminology,'runtime_snapshot',lambda:SimpleNamespace(canonical_terms=('Sable7Alias','B650','RTX5070Ti')))
    seen={}
    def worker(key,audio,**kwargs):
        seen.update(key=key,**kwargs)
        return dict(results=[],revision='pinned',weights_license='MIT',session_complete=True,input_audio_sha256='real-input-test')
    monkeypatch.setattr(bridge,'run_optional',worker)
    monkeypatch.setattr(cache,'record_run_event',lambda *a,**kw:None)
    assert bridge.transcribe('vibevoice_7b',[])==[]
    assert seen==dict(key='vibevoice_7b',context_info='Sable7Alias, B650, RTX5070Ti',task_id='frozen-job')
    assert 'vibevoice_7b' in context.media_identity['optional_models']

def test_pending_version_action_chooses_sample_before_preparation(qtbot,monkeypatch,tmp_path):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QFileDialog
    from twobyteasr.recognition import optional_models
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage, ModelVersionDialog
    from PySide6.QtWidgets import QDialog
    monkeypatch.setattr(optional_models,'readiness',lambda key:'inference_pending')
    page=ModelWorkshopPage(ROOT,{'models':{'primary_asr_backend':'moss'}});qtbot.addWidget(page)
    page._view_variant('vibevoice','vibevoice_7b')
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**kw:('owned-sample.wav',''))
    dialog=SimpleNamespace(download_keys=('vibevoice_7b',));seen=[]
    monkeypatch.setattr(page,'download_combination',lambda keys,name:seen.append(keys) or dialog)
    def choose_version(chooser):
        chooser.choices['vibevoice_7b'].setChecked(True)
        chooser._accept_action('verify')
        return QDialog.Accepted
    monkeypatch.setattr(ModelVersionDialog, 'exec', choose_version)
    page._perform_action('vibevoice')
    assert seen==[['vibevoice_7b']] and dialog.verification_sample=='owned-sample.wav'

def test_fixed_vendor_manifest_is_entirely_in_build_fingerprint():
    from twobyteasr.diagnostics.build_identity import source_snapshot_files
    paths={p.relative_to(ROOT).as_posix() for p in source_snapshot_files(ROOT)}
    for vendor in ('DiariZen','VibeVoice'):
        provenance=json.loads((ROOT/'third_party'/vendor/'UPSTREAM_SOURCE.json').read_text('utf8'))
        assert all('third_party/'+vendor+'/'+p in paths for p in provenance['files'])
