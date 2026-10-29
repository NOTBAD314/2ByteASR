# UI translations

`en.json` and `ja.json` hold every English and Japanese UI string; `zh-Hant.json` holds
繁體中文 (generated, see below). Each file is
one flat JSON object:

```json
{
  "取消": "Cancel",
  "成功 {success} 个": "{success} succeeded"
}
```

- The key is the exact Chinese source text used in code (`tr("…")`,
  `bind_text(widget, "…")`, widget text), after the "●  " decoration and
  surrounding whitespace are stripped.
- Both files carry the same keys, and a translation keeps the same
  `{placeholders}` (same names and format specs) as its key.
- Order matters: when two sources share one translation, the later key wins
  the reverse lookup that recaptures widgets after a language switch. Append
  new keys; do not re-sort the files.

Edit through the tool so the files stay valid and canonical:

```
python scripts/i18n_locales.py missing          # strings in code without a translation
python scripts/i18n_locales.py add batch.json   # {"<zh>": {"en": "…", "ja": "…"}}
python scripts/i18n_locales.py check
```

Do not add new `i18n_round_*.py` modules; they were merged into these files on
2026-10-11.

## 繁體中文 (zh-Hant, since 2026-10-14)

The Chinese source strings are Simplified. `zh-Hant.json` (same keys) and
`zh-Hant-chars.json` (single-character fallback) are **generated** from them
with OpenCC (`s2twp`, Taiwan wording) by `scripts/make_zh_hant.py`, which also
writes `docs/api-setup/*.zh-Hant.md`. Do not edit them by hand; after adding UI
strings, run it in an environment that has `opencc` installed:

```
python -X utf8 scripts/make_zh_hant.py
```

Until it is rerun, new strings are shown with the character fallback (only
known UI strings are converted; user content never is). `check` reports how
many strings are waiting.

## 한국어 and the 2026-10-19 languages

`ko.json` (since 2026-10-14) and `es.json`, `de.json`, `fr.json`, `pt.json`,
`it.json`, `ru.json` (Español, Deutsch, Français, Português with Brazilian
wording, Italiano, Русский; since 2026-10-19) carry the same keys as
`en.json`, translated from the Chinese and English. They load the first time
the language is used. They may lag behind: a string without a translation
shows the English at runtime, and `check` only notes how many are waiting.
`add` accepts `ko`, `es`, `de`, `fr`, `pt`, `it`, `ru` next to `en` and `ja`.
The language menus take their names from `i18n.LANGUAGE_NATIVE_NAMES`.

## Subtitle conversion table (not UI text, since 2026-10-19)

`zh-Hant-subtitles.json` is not a UI catalog. It converts recognized Chinese
subtitles to 繁體 when the home language menu is set to 繁体中文
(`twobyteasr/subtitle_rules/chinese_script.py`, ADR 0132): OpenCC `s2tw`
characters and phrases, character forms only, never wording. It is generated
by `scripts/make_zh_hant_subtitles.py` (needs `opencc`); do not edit it by hand.

`zh-Hans-subtitles.json` (afternoon of 2026-10-19) is the reverse table, from
OpenCC `tw2s`, for the workbench command 简繁 that converts a whole project
back to 简体. The same script generates it and checks that every entry keeps
its length.
