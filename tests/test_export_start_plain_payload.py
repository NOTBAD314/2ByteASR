"""Export start serializes the frozen snapshot as plain data (2026-11-19).

Daily 9c60392 closed the whole app on 导出: the GUI thread spent >2 s in a
per-node ``copy.deepcopy`` of a large ``studio_state`` (``to_dict`` ->
``validate`` -> ``_mapping``) and then died with an access violation inside
``deepcopy``. The export snapshot is worker-owned, so ``_job`` now detaches it
once with a plain-data copy, and project data never runs object copy hooks.
"""
import copy
import json

import pytest
from PySide6.QtCore import QObject, QPointF, QSettings, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from twobyteasr.exports import studio_export_ui
from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
from twobyteasr.projects.project_snapshot import copy_json_value, document_snapshot
from twobyteasr.projects.studio_project import (
    ProjectValidationError, StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
    detached_snapshot_payload, default_style)

PLAIN = (str, int, float, bool, type(None))


def _non_plain(value, path='', out=None):
    out = [] if out is None else out
    if isinstance(value, dict):
        for key, item in value.items():
            if type(key) is not str:
                out.append((path, type(key).__name__))
            _non_plain(item, f'{path}.{key}', out)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _non_plain(item, f'{path}[{index}]', out)
    elif type(value) not in PLAIN:
        out.append((path, type(value).__name__))
    return out


def _real_like_project(tmp_path, cues=240):
    """Shape of a real edited project: styled captions with per-cue layout,
    two speakers, caption-timeline instances and a deep AI refine history
    (the 2026-11-19 report: 436 cues, multi-MB studio_state)."""
    rows = []
    for index in range(cues):
        start = index * 2500
        rows.append(StudioCue(
            f'cue-{index}', start, start + 2000, f'第 {index} 句字幕 line {index}',
            speaker_id='S00' if index % 3 else 'S01', original_text=f'原文 {index}',
            evidence_refs=[f'link-{index}'],
            appearance_override={'primary_color': '#FFEECC', 'outline': {'width': 2.5, 'color': '#101010'}},
            transform={'position_x': 960.0, 'position_y': 980.0,
                       'language_layers': {'zh': {'position_x': 960.0}, 'en': {'position_x': 960.0}},
                       'initial_layout': {'lines': [[0, 12], [12, 24]]}}))
    refine = {f'cue-{index}': {'rounds': [
        {'request': {'text': f'第 {index} 句', 'context': [f'ctx {n}' for n in range(6)]},
         'result': {'candidates': [{'text': f'候选 {n}', 'scores': {'fluency': 0.9, 'terms': [n, n + 1]}}
                                   for n in range(4)]}} for _ in range(3)]}
        for index in range(cues)}
    timeline = {'instances': {row.id: {'source': {'cue_id': row.id, 'span': [row.start_ms, row.end_ms]},
                                       'words': [{'w': f'w{n}', 't': [row.start_ms + n * 100, row.start_ms + n * 100 + 90]}
                                                 for n in range(8)]} for row in rows},
                'source_archive': {'generation': 3, 'segments': [[n, n + 1] for n in range(200)]}}
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / '源 视频.mp4'), duration_ms=cues * 2500 + 5000,
                          width=1920, height=1080),
        cues=rows,
        speakers=[StudioSpeaker('S00', '主持'), StudioSpeaker('S01', '嘉宾')],
        styles=[default_style()],
        generation_metadata={'language': 'zh', 'translations': {row.id: {'en': row.text} for row in rows}},
        asr_evidence={f'link-{index}': {'end_ms': index * 2500 + 2000, 'words': [[n, 'x'] for n in range(5)]}
                      for index in range(cues)},
        render_settings={'play_res_x': 1920, 'play_res_y': 1080},
        studio_state={'ai_sentence_refine': refine, 'caption_timeline': timeline,
                      'layout': {'panels': [320, 1200, 400]}, 'zoom': 1.25,
                      'review_risks': {'cue-0': ['transient']}},
    )
    project.validate()
    return project


@pytest.fixture
def make_workspace(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / 'config.ini'), QSettings.IniFormat)
    monkeypatch.setattr(studio_export_ui, 'QSettings', lambda *args: settings)
    monkeypatch.setattr(studio_export_ui, 'cached_encoder_choices', lambda *args: ['libx264'])
    made = []

    def make(project):
        ui = StudioExportWorkspace(project, str(tmp_path / 'preview.ass'))
        made.append(ui)
        return ui
    yield make
    for ui in made:
        ui.close(); ui.deleteLater()
    app.processEvents()


