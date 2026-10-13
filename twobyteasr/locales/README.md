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
