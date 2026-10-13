# UI translations

`en.json` and `ja.json` hold every English and Japanese UI string. Each file is
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
