"""Open the real cover editor using a fresh, isolated sample document."""
import argparse
import os
from pathlib import Path
import sys
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshot', type=Path, help='Capture the native editor and exit')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(root/'tmp'/'cover-snap-preview'/uuid.uuid4().hex)
    sys.path.insert(0, str(root))
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QSettings, QTimer
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from twobyteasr.cover.cover_document import CoverDocument
    from twobyteasr.cover.cover_editor import CoverEditor

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope,
                      str(Path(os.environ['TWOBYTEASR_TEST_ROOT'])/'qsettings'))
    app = QApplication([])
    image = QImage(700, 590, QImage.Format_ARGB32)
    image.fill(QColor('#bdd2df'))
    painter = QPainter(image)
    painter.setPen(QColor('#fff0be'))
    painter.setBrush(QColor('#fff0be'))
    painter.drawEllipse(90, 70, 160, 160)
    painter.setBrush(QColor('#638078'))
    painter.setPen(QColor('#638078'))
    painter.drawEllipse(-100, 300, 1000, 700)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, 'PNG')
    document = CoverDocument(width=1920, height=1080, background='#f4f4f0')
    layer = document.add_image(bytes(data), '拖动这张图片试试', (700, 590))
    layer.width, layer.height, layer.x, layer.y = 700, 590, 1180, 450
    editor = CoverEditor(document)
    editor.setWindowTitle('制作封面 · 边框吸附开发版（独立测试）')
    editor.session.selected = {layer.id}
    editor.session.changed.emit()
    editor.show()
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            editor._cover_snap.button.setChecked(True)
            app.processEvents()
            editor.grab().save(str(args.screenshot))
            editor.session.saved_signature = editor.session.document.signature()
            editor.close()
            app.quit()
        QTimer.singleShot(500, capture)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
