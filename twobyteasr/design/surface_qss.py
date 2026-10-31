"""Token-authored application surfaces. No warm-literal substitution."""
from .tokens import RADIUS_SCALE, TYPE_SCALE, WEIGHT_SCALE
from .typography import TITLE_FONT_STACK, UI_FONT_STACK


def build_surface_qss(t):
    from .semantic_qss import build_semantic_qss
    from .home_qss import build_home_qss
    return _build_surface_qss(t) + build_semantic_qss(t) + build_home_qss(t)


def _header_navigation_qss(t):
    """Header buttons (2026-10-23, home design A): tonal fills, no outline.
    字幕工作台 and 模型工坊 take the accent tint; 检查更新, 设置, 说明 and the
    language menu a quiet neutral one; 支持我 the Studio pink."""
    from .ui_theme import blend_hex
    light = t.is_light

    def tone(color, rest, dark):
        return blend_hex(t.surface, color, rest if light else dark)
    nav, nav_hover, nav_down = tone(t.accent, 0.11, 0.16), tone(t.accent, 0.17, 0.23), tone(t.accent, 0.23, 0.29)
    quiet, quiet_hover, quiet_down = tone(t.text, 0.055, 0.07), tone(t.text, 0.1, 0.12), tone(t.text, 0.14, 0.16)
    studio = t.zone_colors.get("studio", t.accent)
    pink, pink_hover = tone(studio, 0.14, 0.18), tone(studio, 0.2, 0.25)
    chevron = tone(t.accent, 0.15, 0.22)
    nav_sel = 'QPushButton#softAction[homeNavigation="true"]'
    quiet_sel = nav_sel + '[homeTone="quiet"]'
    return f"""
{nav_sel}, QPushButton#supportEntry {{ min-height: 38px; max-height: 38px; padding: 0 14px;
    border-radius: 12px; font-size: 14px; font-weight: 600; background: {nav};
    border: 1px solid transparent; color: {t.text}; }}
{nav_sel}:hover {{ background: {nav_hover}; }}
{nav_sel}:pressed {{ background: {nav_down}; }}
{quiet_sel} {{ background: {quiet}; }}
{quiet_sel}:hover {{ background: {quiet_hover}; }}
{quiet_sel}:pressed {{ background: {quiet_down}; }}
QPushButton#supportEntry {{ background: {pink}; }}
QPushButton#supportEntry:hover, QPushButton#supportEntry:pressed {{ background: {pink_hover}; }}
{nav_sel}:focus, QPushButton#supportEntry:focus {{ border-color: {t.focus}; }}
QComboBox#headerLanguage {{ background: {quiet}; color: {t.text}; border: 1px solid transparent; border-radius: 12px;
    min-height: 38px; max-height: 38px; padding: 0 6px 0 13px; font-size: 14px; font-weight: 600; }}
QComboBox#headerLanguage:hover, QComboBox#headerLanguage:on {{ background: {quiet_hover}; border-color: transparent; }}
QComboBox#headerLanguage:focus {{ background: {quiet}; border: 1px solid {t.focus}; }}
QComboBox#headerLanguage::drop-down {{ subcontrol-origin: content; subcontrol-position: center right;
    width: 24px; height: 24px; border-radius: 11px; background: {chevron}; border: 0; }}
"""


def _build_surface_qss(t):
    from ..app.home_studio_entry import studio_paper_colors
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
QFrame#dialogSurfaceHeader {{ background: transparent; border: 0; border-bottom: 1px solid {t.border}; }}
QLabel#dialogSurfaceTitle {{ color: {t.text}; font-family: {UI_FONT_STACK}; font-size: 16px; font-weight: {WEIGHT_SCALE['semibold']}; background: transparent; }}
QWidget#dialogSurfaceBody, QFrame#dialogSurfaceFooter {{ background: transparent; color: {t.text}; border: 0; }}
QFrame#dialogSurfaceFooter {{ border-top: 1px solid {t.border}; }}
QFrame#studioToolbar {{ background: {t.shell}; border: 0; border-bottom: 1px solid {t.shell_border}; }}
QFrame#contextPanel, QFrame#cueListPanel {{ background: {t.panel}; border: 0; border-left: 1px solid {t.border}; }}
QFrame#contextCard, QFrame#styleSection {{ background: {t.panel}; border: 0; border-top: 1px solid {t.border}; border-radius: 0; }}
QFrame#contextPanel QGroupBox {{ background: transparent; border: 0; border-top: 1px solid {t.border};
    border-radius: 0; margin-top: 20px; padding: 16px 0 8px; font-weight: 600; color: {t.text}; }}
