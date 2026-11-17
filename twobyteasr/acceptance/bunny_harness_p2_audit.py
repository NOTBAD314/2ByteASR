"""Opt-in normal Windows chat acceptance; isolated data and scripted providers only."""

def run(window, page, output, check):
    import json
    import time
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    from ..app import bunny_audit, bunny_chat, bunny_permissions, bunny_vision
    from ..app.bunny_tools import TOOLS, run_turn
    from ..providers import ai_providers
    from ..providers.provider_input_budget import prepare_input
    from ..design.theme_manager import request_theme

    app=QApplication.instance()
    ready,support,provider=bunny_chat.ai_readiness,bunny_vision.support,ai_providers.provider_for_stage
    permissions=bunny_permissions.load()
    saved_clipboard=QMimeData()
    for fmt in QApplication.clipboard().mimeData().formats():
        saved_clipboard.setData(fmt,QApplication.clipboard().mimeData().data(fmt))
    sent=[]; choice_requests=[]; card=None
    class Provider:
        def complete(self,messages,**kwargs):
            if kwargs.get('max_tokens')==300:
                choice_requests.append(True)
                return json.dumps({'suggest':['继续看附件','打开设置看看']},ensure_ascii=False)
            prepared,report=prepare_input(messages,schema=None,max_tokens=8000,operation='bunny_chat')
            sent.append((prepared,report))
            return json.dumps({'lines':['离线验收已收到附件。'],'mood':'happy'},ensure_ascii=False)
    def wait(predicate,label):
        end=time.monotonic()+15
        while not predicate() and time.monotonic()<end:
            app.processEvents();QTest.qWait(10)
        check('P2 '+label,predicate())
    def state(label):
        details=dict(label=label,attachments=[dict(name=i.name,kind=i.kind) for i in card._attachments],
                     input=card.input.text()[:100],clipboard_formats=list(QApplication.clipboard().mimeData().formats()),
                     clipboard_has_image=QApplication.clipboard().mimeData().hasImage(),
                     last_reply=[text for who,text in card.transcript if who=='bunny'][-1:],
                     busy=card.busy,ready=card.ready,visible=card.isVisible(),mode=card.mode,
                     chips=[dict(text=b.text(),visible=b.isVisible()) for b in card.attach_row.findChildren(QPushButton)])
        (output/('P2-state-'+label+'.json')).write_text(json.dumps(details,ensure_ascii=False,indent=2),'utf8')
        card.grab().save(str(output/('P2-state-'+label+'.png')))
    def drop(path):
        before=[dict(name=i.name,kind=i.kind) for i in card._attachments]
        mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(path))])
        enter=QDragEnterEvent(card.input.rect().center(),Qt.DropAction.CopyAction,mime,
                              Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(card.input,enter)
        event=QDropEvent(QPointF(card.input.rect().center()),Qt.DropAction.CopyAction,mime,
                         Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(card.input,event)
        after=[dict(name=i.name,kind=i.kind) for i in card._attachments]
        (output/('P2-drop-'+path.name+'.json')).write_text(json.dumps(dict(
            file=path.name,enter_accepted=enter.isAccepted(),drop_accepted=event.isAccepted(),
            before=before,after=after,added=len(after)-len(before),busy=card.busy,ready=card.ready,
            image_support=bunny_vision.support(card.settings)),ensure_ascii=False,indent=2),'utf8')
        check('P2 actual file drop accepted '+path.name,enter.isAccepted() and event.isAccepted())
    try:
        bunny_chat.ai_readiness=lambda _s:(True,'Offline P2 acceptance')
        bunny_vision.support=lambda _s:(True,'')
        ai_providers.provider_for_stage=lambda *a,**k:Provider()
        bunny_permissions.save(dict(permissions,remember=True,keep_chat=True))
        page.cue_bunny_button.click();app.processEvents();card=window._bunny_chat
        card.new_conversation();card.reveal_all();card.set_mode('dialog')
        long_json=json.dumps({'items':['附件内容']*450},ensure_ascii=False,indent=2)
        # Windows OLE can complete the previous audit's clipboard restore on a later event.
        # Reassert this owned fixture with a bounded retry; never log clipboard contents.
        for _ in range(10):
            QApplication.clipboard().setText(long_json);QTest.qWait(50)
            if QApplication.clipboard().text().replace('\r\n','\n')==long_json:break
        card.input.setFocus();app.processEvents()
        wait(lambda:QApplication.clipboard().text().replace('\r\n','\n')==long_json,'clipboard contains requested JSON')
        QTest.keyClick(card.input,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier);app.processEvents()
        state('paste')
        check('P2 actual long Ctrl V becomes JSON attachment',len(card._attachments)==1
              and card._attachments[0].name.endswith('.json') and not card.input.text())
        file=output/'P2-中文日志.txt';file.write_text('第一行\n第二行\n'+'日'*5000,'utf8');drop(file)
        image=QImage(1900,900,QImage.Format.Format_ARGB32);image.fill(QColor('#3e819b'))
        def image_ready():
            mime=QApplication.clipboard().mimeData()
            if mime is None or not mime.hasImage():return False
            current=QApplication.clipboard().image()
            return (not current.isNull() and current.size()==image.size()
                    and current.pixelColor(0,0)==image.pixelColor(0,0))
        for _ in range(10):
            QApplication.clipboard().setImage(image);QTest.qWait(50)
            if image_ready():break
        wait(image_ready,'clipboard contains requested image')
        state('image-ready')
        QTest.keyClick(card.input,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier)
        state('after-image-paste')
        image_path=output/'P2-图片.png';image.save(str(image_path));drop(image_path)
        state('mixed')
        check('P2 mixed files and images wait together',len(card._attachments)==4
              and sum(item.kind=='image' for item in card._attachments)==2)
        check('P2 attachment removal uses visible chip',len(card.attach_row.findChildren(QPushButton))>=4)
        # Remove the first picture through its actual chip; then put it back.
        wait(lambda:any(b.text()=='图1' and b.isVisible() for b in card.attach_row.findChildren(QPushButton)),
             'attachment chip is painted before click')
        chip=next(b for b in card.attach_row.findChildren(QPushButton) if b.text()=='图1' and b.isVisible())
        chip.click();app.processEvents();check('P2 clicking picture chip removes only one attachment',len(card._attachments)==3)
        card.attach_picture(image)
        prepared=list(card._attachments)
        for theme in ('sand','midnight'):
            request_theme(theme);QTest.qWait(200)
            card.close_chat();app.processEvents()
            page.cue_bunny_button.click();app.processEvents();card=window._bunny_chat
            card.new_conversation();card.reveal_all();card.set_mode('dialog')
            for item in prepared:
                if item.kind=='image':card.attach_picture(image)
                else:card.attach_text(item.text,item.name)
            app.processEvents()
            card.input.setText('检查附件');QTest.keyClick(card.input,Qt.Key.Key_Return,Qt.KeyboardModifier.ShiftModifier)
            card.input.insertPlainText('保留换行')
            check('P2 multiline input and send are accessible '+theme,'\n' in card.input.text()
                  and not card.input.visibleRegion().isEmpty() and not card.send_button.visibleRegion().isEmpty())
            chips=[card.attach_row.layout().itemAt(i).widget() for i in range(card.attach_row.layout().count())]
            check('P2 attachment chips stay inside separate rows '+theme,
                  all(card.attach_row.rect().contains(b.geometry()) for b in chips)
                  and all(not a.geometry().intersects(b.geometry()) for i,a in enumerate(chips) for b in chips[i+1:]))
            card.grab().save(str(output/('P2-attachments-'+theme+'.png')))
        QTest.keyClick(card.input,Qt.Key.Key_Return)
        wait(lambda:not card.busy,'mixed attachment request finishes')
        card.reveal_all()
        wait(lambda:bool(card._ai_suggest),'fallback choices arrive')
        card.refresh_suggestions();app.processEvents()
        check('P2 sends two bounded images and full text in one question',sent[0][1]['image_count']==2
              and '附件内容' in json.dumps(sent[0][0],ensure_ascii=False)
              and '第二行' in json.dumps(sent[0][0],ensure_ascii=False) and not card._attachments)
        check('P2 history contains shortened text and no image bytes',all(isinstance(m['content'],str) for m in card._history)
              and 'data:image' not in json.dumps(card._history) and '这次没有再附上' in card._history[0]['content'])
        choices=[b for b in card.suggest_row.findChildren(QPushButton) if b.isVisible()]
        check('P2 two selectable marked choices below answer',len(choices)==2
              and all(b.text().startswith(bunny_chat.CHOICE_MARK) for b in choices) and bool(choice_requests))
        card.grab().save(str(output/'P2-choices-midnight.png'))
        choices[0].click();wait(lambda:not card.busy,'choice sends next question')
        card.reveal_all()
        check('P2 clicked choice is plain question without prior images',card.transcript[-2][1]=='继续看附件'
              and sent[-1][1]['image_count']==0)
        card.attach_text('old project text');card.attach_picture(image)
        key=card._project_key;card._project_key=lambda:'p2-other-project'
        card.attach_text('new project text')
        check('P2 new attachment sync drops previous project files and images',len(card._attachments)==1
              and card._attachments[0].text=='new project text')
        card._project_key=key;card._sync_chat_context()
        check('P2 returning project drops unsent attachments',not card._attachments)
        prompt=TOOLS['tool_help'].run(window,{'names':['change_terms','write_file']})
        check('P2 tool search returns full arguments',TOOLS['change_terms'].args in prompt and TOOLS['write_file'].args in prompt)
        bunny_audit.record('ui_press',{'text':'P2 test'},'- ui_press：成功。',question='P2 offline test')
        listing=run_turn(window,[('recent_actions',{})],bunny_permissions.load())
        check('P2 persistent action listing works','P2 test' in listing.receipts[0])
        for switch in ('read_subtitles','read_diagnostics','remember'):
            closed=dict(bunny_permissions.load(),**{switch:False})
            for name in ('recent_actions','replay_action'):
                check('P2 history closed switch '+switch+' '+name,
                      '关掉了' in run_turn(window,[(name,{'id':1})],closed).receipts[0])
        bunny_permissions.save(dict(permissions,remember=False))
        check('P2 replay respects disabled memory','关掉了' in run_turn(window,[('replay_action',{'id':1})],None).receipts[0])
    finally:
        if card is not None:card.close_chat()
        bunny_chat.ai_readiness=ready;bunny_vision.support=support
        ai_providers.provider_for_stage=provider;bunny_permissions.save(permissions)
        QApplication.clipboard().setMimeData(saved_clipboard)
