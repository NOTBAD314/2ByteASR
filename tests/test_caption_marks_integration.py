import copy
import json
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project, load_project
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.rendering.advanced_live_renderer import render_live_snapshot
from twobyteasr.rendering.marked_glyphs import marked_ass_text
from twobyteasr.caption_style.bilingual_layout import project_display_cues
from twobyteasr.timeline.studio_commands import split_cue_command, merge_cues_command, SetCueFieldsCommand
from twobyteasr.glossary.terminology import GlossarySnapshot, GlossaryLibrary, TermEntry, TermResolver
from twobyteasr.glossary.visual_emphasis import match_marks


def make_project():
    value=SubtitleProject(media=StudioMedia('',duration_ms=4000),
        speakers=[StudioSpeaker('S01','玩家')], cues=[StudioCue('a',0,4000,'火球火球',speaker_id='S01')])
    value.validate()
    return value


def test_marked_glyphs_are_static_and_coloured(tmp_path):
    app=QApplication.instance() or QApplication([])
    p=make_project();cue=p.cues[0]
    plain=render_live_snapshot(build_visual_cue_snapshot(p,'a'),width=640,height=360)
    cue.appearance_override={'text_marks':[{'start':2,'end':4,'bold':True,'color':'#FF0000'}]}
    snap=build_visual_cue_snapshot(p,'a')
    image=render_live_snapshot(snap,width=640,height=360)
    assert image != plain
    reds=sum(image.pixelColor(x,y).red()>150 and image.pixelColor(x,y).green()<80
             and image.pixelColor(x,y).alpha()>120 for y in range(image.height()) for x in range(image.width()))
    assert reds > 20
    from twobyteasr.exports.static_caption_contract import shared_static_cue
    assert shared_static_cue(p,cue)
    ass=marked_ass_text(cue.text,snap.text_marks,snap.resolved_caption.style)
    assert '\\b900' in ass and '\\1c&H0000FF&' in ass
    image.save(str(tmp_path/'marked.png'))


def test_split_merge_and_reopen_keep_marks_translation_and_time(tmp_path):
    p=make_project();p.generation_metadata['translations']={'a':'Fireball twice'}
    p.cues[0].appearance_override={'text_marks':[{'start':2,'end':4,'bold':True}],
        'translation':{'style':{'font_size':29},'text_marks':[{'start':0,'end':8,'italic':True}]}}
    stack=QUndoStack();stack.push(split_cue_command(p,'a',2000,'火球','火球'))
    assert p.cues[0].appearance_override['text_marks']==[]
    assert p.cues[1].appearance_override['text_marks']==[{'start':0,'end':2,'bold':True}]
    assert list(p.generation_metadata['translations'].values())==['Fireball','twice']
    assert p.cues[1].appearance_override['translation']['style']['font_size']==29
    # 2026-10-24 daily port: the records come from the daily split snapshot, the
    # translation marks follow the pieces those records hold.
    assert p.cues[0].appearance_override['translation']['text_marks']==[{'start':0,'end':8,'italic':True}]
    assert p.cues[1].appearance_override['translation']['text_marks']==[]
    stack.push(merge_cues_command(p,[c.id for c in p.cues]))
    assert p.cues[0].text=='火球火球'
    assert p.generation_metadata['translations']['a']=='Fireball twice'
    assert p.cues[0].appearance_override['text_marks']==[{'start':2,'end':4,'bold':True}]
    assert p.cues[0].appearance_override['translation']['text_marks']==[{'start':0,'end':8,'italic':True}]
    path=tmp_path/'保存.2byteproj';save_project(p,path);loaded=load_project(path)
    assert loaded.cues[0].appearance_override==p.cues[0].appearance_override
    assert loaded.generation_metadata['translations']==p.generation_metadata['translations']
    stack.undo();stack.undo()
    assert p.cues[0].text=='火球火球' and p.cues[0].end_ms==4000


def test_translation_uses_own_marks_and_sentence_timing():
    app=QApplication.instance() or QApplication([])
    p=make_project();p.generation_metadata['translations']={'a':'Fireball'}
    p.studio_state['bilingual']={'mode':'bilingual'}
    p.cues[0].appearance_override={'text_marks':[{'start':2,'end':4,'bold':True}],
        'translation':{'style':{'font_size':29},'text_marks':[{'start':0,'end':8,'italic':True}]}}
    cues=project_display_cues(p)
    assert cues[1].transform['font_size']==29
    assert cues[1].appearance_override['text_marks']==[{'start':0,'end':8,'italic':True}]
    from twobyteasr.recognition.cue_word_alignment import cue_words
    assert cue_words(p,cues[1])==((), 'translation_has_no_measured_word_alignment')


def test_glossary_independent_usage_and_overlap_no_replacement():
    snapshot=GlossarySnapshot((GlossaryLibrary('game','遊戲','1',terms=(
        TermEntry('火球術',('火求術',),correction_enabled=False,emphasis_enabled=True),
        TermEntry('火球',emphasis_enabled=True),
        TermEntry('冰箭',('冰間',),emphasis_enabled=False))),))
    resolver=TermResolver(snapshot)
    assert resolver.resolve('火求術 冰間').text=='火求術 冰箭'
    text='火球術 火球 火球'
    marks=match_marks(text,json.dumps(snapshot.to_dict(),ensure_ascii=False))
    assert marks==((0,3),(4,6),(7,9))
    assert text=='火球術 火球 火球'
    overrides=GlossarySnapshot((GlossaryLibrary('game','遊戲','2',terms=(
        TermEntry('火球術',('火求術',),priority=10),
        TermEntry('火球術',('火求術',),priority=20,correction_enabled=False,emphasis_enabled=True))),))
    assert TermResolver(overrides).resolve('火求術').text=='火求術'


