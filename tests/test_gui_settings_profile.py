"""GUI settings use an explicitly selected data root, without registry writes."""
import os
from pathlib import Path
import subprocess
import sys


def _child(code, env):
    return subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=30)


def test_explicit_data_root_routes_real_qsettings_to_ini(tmp_path):
    env = os.environ.copy()
    env.pop('TWOBYTEASR_TEST_ROOT', None)
    env['2BYTEASR_USER_DATA_ROOT'] = str(tmp_path)
    code = r'''
from pathlib import Path
from twobyteasr.app.settings_profile import configure_gui_settings_profile
assert configure_gui_settings_profile()
from PySide6.QtCore import QSettings, QCoreApplication
QCoreApplication.setOrganizationName('2ByteASR')
QCoreApplication.setApplicationName('2ByteASR')
root = (Path(__import__('os').environ['2BYTEASR_USER_DATA_ROOT']) / '2ByteASR' / 'qsettings').resolve()
a = QSettings('2ByteASR', '2ByteASR')
b = QSettings()
assert a.format() == QSettings.IniFormat and b.format() == QSettings.IniFormat
assert Path(a.fileName()).resolve().is_relative_to(root)
assert Path(b.fileName()).resolve().is_relative_to(root)
assert Path(a.fileName()).resolve() == Path(b.fileName()).resolve()
a.setValue('appearance/theme', 'fixture'); a.sync()
assert b.value('appearance/theme') == 'fixture'
assert a.status() == QSettings.NoError
explicit = Path(__import__('os').environ['2BYTEASR_USER_DATA_ROOT']) / 'explicit.ini'
c = QSettings(str(explicit), QSettings.IniFormat)
c.setValue('fixture', 'ok'); c.sync()
assert Path(c.fileName()).resolve() == explicit.resolve()
assert c.value('fixture') == 'ok'
d = QSettings(QSettings.IniFormat, QSettings.UserScope, '2ByteASR', 'Other')
assert Path(d.fileName()).resolve().is_relative_to(root)
assert d.format() == QSettings.IniFormat
'''
    result = _child(code, env)
    assert result.returncode == 0, result.stderr
    assert list((tmp_path / '2ByteASR' / 'qsettings').glob('*.ini'))


def test_default_and_test_root_do_not_install_gui_qsettings_profile(tmp_path):
    code = r'''
import sys
from twobyteasr.app.settings_profile import configure_gui_settings_profile
assert configure_gui_settings_profile() is False
assert 'PySide6.QtCore' not in sys.modules
'''
    env = os.environ.copy()
    env.pop('TWOBYTEASR_TEST_ROOT', None)
    env.pop('2BYTEASR_USER_DATA_ROOT', None)
    result = _child(code, env)
    assert result.returncode == 0, result.stderr
    # Test isolation has its own Qt boundary; the GUI override must not replace it.
    env['TWOBYTEASR_TEST_ROOT'] = str(tmp_path / 'tmp' / 'profile')
    env['2BYTEASR_USER_DATA_ROOT'] = str(tmp_path / 'other')
    result = _child("from twobyteasr.app.settings_profile import configure_gui_settings_profile; assert configure_gui_settings_profile() is False", env)
    assert result.returncode == 0, result.stderr


def test_mcp_stdio_does_not_import_qt_with_data_root(tmp_path):
    env = os.environ.copy()
    env.pop('TWOBYTEASR_TEST_ROOT', None)
    env['2BYTEASR_USER_DATA_ROOT'] = str(tmp_path)
    code = r"""
import sys, types
sys.argv = ['quick_start.py', '--mcp-stdio']
fake = types.ModuleType('twobyteasr.local_mcp.mcp_stdio')
fake.main = lambda argv: 73
sys.modules[fake.__name__] = fake
import quick_start
assert quick_start.main() == 73
assert 'PySide6.QtCore' not in sys.modules
"""
    result = _child(code, env)
    assert result.returncode == 0, result.stderr
