"""Built-in and user-owned Subtitle Studio style presets."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .studio_project import SubtitleProject, SubtitleStyle, default_style, studio_data_root


BUILTIN_PRESETS = {
    "default": default_style(),
    "clean-white": SubtitleStyle("clean-white", "简洁白字", font_size=48, outline_width=2, shadow=0),
    "game": SubtitleStyle("game", "游戏字幕", font_size=54, outline_width=4, shadow=1, bold=True),
    "livestream": SubtitleStyle(
        "livestream", "直播切片", font_size=56, primary_color="#FFF4B8", outline_width=4, bold=True
    ),
    "dialogue-a": SubtitleStyle("dialogue-a", "双人对话 白", font_size=50),
    "dialogue-b": SubtitleStyle("dialogue-b", "双人对话 蓝", font_size=50, primary_color="#B9DDFF"),
}


def _validated_stored_recipe(recipe, style_id):
    recipe = dict(recipe)
    if 'webTheme' in recipe:
        from .theme_metadata import validate_theme_before_save
        from .style_recipe import StyleRecipe
        recipe['webTheme'] = validate_theme_before_save(
            recipe['webTheme'], path=f'presets[{style_id}].recipe.webTheme')
        recipe = StyleRecipe.from_dict(recipe).to_dict()
    return recipe


class StylePresetStore:
    def __init__(self, base: str | os.PathLike[str] | None = None) -> None:
        self.path = studio_data_root(base) / "style-presets.json"

    def load_user(self) -> dict[str, SubtitleStyle]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            names = {field.name for field in fields(SubtitleStyle)}
            styles = {
                str(item["id"]): SubtitleStyle(**{key: value for key, value in item.items() if key in names})
                for item in payload.get("presets", [])
                if isinstance(item, dict) and str(item.get("id") or "") not in BUILTIN_PRESETS
            }
            for style in styles.values():
                style.validate()
            return styles
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    def load_patch(self, style_id: str) -> dict:
        if style_id in BUILTIN_PRESETS:
            return asdict(BUILTIN_PRESETS[style_id])
        return next((dict(item) for item in self._load_payload().get('presets', [])
                     if isinstance(item, dict) and item.get('id') == style_id), {})

    def _load_payload(self) -> dict:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def hidden_builtin_ids(self) -> frozenset[str]:
        payload = self._load_payload()
        return frozenset(
            str(item) for item in payload.get("hidden_builtin_preset_ids", [])
            if str(item) in BUILTIN_PRESETS
        )

    def favorite_builtin_ids(self) -> frozenset[str]:
        payload = self._load_payload()
        return frozenset(
            str(item) for item in payload.get("favorite_builtin_preset_ids", [])
            if str(item) in BUILTIN_PRESETS
        )

    def all(self) -> dict[str, SubtitleStyle]:
        hidden = self.hidden_builtin_ids()
        return {
            **{style_id: style for style_id, style in BUILTIN_PRESETS.items() if style_id not in hidden},
            **self.load_user(),
        }

    def load_recipes(self) -> dict[str, dict]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return {
                str(item["id"]): dict(item["recipe"])
                for item in payload.get("presets", [])
                if isinstance(item, dict) and isinstance(item.get("recipe"), dict)
            }
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    def load_metadata(self) -> dict[str, dict]:
        builtin_favorites = self.favorite_builtin_ids()
        builtin_metadata = {
            style_id: {
                "favorite": style_id in builtin_favorites,
                "source": "builtin",
                "created_at": "",
            }
            for style_id in BUILTIN_PRESETS
        }
        if not self.path.is_file():
            return builtin_metadata
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return {
                **builtin_metadata,
                **{
                str(item["id"]): {
                    "favorite": bool(item.get("favorite", False)),
                    "source": str(item.get("source") or ("ai" if str(item.get("id", "")).startswith("ai-") else "custom")),
                    "created_at": str(item.get("created_at") or ""),
                }
                for item in payload.get("presets", [])
                if isinstance(item, dict) and str(item.get("id") or "")
                },
            }
        except (OSError, ValueError, TypeError, KeyError):
            return builtin_metadata

    def save_user(
        self,
        styles: Iterable[SubtitleStyle],
        recipes: dict[str, dict] | None = None,
        metadata: dict[str, dict] | None = None,
    ) -> None:
        recipes = self.load_recipes() if recipes is None else dict(recipes)
        metadata = self.load_metadata() if metadata is None else dict(metadata)
        clean = []
        for style in styles:
            style.validate()
            if style.id in BUILTIN_PRESETS:
                raise ValueError("built-in style presets are read-only")
            item = self._stored_style_fields(style)
            if style.id in recipes:
                item["recipe"] = _validated_stored_recipe(recipes[style.id], style.id)
            item.update(metadata.get(style.id, {}))
            clean.append(item)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".style-presets.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump({
                    "schema_version": 3,
                    "hidden_builtin_preset_ids": sorted(self.hidden_builtin_ids()),
                    "favorite_builtin_preset_ids": sorted(self.favorite_builtin_ids()),
                    "presets": clean,
                }, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                pass

    def upsert(self, style: SubtitleStyle, recipe: dict | None = None, *, source: str = "") -> None:
        if style.id in BUILTIN_PRESETS:
            raise ValueError("built-in style presets are read-only")
        styles = self.load_user()
        styles[style.id] = style
        recipes = self.load_recipes()
        if recipe is not None:
            recipes[style.id] = dict(recipe)
        metadata = self.load_metadata()
        current = metadata.get(style.id, {})
        metadata[style.id] = {
            "favorite": bool(current.get("favorite", False)),
            "source": str(source or current.get("source") or "custom"),
            "created_at": str(current.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
        }
        self.save_user(styles.values(), recipes, metadata)

    def _stored_style_fields(self, style: SubtitleStyle) -> dict:
        """Metadata edits must not turn an existing sparse preset into defaults."""
        old = self.load_patch(style.id)
        current = asdict(style)
        if not old:
            return current
        fields = set(current)
        previous = asdict(SubtitleStyle(**{k:v for k,v in old.items() if k in fields}))
        authored = (set(old) & fields) | {k for k,v in current.items() if v != previous[k]}
        return {k:v for k,v in current.items() if k in authored}

    def set_favorite(self, style_id: str, favorite: bool) -> None:
        style_id = str(style_id)
        if style_id in BUILTIN_PRESETS:
            favorites = set(self.favorite_builtin_ids())
            if favorite:
                favorites.add(style_id)
            else:
                favorites.discard(style_id)
            self._save_with_hidden(self.hidden_builtin_ids(), favorite_builtins=favorites)
            return
        styles = self.load_user()
        if style_id not in styles:
            raise ValueError("missing style preset")
        metadata = self.load_metadata()
        current = metadata.get(style_id, {})
        metadata[style_id] = {
            "favorite": bool(favorite),
            "source": str(current.get("source") or ("ai" if style_id.startswith("ai-") else "custom")),
            "created_at": str(current.get("created_at") or ""),
        }
        self.save_user(styles.values(), self.load_recipes(), metadata)

    def delete(self, style_id: str) -> None:
        if style_id in BUILTIN_PRESETS:
            self.hide_builtin(style_id)
            return
        styles = self.load_user()
        styles.pop(str(style_id), None)
        recipes = self.load_recipes()
        recipes.pop(str(style_id), None)
        metadata = self.load_metadata()
        metadata.pop(str(style_id), None)
        self.save_user(styles.values(), recipes, metadata)

    def hide_builtin(self, style_id: str) -> None:
        style_id = str(style_id)
        if style_id not in BUILTIN_PRESETS:
            raise ValueError("not a built-in style preset")
        hidden = set(self.hidden_builtin_ids())
        hidden.add(style_id)
        self._save_with_hidden(hidden)

    def restore_builtins(self, style_ids: Iterable[str] | None = None) -> int:
        hidden = set(self.hidden_builtin_ids())
        wanted = hidden if style_ids is None else hidden.intersection(str(item) for item in style_ids)
        if not wanted:
            return 0
        restored = len(wanted)
        hidden.difference_update(wanted)
        self._save_with_hidden(hidden)
        return restored

    def _save_with_hidden(
        self,
        hidden: Iterable[str],
        *,
        favorite_builtins: Iterable[str] | None = None,
    ) -> None:
        hidden_ids = sorted({str(item) for item in hidden if str(item) in BUILTIN_PRESETS})
        favorite_ids = sorted({
            str(item)
            for item in (
                self.favorite_builtin_ids()
                if favorite_builtins is None
                else favorite_builtins
            )
            if str(item) in BUILTIN_PRESETS
        })
        styles = self.load_user()
        recipes = self.load_recipes()
        metadata = self.load_metadata()
        rows = []
        for style in styles.values():
            item = self._stored_style_fields(style)
            if style.id in recipes:
                item["recipe"] = _validated_stored_recipe(recipes[style.id], style.id)
            item.update(metadata.get(style.id, {}))
            rows.append(item)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".style-presets.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump({
                    "schema_version": 3,
                    "hidden_builtin_preset_ids": hidden_ids,
                    "favorite_builtin_preset_ids": favorite_ids,
                    "presets": rows,
                }, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                pass

    def delete_many(self, style_ids: Iterable[str]) -> int:
        requested = {str(item) for item in style_ids if str(item)}
        builtin_wanted = requested.intersection(BUILTIN_PRESETS)
        for style_id in builtin_wanted:
            self.hide_builtin(style_id)
        wanted = requested.difference(BUILTIN_PRESETS)
        if not wanted:
            return len(builtin_wanted)
        styles = self.load_user()
        removed = sum(1 for item in wanted if item in styles)
        for style_id in wanted:
            styles.pop(style_id, None)
        recipes = self.load_recipes()
        metadata = self.load_metadata()
        for style_id in wanted:
            recipes.pop(style_id, None)
            metadata.pop(style_id, None)
        self.save_user(styles.values(), recipes, metadata)
        return removed + len(builtin_wanted)

    def delete_all_ai(self, *, keep_favorites: bool = True) -> int:
        metadata = self.load_metadata()
        wanted = [
            style_id
            for style_id, item in metadata.items()
            if str(item.get("source") or "") == "ai"
            and not (keep_favorites and bool(item.get("favorite", False)))
        ]
        return self.delete_many(wanted)

    def rename(self, style_id: str, name: str) -> None:
        styles = self.load_user()
        style = styles.get(str(style_id))
        if style is None:
            raise ValueError("built-in or missing style presets cannot be renamed")
        clean = str(name or "").strip()
        if not clean:
            raise ValueError("preset name must not be empty")
        recipes=self.load_recipes()
        recipe=recipes.get(str(style_id),{})
        if recipe.get('webTheme'):
            from .theme_metadata import validate_name, validate_theme_before_save
            clean=validate_name(name)
            theme=validate_theme_before_save(recipe['webTheme'])
            theme['name']=clean
            recipe=dict(recipe,name=clean,webTheme=theme)
            recipes[str(style_id)]=recipe
        style.name = clean[:120]
        self.save_user(styles.values(), recipes, self.load_metadata())

    def export_file(
        self,
        path: str | os.PathLike[str],
        style_ids: Iterable[str] | None = None,
    ) -> int:
        user_styles = self.load_user()
        styles = self.all() if style_ids is not None else user_styles
        wanted = set(str(item) for item in style_ids) if style_ids is not None else set(user_styles)
        recipes = self.load_recipes()
        metadata = self.load_metadata()
        rows = []
        for style_id, style in styles.items():
            if style_id not in wanted:
                continue
            item = asdict(style)
            if style_id in recipes:
                item["recipe"] = recipes[style_id]
            item.update(metadata.get(style_id, {}))
            rows.append(item)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {"schema_version": 2, "kind": "2byteasr-style-presets", "presets": rows},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        return len(rows)

    def import_file(self, path: str | os.PathLike[str]) -> int:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = payload.get("presets") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("not a 2ByteASR style preset file")
        names = {field.name for field in fields(SubtitleStyle)}
        styles = self.load_user()
        recipes = self.load_recipes()
        metadata = self.load_metadata()
        imported = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            source_id = str(row.get("id") or "").strip()
            if not source_id:
                continue
            style_id = source_id
            if style_id in BUILTIN_PRESETS or style_id in styles:
                style_id = f"{source_id}-imported-{uuid.uuid4().hex[:6]}"
            values = {key: value for key, value in row.items() if key in names}
            values["id"] = style_id
            style = SubtitleStyle(**values)
            style.validate()
            styles[style_id] = style
            if isinstance(row.get("recipe"), dict):
                recipes[style_id] = dict(row["recipe"])
            metadata[style_id] = {
                "favorite": bool(row.get("favorite", False)),
                "source": str(row.get("source") or "custom"),
                "created_at": str(row.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
            }
            imported += 1
        self.save_user(styles.values(), recipes, metadata)
        return imported


def install_style(project: SubtitleProject, style: SubtitleStyle) -> None:
    style.validate()
    project.styles = [item for item in project.styles if item.id != style.id]
    project.styles.append(style)
    project.validate()
