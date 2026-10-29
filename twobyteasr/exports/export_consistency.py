"""Export presentation of the shared, read-only committed-caption contract."""
from __future__ import annotations
import json

from ..projects.subtitle_consistency import validate_export_view


class SubtitleDataError(ValueError):
    def __init__(self, result, speaker_id=""):
        self.result = result
        issue = result.errors[0]
        location = speaker_id or "当前范围"
        if issue.cue_index is not None:
            location += f" 第 {issue.cue_index + 1} 条字幕"
        super().__init__(f"{location}无法安全导出：{issue.reason} 原工程保留。")

    def details(self):
        return json.dumps(self.result.to_dict(), ensure_ascii=False, indent=2)


def require_consistent_view(project, cues, *, speaker_id=""):
    """Only selected timeline cues; word warnings never block sentence SRT."""
    result = validate_export_view(project, cues, stage="export")
    if not result.ok:
        raise SubtitleDataError(result, speaker_id)
    return result
