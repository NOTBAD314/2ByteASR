"""Application status derived from the selected cue, including Undo/Redo."""
from PySide6.QtCore import QTimer
from .i18n import tr, bind_text, join_text


def refresh_application_ui(page):
    from .studio_design_target import design_cue
    owner = getattr(page, '_theme_draft_coordinator', None)
    cue = design_cue(page.project, page.selected_cue_id)
    recipe = page.project.style_recipes.get(cue.style_id, {}) if cue is not None else {}
    theme = recipe.get('webTheme') or {}
    pending = getattr(page, '_pending_web_theme', None)
    busy = owner is not None and owner.phase == 'APPLYING'
    validating = bool(owner and getattr(owner,'auto_apply',False) and owner.phase == 'RENDERING')
    can_rebind = bool(owner and owner.current and owner.current.theme_json
                      and owner.phase not in {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW','APPLYING'})
    same = bool(theme and pending and theme == pending.theme)
    scope = str(page.ai_apply_scope.currentData() or 'current')
    target = tr({'current':'当前字幕','speaker':'该说话人字幕','all':'全部字幕'}[scope])
    if busy or validating:
        message = '正在应用到当前字幕…' if busy else '已采用方向 · 正在校验并应用…'
        label = '正在应用…'
    elif theme:
        message = '已应用到当前字幕 · 可编辑主题'
        label = tr('重新应用到{target}' if same and scope == 'current' else '应用到{target}', target=target)
    else:
        message = '当前字幕尚未应用方案' if cue else '请先在时间轴选中字幕，再应用已采用的方案'
        label = tr('应用到{target}', target=target)
    if owner and owner.category == 'stale_target' and not theme:
        message = '原设计对象已改变或删除 · 选中字幕后可重试应用'
        label = tr('重试应用到{target}', target=target)
    bind_text(page.ai_application_status, message)
    bind_text(page.ai_apply_button, label)
    valid = bool(owner and owner.allow_pending()) if pending else bool(getattr(page,'_pending_suggestion',None))
    page.ai_apply_button.setEnabled(bool(cue and not busy and not validating and (valid or can_rebind)))
    page.ai_transform_hint.setVisible(bool(theme))
    if theme:
        parts=[tr('可编辑主题 · 拖动字幕移动，拖动角点等比缩放；双击改字。')]
        worker=getattr(page,'_web_live_worker',None)
        key=getattr(worker,'_proxy_key',None)
        if key:
            from .caption_proxy import proxy_store
            status,(count,total)=proxy_store().progress(key)
            if status in {'building','missing'}:
                parts.append(tr('流畅预览准备中 {progress}，完成后自动使用。', progress=f'{round(count*100/total)}%' if total else ''))
            elif status=='ready':parts.append(tr('流畅预览已就绪 · 文字仍可编辑'))
            elif status=='failed':parts.append(tr('流畅预览未就绪，当前使用实时预览。'))
        bind_text(page.ai_transform_hint, join_text(parts, '\n'))
    page.ai_local_polish_button.setEnabled(bool(theme and not busy and not validating))


def install_application_status(page):
    timer = QTimer(page)
    timer.setInterval(400)
    timer.timeout.connect(lambda: refresh_application_ui(page))
    page._theme_application_timer = timer
    timer.start()
