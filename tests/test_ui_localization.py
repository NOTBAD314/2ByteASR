import ast
from copy import deepcopy
from pathlib import Path
from string import Formatter

import pytest

from twobyteasr import i18n


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_bound_messages_have_both_translations():
    missing=[]
    for p in (Path(__file__).parents[1]/'twobyteasr').glob('*.py'):
        if 'audit' in p.stem:continue
        tree=ast.parse(p.read_text('utf-8-sig'))
        for n in ast.walk(tree):
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('bind_text','tr','translate'):
                index=1 if n.func.id=='bind_text' else 0
                if len(n.args)>index and isinstance(n.args[index],ast.Constant) and isinstance(n.args[index].value,str):
                    key=n.args[index].value
                    if any('\u4e00'<=c<='\u9fff' for c in key):
                        for lang in ('en','ja'):
                            if key not in i18n._TRANSLATIONS[lang]:missing.append((p.name,n.lineno,lang,key))
    assert not missing,missing


def test_complete_format_specifications_match():
    def fields(s):return sorted((name,spec,conv) for _,name,spec,conv in Formatter().parse(s) if name is not None)
    for language in ('en','ja'):
        for source,translated in i18n._TRANSLATIONS[language].items():
            assert fields(source)==fields(translated),(language,source,translated)


def test_locale_files_load_with_identical_keys():
    import json
    assert not i18n.LOCALE_LOAD_ERRORS
    tables={language:json.loads((i18n.LOCALE_DIR/f'{language}.json').read_text('utf8'))
            for language in i18n.TRANSLATED_LANGUAGES}
    assert tables['en'].keys()==tables['ja'].keys() and len(tables['en'])>4000
    assert all(isinstance(value,str) and value.strip() for table in tables.values() for value in table.values())
    assert i18n._TRANSLATIONS==tables


def test_dynamic_status_replaces_previous_capture(app):
    from PySide6.QtWidgets import QLabel
    label=QLabel('等待')
    i18n.apply_ui_language(label,'en')
    label.setText('已完成')
    i18n.apply_ui_language(label,'ja')
    assert label.text()==i18n.translate('已完成','ja')
    label.setText('原始服务错误xyz')
    i18n.apply_ui_language(label,'en')
    assert label.text()=='原始服务错误xyz'


def test_binding_does_not_replace_tooltip_or_editor_content(app,monkeypatch):
    from PySide6.QtWidgets import QLabel,QLineEdit,QWidget
    root=QWidget();label=QLabel(root);edit=QLineEdit(root)
    monkeypatch.setattr(i18n,'_CURRENT_LANGUAGE_CACHE','zh')
    i18n.bind_text(label,'最近：{name}',name='游戏剪辑第一版')
    label.setToolTip('说话人管理');edit.setText('全部');edit.setPlaceholderText('输入主题或设计要求…')
    for lang in ('en','ja','zh'):
        i18n.apply_ui_language(root,lang)
        assert '游戏剪辑第一版' in label.text()
        assert label.toolTip()==i18n.translate('说话人管理',lang)
        assert edit.text()=='全部'


def test_combobox_switch_has_no_business_callbacks_or_data_changes(app):
    from PySide6.QtWidgets import QComboBox
    combo=QComboBox();combo.addItem('纯色','solid');combo.addItem('关闭','off');combo.setCurrentIndex(1)
    emitted=[];combo.currentTextChanged.connect(emitted.append)
    for lang in ('en','ja','zh'):
        i18n.apply_ui_language(combo,lang)
        assert combo.currentData()=='off' and combo.currentIndex()==1
    assert emitted==[]
    combo.clear();combo.addItem('说话人管理','speakers')
    i18n.apply_ui_language(combo,'en')
    assert combo.currentText()=='Speaker Management'
    assert combo.currentData()=='speakers'


def test_user_labels_and_table_content_are_opaque(app):
    from PySide6.QtWidgets import QLabel,QTableWidget,QTableWidgetItem
    label=i18n.user_text(QLabel('全部'))
    table=QTableWidget(1,1);table.setItem(0,0,QTableWidgetItem('说话人管理'))
    i18n.apply_ui_language(label,'en');i18n.apply_ui_language(table,'en')
    assert label.text()=='全部'
    assert table.item(0,0).text()=='说话人管理'


