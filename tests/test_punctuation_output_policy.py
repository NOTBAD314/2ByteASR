import os
import json
import copy

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from twobyteasr.projects.studio_project import (SubtitleProject, StudioMedia, StudioCue,
    StudioSpeaker, save_project, load_project)
from twobyteasr.subtitle_rules.punctuation_style import (style_text, style_translation,
    style_cues, MODE_ADD, MODE_NONE, MODE_ORIGINAL, state_value)
from twobyteasr.exports.studio_subtitle_export import (export_subtitle_artifacts,
    export_language_layers, SubtitleExportOptions)


@pytest.mark.parametrize('marks', ['?', '!', '？', '！', '?!', '!?', '？！', '！？', '‼', '⁇', '⁈', '⁉', '‼️'])
def test_default_and_none_remove_all_question_exclamation_forms_and_keep_mapping(marks):
    text = 'えBGM' + marks + 'めっちゃいい' + marks + ' い' + marks + ' な' + marks
    for mode in (MODE_ORIGINAL, MODE_NONE):
        styled = style_text(text, mode)
        assert styled.text == 'えBGM めっちゃいい い な'
        assert style_translation(text, mode) == styled.text
        assert style_text(styled.text, mode).text == styled.text
        assert all(target is None or styled.text[target] == text[index]
                   for index, target in enumerate(styled.index_map))
    assert marks in style_text(text, MODE_ADD).text


def test_default_keeps_other_punctuation_spacing_url_and_terms():
    text = '  3.14，12:30。  https://example.test/a?x=1!2&y=3 Node.js Who?! え?'
    styled = style_text(text, MODE_ORIGINAL, protected_terms=('Who?!',))
    assert styled.text == '  3.14，12:30。  https://example.test/a?x=1!2&y=3 Node.js Who?! え'
    assert style_text('えBGMめっちゃいい? い? な!', MODE_ORIGINAL).text == 'えBGMめっちゃいい い な'
    from twobyteasr.subtitle_rules.chinese_punctuation import clean
    assert clean('术语?!') == '术语?!'


@pytest.mark.parametrize('choice', [None, 'original', {'mode': 'original', 'version': 1}, {'mode': 'none', 'version': 1}])
def test_old_project_outputs_preview_list_layers_and_json_are_reversible(tmp_path, choice):
    from twobyteasr.studio.studio_cue_table import CueTableModel
    original = 'えBGMめっちゃいい? い? な!'
    translated = 'BGM真好听？！ 是吧⁉'
    p = SubtitleProject(StudioMedia('', duration_ms=4000),
        cues=[StudioCue('a', 0, 3000, original, 'S00')], speakers=[StudioSpeaker('S00', '人物')])
    p.generation_metadata['translations'] = {'a': translated}
    if choice is not None:
        p.studio_state['punctuation'] = choice
    p.validate()
    before = copy.deepcopy(p.to_dict())
    artifacts = export_subtitle_artifacts(p, tmp_path, 'plain',
        SubtitleExportOptions(frozenset({'srt', 'txt', 'ass', 'json'}), 'both'))
    payload = json.loads(next(a.path for a in artifacts if a.format == 'json').read_text(encoding='utf-8'))
    assert payload['cues'][0]['text'] == 'えBGMめっちゃいい い な'
    assert payload['cues'][0]['original_text'] == original
    result = export_language_layers(p, tmp_path, 'layers', ('original', 'translation', 'bilingual'), speaker_mode='both')
    for artifact in result.artifacts:
        assert not any(mark in artifact.path.read_text(encoding='utf-8') for mark in '?!？！‼⁇⁈⁉')
    assert style_cues(p, p.cues)[0].text == 'えBGMめっちゃいい い な'
    model = CueTableModel()
    model.set_project(p)
    assert model.data(model.index(0, 3), Qt.DisplayRole) == 'えBGMめっちゃいい い な'
    assert model.data(model.index(0, 3), Qt.EditRole) == original
    assert p.to_dict() == before
    reopened = load_project(save_project(p, tmp_path / 'keep.2byteproj'))
    reopened.studio_state['punctuation'] = state_value(MODE_ADD)
    assert '?' in style_cues(reopened, reopened.cues)[0].text
    assert reopened.cues[0].text == original
