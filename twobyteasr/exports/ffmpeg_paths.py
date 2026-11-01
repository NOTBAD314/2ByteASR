"""Literal file paths in FFmpeg filter options, without an intervening shell."""
from pathlib import Path


def filter_value(value: str) -> str:
    """Escape the option parser, then the enclosing filtergraph parser.

    A backslash inside single quotes does not escape a quote in FFmpeg's
    tokenizer. Escape each parsing layer explicitly instead; Unicode remains
    intact and punctuation cannot become another option, filter or link.
    """
    option = ''.join('\\' + char if char in "\\':" or char.isspace() else char
                     for char in value)
    return ''.join('\\' + char if char in "\\'[],;" or char.isspace() else char
                   for char in option)


def filter_path(path) -> str:
    return filter_value(Path(path).resolve().as_posix())