QFrame#contextPanel QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;
    left: 0; padding: 0; color: {t.text}; }}
/* 2026-10-23: the 视频 panel (design C) is styled in design/soft_qss.py. */
QFrame#timelineHost {{ background: {t.timeline}; border: 0; border-top: 1px solid {t.border}; }}
QLabel#projectLibraryBrand {{ font-family: {TITLE_FONT_STACK}; font-size: {TYPE_SCALE['display']}px; font-weight: {WEIGHT_SCALE['heavy']}; }}
QLabel#projectLibraryTitle {{ font-family: {TITLE_FONT_STACK}; font-size: {TYPE_SCALE['heading1']}px; font-weight: {WEIGHT_SCALE['heavy']}; }}
QLabel#resumeProjectTitle {{ font-family: {TITLE_FONT_STACK}; font-size: {TYPE_SCALE['display']}px; font-weight: {WEIGHT_SCALE['heavy']}; }}
QLabel#projectCardTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#projectCardMeta, QLabel#resumeProjectMeta {{ font-size: 12px; font-weight: 400; color: {t.text_secondary}; }}
QToolButton#recentProjectCard, QFrame#resumeProjectCard {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {r['surface']}px; }}
QToolButton#recentProjectCard:hover {{ background: {t.surface_elevated}; border-color: {t.border_strong}; }}
QToolButton#recentProjectCard:focus {{ border: 2px solid {t.focus}; }}
QToolButton#recentProjectCard:checked {{ background: {t.accent_soft}; border: 2px solid {t.accent}; }}
QToolButton#recentProjectCard:checked:hover {{ background: {t.accent_soft}; border: 2px solid {t.accent}; }}
QToolButton#projectListRow:checked {{ background: {t.accent_soft}; border: 1px solid {t.accent}; }}
QFrame#libraryManageBar {{ background: {t.surface}; border: 1px solid {t.accent}; border-radius: {r['surface']}px; }}
QLabel#libraryManageCount {{ font-size: 13px; font-weight: 700; color: {t.text}; }}
QPushButton#libraryManageAction {{ min-height: 34px; padding: 0 16px; border-radius: {r['control']}px;
    background: {t.panel}; color: {t.text}; border: 1px solid {t.border_strong}; font-weight: 600; }}
QPushButton#libraryManageAction:hover {{ background: {t.selected}; border-color: {t.text_muted}; color: {t.text}; }}
QPushButton#libraryManageDanger {{ min-height: 34px; padding: 0 16px; border-radius: {r['control']}px;
    background: {t.danger_soft}; color: {t.danger}; border: 1px solid {t.danger}; font-weight: 700; }}
QPushButton#libraryManageDanger:hover {{ background: {t.danger}; color: {t.surface}; }}
QPushButton#libraryManageDanger:disabled {{ color: {t.disabled}; border-color: {t.border}; background: {t.panel}; }}
QTabWidget#contextDrawer QTabBar::tab {{ min-width: 36px; max-width: 88px; min-height: 32px; padding: 2px 4px; font-size: 12px; }}
QTabWidget#contextDrawer[tabMode="icon"] QTabBar::tab {{ min-width: 36px; max-width: 44px; min-height: 32px; padding: 2px 4px; }}
QFrame#settingsSurface {{ background: transparent; border: 0; border-radius: 0; }}
{_header_navigation_qss(t)}
QFrame#studioEntryCard {{ background: {paper}; border: 1px solid {paper_edge}; border-radius: 20px; }}
QFrame#studioEntryCard:hover {{ background: {paper_hover}; border-color: {paper_muted}; }}
QFrame#studioEntryCard:focus {{ border: 2px solid {paper_muted}; }}
QLabel#studioEntryEyebrow {{ color: {paper_muted}; font-size: 12px; font-weight: 500;
    background: transparent; border: 0; }}
