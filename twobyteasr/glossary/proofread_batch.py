"""Validate all selected replacements against the same original caption."""


def adoption_text(text, issues):
    spans = []
    for issue in issues:
        a, b = issue["span"]
        if issue.get("stale") or not 0 <= a <= b <= len(text) or text[a:b] != issue["original"]:
            raise ValueError("建议已对不上当前原文")
        if any(a < end and start < b or a == b == start == end for start, end in spans):
            raise ValueError("建议的原文区间重叠")
        spans.append((a, b))
    for issue in sorted(issues, key=lambda i: i["span"], reverse=True):
        a, b = issue["span"]
        text = text[:a] + issue["replacement"] + text[b:]
    return text
