"""Explicit selected-cue translation actions and settings continuation."""
from __future__ import annotations

from ..i18n import tr


def failure_hint(category):
    return tr({'auth_config':'当前文字翻译服务缺少 API Key，请前往设置。',
               'auth_error':'服务拒绝了凭据，请检查当前文字服务的 Key 与权限。',
               'quota_exhausted':'服务提示余额或额度不足，请检查该服务账户。',
               'rate_limited':'服务正在限流，请稍后重试。',
               'configuration_error':'请检查当前服务地址与模型是否存在、是否可用。',
               'model_not_supported':'服务没有找到当前模型，或账户没有该模型权限。请检查文字服务设置。',
               'request_rejected':'服务拒绝了参数或模型，请检查详细原因。',
               'transport_error':'网络连接失败，请检查当前文字服务的连接。',
               'connection_error':'网络连接失败，请检查当前文字服务地址与网络连接。',
               'tls_error':'无法验证服务的 TLS 证书，请检查系统时间与代理证书；不要关闭证书验证。',
               'connect_timeout':'连接文字服务超时，请检查网络后重试。',
               'read_idle_timeout':'文字服务长时间没有返回数据，请稍后重试。',
               'provider_total_timeout':'请求超时；已完成的合并与原文会保留。',
               'total_timeout':'请求超时；已完成的合并与原文会保留。',
               'cancelled':'请求已停止；已完成的合并与原文会保留。'}.get(str(category), ''))


def capture_intent(page, ids, target):
    from ..projects.studio_runtime_state import state_for
    project = page.project
    wanted = None if ids is None else set(ids)
    revisions = state_for(project).content_revisions
    return (project, str(target), tuple((cue.id, cue.text, revisions.get(cue.id, 0))
                                      for cue in project.cues if wanted is None or cue.id in wanted))


def intent_current(page, intent, target):
    project, language, rows = intent
    if page.project is not project or str(target) != language:
        return False
    from ..projects.studio_runtime_state import state_for
    state = state_for(project)
    return all((cue := state.cue_by_id.get(cue_id)) is not None and cue.text == text
               and state.content_revisions.get(cue_id, 0) == revision
               for cue_id, text, revision in rows)


def translate_selected(page, *, merge=False):
    if not page.project or not page.selected_cue_ids():
        return
    if merge:
        from ..app.settings_lifecycle import activate
        if activate(getattr(page, '_translation_dialog', None)):
            return
        from ..timeline.studio_commands import merge_cues_command
        ids = page.selected_cue_ids()
        if len(ids) >= 2:
            page.undo_stack.push(merge_cues_command(page.project, ids, page.cue_controller.model_changed))
        else:
            before = tuple((cue.id, cue.text) for cue in page.project.cues)
            page.cue_controller.merge_next()
            if before == tuple((cue.id, cue.text) for cue in page.project.cues):
                return
        # The command's stable ID is the complete merged sentence, never the
        # old selection scope (which may still contain removed cue IDs).
        from ..projects.studio_runtime_state import state_for
        selected = state_for(page.project).selected_cue_id
        page.select_cue(selected)
    page._open_translation_dialog(scope='selected', auto_start=merge)


def add_actions(page, menu):
    action = menu.addAction(tr('翻译所选字幕 / 更新所选翻译…'))
    action.triggered.connect(lambda: translate_selected(page))
    merge = menu.addAction(tr('合并并更新翻译（发送翻译请求）'))
    merge.triggered.connect(lambda: translate_selected(page, merge=True))
    reason = menu.addAction('')
    reason.setEnabled(False)
    menu.setToolTipsVisible(True)
    def refresh():
        enabled = bool(page.project and page.selected_cue_ids())
        message = '' if enabled else tr('请先选取字幕' if page.project else '请先打开工程')
        if enabled:
            from ..subtitle_rules.subtitle_translation import records_of
            records = records_of(page.project)
            missing = sum(len((records.get(key) or {}).get('merge_missing') or ()) for key in page.selected_cue_ids())
            if missing:
                message = tr('合并字幕有 {count} 段缺译；已有译文已保留，可在此补译。', count=missing)
        for item in (action, merge):
            item.setEnabled(enabled)
            item.setToolTip(message or tr('打开翻译窗口；已有译文会保留，缺少 API Key 时可前往设置。'))
        reason.setText(message)
        reason.setVisible(bool(message))
    menu.aboutToShow.connect(refresh)
    refresh()
    return action, merge


def open_translation_settings(dialog):
    """Keep a modeless translation dialog and its immutable selected scope."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog
    from shiboken6 import isValid
    from ..providers.llm_config import text_ai_key_missing
    from ..caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
    owner = dialog.page.window()
    opener = getattr(owner, '_open_ai_settings_dialog', None)
    if not callable(opener):
        dialog.status.setText(tr('请在主窗口打开 AI 文字服务设置，填写“字幕校对”服务的 API Key。'))
        return
    intent = capture_intent(dialog.page, dialog._scope_ids(), dialog._target())
    dialog.hide()
    opener()
    settings = getattr(owner, '_ai_settings_dialog', None)
    if settings is None:
        dialog.show()
        return
    # The top form serves translation: the shared service, or 校对 when line
    # breaking has its own (2026-10-22, one-page AI settings).
    editor = owner.__dict__.get('_ai_main_editor') or getattr(owner, 'polish_editor', None)
    if editor is not None:
        editor.show()
        editor.key.setFocus()
        editor.key.selectAll()
        from PySide6.QtWidgets import QScrollArea
        scroll = settings.findChild(QScrollArea, 'aiDialogScroll')
        if scroll is not None:
            scroll.ensureWidgetVisible(editor.key)

    def finished(result):
        if not isValid(dialog):
            return
        dialog.show(); dialog.raise_(); dialog.activateWindow()
        dialog._provider_ready = dialog._describe_service()
        if result != int(QDialog.Accepted):
            dialog.status.setText(tr('已取消设置，字幕与选取保持不变。'))
        elif not intent_current(dialog.page, intent, dialog._target()):
            dialog.status.setText(tr('工程或原文已变化，未继续翻译。请重新选择字幕。'))
        elif not text_ai_key_missing(GLOBAL_PROVIDER_REGISTRY.settings(), 'polish'):
            QTimer.singleShot(0, dialog._start)
    settings.finished.connect(finished)
