"""Main application stylesheet extracted from the legacy UI facade."""

from __future__ import annotations

from twobyteasr.typography import TITLE_FONT_STACK, UI_FONT_STACK
from twobyteasr.design.tokens import WEIGHT_SCALE
from twobyteasr.ui_theme import (
    AMBER, CHARCOAL, CORAL, GREEN, GREEN_HOVER, GREEN_PRESSED,
    GREEN_SOFT, GREEN_SUBTLE, INK, MUTED, MUTED_LIGHT, SURFACE_MUTED,
    BACKGROUND as IVORY, BACKGROUND_ALT as PARCHMENT,
    BORDER as LINE, SURFACE, BLUE,
)

APP_QSS = f"""
QWidget {{
    color: {INK};
    font-family: {UI_FONT_STACK};
    font-size: 14px;
    font-weight: 500;
}}
QMainWindow, QWidget#appRoot {{ background: {IVORY}; }}
QWidget#appRoot {{ border: 1px solid {LINE}; border-radius: 12px; }}
QWidget#appContent {{ background: {IVORY}; border: 0; }}
QFrame#appHeader {{
    background: {SURFACE};
    border: 0;
    border-bottom: 1px solid {LINE};
}}
QFrame#windowTitleBar {{
    background: {SURFACE};
    border: 0;
}}
QLabel#windowChromeTitle {{ color: {MUTED}; font-size: 12px; font-weight: 500; }}
QPushButton#windowControl, QPushButton#windowControlClose {{
    background: transparent;
    color: #494943;
    border: 0;
    border-radius: 6px;
    padding: 0;
    min-width: 28px;
    min-height: 26px;
    max-width: 28px;
    max-height: 26px;
}}
QPushButton#windowControl:hover {{ background: #eee9df; }}
QPushButton#windowControlClose:hover {{ background: #f1d9d1; color: #7b4035; }}
QPushButton#windowControl:pressed {{ background: #e3ddd1; }}
QPushButton#windowControlClose:pressed {{ background: #e2b9ae; color: #663229; }}
QLabel#chromeBrandMark {{ color: {GREEN}; font-size: 12px; font-weight: 700; }}
QLabel#headerSubtitle {{ color: {INK}; font-family: {TITLE_FONT_STACK}; font-size: 27px; font-weight: 800; }}
QLabel#brand, QLabel#recognitionModelName, QLabel#contentHeroTitle, QLabel#sectionTitle,
QLabel#termLibraryTitle, QLabel#termGameTitle, QLabel#smartDialogTitle {{
    font-family: {TITLE_FONT_STACK};
}}
QLabel#headerStatus {{
    color: {GREEN};
    background: {GREEN_SOFT};
    border: 0;
    border-radius: 10px;
    padding: 4px 9px;
    font-size: 13px;
    font-weight: 600;
}}
QLabel#pageSubtitle {{ color: #5f5d56; font-size: 14px; font-weight: 500; }}
QLabel#contentHeroTitle {{ color: {INK}; font-size: 24px; font-weight: {WEIGHT_SCALE['heavy']}; }}
QFrame#contentRule {{ background: {LINE}; border: 0; }}
QFrame#modalBackdrop {{
    /* Alpha is painted directly by _ModalBackdrop; never animate a graphics effect. */
    background: transparent;
    border: 0;
}}
QFrame#modalFooter {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 14px;
}}
QFrame#actionBar {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 16px;
}}
QDialog {{
    background-color: {IVORY};
    color: {INK};
    border: 1px solid {LINE};
    border-radius: 4px;
}}
QDialog QWidget {{ background-color: transparent; color: {INK}; }}
QDialog QLabel, QMessageBox QLabel {{
    background-color: transparent;
    color: {INK};
}}
QMessageBox {{
    background-color: {IVORY};
    color: {INK};
    border: 1px solid {LINE};
    border-radius: 12px;
}}
QFrame#workflow, QFrame#accordion, QFrame#mediaRow {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 16px;
}}
/* 识别方案三角色卡（批准图 #1） */
QFrame#recognitionRoleCard {{
    background: {GREEN_SUBTLE};
    border: 1px solid #bfd2bd;
    border-radius: 14px;
}}
QFrame#recognitionRoleCard:hover {{ border-color: {GREEN}; background: #eef5ea; }}
QFrame#recognitionRoleCard:focus {{ border: 1px solid {GREEN}; }}
/* 时间轴卡：暖黄底（批准图 #1 三卡 绿/暖黄/绿） */
QFrame#recognitionRoleCard[role="timeline"] {{
    background: #f4ecd9;
    border-color: #d8c9a3;
}}
QFrame#recognitionRoleCard[role="timeline"]:hover {{ background: #faf3e2; border-color: {AMBER}; }}
QLabel#recognitionRoleIcon {{
    background: {GREEN};
    color: #ffffff;
    border-radius: 22px;
    min-width: 44px;
    min-height: 44px;
    max-width: 44px;
    max-height: 44px;
    padding: 0px;
}}
QFrame#recognitionRoleCard[density="compact"] QLabel#recognitionRoleIcon {{
    border-radius: 22px;
    min-width: 44px; min-height: 44px;
    max-width: 44px; max-height: 44px;
}}
QFrame#recognitionRoleCard[density="normal"] QLabel#recognitionRoleIcon {{
    border-radius: 28px;
    min-width: 56px; min-height: 56px;
    max-width: 56px; max-height: 56px;
}}
QFrame#recognitionRoleCard[density="large"] QLabel#recognitionRoleIcon {{
    border-radius: 34px;
    min-width: 68px; min-height: 68px;
    max-width: 68px; max-height: 68px;
}}
QFrame#recognitionRoleCard[density="extra_large"] QLabel#recognitionRoleIcon {{
    border-radius: 34px;
    min-width: 68px; min-height: 68px;
    max-width: 68px; max-height: 68px;
}}
QFrame#recognitionRoleCard[role="timeline"] QLabel#recognitionRoleIcon {{
    background: #e4c36a;
    color: #ffffff;
}}
QFrame#recognitionRoleCard[role="review"] QLabel#recognitionRoleIcon {{
    background: {GREEN};
    color: #ffffff;
}}
QLabel#recognitionRoleLabel {{ color: {INK}; font-family: {TITLE_FONT_STACK}; font-size: 20px; font-weight: 800; }}
QFrame#recognitionRoleCard[density="compact"] QLabel#recognitionRoleLabel {{ font-size: 16px; }}
QFrame#recognitionRoleCard[density="large"] QLabel#recognitionRoleLabel {{ font-size: 23px; }}
QFrame#recognitionRoleCard[density="extra_large"] QLabel#recognitionRoleLabel {{ font-size: 26px; }}
QLabel#recognitionModelName {{
    color: {INK};
    font-size: 28px;
    font-weight: {WEIGHT_SCALE['heavy']};
    border: 0;
    background: transparent;
}}
QFrame#recognitionRoleCard[density="compact"] QLabel#recognitionModelName {{ font-size: 22px; }}
QFrame#recognitionRoleCard[density="large"] QLabel#recognitionModelName {{ font-size: 36px; }}
QFrame#recognitionRoleCard[density="extra_large"] QLabel#recognitionModelName {{ font-size: 40px; }}
QLabel#recognitionModelDescription {{
    color: {MUTED}; font-size: 15px; font-weight: 500;
    background: transparent; border: 0;
}}
QFrame#recognitionRoleCard[density="large"] QLabel#recognitionModelDescription {{ font-size: 16px; }}
QFrame#recognitionRoleCard[density="extra_large"] QLabel#recognitionModelDescription {{ font-size: 17px; }}
QLabel#recognitionKindBadge {{
    background: #efe8da;
    color: #5b564c;
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 600;
}}
QLabel#recognitionStatusGood {{
    background: {GREEN_SOFT};
    color: {GREEN};
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 700;
}}
QLabel#recognitionStatusWarn {{
    background: {AMBER};
    color: #ffffff;
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 700;
}}
QLabel#recognitionStatusMuted {{
    background: #e4e0d6;
    color: {MUTED};
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 700;
}}
QPushButton#recognitionRecovery {{
    background: {GREEN_SOFT};
    color: {GREEN};
    border: 1px solid #c4d3ba;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#recognitionRecovery:hover {{ background: #dcead2; }}
QLabel#recognitionChangeHint {{ color: {MUTED}; font-size: 12px; }}
QPushButton#glossaryChip {{
    background: {GREEN_SOFT};
    color: {GREEN};
    border: 1px solid #c4d3ba;
    border-radius: 12px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#glossaryChip:hover {{ background: #f3e3dd; color: {CORAL}; border-color: #d8b3a9; }}
/* 三设置 tile（批准图 #1/#2） */
QFrame#settingTile {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 16px;
    text-align: left;
    min-height: 88px;
}}
QFrame#settingTile:hover {{ border-color: {AMBER}; background: #fffaf2; }}
QFrame#settingTile:checked, QFrame#settingTile[checked="true"] {{ border: 1.5px solid {GREEN}; background: {GREEN_SUBTLE}; }}
QLabel#settingTileIcon {{
    background: {GREEN_SOFT};
    border-radius: 12px;
}}
QLabel#settingTileTitle {{ color: {INK}; font-size: 16px; font-weight: 600; }}
QLabel#settingTileSummary {{ color: {MUTED}; font-size: 13px; }}
QLabel#settingTileChevron {{ color: #9a948a; font-size: 18px; }}
QListWidget#glossaryPickerList::item {{
    padding: 6px 8px;
    border-radius: 6px;
}}
QListWidget#glossaryPickerList::item:selected {{ background: {GREEN_SOFT}; color: {GREEN}; }}
QFrame#batchStrip {{
    background: #eef6ea;
    border: 1px solid #d5e0cb;
    border-radius: 10px;
}}
/* 智能建词三 source 卡（批准图 #7） */
QFrame#smartSourceCard {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 14px;
}}
QFrame#smartSourceCard:hover {{ border-color: {AMBER}; background: #fffaf2; }}
QFrame#smartSourceCard[selected="true"] {{
    border: 1.5px solid {GREEN};
    background: {GREEN_SUBTLE};
}}
QLabel#smartSourceTitle {{ color: {INK}; font-size: 14px; font-weight: 600; }}
QLabel#smartSourceBadge {{
    background: {GREEN};
    color: white;
    border-radius: 8px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel#smartStep {{
    color: {MUTED};
    font-size: 13px;
    padding: 2px 0;
}}
QLabel#smartStep[active="true"] {{
    color: {GREEN};
    font-weight: 700;
}}
QLabel#smartDialogTitle {{ color: {INK}; font-size: 24px; font-weight: 700; }}
QLabel#smartBreadcrumb {{ color: {MUTED}; font-size: 12px; }}
QFrame#smartStepper {{
    background: {PARCHMENT};
    border: 1px solid {LINE};
    border-radius: 12px;
}}
QFrame#smartStepDot {{
    background: transparent;
    border: 1.5px solid #bdb8ae;
    border-radius: 9px;
}}
QFrame#smartStepDot[active="true"] {{
    background: {GREEN};
    border: 1.5px solid {GREEN};
}}
QFrame#smartStepLine {{
    background: #d5e0cb;
    border: 0;
}}
QFrame#smartAiCard {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 14px;
}}
QLabel#smartAiPill {{
    background: {GREEN_SOFT};
    color: {GREEN};
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 600;
}}
QFrame#smartAiWarn {{
    background: #fff6e8;
    border: 1px solid #e8d2a8;
    border-radius: 8px;
}}
QFrame#registryStrip {{
    background: #f2f6ee;
    border: 1px solid #d5e0cb;
    border-radius: 10px;
}}
/* 绿主题 checkbox（禁止 Windows 蓝色系统复选框） */
QListWidget#smartCandidateList::indicator,
QListWidget#glossaryPickerList::indicator,
QListWidget#termGameList::indicator {{
    width: 18px; height: 18px;
    border-radius: 4px;
    border: 1px solid #bdb8ae;
    background: #fffefa;
}}
QListWidget#smartCandidateList::indicator:hover,
QListWidget#glossaryPickerList::indicator:hover,
QListWidget#termGameList::indicator:hover {{ border-color: {GREEN}; }}
QListWidget#smartCandidateList::indicator:checked,
QListWidget#glossaryPickerList::indicator:checked,
QListWidget#termGameList::indicator:checked {{
    background: {GREEN};
    border-color: {GREEN};
    image: url(assets/ui-check.png);
}}
QFrame#settingsSurface {{
    background: transparent;
    border: 0;
}}
QFrame#homeContentProfile, QFrame#homeBatchGlossary {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 10px;
}}
QFrame#homeBatchGlossary {{
    background: {SURFACE};
    border-color: {LINE};
}}
QFrame#homeContentProfile QFrame#homeBatchGlossary {{
    background: transparent; border: 0; border-top: 1px solid {LINE}; border-radius: 0;
}}
QLabel#homeCardTitle {{
    color: {INK};
    font-size: 15px;
    font-weight: 600;
}}
QLabel#homeGlossaryStatus {{
    color: #3d4639;
    font-size: 14px;
    font-weight: 600;
}}
QFrame#termLibrarySidebar {{
    background: #f6f2ea;
    border: 1px solid #ddd5c7;
    border-radius: 12px;
}}
QFrame#termLibraryContent {{
    background: #fffefa;
    border: 1px solid #d9d0c1;
    border-radius: 12px;
}}
QFrame#termLibraryContentHeader {{
    background: #fffefa;
    border: 0;
    border-bottom: 1px solid #ece4d8;
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
}}
QWidget#termLibraryBody {{
    background: #fffefa;
    border: 0;
}}
QFrame#termQuickAdd {{
    background: #faf7f0;
    border: 1px solid #e5dccd;
    border-radius: 10px;
}}
QFrame#termLibraryFooter {{
    background: #faf7f0;
    border: 0;
    border-top: 1px solid #e8dfd2;
    border-bottom-left-radius: 12px;
    border-bottom-right-radius: 12px;
}}
QFrame#termReferencePanel {{
    background: #faf8f3;
    border: 1px solid #e6ddcf;
    border-radius: 10px;
}}
QLabel#termReferencePolicy {{
    color: #6c6961;
    font-size: 12px;
    font-weight: 400;
}}
QLabel#termLibraryTitle {{
    color: #28261f;
    font-size: 21px;
    font-weight: 700;
}}
QLabel#termGameTitle {{
    color: #28261f;
    font-size: 15px;
    font-weight: 700;
}}
QLabel#termLibraryBadge {{
    background: #e4ebdd;
    color: {GREEN};
    border: 1px solid #d4e0ce;
    border-radius: 9px;
    padding: 3px 9px;
    font-size: 12px;
    font-weight: 700;
}}
QFrame#recognitionRoleCard[density="large"] QLabel#recognitionKindBadge,
QFrame#recognitionRoleCard[density="large"] QLabel#recognitionStatusGood,
QFrame#recognitionRoleCard[density="large"] QLabel#recognitionStatusWarn,
QFrame#recognitionRoleCard[density="large"] QLabel#recognitionStatusMuted {{ font-size: 15px; }}
QFrame#recognitionRoleCard[density="large"] QLabel#recognitionKindBadge {{ font-size: 15px; }}
QFrame#recognitionRoleCard[density="extra_large"] QLabel#recognitionKindBadge,
QFrame#recognitionRoleCard[density="extra_large"] QLabel#recognitionStatusGood,
QFrame#recognitionRoleCard[density="extra_large"] QLabel#recognitionStatusWarn,
QFrame#recognitionRoleCard[density="extra_large"] QLabel#recognitionStatusMuted {{ font-size: 16px; }}
QLabel#termLibrarySectionTitle {{
    color: {INK};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#termLearnedTitle {{
    color: #3f3b34;
    font-size: 13px;
    font-weight: 600;
}}
QLabel#termEmptyTitle {{
    color: {INK};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#termEmptyHint {{
    color: {MUTED};
    font-size: 13px;
    font-weight: 400;
}}
QLabel#categoryChip {{
    background: {GREEN_SOFT};
    color: {GREEN};
    border: 1px solid #d4e1cf;
    border-radius: 9px;
    padding: 3px 8px;
    font-size: 12px;
    font-weight: 600;
}}
QLabel#statusBadgeGood {{
    background: {GREEN_SOFT}; color: {GREEN}; border-radius: 9px;
    padding: 3px 8px; font-size: 12px; font-weight: 600;
}}
QLabel#statusBadgeWarn {{
    background: #f7edd9; color: #8f6228; border-radius: 9px;
    padding: 3px 8px; font-size: 12px; font-weight: 600;
}}
QLabel#statusBadgeMuted {{
    background: #efebe3; color: {MUTED}; border-radius: 9px;
    padding: 3px 8px; font-size: 12px; font-weight: 600;
}}
QListWidget#termGameList {{
    background: transparent;
    border: 0;
    border-radius: 10px;
    padding: 0;
    outline: 0;
}}
QListWidget#termGameList::item {{
    color: #4d4a43;
    border: 0;
    border-radius: 10px;
    padding: 0;
    margin: 3px 0;
}}
QListWidget#termGameList::item:hover {{ background: #eeeae2; }}
QListWidget#termGameList::item:selected {{
    background: transparent;
    color: {GREEN};
    font-weight: 700;
}}
QFrame#termGameRow {{
    background: #fffefa;
    border: 1px solid #e2d9ca;
    border-radius: 9px;
}}
QFrame#termGameRow:hover {{ background: #fbf8f1; border-color: #cfc2af; }}
QFrame#termGameRow[selected="true"] {{
    background: #e6efe2;
    border: 1px solid #9fb994;
}}
QLabel#termGameRowName {{ color: {INK}; font-size: 14px; font-weight: 600; }}
QLabel#termGameRowCount {{ color: {MUTED}; font-size: 12px; font-weight: 500; }}
QLabel#termGameRowType {{
    background: #eee8dc;
    color: #746d61;
    border-radius: 7px;
    padding: 1px 6px;
    font-size: 11px;
    font-weight: 500;
}}
QLabel#termGameRowIcon {{ background: transparent; border: 0; }}
QFrame#termGameRow[selected="true"] QLabel#termGameRowName {{ color: {GREEN}; }}
QLabel#termSidebarSync {{ color: {MUTED}; font-size: 11px; font-weight: 500; }}
QLabel#termQuickAddTitle {{ color: {INK}; font-size: 13px; font-weight: 600; }}
QTableView#termMappingTable {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 10px;
    gridline-color: #eee7dc;
    outline: 0;
    selection-background-color: {GREEN_SUBTLE};
    selection-color: {INK};
}}
QTableView#termMappingTable QTableCornerButton::section,
QTableView#termMappingTable QHeaderView::section {{
    background: {PARCHMENT};
    color: #5f5a51;
    border: 0;
    border-bottom: 1px solid {LINE};
    padding: 8px 10px;
    font-weight: 600;
    font-family: "Source Han Sans SC", "思源黑体", "Microsoft YaHei UI", sans-serif;
}}
QTableView#termMappingTable QHeaderView::section:hover {{
    background: #f0e9dc;
}}
QTableView#termMappingTable::item {{
    background: {SURFACE};
    color: {INK};
    padding: 7px 10px;
    border-bottom: 1px solid #eee7dc;
}}
QTableView#termMappingTable::item:hover {{ background: #f3f7ef; }}
QTableView#termMappingTable::item:selected {{ background: {GREEN_SUBTLE}; color: {INK}; }}
/* Empty area inside the viewport should not be a stark white block */
QTableView#termMappingTable QScrollArea,
QTableView#termMappingTable QWidget#qt_scrollarea_viewport {{
    background: {SURFACE};
}}
/* Scrollbars follow DS warm neutrals */
QTableView#termMappingTable QScrollBar:vertical {{
    background: #f0e9dc; width: 10px; margin: 0; border-radius: 5px;
}}
QTableView#termMappingTable QScrollBar::handle:vertical {{
    background: #c2b6a6; min-height: 28px; border-radius: 5px;
}}
QTableView#termMappingTable QScrollBar::add-line:vertical,
QTableView#termMappingTable QScrollBar::sub-line:vertical {{ height: 0; }}
QPushButton#termRowAction {{
    background: transparent; color: {MUTED}; border: 0; border-radius: 7px;
    padding: 4px 7px; min-height: 22px; font-weight: 600;
}}
QPushButton#termRowAction:hover {{ background: {GREEN_SOFT}; color: {GREEN}; }}
QListWidget#smartCandidateList::item {{
    background: #fffefa;
    border: 1px solid #ece5d8;
    border-radius: 8px;
    padding: 7px 10px;
    margin: 2px 0;
}}
QListWidget#smartCandidateList::item:hover {{ border-color: #d4b783; background: #fffaf2; }}
QFrame#mediaRow[dropActive="true"] {{
    background: #eef6ea;
    border: 2px dashed {GREEN};
}}
QFrame#mediaRow[empty="true"] {{
    background: #fffaf1;
    border: 2px dashed #c7ad84;
}}
QFrame#dropOverlay {{
    background: transparent;
    border: 0;
}}
QFrame#dropTarget {{
    background: {SURFACE};
    border: 3px dashed {GREEN};
    border-radius: 24px;
}}
QLabel#dropOverlayTitle {{
    color: {INK}; font-size: 22px; font-weight: 700;
}}
QLabel#dropOverlayHint {{
    color: {MUTED}; font-size: 14px;
}}
QLabel#dropHint {{ color: {MUTED}; font-size: 13px; }}
QFrame#endpointCard {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 10px;
}}
QFrame#progressHero {{
    background: {SURFACE_MUTED};
    border: 1px solid {LINE};
    border-radius: 14px;
}}
QFrame#phaseCard, QFrame#currentStageCard, QFrame#eventFeedCard, QFrame#consoleCard,
QFrame#resultSummaryCard, QFrame#resultFilesCard, QFrame#resultLogCard {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 12px;
}}
QLabel#progressPercent {{
    background: {GREEN}; color: white; border-radius: 15px;
    font-size: 16px; font-weight: 700; padding: 6px 12px;
}}
QLabel#stageEyebrow {{ color: {AMBER}; font-size: 13px; font-weight: 600; }}
QLabel#stageLarge {{ font-size: 18px; font-weight: 600; }}
QLabel#consoleBadge {{
    background: #e9dfcf; color: #5b4a36; border-radius: 9px;
    padding: 4px 9px; font-size: 12px; font-weight: 700;
}}
QListWidget#eventFeed {{
    background: #fffaf1; border: 0; border-radius: 11px; padding: 5px;
    outline: 0;
}}
QListWidget#eventFeed::item {{
    border: 0; margin: 3px 1px; padding: 0;
}}
QTextEdit#consoleLog {{
    background: #30332f; color: #edf0e9; border: 0; border-radius: 9px;
    padding: 9px; font-family: "Cascadia Mono", "Microsoft YaHei UI"; font-size: 13px;
    selection-background-color: #6d8d67;
}}
QTextEdit#resultFiles {{
    background: #fffaf1; border: 0; border-radius: 9px; padding: 9px;
}}
QTextEdit#resultConsole {{
    background: #30332f; color: #edf0e9; border: 0; border-radius: 9px;
    padding: 9px; font-family: "Cascadia Mono", "Microsoft YaHei UI"; font-size: 13px;
}}
QLineEdit, QPlainTextEdit, QListWidget {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 10px;
    padding: 8px 11px;
    min-height: 22px;
    selection-background-color: {GREEN};
}}
QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus {{
    border: 1px solid {GREEN};
}}
QComboBox {{
    color: {INK};
    background-color: {SURFACE};
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 10px;
    padding: 5px 30px 5px 11px;
    min-height: 22px;
    outline: none;
    selection-background-color: #e5eee2;
    selection-color: {INK};
}}
/* 非可编辑组合框走 CC_ComboBox：锁死不透明白底，否则上下露出 Fusion
   默认面板（Win11 上表现为大块黑带） */
QComboBox:!editable,
QComboBox:!editable:on,
QComboBox:!editable:hover,
QComboBox:!editable:focus {{
    color: {INK};
    background-color: #ffffff;
    background: #ffffff;
}}
QComboBox:hover {{
    border: 1px solid #9a948a;
    background-color: #ffffff;
}}
QComboBox:focus,
QComboBox:on {{
    border: 1px solid {GREEN};
    background-color: #ffffff;
}}
QComboBox:disabled {{
    color: #99958d;
    background-color: #ece7de;
    border: 1px solid #d2cbc0;
}}
/* 关键：origin 用 border（与主框同高），杜绝上下黑带 */
QComboBox::drop-down {{
    subcontrol-origin: border;
    subcontrol-position: center right;
    width: 24px;
    border: none;
    background: transparent;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}}
QComboBox::drop-down:hover,
QComboBox::drop-down:on {{
    background: transparent;
    border: none;
}}
QComboBox::down-arrow {{
    width: 12px;
    height: 12px;
    image: url(assets/ui-chevron-down.png);
}}
QComboBox::down-arrow:on {{
    image: url(assets/ui-chevron-down.png);
}}
QComboBox QAbstractItemView {{
    color: {INK};
    background-color: #ffffff;
    background: #ffffff;
    border: 1px solid {LINE};
    border-radius: 8px;
    outline: none;
    padding: 4px;
    selection-background-color: #e5eee2;
    selection-color: {INK};
}}
QComboBox QAbstractItemView::item {{
    min-height: 28px;
    padding: 4px 8px;
    border: none;
    background-color: #ffffff;
    color: {INK};
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: #f0fdf4;
    color: {INK};
}}
QFrame#comboPopupWindow {{
    background: transparent;
    border: 0;
}}
QListWidget#comboPopupList {{
    color: {INK};
    background: #ffffff;
    border: 1px solid {LINE};
    border-radius: 9px;
    outline: 0;
    padding: 4px;
}}
QListWidget#comboPopupList::item {{
    min-height: 30px;
    padding: 4px 9px;
    margin: 0;
    border: 0;
    border-radius: 4px;
    color: {INK};
    background: #ffffff;
}}
QListWidget#comboPopupList::item:hover {{
    background: #f0f6ed;
}}
QListWidget#comboPopupList::item:selected {{
    color: {INK};
    background: #e3ecdf;
    border: 1px solid #9eaa98;
}}
QPushButton {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 10px;
    padding: 8px 16px;
    min-height: 20px;
    font-weight: 600;
}}
QWidget#termMappingEmpty {{
    background: #fbf8f1;
    border: 1px dashed #ddd3c3;
    border-radius: 12px;
}}
QPushButton:hover {{ background: #faf6ee; border-color: #c8b79f; }}
QPushButton:pressed {{ background: #f0e9de; border-color: #b8a990; }}
QPushButton#primary {{
    background: {GREEN};
    color: white; border: 1px solid {GREEN}; border-radius: 8px;
    font-size: 15px; font-weight: 750; padding: 11px 28px;
}}
QPushButton#primary:hover {{
    background: {GREEN_HOVER};
    border-color: {GREEN_HOVER};
}}
QPushButton#primary:pressed {{ background: {GREEN_PRESSED}; border-color: {GREEN_PRESSED}; }}
QPushButton#studioFooterButton {{
    background: {SURFACE}; color: {INK}; border: 1px solid {LINE};
    border-radius: 8px; padding: 11px 24px; min-width: 190px;
    font-size: 15px; font-weight: 750;
}}
QPushButton#studioFooterButton:hover {{ background: {GREEN_SOFT}; border-color: {GREEN}; }}
QPushButton#studioFooterButton:pressed {{ background: {GREEN_SUBTLE}; border-color: {GREEN}; }}
QPushButton#outline {{
    background: transparent;
    border: 1px solid {GREEN};
    color: {GREEN};
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton#outline:hover {{ background: #eef6ea; border-color: #3a6d3e; }}
QPushButton#presetCard {{
    background: #fffdf8;
    color: {INK};
    border: 2px solid #d8cdbc;
    border-radius: 14px;
    padding: 15px 13px;
    min-height: 68px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#presetCard:hover {{
    background: #fbf8f0;
    border-color: #9db092;
}}
QPushButton#presetCard:checked {{
    background: #e4ebdd;
    color: #355f3a;
    border: 2px solid {GREEN};
}}
QPushButton#linkButton {{
    border: 0; background: transparent; color: {GREEN};
    font-weight: 600; padding: 6px 10px; border-radius: 6px;
}}
QPushButton#linkButton:hover {{ background: #eef6ea; color: #3a6d3e; }}
QPushButton:disabled {{ color: #99958d; background: #ece7de; border-color: #d2cbc0; }}
QPushButton#danger {{ color: #8a6524; }}
QPushButton#flat {{ border: 0; background: transparent; padding: 5px; }}
QPushButton#accordionButton {{
    border: 0; background: transparent; text-align: left; padding: 8px 12px;
    font-size: 14px; font-weight: 600;
}}
QPushButton#accordionButton:hover {{ background: rgba(196, 171, 131, 0.12); }}
QWidget#accordionHeader {{ border-radius: 10px; }}
QWidget#accordionHeader:hover {{ background: rgba(196, 171, 131, 0.14); }}
QLabel#accordionSummary {{ color: #8a857a; font-size: 12px; }}
QLabel#brand {{ font-size: 22px; font-weight: {WEIGHT_SCALE['heavy']}; padding: 4px 7px; border-radius: 8px; }}
QLabel#brand:hover {{ background: #eee7d9; color: #365f3a; }}
QLabel#title {{ font-size: 16px; font-weight: 600; }}
QLabel#sectionTitle {{
    color: {INK};
    font-size: 24px; font-weight: {WEIGHT_SCALE['heavy']};
    padding: 0;
}}
QLabel#muted {{ color: {MUTED}; font-size: 13px; font-weight: 500; }}
QLabel#statusGood {{ color: {GREEN}; font-weight: 600; }}
QLabel#statusWarn {{ color: {AMBER}; font-weight: 600; }}
QLabel#statusBad {{ color: {CORAL}; font-weight: 700; }}
QProgressBar {{
    background: #e4dccf; border: 0; border-radius: 7px; height: 14px; text-align: center;
}}
QProgressBar::chunk {{ background: {GREEN}; border-radius: 7px; }}
QScrollArea, QWidget#qt_scrollarea_viewport, QWidget#settingsPage {{
    border: 0; background: {IVORY};
}}
QScrollBar:vertical {{
    background: #eee7dc; width: 10px; margin: 0; border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: #b9ad9d; min-height: 36px; border-radius: 5px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""
