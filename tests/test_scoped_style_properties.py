import copy
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import StudioCue, SubtitleProject, StudioMedia
from twobyteasr.caption_style.scoped_style import style_patch_command, effective_layer_style


def project():
    value = SubtitleProject(media=StudioMedia(""), cues=[StudioCue(str(i), i*1000, (i+1)*1000, '字幕') for i in range(6)])
    value.validate()
    return value


def test_shared_template_and_noncontiguous_selection_are_isolated():
    p = project(); template = copy.deepcopy(p.styles)
    p.cues[1].appearance_override = {'primary_color': '#FF0000', 'translation': {'style': {'font_size': 31}}}
    p.cues[4].appearance_override = {'primary_color': '#00FF00'}
    before = copy.deepcopy(p.cues)
    stack = QUndoStack()
    stack.push(style_patch_command(p, ['1', '4'], {'font_size': 79}))
    assert p.styles == template
    assert [effective_layer_style(p, c).font_size for c in p.cues] == [56, 79, 56, 56, 79, 56]
    assert effective_layer_style(p, p.cues[1]).primary_color == '#FF0000'
    assert effective_layer_style(p, p.cues[4]).primary_color == '#00FF00'
    assert p.cues[1].appearance_override['translation']['style']['font_size'] == 31
    stack.undo()
    assert [c.appearance_override for c in p.cues] == [c.appearance_override for c in before]


def test_translation_and_nested_recipe_are_private():
    p = project()
    p.style_recipes['default'] = {'name': '自由主題', 'webTheme': __import__('twobyteasr.caption_design.web_theme', fromlist=['builtin_web_themes']).builtin_web_themes()['doom95'].to_dict(), 'motion': {'mode': 'none'}}
    p.validate()
    original = copy.deepcopy(p.style_recipes)
    command = style_patch_command(p, ['1'], {'font_size': 25}, layer='translation',
                                  recipe_patch={'outline': {'shadow': {'opacity': 0.2}}})
    command.redo()
    assert p.style_recipes == original
    assert effective_layer_style(p, p.cues[1]).font_size == 56
    assert effective_layer_style(p, p.cues[1], 'translation').font_size == 25
    assert not p.cues[0].appearance_override
    command.undo()
    assert not p.cues[1].appearance_override
