"""兔白看画面 (2026-11-16): a picture of 2ByteASR's own windows for an AI that can see images.

User (2026-11-16): 「这 AI 如果能调用视觉来截图看的话会更好一些」. Chosen with the user:

* only 2ByteASR's own windows are pictured (Qt's ``QWidget.grab``), never the desktop or another
  program; 兔白's own chat card, the floating bunny and her spotlight are left out;
* only when the user turned on 「让兔白截图看 2ByteASR 的画面」 in 「兔白权限」 (off by default, with a
  first-time explanation), and only when the AI she talks through can see images. For a text-only
  model (DeepSeek's) she says which kinds of models can, instead of trying;
* the picture is made smaller (``LONG_SIDE``), sent once with the next request and never written
  to disk; the saved chat keeps only 「[截图 1280×720]」.

2026-11-17 (user): DeepSeek V4.1 Flash (``deepseek-flash``, and the old ``deepseek-v4-flash`` name it
serves) sees images, per DeepSeek's pricing page; only ``deepseek-v4-pro`` does not. The user may
also paste (Ctrl+V) or drop a picture into the chat (``pasted``); it goes with that question only.

``support`` has no Qt; ``capture`` needs the GUI thread.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field

LONG_SIDE = 1280             # px, the long side of what is sent
THUMB_SIDE = 220             # px, the long side of the picture shown in the chat
JPEG_QUALITY = 80
SKIP_NAMES = frozenset({'bunnyChat', 'bunnyCarrier', 'bunnyLog', 'bunnyChatMascot', 'stageCover'})
SKIP_CLASSES = frozenset({'Spotlight', 'QTipLabel', 'QComboBoxPrivateContainer', 'QMenu'})

# Kinds of models that can see images, for the explanation (in the user's words, not ids).
SEEING_MODELS = 'DeepSeek V4.1 Flash（deepseek-flash）、Claude、OpenAI 的 GPT-4.1 / GPT-4o / GPT-5、Gemini、通义千问 VL（qwen-vl）'
DEEPSEEK_SEEING = frozenset({'deepseek-flash', 'deepseek-v4-flash'})
PASTE_SIDE = 1600            # px, a picture the user pastes keeps more detail (screenshots of text)
PRIVACY_NOTE = ('打开后，兔白需要时会把 2ByteASR 自己窗口的截图（不含桌面和其他程序）发给你在「字幕校对」设置的 AI 服务，'
                '截图里可能有字幕、视频画面和工程名称。每次截图都会在聊天里显示一张小图。截图不会存到电脑上。')


@dataclass
class Capture:
    """What ``look_screen`` hands back: the receipt she reads and the picture that goes with it."""
    receipt: str
    data_url: str
    width: int
    height: int
    thumbnail: object = field(default=None, repr=False)   # QImage for the chat, never sent

    @property
    def placeholder(self) -> str:
        return f'[截图 {self.width}×{self.height}]'


# ------------------------------------------------------------------ can the AI see?
def _known_seeing(provider: str, model: str) -> bool | None:
    """Model names known to take images; None when the name says nothing either way."""
    name = model.casefold()
    provider = provider.casefold()
    if provider == 'deepseek' or name.startswith('deepseek'):
        # 2026-11-17 (user; DeepSeek's pricing page, "Vision" row): deepseek-flash is V4.1-Flash and takes
        # images; the old deepseek-v4-flash name is served by the same model. deepseek-v4-pro: not supported.
        if name in DEEPSEEK_SEEING:
            return True
        return False if name == 'deepseek-v4-pro' else None
    if provider == 'anthropic' or name.startswith('claude'):
        return True
    if provider == 'gemini' or name.startswith('gemini'):
        return True
    if any(mark in name for mark in ('-vl', 'vl-', 'qwen-vl', 'qvq', 'vision', 'omni', 'gpt-4o', 'gpt-4.1', 'gpt-5',
                                     'llava', 'pixtral', 'glm-4v', 'glm-4.5v')):
        return True
    return None


def judge(provider: str, model: str, transport: str, runtime_vision, declared: bool = False) -> tuple[bool, str]:
    """(can she see, why not in plain words). ``runtime_vision``: what the provider's own model list
    says (True / False / None = it does not say); ``declared``: the user marked the model as
    image-capable in the endpoint settings."""
    provider, model, transport = str(provider or ''), str(model or '').strip(), str(transport or '')
    shown = f'{model}' if model else provider or '现在的服务'
    if transport == 'grok_cli':
        return True, ''
    if transport in ('codex_cli', 'antigravity_cli'):
        if runtime_vision is True:
            return True, ''
        return False, f'现在兔白用的是命令行 AI（{shown}），兔白这边还不能把截图交给它。'
    if runtime_vision is True or declared:
        return True, ''
    known = _known_seeing(provider, model)
    if runtime_vision is False or known is False:
        return False, f'现在兔白用的 {shown} 是文字模型，看不了图。'
    if known:
        return True, ''
    return False, f'兔白不确定现在用的 {shown} 能不能看图，为了不白花钱先不发截图。'


def advice(reason: str) -> str:
    """What to tell the user when she cannot see."""
    return (f'{reason}想让兔白看画面，可以在「AI 设置」把「字幕校对」用的服务换成能看图的模型：{SEEING_MODELS}。'
            '注意 AI 断句、校对、翻译也会一起换成它。')


def support(settings) -> tuple[bool, str]:
    """For the AI 兔白 talks through (the 「字幕校对」 service): (can she see, advice when not)."""
    if not settings:
        return False, advice('还没有设置文字 AI。')
    try:
        from ..providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
        selection = GLOBAL_PROVIDER_REGISTRY.selection(dict(settings), stage='polish')
    except Exception as exc:  # noqa: BLE001 - a broken configuration simply means "cannot see"
        return False, advice(f'读不到 AI 设置（{type(exc).__name__}）。')
    runtime = None
    try:
        from ..providers.ai_providers import provider_for_stage
        client = provider_for_stage(dict(settings), 'polish')
        probe = getattr(client, 'runtime_capabilities', None)
        found = probe() if callable(probe) else None
        runtime = found.get('vision') if isinstance(found, dict) else getattr(found, 'vision', None)
    except Exception:  # noqa: BLE001
        runtime = None
    models = settings.get('models', {}) if isinstance(settings, dict) else {}
    declared = models.get('polish_capabilities')
    declared = bool(declared.get('vision')) if isinstance(declared, dict) else 'vision' in (declared or ())
    ok, reason = judge(selection.provider, selection.model, selection.transport, runtime, declared)
    return ok, '' if ok else advice(reason)


# ------------------------------------------------------------------ the picture
def _own_windows(window):
    """2ByteASR's visible top-level windows, bottom to top, without 兔白's own."""
    from PySide6.QtWidgets import QApplication
    tops = [window]
    modal = QApplication.activeModalWidget()
    for top in QApplication.topLevelWidgets():
        if (top is window or not top.isVisible() or top.objectName() in SKIP_NAMES or top.isMinimized()
                or top.metaObject().className() in SKIP_CLASSES or type(top).__name__ in SKIP_CLASSES
                or top.width() < 40 or top.height() < 40):
            continue
        tops.append(top)
    if modal is not None and modal in tops:          # the dialog that must be answered is on top
        tops.remove(modal)
        tops.append(modal)
    return tops


def _grab_without_bunny(widget):
    """``widget.grab()`` with 兔白's own child widgets hidden (where she is not a floating window)."""
    from PySide6.QtWidgets import QWidget
    hidden = [child for child in widget.findChildren(QWidget)
              if child.objectName() in SKIP_NAMES and child.isVisible()]
    for child in hidden:
        child.setVisible(False)
    try:
        return widget.grab()
    finally:
        for child in hidden:
            child.setVisible(True)


