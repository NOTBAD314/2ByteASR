import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPaintDevice
from PySide6.QtWidgets import QApplication, QWidget

import twobyteasr.studio_ui as studio_ui
from twobyteasr.studio_hub import StudioHubMixin
from twobyteasr.studio_review_ui import StudioReviewMixin
from twobyteasr.studio_ui import SubtitleStudioPage


REVIEW_METHODS = (
    "_select_review_cue_immediately",
    # P25.3 review-convergence round additions
    "_adopt_model_text",
    "_adopt_review_candidate",
    "_advance_review_after_resolution",
    "_confirm_current_review",
    "_exit_review",
    "_mark_review_resolved",
    "_pause_review_context",
    "_play_review_context",
    # 2026-10-15 review replay stops on media time and holds the selection
    "_arm_review_fallback",
    "_review_fallback_due",
    "_review_playback_tick",
    "_review_stop_due",
    "_park_review_playback",
    "_release_review_playback",
    "_review_held_cue_id",
    "_refresh_review_risks",
    # 2026-09-18 分片 QC 扫描（进入路径无阻塞）
    "_QC_SCAN_CHUNK",
    "_start_chunked_qc_scan",
    "_finish_chunked_qc_scan",
    "_refresh_review_summary_strip",
    "_set_continuous_review",
    "_set_review_mode",
    "_skip_current_review",
    "_set_cue_filter",
    "_toggle_review_dock",
    "_show_filter_menu",
    "_activate_filter",
    "_jump_to_row",
    "_step_cue",
    "_focus_review_editor",
    "_refresh_current_review_context",
)

HUB_METHODS = (
    "_apply_hub_paper_texture",
    "_refresh_studio_empty_state",
    "_project_library_records",
    "_open_recent_project_card",
    "_remove_recent_project_metadata",
    "_set_hub_toolbar_mode",
    "_show_hub_preferences",
    "_choose_hub_project_root",
    "_save_hub_preferences",
    "_clear_recent_project_metadata",
    "_recent_project_menu",
)

STUDIO_SIGNALS = {
    'ai_refine_signal',
    'ai_stream_line_signal',
    'ai_web_adjust_signal',
    'ai_web_theme_signal',
    'library_records_ready_signal',
    'library_cover_ready_signal',
    'recognition_cancel_requested',
    'recognition_detail_requested',

    "ai_provider_progress_signal",
    "return_requested",
    "recognition_requested",
    "cover_ready_signal",
    "waveform_ready_signal",
    "waveform_progress_signal",
    "waveform_failed_signal",
    "startup_milestone_signal",
    "media_ingest_ready_signal",
    "project_media_probe_ready_signal",
    "ai_ready_signal",
    "ai_failed_signal",
    "ai_stage_signal",
    "ai_provider_probe_signal",
    "ai_revision_signal",
    "ai_revision_failed_signal",
    "reasr_ready_signal",
    "reasr_failed_signal",
    "ass_ready_signal",
    "ass_failed_signal",
    "autosave_ready_signal",
    "autosave_failed_signal",
    "advanced_preview_ready_signal",
    "advanced_preview_failed_signal",
    "ai_variant_preview_ready_signal",
    "close_ready_signal",
}

STUDIO_SIGNAL_SIGNATURES = {
    "return_requested()",
    "recognition_requested(QString,QString,QString)",
    "cover_ready_signal(QString,QString)",
    "waveform_ready_signal(int,QString,QString,PyObject)",
    "waveform_progress_signal(int,QString,QString)",
    "library_cover_ready_signal(QString,int,int,QImage)",
    "waveform_failed_signal(int,QString,QString)",
    "startup_milestone_signal(QString,PyObject)",
    "media_ingest_ready_signal(PyObject)",
    "project_media_probe_ready_signal(int,QString,PyObject)",
    "ai_ready_signal(PyObject)",
    "ai_failed_signal(QString)",
    "ai_stage_signal(int,QString)",
    "ai_provider_probe_signal(int,QString,QString,PyObject)",
    "ai_revision_signal(int,int,PyObject,PyObject,QString)",
    "ai_revision_failed_signal(int,QString)",
    "reasr_ready_signal(PyObject)",
    "reasr_failed_signal(QString)",
    "ass_ready_signal(int,QString)",
    "ass_failed_signal(int,QString)",
    "autosave_ready_signal(int)",
    "autosave_failed_signal(int,QString)",
    "advanced_preview_ready_signal(PyObject,int,QString,bool)",
    "advanced_preview_failed_signal(PyObject,int,QString)",
    "ai_variant_preview_ready_signal(int,int,QString,bool)",
    "close_ready_signal(PyObject)",
}


def test_review_behavior_mixin_structure_resolution_and_qobject_contract():
    assert not issubclass(StudioReviewMixin, QObject)
    assert "__init__" not in StudioReviewMixin.__dict__
    assert not any(
        isinstance(value, Signal) for value in StudioReviewMixin.__dict__.values()
    )
    assert not {
        name
        for name in StudioReviewMixin.__dict__
        if not name.startswith("__") and name not in REVIEW_METHODS
    }
    assert set(REVIEW_METHODS) <= set(StudioReviewMixin.__dict__)
    assert '_set_check_state' not in StudioReviewMixin.__dict__

    # MRO 守卫按意图断言：页面 → 行为 mixin（hub/review 在最前）→ Qt 基类。
    # 拆分继续插入新 flow mixin 时序列自然变化，不再钉死具体清单。
    mro_names = [cls.__name__ for cls in SubtitleStudioPage.__mro__]
    assert mro_names[:4] == ["SubtitleStudioPage", "StudioHubMixin", "StudioSentenceRefineMixin", "StudioReviewMixin"]
    widget_index = mro_names.index("QWidget")
    assert widget_index > 3, "behavior mixins must sit between the page and QWidget"
    assert all(name.endswith("Mixin") for name in mro_names[1:widget_index])
    assert not (set(REVIEW_METHODS) & set(StudioHubMixin.__dict__))
    assert not (set(REVIEW_METHODS) & set(SubtitleStudioPage.__dict__))
    assert not (set(REVIEW_METHODS) & set(dir(QWidget)))
    for name in REVIEW_METHODS:
        assert getattr(SubtitleStudioPage, name) is getattr(StudioReviewMixin, name)
    for name in HUB_METHODS:
        assert getattr(SubtitleStudioPage, name) is getattr(StudioHubMixin, name)
    for name in ("eventFilter", "keyPressEvent", "resizeEvent"):
        assert name in SubtitleStudioPage.__dict__

    assert {
        name
        for name, value in SubtitleStudioPage.__dict__.items()
        if isinstance(value, Signal)
    } == STUDIO_SIGNALS
    app = studio_ui.QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    try:
        meta = page.metaObject()
        assert meta.className() == "SubtitleStudioPage"
        assert {
            signature
            for signature in STUDIO_SIGNAL_SIGNATURES
            if meta.indexOfSignal(signature) >= 0
        } == STUDIO_SIGNAL_SIGNATURES
    finally:
        page.close_page()
