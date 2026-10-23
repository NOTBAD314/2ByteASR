"""Home (recognition setup) page look, 2026-10-08.

Each home block is a module with a low-saturation zone hue (theme.zone_colors):
Studio berry pink / purple-red, AI magenta rose-violet, content & terms
grey-violet leaning cyan — a light tint, a matching edge and icon chip, never
a loud fill. Section titles 19px, field labels 13px, taller primary controls,
a centred hero drop zone while no media is loaded, and a bottom bar that names
what is missing. Appended after the surface sheet so it owns these selectors.
"""
from .typography import UI_FONT_STACK

# 2026-10-22 (user): while no AI is connected the AI card and 内容与术语 are
# blue-grey (the first draft's sand "跟紫色背景不搭"): a steel blue mixed into
# each theme's own surface, quiet on the purple themes and the light ones alike.
AI_LOCK_HUE = "#7c9cbd"


def ai_lock_palette(t) -> dict[str, str]:
    """The blue-grey of the locked AI zone for theme ``t`` (QSS and the frosted overlay share it)."""
    from .ui_theme import blend_hex
    light = t.is_light
    return {
        "band": blend_hex(t.surface, AI_LOCK_HUE, 0.11 if light else 0.08),
        "band_edge": blend_hex(t.surface, AI_LOCK_HUE, 0.34 if light else 0.26),
        "card": blend_hex(t.surface, AI_LOCK_HUE, 0.17 if light else 0.13),
        "edge": blend_hex(t.surface, AI_LOCK_HUE, 0.48 if light else 0.40),
        "edge_strong": blend_hex(t.surface, AI_LOCK_HUE, 0.72 if light else 0.62),
        "chip": blend_hex(t.surface, AI_LOCK_HUE, 0.28 if light else 0.25),
        "title": blend_hex(t.text, AI_LOCK_HUE, 0.42 if light else 0.38),
        "text": blend_hex(t.text_secondary, AI_LOCK_HUE, 0.30),
        "frost": blend_hex(t.surface, AI_LOCK_HUE, 0.20 if light else 0.14),
    }