def test_export_job_serializes_snapshot_without_a_gui_thread_deepcopy_walk(make_workspace, tmp_path, monkeypatch):
    project = _real_like_project(tmp_path)
    ui = make_workspace(project)
    settings = ui._render_settings()
    calls = []
    real = copy.deepcopy
    document_nodes = ('rounds', 'candidates', 'words', 'segments', 'translations')

    def counting(value, memo=None, _nil=[]):
        # Only nodes of the document's JSON graph (studio_state, evidence,
        # metadata) are counted; per-cue style records are not this path.
        if isinstance(value, dict) and any(key in value for key in document_nodes):
            calls.append(sorted(value)[:3])
        return real(value, memo)
    monkeypatch.setattr(copy, 'deepcopy', counting)
    job = ui._job(tmp_path / 'out.mp4', settings=settings)
    monkeypatch.setattr(copy, 'deepcopy', real)

    payload = job.export_project_data
    assert _non_plain(payload) == []
    json.dumps(payload, ensure_ascii=False)
    assert len(payload['cues']) == len(project.cues)
    assert payload['studio_state']['ai_sentence_refine']['cue-7']['rounds'][2]['result']['candidates'][3]['text'] == '候选 3'
    assert 'review_risks' not in payload['studio_state']
    # The old path deep-copied studio_state/evidence per node (snapshot and
    # validate; asdict walked it again) on the GUI thread. Now: never.
    assert calls == [], (len(calls), calls[:5])
    # The worker payload shares nothing with the frozen snapshot or the editor.
    payload['studio_state']['ai_sentence_refine']['cue-7']['rounds'][0]['request']['text'] = 'worker'
    payload['cues'][0]['transform']['position_x'] = -1
    assert ui._export_project.studio_state['ai_sentence_refine']['cue-7']['rounds'][0]['request']['text'] == '第 7 句'
    assert project.studio_state['ai_sentence_refine']['cue-7']['rounds'][0]['request']['text'] == '第 7 句'
    assert ui._export_project.cues[0].transform['position_x'] != -1
    assert project.cues[0].transform['position_x'] == 960.0


def test_detached_payload_matches_to_dict(tmp_path):
    project = _real_like_project(tmp_path, cues=30)
    owned = detached_snapshot_payload(document_snapshot(project))
    legacy = document_snapshot(project).to_dict()
    assert json.dumps(owned, sort_keys=True, ensure_ascii=False) == json.dumps(legacy, sort_keys=True, ensure_ascii=False)


def test_qt_values_in_project_data_become_plain_and_live_objects_are_refused(make_workspace, tmp_path):
    project = _real_like_project(tmp_path, cues=12)
    project.studio_state['cover_template'] = {'accent': QColor(255, 0, 0), 'shade': QColor(0, 0, 0, 128),
                                              'anchor': QPointF(0.5, 0.25), 'align': Qt.AlignmentFlag.AlignHCenter}
    ui = make_workspace(project)
    job = ui._job(tmp_path / 'out.mp4', settings=ui._render_settings())
    template = job.export_project_data['studio_state']['cover_template']
    assert template == {'accent': '#ff0000', 'shade': '#80000000', 'anchor': [0.5, 0.25],
                        'align': int(Qt.AlignmentFlag.AlignHCenter.value)}
    assert _non_plain(job.export_project_data) == []

    owner = QObject()
    project.studio_state['cover_template'] = {'preview_owner': owner}
    with pytest.raises(ProjectValidationError, match=r'cover_template\.preview_owner.*QObject'):
        ui._job(tmp_path / 'out2.mp4', settings=ui._render_settings())
    # Validation never deep-copies the live wrapper either.
    with pytest.raises(ProjectValidationError, match='QObject'):
        project.validate()


def test_copy_json_value_keeps_plain_and_legacy_values():
    shared = {'k': [1, 2]}
    source = {'a': shared, 'b': shared, 't': (1, 'x'), 'f': 1.5, 'n': None, 'raw': b'\x00'}
    copied = copy_json_value(source)
    assert copied == source and copied['a'] is not shared
    marker = object.__new__(type('Legacy', (), {}))
    detached = copy_json_value({'legacy': marker, 'color': QColor('#123456')})
    assert detached['color'] == '#123456'
    assert type(detached['legacy']).__name__ == 'Legacy' and detached['legacy'] is not marker