def test_speaker_template_label_is_live_and_empty_placeholder_disappears():
    app=QApplication.instance() or QApplication([])
    p=make_project()
    from twobyteasr.caption_style.speaker_labels import template_speaker, SetSpeakerLabelCommand
    from twobyteasr.caption_design.web_theme import substitute_placeholders
    assert template_speaker(p,p.cues[0])=='玩家'
    first_hash=build_visual_cue_snapshot(p,'a').stable_hash()
    p.speakers[0].name='隊長'
    assert template_speaker(p,p.cues[0])=='隊長'
    assert build_visual_cue_snapshot(p,'a').stable_hash()!=first_hash
    SetSpeakerLabelCommand(p,'S01',False).redo()
    assert template_speaker(p,p.cues[0])==''
    html=substitute_placeholders('<div class="tag">{{speaker}}</div><i></i>{{text}}',text='正文',speaker='')
    assert 'class="tag"' not in html and '<i></i>' in html
    assert p.cues[0].text=='火球火球'


def test_visual_glossary_uses_project_choice_in_frozen_preview(monkeypatch):
    import subtitle_core as legacy
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    from twobyteasr.rendering.caption_playback_cache import materialize_caption_project
    p=make_project();p.glossary_ids=['right']
    monkeypatch.setattr(legacy,'runtime_enabled_glossary_ids',lambda:['wrong'])
    monkeypatch.setattr(legacy,'load_game_profiles',lambda:{})
    monkeypatch.setattr(legacy,'resolve_glossary_identity',lambda value:value)
    monkeypatch.setattr(legacy,'load_learned_term_payload',lambda:{'games':{'right':{'game':'right','mappings':[
        {'from':'火球','to':'火球','confirmed':True,'provenance':'user_confirmed','emphasis_enabled':True,'correction_enabled':False}]}}})
    revision=StudioRevisionStore(p).render
    assert revision.glossary_ids==('right',)
    shown=materialize_caption_project(revision)
    assert shown.cues[0].appearance_override['text_marks']==[
        {'start':0,'end':2,'highlight':True},{'start':2,'end':4,'highlight':True}]
    assert p.cues[0].appearance_override=={} and p.cues[0].text=='火球火球'


def test_source_style_edit_does_not_recolour_or_resize_translation():
    from twobyteasr.caption_style.scoped_style import style_patch_command
    from twobyteasr.caption_style.style_resolution import resolve_cue_visual
    p=make_project();p.generation_metadata['translations']={'a':'Fireball'}
    p.studio_state['bilingual']={'mode':'bilingual','original_scale':.78,'translation_scale':.66}
    before=project_display_cues(p)
    translation_before=resolve_cue_visual(p,before[1]).style
    style_patch_command(p,['a'],{'font_size':77,'primary_color':'#FF0000'}).redo()
    after=project_display_cues(p)
    assert resolve_cue_visual(p,after[0]).style.font_size==77
    translated=resolve_cue_visual(p,after[1]).style
    assert translated.font_size==translation_before.font_size
    assert translated.primary_color==translation_before.primary_color
    style_patch_command(p,['a'],{'font_size':25},layer='translation').redo()
    after=project_display_cues(p)
    assert resolve_cue_visual(p,after[0]).style.font_size==77
    assert resolve_cue_visual(p,after[1]).style.font_size==25


def test_batch_replace_remaps_marks_and_undo_restores_them():
    from twobyteasr.timeline.studio_commands import BatchReplaceTextCommand
    p=make_project();p.cues[0].text='先用火球再走'
    p.cues[0].appearance_override={'text_marks':[{'start':2,'end':4,'color':'#FF0000'}]}
    before=copy.deepcopy(p.cues[0].appearance_override)
    command=BatchReplaceTextCommand(p,{'a':'現在先用火球再走'})
    command.redo()
    assert p.cues[0].appearance_override['text_marks']==[{'start':4,'end':6,'color':'#FF0000'}]
    command.undo()
    assert p.cues[0].appearance_override==before


def test_authored_bilingual_theme_keeps_its_own_layout_without_duplicate_companion():
    from twobyteasr.caption_design.web_theme import builtin_web_themes
    from twobyteasr.caption_style.bilingual_layout import materialize_display_project
    from twobyteasr.rendering.live_web_preview import prepare_web_configuration
    app=QApplication.instance() or QApplication([])
    p=make_project();p.generation_metadata['translations']={'a':'Fireball twice'}
    p.studio_state['bilingual']={'mode':'bilingual'}
    theme=builtin_web_themes()['doom95'].to_dict()
    theme['cueHtml']+='<div class="translation">{{translation}}</div>'
    p.style_recipes['default']={'name':'自由雙語','engine':'remotion','webTheme':theme}
    shown=materialize_display_project(p)
    assert len(shown.cues)==1
    snap=build_visual_cue_snapshot(shown,'a')
    assert snap.translation=='Fireball twice' and snap.style_recipe['webTheme']['cueHtml']==theme['cueHtml']
    web=prepare_web_configuration(theme,snap.text,'玩家',4,translation=snap.translation)
    assert web.translation=='Fireball twice'
    assert web.strip_key!=prepare_web_configuration(theme,snap.text,'玩家',4,translation='Different').strip_key
