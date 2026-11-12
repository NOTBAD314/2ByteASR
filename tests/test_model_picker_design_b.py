import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]


def _app():
    return QApplication.instance() or QApplication([])


def test_qwen_audio_speakers_are_off_by_default_only_on_the_official_api():
    from twobyteasr.providers.asr_api_process import qwen_diarize_hint
    from twobyteasr.providers.qwen31_asr import FILETRANS, QWEN3_FILETRANS
    official = {'provider': 'qwen_cloud_filetrans', 'model': FILETRANS}
    assert qwen_diarize_hint(official, {'models': {}}) == {'filetrans_diarize': False}
    assert qwen_diarize_hint(official, {'models': {'qwen_audio_diarize': True}}) == {'filetrans_diarize': True}
    assert qwen_diarize_hint({'provider': 'qwen31_filetrans', 'model': FILETRANS}, {}) == {}
    assert qwen_diarize_hint({'provider': 'qwen_cloud_filetrans', 'model': QWEN3_FILETRANS}, {}) == {}


def test_picker_scores_and_role_recommendations():
    from twobyteasr.local_models.model_benchmarks import reference_entry
    from twobyteasr.local_models.model_picker_copy import recommended_for
    assert reference_entry('qwen_cloud_filetrans', 'accuracy', 'zh')['score'] == 70
    assert reference_entry('moss', 'accuracy', 'zh')['score'] == 85
    assert recommended_for('timeline') == ('qwen_aligner', 'firered')
    assert recommended_for('review') == ('qwen_local',)


def test_picker_cards_show_prices_only_on_cloud_and_recommended_first():
    _app()
    from twobyteasr.local_models.model_workshop import ModelPickerPanel, ModelWorkshopPage
    page = ModelWorkshopPage(ROOT, {'models': {}})
    picker = ModelPickerPanel(page, 'timeline')
    order = picker.ordered_keys()
    assert order[:2] == ['qwen_aligner', 'firered'] or order[1:3] == ['qwen_aligner', 'firered']
    primary = ModelPickerPanel(page, 'primary')
    assert primary.cards['qwen_cloud_filetrans'].model.name == 'Qwen Audio 3.1'
    assert primary.cards['qwen_cloud_filetrans'].diarize is not None
    assert not primary.cards['qwen_cloud_filetrans'].diarize.isChecked()
    texts = lambda card: [w.text() for w in card.findChildren(type(card.summary_label)) if w.objectName() == 'pickerChip']
    assert '2 元 / 小时' in texts(primary.cards['mosi_moss_pro'])
    assert not any('元' in t for t in texts(primary.cards['firered']))
    primary.cards['firered'].matches('local') and primary._set_filter('cloud')
    assert primary.cards['firered'].isHidden()
    for widget in (picker, primary, page):
        widget.deleteLater()
