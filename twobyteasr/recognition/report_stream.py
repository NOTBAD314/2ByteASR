"""Project a journal without holding the event log in Python memory."""

from __future__ import annotations

import json
import mmap
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


INLINE_BYTES = 128 * 1024
_MAX_VALUE_BYTES = 16 * 1024 * 1024
_SPACE = re.compile(rb"[ \t\r\n]*")
_STRING = re.compile(rb'"[^"\\\x00-\x1f]*(?:\\[^\r\n][^"\\\x00-\x1f]*)*"')
_STRUCTURE = re.compile(rb'["{}\[\]]')
_PRIMITIVE = re.compile(rb'[^,}\]\r\n\t ]+')
_ARRAYS = {"events", "review_items"}


class ReportCancelled(ValueError):
    pass


class WrongReportSchema(ValueError):
    pass


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise ReportCancelled()


class _Reader:
    def __init__(self, data, cancel):
        self.data = data
        self.cancel = cancel

    def next(self, pos):
        return _SPACE.match(self.data, pos).end()

    def require(self, pos, char):
        if self.data[pos:pos + 1] != char:
            raise ValueError(f"JSON 格式无效（字节 {pos}）")
        return self.next(pos + 1)

    def _match(self, pattern, pos):
        match = pattern.match(self.data, pos, min(len(self.data), pos + _MAX_VALUE_BYTES))
        if match is None:
            raise ValueError(f"JSON 值缺失或过大（字节 {pos}）")
        return match.end()

    def value_end(self, pos):
        first = self.data[pos:pos + 1]
        if first == b'"':
            return self._match(_STRING, pos)
        if first not in (b'{', b'['):
            return self._match(_PRIMITIVE, pos)
        stop = min(len(self.data), pos + _MAX_VALUE_BYTES)
        cursor = pos + 1
        depth = 1
        while depth:
            match = _STRUCTURE.search(self.data, cursor, stop)
            if match is None:
                raise ValueError(f"JSON 容器未关闭或过大（字节 {pos}）")
            token = match.group()
            cursor = match.end()
            if token == b'"':
                cursor = self._match(_STRING, match.start())
            elif token in (b'{', b'['):
                depth += 1
            else:
                depth -= 1
        return cursor

    def decode(self, start, end):
        return json.loads(self.data[start:end])

    def array(self, pos):
        pos = self.require(pos, b'[')
        if self.data[pos:pos + 1] == b']':
            return pos + 1
        while True:
            _check(self.cancel)
            end = self.value_end(pos)
            yield pos, end
            pos = self.next(end)
            if self.data[pos:pos + 1] == b']':
                return pos + 1
            pos = self.require(pos, b',')

    def members(self, visit, visit_item):
        pos = 3 if self.data[:3] == b'\xef\xbb\xbf' else 0
        pos = self.require(self.next(pos), b'{')
        seen = set()
        if self.data[pos:pos + 1] != b'}':
            while True:
                _check(self.cancel)
                end = self._match(_STRING, pos)
                name = self.decode(pos, end)
                if name in seen:
                    raise ValueError(f"JSON 顶层字段重复：{name}")
                seen.add(name)
                pos = self.require(self.next(end), b':')
                if name in _ARRAYS:
                    visit(name, None)
                    items = self.array(pos)
                    while True:
                        try:
                            start, end = next(items)
                        except StopIteration as done:
                            pos = done.value
                            break
                        visit_item(name, self.decode(start, end), (start, end))
                else:
                    end = self.value_end(pos)
                    visit(name, self.decode(pos, end))
                    pos = end
                pos = self.next(pos)
                if self.data[pos:pos + 1] == b'}':
                    break
                pos = self.require(pos, b',')
        if self.next(pos + 1) != len(self.data):
            raise ValueError("JSON 对象后还有其他数据")


@contextmanager
def _open(path, cancel=None):
    with Path(path).open("rb") as handle:
        stat = os.fstat(handle.fileno())
        if not stat.st_size:
            raise ValueError("JSON 文件为空")
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            yield _Reader(data, cancel), (stat.st_size, stat.st_mtime_ns)


