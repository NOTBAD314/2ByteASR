"""Confirmed export preferences and Windows-safe single-use output names."""
import re

LEGACY_PLACEHOLDER = '_成片@3得43这'


def clean_affix(value):
    value = str(value or '')
    return '' if value == LEGACY_PLACEHOLDER else value


def output_basename(base, prefix='', suffix=''):
    base = str(base or '').strip()
    while re.search(r'\.(mp4|mkv|mov|webm|flv)$', base, re.I):
        base = base.rsplit('.', 1)[0]
    name = f'{prefix}{base}{suffix}'
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .') or '字幕视频'
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        name = '_' + name
    return name
