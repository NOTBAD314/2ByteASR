"""Normal source entry, fresh isolated profile and a private Windows desktop."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('Evidence must be in repository tmp')
    if not args.child:
        if out.exists():
            raise ValueError('Fresh output directory required')
        out.mkdir(parents=True)
        from isolated_windows_desktop import run_on_desktop
        env = os.environ.copy()
        env.update(TWOBYTEASR_TEST_ROOT=str(out), QT_QPA_PLATFORM='windows',
                   TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1',
                   HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        code = run_on_desktop([sys.executable, '-B', __file__, '--child', '--output', str(out)],
                              cwd=ROOT, env=env, output=out/'process', timeout=100)
        if (out/'result.json').exists():
            receipt=json.loads((out/'result.json').read_text('utf-8'))
            receipt['checks_passed']=receipt['passed']
            receipt['process_exit']=code
            receipt['passed']=receipt['checks_passed'] and code==0
            (out/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
        print(f'Native process exit={code}', flush=True)
        print((out/'result.json').read_text('utf-8') if (out/'result.json').exists() else f'No receipt; exit={code}')
        return code

    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtCore import QTimer, QSettings, QPoint, Qt
    from PySide6.QtGui import QPalette
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFrame, QDialog
    import quick_start
    import twobyteasr.ui as ui
    from twobyteasr.theme_manager import theme_key
    from twobyteasr.ui_theme import theme_definition
    result = {'passed': False, 'checks': [], 'entry': 'quick_start.main', 'profile': str(out)}
    def check(name, value, detail=None):
        result['checks'].append({'name':name, 'passed':bool(value), 'detail':detail})
        if not value:
            raise AssertionError(name)
    def capture(window, name):
        # Native PrintWindow pixels, not a web mockup or an offscreen QWidget.
        import ctypes
        from ctypes import wintypes as W
        from capture_process_window import print_window
        user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
        user.GetWindowDC.argtypes=[W.HWND]; user.GetWindowDC.restype=W.HDC
        user.ReleaseDC.argtypes=[W.HWND,W.HDC]
        user.PrintWindow.argtypes=[W.HWND,W.HDC,W.UINT]
        gdi.CreateCompatibleDC.argtypes=[W.HDC];gdi.CreateCompatibleDC.restype=W.HDC
        gdi.CreateCompatibleBitmap.argtypes=[W.HDC,ctypes.c_int,ctypes.c_int];gdi.CreateCompatibleBitmap.restype=W.HBITMAP
        gdi.SelectObject.argtypes=[W.HDC,W.HANDLE];gdi.SelectObject.restype=W.HANDLE
        gdi.GetDIBits.argtypes=[W.HDC,W.HBITMAP,W.UINT,W.UINT,ctypes.c_void_p,ctypes.c_void_p,W.UINT]
        gdi.DeleteObject.argtypes=[W.HANDLE];gdi.DeleteDC.argtypes=[W.HDC]
        rect=W.RECT();user.GetWindowRect(W.HWND(int(window.winId())),ctypes.byref(rect))
        print_window(int(window.winId()),(rect.left,rect.top,rect.right,rect.bottom)).save(out/name)
    def audit(window):
        app=QApplication.instance()
        try:
            window.resize(1440,900); QTest.qWait(250)
            check('fresh profile defaults to grape',theme_key()=='grape')
            check('actual application palette is grape',app.palette().color(QPalette.ColorRole.Window).name()==theme_definition('grape').app_background)
            check('Chinese brand text',window.header_subtitle.text()=='兔白字幕')
            check('Chinese brand is 27px and heavy',window.header_subtitle.font().pixelSize()==27 and window.header_subtitle.font().weight()>=800,
                  {'size':window.header_subtitle.font().pixelSize(),'weight':window.header_subtitle.font().weight()})
            check('no vertical separator',not any(w.frameShape()==QFrame.Shape.VLine for w in window.header_content.findChildren(QFrame)))
            gap=window.header_subtitle.x()-window.brand.geometry().right()-1
            check('brand names are adjacent',0<=gap<=12, gap)
            check('brand fits its layout',window.header_subtitle.width()>=window.header_subtitle.fontMetrics().horizontalAdvance('兔白字幕'))
            check('title bar uses brand', '兔白字幕' in window.windowTitle() and '智能游戏字幕工作台' not in window.windowTitle())
            capture(window,'desktop-brand.png')
            def settings_check():
                try:
                    dialog=next(w for w in app.allWidgets() if w.isVisible() and hasattr(w,'theme_combo'))
                    dialog.navigation.setCurrentRow(2);QTest.qWait(120)
                    check('real appearance selector defaults to grape',dialog.theme_combo.currentData()=='grape',dialog.theme_combo.currentText())
                    check('theme name identifies deep grape','深葡萄紫' in dialog.theme_combo.currentText())
                    capture(dialog,'desktop-appearance.png')
                    # Dispose the audit dialog directly: the private desktop can
                    # suspend native opacity animations. Closing motion is not
                    # part of this brand/default-theme acceptance.
                    QDialog.done(dialog, QDialog.DialogCode.Rejected)
                except Exception:
                    result['error']=traceback.format_exc();app.closeAllWindows()
            QTimer.singleShot(450,settings_check)
            QTest.mouseClick(window.app_settings_button,Qt.MouseButton.LeftButton)
            check('settings inspected',any(c['name']=='real appearance selector defaults to grape' for c in result['checks']))
            result['passed']=True
        except Exception:
            result['error']=traceback.format_exc()
        finally:
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
            # Use the normal close chain so Studio actors/workers are shut down
            # before Qt destruction; app.exit alone skips MainWindow.closeEvent.
            window.close()
            QTimer.singleShot(250,lambda:app.exit(0 if result['passed'] else 1))
    original=ui.run_desktop_app
    def observed_entry(*a,**kw):
        app=QApplication.instance()
        timer=QTimer(app)
        def ready():
            windows=[w for w in app.topLevelWidgets() if isinstance(w,ui.MainWindow) and w.isVisible()]
            if windows:
                timer.stop();QTimer.singleShot(500,lambda:audit(windows[0]))
        timer.timeout.connect(ready);timer.start(200);app._brand_audit_timer=timer
        return original(*a,**kw)
    ui.run_desktop_app=observed_entry
    quick_start._log_path=lambda:str(out/'startup.log')
    sys.argv=[str(ROOT/'quick_start.py')]
    return quick_start.main()


if __name__=='__main__':
    raise SystemExit(main())
