from pathlib import Path

from PySide6.QtCore import QSettings

from twobyteasr.app.ui import (
    LAST_MEDIA_DIRECTORY_KEY,
    _media_dialog_initial_directory,
    _remember_media_directory,
)


def test_media_dialog_remembers_last_selected_folder(tmp_path):
    settings = QSettings(
        str(tmp_path / "ui-state.ini"),
        QSettings.Format.IniFormat,
    )
    settings.clear()
    default_directory = Path(_media_dialog_initial_directory(settings))
    assert default_directory.is_dir()

    media_directory = tmp_path / "素材"
    media_directory.mkdir()
    media_path = media_directory / "sample.mp4"
    media_path.touch()
    _remember_media_directory([str(media_path)], settings)

    assert settings.value(LAST_MEDIA_DIRECTORY_KEY) == str(media_directory.resolve())
    assert Path(_media_dialog_initial_directory(settings)) == media_directory.resolve()


def test_missing_remembered_folder_falls_back_to_desktop_or_home(tmp_path):
    settings = QSettings(
        str(tmp_path / "ui-state.ini"),
        QSettings.Format.IniFormat,
    )
    settings.setValue(LAST_MEDIA_DIRECTORY_KEY, str(tmp_path / "missing"))
    assert Path(_media_dialog_initial_directory(settings)).is_dir()

