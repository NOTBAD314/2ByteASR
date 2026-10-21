"""Local, conservative glossary input parsing; never writes glossary data."""
from __future__ import annotations

import re
import shlex


def parse_term_line(value: str, *, mapping_mode=False) -> dict:
    raw = str(value).strip(' \r\n')
    row = {'from': raw, 'to': raw, 'category': '其他', 'raw': raw}
    # Only delimiters outside quotes carry syntax. Names and case are intact.
    quote = None
    outside = []
    for index, character in enumerate(raw):
        if character in ('"', "'", '“', '”'):
            closing = '”' if character == '“' else character
            if quote is None and (index == 0 or raw[index-1].isspace() or raw[index-1] == '→'):
                quote = closing
            elif character == quote:
                quote = None
            outside.append(' ')
        else:
            outside.append(character if quote is None else ' ')
    if quote is not None:
        row.update(parse_error='引号未闭合，请编辑该行')
        return row
    syntax = ''.join(outside)
    matches = list(re.finditer(r'→|->|=>|\t|(?<=\s)-(?=\s)', syntax))
    if len(matches) > 1:
        row.update(parse_error='分隔符混用或超过两列，请明确别名与规范词')
        return row

    def unquote(text):
        text = text.strip()
        if len(text) >= 2 and ((text[0], text[-1]) in [('"', '"'), ("'", "'"), ('“', '”')]):
            return text[1:-1].strip()
        return text

    if matches:
        match = matches[0]
        source, target = unquote(raw[:match.start()]), unquote(raw[match.end():])
        row.update({'from': source, 'to': target})
        if not source or not target:
            row['parse_error'] = '别名或规范词为空，请补全该行'
        return row
    if not mapping_mode:
        row.update({'from': unquote(raw), 'to': unquote(raw)})
        return row
    try:
        columns = shlex.split(raw.replace('“', '"').replace('”', '"'), posix=True)
    except ValueError:
        row['parse_error'] = '引号未闭合，请编辑该行'
        return row
    if len(columns) == 2:
        row.update({'from': columns[0], 'to': columns[1]})
    elif len(columns) > 2:
        row['parse_error'] = '空格有多个解释；多词名称请用引号、箭头或Tab分隔'
    elif '-' in raw:
        row['parse_error'] = '名称内连字符不自动拆分；映射请使用两侧空格的短横线或箭头'
    else:
        row['parse_error'] = '快捷映射需要两列；只添加规范词请切换为普通术语'
    return row


def validate_term_records(records, existing=()):
    """Preview all batch conflicts before any row reaches the existing store."""
    confirmed = {str(row.get('from', '')).casefold(): str(row.get('to', '')) for row in existing}
    canonical = {str(row.get('to', '')).casefold(): str(row.get('to', '')) for row in existing}
    choices = {}
    for row in records:
        if not row.get('parse_error') and row.get('from') and row.get('to'):
            choices.setdefault(row['from'].casefold(), set()).add(row['to'].casefold())
    result = []
    for original in records:
        record = dict(original)
        source, target = str(record.get('from', '')).strip(), str(record.get('to', '')).strip()
        record.update({'from': source, 'to': target})
        previous = confirmed.get(source.casefold())
        if record.get('parse_error'):
            record.update(status='invalid', reason=record['parse_error'])
        elif not source or not target:
            record.update(status='invalid', reason='规范词或别名为空')
        elif len(choices.get(source.casefold(), ())) > 1:
            record.update(status='conflict', reason=f'本批冲突：{source} 对应多个规范词，请编辑后确认')
        elif previous:
            record.update(status='duplicate' if previous.casefold() == target.casefold() else 'conflict',
                reason=f'重复跳过；已确认写法 {previous} 保持' if previous.casefold() == target.casefold()
                       else f'冲突：{source} 已指向 {previous}，需要覆盖请直接编辑')
            if previous.casefold() == target.casefold():
                record['to'] = previous
        else:
            merge = target.casefold() in canonical
            record['to'] = canonical.get(target.casefold(), target)
            record.update(status='ready', reason='合并别名到现有规范词' if merge and source != record['to']
                else '将新增纠错映射' if source != record['to'] else '将新增规范词（大小写原样保留）')
            confirmed[source.casefold()] = record['to']
            canonical.setdefault(target.casefold(), record['to'])
        result.append(record)
    return result
