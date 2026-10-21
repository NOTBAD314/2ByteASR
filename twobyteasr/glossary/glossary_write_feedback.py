"""Keep manual glossary editors open when the underlying store rejects IO."""
from functools import wraps


def glossary_write_errors(function=None, *, owner=None):
    def decorate(callback):
        @wraps(callback)
        def guarded(*args, **kwargs):
            widget = owner if owner is not None else args[0]
            try:
                return callback(*args, **kwargs)
            except (OSError, ValueError) as exc:
                message = ("词库保存失败，输入已保留。批量操作已保存的条目不会重复添加，请重试。"
                           + " ".join(str(exc).split())[:160])
                hint = getattr(getattr(widget, "owner", widget), "term_hint", None)
                if hint is not None:
                    hint.setText(message)
                    hint.show()
                toast = getattr(widget, "_show_toast", None) or getattr(widget, "_show_inline_toast", None)
                if callable(toast): toast(message, 5000)
                for name in ("_mappings_cache", "_builtin_entry_cache"):
                    cache = getattr(widget, name, None)
                    if cache is not None: cache.clear()
                return None
        return guarded
    return decorate(function) if function is not None else decorate