@dataclass(frozen=True)
class ReportPages:
    path: Path
    identity: tuple[int, int]
    arrays: dict[str, list[tuple[int, int]]]

    def read(self, name, first, count, *, cancel=None):
        with _open(self.path) as (reader, identity):
            if identity != self.identity:
                raise ValueError("报告已变化，请重新打开")
            for start, end in self.arrays.get(name, ())[first:first + count]:
                _check(cancel)
                yield reader.decode(start, end)


def project_report(path, *, cancel=None, collect_review=True, collect_pages=True, select_event=None,
                   map_event=None):
    payload = {}
    arrays = {}

    def visit(name, value):
        if name in _ARRAYS:
            arrays[name] = []
            payload[name] = []
        else:
            payload[name] = value

    def visit_item(name, value, span):
        if collect_pages:
            arrays[name].append(span)
        if name == "review_items" and collect_review:
            payload[name].append(value)
        if name == "events" and select_event is not None and select_event(value):
            payload[name].append(map_event(value) if map_event is not None else value)

    with _open(path, cancel) as (reader, identity):
        reader.members(visit, visit_item)
    if not isinstance(payload.get("settings"), dict) or not (
        isinstance(payload.get("stages"), list) or payload.get("journal_version") == 1
    ):
        raise WrongReportSchema("不是可读取的识别任务报告")
    return payload, ReportPages(Path(path), identity, arrays)


def search_report(pages, query, redact, sensitive_key, *, cancel=None):
    query = query.casefold()
    matches = []
    positions = {}

    def check(label, value):
        text = json.dumps(redact(value), ensure_ascii=False, separators=(",", ":"))
        if query not in text.casefold() and query not in label.casefold():
            return
        first = text.casefold().find(query)
        start = max(0, first - 55)
        matches.append(f"{label} · {text[start:start + 180]}")
        if len(matches) == 50:
            raise _SearchLimit()

    def visit(name, value):
        if name in _ARRAYS:
            positions[name] = 0
        else:
            check(name, "<已隐藏>" if sensitive_key(name) else value)

    def visit_item(name, item, _span):
        position = positions[name]
        positions[name] += 1
        check(f"{name}[{position}]", item)

    with _open(pages.path, cancel) as (reader, identity):
        if identity != pages.identity:
            raise ValueError("报告已变化，请重新打开")
        try:
            reader.members(visit, visit_item)
        except _SearchLimit:
            pass
    return matches


class _SearchLimit(Exception):
    pass


def save_redacted_report(source, destination, redact, sensitive_key, *, cancel=None, identity=None):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve() or (destination.exists() and source.samefile(destination)):
        raise ValueError("请选择不同于原报告的文件")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", errors="backslashreplace", dir=destination.parent,
                                         delete=False) as output:
            temporary = Path(output.name)
            output.write("{")
            first = True
            active_array = False
            first_item = True

            def visit(name, value):
                nonlocal first, active_array, first_item
                if active_array:
                    output.write("]")
                if not first:
                    output.write(",")
                first = False
                output.write(json.dumps(name, ensure_ascii=False))
                output.write(":")
                active_array = name in _ARRAYS
                first_item = True
                if active_array:
                    output.write("[")
                else:
                    output.write(json.dumps("<已隐藏>" if sensitive_key(name) else redact(value),
                                            ensure_ascii=False, separators=(",", ":")))

            def visit_item(name, value, _span):
                nonlocal first_item
                if not first_item:
                    output.write(",")
                first_item = False
                output.write(json.dumps(redact(value), ensure_ascii=False, separators=(",", ":")))

            with _open(source, cancel) as (reader, actual):
                if identity is not None and actual != identity:
                    raise ValueError("报告已变化，请重新打开")
                reader.members(visit, visit_item)
            output.write("]}" if active_array else "}")
        _check(cancel)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
