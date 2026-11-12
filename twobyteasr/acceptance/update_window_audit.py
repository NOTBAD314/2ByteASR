"""Explicit normal-window checks for the incremental update offer."""
def verify(window, output, theme, check, settle, shot):
    from types import SimpleNamespace
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontInfo,QPalette
    from PySide6.QtWidgets import QLabel,QFrame
    from ..app.updater import ComponentAction,UpdatePlan
    from ..app.update_dialog import UpdateOfferDialog,card_ink
    from ..design.loading_font import loading_font
    from ..i18n import apply_ui_language,save_language,tr

    plan=UpdatePlan('components',(ComponentAction('app','changed',23*1024*1024,23*1024*1024,48_000_000),),23*1024*1024,1_000_000_000,'',(),())
    highlights=(
        ('说话人拖拽分区','拖放换组、合并角色，一次确认整组。'),
        ('当前字幕快捷操作','定位、居中、合并和删除，Alt+J 往返两端。'),
        ('日语与双语编辑','即时预览草稿，保留原译文和校对来源。'),
        ('兔白语音教学','原版动画搭配可关闭的语音与知识气泡。'),
        ('常用窗口整理','模型、记录和更新信息更清楚。'),
        ('问题诊断反馈','导出失败显示原因，支持重新尝试。'),
    )
    for count in (1,3,4,6,0):
        notes='\n'.join(title+'：'+detail for title,detail in highlights[:count]) if count else '完整说明'+('较长的更新内容。'*15)
        offer=SimpleNamespace(plan=plan,latest_version='1.0.0',current_version='0.9.7',manifest=SimpleNamespace(note_for=lambda language:notes))
        dialog=UpdateOfferDialog(offer,window,reminder=count==4);dialog.show();settle(.2)
        prefix=theme+' update '+str(count)+' '
        check(prefix+'rounded normal window',bool(dialog.windowFlags()&Qt.WindowType.FramelessWindowHint) and dialog.RADIUS==24)
        check(prefix+'size on primary button',dialog.primary_button.text()==tr('下载并准备更新 · {value0}',value0='23.0 MB'))
        check(prefix+'no redundant size or progress',not dialog.findChildren(QFrame,'updateOfferTrack') and not dialog.findChildren(QLabel,'updateOfferSize'))
        check(prefix+'correct highlight count',len(dialog.highlight_cards)==min(count,4))
        version=dialog.findChild(QLabel,'updateOfferVersion')
        check(prefix+'bundled version font',QFontInfo(version.font()).family()==QFontInfo(loading_font()).family() and version.font().pixelSize()==60,QFontInfo(version.font()).family())
        for index,card in enumerate(dialog.highlight_cards):
            title=card.findChild(QLabel,'updateOfferCardTitle')
            detail=card.findChild(QLabel,'updateOfferCardText')
            check(prefix+'specific major update '+str(index),title.text()==highlights[index][0] and detail is not None and detail.text()==highlights[index][1])
            check(prefix+'card title hue '+str(index),title.palette().color(QPalette.ColorRole.WindowText).name()==card_ink(dialog._offer_theme,index).lower())
            check(prefix+'card title inside '+str(index),card.rect().contains(title.geometry()))
        check(prefix+'button within dialog',dialog.rect().contains(dialog.primary_button.geometry()))
        check(prefix+'fits available screen',dialog.height()<=dialog.screen().availableGeometry().height(),dict(height=dialog.height(),available=dialog.screen().availableGeometry().height()))
        if count==4:
            check(prefix+'reminder retained',dialog.remind_box is not None and dialog.remind_box.isChecked())
            dialog.remind_box.click();check(prefix+'reminder choice retained',dialog.keep_reminding is False)
        shot(dialog,theme+'-update-'+str(count))
        if count==6:
            dialog.more_line.linkActivated.emit('page');check(prefix+'full notes action',dialog.choice=='page')
        else:
            dialog.primary_button.click();check(prefix+'component action',dialog.choice=='download')
        dialog.deleteLater();settle(.05)
    for language in ('en','ja'):
        save_language(language)
        apply_ui_language(window,language)
        dialog=UpdateOfferDialog(offer,window);dialog.show();settle(.1)
        check(theme+' '+language+' translated size button',dialog.primary_button.text()==tr('下载并准备更新 · {value0}',value0='23.0 MB') and not dialog.primary_button.text().startswith('下载'))
        check(theme+' '+language+' button text fits',dialog.primary_button.fontMetrics().horizontalAdvance(dialog.primary_button.text())+44<dialog.primary_button.width())
        shot(dialog,theme+'-update-'+language);dialog.reject();dialog.deleteLater();settle(.05)
    save_language('zh');apply_ui_language(window,'zh')
    fallback=UpdatePlan('setup',(),1_200_000_000,1_200_000_000,'当前安装没有元件清单',('moss',),('moss',))
    offer.plan=fallback
    dialog=UpdateOfferDialog(offer,window);dialog.show();settle(.1)
    text='\n'.join(label.text() for label in dialog.findChildren(QLabel))
    check(theme+' setup reason and size retained','1.12 GB' in text and '当前安装没有元件清单' in text)
    shot(dialog,theme+'-update-setup');dialog.primary_button.click();check(theme+' setup action retained',dialog.choice=='setup')
    dialog.deleteLater();settle(.05)