def test_application_refresh_handles_item_view_overloads(app):
    from PySide6.QtWidgets import QWidget,QListWidget
    from twobyteasr.i18n_widgets import refresh_application
    root=QWidget();view=QListWidget(root);view.addItem('用户内容')
    refresh_application('en')
    assert view.item(0).text()=='用户内容'


def test_default_names_localize_without_mutation(tmp_path,monkeypatch):
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,save_project
    from twobyteasr.project_display_name import display_project_name
    folder=tmp_path/'未命名工程 30';folder.mkdir()
    path=folder/'未命名工程 30.2byteproj'
    project=SubtitleProject(media=StudioMedia(path='',display_name='未命名工程 30'))
    save_project(project,path);before=path.read_bytes();state=deepcopy(project.studio_state)
    for lang,name in [('zh','未命名工程 30'),('en','Unnamed Project 30'),('ja','無題のプロジェクト 30')]:
        monkeypatch.setattr(i18n,'_CURRENT_LANGUAGE_CACHE',lang)
        assert display_project_name(path=path)==name
        assert display_project_name(path=path,project=project)==name
        assert path.read_bytes()==before and project.studio_state==state
    project.studio_state['project_name']='未命名工程 30'
    assert display_project_name(path=path,project=project)=='未命名工程 30'
    project.studio_state['project_name']='游戏剪辑第一版'
    assert display_project_name(path=path,project=project)=='游戏剪辑第一版'


def test_uncertain_offline_names_are_not_guessed(tmp_path,monkeypatch):
    from twobyteasr.project_display_name import display_project_name
    monkeypatch.setattr(i18n,'_CURRENT_LANGUAGE_CACHE','en')
    assert display_project_name({'path':str(tmp_path/'未命名工程 30.2byteproj'),'name':'未命名工程 30'})=='未命名工程 30'


def test_locale_key_parity():
    assert i18n._TRANSLATIONS['en'].keys() == i18n._TRANSLATIONS['ja'].keys()


def test_nested_worker_messages_retranslate_and_preserve_recognition_text(app, monkeypatch):
    from PySide6.QtWidgets import QLabel
    from twobyteasr.recognition_status_text import recognition_event_text
    monkeypatch.setattr(i18n, '_CURRENT_LANGUAGE_CACHE', 'zh')
    payload=dict(completed_chunks=1,total_chunks=2,processed_start=0,processed_end=4,
                 rows=[{'text':'用户内容：说话人管理'}])
    before=deepcopy(payload)
    message=recognition_event_text('asr_evidence_delta',payload)
    label=QLabel()
    i18n.bind_text(label,i18n.tr('{message} · 距最近有效结果 {seconds} 秒',message=message,seconds=3))
    for language,word in [('en','provisional'),('ja','仮結果'),('zh','临时证据')]:
        i18n.apply_ui_language(label,language)
        assert word in label.text() and '用户内容：说话人管理' in label.text()
        assert '1/2' in label.text() and payload==before
    assert deepcopy(message).source==message.source


def test_dynamic_combo_and_dialog_keep_arguments(app, monkeypatch):
    from PySide6.QtWidgets import QComboBox,QMessageBox
    from twobyteasr.i18n_widgets import add_combo_item
    monkeypatch.setattr(i18n,'_CURRENT_LANGUAGE_CACHE','zh')
    combo=QComboBox();add_combo_item(combo,i18n.tr('完整候选并发：{count}',count=2),2)
    box=QMessageBox();i18n.bind_text(box,'确定删除 {value0}？',property='informativeText',value0='游戏剪辑第一版')
    called=[];combo.currentTextChanged.connect(called.append)
    for lang in ('en','ja','zh'):
        i18n.apply_ui_language(combo,lang);i18n.apply_ui_language(box,lang)
        assert combo.currentData()==2 and combo.currentText()==i18n.translate('完整候选并发：{count}',lang).format(count=2)
        assert box.informativeText()==i18n.translate('确定删除 {value0}？',lang).format(value0='游戏剪辑第一版')
    assert called==[]


