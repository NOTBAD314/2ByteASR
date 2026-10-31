"""SRT wire representation. No project mutation and no expected-data input."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SIDECAR_FORMAT = "2byteasr-subtitles"


def sidecar_path(path: Path) -> Path:
    return path.with_name(path.name + ".2byte.json")


def normalize_srt_text(text: str) -> str:
    """Only newline encoding changes; spaces and blank lines are manuscript."""
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


_TIME = r"[0-9]{2,}:[0-5][0-9]:[0-5][0-9],[0-9]{3}"
_HEADER = rf"[ \t]*[0-9]+[ \t]*\n{_TIME}[ \t]*-->[ \t]*{_TIME}[ \t]*\n"
# Keep the historical three groups (start, end, text). A numeric body line
# alone is not a header. Exactly two LFs are framing; any preceding LFs are text.
_SRT_BLOCK = re.compile(
    rf"(?ms)^[ \t]*[0-9]+[ \t]*\n({_TIME})[ \t]*-->[ \t]*({_TIME})[ \t]*\n"
    rf"(.*?)(?=\n\n{_HEADER}|\Z)"
)


def parse_srt_time(value: str) -> int:
    hours, minutes, tail = value.split(":")
    seconds, millis = tail.split(",")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


@dataclass(frozen=True)
class SrtRow:
    number: int
    start_ms: int
    end_ms: int
    text: str


def parse_srt(content: str) -> tuple[list[SrtRow], list[tuple[int, str]]]:
    """Read our documented SRT framing without seeing the source cues.

    The writer terminates the file with one LF. Remove precisely that LF,
    not rstrip(), so the final cue retains its own trailing blank lines.
    Nonempty content outside blocks, malformed numbering and invalid time
    ranges are errors, including in a supposedly empty track.
    """
    content = normalize_srt_text(content)
    errors: list[tuple[int, str]] = []
    if content and not content.endswith("\n"):
        errors.append((1, "文件缺少结束换行"))
    content = content.removesuffix("\n")
    rows: list[SrtRow] = []
    cursor = 0
    for match in _SRT_BLOCK.finditer(content):
        index = len(rows) + 1
        if content[cursor:match.start()] != ("\n\n" if rows else ""):
            errors.append((index, "条目外存在无法解析的内容"))
        row = SrtRow(int(match.group(0).split("\n", 1)[0]),
                     parse_srt_time(match.group(1)), parse_srt_time(match.group(2)), match.group(3))
        if row.number != index:
            errors.append((index, f"字幕编号应为 {index}，实际为 {row.number}"))
        if row.end_ms <= row.start_ms:
            errors.append((index, "结束时间不晚于开始时间"))
        rows.append(row)
        cursor = match.end()
    if content[cursor:]:
        errors.append((len(rows) + 1, "存在无法解析的字幕标头或正文"))
    return rows, errors
