# SPDX-License-Identifier: GPL-3.0-only
"""Offline, installation-local license documents shared by both workspaces."""
from pathlib import Path
import sys

ROOT_DOCUMENTS = frozenset({'LICENSE', 'PROJECT_LICENSE.md', 'SOURCE_DELIVERY.md',
    'BUILD_FROM_SOURCE.md', 'CONTRIBUTING.md', 'THIRD_PARTY_NOTICES.md'})


def document_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])).resolve()


def resolve_document(relative, root=None):
    root = Path(root or document_root()).resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError('Document is outside this installation')
    rel = candidate.relative_to(root).as_posix()
    if rel not in ROOT_DOCUMENTS and not rel.startswith('licenses/'):
        raise ValueError('Not a license document')
    if not candidate.is_file() or candidate.suffix.lower() in {'.exe', '.dll', '.pyd', '.zip', '.gz', '.xz', '.bz2'}:
        raise ValueError('Not a readable license text')
    return candidate


def show_document(parent, relative):
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QLabel, QPushButton
    from .i18n import bind_text, tr
    from .studio_theme import apply_secondary_surface_theme

    class OfflineBrowser(QTextBrowser):
        def loadResource(self, kind, url):
            # License pages contain text; never fetch remote images or resources.
            return None

    dialog = QDialog(parent)
    dialog.setObjectName('licenseDocumentDialog')
    bind_text(dialog, '许可与对应源码', property='windowTitle')
    dialog.resize(840, 650)
    layout = QVBoxLayout(dialog)
    location = QLabel(); location.setObjectName('licenseDocumentLocation'); location.setWordWrap(True)
    browser = OfflineBrowser(); browser.setObjectName('licenseDocumentText')
    browser.setOpenLinks(False); browser.setOpenExternalLinks(False)
    layout.addWidget(location); layout.addWidget(browser, 1)
    close = bind_text(QPushButton(), '关闭'); close.clicked.connect(dialog.close); layout.addWidget(close)
    current = {'path': None}

    def display(name):
        try:
            path = resolve_document(name)
            content = path.read_text('utf-8-sig')
            current['path'] = path
            browser.document().setBaseUrl(QUrl.fromLocalFile(str(path.parent) + '/'))
            if path.suffix.lower() == '.md': browser.setMarkdown(content)
            else: browser.setPlainText(content)
            location.setText(path.relative_to(document_root()).as_posix())
        except (OSError, ValueError, UnicodeError):
            location.setText(tr('无法读取本地许可文件'))

    def follow(url):
        if url.scheme() not in ('', 'file') or not current['path']:
            location.setText(tr('此入口仅查看随软件提供的本地材料'))
            return
        if url.isLocalFile(): path = Path(url.toLocalFile())
        else: path = current['path'].parent / url.path()
        display(path)
    browser.anchorClicked.connect(follow)
    display(relative)
    apply_secondary_surface_theme(dialog)
    dialog.exec()