def test_new_default_and_offline_rename_are_distinct(tmp_path,monkeypatch):
    from twobyteasr.studio_project import SubtitleProject,StudioMedia
    from twobyteasr.project_display_name import display_project_name
    p=SubtitleProject(media=StudioMedia(path=""));p.studio_state['project_name_origin']={'kind':'unnamed','number':35}
    for lang,expected in [('en','Unnamed Project 35'),('ja','無題のプロジェクト 35')]:
        monkeypatch.setattr(i18n,'_CURRENT_LANGUAGE_CACHE',lang)
        assert display_project_name(project=p,path=tmp_path/'stable.2byteproj')==expected
        assert display_project_name({'name':'未命名工程 30','name_custom':True,'path':str(tmp_path/'missing.2byteproj')})=='未命名工程 30'
    p.studio_state['project_name']='全部'
    assert display_project_name(project=p)=='全部'


def test_automatic_and_custom_speaker_names(monkeypatch):
    from twobyteasr.studio_project import SubtitleProject,StudioSpeaker,StudioMedia
    from twobyteasr.speaker_names import display_speaker_name
    p=SubtitleProject(media=StudioMedia(path=""));s=StudioSpeaker('S01','说话人 1')
    p.generation_metadata['speaker_names']={'entries':{'S01':{'automatic':True}}}
    monkeypatch.setattr(i18n,'_CURRENT_LANGUAGE_CACHE','en')
    assert display_speaker_name(p,s)=='Speaker 1'
    p.generation_metadata['speaker_names']['entries']['S01']['automatic']=False
    assert display_speaker_name(p,s)=='说话人 1'


def test_built_in_model_prose_is_translated_without_changing_evidence(monkeypatch):
    from twobyteasr.model_evaluation_metadata import get_profile,_TECHNICAL_PROFILES
    import re
    def strings(value):
        if isinstance(value,str):yield value
        elif isinstance(value,dict):
            for item in value.values():yield from strings(item)
        elif isinstance(value,(list,tuple)):
            for item in value:yield from strings(item)
    for key in _TECHNICAL_PROFILES:
        source=get_profile(key,'zh');ja=get_profile(key,'ja')
        for text in strings(source):
            if re.search('[\u4e00-\u9fff]',text) and text!='日本語':
                assert text in i18n._TRANSLATIONS['ja'],(key,text)
        for original,localized in zip(source.get('benchmarks',[]),ja.get('benchmarks',[])):
            assert localized['value']==original['value']
            assert localized['source_url']==original['source_url']


def test_application_table_cells_retranslate_nested_labels(app,monkeypatch):
    from PySide6.QtWidgets import QTableWidget,QTableWidgetItem
    from twobyteasr.i18n_widgets import bind_item
    monkeypatch.setattr(i18n,'_CURRENT_LANGUAGE_CACHE','zh')
    table=QTableWidget(1,2)
    table.setItem(0,0,bind_item(QTableWidgetItem(),i18n.tr('{name}（已隐藏）',name=i18n.tr('说话人 {number}',number=1))))
    table.setItem(0,1,QTableWidgetItem('说话人 1'))
    for lang,word in [('en','Speaker 1 (hidden)'),('ja','話者 1（非表示）')]:
        i18n.apply_ui_language(table,lang)
        assert table.item(0,0).text()==word
        assert table.item(0,1).text()=='说话人 1'


def test_generated_panel_headings_preserve_provider_content(app,monkeypatch):
    from PySide6.QtWidgets import QPlainTextEdit
    monkeypatch.setattr(i18n,'_CURRENT_LANGUAGE_CACHE','zh')
    panel=QPlainTextEdit();panel.setReadOnly(True)
    i18n.bind_text(panel,'{value0}\n{value1}\n\n动效：{value2}',property='plainText',
                   value0='用户主题',value1='服务返回的中文设计说明',value2='用户提供的动效')
    i18n.apply_ui_language(panel,'en')
    assert panel.toPlainText()=='用户主题\n服务返回的中文设计说明\n\nMotion: 用户提供的动效'
    i18n.apply_ui_language(panel,'ja')
    assert panel.toPlainText()=='用户主题\n服务返回的中文设计说明\n\nアニメーション：用户提供的动效'
