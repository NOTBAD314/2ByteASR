"""Files for 「导入术语」: any encoding, CSV/TSV/Excel/JSON/text, columns by name (2026-11-16).

User (2026-11-16): people with a complete term list still found importing it hard and had another
AI harness do it. The import sheet only took pasted text: no file picker although its tooltip
offered one, Tab-only columns (a comma CSV line became one long "term"), a fixed column order,
no Excel, no GBK / UTF-16, and a JSON with several games was poured into the current library.

``load_import_file`` reads a file into the text the sheet's editor shows: tables become Tab
columns under a header line whose names say what each column is (术语 / 别名 / 分类 / 忽略), so
the user can see and change the reading in the editor before anything is saved; plain lines and
JSON pass through. ``header_roles`` reads such a header in any column order. ``json_game_groups``
lists the games in a multi-game JSON so one can be picked. Reading never writes user data. No Qt.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 20000
SPLIT_ALIASES = re.compile(r'[、,，;；|]+')

# Header words, compared after casefold and with spaces / brackets removed.
TERM_HEADERS = {'term', 'terms', 'canonical', 'name', 'names', 'word', 'to', 'target', 'correct',
                '规范词', '标准词', '术语', '词条', '名称', '正确写法', '正确', '正确词', '规范写法', '最终输出',
                '官方名', '官方名称', '中文名', '名字', '词', '词语', '专名', '规范名'}
ALIAS_HEADERS = {'alias', 'aliases', 'from', 'source', 'wrong', 'misspelling', 'misrecognition', 'variants',
                 '别名', '错词', '常见错词', '误识别', '错误写法', '错写', '同义词', '简称', '昵称', '俗称',
                 '别称', '其他写法', '原文', '识别结果'}
CATEGORY_HEADERS = {'category', 'type', 'kind', 'class', 'group', '分类', '类别', '类型', '种类', '类'}
IGNORE_HEADERS = {'忽略', 'ignore', '-', '—', '不用'}
ROLE_NAMES = {'term': '术语', 'aliases': '别名', 'category': '分类', 'ignore': '忽略'}
ENGLISH_ROLE_NAMES = {'term': 'term', 'aliases': 'alias', 'category': 'category', 'ignore': 'ignore'}


def _header_key(cell: str) -> str:
    return re.sub(r'[\s()（）\[\]【】:：/]+', '', str(cell or '')).casefold()


def header_role(cell: str) -> str:
    key = _header_key(cell)
    if key in TERM_HEADERS:
        return 'term'
    if key in ALIAS_HEADERS:
        return 'aliases'
    if key in CATEGORY_HEADERS:
        return 'category'
    if key in IGNORE_HEADERS:
        return 'ignore'
    return ''


def header_roles(columns: list[str]) -> list[str] | None:
    """Roles for a header row, or None when the row is not a header.

    A header names a term column; a column whose name is not known (编号, 备注…) is ignored. The
    old fixed header ``term / category / aliases`` uses known names, so it reads as before."""
    roles = [header_role(cell) for cell in columns]
    if 'term' not in roles:
        return None
    return [role or 'ignore' for role in roles]


def records_from_table(lines: list[tuple[int, list[str]]], roles: list[str]) -> list[dict]:
    """Rows under a header -> import records ({from, to, category, line, raw})."""
    records = []
    term_at = roles.index('term')
    for line_number, columns in lines:
        cells = [str(cell or '').strip() for cell in columns]
        target = cells[term_at] if term_at < len(cells) else ''
        category = next((cells[i] for i, role in enumerate(roles) if role == 'category' and i < len(cells) and cells[i]),
                        '') or '其他'
        raw = '\t'.join(cells)
        if not target:
            if any(cells):
                records.append({'from': '', 'to': '', 'category': category, 'line': line_number, 'raw': raw,
                                'parse_error': '这一行的术语列是空的'})
            continue
        records.append({'from': target, 'to': target, 'category': category, 'line': line_number, 'raw': raw})
        for index, role in enumerate(roles):
            if role == 'aliases' and index < len(cells):
                for alias in SPLIT_ALIASES.split(cells[index]):
                    alias = alias.strip()
                    if alias and alias != target:
                        records.append({'from': alias, 'to': target, 'category': category, 'line': line_number,
                                        'raw': raw})
    return records


# ------------------------------------------------------------------ reading files

def decode_bytes(data: bytes) -> tuple[str, str]:
    """Text and the encoding it was read with (BOM, UTF-8, then the best guess, then GB18030)."""
    for bom, name in ((b'\xef\xbb\xbf', 'utf-8-sig'), (b'\xff\xfe', 'utf-16'), (b'\xfe\xff', 'utf-16')):
        if data.startswith(bom):
            return data.decode(name), ('utf-8' if name == 'utf-8-sig' else name)
    if len(data) >= 4 and data[1:4:2] == b'\x00\x00' and data[0:3:2] != b'\x00\x00':
        try:
            return data.decode('utf-16-le'), 'utf-16-le'
        except UnicodeDecodeError:
            pass
    try:
        return data.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(data).best()
        if best is not None and best.encoding:
            return str(best), best.encoding
    except Exception:  # noqa: BLE001 - a guesser failure falls back to GB18030
        pass
    return data.decode('gb18030', errors='replace'), 'gb18030'


def read_xlsx(data: bytes) -> list[list[str]]:
    """The first worksheet of an .xlsx as rows of cell text (shared and inline strings, numbers)."""
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        names = set(book.namelist())
        shared = []
        if 'xl/sharedStrings.xml' in names:
            root = ElementTree.fromstring(book.read('xl/sharedStrings.xml'))
            for item in root.findall('m:si', ns):
                shared.append(''.join(node.text or '' for node in item.iter(f"{{{ns['m']}}}t")))
        sheet = 'xl/worksheets/sheet1.xml'
        try:
            workbook = ElementTree.fromstring(book.read('xl/workbook.xml'))
            first = workbook.find('m:sheets/m:sheet', ns)
            rels = ElementTree.fromstring(book.read('xl/_rels/workbook.xml.rels'))
            rid = first.get(f"{{{ns['r']}}}id") if first is not None else None
            for rel in rels:
                if rel.get('Id') == rid:
                    target = rel.get('Target', '').lstrip('/')
                    sheet = target if target.startswith('xl/') else 'xl/' + target
        except (KeyError, ElementTree.ParseError, AttributeError):
            pass
        if sheet not in names:
            sheet = next((name for name in sorted(names) if name.startswith('xl/worksheets/sheet')), '')
        if not sheet:
            raise ValueError('这个 Excel 文件里没有找到工作表')
        root = ElementTree.fromstring(book.read(sheet))
    rows = []
    for row in root.iter(f"{{{ns['m']}}}row"):
        cells: dict[int, str] = {}
        for cell in row.findall('m:c', ns):
            ref = cell.get('r', '')
            letters = ''.join(ch for ch in ref if ch.isalpha())
            column = 0
            for ch in letters.upper():
                column = column * 26 + (ord(ch) - 64)
            column = (column - 1) if letters else len(cells)
            kind = cell.get('t', '')
            if kind == 'inlineStr':
                text = ''.join(node.text or '' for node in cell.iter(f"{{{ns['m']}}}t"))
            else:
                value = cell.findtext('m:v', default='', namespaces=ns)
                if kind == 's' and value.isdigit() and int(value) < len(shared):
                    text = shared[int(value)]
                elif kind == 'b':
                    text = 'TRUE' if value == '1' else 'FALSE'
                else:
                    text = value[:-2] if value.endswith('.0') and value[:-2].lstrip('-').isdigit() else value
            cells[column] = text
        if cells:
            rows.append([cells.get(i, '') for i in range(max(cells) + 1)])
        if len(rows) >= MAX_ROWS:
            break
    return rows


def split_table(text: str) -> list[list[str]] | None:
    """Rows of a delimited table (Tab, comma or semicolon), or None for plain lines."""
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if not lines:
        return None
    sample = '\n'.join(lines[:50])
    if '\t' in sample:
        delimiter = '\t'
    else:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=',;，').delimiter
        except csv.Error:
            return None
    rows = list(csv.reader(io.StringIO('\n'.join(lines)), delimiter=delimiter))
    wide = [row for row in rows if len(row) >= 2]
    if delimiter != '\t' and len(wide) < max(1, len(rows) * 0.6):
        return None             # a few commas inside plain lines, not a table
    return rows[:MAX_ROWS]


def _looks_like_category(values: list[str]) -> bool:
    values = [v.strip() for v in values if v.strip()]
    if not values:
        return False
    from .glossary_skill import CATEGORY_LABELS
    known = set(CATEGORY_LABELS.values()) | set(CATEGORY_LABELS) | {'其他', '游戏术语'}
    # Known category words, or (in a longer table) a few short words repeated down the column.
    return sum(v in known for v in values) >= len(values) * 0.6 or (
        len(values) >= 8 and len(set(values)) <= len(values) // 4 and all(len(v) <= 6 for v in values))


def guess_roles(rows: list[list[str]]) -> list[str]:
    """Roles for a table without a header.

    Two columns read like the sheet's own quick mapping (别名 → 规范词, as a Tab line always did),
    unless the second is a column of categories. Wider tables: 1st column 术语; a column of a few
    repeated short words 分类; the 2nd or 3rd column otherwise 别名; the rest 忽略. The guess is
    written as a header line the user sees and can change."""
    width = max((len(row) for row in rows), default=0)
    roles = ['ignore'] * width
    if not width:
        return roles
    if width == 2 and not _looks_like_category([row[1] if len(row) > 1 else '' for row in rows[:200]]):
        return ['aliases', 'term']
    roles[0] = 'term'
    for index in range(1, width):
        column = [row[index] if index < len(row) else '' for row in rows[:200]]
        if 'category' not in roles and _looks_like_category(column):
            roles[index] = 'category'
        elif 'aliases' not in roles and index <= 2:
            roles[index] = 'aliases'
    return roles


def table_to_text(rows: list[list[str]], role_names: dict | None = None) -> tuple[str, bool]:
    """Rows -> editor text: Tab columns under a header line. Returns (text, header was added).

    ``role_names``: the words for an added header (``ENGLISH_ROLE_NAMES`` outside a Chinese UI)."""
    def clean(cell):
        return ' '.join(str(cell or '').replace('\t', ' ').split())
    rows = [[clean(cell) for cell in row] for row in rows if any(clean(cell) for cell in row)]
    if not rows:
        return '', False
    added = header_roles(rows[0]) is None
    if added:
        names = role_names or ROLE_NAMES
        rows = [[names[role] for role in guess_roles(rows)], *rows]
    return '\n'.join('\t'.join(row) for row in rows), added


def load_import_file(path: str | Path, *, role_names: dict | None = None) -> dict:
    """Read one file for the import sheet.

    Returns {text, kind ('table' | 'json' | 'lines'), encoding, header_added, rows}. ``text`` goes
    into the editor; nothing is written."""
    path = Path(path)
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f'文件太大（{size // 1024 // 1024} MB）；术语表一般不超过 20 MB')
    data = path.read_bytes()
    suffix = path.suffix.casefold()
    if suffix in {'.xlsx', '.xlsm'} or data[:2] == b'PK' and suffix not in {'.json', '.txt', '.csv', '.tsv'}:
        try:
            rows = read_xlsx(data)
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise ValueError('读不了这个 Excel 文件；可以在 Excel 里另存为 CSV（UTF-8）再导入') from exc
        text, added = table_to_text(rows, role_names)
        return dict(text=text, kind='table', encoding='xlsx', header_added=added, rows=max(0, len(rows)))
    if suffix == '.xls':
        raise ValueError('旧版 .xls 读不了；请在 Excel 里另存为 .xlsx 或 CSV（UTF-8）再导入')
    text, encoding = decode_bytes(data)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    stripped = text.strip()
    if stripped.startswith(('{', '[')):
        try:
            json.loads(stripped)
            return dict(text=stripped, kind='json', encoding=encoding, header_added=False, rows=0)
        except ValueError:
            pass
    rows = split_table(text)
    lines = dict(text=stripped, kind='lines', encoding=encoding, header_added=False, rows=len(stripped.splitlines()))
    if rows is None:
        return lines
    if '\t' in '\n'.join(stripped.splitlines()[:50]):
        # Tab text keeps its old reading: a header line names the columns, otherwise every line is a
        # quick mapping (别名 Tab 规范词) as when it is pasted.
        return dict(lines, kind='table' if header_roles(rows[0]) is not None else 'lines')
    converted, added = table_to_text(rows, role_names)
    return dict(text=converted, kind='table', encoding=encoding, header_added=added, rows=len(rows))


def json_game_groups(text: str) -> list[tuple[str, int]]:
    """(game, entries) for a JSON holding several games' mappings; [] for any other text."""
    raw = str(text or '').strip()
    if not raw.startswith('{'):
        return []
    try:
        payload = json.loads(raw)
    except ValueError:
        return []
    games = payload.get('games') if isinstance(payload, dict) else None
    if not isinstance(games, dict):
        return []
    groups = []
    for key, entry in games.items():
        if isinstance(entry, dict):
            name = str(entry.get('game') or key)
            groups.append((name, len(entry.get('mappings') or ())))
    return groups


__all__ = ['ENGLISH_ROLE_NAMES', 'ROLE_NAMES', 'decode_bytes', 'guess_roles', 'header_role', 'header_roles', 'json_game_groups',
           'load_import_file', 'read_xlsx', 'records_from_table', 'split_table', 'table_to_text']
