import copy
import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.providers.endpoint_editor_ui import PromptDialog
from twobyteasr.subtitle_rules.grouping_request import custom_grouping_guidance,default_grouping_guidance,grouping_prompt_key
from twobyteasr.subtitle_rules.segmentation_profiles import prompt_languages,profile_for
from twobyteasr.storage import settings as storage

APP=QApplication.instance() or QApplication([])


def test_language_drafts_restore_one_and_preserve_legacy_settings(tmp_path,monkeypatch):
    current=copy.deepcopy(storage.DEFAULT_SETTINGS)
    current['subtitle_language']['recognition_language']='it-IT'
    current['grouping_prompts'].update(zh='保留中文自定义',en='English custom',it='Old Italian',**{'legacy-future':'保留旧配置'})
    monkeypatch.setattr(storage,'save_runtime_settings',lambda data: storage_save(data,project_root=tmp_path))
    dialog=PromptDialog(None,current)
    try:
        assert dialog.language.count()==len(prompt_languages()) and dialog._current=='it'
        dialog.editor.setPlainText("Conserva l'auto e i nomi completi.")
        dialog.language.setCurrentIndex(dialog.language.findData('fr'))
        dialog.editor.setPlainText("Conserver l'équipe et Jean-Luc.")
        dialog.language.setCurrentIndex(dialog.language.findData('it'))
        assert dialog.editor.toPlainText()=="Conserva l'auto e i nomi completi."
        assert '84' in dialog.fixed_note.text() and '16' not in dialog.fixed_note.text()
        dialog.restore.click()
        assert dialog.editor.toPlainText()==default_grouping_guidance('it')
        dialog.editor.setPlainText('A new custom rule after restore')
        assert dialog.guidance_values()['it']=='A new custom rule after restore'
        dialog.restore.click()
        dialog.save()
    finally:dialog.deleteLater();APP.processEvents()
    loaded=storage.load_runtime_settings(project_root=tmp_path)
    loaded=loaded[0] if isinstance(loaded,tuple) else loaded
    assert loaded['grouping_prompts']['it']==''
    assert loaded['grouping_prompts']['fr']=="Conserver l'équipe et Jean-Luc."
    assert loaded['grouping_prompts']['zh']=='保留中文自定义' and loaded['grouping_prompts']['en']=='English custom'
    assert loaded['grouping_prompts']['legacy-future']=='保留旧配置'
    reopened=PromptDialog(None,loaded)
    try:
        reopened.language.setCurrentIndex(reopened.language.findData('fr'))
        assert reopened.editor.toPlainText()=="Conserver l'équipe et Jean-Luc."
    finally:reopened.deleteLater();APP.processEvents()


storage_save=storage.save_runtime_settings


def test_known_locale_aliases_migrate_conservatively_and_are_independent():
    payload={'grouping_prompts':{'pt_br':'Brazil custom','pt':'Generic custom','it':'Italian custom','mystery':'Unknown old'}}
    merged,warnings=storage._merge_known_settings(storage.DEFAULT_SETTINGS,payload)
    assert not warnings
    assert custom_grouping_guidance('pt-BR',merged)=='Brazil custom'
    assert custom_grouping_guidance('pt',merged)=='Generic custom'
    assert custom_grouping_guidance('it-IT',merged)=='Italian custom'
    assert merged['grouping_prompts']['mystery']=='Unknown old'
    restored=copy.deepcopy(merged);restored['grouping_prompts']['pt-BR']=''
    assert custom_grouping_guidance('pt-BR',restored)==''
    assert custom_grouping_guidance('pt',restored)=='Generic custom'
    assert grouping_prompt_key('pt-BR',merged)!=grouping_prompt_key('pt-BR',restored)


def test_current_task_snapshot_is_immutable_while_new_task_reads_new_settings():
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    original={'grouping_prompts':{'it':'Old task preference'}}
    snapshot=copy.deepcopy(original)
    context=RuntimeContext(task_language='it',asr_settings_snapshot=snapshot)
    with activate_runtime_context(context):
        first=custom_grouping_guidance('it')
        original['grouping_prompts']['it']='New task preference'
        assert custom_grouping_guidance('it')==first
    with activate_runtime_context(RuntimeContext(task_language='it',asr_settings_snapshot=copy.deepcopy(original))):
        assert custom_grouping_guidance('it')=='New task preference'
