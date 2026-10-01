"""Localized labels without changing saved font identities."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter

from .i18n import bind_text


def style_label(style):
    return {'Regular': '常规', 'Normal': '常规', 'Medium': '中等', 'Light': '细体',
            'Thin': '极细', 'ExtraLight': '特细', 'SemiBold': '半粗', 'DemiBold': '半粗',
            'Bold': '粗体', 'ExtraBold': '特粗', 'Heavy': '特粗', 'Black': '超粗',
            'Italic': '斜体', 'Bold Italic': '粗斜体'}.get(style, style)


class FontFamilyCombo(QComboBox):
    def __init__(self, faces, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(10)
        self.setMaxVisibleItems(12)
        bind_text(self.lineEdit(), '搜索中文或英文字体名', property='placeholderText')
        groups = {}
        for face in faces:
            groups.setdefault(face.family, []).append(face)
        suggestions = set()
        self.aliases = {}
        labels = {}
        for family, group in groups.items():
            label = next((f.display_family for f in group if f.display_family and f.display_family != family), family)
            labels[family] = label
            for face in group:
                for alias in (*face.aliases, family, label):
                    self.aliases.setdefault(alias.casefold(), family)
            suggestions.update((label, family))
        for family in sorted(groups, key=lambda f: (labels[f] == f, labels[f].casefold())):
            self.addItem(labels[family], family)
            self.setItemData(self.count()-1, family, Qt.ToolTipRole)
        completer = QCompleter(sorted(suggestions, key=str.casefold), self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.setCompleter(completer)

    def family(self):
        text = self.currentText().strip()
        if self.currentIndex() >= 0 and text == self.itemText(self.currentIndex()):
            return self.currentData()
        return self.aliases.get(text.casefold(), text)

    def show_family(self, family):
        index = self.findData(self.aliases.get(family.casefold(), family))
        if index >= 0:
            self.setCurrentIndex(index)
            self.setEditText(self.itemText(index))
        else:
            self.setCurrentIndex(-1)
            self.setEditText(family)
