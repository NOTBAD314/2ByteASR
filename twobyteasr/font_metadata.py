"""Read OpenType identity without Qt, locale guesses or an optional dependency."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import struct


@dataclass(frozen=True)
class FontMetadata:
    file: str
    index: int
    family: str
    style: str
    full_name: str
    postscript: str
    weight: int
    aliases: tuple[str, ...]
    units_per_em: int = 1000
    win_ascent: int = 1000
    win_descent: int = 0
    display_family: str = ''
    display_style: str = ''


def _chinese_name(records, kinds):
    # Windows Chinese locales first; do not mistake Japanese Kanji for a
    # Chinese localization. Unicode records may have no locale identifier.
    languages = {0x804: 0, 0x1004: 1, 0x404: 2, 0xC04: 3, 0x1404: 4}
    choices = [(languages.get(language, 5), kinds.index(kind), text)
               for kind, language, text in records if kind in kinds
               and (language in languages or language == 0)
               and any('\u3400' <= char <= '\u9fff' for char in text)
               and not any('\u3040' <= char <= '\u30ff' for char in text)]
    return min(choices)[2] if choices else ''


@lru_cache(maxsize=1024)
def read_faces(filename: str) -> tuple[FontMetadata, ...]:
    # Read only the table directory and the few tables used below. Startup
    # scans every installed font (hundreds of MB of CJK glyph data); reading
    # whole files evicted the OS cache and cost seconds on a cold disk.
    with open(filename, 'rb') as stream:
        def read(offset, length):
            stream.seek(offset)
            return stream.read(length)
        u16 = lambda buffer, at: struct.unpack_from('>H', buffer, at)[0]
        u32 = lambda buffer, at: struct.unpack_from('>I', buffer, at)[0]
        header = read(0, 12)
        if header[:4] == b'ttcf':
            count = u32(header, 8)
            listing = read(12, count * 4)
            offsets = [u32(listing, i * 4) for i in range(count)]
        else:
            offsets = [0]
        faces = []
        for index, offset in enumerate(offsets):
            table_count = u16(read(offset + 4, 2), 0)
            directory = read(offset + 12, table_count * 16)
            tables = {}
            for i in range(table_count):
                at = i * 16
                tables[directory[at:at + 4]] = (u32(directory, at + 8), u32(directory, at + 12))
            names = {}; aliases = set(); localized = []
            name_offset, name_length = tables[b'name']
            data = read(name_offset, name_length)
            strings = u16(data, 4)
            for i in range(u16(data, 2)):
                platform, encoding, language, kind, length, pos = struct.unpack_from('>6H', data, 6 + i * 12)
                if kind not in (1, 2, 4, 6, 16, 17):
                    continue
                try:
                    text = data[strings + pos:strings + pos + length].decode('utf-16-be' if platform in (0, 3) else 'mac_roman')
                except UnicodeError:
                    continue
                if platform in (0, 3): localized.append((kind, language, text))
                if kind in (1, 4, 6, 16): aliases.add(text)
                if kind not in names or language == 0x409: names[kind] = text
            os2 = read(tables[b'OS/2'][0], 78) if b'OS/2' in tables else None
            hhea = read(tables[b'hhea'][0], 8) if os2 is None else None
            faces.append(FontMetadata(str(Path(filename).resolve()), index,
                names.get(16, names.get(1, '')), names.get(17, names.get(2, '')),
                names.get(4, names.get(1, '')), names.get(6, ''),
                u16(os2, 4) if os2 is not None else 400, tuple(sorted(aliases)),
                u16(read(tables[b'head'][0] + 18, 2), 0),
                u16(os2, 74) if os2 is not None else u16(hhea, 4),
                u16(os2, 76) if os2 is not None else -struct.unpack_from('>h', hhea, 6)[0],
                _chinese_name(localized, (16, 1)) or names.get(16, names.get(1, '')),
                _chinese_name(localized, (17, 2)) or names.get(17, names.get(2, ''))))
    return tuple(faces)


@lru_cache(maxsize=512)
def has_character(filename: str, index: int, character: str) -> bool:
    """Whether a face maps ``character`` in its Unicode cmap (formats 4 and 12).

    Reads only the table directory and ``cmap``; any unreadable font counts as
    not having it (2026-10-14: Korean translation lines need Hangul).
    """
    code = ord(character)
    try:
        with open(filename, 'rb') as stream:
            def read(offset, length):
                stream.seek(offset)
                return stream.read(length)
            u16 = lambda buffer, at: struct.unpack_from('>H', buffer, at)[0]
            u32 = lambda buffer, at: struct.unpack_from('>I', buffer, at)[0]
            offset = u32(read(12 + 4 * index, 4), 0) if read(0, 4) == b'ttcf' else 0
            table_count = u16(read(offset + 4, 2), 0)
            directory = read(offset + 12, table_count * 16)
            location = next(((u32(directory, i * 16 + 8), u32(directory, i * 16 + 12))
                             for i in range(table_count) if directory[i * 16:i * 16 + 4] == b'cmap'), None)
            if location is None:
                return False
            data = read(*location)
            subtables = {struct.unpack_from('>HH', data, 4 + i * 8): u32(data, 8 + i * 8)
                         for i in range(u16(data, 2))}
            for key in ((3, 10), (0, 4), (0, 6), (3, 1), (0, 3), (0, 2), (0, 1), (0, 0)):
                if key not in subtables:
                    continue
                at = subtables[key]
                kind = u16(data, at)
                if kind == 12:
                    return any(start <= code <= end for start, end, _glyph in
                               (struct.unpack_from('>III', data, at + 16 + g * 12) for g in range(u32(data, at + 12))))
                if kind == 4:
                    if code > 0xFFFF:
                        return False
                    segments = u16(data, at + 6) // 2
                    ends, starts = at + 14, at + 16 + segments * 2
                    deltas, ranges = starts + segments * 2, starts + segments * 4
                    for s in range(segments):
                        if code > u16(data, ends + 2 * s):
                            continue
                        start = u16(data, starts + 2 * s)
                        if code < start:
                            return False
                        range_offset = u16(data, ranges + 2 * s)
                        if range_offset == 0:
                            return (code + struct.unpack_from('>h', data, deltas + 2 * s)[0]) & 0xFFFF != 0
                        return u16(data, ranges + 2 * s + range_offset + 2 * (code - start)) != 0
                    return False
            return False
    except (OSError, struct.error, IndexError):
        return False


def local_font_paths():
    """Read app, system and per-user font locations; never install fonts."""
    import os
    root = Path(__file__).resolve().parents[1]
    directories = [root/'assets/fonts', root/'tools/fonts']
    paths = []
    if os.name == 'nt':
        import winreg
        system = Path(os.environ.get('WINDIR', r'C:\Windows'))/'Fonts'
        user = Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'AppData/Local')))/'Microsoft/Windows/Fonts'
        directories += [system, user]
        key_path = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts'
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        value = Path(os.path.expandvars(str(winreg.EnumValue(key, i)[1])))
                        if value.is_absolute():
                            paths.append(value)
                        else:
                            # Per-user registrations can contain just a filename.
                            paths += [directory/value for directory in
                                      ((user, system) if hive == winreg.HKEY_CURRENT_USER else (system, user))]
            except OSError:
                pass
    files = [path for directory in directories for path in sorted(directory.glob('*'))
             if path.suffix.lower() in ('.otf', '.ttf', '.ttc', '.otc')]
    return tuple(dict.fromkeys(files + paths))


@lru_cache(maxsize=1)
def local_faces() -> tuple[FontMetadata, ...]:
    """Bundled bytes first; installed files supply their localized aliases too."""
    found = []
    for path in local_font_paths():
        try: found.extend(read_faces(str(path)))
        except (OSError, KeyError, struct.error, ValueError): pass
    return tuple(found)


@lru_cache(maxsize=512)
def resolve_local_face(family: str, weight: int = 0, style: str = '', bold: bool = False,
                       filename: str = '', index: int = 0) -> tuple[FontMetadata, str]:
    faces = local_faces()
    if filename:
        try:
            explicit = read_faces(filename)[index]
            return explicit, ''
        except (OSError, IndexError, KeyError, struct.error):
            pass
    candidates = [face for face in faces if family.casefold() in {name.casefold() for name in face.aliases}]
    reason = ''
    if candidates:
        # A legacy full face name already unambiguously identifies Heavy.
        # bold=False means no synthetic bold, not a request for Medium/400.
        requested = weight or (candidates[0].weight if len({f.weight for f in candidates}) == 1 else (700 if bold else 400))
        exact = [face for face in candidates if not style or face.style.casefold() == style.casefold()]
        chosen = min(exact or candidates, key=lambda face: abs(face.weight - requested))
        if (style and not exact) or (weight and chosen.weight != weight):
            reason = f'缺失字体字面：{family} / {style or requested}；临时使用 {chosen.full_name} ({chosen.weight})'
        return chosen, reason
    chosen = next(face for face in faces if face.family == 'Source Han Sans SC' and face.weight == 500)
    return chosen, f'缺失字体：{family}；临时使用 {chosen.full_name}，原始选择保留'


@lru_cache(maxsize=1)
def _faces_by_alias() -> dict[str, tuple[FontMetadata, ...]]:
    """Casefolded alias -> faces, in local_faces() order (built once)."""
    index: dict[str, list[FontMetadata]] = {}
    for face in local_faces():
        for alias in dict.fromkeys(name.casefold() for name in face.aliases):
            index.setdefault(alias, []).append(face)
    return {alias: tuple(faces) for alias, faces in index.items()}


def restore_legacy_heavy_identity(style):
    """Only fill absent identity when a real full face alias proves Heavy/900.

    An explicit weight/style/file or a generic family is never migrated. This
    does not infer a face from the word Heavy, and never persists a fallback.
    """
    if style.font_weight or style.font_style_name or style.font_file:
        return
    family = style.font_family.casefold()
    matches = [f for f in _faces_by_alias().get(family, ()) if family != f.family.casefold()]
    if matches and {(f.style, f.weight) for f in matches} == {('Heavy', 900)}:
        style.font_style_name = 'Heavy'
        style.font_weight = 900
