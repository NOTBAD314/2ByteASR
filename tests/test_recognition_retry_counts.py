import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QLabel
from tests.test_recognition_history import _app,_report_payload
from twobyteasr.recognition.recognition_history import RecognitionHistoryDetail,parse_recognition_report


def test_interrupted_detail_shows_failed_polish_work_separately_from_review_issues(tmp_path):
    app=_app()
    payload=_report_payload()
    payload.update(status='interrupted',polishing_summary={'success_cues':911,'fallback_cues':68,'fallback_batches':6},
        review_items=[{'severity':'review','category':'时间待看','message':'仅一项审核问题'}])
    payload['task']={'remote_total':3,'remote_requests':{
        '2':{'start':2398.3826875,'end':3601.024},'0':{'start':0,'end':1123.4413125},
        '1':{'start':1123.4413125,'end':2398.3826875}}}
    path=tmp_path/'report.json';path.write_text(json.dumps(payload,ensure_ascii=False),'utf-8')
    detail=RecognitionHistoryDetail(parse_recognition_report(path))
    try:
        labels=[label.text() for label in detail.findChildren(QLabel)]
        assert '校对待重试' in labels
        assert '6 批 · 68 条处理记录（已保留原文）' in labels
        assert '0:00–18:43、18:43–39:58、39:58–60:01' in labels
    finally:detail.close();detail.deleteLater();app.processEvents()


def test_completed_polish_does_not_treat_review_notes_as_failed_work(tmp_path):
    app=_app()
    payload=_report_payload()
    payload.update(polishing_summary={'success_cues':979,'fallback_cues':0},
        review_items=[{'severity':'review','category':'时间待看','message':'需要人工检查'}])
    path=tmp_path/'report.json';path.write_text(json.dumps(payload,ensure_ascii=False),'utf-8')
    detail=RecognitionHistoryDetail(parse_recognition_report(path))
    try:assert '校对待重试' not in [label.text() for label in detail.findChildren(QLabel)]
    finally:detail.close();detail.deleteLater();app.processEvents()
