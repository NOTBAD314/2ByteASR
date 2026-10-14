"""Home (recognition setup) page look, 2026-10-08.

Each home block is a module with a low-saturation zone hue (theme.zone_colors):
Studio berry pink / purple-red, AI magenta rose-violet, content & terms
grey-violet leaning cyan — a light tint, a matching edge and icon chip, never
a loud fill. Section titles 19px, field labels 13px, taller primary controls,
a centred hero drop zone while no media is loaded, and a bottom bar that names
what is missing. Appended after the surface sheet so it owns these selectors.
"""
from ..typography import UI_FONT_STACK


def build_home_qss(t):
    from ..ui_theme import blend_hex
    light = t.is_light
    rest, edge_amount, chip_amount = (0.07, 0.36, 0.2) if light else (0.08, 0.3, 0.22)
    zones = t.zone_colors
    tint = {name: blend_hex(t.surface, color, rest) for name, color in zones.items()}
    edge = {name: blend_hex(t.surface, color, edge_amount) for name, color in zones.items()}
    strong = {name: blend_hex(t.surface, color, 0.55) for name, color in zones.items()}
    chip = {name: blend_hex(t.surface, color, chip_amount) for name, color in zones.items()}
    inner = blend_hex(tint["content"], "#ffffff" if light else t.app_background, 0.5 if light else 0.42)
    hero = blend_hex(t.surface, t.accent, 0.07)
    hero_hover = blend_hex(t.surface, t.accent, 0.11)
    hero_edge = blend_hex(t.surface, t.accent_text, 0.5)
    disabled_fill = blend_hex(t.surface, t.accent, 0.12)
    disabled_edge = blend_hex(t.surface, t.accent_text, 0.45)
    return f"""
QFrame#studioEntryCard {{ background: {tint['studio']}; border: 1px solid {edge['studio']}; border-radius: 14px; }}
QFrame#studioEntryCard:hover {{ background: {tint['studio']}; border-color: {strong['studio']}; }}
QFrame#studioEntryCard:focus {{ border: 1px solid {t.focus}; }}
QFrame#studioEntryCard QLabel#homeCardIcon {{ background: {chip['studio']}; border-radius: 11px; }}
QFrame#homeProcessCard {{ background: {tint['ai']}; border: 1px solid {edge['ai']}; border-radius: 14px; }}
QFrame#homeProcessCard[expanded="true"] {{ border-color: {strong['ai']}; }}
QFrame#homeContentProfile {{ background: {tint['content']}; border: 1px solid {edge['content']}; border-radius: 14px; }}
QFrame#homeContentProfile QLabel#homeCardIcon {{ background: {chip['content']}; border-radius: 11px; }}
QLabel#homeSectionTitle {{ color: {t.text}; font-family: {UI_FONT_STACK}; font-size: 19px;
    font-weight: 600; background: transparent; border: 0; }}
QLabel#homeSectionHint {{ color: {t.text_secondary}; font-size: 13px; font-weight: 500; background: transparent; }}
QLabel#homeFieldLabel, QWidget#homePlanBlock QLabel#fieldLabel {{ color: {t.text_secondary};
    font-size: 13px; font-weight: 500; background: transparent; }}
QPushButton#homeHeaderAction {{ background: transparent; color: {t.text_secondary};
    border: 1px solid {t.border}; border-radius: 8px; padding: 0 12px; min-height: 34px;
    font-size: 13px; font-weight: 500; }}
QPushButton#homeHeaderAction:hover {{ background: {t.selected}; color: {t.text}; border-color: {t.border_strong}; }}
QPushButton#homeHeaderAction:focus {{ border-color: {t.focus}; }}
QWidget#homePlanBlock QComboBox#recognitionPlanCombo, QWidget#homePlanBlock QComboBox#projectProfileCombo {{
    min-height: 40px; font-size: 14px; padding: 0 12px; border-radius: 9px; }}
QFrame#homeContentProfile QFrame#homeContentPanel, QFrame#homeContentProfile QFrame#homeBatchGlossary {{
    background: {inner}; border: 1px solid {edge['content']}; border-radius: 12px; }}
QFrame#homeContentProfile QComboBox#homeContentCombo {{ min-height: 44px; font-size: 16px;
    padding: 0 14px; border-radius: 10px; }}
QFrame#homePanelRule {{ background: {edge['content']}; border: 0; }}
QAbstractButton#homeSwitch {{ font-size: 15px; }}
QLabel#homeTermState {{ font-size: 14px; font-weight: 500; color: {t.text_secondary}; background: transparent; }}
QLabel#homeTermState[tone="warn"] {{ color: {t.warning}; }}
QLabel#homeTermState[tone="off"] {{ color: {t.text_muted}; }}
QFrame#homeBatchGlossary QPushButton#glossaryChip {{ min-height: 28px; max-height: 28px; padding: 0 12px;
    border-radius: 14px; font-size: 13px; }}
QLabel#homeQuickCaption {{ color: {t.text_muted}; font-size: 13px; font-weight: 500; background: transparent; }}
QPushButton#contentQuickChip {{ background: {t.surface_elevated}; color: {t.text_secondary};
    border: 1px solid {t.border}; border-radius: 16px; padding: 0 14px; min-height: 32px; max-height: 32px;
    font-size: 14px; font-weight: 500; }}
QPushButton#contentQuickChip:hover {{ color: {t.text}; border-color: {strong['content']}; background: {t.selected}; }}
QPushButton#contentQuickChip:checked {{ background: {chip['content']}; color: {t.text}; border-color: {strong['content']}; }}
QFrame#homeProcessCard QFrame#settingTile, QFrame#homeProcessCard QFrame#settingTile[checked="true"] {{
    background: transparent; border: 0; border-radius: 14px; }}
QFrame#homeProcessCard QFrame#settingTile:hover {{ background: {chip['ai']}; border: 0; }}
QFrame#homeProcessCard QLabel#settingTileIcon {{ background: {chip['ai']}; border-radius: 11px; }}
QFrame#homeProcessCard QLabel#settingTileTitle {{ color: {t.text}; font-size: 19px; font-weight: 600; }}
QFrame#homeProcessCard QLabel#settingTileSummary {{ color: {t.text_secondary}; font-size: 13px; font-weight: 500; }}
QFrame#homeProcessCard QLabel#settingTileChevron {{ background: transparent; }}
QFrame#homeProcessCard QFrame#accordion {{ background: transparent; border: 0; }}
QLabel#homeFactChip {{ border-radius: 8px; padding: 4px 10px; font-size: 13px; font-weight: 500; }}
QLabel#homeFactChip[state="on"] {{ background: {chip['ai']}; color: {t.text}; }}
QLabel#homeFactChip[state="off"] {{ background: transparent; color: {t.text_muted}; border: 1px solid {edge['ai']}; }}
QLabel#homeFactChip[state="warn"] {{ background: {t.warning_soft}; color: {t.warning}; }}
QPushButton#homeAiSettings {{ background: {chip['ai']}; color: {t.text}; border: 1px solid {edge['ai']};
    border-radius: 10px; min-height: 38px; padding: 0 16px; font-size: 14px; font-weight: 600; }}
QPushButton#homeAiSettings:hover {{ border-color: {strong['ai']}; background: {blend_hex(t.surface, zones['ai'], chip_amount + 0.1)}; }}
QDialog#aiSettingsDialog QFrame#aiDialogHeader {{ background: {t.surface}; border: 0; border-bottom: 1px solid {t.border}; }}
QDialog#aiSettingsDialog QFrame#aiDialogFooter {{ background: {t.surface}; border: 0; border-top: 1px solid {t.border}; }}
QDialog#aiSettingsDialog QLabel#aiDialogTitle {{ color: {t.text}; font-size: 20px; font-weight: 600; background: transparent; }}
QDialog#aiSettingsDialog QLabel#aiDialogSubtitle {{ color: {t.text_secondary}; font-size: 13px; background: transparent; }}
QDialog#aiSettingsDialog QScrollArea#aiDialogScroll, QDialog#aiSettingsDialog QWidget#aiDialogBody {{ background: {t.surface}; border: 0; }}
QDialog#aiSettingsDialog QFrame#accordion {{ background: transparent; border: 0; }}
QToolButton#endpointAdvancedToggle {{ background: transparent; border: 0; color: {t.text_secondary};
    font-size: 13px; font-weight: 600; padding: 6px 0; }}
QToolButton#endpointAdvancedToggle:hover {{ color: {t.text}; }}
QFrame#homeFactDivider {{ background: {edge['ai']}; border: 0; }}
QLabel#homeFactCaption {{ color: {t.text_secondary}; font-size: 13px; font-weight: 600; background: transparent; }}
QFrame#studioEntryCard QPushButton#studioEntryPrimary {{ background: {chip['studio']}; color: {t.text};
    border: 1px solid {edge['studio']}; border-radius: 11px; min-height: 46px; max-height: 46px;
    padding: 0 18px; font-size: 15px; font-weight: 600; }}
QFrame#studioEntryCard QPushButton#studioEntryPrimary:hover {{ background: {blend_hex(t.surface, zones['studio'], chip_amount + 0.1)};
    border-color: {strong['studio']}; }}
QFrame#studioEntryCard QPushButton#studioEntryPrimary:focus {{ border-color: {t.focus}; }}
QFrame#mediaRow[empty="true"] {{ background: {hero}; border: 2px dashed {hero_edge}; border-radius: 16px; }}
QFrame#mediaRow[empty="true"]:hover {{ background: {hero_hover}; border-color: {t.accent_text}; }}
QFrame#mediaRow[empty="true"] QLabel#mediaIcon {{ border-radius: 18px; background: {t.accent_tint}; }}
QFrame#mediaRow[empty="false"] {{ border-radius: 12px; }}
QLabel#mediaFormats {{ color: {t.text_muted}; font-size: 12px; font-weight: 500; background: transparent; }}
QFrame#mediaRow QPushButton#softAction[heroAction="true"] {{ background: {t.accent}; color: {t.text_on_accent};
    border: 1px solid {t.accent}; border-radius: 10px; min-height: 44px; padding: 0 24px;
    font-size: 15px; font-weight: 600; }}
QFrame#mediaRow QPushButton#softAction[heroAction="true"]:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QFrame#mediaRow QPushButton#softAction[heroAction="true"]:pressed {{ background: {t.accent_pressed}; }}
QFrame#actionBar QLabel#statusGood, QFrame#actionBar QLabel#statusWarn {{ font-size: 14px; font-weight: 600; }}
QPushButton#readinessChip {{ border-radius: 15px; padding: 0 14px; min-height: 30px; max-height: 30px;
    font-size: 13px; font-weight: 600; }}
QPushButton#readinessChip[kind="media"] {{ background: {t.accent_tint}; color: {t.accent_text};
    border: 1px solid {blend_hex(t.surface, t.accent_text, 0.4)}; }}
QPushButton#readinessChip[kind="media"]:hover {{ border-color: {t.accent_text}; }}
QPushButton#readinessChip[kind="plan"] {{ background: {t.warning_soft}; color: {t.warning};
    border: 1px solid {blend_hex(t.surface, t.warning, 0.4)}; }}
QPushButton#readinessChip[kind="plan"]:hover {{ border-color: {t.warning}; }}
QPushButton#startHint {{ font-size: 14px; font-weight: 600; color: {t.accent_text}; background: transparent;
    border: 1px solid transparent; border-radius: 15px; padding: 0 12px; min-height: 30px; max-height: 30px; }}
QPushButton#startHint:hover {{ background: {t.accent_tint}; border-color: {blend_hex(t.surface, t.accent_text, 0.4)}; }}
QPushButton#startHint[tone="warn"] {{ color: {t.warning}; }}
QPushButton#startHint[tone="warn"]:hover {{ background: {t.warning_soft}; border-color: {blend_hex(t.surface, t.warning, 0.4)}; }}
QPushButton#primary[homeGenerate="true"][buttonRole="primary"]:disabled {{ background: {disabled_fill};
    color: {t.text_secondary}; border: 1px dashed {disabled_edge}; }}
"""
