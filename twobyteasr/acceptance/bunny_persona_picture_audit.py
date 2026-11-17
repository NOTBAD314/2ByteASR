"""Actual chat input events with an offline provider, in the normal Windows GUI."""
def run(window, page, output, check):
    import json
    import time
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..app import bunny_chat, bunny_permissions, bunny_vision
    from ..providers import ai_providers
    from ..providers.provider_input_budget import prepare_input
    from ..design.theme_manager import request_theme
    app = QApplication.instance()
    ready, support, provider = bunny_chat.ai_readiness, bunny_vision.support, ai_providers.provider_for_stage
    permissions = bunny_permissions.load()
    original_size = window.size()
    original_clipboard = QMimeData()
    clipboard = QApplication.clipboard().mimeData()
    for fmt in clipboard.formats(): original_clipboard.setData(fmt, clipboard.data(fmt))
    sent, answers = [], []
    card = None
    def images():
        return [item.capture for item in card._attachments if item.kind == "image"]
    def wait():
        deadline = time.monotonic() + 15
        while card.busy and time.monotonic() < deadline:
            app.processEvents(); QTest.qWait(10)
        check('picture worker completed ' + str(len(sent)), not card.busy)
        card.reveal_all()
    class Provider:
        def complete(self, messages, **kwargs):
            if kwargs.get('max_tokens') == 300:
                return json.dumps({'suggest':['继续检查', '看看设置']}, ensure_ascii=False)
            prepared, report = prepare_input(messages, schema=None, max_tokens=8000, operation='bunny_chat')
            sent.append((prepared, report))
            return json.dumps(answers.pop(0), ensure_ascii=False)
    try:
        bunny_chat.ai_readiness = lambda settings: (True, 'Offline picture acceptance')
        bunny_vision.support = lambda settings: (True, '')
        ai_providers.provider_for_stage = lambda *args, **kwargs: Provider()
        bunny_permissions.save(dict(permissions, keep_chat=True, remember=True))
        page.cue_bunny_button.click(); app.processEvents()
        card = window._bunny_chat
        card.new_conversation(); card.reveal_all(); card.set_mode('dialog')
        image = QImage(1900, 900, QImage.Format.Format_ARGB32)
        image.fill(QColor(35, 120, 195, 255))
        QApplication.clipboard().setImage(image)
        card.input.setFocus()
        QTest.keyClick(card.input, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        app.processEvents()
        check('actual Ctrl V attaches and previews bounded image', bool(images())
              and max(images()[0].width, images()[0].height) == 1600 and card.attach_row.isVisible())
        for theme in ('sand', 'midnight'):
            request_theme(theme); QTest.qWait(250)
            card.close_chat(); app.processEvents()
            page.cue_bunny_button.click(); app.processEvents(); card = window._bunny_chat
            card.set_mode('dialog'); card.attach_picture(image)
            check('pending picture input visible ' + theme, not card.input.visibleRegion().isEmpty()
                  and not card.send_button.visibleRegion().isEmpty())
            card.grab().save(str(output / ('picture-pending-' + theme + '.png')))
        answers.append(dict(lines=['图像已收到，这是离线验收。'], mood='happy', meme=True))
        QTest.keyClick(card.input, Qt.Key.Key_Return); wait()
        check('Enter alone sends one budgeted picture', len(sent) == 1 and sent[0][1]['image_count'] == 1
              and not images() and card._since_meme == 0)
        check('picture history and saved transcript contain only text', all(isinstance(m['content'], str)
              for m in card._history) and 'data:image' not in json.dumps(card.transcript))
        card.grab().save(str(output / 'picture-sent.png'))
        answers.append(dict(lines=['下一题没有图片。']))
        card.input.setText('继续'); QTest.keyClick(card.input, Qt.Key.Key_Return); wait()
        check('next request does not repeat picture', sent[-1][1]['image_count'] == 0)
        picture_file = output / 'owned-drop.png'
        image.save(str(picture_file))
        mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(picture_file))])
        drag = QDragEnterEvent(card.input.rect().center(), Qt.DropAction.CopyAction, mime,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(card.input, drag)
        drop = QDropEvent(QPointF(card.input.rect().center()), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(card.input, drop)
        check('actual file drag and drop attaches picture', drag.isAccepted() and drop.isAccepted()
              and bool(images()))
        card.set_mode('thread')
        answers.append(dict(lines=['呜……别吓兔白。'], mood='scared', spooked=True))
        card.input.setText('离线表情状态'); QTest.keyClick(card.input, Qt.Key.Key_Return); wait()
        check('thread picture sent and frightened mood retained', sent[-1][1]['image_count'] == 1
              and card._uneasy > 0 and card.transcript[-2][1].endswith(bunny_chat.PICTURE_MARK))
        card.grab().save(str(output / 'picture-thread-scared.png'))
        answers.append(dict(lines=['哼，原谅你这一次。'], made_up=True))
        card.input.setText('对不起，不吓你了'); card.send(); wait()
        check('apology clears frightened state', card._uneasy == 0)
        card._uneasy = 3; card._since_meme = 0; card._tricked = True
        card.attach_picture(image); card.new_button.click(); app.processEvents()
        check('real new conversation clears picture and session moods', not images()
              and card._uneasy == 0 and not card._tricked and card._since_meme == bunny_chat.bunny_persona.MEME_GAP)
        card.attach_picture(image)
        before = len(sent)
        old_key = card._project_key
        card._project_key = lambda: 'persona-picture-other-project'
        answers.append(dict(lines=['新工程只有文字。']))
        card.input.setText('另一工程'); card.send(); wait()
        check('immediate project switch never sends previous picture', len(sent) == before + 1
              and sent[-1][1]['image_count'] == 0 and not images())
        card._project_key = old_key; card._sync_chat_context()
        card.attach_picture(image)
        before = len(sent)
        bunny_vision.support = lambda settings: (False, '当前模型不支持图片')
        card.input.setText('看看'); card.send(); app.processEvents()
        check('send rechecks changed model capability', len(sent) == before and not card.busy
              and not images())
    finally:
        if card is not None: card.close_chat()
        bunny_chat.ai_readiness = ready; bunny_vision.support = support
        ai_providers.provider_for_stage = provider
        bunny_permissions.save(permissions)
        QApplication.clipboard().setMimeData(original_clipboard)
        window.resize(original_size)
