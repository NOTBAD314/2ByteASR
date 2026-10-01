"""Token-authored application surfaces. No warm-literal substitution."""
from .tokens import RADIUS_SCALE, TYPE_SCALE, WEIGHT_SCALE
from ..typography import TITLE_FONT_STACK, UI_FONT_STACK


def build_surface_qss(t):
    from ..home_studio_entry import studio_paper_colors
    paper, paper_hover, paper_edge, paper_ink, paper_muted = studio_paper_colors(t)
    r=RADIUS_SCALE
    return f"""
QLabel[typography="title"] {{ font-family: {TITLE_FONT_STACK}; font-size: {TYPE_SCALE['heading1']}px; font-weight: {WEIGHT_SCALE['heavy']}; color: {t.text}; }}
QLabel[typography="section"] {{ font-family: {UI_FONT_STACK}; font-size: {TYPE_SCALE['section']}px; font-weight: {WEIGHT_SCALE['semibold']}; color: {t.text}; }}
QLabel[typography="meta"] {{ font-family: {UI_FONT_STACK}; font-size: {TYPE_SCALE['small']}px; font-weight: {WEIGHT_SCALE['regular']}; color: {t.text_muted}; }}
QDialog#applicationSettings {{ background: {t.app_background}; color: {t.text}; }}
QFrame#settingsHeader, QFrame#settingsFooter {{ background: {t.app_background}; border: 0; }}
QFrame#settingsHeader {{ border-bottom: 1px solid {t.border}; }}
QFrame#settingsFooter {{ border-top: 1px solid {t.border}; }}
QListWidget#settingsNavigation {{ background: {t.app_background}; border: 0; padding: 8px; }}
QListWidget#settingsNavigation::item {{ height: 36px; padding: 0 12px; border-radius: {r['control']}px; color: {t.text_secondary}; }}
QListWidget#settingsNavigation::item:selected {{ background: {t.accent_soft}; color: {t.text}; border: 0; }}
QWidget#settingsPage, QScrollArea#settingsScroll, QWidget#settingsViewport {{ background: {t.surface}; }}
QFrame#settingsSection {{ background: transparent; border: 0; border-top: 1px solid {t.border}; border-radius: 0; }}
QLabel#settingsDescription {{ color: {t.text_secondary}; font-size: 13px; font-weight: 500; }}
QLabel#settingsRowTitle {{ color: {t.text}; font-size: 13px; font-weight: 500; }}
QLabel#buildIdentityLabel {{ background: {t.panel}; color: {t.text_secondary}; padding: 16px;
    border: 1px solid {t.border}; border-radius: {r['control']}px; font-size: 12px; font-weight: 400; }}
QFrame#dialogSurface {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {r['modal']}px; }}
QFrame#dialogSurfaceHeader {{ background: {t.surface}; border: 0; border-bottom: 1px solid {t.border}; }}
QLabel#dialogSurfaceTitle {{ color: {t.text}; font-family: {UI_FONT_STACK}; font-size: 16px; font-weight: {WEIGHT_SCALE['semibold']}; background: transparent; }}
QWidget#dialogSurfaceBody, QFrame#dialogSurfaceFooter {{ background: {t.surface}; color: {t.text}; border: 0; }}
QFrame#dialogSurfaceFooter {{ border-top: 1px solid {t.border}; }}
QFrame#studioToolbar {{ background: {t.shell}; border: 0; border-bottom: 1px solid {t.shell_border}; }}
QFrame#contextPanel, QFrame#cueListPanel {{ background: {t.panel}; border: 0; border-left: 1px solid {t.border}; }}
QFrame#contextCard, QFrame#styleSection {{ background: {t.panel}; border: 0; border-top: 1px solid {t.border}; border-radius: 0; }}
QFrame#contextPanel QGroupBox {{ background: transparent; border: 0; border-top: 1px solid {t.border};
    border-radius: 0; margin-top: 20px; padding: 16px 0 8px; font-weight: 600; color: {t.text}; }}
QFrame#contextPanel QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;
    left: 0; padding: 0; color: {t.text}; }}
QWidget#videoInspector QLabel, QWidget#videoInspector QGroupBox,
QWidget#videoInspector QDoubleSpinBox, QWidget#videoInspector QComboBox,
QWidget#videoInspector QCheckBox {{ font-family: {UI_FONT_STACK}; font-weight: 600; color: {t.text}; }}
QWidget#videoInspector QLabel#videoSelectionSummary {{ background: {t.accent_soft};
    border-radius: 9px; padding: 10px; font-size: 12px; color: {t.text}; }}
QWidget#videoInspector QLabel#videoAxisLabel {{ color: {t.text_secondary}; font-size: 11px; min-width: 10px; }}
QWidget#videoInspector QGroupBox#videoInspectorSection {{ background: {t.surface};
    border: 1px solid {t.border}; border-radius: 12px; margin-top: 16px; padding: 14px 0 8px;
    font-weight: 700; }}
QWidget#videoInspector QGroupBox#videoInspectorSection::title {{ left: 12px; padding: 0 5px; }}
QWidget#videoInspector QDoubleSpinBox, QWidget#videoInspector QComboBox {{ font-weight: 600;
    background: {t.app_background}; border: 1px solid {t.border_strong}; border-radius: 7px; }}
QWidget#videoInspector QDoubleSpinBox:hover, QWidget#videoInspector QComboBox:hover {{ border-color: {t.text_secondary}; }}
QWidget#videoInspector QDoubleSpinBox:focus, QWidget#videoInspector QComboBox:focus {{ border: 1px solid {t.accent}; }}
QWidget#videoInspector QToolButton#videoScaleLink {{ border: 0; border-radius: 7px; background: transparent; }}
QWidget#videoInspector QToolButton#videoScaleLink:checked {{ background: {t.accent_soft}; }}
QWidget#videoInspector QLabel#contextEmpty {{ color: {t.text_secondary}; font-weight: 500; font-size: 11px; }}
QFrame#timelineHost {{ background: {t.timeline}; border: 0; border-top: 1px solid {t.border}; }}
QLabel#projectLibraryBrand {{ font-family: {TITLE_FONT_STACK}; font-size: {TYPE_SCALE['display']}px; font-weight: {WEIGHT_SCALE['heavy']}; }}
QLabel#projectLibraryTitle {{ font-family: {TITLE_FONT_STACK}; font-size: {TYPE_SCALE['heading1']}px; font-weight: {WEIGHT_SCALE['heavy']}; }}
QLabel#resumeProjectTitle {{ font-family: {TITLE_FONT_STACK}; font-size: {TYPE_SCALE['display']}px; font-weight: {WEIGHT_SCALE['heavy']}; }}
QLabel#projectCardTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#projectCardMeta, QLabel#resumeProjectMeta {{ font-size: 12px; font-weight: 400; color: {t.text_secondary}; }}
QToolButton#recentProjectCard, QFrame#resumeProjectCard {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {r['surface']}px; }}
QToolButton#recentProjectCard:hover {{ background: {t.surface}; border-color: {t.accent}; }}
QToolButton#recentProjectCard:focus {{ border: 2px solid {t.accent}; }}
QToolButton#recentProjectCard:checked {{ background: {t.accent_soft}; border: 2px solid {t.accent}; }}
QToolButton#recentProjectCard:checked:hover {{ background: {t.accent_soft}; border: 2px solid {t.accent}; }}
QToolButton#projectListRow:checked {{ background: {t.accent_soft}; border: 1px solid {t.accent}; }}
QFrame#libraryManageBar {{ background: {t.surface}; border: 1px solid {t.accent}; border-radius: {r['surface']}px; }}
QLabel#libraryManageCount {{ font-size: 13px; font-weight: 700; color: {t.text}; }}
QPushButton#libraryManageAction {{ min-height: 34px; padding: 0 16px; border-radius: {r['control']}px;
    background: {t.panel}; color: {t.text}; border: 1px solid {t.border_strong}; font-weight: 600; }}
QPushButton#libraryManageAction:hover {{ border-color: {t.accent}; color: {t.accent}; }}
QPushButton#libraryManageDanger {{ min-height: 34px; padding: 0 16px; border-radius: {r['control']}px;
    background: {t.danger_soft}; color: {t.danger}; border: 1px solid {t.danger}; font-weight: 700; }}
QPushButton#libraryManageDanger:hover {{ background: {t.danger}; color: {t.surface}; }}
QPushButton#libraryManageDanger:disabled {{ color: {t.disabled}; border-color: {t.border}; background: {t.panel}; }}
QTabWidget#contextDrawer QTabBar::tab {{ min-width: 36px; max-width: 88px; min-height: 32px; padding: 2px 4px; font-size: 12px; }}
QTabWidget#contextDrawer[tabMode="icon"] QTabBar::tab {{ min-width: 36px; max-width: 44px; min-height: 32px; padding: 2px 4px; }}
QFrame#settingsSurface {{ background: transparent; border: 0; border-radius: 0; }}
QPushButton#softAction[homeNavigation="true"] {{ min-height: 38px; padding: 0 16px;
    border-radius: 13px; font-size: 15px; font-weight: 500; background: {t.accent_soft}; }}
QFrame#studioEntryCard {{ background: {paper}; border: 1px solid {paper_edge}; border-radius: 20px; }}
QFrame#studioEntryCard:hover {{ background: {paper_hover}; border-color: {paper_muted}; }}
QFrame#studioEntryCard:focus {{ border: 2px solid {paper_muted}; }}
QLabel#studioEntryEyebrow {{ color: {paper_muted}; font-size: 12px; font-weight: 700;
    background: transparent; border: 0; }}
QLabel#studioEntryTitle {{ font-family: {TITLE_FONT_STACK}; color: {paper_ink}; font-size: 26px; font-weight: 800; }}
QLabel#studioEntryHint {{ color: {paper_muted}; font-size: 13px; font-weight: 600; background: transparent; }}
QFrame#studioEntryCard QPushButton#studioEntryPrimary {{ background: {paper_hover}; color: {paper_ink}; border: 1px solid {paper_edge}; border-radius: 14px;
    min-height: 48px; font-size: 17px; padding: 0 12px; }}
QFrame#studioEntryCard QPushButton#studioEntryPrimary:hover {{ background: {paper}; border-color: {paper_muted}; }}
QPushButton#primary[homeGenerate="true"][buttonRole="primary"] {{ min-height: 64px; padding: 0 30px;
    border-radius: 23px; border: 0; border-bottom: 4px solid {t.accent_pressed};
    font-family: {TITLE_FONT_STACK}; font-size: 23px; font-weight: 800;
    background: {t.accent}; color: {t.text_on_accent}; }}
QPushButton#primary[homeGenerate="true"][buttonRole="primary"]:hover {{ background: {t.accent_hover}; }}
QPushButton#primary[homeGenerate="true"][buttonRole="primary"]:pressed {{ background: {t.accent_pressed};
    border-bottom: 1px solid {t.accent_pressed}; padding-top: 3px; }}
QPushButton#primary[homeGenerate="true"][buttonRole="primary"]:disabled {{ background: {t.accent_soft};
    color: {t.text_secondary}; border-bottom-color: {t.border}; }}
/* 四十九轮：#homeContentProfile/#recognitionRoleCard/#accordion 三组选择器曾把
   识别首页从无边框通栏布局改成 boxed 卡片并钳制图标尺寸（用户"主页变丑"），
   已摘除；识别首页外观归 ui.py 内联 QSS 所有，勿在此文件重建。 */
QFrame#workshopContent {{ background: transparent; border: 0; }}
QFrame#workshopSidebar, QFrame#workshopDetail {{ background: {t.panel}; border: 0; border-radius: {r['surface']}px; }}
QFrame#workshopComboCard, QFrame#workshopHealthCard {{ background: transparent; border: 0; border-top: 1px solid {t.border}; border-radius: 0; }}
QFrame#workshopModelCard {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {r['surface']}px; }}
QFrame#workshopModelCard[selected="true"] {{ background: {t.surface}; border-color: {t.accent}; }}
QDialog#shortcutSettings QTableWidget {{ background: {t.surface}; border: 0; }}
QDialog#shortcutSettings QHeaderView::section {{ background: {t.panel}; color: {t.text_secondary}; border: 0; border-bottom: 1px solid {t.border}; padding: 8px; }}
QDialog#shortcutSettings QKeySequenceEdit {{ background: {t.input_surface}; border: 1px solid {t.border}; border-radius: {r['small']}px; min-height: 24px; padding: 0 6px; }}
QPushButton#workshopCardUninstall {{ color: {t.text_secondary}; background: transparent; border: 1px solid {t.border}; border-radius: {r['control']}px; }}
QPushButton#workshopCardUninstall:hover {{ color: {t.text}; background: {t.selected}; border-color: {t.accent}; }}
QPushButton#workshopCardUninstall:disabled {{ color: {t.disabled}; border-color: {t.border}; }}
"""