QLabel#studioEntryTitle {{ font-family: {TITLE_FONT_STACK}; color: {paper_ink}; font-size: 22px; font-weight: 800; }}
QLabel#studioEntryHint {{ color: {paper_muted}; font-size: 13px; font-weight: 500; background: transparent; }}
QFrame#studioEntryCard QPushButton#studioEntryPrimary {{ background: {paper_hover}; color: {paper_ink}; border: 1px solid {paper_edge}; border-radius: 10px;
    min-height: 44px; font-size: 15px; font-weight: 600; padding: 0 12px; }}
QFrame#studioEntryCard QPushButton#studioEntryPrimary:hover {{ background: {paper}; border-color: {paper_muted}; }}
QPushButton#primary[homeGenerate="true"][buttonRole="primary"] {{ min-height: 56px; max-height: 56px; padding: 0 32px;
    border-radius: 12px; border: 1px solid {t.accent};
    font-family: {UI_FONT_STACK}; font-size: 18px; font-weight: 600;
    background: {t.accent}; color: {t.text_on_accent}; }}
QPushButton#primary[homeGenerate="true"][buttonRole="primary"]:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QPushButton#primary[homeGenerate="true"][buttonRole="primary"]:pressed {{ background: {t.accent_pressed}; border-color: {t.accent_pressed}; }}
QPushButton#primary[homeGenerate="true"][buttonRole="primary"]:focus {{ border: 2px solid {t.focus}; }}
QPushButton#primary[homeGenerate="true"][buttonRole="primary"]:disabled {{ background: {t.panel};
    color: {t.disabled}; border-color: {t.border}; }}
/* 四十九轮：#homeContentProfile/#recognitionRoleCard/#accordion 三组选择器曾把
   识别首页从无边框通栏布局改成 boxed 卡片并钳制图标尺寸（用户"主页变丑"），
   已摘除；识别首页外观归 ui.py 内联 QSS 所有，勿在此文件重建。 */
QFrame#workshopContent {{ background: transparent; border: 0; }}
QFrame#workshopSidebar, QFrame#workshopDetail {{ background: {t.panel}; border: 0; border-radius: {r['surface']}px; }}
QFrame#workshopComboCard, QFrame#workshopHealthCard {{ background: transparent; border: 0; border-top: 1px solid {t.border}; border-radius: 0; }}
QFrame#workshopModelCard {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {r['surface']}px; }}
QFrame#workshopModelCard[selected="true"] {{ background: {t.surface}; border-color: {t.accent}; }}
QLabel#workshopStateBadge[tone="ready"] {{ background: {t.success_soft}; color: {t.success}; border: 0; }}
QLabel#workshopStateBadge[tone="missing"], QLabel#workshopStateBadge[tone="muted"] {{
    background: {t.surface_elevated}; color: {t.text_secondary}; border: 0; }}
QLabel#workshopRecommendationBadge, QLabel#recTag {{ background: {t.info_soft}; color: {t.info}; border: 0; }}
QLabel#workshopBadge {{ background: {t.surface_elevated}; color: {t.text_secondary}; border: 0; }}
QDialog#shortcutSettings QTableWidget {{ background: {t.surface}; border: 0; }}
QDialog#shortcutSettings QHeaderView::section {{ background: {t.panel}; color: {t.text_secondary}; border: 0; border-bottom: 1px solid {t.border}; padding: 8px; }}
QDialog#shortcutSettings QKeySequenceEdit {{ background: {t.input_surface}; border: 1px solid {t.border}; border-radius: {r['small']}px; min-height: 24px; padding: 0 6px; }}
QPushButton#workshopCardUninstall {{ color: {t.text_secondary}; background: transparent; border: 1px solid {t.border}; border-radius: {r['control']}px; }}
QPushButton#workshopCardUninstall:hover {{ color: {t.text}; background: {t.selected}; border-color: {t.accent}; }}
QPushButton#workshopCardUninstall:disabled {{ color: {t.disabled}; border-color: {t.border}; }}
"""
