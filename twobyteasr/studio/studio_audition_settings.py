"""Preferences for Studio's bounded subtitle audition."""
from ..i18n import tr

_FIELDS = (
    ("head_ms", "句首试听时长", 1000, 100),
    ("tail_ms", "句尾试听时长", 1000, 100),
    ("before_ms", "入点前额外试听", 0, 0),
    ("after_ms", "出点后额外试听", 0, 0),
)


def values(preferences):
    entry = preferences.get("subtitle_audition")
    entry = entry if isinstance(entry, dict) else {}
    result = {}
    for key, _label, default, minimum in _FIELDS:
        value = entry.get(key)
        result[key] = max(minimum, min(value, 10000)) if type(value) is int else default
    return result


def show(page):
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QSpinBox

    dialog = QDialog(page)
    dialog.setWindowTitle(tr("字幕试听设置"))
    form = QFormLayout(dialog)
    controls = {}
    current = values(page._studio_preferences())
    for key, label, _default, minimum in _FIELDS:
        spin = QSpinBox(dialog)
        spin.setRange(minimum, 10000)
        spin.setSingleStep(100)
        spin.setSuffix(" ms")
        spin.setValue(current[key])
        form.addRow(tr(label), spin)
        controls[key] = spin
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    from ..app.application_settings import _write_settings_json

    def update(payload):
        existing = payload.get("studio_preferences")
        preferences = dict(existing) if isinstance(existing, dict) else {}
        preferences["subtitle_audition"] = {key: spin.value() for key, spin in controls.items()}
        payload["studio_preferences"] = preferences

    _write_settings_json(update)