def _ai_card_rules(t, zones, strong, chip_amount) -> str:
    """The home AI card (design B) and the locked zone around it (2026-10-22)."""
    from .ui_theme import blend_hex
    light = t.is_light
    lock = ai_lock_palette(t)
    card = blend_hex(t.surface, zones["ai"], 0.13 if light else 0.09)
    card_edge = blend_hex(t.surface, zones["ai"], 0.42 if light else 0.32)
    good = blend_hex(t.surface, t.success, 0.18 if light else 0.16)
    return f"""
QFrame#homeProcessCard[aiLock="true"] {{ background: {lock['band']}; border-top: 1px solid {lock['band_edge']}; }}
QFrame#homeAiCard {{ background: {card}; border: 1px solid {card_edge}; border-radius: 14px; }}
QFrame#homeAiCard:hover {{ border-color: {strong['ai']}; }}
QFrame#homeAiCard:focus {{ border-color: {t.focus}; }}
QFrame#homeAiCard[aiLock="true"] {{ background: {lock['card']}; border-color: {lock['edge']}; }}
QFrame#homeAiCard[aiLock="true"]:hover {{ border-color: {lock['edge_strong']}; }}
QFrame#homeAiCard[aiLock="true"]:focus {{ border-color: {t.focus}; }}
QLabel#homeAiRole {{ color: {blend_hex(t.text, zones['ai'], 0.55)}; font-size: 13px; font-weight: 700; background: transparent; }}
QFrame#homeAiCard[aiLock="true"] QLabel#homeAiRole {{ color: {lock['title']}; }}
QLabel#homeAiIcon {{ background: {t.accent}; border-radius: 15px; }}
QFrame#homeAiCard[aiLock="true"] QLabel#homeAiIcon {{ background: {lock['chip']}; }}
QLabel#homeAiTitle {{ color: {t.text}; font-family: {UI_FONT_STACK}; font-size: 20px; font-weight: 700; background: transparent; }}
QLabel#homeAiSummary {{ color: {t.text_secondary}; font-size: 13px; font-weight: 500; background: transparent; }}
QFrame#homeAiCard[aiLock="true"] QLabel#homeAiSummary {{ color: {lock['text']}; }}
QWidget#homeAiFeatures {{ background: transparent; }}
QLabel#homeAiState {{ border-radius: 7px; padding: 2px 9px; font-size: 12px; font-weight: 700; }}
QLabel#homeAiState[state="ready"] {{ background: {good}; color: {t.success}; }}
QLabel#homeAiState[state="lock"] {{ background: {lock['chip']}; color: {lock['title']}; }}
QLabel#homeAiState[state="warn"] {{ background: {t.warning_soft}; color: {t.warning}; }}
QLabel#homeAiFeature {{ border-radius: 6px; padding: 2px 9px; font-size: 12px; font-weight: 600; }}
QLabel#homeAiFeature[on="true"] {{ background: {good}; color: {t.success}; }}
QLabel#homeAiFeature[on="false"] {{ background: transparent; color: {t.text_muted}; border: 1px solid {t.border}; }}
QPushButton#homeAiSettings {{ background: {blend_hex(t.surface, zones['ai'], chip_amount)}; color: {t.text};
    border: 1px solid {card_edge}; border-radius: 10px; min-height: 38px; padding: 0 16px; font-size: 14px; font-weight: 600; }}
QPushButton#homeAiSettings:hover {{ border-color: {strong['ai']}; background: {blend_hex(t.surface, zones['ai'], chip_amount + 0.1)}; }}
QFrame#homeAiCard[aiLock="true"] QPushButton#homeAiSettings {{ background: {lock['chip']}; border-color: {lock['edge']}; }}
QFrame#homeAiCard[aiLock="true"] QPushButton#homeAiSettings:hover {{ border-color: {lock['edge_strong']}; }}
QPushButton#homeAiPrimary {{ min-height: 40px; padding: 0 20px; font-size: 15px; font-weight: 700; border-radius: 10px; }}
QFrame#homeContentProfile[aiLock="true"] {{ background: {lock['band']}; border-top: 1px solid {lock['band_edge']}; }}
QFrame#homeContentProfile[aiLock="true"] QLabel#homeSectionTitle {{ color: {t.text_muted}; }}
QFrame#homeContentProfile[aiLock="true"] QLabel#homeCardIcon {{ background: {lock['chip']}; }}
QFrame#homeContentProfile[aiLock="true"] QFrame#homePanelRule {{ background: {lock['band_edge']}; }}
QWidget#homeContentBody {{ background: transparent; }}
QDialog#aiSettingsDialog QLabel#aiDialogState {{ border-radius: 7px; padding: 2px 10px; font-size: 12px; font-weight: 700; }}
QDialog#aiSettingsDialog QLabel#aiDialogState[state="ready"] {{ background: {good}; color: {t.success}; }}
QDialog#aiSettingsDialog QLabel#aiDialogState[state="lock"] {{ background: {lock['chip']}; color: {lock['title']}; }}
QDialog#aiSettingsDialog QLabel#aiDialogState[state="warn"] {{ background: {t.warning_soft}; color: {t.warning}; }}
QDialog#aiSettingsDialog QLabel#aiSectionTitle {{ color: {t.text}; font-size: 15px; font-weight: 700; background: transparent; padding-top: 2px; }}
QDialog#aiSettingsDialog QFrame#aiAdvancedBox {{
    background: {blend_hex(t.surface, t.text, 0.03 if light else 0.025)}; border: 1px solid {t.border}; border-radius: 12px; }}
QDialog#aiSettingsDialog QFrame#aiAdvancedRule {{ background: {t.border}; border: 0; }}
QFrame#aiGuide {{ background: {blend_hex(t.surface, t.accent, 0.12 if light else 0.10)}; border: 1px solid {blend_hex(t.surface, t.accent, 0.4 if light else 0.32)}; border-radius: 12px; }}
QFrame#aiGuide[state="untested"], QFrame#aiGuide[state="failed"], QFrame#aiGuide[state="off"] {{
    background: {blend_hex(t.surface, t.text, 0.04 if light else 0.03)}; border-color: {t.border}; }}
QFrame#aiGuide[state="ready"] {{ background: {blend_hex(t.surface, t.success, 0.12 if light else 0.09)}; border-color: {blend_hex(t.surface, t.success, 0.4 if light else 0.3)}; }}
QFrame#aiGuide QLabel {{ background: transparent; }}
QLabel#aiGuideEyebrow {{ color: {t.accent_text}; font-size: 12px; font-weight: 700; }}
QFrame#aiGuide[state="ready"] QLabel#aiGuideEyebrow {{ color: {t.success}; }}
QFrame#aiGuide[state="failed"] QLabel#aiGuideEyebrow {{ color: {t.warning}; }}
QLabel#aiGuideHeading {{ color: {t.text}; font-size: 16px; font-weight: 700; }}
QLabel#aiGuideText {{ color: {t.text_secondary}; font-size: 13px; }}
QLabel#aiGuideStep {{ color: {t.text}; font-size: 13px; }}
QLabel#aiGuideStep[step="next"] {{ color: {t.text_muted}; }}
QLabel#aiGuideBadge {{ border-radius: 10px; font-size: 11px; font-weight: 700; }}
QLabel#aiGuideBadge[step="now"] {{ background: {t.accent}; color: {t.text_on_accent}; }}
QLabel#aiGuideBadge[step="next"] {{ background: {blend_hex(t.surface, t.text, 0.12)}; color: {t.text_muted}; }}
QLabel#aiGuideBadge[step="done"] {{ background: {t.success}; }}
QLabel#aiGuideBadge[step="plain"] {{ background: transparent; }}
QFrame#aiGuide QWidget#aiGuideSteps, QFrame#aiGuide QWidget#aiWin {{ background: transparent; }}
QLabel#aiWinEyebrow {{ color: {t.success}; font-size: 12px; font-weight: 700; }}
QLabel#aiWinHeading {{ color: {t.text}; font-size: 17px; font-weight: 700; }}
QLabel#aiWinMeta {{ color: {t.text_secondary}; font-size: 12px; }}
QLabel#aiWinCaption {{ color: {t.text_secondary}; font-size: 12px; font-weight: 700; }}
QFrame#aiWinTile {{ background: {blend_hex(t.surface, t.success, 0.17 if light else 0.14)};
    border: 1px solid {blend_hex(t.surface, t.success, 0.4 if light else 0.32)}; border-radius: 10px; }}
QFrame#aiWinTile[on="false"] {{ background: transparent; border: 1px dashed {t.border}; }}
QLabel#aiWinTileIcon {{ background: {blend_hex(t.surface, t.success, 0.28 if light else 0.24)}; border-radius: 7px; }}
QFrame#aiWinTile[on="false"] QLabel#aiWinTileIcon {{ background: {blend_hex(t.surface, t.text, 0.08)}; }}
QLabel#aiWinTileName {{ color: {t.text}; font-size: 13px; font-weight: 650; }}
QFrame#aiWinTile[on="false"] QLabel#aiWinTileName {{ color: {t.text_muted}; font-weight: 500; }}
QLabel#aiWinTileUse {{ color: {t.text_secondary}; font-size: 12px; }}
QFrame#aiWinTile[on="false"] QLabel#aiWinTileUse {{ color: {t.text_muted}; }}
QFrame#aiWinNext {{ background: transparent; border: 0; border-top: 1px solid {blend_hex(t.surface, t.success, 0.32)}; }}
QLabel#aiWinNextText {{ color: {t.text}; font-size: 13px; }}
QDialog#aiSettingsDialog QPushButton[aiDialogAction="true"] {{ min-height: 46px; max-height: 46px; padding: 0 20px;
    font-size: 14px; font-weight: 650; }}
QDialog#aiSettingsDialog QPushButton#helpLink[emphasis="primary"] {{ color: {t.text_on_accent}; background: {t.accent};
    border: 1px solid {t.accent}; border-radius: 10px; min-height: 42px; padding: 0 14px; font-size: 14px; font-weight: 650; }}
QDialog#aiSettingsDialog QPushButton#helpLink[emphasis="primary"]:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QDialog#aiSettingsDialog QPushButton#helpLink[emphasis="secondary"] {{ color: {t.text}; background: {t.control_background};
    border: 1px solid {t.border}; border-radius: 10px; min-height: 42px; padding: 0 14px; font-size: 14px; font-weight: 600; }}
QDialog#aiSettingsDialog QPushButton#helpLink[emphasis="secondary"]:hover {{ background: {t.control_hover}; border-color: {t.border_strong}; }}
QDialog#aiSettingsDialog QLabel#aiAdvancedSummary {{ color: {t.text_muted}; font-size: 13px; background: transparent; }}
QDialog#aiSettingsDialog QLabel#aiDutyNote {{ color: {t.text_muted}; font-size: 12px; background: transparent; }}
QDialog#aiSettingsDialog QToolButton#endpointAdvancedToggle {{ font-size: 14px; color: {t.text}; }}
QLabel#homeFrostNote {{ background: transparent; color: {t.text}; font-size: 18px; font-weight: 700; }}
QLabel#homeFrostSub {{ background: transparent; color: {lock['text']}; font-size: 12px; }}
QFrame#homeFrostTile {{ background: {blend_hex(lock['card'], t.surface_elevated, 0.25)};
    border: 1px dashed {lock['edge_strong']}; border-radius: 10px; }}
QLabel#homeFrostTileIcon {{ background: {lock['chip']}; border-radius: 9px; }}
QLabel#homeFrostTileName {{ background: transparent; color: {t.text}; font-size: 14px; font-weight: 700; }}
QLabel#homeFrostTileLock {{ background: transparent; }}
QLabel#homeFrostTileUse {{ background: transparent; color: {lock['text']}; font-size: 12px; }}
QComboBox#homeLanguageCombo[aiLock="true"], QComboBox#homeLanguageCombo[aiLock="true"]:disabled {{
    background: {lock['card']}; color: {lock['title']}; border: 1px dashed {lock['edge_strong']}; }}
QLabel#homeLanguageCaption[aiLock="true"] {{ color: {lock['title']}; }}
"""


