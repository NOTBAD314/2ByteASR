"""Tests for zero-friction quick glossary capture (local parser, safety lint, AI extraction)."""
from __future__ import annotations

from twobyteasr.glossary.quick_term_capture import (
    candidates_from_project_edits,
    extract_terms_with_ai,
    parse_freeform_terms,
)


def test_parse_freeform_terms_handles_mixed_formats_and_blocks_dangerous_aliases():
    raw = """
    杰风 -> 捷风
    欧门 = 欧门
    大 -> 打
    的 -> 得
    深海明珠（深海明主、生海明珠）
    这版本新特务「壹决（一决）」和「暮蝶」很热门。
    派蒙\t角色\t派门、拍萌
    """
    rows = parse_freeform_terms(raw)
    by_pair = {(r.source, r.target): r for r in rows}

    assert ("杰风", "捷风") in by_pair and by_pair[("杰风", "捷风")].checked is True
    assert ("深海明主", "深海明珠") in by_pair and by_pair[("深海明主", "深海明珠")].checked is True
    assert ("一决", "壹决") in by_pair and by_pair[("一决", "壹决")].checked is True
    assert ("暮蝶", "暮蝶") in by_pair and by_pair[("暮蝶", "暮蝶")].is_alias is False
    assert ("派门", "派蒙") in by_pair and by_pair[("派门", "派蒙")].category == "角色"

    # Single-char common-word aliases must be flagged dangerous & unchecked by default
    assert by_pair[("大", "打")].dangerous is True and by_pair[("大", "打")].checked is False
    assert by_pair[("的", "得")].dangerous is True and by_pair[("的", "得")].checked is False


def test_candidates_from_project_edits():
    rows = candidates_from_project_edits([
        {"source": "元神", "target": "原神", "count": 3, "left": 9},
        {"source": "打", "target": "大", "count": 2, "left": 5},
    ])
    assert len(rows) == 2
    assert rows[0].checked is True and "9 处" in rows[0].note
    assert rows[1].dangerous is True and rows[1].checked is False


def test_extract_terms_with_ai_uses_single_provider_and_lints_output():
    class _FakeProvider:
        def structured_complete(self, messages, schema, **kwargs):
            assert kwargs["stage"] == "glossary_update"
            return {
                "summary": "整理出 2 个角色与易听错词",
                "entries": [
                    {"to": "捷风", "category": "角色", "aliases": ["杰风", "大"]},
                    {"to": "蕾兹", "category": "角色", "aliases": ["雷兹"]},
                ],
            }

    rows, summary = extract_terms_with_ai("瓦罗兰特特务捷风和蕾兹", "瓦罗兰特", {}, provider=_FakeProvider())
    assert "整理出" in summary
    by_pair = {(r.source, r.target): r for r in rows}
    assert by_pair[("杰风", "捷风")].checked is True
    assert by_pair[("大", "捷风")].dangerous is True and by_pair[("大", "捷风")].checked is False
    assert by_pair[("雷兹", "蕾兹")].checked is True


def test_bunny_quick_capture_terms_tool_is_registered():
    from twobyteasr.app.bunny_tools import TOOLS
    assert "quick_capture_terms" in TOOLS