def capture(window) -> Capture:
    """One picture of 2ByteASR's windows as they are stacked on screen; GUI thread only."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, Qt
    from PySide6.QtGui import QImage, QPainter
    tops = [top for top in _own_windows(window) if top.isVisible()]
    if not tops:
        raise RuntimeError('2ByteASR 的窗口现在没有显示')
    area = QRect()
    for top in tops:
        area = area.united(QRect(top.mapToGlobal(QPoint(0, 0)), top.size()))
    canvas = QImage(area.size(), QImage.Format.Format_RGB32)
    canvas.fill(Qt.GlobalColor.black)
    painter = QPainter(canvas)
    try:
        for top in tops:
            picture = _grab_without_bunny(top)
            at = top.mapToGlobal(QPoint(0, 0)) - area.topLeft()
            painter.drawPixmap(QRect(at, top.size()), picture)    # logical size, whatever the DPI
    finally:
        painter.end()
    image, url, thumb = _encode(canvas, LONG_SIDE)
    titles = [top.windowTitle() for top in tops[1:] if top.windowTitle()]
    receipt = (f'截好了 2ByteASR 的画面（{image.width()}×{image.height()}，图在这条消息后面）'
               + (f'，上面还开着：' + '、'.join(f'「{title}」' for title in titles[:4]) if titles else '')
               + '。照图回答；看不清的地方就说看不清，不要猜。')
    return Capture(receipt, url, image.width(), image.height(), thumb)


def _encode(image, side: int):
    """(the picture made at most ``side`` px long, its JPEG data URL, the chat's thumbnail)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImage
    if image.hasAlphaChannel():                       # a transparent paste: on white, not black
        flat = QImage(image.size(), QImage.Format.Format_RGB32)
        flat.fill(Qt.GlobalColor.white)
        from PySide6.QtGui import QPainter
        painter = QPainter(flat)
        painter.drawImage(0, 0, image)
        painter.end()
        image = flat
    if max(image.width(), image.height()) > side:
        image = image.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    data = QByteArray()
    stream = QBuffer(data)
    stream.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(stream, 'JPEG', JPEG_QUALITY)
    stream.close()
    url = 'data:image/jpeg;base64,' + base64.b64encode(bytes(data)).decode('ascii')
    thumb = image.scaled(THUMB_SIDE, THUMB_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return image, url, thumb


PASTED_NOTE = '（小兔纸贴了一张图，图在这条消息后面）'


def pasted(image) -> Capture:
    """A picture the user pasted or dropped into the chat (2026-11-17, user): sent with their question."""
    if image is None or image.isNull():
        raise ValueError('没有图片')
    image, url, thumb = _encode(image, PASTE_SIDE)
    return Capture(PASTED_NOTE, url, image.width(), image.height(), thumb)


IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')


def image_from_mime(mime):
    """The picture in a clipboard or drop (an image, or one image file); None when there is none."""
    from PySide6.QtGui import QImage
    if mime is None:
        return None
    if mime.hasImage():
        value = mime.imageData()
        image = value if isinstance(value, QImage) else value.toImage() if hasattr(value, 'toImage') else QImage()
        if not image.isNull():
            return image
    if mime.hasUrls():
        for url in mime.urls():
            path = url.toLocalFile()
            if path and path.casefold().endswith(IMAGE_SUFFIXES):
                image = QImage(path)
                if not image.isNull():
                    return image
    return None


# ------------------------------------------------------------------ messages
def with_images(message: dict, captures) -> dict:
    """The program's tool-result turn with the pictures attached (OpenAI-style content parts)."""
    captures = [item for item in captures or () if isinstance(item, Capture)]
    if not captures:
        return message
    parts = [{'type': 'text', 'text': str(message.get('content') or '')}]
    parts += [{'type': 'image_url', 'image_url': {'url': item.data_url}} for item in captures]
    return {**message, 'content': parts}


def text_only(message: dict) -> dict:
    """A turn safe to keep in the chat history: any picture becomes a short placeholder."""
    content = message.get('content')
    if not isinstance(content, list):
        return message
    words = []
    for part in content:
        if isinstance(part, dict) and part.get('type') == 'text':
            words.append(str(part.get('text') or ''))
        elif isinstance(part, dict) and part.get('type') in ('image_url', 'input_image', 'image'):
            words.append('[截图]')
    return {**message, 'content': '\n'.join(words)}


__all__ = ['Capture', 'DEEPSEEK_SEEING', 'LONG_SIDE', 'PASTED_NOTE', 'PRIVACY_NOTE', 'SEEING_MODELS', 'advice',
           'capture', 'image_from_mime', 'judge', 'pasted', 'support', 'text_only', 'with_images']