def build_home_qss(t):
    from .ui_theme import blend_hex
    light = t.is_light
    # 2026-10-17 (user: on dark themes the colour "有點醜和搶目光", light is
    # fine): dark themes keep the zone and identity hues to a faint hint on the
    # surfaces; colour lives in the icon chips, role names and status tags.
    rest, edge_amount, chip_amount = (0.07, 0.36, 0.2) if light else (0.045, 0.2, 0.17)
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
    # 2026-10-17 home C′ (user: "右邊那些也多做些顏色…可以更和諧耐看一些"):
    # one settings card; the model cards carry their identity hue a little
    # stronger, the AI and content sections are whole bands in their zone hue.
    band = {"ai": blend_hex(t.surface, zones["ai"], 0.1 if light else 0.045),
            "content": blend_hex(t.surface, zones["content"], 0.09 if light else 0.04)}
    band_edge = {"ai": blend_hex(t.surface, zones["ai"], 0.32 if light else 0.16),
                 "content": blend_hex(t.surface, zones["content"], 0.32 if light else 0.15)}
    band_chip = {name: blend_hex(t.surface, zones[name], 0.24 if light else 0.17) for name in ("ai", "content")}
    wash, wash_hover = (0.15, 0.21) if light else (0.05, 0.09)
    # The model cards are the settings card's first band: three columns edge to
    # edge, hairlines between them, the outer top corners follow the card.
    column_edge = blend_hex(t.surface, t.text, 0.14 if light else 0.12)
    corners = {"primary": " border-top-left-radius: 13px;", "review": " border-top-right-radius: 13px;"}
    role_rules = "\n".join(
        f'QFrame#homeSettingsCard QFrame#recognitionRoleCard[role="{role}"] {{ background: {blend_hex(t.surface, color, wash)};'
        f' border: 0; border-radius: 0;{corners.get(role, "")}'
        f'{"" if role == "review" else " border-right: 1px solid " + column_edge + ";"} }}\n'
        f'QFrame#homeSettingsCard QFrame#recognitionRoleCard[role="{role}"]:hover,'
        f' QFrame#homeSettingsCard QFrame#recognitionRoleCard[role="{role}"]:focus {{ background: {blend_hex(t.surface, color, wash_hover)}; }}\n'
        f'QFrame#homeSettingsCard QFrame#recognitionRoleCard[role="{role}"] QFrame#contentRule {{ background: {blend_hex(t.surface, color, 0.3 if light else 0.14)}; border: 0; }}'
        for role, color in t.role_colors.items())
    return f"""
QFrame#studioEntryCard {{ background: {tint['studio']}; border: 1px solid {edge['studio']}; border-radius: 14px; }}
QFrame#studioEntryCard:hover {{ background: {tint['studio']}; border-color: {strong['studio']}; }}
QFrame#studioEntryCard:focus {{ border: 1px solid {t.focus}; }}
QFrame#studioEntryCard QLabel#homeCardIcon {{ background: {chip['studio']}; border-radius: 11px; }}
QFrame#homeSettingsCard {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 14px; }}
QFrame#homeSettingsCard QWidget#homePlanBlock {{ background: transparent; }}
{role_rules}
QFrame#homeProcessCard {{ background: {band['ai']}; border: 0; border-top: 1px solid {band_edge['ai']}; border-radius: 0; }}
QFrame#homeContentProfile {{ background: {band['content']}; border: 0; border-top: 1px solid {band_edge['content']};
    border-radius: 0; border-bottom-left-radius: 13px; border-bottom-right-radius: 13px; }}
QFrame#homeContentProfile QLabel#homeCardIcon {{ background: {band_chip['content']}; border-radius: 10px; }}
QFrame#homeContentProfile QWidget#homeTermSearchPanel, QFrame#homeContentProfile QWidget#homeContentPlain {{ background: transparent; }}
QLabel#homeLanguageTitle {{ color: {t.text}; font-size: 15px; font-weight: 600; background: transparent; }}
QWidget#homeLanguageField {{ background: transparent; }}
QLabel#homeLanguageCaption {{ color: {t.text_muted}; font-size: 12px; font-weight: 600; background: transparent; }}
QLabel#homeLanguageArrow {{ color: {t.text_muted}; font-size: 16px; font-weight: 700; background: transparent; }}
QLabel#homeLanguageSummary {{ color: {t.text_secondary}; font-size: 13px; font-weight: 600; background: transparent; }}
QLabel#homeSectionTitle {{ color: {t.text}; font-family: {UI_FONT_STACK}; font-size: 19px;
    font-weight: 600; background: transparent; border: 0; }}
QLabel#homeSectionHint {{ color: {t.text_secondary}; font-size: 13px; font-weight: 500; background: transparent; }}
QWidget#homePlanBlock QLabel#homeSectionHint {{ color: {t.text_muted}; }}
QLabel#homeFieldLabel, QWidget#homePlanBlock QLabel#fieldLabel {{ color: {t.text_secondary};
    font-size: 13px; font-weight: 500; background: transparent; }}
QPushButton#homeHeaderAction {{ background: transparent; color: {t.text_secondary};
    border: 1px solid {t.border}; border-radius: 8px; padding: 0 12px; min-height: 34px;
    font-size: 13px; font-weight: 500; }}
QPushButton#homeHeaderAction:hover {{ background: {t.selected}; color: {t.text}; border-color: {t.border_strong}; }}
QPushButton#homeHeaderAction:focus {{ border-color: {t.focus}; }}
QWidget#homePlanBlock QComboBox#recognitionPlanCombo, QWidget#homePlanBlock QComboBox#projectProfileCombo {{
    min-height: 38px; font-size: 14px; padding: 0 12px; border-radius: 9px; }}
QFrame#homeContentProfile QFrame#homeContentPanel {{
    background: {inner}; border: 1px solid {edge['content']}; border-radius: 12px; }}
QFrame#homeContentProfile QFrame#homeBatchGlossary {{ background: transparent; border: 0; border-radius: 0; }}
QFrame#homeContentProfile QComboBox#homeContentCombo {{ min-height: 44px; font-size: 16px;
    padding: 0 14px; border-radius: 10px; }}
QFrame#homePanelRule {{ background: {band_edge['content']}; border: 0; }}
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
QFrame#homeProcessCard QFrame#accordion {{ background: transparent; border: 0; }}
{_ai_card_rules(t, zones, strong, chip_amount)}
QDialog#aiSettingsDialog QFrame#aiDialogHeader {{ background: {t.surface}; border: 0; border-bottom: 1px solid {t.border}; }}
QDialog#aiSettingsDialog QLabel#aiDialogTitle {{ color: {t.text}; font-size: 20px; font-weight: 600; background: transparent; }}
QDialog#aiSettingsDialog QLabel#aiDialogSubtitle {{ color: {t.text_secondary}; font-size: 13px; background: transparent; }}
QDialog#aiSettingsDialog QScrollArea#aiDialogScroll, QDialog#aiSettingsDialog QWidget#aiDialogBody {{ background: {t.surface}; border: 0; }}
QDialog#aiSettingsDialog QFrame#accordion {{ background: transparent; border: 0; }}
QDialog#groupingPromptDialog {{ background: {t.surface}; }}
QDialog#groupingPromptDialog QFrame#aiDialogHeader {{ background: {t.surface}; border: 0; border-bottom: 1px solid {t.border}; }}
QDialog#groupingPromptDialog QFrame#aiDialogFooter {{ background: {t.surface}; border: 0; border-top: 1px solid {t.border}; }}
QDialog#groupingPromptDialog QLabel#aiDialogTitle {{ color: {t.text}; font-size: 20px; font-weight: 600; background: transparent; }}
QDialog#groupingPromptDialog QLabel#aiDialogSubtitle {{ color: {t.text_secondary}; font-size: 13px; background: transparent; }}
QDialog#groupingPromptDialog QWidget#aiDialogBody {{ background: {t.surface}; border: 0; }}
QDialog#groupingPromptDialog QPlainTextEdit#groupingPromptEditor, QDialog#groupingPromptDialog QPlainTextEdit#groupingPromptFixed {{
    font-size: 14px; border: 1px solid {t.border}; border-radius: 8px; padding: 6px; }}
QDialog#groupingPromptDialog QPlainTextEdit#groupingPromptFixed {{ color: {t.text_secondary}; }}
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
QFrame#mediaRow[empty="true"] QLabel#mediaIcon {{ border-radius: 13px; background: {t.accent_tint}; }}
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
