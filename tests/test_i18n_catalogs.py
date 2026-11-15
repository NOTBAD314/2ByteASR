"""The translation catalogs pass `scripts/i18n_locales.py check` (2026-11-14).

Six English-only keys reached the daily because nothing ran the check; its
message also did not say which keys were missing.
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('i18n_locales', ROOT / 'scripts' / 'i18n_locales.py')
i18n_locales = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(i18n_locales)


def test_catalogs_pass_the_check():
    assert i18n_locales.problems() == []


def test_mismatch_names_the_missing_keys():
    found = i18n_locales.key_mismatch({'en': {'甲': 'A', '乙': 'B'}, 'ja': {'甲': 'エー'}})
    assert found == ["ja.json lacks 1 key(s) the other catalog has: '乙'"]


def test_add_keeps_each_catalogs_line_endings(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n_locales, 'LOCALE_DIR', tmp_path)
    monkeypatch.setattr(i18n_locales, 'OPTIONAL_LANGUAGES', ())
    (tmp_path / 'en.json').write_bytes(i18n_locales.canonical({'甲': 'A'}).replace('\n', '\r\n').encode())
    (tmp_path / 'ja.json').write_bytes(i18n_locales.canonical({'甲': 'エー'}).encode())
    batch = tmp_path / 'batch.json'
    batch.write_text(json.dumps({'乙': {'en': 'B', 'ja': 'ビー'}}, ensure_ascii=False), encoding='utf-8')
    i18n_locales.add(batch)
    assert b'\r\n' in (tmp_path / 'en.json').read_bytes()
    assert b'\r\n' not in (tmp_path / 'ja.json').read_bytes()
    assert i18n_locales.load('en') == {'甲': 'A', '乙': 'B'}
