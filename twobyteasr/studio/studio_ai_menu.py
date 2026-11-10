"""The one「AI 工具」menu in the subtitle list header (2026-11-10, user).

AI commands used to be spread over the cue-list AI menu, the timeline cue
menu (断句 / 优化 / 修轴 / 重识别) and 双语 / 翻译. They are grouped here by
scope: the whole project first, then the current or selected subtitles.
Each row is a ``RichMenuAction`` (title + caption); the existing buttons keep
owning their callbacks and enabled state.
"""

from __future__ import annotations

from ..design.rich_menu import RichMenuAction, add_header, add_rich
from ..design.themed_icons import themed_icon
from ..i18n import tr


def _icon(name):
    return themed_icon(name, "accent")


def _click(page, name):
    button = getattr(page, name, None)
    if button is not None:
        button.click()


def build_ai_menu(page, menu) -> None:
    from .translation_actions import translate_selected

    add_header(menu, tr("整个工程"))
    page.cue_proofread_action = add_rich(
        menu, _icon("fa5s.spell-check"), tr("AI 校对"), tr("按词库找错字和专有名词，勾选建议后应用"),
        lambda: page.glossary_proofread_requested.emit())
    page.cue_proofread_action.setToolTip(tr("打开当前工程的 AI 词库校对，勾选建议后应用"))
    page.cue_cleanup_action = add_rich(
        menu, _icon("fa5s.broom"), tr("AI 清理"), tr("去掉口癖、重复字和多余标点，逐条确认"),
        lambda: page._open_ai_cleanup())
    page.cue_cleanup_action.setToolTip(tr("用 AI 清理口癖、重复和标点；逐条确认后应用"))
    page.ai_refine_project_action = add_rich(
        menu, _icon("fa5s.paragraph"), tr("AI 断句"), tr("把整个工程重新断成好读的句子"),
        lambda: page.run_sentence_refine(whole_project=True))
    page.ai_translate_project_action = add_rich(
        menu, _icon("fa5s.language"), tr("翻译整个工程…"), tr("生成译文，之后可切换原文 / 译文 / 双语显示"),
        lambda: page._open_translation_dialog(scope="all"))

    menu.addSeparator()
    add_header(menu, tr("当前 / 选中的字幕"))
    page.ai_optimize_action = add_rich(
        menu, _icon("fa5s.magic"), tr("AI 优化"), tr("润色当前这条字幕的文字"),
        lambda: _click(page, "ai_optimize_button"))
    page.ai_smart_align_action = add_rich(
        menu, _icon("fa5s.wave-square"), tr("智能修轴"), tr("按声音重新对齐当前字幕的起止时间"),
        lambda: _click(page, "smart_align_button"))
    page.ai_reasr_action = add_rich(
        menu, _icon("fa5s.microphone"), tr("重新识别"), tr("对当前字幕的这段声音重新识别一次"),
        lambda: _click(page, "reasr_button"))
    page.ai_refine_selection_action = add_rich(
        menu, _icon("fa5s.cut"), tr("AI 断句（选中范围）"), tr("只对选中的字幕试跑断句"),
        lambda: page.run_sentence_refine(whole_project=False))
    page.ai_translate_selected_action = add_rich(
        menu, _icon("fa5s.globe"), tr("翻译所选字幕…"), tr("翻译或更新选中字幕的译文；已有译文会保留"),
        lambda: translate_selected(page))

    # Only in the menu while they mean something (a failed range / a running
    # job). Added and removed, not hidden: a hidden QWidgetAction still paints
    # its row at the menu's top-left corner.
    page.ai_refine_retry_action = RichMenuAction(
        _icon("fa5s.redo"), tr("重试断句失败的范围"), tr("上次 AI 断句有范围失败，只重跑这些"), menu)
    page.ai_refine_retry_action.triggered.connect(
        lambda _checked=False: page.run_sentence_refine(whole_project=False, retry_failed=True))
    page.ai_refine_cancel_action = RichMenuAction(
        _icon("fa5s.stop-circle"), tr("取消本次 AI 断句"), tr("已写回的结果保留"), menu)
    page.ai_refine_cancel_action.triggered.connect(lambda _checked=False: page.cancel_sentence_refine())

    def place(action, wanted):
        present = action in menu.actions()
        if wanted and not present:
            menu.addAction(action)
        elif present and not wanted:
            menu.removeAction(action)

    def refresh():
        project = getattr(page, "project", None)
        has_project = project is not None
        selected = bool(has_project and page.selected_cue_ids())
        current = bool(has_project and getattr(page, "selected_cue_id", None))
        for action in (page.ai_refine_project_action, page.ai_translate_project_action):
            action.setEnabled(has_project)
        for action, name in ((page.ai_optimize_action, "ai_optimize_button"),
                             (page.ai_smart_align_action, "smart_align_button"),
                             (page.ai_reasr_action, "reasr_button")):
            button = getattr(page, name, None)
            action.setEnabled(bool(current and (button is None or button.isEnabled())))
        page.ai_refine_selection_action.setEnabled(selected)
        page.ai_translate_selected_action.setEnabled(selected)
        failed = bool(has_project and (project.studio_state.get("ai_sentence_refine") or {}).get("failed_cue_ids"))
        worker = getattr(page, "_refine_worker", None)
        running = bool(worker is not None and worker.isRunning())
        place(page.ai_refine_retry_action, failed and not running)
        place(page.ai_refine_cancel_action, running)

    menu.aboutToShow.connect(refresh)
    refresh()
