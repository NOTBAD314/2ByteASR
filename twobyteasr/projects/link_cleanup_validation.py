"""Strict all-or-nothing AI preview validation for imported source captions."""
from __future__ import annotations
import json
import math


def validate_cleanup_response(raw, cues):
    payload=json.loads(raw) if isinstance(raw,str) else raw
    if not isinstance(payload,dict) or not isinstance(payload.get("changes"),list):
        raise ValueError("AI 校对结果缺少 changes 数组；原字幕保持不变。")
    source={cue.id:cue for cue in cues}
    seen=set()
    for item in payload["changes"]:
        if not isinstance(item,dict) or not {"cue_id","original","replacement","reason"}<=set(item):
            raise ValueError("AI 校对字段不完整；原字幕保持不变。")
        if set(item)-{"cue_id","original","replacement","reason","confidence"}:
            raise ValueError("AI 校对返回了未允许的字段；不能修改字幕时间或来源。")
        identity=item["cue_id"]
        if not isinstance(identity,str) or identity not in source or identity in seen:
            raise ValueError("AI 校对包含重复或范围外的字幕 ID；整批结果未应用。")
        seen.add(identity)
        cue=source[identity]
        if item["original"]!=cue.text or not isinstance(item["original"],str):
            raise ValueError("AI 校对原文与目标字幕不一致；整批结果未应用。")
        if not isinstance(item["replacement"],str) or not item["replacement"].strip():
            raise ValueError("AI 校对返回空白字幕；原文保持不变。")
        if not isinstance(item["reason"],str):
            raise ValueError("AI 校对说明字段无效；原字幕保持不变。")
        confidence=item.get("confidence",.8)
        if (not isinstance(confidence,(int,float)) or isinstance(confidence,bool)
                or not math.isfinite(confidence) or not 0<=confidence<=1):
            raise ValueError("AI 校对置信度无效；整批结果未应用。")
        if cue.start_ms<0 or cue.end_ms<=cue.start_ms:
            raise ValueError("目标字幕时间范围无效；请先检查工程。")
    return payload
